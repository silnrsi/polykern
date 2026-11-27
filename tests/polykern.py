#!/usr/bin/env python3
'''A direct transcription of the PolyKern algorithm in documentation/PolyKernLookup.md.

Step numbers in the comments refer to the steps in that document. The aim is to follow
the description, not to be fast, and to be written so that it carries over directly to
C or C++: plain loops over indices, a flag beside any value that may be "none", and no
lists built on the fly. The statistics gathered for testing are marked; an engine would
leave them out.
'''

# The glyph categories (see "Glyph categories" in the specification)
IGNORED, ATTACHED, SPACE, KERNABLE, BARRIER = range(5)
CATNAMES = ['ignored', 'attached', 'space', 'kernable', 'barrier']

# Indexes into a point (x, y) and a bounding box (xMin, yMin, xMax, yMax). A boundary's
# bbox is its minPoint and maxPoint.
X, Y = 0, 1
XMIN, YMIN, XMAX, YMAX = 0, 1, 2, 3


class Glyph:
    '''One glyph in the run, as the shaper has positioned it.'''

    def __init__(self, name, cat, bnd, adv, xoff, yoff):
        self.name = name            # glyph name (for reports only)
        self.cat = cat              # its glyph category, one of IGNORED .. BARRIER
        self.bnd = bnd              # its boundary: left polyline (points bottom to top),
                                    # right polyline (top to bottom) and bbox; or None
        self.adv = adv              # its advance; PolyKern changes this
        self.xoff = xoff            # its resolved x offset (from mark and cursive attachment)
        self.yoff = yoff            # its resolved y offset; this is its y position
        self.origAdv = adv          # its original advance: before PolyKern changed it
        self.cluster = None         # for testing: index of the first glyph of its cluster

    def hasBoundary(self):
        '''"Has a boundary and is not ignored", as the algorithm says throughout.'''
        return self.cat != IGNORED and self.bnd is not None


def positions(glyphs, rtl):
    '''x positions of the glyphs in logical order, from their advances and offsets.
    In left to right text a glyph's advance runs right, to the next glyph.
    In right to left text it runs right, to the glyph logically before it.'''
    n = len(glyphs)                 # number of glyphs in the run
    xs = [0] * n                    # xs[i] is the x position of glyph i
    pen = 0                         # the pen position as the advances are added up
    for i in range(n):
        if rtl:
            pen -= glyphs[i].adv
            xs[i] = pen + glyphs[i].xoff
        else:
            xs[i] = pen + glyphs[i].xoff
            pen += glyphs[i].adv
    return xs


def divUp(a, b):
    '''a / b rounded up, for b != 0. Used for the left x, so errors only ever make the
    glyphs further apart.'''
    if b < 0:
        a = -a
        b = -b
    return -((-a) // b)


def divDown(a, b):
    '''a / b rounded down, for b != 0. Used for the right x.'''
    if b < 0:
        a = -a
        b = -b
    return a // b


def separation(R, L, dx, dy):
    '''Separation of two glyphs ("Separation of two glyphs" in the specification).
    R is the right polyline of the left glyph, top to bottom. L is the left polyline of
    the right glyph, bottom to top, and is treated as moved by dx and dy. Returns None
    for none (in C: a bool result and an out value).'''
    nR = len(R)                     # number of points in R
    nL = len(L)                     # number of points in L
    # Step 1
    top = min(R[0][Y], L[nL - 1][Y] + dy)           # the top of the shared y range
    bottom = max(R[nR - 1][Y], L[0][Y] + dy)        # the bottom of the shared y range
    # Step 2
    if top < bottom:
        return None
    # Step 3
    haveGap = False                 # whether gap has a value yet (the gap is "none")
    gap = 0                         # the gap: the smallest right x minus left x so far
    y = top                         # y: the height at which the gap is being measured
    i = 0                           # index of the current point of R
    j = nL - 1                      # index of the current point of L
    while True:
        # Step 4
        while R[i + 1][Y] > y:
            i += 1
        # Step 5
        while L[j - 1][Y] + dy > y:
            j -= 1
        # Step 6
        if R[i][Y] == y:
            leftx = R[i][X]         # the left x: the x of R at y
        else:
            x1 = R[i][X]            # (x1, y1): the current point of R
            y1 = R[i][Y]
            x2 = R[i + 1][X]        # (x2, y2): the point after it, below y
            y2 = R[i + 1][Y]
            leftx = x1 + divUp((y - y1) * (x2 - x1), y2 - y1)
        k = i + 1                   # steps through further points of R at y (step 6.3)
        while k < nR and R[k][Y] == y:
            leftx = max(leftx, R[k][X])
            k += 1
        # Step 7
        if L[j][Y] + dy == y:
            rightx = L[j][X] + dx   # the right x: the x of L at y
        else:
            x1 = L[j][X] + dx       # (x1, y1): the current point of L, moved
            y1 = L[j][Y] + dy
            x2 = L[j - 1][X] + dx   # (x2, y2): the point before it, below y, moved
            y2 = L[j - 1][Y] + dy
            rightx = x1 + divDown((y - y1) * (x2 - x1), y2 - y1)
        m = j - 1                   # steps through further points of L at y (step 7.3)
        while m >= 0 and L[m][Y] + dy == y:
            rightx = min(rightx, L[m][X] + dx)
            m -= 1
        # Step 8
        if not haveGap or rightx - leftx < gap:
            gap = rightx - leftx
            haveGap = True
        # Step 9
        if y == bottom:
            return gap
        # Step 10 (k and m are now the next points below y)
        y = max(bottom, max(R[k][Y], L[m][Y] + dy))


def startsCluster(glyphs, i):
    '''Does glyph i start a cluster? A kernable base does; so does an attached glyph
    with a boundary whose previous glyph is not attached, a kernable base or ignored.'''
    c = glyphs[i].cat               # the category of glyph i
    if c == KERNABLE:
        return True
    if c != ATTACHED or not glyphs[i].hasBoundary():
        return False
    if i == 0:
        return True
    p = glyphs[i - 1].cat           # the category of the glyph before it
    return p != ATTACHED and p != KERNABLE and p != IGNORED


class Run:
    '''The working state while PolyKern runs over a run of glyphs. In C this would be a
    struct, with the arrays sized to the number of glyphs.'''

    def __init__(self, glyphs, rtl):
        n = len(glyphs)                     # number of glyphs in the run
        self.glyphs = glyphs                # the glyphs, in logical order
        self.rtl = rtl                      # whether the text is right to left
        self.xs = positions(glyphs, rtl)    # glyph x positions, kept up to date as
                                            # advances change (see moveFrom)
        # The list of reaches (main step 9): one entry per cluster, holding the reach as
        # it was just before that cluster. An entry can be none, hence the flags.
        self.numReaches = 0                 # number of entries in the list so far
        self.reachSet = [False] * n         # reachSet[k]: whether entry k is not none
        self.reachVal = [0] * n             # reachVal[k]: the value of entry k
        # Testing statistics
        self.stats = {'walked': 0, 'separations': 0, 'clusters': 0, 'kerned': 0,
                      'walkDepth': {}, 'bindDepth': {}, 'clusterSkips': 0}

    def moveFrom(self, k, delta):
        '''Glyph k and everything after it has moved by delta in x.'''
        for i in range(k, len(self.glyphs)):
            self.xs[i] += delta


def calcShift(run, first, last, boxXMin, boxYMin, boxXMax, boxYMax, stop=True):
    '''Calculating the shift for F ("Calculating the shift" in the specification).
    F is the cluster glyphs[first..last]; its box is given. Changes nothing. Returns
    (haveShift, shift, bindDepth): the shift is a kern (positive means more space).
    bindDepth is for testing: which cluster back set the shift. For testing, stop=False
    never stops the walk early.'''
    glyphs = run.glyphs             # the glyphs in logical order
    xs = run.xs                     # their current x positions
    rtl = run.rtl                   # whether the text is right to left
    stats = run.stats               # testing statistics
    # Step 1
    haveShift = False               # whether the shift has a value yet (it is "none")
    shift = 0                       # the shift: the least kern F needs, so far
    extra = 0                       # the extra separation: the original advances of the
                                    # spaces passed on the walk back so far
    current = run.numReaches        # the current reach: index into the list of reaches,
                                    # starting just after its last entry
    bindDepth = 0                   # testing: how many clusters back set the shift
    # Step 2 (the caller only calls this when F has a box)
    # Step 3
    e = first - 1                   # index of the earlier glyph, walking back from F
    while True:
        # Step 4
        if e < 0 or glyphs[e].cat == BARRIER:
            break
        stats['walked'] += 1
        eg = glyphs[e]              # the earlier glyph
        # Step 5
        if eg.cat == SPACE:
            extra += eg.origAdv
        else:
            # Step 6
            if eg.hasBoundary():
                eb = eg.bnd.bbox    # the earlier glyph's own box (its minPoint, maxPoint)
                eXMin = xs[e] + eb[XMIN]        # the earlier glyph's box, moved by its
                eYMin = eg.yoff + eb[YMIN]      # position (step 6.1)
                eXMax = xs[e] + eb[XMAX]
                eYMax = eg.yoff + eb[YMAX]
                compare = True      # whether to compare it with each glyph of F (step 6.3)
                # Step 6.1
                if eYMin > boxYMax or eYMax < boxYMin:
                    compare = False
                # Step 6.2
                if rtl:
                    gap = eXMin - boxXMax       # the gap between the earlier glyph's box
                else:                           # and F's box, in x
                    gap = boxXMin - eXMax
                if haveShift and extra - gap <= shift:
                    compare = False
                if not compare:
                    stats['clusterSkips'] += 1
                # Step 6.3
                f = first           # index of the glyph of F being compared
                while compare and f <= last:
                    if glyphs[f].hasBoundary():
                        # Step 6.3.1
                        if rtl:
                            li = f              # index of the left glyph
                            ri = e              # index of the right glyph
                        else:
                            li = e
                            ri = f
                        lg = glyphs[li]         # the left glyph
                        rg = glyphs[ri]         # the right glyph
                        # Step 6.3.2
                        dx = xs[ri] - xs[li]    # dx, dy: the right glyph's position
                        dy = rg.yoff - lg.yoff  # relative to the left glyph's
                        lb = lg.bnd.bbox        # the left glyph's own box
                        rb = rg.bnd.bbox        # the right glyph's own box
                        # Step 6.3.3, then 6.3.4
                        if (rb[YMIN] + dy <= lb[YMAX] and rb[YMAX] + dy >= lb[YMIN]
                                and not (haveShift
                                         and extra - (rb[XMIN] + dx - lb[XMAX]) <= shift)):
                            # Step 6.3.5
                            stats['separations'] += 1
                            # s: the separation, then the shift it needs (step 6.3.6)
                            s = separation(lg.bnd.right, rg.bnd.left, dx, dy)
                            # Step 6.3.6
                            if s is not None:
                                s = extra - s
                                if not haveShift or s > shift:
                                    shift = s
                                    haveShift = True
                                    bindDepth = run.numReaches - current + 1
                    f += 1
            # Step 7
            if startsCluster(glyphs, e):
                # Step 7.1
                current -= 1
                if stop:
                    # Step 7.2
                    if not run.reachSet[current]:
                        break
                    reach = run.reachVal[current]   # the current reach: the reach
                                                    # recorded before this cluster
                    # Step 7.3
                    if rtl:
                        gap = reach - boxXMax   # the gap between F's box and the reach
                    else:
                        gap = boxXMin - reach
                    # Step 7.4
                    limit = shift if haveShift else 0   # the shift, taking none as 0
                    if extra - gap <= limit:
                        break
        # Step 8
        e -= 1
    depth = run.numReaches - current            # testing: how far back the walk went
    stats['walkDepth'][depth] = stats['walkDepth'].get(depth, 0) + 1
    # Step 9
    return haveShift, shift, bindDepth


def orderRule(run, first, last, prevFirst, prevLast, shift):
    '''Experimental alternative to main step 8.1: limit F by the start of the previous
    cluster's polyline bounding box instead of its width. Returns the new shift.'''
    glyphs = run.glyphs             # the glyphs in logical order
    xs = run.xs                     # their current x positions
    F = [k for k in range(first, last + 1) if glyphs[k].hasBoundary()]     # F's glyphs
    P = [k for k in range(prevFirst, prevLast + 1) if glyphs[k].hasBoundary()]
                                    # the previous cluster's glyphs
    if not F or not P:
        return shift
    # limit: the least shift that keeps F's start from passing the previous cluster's
    if run.rtl:
        limit = (max(xs[k] + glyphs[k].bnd.bbox[XMAX] for k in F)
                 - max(xs[k] + glyphs[k].bnd.bbox[XMAX] for k in P))
    else:
        limit = (min(xs[k] + glyphs[k].bnd.bbox[XMIN] for k in P)
                 - min(xs[k] + glyphs[k].bnd.bbox[XMIN] for k in F))
    return max(shift, limit)


def polykern(glyphs, rtl, stop=True, cap=True, order=False):
    '''The main algorithm ("Main algorithm" in the specification). Applies PolyKern to a
    list of Glyph in logical order, changing their advances. Returns testing statistics.
    For testing: stop=False never stops the walk back early, cap=False leaves out step
    8.1, and order=True uses an alternative to step 8.1.'''
    run = Run(glyphs, rtl)          # the working state, including the list of reaches
    stats = run.stats               # testing statistics
    n = len(glyphs)                 # number of glyphs in the run
    # Step 1
    haveReach = False               # whether the reach has a value (it is "none")
    reach = 0                       # the reach: the furthest point, in the direction of
                                    # the text, of any boundary so far, plus later spaces
    havePrev = False                # whether there is a previous cluster
    prevFirst = prevLast = 0        # the previous cluster's first and last glyphs
    prevWidth = 0                   # the previous cluster's width (original advances)
    i = 0                           # index of the current glyph
    while True:
        # Step 2
        if i >= n:
            return stats
        g = glyphs[i]               # the current glyph
        # Step 3
        if g.cat == SPACE:
            if haveReach:
                if rtl:
                    reach -= g.origAdv
                else:
                    reach += g.origAdv
            i += 1
            continue
        # Step 4
        if g.cat == BARRIER:
            haveReach = False
            havePrev = False
            i += 1
            continue
        # Step 5
        if g.cat == IGNORED or (g.cat == ATTACHED and (not g.hasBoundary() or (
                i > 0 and (glyphs[i - 1].cat == ATTACHED or glyphs[i - 1].cat == IGNORED)))):
            i += 1
            continue
        # Step 6.1: the current glyph is the first glyph of a new cluster, F
        last = i                    # index of the last glyph of F, found in step 6
        width = 0                   # F's width: the total of its original advances
        haveBox = False             # whether F has a box (it is "none")
        boxXMin = boxYMin = 0       # F's box: the smallest box enclosing the boxes
        boxXMax = boxYMax = 0       # of its glyphs that have a boundary
        while True:
            # Step 6.2
            lg = glyphs[last]       # the glyph being added to F
            width += lg.origAdv
            if lg.hasBoundary():
                b = lg.bnd.bbox     # its own box (its minPoint and maxPoint)
                gXMin = run.xs[last] + b[XMIN]  # its box moved by its position
                gYMin = lg.yoff + b[YMIN]
                gXMax = run.xs[last] + b[XMAX]
                gYMax = lg.yoff + b[YMAX]
                if not haveBox:
                    boxXMin, boxYMin, boxXMax, boxYMax = gXMin, gYMin, gXMax, gYMax
                    haveBox = True
                else:
                    boxXMin = min(boxXMin, gXMin)
                    boxYMin = min(boxYMin, gYMin)
                    boxXMax = max(boxXMax, gXMax)
                    boxYMax = max(boxYMax, gYMax)
            # Step 6.3
            if last + 1 < n and (glyphs[last + 1].cat == ATTACHED
                                 or glyphs[last + 1].cat == IGNORED):
                last += 1
            else:
                break
        for k in range(i, last + 1):            # testing: record cluster membership
            glyphs[k].cluster = i
        stats['clusters'] += 1
        # Step 7
        haveShift = False           # whether F has a shift (it is "none")
        shift = 0                   # the shift for F: a kern, positive means more space
        bindDepth = 0               # testing: what set the shift
        if haveBox:
            haveShift, shift, bindDepth = calcShift(run, i, last, boxXMin, boxYMin,
                                                    boxXMax, boxYMax, stop)
        # Step 8
        if haveShift:
            # Step 8.1
            if havePrev and cap and shift < -prevWidth:
                shift = -prevWidth
                bindDepth = 'cap'
            if havePrev and order:
                limited = orderRule(run, i, last, prevFirst, prevLast, shift)
                if limited != shift:
                    shift = limited
                    bindDepth = 'order'
            # Step 8.2: change the one advance that spans the gap before F, and keep
            # the positions up to date
            if glyphs[i - 1].cat == SPACE or not rtl:
                glyphs[i - 1].adv += shift
                if rtl:
                    run.moveFrom(i - 1, -shift)
                else:
                    run.moveFrom(i, shift)
            else:
                glyphs[i].adv += shift
                run.moveFrom(i, -shift)
            stats['kerned'] += 1
            stats['bindDepth'][bindDepth] = stats['bindDepth'].get(bindDepth, 0) + 1
        # Step 9
        run.reachSet[run.numReaches] = haveReach
        run.reachVal[run.numReaches] = reach
        run.numReaches += 1
        # Step 10
        if haveBox:
            # far: F's far edge after the shift
            if rtl:
                far = boxXMin - shift if haveShift else boxXMin
                if not haveReach or far < reach:
                    reach = far
            else:
                far = boxXMax + shift if haveShift else boxXMax
                if not haveReach or far > reach:
                    reach = far
            haveReach = True
        # Step 11
        havePrev = True
        prevFirst = i
        prevLast = last
        prevWidth = width
        # Step 12
        i = last + 1


def worstOverlap(glyphs, rtl):
    '''For testing: the smallest gap, less the spaces between, over every pair of glyphs
    in different clusters with no barrier between them. Returns (gap, a, b), or
    (None, None, None) if no pair overlaps vertically.'''
    xs = positions(glyphs, rtl)     # the glyphs' x positions after kerning
    haveWorst = False               # whether any pair has been measured yet
    worst = 0                       # the smallest gap less spaces found so far
    worstA = worstB = None          # the pair of glyphs it was found between
    for b in range(len(glyphs)):    # b: the later glyph of the pair
        a = b - 1                   # a: the earlier glyph, back to a barrier
        while a >= 0 and glyphs[a].cat != BARRIER:
            if (glyphs[a].hasBoundary() and glyphs[b].hasBoundary()
                    and not (glyphs[a].cluster is not None
                             and glyphs[a].cluster == glyphs[b].cluster)):
                # extra: the spaces between them, which the gap must allow for
                extra = sum(glyphs[k].origAdv for k in range(a + 1, b)
                            if glyphs[k].cat == SPACE)
                if rtl:
                    li = b          # index of the left glyph
                    ri = a          # index of the right glyph
                else:
                    li = a
                    ri = b
                s = separation(glyphs[li].bnd.right, glyphs[ri].bnd.left, xs[ri] - xs[li],
                               glyphs[ri].yoff - glyphs[li].yoff)
                if s is not None and (not haveWorst or s - extra < worst):
                    worst = s - extra
                    worstA = a
                    worstB = b
                    haveWorst = True
            a -= 1
    if not haveWorst:
        return None, None, None
    return worst, worstA, worstB
