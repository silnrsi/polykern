#!/usr/bin/env python3
'''Build PolyKern boundaries from glyph outlines.

Each glyph's polylines are made from the outline's points, on and off the curve,
joined by straight lines. Contours inside other contours are dropped, and the rest are
made bolder by the margin, moving each point outwards along its normal. At the height of
each point the leftmost and rightmost line is found; joining these from point to point
follows the outline.
Each side is then simplified by repeatedly replacing two lines by one wherever the error
triangle between them is below a threshold area.
'''

import heapq
import math

from fontTools.pens.basePen import BasePen


class PointsPen(BasePen):
    '''Collects each contour as the list of its points, on and off the curve, in order.'''

    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.contours = []

    def moveTo(self, p):
        self.contours.append([p])

    def lineTo(self, p):
        self.contours[-1].append(p)

    def qCurveTo(self, *points):
        if points[-1] is None:          # a contour with no on-curve points
            self.contours.append(list(points[:-1]))
        else:
            self.contours[-1].extend(points)

    curveTo = qCurveTo

    def closePath(self):
        pass

    endPath = closePath


def _inside(p, poly):
    '''Is point p inside the polygon?'''
    x, y = p
    res = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            res = not res
    return res


class FlattenPen(BasePen):
    '''Collects a glyph outline, with its curves flattened, as a list of straight edges
    ((x0, y0), (x1, y1)). Used to check the actual ink.'''

    def __init__(self, glyphSet, curveSteps=8):
        super().__init__(glyphSet)
        self.edges = []
        self.curveSteps = curveSteps
        self.start = self.current = None

    def _moveTo(self, p):
        self.start = self.current = p

    def _lineTo(self, p):
        self.edges.append((self.current, p))
        self.current = p

    def _curveToOne(self, p1, p2, p3):
        p0 = self.current
        for i in range(1, self.curveSteps + 1):
            t = i / self.curveSteps
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            self._lineTo((x, y))

    def _qCurveToOne(self, p1, p2):
        p0 = self.current
        for i in range(1, self.curveSteps + 1):
            t = i / self.curveSteps
            mt = 1 - t
            x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
            y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
            self._lineTo((x, y))

    def _closePath(self):
        if self.current != self.start:
            self._lineTo(self.start)

    _endPath = _closePath


class Boundary:
    '''A PolyKern boundary: left polyline bottom to top, right polyline top to bottom,
    and the bounding box (xmin, ymin, xmax, ymax) of both.'''

    def __init__(self, left, right):
        self.left = left
        self.right = right
        pts = left + right
        self.bbox = (min(p[0] for p in pts), min(p[1] for p in pts),
                     max(p[0] for p in pts), max(p[1] for p in pts))


def _edgeExtent(edge, ylo, yhi):
    '''The x range of the part of an edge that lies between ylo and yhi, or None.'''
    (x0, y0), (x1, y1) = edge
    if y0 > y1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    if y1 < ylo or y0 > yhi:
        return None
    if y0 == y1:
        return (min(x0, x1), max(x0, x1))
    xs = []
    for y in (max(y0, ylo), min(y1, yhi)):
        xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return (min(xs), max(xs))


def _inkExtents(edges, ys, margin):
    '''For each y, the leftmost and rightmost edge within the margin of it vertically,
    pushed out by the margin. None where there is nothing.'''
    lefts = []
    rights = []
    for y in ys:
        xl = xr = None
        for e in edges:
            r = _edgeExtent(e, y - margin, y + margin)
            if r is None:
                continue
            xl = r[0] if xl is None else min(xl, r[0])
            xr = r[1] if xr is None else max(xr, r[1])
        lefts.append(None if xl is None else xl - margin)
        rights.append(None if xr is None else xr + margin)
    return lefts, rights


def _triangleArea(a, b, c):
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2


def simplify(points, maxArea):
    '''Visvalingam-Whyatt: repeatedly replace two lines by one, removing the point
    between them whose error triangle is smallest, while that area is below maxArea.'''
    pts = list(points)
    n = len(pts)
    prev = list(range(-1, n - 1))
    nxt = list(range(1, n + 1))
    alive = [True] * n
    heap = [(_triangleArea(pts[i - 1], pts[i], pts[i + 1]), i) for i in range(1, n - 1)]
    heapq.heapify(heap)
    area = {i: a for a, i in heap}
    while heap:
        a, i = heapq.heappop(heap)
        if not alive[i] or area[i] != a:
            continue
        if a >= maxArea:
            break
        alive[i] = False
        p, q = prev[i], nxt[i]
        nxt[p] = q
        prev[q] = p
        for k in (p, q):
            if 0 < k < n - 1:
                area[k] = _triangleArea(pts[prev[k]], pts[k], pts[nxt[k]])
                heapq.heappush(heap, (area[k], k))
    return [pt for pt, keep in zip(pts, alive) if keep]


def embolden(contour, margin, miterLimit=4):
    '''Move each point of a closed contour outwards by margin, along the line bisecting
    the outward normals of its two edges, so that both edges end up margin further out
    (as FreeType's FT_Outline_Embolden does). Very sharp corners are limited to
    miterLimit times the margin.'''
    pts = [p for i, p in enumerate(contour) if p != contour[i - 1]]
    n = len(pts)
    if n < 3:
        return pts
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    side = 1 if area > 0 else -1        # counter-clockwise: outside is on the right

    def normal(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        d = math.hypot(dx, dy)
        return (side * dy / d, -side * dx / d)

    out = []
    for i in range(n):
        n1 = normal(pts[i - 1], pts[i])
        n2 = normal(pts[i], pts[(i + 1) % n])
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        b2 = bx * bx + by * by
        if b2 < 1e-9:                   # the outline doubles back on itself
            bx, by, scale = n1[0], n1[1], margin
        else:
            scale = min(2 * margin / b2, miterLimit * margin / math.sqrt(b2))
        out.append((pts[i][0] + bx * scale, pts[i][1] + by * scale))
    return out


def makeBoundary(glyphSet, name, margin=200, maxArea=1000):
    '''Return a Boundary for the glyph, or None if it has no outline.

    Each contour's points, on and off the curve, are joined in order by straight lines.
    Contours inside another contour are dropped, and the rest are made bolder by the
    margin (see embolden). At the height of every point, the leftmost and rightmost line
    gives a point on each side. The left side runs from bottom to top and the right side
    from top to bottom. Each side is then simplified, replacing two lines by one wherever
    the error triangle is below maxArea.'''
    pen = PointsPen(glyphSet)
    glyphSet[name].draw(pen)
    contours = [c for c in pen.contours if len(c) > 1]
    contours = [c for i, c in enumerate(contours)
                if not any(j != i and all(_inside(p, d) for p in c)
                           for j, d in enumerate(contours))]
    contours = [embolden(c, margin) for c in contours]
    contours = [c for c in contours if len(c) > 1]
    if not contours:
        return None
    lines = [(p, q) for c in contours for p, q in zip(c, c[1:] + c[:1]) if p != q]
    left = []
    right = []
    for y in sorted({p[1] for c in contours for p in c}):
        xs = []
        for (x0, y0), (x1, y1) in lines:
            if min(y0, y1) <= y <= max(y0, y1):
                xs += [x0, x1] if y0 == y1 else [x0 + (y - y0) * (x1 - x0) / (y1 - y0)]
        left.append((math.floor(min(xs)), y))
        right.append((math.ceil(max(xs)), y))
    left = simplify(_intYs(left, min), maxArea)
    right = simplify(_intYs(right, max), maxArea)
    return Boundary(left, list(reversed(right)))


def _intYs(points, outer):
    '''Round the y values to integers (outwards at the ends), keeping the outer x where
    two points end up at the same y.'''
    res = {}
    last = len(points) - 1
    for i, (x, y) in enumerate(points):
        iy = math.floor(y) if i == 0 else math.ceil(y) if i == last else round(y)
        res[iy] = x if iy not in res else outer(res[iy], x)
    return [(x, y) for y, x in sorted(res.items())]


def arabicGlyphs(font):
    '''All glyphs reachable from Arabic characters through GSUB, as a set of names.'''
    from fontTools import subset
    arabic = [u for r in ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                          (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)) for u in range(r[0], r[1] + 1)]
    cmap = font.getBestCmap()
    unicodes = [u for u in arabic if u in cmap]
    opts = subset.Options()
    opts.layout_features = ['*']
    opts.notdef_outline = False
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=unicodes)
    sub._closure_glyphs(font)
    return set(sub.glyphs_retained) - {".notdef"}


def makeAllBoundaries(font, margin=200, glyphs=None, maxArea=1000):
    '''Return {glyph name: Boundary} for all Arabic glyphs with outlines.'''
    if glyphs is None:
        glyphs = arabicGlyphs(font)
    glyphSet = font.getGlyphSet()
    res = {}
    for g in sorted(glyphs):
        b = makeBoundary(glyphSet, g, margin, maxArea)
        if b is not None:
            res[g] = b
    return res
