#!/usr/bin/env python3
'''A direct transcription of the PolyKern algorithm in documentation/PolyKernLookup.md.

Step numbers in the comments refer to the steps in that document. The aim is to follow
the description, not to be fast.
'''

IGNORED, MARK, ATTACHED, SPACE, KERNABLE, BARRIER = range(6)
CATNAMES = ['ignored', 'mark', 'attached', 'space', 'kernable', 'barrier']


class Glyph:
    '''One glyph in the run. adv is the advance, xoff and yoff the resolved offsets.
    bnd is a Boundary (see makepolylines) or None.'''

    def __init__(self, name, cat, bnd, adv, xoff, yoff):
        self.name = name
        self.cat = cat
        self.bnd = bnd
        self.adv = adv
        self.xoff = xoff
        self.yoff = yoff
        self.origAdv = adv              # the advance before PolyKern changed it
        self.cluster = None             # index of the first glyph of its cluster

    def hasBoundary(self):
        return self.cat != IGNORED and self.bnd is not None


def positions(glyphs, rtl):
    '''x positions of the glyphs in logical order, from their advances and offsets.
    In left to right text a glyph's advance runs right, to the next glyph.
    In right to left text it runs right, to the glyph logically before it.'''
    xs = []
    pen = 0
    for g in glyphs:
        if rtl:
            pen -= g.adv
            xs.append(pen + g.xoff)
        else:
            xs.append(pen + g.xoff)
            pen += g.adv
    return xs


def _divUp(a, b):
    if b < 0:
        a, b = -a, -b
    return -((-a) // b)


def _divDown(a, b):
    if b < 0:
        a, b = -a, -b
    return a // b


def separation(R, L, dx, dy):
    '''Separation of two glyphs. R is the right polyline of the left glyph, top to
    bottom. L is the left polyline of the right glyph, bottom to top. Returns None
    for none.'''
    nR = len(R)
    nL = len(L)
    # Step 1
    top = min(R[0][1], L[nL - 1][1] + dy)
    bottom = max(R[nR - 1][1], L[0][1] + dy)
    # Step 2
    if top < bottom:
        return None
    # Step 3
    gap = None
    y = top
    i = 0           # current point of R
    j = nL - 1      # current point of L
    while True:
        # Step 4
        while R[i + 1][1] > y:
            i += 1
        # Step 5
        while L[j - 1][1] + dy > y:
            j -= 1
        # Step 6
        if R[i][1] == y:
            leftx = R[i][0]
        else:
            leftx = R[i][0] + _divUp((y - R[i][1]) * (R[i + 1][0] - R[i][0]),
                                     R[i + 1][1] - R[i][1])
        k = i + 1
        while k < nR and R[k][1] == y:
            leftx = max(leftx, R[k][0])
            k += 1
        # Step 7
        if L[j][1] + dy == y:
            rightx = L[j][0] + dx
        else:
            rightx = L[j][0] + dx + _divDown((y - L[j][1] - dy) * (L[j - 1][0] - L[j][0]),
                                             L[j - 1][1] - L[j][1])
        m = j - 1
        while m >= 0 and L[m][1] + dy == y:
            rightx = min(rightx, L[m][0] + dx)
            m -= 1
        # Step 8
        if gap is None or rightx - leftx < gap:
            gap = rightx - leftx
        # Step 9
        if y == bottom:
            return gap
        # Step 10
        y = max(bottom, R[k][1], L[m][1] + dy)


def startsCluster(glyphs, i):
    '''Does glyph i start a cluster? (A kernable base, or an attached base whose
    previous glyph is not a mark, an attached base, a kernable base or ignored.)'''
    c = glyphs[i].cat
    if c == KERNABLE:
        return True
    if c != ATTACHED:
        return False
    return i == 0 or glyphs[i - 1].cat not in (MARK, ATTACHED, KERNABLE, IGNORED)


def calcShift(glyphs, first, last, box, reaches, rtl, stats, stop=True):
    '''Calculate the shift for the cluster glyphs[first..last] against the glyphs before
    it, given its box (left, bottom, right, top) and the list of reaches. Changes nothing. Returns
    (shift, which cluster set it), where the shift is a kern (positive means more space)
    or None. For testing: stop=False never stops the walk back early.'''
    xs = positions(glyphs, rtl)
    F = [f for f in range(first, last + 1) if glyphs[f].hasBoundary()]
    # Step 1
    shift = None
    extra = 0
    current = len(reaches)          # the current reach: just after the last entry
    bindDepth = None
    # Step 2
    if box is None:
        return None, None
    near = box[2] if rtl else box[0]
    # Step 3
    e = first - 1
    while True:
        # Step 4
        if e < 0 or glyphs[e].cat == BARRIER:
            break
        stats['walked'] += 1
        eg = glyphs[e]
        # Step 5
        if eg.cat == SPACE:
            extra += eg.origAdv
        else:
            # Step 6
            if eg.hasBoundary():
                eb = eg.bnd.bbox
                ebox = (xs[e] + eb[0], eg.yoff + eb[1], xs[e] + eb[2], eg.yoff + eb[3])
                todo = F
                # Step 6.1
                if ebox[1] > box[3] or ebox[3] < box[1]:
                    todo = []
                # Step 6.2
                gap = ebox[0] - box[2] if rtl else box[0] - ebox[2]
                if shift is not None and extra - gap <= shift:
                    todo = []
                stats['clusterSkips'] = stats.get('clusterSkips', 0) + (not todo)
                # Step 6.3
                for f in todo:
                    # Step 6.3.1
                    if rtl:
                        l, r = f, e
                    else:
                        l, r = e, f
                    lg, rg = glyphs[l], glyphs[r]
                    # Step 6.3.2
                    dx = xs[r] - xs[l]
                    dy = rg.yoff - lg.yoff
                    # Step 6.3.3
                    lb, rb = lg.bnd.bbox, rg.bnd.bbox
                    if rb[1] + dy > lb[3] or rb[3] + dy < lb[1]:
                        continue
                    # Step 6.3.4
                    if shift is not None and extra - (rb[0] + dx - lb[2]) <= shift:
                        continue
                    # Step 6.3.5
                    stats['separations'] += 1
                    s = separation(lg.bnd.right, rg.bnd.left, dx, dy)
                    # Step 6.3.6
                    if s is not None:
                        s = extra - s
                        if shift is None or s > shift:
                            shift = s
                            bindDepth = len(reaches) - current + 1
            # Step 7
            if startsCluster(glyphs, e):
                # Step 7.1
                current -= 1
                if stop:
                    reach = reaches[current]
                    # Step 7.2
                    if reach is None:
                        break
                    # Step 7.3
                    gap = reach - near if rtl else near - reach
                    # Step 7.4
                    if extra - gap <= (0 if shift is None else shift):
                        break
        # Step 8
        e -= 1
    depth = len(reaches) - current
    stats['walkDepth'][depth] = stats['walkDepth'].get(depth, 0) + 1
    # Step 9
    return shift, bindDepth


def orderRule(glyphs, first, last, prev, rtl, shift):
    '''Experimental alternative to main step 8.1: limit F by the start of the previous
    cluster's polyline bounding box instead of its width. Returns the new shift.'''
    xs = positions(glyphs, rtl)
    F = [f for f in range(first, last + 1) if glyphs[f].hasBoundary()]
    P = [k for k in range(prev[0], prev[1] + 1) if glyphs[k].hasBoundary()]
    if not F or not P:
        return shift
    if rtl:
        limit = (max(xs[f] + glyphs[f].bnd.bbox[2] for f in F)
                 - max(xs[k] + glyphs[k].bnd.bbox[2] for k in P))
    else:
        limit = (min(xs[k] + glyphs[k].bnd.bbox[0] for k in P)
                 - min(xs[f] + glyphs[f].bnd.bbox[0] for f in F))
    return max(shift, limit)


def polykern(glyphs, rtl, stop=True, cap=True, order=False):
    '''Apply PolyKern to a list of Glyph in logical order. Changes the advances.
    Returns statistics. For testing: stop=False never stops the walk back early,
    cap=False leaves out step 8.1, and order=True uses an alternative to step 8.1.'''
    stats = {'walked': 0, 'separations': 0, 'clusters': 0, 'kerned': 0,
             'walkDepth': {}, 'bindDepth': {}}
    # Step 1
    reach = None
    reaches = []
    prev = None
    i = 0
    while True:
        # Step 2
        if i >= len(glyphs):
            return stats
        g = glyphs[i]
        # Step 3
        if g.cat == SPACE:
            if reach is not None:
                reach += -g.origAdv if rtl else g.origAdv
            i += 1
            continue
        # Step 4
        if g.cat == BARRIER:
            reach = None
            prev = None
            i += 1
            continue
        # Step 5
        if g.cat in (MARK, IGNORED) or (g.cat == ATTACHED and i > 0
                                        and glyphs[i - 1].cat in (MARK, IGNORED)):
            i += 1
            continue
        # Step 6
        xs = positions(glyphs, rtl)
        # Step 6.1
        last = i
        width = 0
        box = None
        while True:
            # Step 6.2
            width += glyphs[last].origAdv
            if glyphs[last].hasBoundary():
                b = glyphs[last].bnd.bbox
                gbox = (xs[last] + b[0], glyphs[last].yoff + b[1],
                        xs[last] + b[2], glyphs[last].yoff + b[3])
                box = gbox if box is None else (min(box[0], gbox[0]), min(box[1], gbox[1]),
                                                max(box[2], gbox[2]), max(box[3], gbox[3]))
            # Step 6.3
            if last + 1 < len(glyphs) and glyphs[last + 1].cat in (MARK, ATTACHED, IGNORED):
                last += 1
            else:
                break
        for k in range(i, last + 1):
            glyphs[k].cluster = i
        stats['clusters'] += 1
        # Step 7
        shift, bindDepth = calcShift(glyphs, i, last, box, reaches, rtl, stats, stop)
        # Step 8
        if shift is not None:
            # Step 8.1
            if prev is not None and cap and shift < -prev[2]:
                shift = -prev[2]
                bindDepth = 'cap'
            if prev is not None and order:
                limited = orderRule(glyphs, i, last, prev, rtl, shift)
                if limited != shift:
                    shift, bindDepth = limited, 'order'
            # Step 8.2
            if glyphs[i - 1].cat == SPACE or not rtl:
                glyphs[i - 1].adv += shift
            else:
                glyphs[i].adv += shift
            stats['kerned'] += 1
            stats['bindDepth'][bindDepth] = stats['bindDepth'].get(bindDepth, 0) + 1
        # Step 9
        reaches.append(reach)
        # Step 10
        if box is not None:
            move = shift or 0
            if rtl:
                far = box[0] - move
                reach = far if reach is None else min(reach, far)
            else:
                far = box[2] + move
                reach = far if reach is None else max(reach, far)
        # Step 11
        prev = (i, last, width)
        # Step 12
        i = last + 1


def worstOverlap(glyphs, rtl):
    '''Check the result: the smallest gap, less the spaces between, over every pair of
    glyphs in different clusters with no barrier between them. Returns (gap, a, b).'''
    xs = positions(glyphs, rtl)
    worst = (None, None, None)
    for b in range(len(glyphs)):
        for a in range(b - 1, -1, -1):
            if glyphs[a].cat == BARRIER:
                break
            if not glyphs[a].hasBoundary() or not glyphs[b].hasBoundary():
                continue
            if glyphs[a].cluster is not None and glyphs[a].cluster == glyphs[b].cluster:
                continue
            extra = sum(glyphs[k].origAdv for k in range(a + 1, b) if glyphs[k].cat == SPACE)
            l, r = (b, a) if rtl else (a, b)
            s = separation(glyphs[l].bnd.right, glyphs[r].bnd.left, xs[r] - xs[l],
                           glyphs[r].yoff - glyphs[l].yoff)
            if s is not None and (worst[0] is None or s - extra < worst[0]):
                worst = (s - extra, a, b)
    return worst
