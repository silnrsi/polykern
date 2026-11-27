'''Build PolyKern boundaries from glyph outlines.

Each glyph's polylines are made from the outline's points, on and off the curve,
joined by straight lines. Contours inside other contours are dropped, and the rest are
made bolder by the margin, moving each point outwards along its normal. At the height of
each point the leftmost and rightmost line is found; joining these from point to point
follows the outline.
Each side is then simplified by repeatedly replacing two lines by one wherever the error
triangle between them is below a threshold area.
'''

import bisect
import heapq
import math

from fontTools.pens.basePen import BasePen


def _flat(points, tolerance):
    '''Is every inner control point within tolerance of the chord between the ends?

    With p the point and c the chord, both from the start, the dot product gives where p
    falls along the chord, t = (p . c) / |c|^2. Within the chord (0 <= t <= 1) the distance
    is the cross product divided by |c|; beyond either end it is the distance to that end.
    (A handle can lie on the chord's line but far beyond its end.) Squares are compared,
    so no square root is needed.'''
    (x0, y0), (x1, y1) = points[0], points[-1]
    cx, cy = x1 - x0, y1 - y0               # the chord
    chord2 = cx * cx + cy * cy
    tol2 = tolerance * tolerance
    for x, y in points[1:-1]:
        px, py = x - x0, y - y0
        dot = px * cx + py * cy
        if dot <= 0:                        # before the start (or the ends coincide)
            dist2 = px * px + py * py
        elif dot >= chord2:                 # beyond the end
            dist2 = (x - x1) ** 2 + (y - y1) ** 2
        else:
            cross = px * cy - py * cx
            dist2 = cross * cross / chord2
        if dist2 > tol2:
            return False
    return True


def _split(points):
    '''de Casteljau at t = 1/2: the control points of the two halves of a Bezier curve.'''
    left, right = [points[0]], [points[-1]]
    pts = list(points)
    while len(pts) > 1:
        pts = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:])]
        left.append(pts[0])
        right.append(pts[-1])
    return left, list(reversed(right))


def subdivide(points, tolerance, depth=0):
    '''The control polygon of a Bezier curve (given by all its control points, ends
    included), split in halves until every part is within tolerance of flat. Returns the
    polygon's points after the first. The curve always lies within its control polygon's
    convex hull, so the polygon is outside any outward bulge of the curve.'''
    if depth >= 12 or _flat(points, tolerance):
        return list(points[1:])
    a, b = _split(points)
    return subdivide(a, tolerance, depth + 1) + subdivide(b, tolerance, depth + 1)


class PointsPen(BasePen):
    '''Collects each contour as a list of points. Lines give their end points. Curves give
    their control polygon, split (see subdivide) until it is within tolerance units of the
    curve; with tolerance math.inf, the control points as they are.'''

    def __init__(self, glyphSet, tolerance=1):
        super().__init__(glyphSet)
        self.tolerance = tolerance
        self.contours = []

    def _moveTo(self, p):
        self.contours.append([p])

    def _lineTo(self, p):
        self.contours[-1].append(p)

    def _curve(self, points):
        if self.tolerance is None:
            self.contours[-1].extend(points[1:])
        else:
            self.contours[-1].extend(subdivide(points, self.tolerance))

    def _curveToOne(self, p1, p2, p3):
        self._curve([self._getCurrentPoint(), p1, p2, p3])

    def _qCurveToOne(self, p1, p2):
        self._curve([self._getCurrentPoint(), p1, p2])

    def _closePath(self):
        pass

    def _endPath(self):
        pass


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


def _unit(x, y):
    d = math.hypot(x, y)
    return None if d == 0 else (x / d, y / d)


def embolden(contour, margin, tolerance=1):
    '''Move a closed contour outwards by margin: the outline of the ink plus a disc of
    radius margin, made of straight lines.

    Every edge is shifted out by margin, parallel to itself. At an outward corner the two
    shifted edges are joined round the corner at the margin: by a few lines, each touching
    the circle of radius margin about the corner, so every point is at least margin from
    the ink and none is more than tolerance further out. How many lines depends on how far
    the outline turns there. A small turn needs one point, the ordinary mitre; the end of a
    thin spike is rounded, margin beyond its tip.

    At an inward corner the shifted edges cross inside the emboldened outline; each just
    ends margin out from the corner (where the outline nearly doubles back, as the control
    points of a cubic can, the mitre would be thrown far away). These points lie inside
    the emboldened outline, where the leftmost and rightmost edges never come from.'''
    pts = [p for i, p in enumerate(contour) if p != contour[i - 1]]
    n = len(pts)
    if n < 3:
        return pts
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    side = 1 if area > 0 else -1        # counter-clockwise: outside is on the right
    # The largest turn one mitre point may take: its overshoot, margin (1 / cos(t/2) - 1),
    # must be within tolerance.
    maxTurn = 2 * math.acos(margin / (margin + max(tolerance, 1e-6)))

    def normal(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        d = math.hypot(dx, dy)
        return (side * dy / d, -side * dx / d)

    out = []
    for i in range(n):
        p = pts[i]
        q = pts[(i + 1) % n]
        n1 = normal(pts[i - 1], p)
        n2 = normal(p, q)
        d1 = (p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])
        d2 = (q[0] - p[0], q[1] - p[1])
        cross = (d1[0] * d2[1] - d1[1] * d2[0]) * side
        dot = n1[0] * n2[0] + n1[1] * n2[1]
        turn = math.atan2(abs(n1[0] * n2[1] - n1[1] * n2[0]), dot)    # 0 to pi
        if cross < 0 and turn > 1e-9:
            # an inward corner
            out.append((p[0] + n1[0] * margin, p[1] + n1[1] * margin))
            out.append((p[0] + n2[0] * margin, p[1] + n2[1] * margin))
            continue
        # Outward (or straight): k points, each where two lines touching the circle meet,
        # at angles h, 3h, 5h ... from n1 towards n2, at distance margin / cos(h).
        k = max(1, math.ceil(turn / maxTurn - 1e-9))
        h = turn / (2 * k)
        a1 = math.atan2(n1[1], n1[0])
        nCross = n1[0] * n2[1] - n1[1] * n2[0]
        if abs(nCross) < 1e-9 and dot < 0:
            # The outline turns right back on itself. Go round the far end, the way it was
            # heading: from n1 towards d1.
            nCross = n1[0] * d1[1] - n1[1] * d1[0]
        sign = 1 if nCross >= 0 else -1
        r = margin / math.cos(h)
        for j in range(k):
            a = a1 + sign * (2 * j + 1) * h
            out.append((p[0] + r * math.cos(a), p[1] + r * math.sin(a)))
    return out


def _valueAt(ys, xs, y):
    '''x at height y on the polyline through (xs[i], ys[i]), ys ascending.'''
    import bisect
    j = bisect.bisect_left(ys, y)
    if j < len(ys) and ys[j] == y:
        return xs[j]
    y0, y1, x0, x1 = ys[j - 1], ys[j], xs[j - 1], xs[j]
    return x0 + (y - y0) * (x1 - x0) / (y1 - y0)


def _windowExtreme(ys, xs, i, half, pick):
    '''pick (max or min) of x over heights ys[i] - half to ys[i] + half, clipped to the
    ends of the polyline.'''
    import bisect
    lo, hi = max(ys[0], ys[i] - half), min(ys[-1], ys[i] + half)
    vals = xs[bisect.bisect_left(ys, lo):bisect.bisect_right(ys, hi)]
    return pick(pick(vals), _valueAt(ys, xs, lo), _valueAt(ys, xs, hi))


def closeGaps(points, gap, outward):
    '''Fill the notches in one side of a boundary that are less than gap high, since
    nothing can get into them: the thinnest part of another boundary is twice the margin.

    points: (x, y) with y ascending. outward: max for a right side (notches have smaller
    x), min for a left side. This is a morphological closing along y: the outermost x
    within gap / 2 above or below, then the innermost of those. Points within gap / 2 of
    the ends are left alone, since a notch there is open at the end.'''
    if gap <= 0 or len(points) < 3:
        return points
    inward = min if outward is max else max
    ys = [y for x, y in points]
    xs = [x for x, y in points]
    half = gap / 2
    dilated = [_windowExtreme(ys, xs, i, half, outward) for i in range(len(ys))]
    res = []
    for i, (x, y) in enumerate(points):
        if y - half < ys[0] or y + half > ys[-1]:
            res.append((x, y))
            continue
        closed = _windowExtreme(ys, dilated, i, half, inward)
        if outward(x, closed) != x:     # filled: round outwards to a whole unit
            x = math.ceil(closed) if outward is max else math.floor(closed)
        res.append((x, y))
    return res


def _withinError(pts, i, j, maxError2):
    '''Are all the points between pts[i] and pts[j] within the error (squared) of the line
    from one to the other?'''
    (x0, y0), (x1, y1) = pts[i], pts[j]
    cx, cy = x1 - x0, y1 - y0
    chord2 = cx * cx + cy * cy
    for m in range(i + 1, j):
        px, py = pts[m][0] - x0, pts[m][1] - y0
        dot = px * cx + py * cy
        if chord2 == 0 or dot <= 0:
            d2 = px * px + py * py
        elif dot >= chord2:
            d2 = (pts[m][0] - x1) ** 2 + (pts[m][1] - y1) ** 2
        else:
            cross = px * cy - py * cx
            d2 = cross * cross / chord2
        if d2 > maxError2:
            return False
    return True


def simplifyReach(points, maxError):
    '''Keep the ends, and from each kept point go as far along the line as possible while
    every point passed is within maxError of the new line. This comes within a few
    percent of the fewest points possible, where Douglas-Peucker (which always splits at
    the worst point) keeps noticeably more.'''
    pts = list(points)
    if len(pts) < 3 or maxError <= 0:
        return pts
    e2 = maxError * maxError
    res = [pts[0]]
    i, n = 0, len(pts)
    while i < n - 1:
        j = i + 1
        while j + 1 < n and _withinError(pts, i, j + 1, e2):
            j += 1
        res.append(pts[j])
        i = j
    return res


def _xAtY(line, y):
    '''(least x, greatest x) of the line at height y: a horizontal line gives its ends.'''
    (x0, y0), (x1, y1) = line
    if y0 == y1:
        return min(x0, x1), max(x0, x1)
    x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
    return x, x


def _extremes(lines, ys):
    '''For each height in ys (ascending), (leftmost x, the line it is on) and (rightmost x,
    its line), over the lines that reach that height. Each line only visits the heights it
    spans.'''
    lo = [(math.inf, None)] * len(ys)
    hi = [(-math.inf, None)] * len(ys)
    for line in lines:
        (x0, y0), (x1, y1) = line
        a, b = bisect.bisect_left(ys, min(y0, y1)), bisect.bisect_right(ys, max(y0, y1))
        for k in range(a, b):
            xa, xb = _xAtY(line, ys[k])
            if xa < lo[k][0]:
                lo[k] = (xa, line)
            if xb > hi[k][0]:
                hi[k] = (xb, line)
    return lo, hi


def _crossings(lines, ys, ext, pick):
    '''Heights between consecutive ys where the extreme passes from one line to another,
    found by intersecting the two lines (and again within each part, if a third line
    takes over in between).'''
    res = set()

    def pq(line):                       # x = p + q y
        (x0, y0), (x1, y1) = line
        q = (x1 - x0) / (y1 - y0)
        return x0 - q * y0, q

    for k in range(len(ys) - 1):
        stack = [(ys[k], ext[k][1], ys[k + 1], ext[k + 1][1])]
        while stack:
            ya, la, yb, lb = stack.pop()
            if la is None or lb is None or la is lb or la[0][1] == la[1][1] or \
                    lb[0][1] == lb[1][1]:
                continue
            pa, qa = pq(la)
            pb, qb = pq(lb)
            if qa == qb:
                continue
            y = (pb - pa) / (qa - qb)
            if not (ya < y < yb) or y in res:
                continue
            if not all(min(l[0][1], l[1][1]) <= y <= max(l[0][1], l[1][1]) for l in (la, lb)):
                continue                # they would only cross if extended
            res.add(y)
            # the extreme at y may be a third line: look between it and each end
            best = None
            for line in lines:
                (x0, y0), (x1, y1) = line
                if min(y0, y1) <= y <= max(y0, y1):
                    xs = _xAtY(line, y)
                    x = xs[1] if pick is max else xs[0]
                    if best is None or pick(x, best[0]) != best[0]:
                        best = (x, line)
            xa = pa + qa * y
            if best is not None and best[1] is not la and best[1] is not lb and \
                    pick(best[0], xa) != xa:
                stack += [(ya, la, y, best[1]), (y, best[1], yb, lb)]
    return res


def makeBoundary(glyphSet, name, margin=200, maxArea=None, closeGap=None, tolerance=None,
                 maxError=None):
    '''Return a Boundary for the glyph, or None if it has no outline.

    Each contour is turned into straight lines: curves are replaced by their control
    polygons, split in halves (de Casteljau) until within tolerance units of the curve, so
    the lines are always just outside any outward bulge (tolerance math.inf uses the
    control points as they are).
    Contours inside another contour are dropped, and the rest are made bolder by the
    margin (see embolden; corners are rounded at the margin). At the height of
    every point, the leftmost and rightmost line gives a point on each side, so any part
    the emboldening has closed off drops out. Notches in either side less than closeGap
    high (by default twice the margin) are filled, since another boundary is never thinner
    than that (see closeGaps). The left side runs from bottom to top and the right side
    from top to bottom. Each side is then simplified (see simplifyReach) so that no point
    is more than maxError from it; with maxArea instead, by the older Visvalingam-Whyatt
    method, removing points whose error triangle is below maxArea.

    All values are in font units. By default, tolerance is 2.5% of the margin, maxError
    7.5% and closeGap 200%.'''
    if closeGap is None:
        closeGap = 2 * margin
    if tolerance is None:
        tolerance = 0.025 * margin if margin > 0 else 1
    if maxError is None:
        maxError = 0.075 * margin
    pen = PointsPen(glyphSet, tolerance)
    glyphSet[name].draw(pen)
    contours = [c for c in pen.contours if len(c) > 1]
    contours = [c for i, c in enumerate(contours)
                if not any(j != i and all(_inside(p, d) for p in c)
                           for j, d in enumerate(contours))]
    contours = [embolden(c, margin, tolerance if tolerance is not None else 1) for c in contours]
    contours = [c for c in contours if len(c) > 1]
    if not contours:
        return None
    lines = [(p, q) for c in contours for p, q in zip(c, c[1:] + c[:1]) if p != q]
    # At the height of every point, the leftmost and rightmost x of any line there. Each
    # line only visits the heights it spans.
    ys = sorted({p[1] for c in contours for p in c})
    lo, hi = _extremes(lines, ys)
    # Between two of those heights the leftmost (or rightmost) line can change where two
    # lines cross; add the heights of such crossings, or joining the points would cut the
    # corner inwards.
    ys = sorted(set(ys) | _crossings(lines, ys, lo, min) | _crossings(lines, ys, hi, max))
    lo, hi = _extremes(lines, ys)
    left = [(math.floor(x), y) for (x, _), y in zip(lo, ys)]
    right = [(math.ceil(x), y) for (x, _), y in zip(hi, ys)]
    left = closeGaps(_intYs(left, min), closeGap, min)
    right = closeGaps(_intYs(right, max), closeGap, max)
    if maxArea is not None:
        left, right = simplify(left, maxArea), simplify(right, maxArea)
    else:
        # simplify each side in its own order: left bottom to top, right top to bottom
        left = simplifyReach(left, maxError)
        right = list(reversed(simplifyReach(list(reversed(right)), maxError)))
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


def boundaryOutline(boundary):
    '''The points of an open contour for the boundary: up the left side from the bottom,
    then down the right side, with no line back from the last point to the first.'''
    return list(boundary.left) + list(boundary.right)


def scriptGlyphs(font, script='Arab', withOutlines=True):
    '''The glyphs a script can reach through GSUB, in glyph order.

    font: a compiled TTFont (it is changed: GSUB is pruned to the script).
    script: an ISO 15924 code, such as Arab. The characters are those in the cmap whose
        Unicode script extensions include it, and Common or Inherited characters in one
        of the script's own blocks (such as U+06DD END OF AYAH in Arabic). The GSUB
        closure follows only the script's OpenType script tags (such as arab).
    withOutlines: if true, glyphs with no outline (spaces and the like) are left out,
        since they need no boundary. .notdef is always left out.
    '''
    from fontTools import subset, unicodedata
    from fontTools.pens.boundsPen import BoundsPen
    cmap = font.getBestCmap()
    blockName = unicodedata.script_name(script)

    def wanted(u):
        scx = unicodedata.script_extension(u)
        if script in scx:
            return True
        return scx <= {'Zyyy', 'Zinh'} and unicodedata.block(u).startswith(blockName)

    unicodes = [u for u in cmap if wanted(u)]
    opts = subset.Options()
    opts.layout_features = ['*']
    opts.layout_scripts = unicodedata.ot_tags_from_script(script)
    opts.notdef_outline = False
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=unicodes)
    sub._prune_pre_subset(font)
    sub._closure_glyphs(font)
    glyphs = set(sub.glyphs_retained) - {'.notdef'}
    if withOutlines:
        glyphSet = font.getGlyphSet()
        def hasOutline(g):
            pen = BoundsPen(glyphSet)
            glyphSet[g].draw(pen)
            return pen.bounds is not None
        glyphs = {g for g in glyphs if hasOutline(g)}
    return [g for g in font.getGlyphOrder() if g in glyphs]


def mapToUfo(font, glyphs, ufo, tolerance=2, exclude=r'^_'):
    '''Find the UFO glyphs that correspond to glyphs of a compiled font that was not built
    with the UFO's glyph names. A glyph whose name is in the UFO is that glyph. Otherwise
    it matches the UFO glyphs whose outline bounds are within tolerance units (allowing
    for curves converted to quadratics), preferring those with the same advance; glyphs
    drawn the same all match. UFO glyphs that are not exported (public.skipExportGlyphs,
    and names matching the exclude regular expression, by default component glyphs whose
    names start with _) are never matched.

    Returns (UFO glyph names in the UFO's glyph order, font glyphs with no match).'''
    import re
    from fontTools.pens.boundsPen import BoundsPen
    skip = set(ufo.lib.get('public.skipExportGlyphs', []))
    excludeRe = re.compile(exclude) if exclude else None
    layer = ufo.layers.defaultLayer
    candidates = []                     # (bounds, width, name)
    for n in ufo.keys():
        if n in skip or (excludeRe and excludeRe.search(n)):
            continue
        pen = BoundsPen(layer)
        ufo[n].draw(pen)
        if pen.bounds is not None:
            candidates.append((pen.bounds, round(ufo[n].width), n))
    glyphSet = font.getGlyphSet()
    found, missing = set(), []
    for g in glyphs:
        if g in ufo and g not in skip and not (excludeRe and excludeRe.search(g)):
            found.add(g)
            continue
        pen = BoundsPen(glyphSet)
        glyphSet[g].draw(pen)
        if pen.bounds is None:
            missing.append(g)
            continue
        close = [(w, n) for b, w, n in candidates
                 if all(abs(x - y) <= tolerance for x, y in zip(b, pen.bounds))]
        width = round(glyphSet[g].width)
        names = [n for w, n in close if w == width] or [n for w, n in close]
        if names:
            found.update(names)
        else:
            missing.append(g)
    order = list(ufo.glyphOrder) or sorted(ufo.keys())
    return [n for n in order if n in found] + sorted(found - set(order)), missing
