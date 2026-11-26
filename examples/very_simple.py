#!/usr/bin/env python3
'''The separation of two glyphs, as in "Separation of two glyphs" in
documentation/PolyKernLookup.md, with a small worked example.

The same function is in tests/polykern.py, which implements the whole algorithm.
'''

X, Y = 0, 1         # indexes into a point (x, y)


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
    '''The smallest horizontal gap between R, the right polyline of the left glyph (points
    top to bottom), and L, the left polyline of the right glyph (points bottom to top),
    with L moved by dx and dy. Returns None if they don't overlap vertically.'''
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


# Worked examples: (description, R, L, dx, dy, expected separation). R is listed top to
# bottom and L bottom to top, as they are stored in a boundary.
EXAMPLES = [
    ('Two upright edges 100 apart',
     [(100, 1000), (100, 0)], [(0, 0), (0, 1000)], 200, 0, 100),
    ('Slanted right edge: closest at the top',
     [(100, 1000), (0, 0)], [(0, 0), (0, 1000)], 200, 0, 100),
    ('Right glyph lower, overlapping only at the bottom of the left glyph',
     [(100, 1000), (100, 0)], [(50, -500), (0, 400)], 200, -300, 100),
    ('No vertical overlap',
     [(100, 3000), (100, 2000)], [(0, 0), (0, 1000)], 200, 0, None),
    ('Awami: the right side of sad (absSad) against the left side of reh (absReh)',
     [(2369, 1698), (2369, 1321), (2265, 1082), (1889, 897), (1753, 881), (1546, 66),
      (1125, -600)],
     [(82, -10), (64, 28), (555, 322), (647, 459), (789, 992)], 2472, -50, 1045),
]


def main():
    for desc, R, L, dx, dy, expected in EXAMPLES:
        got = separation(R, L, dx, dy)
        print(f'{"ok  " if got == expected else "FAIL"} {desc}: {got}')


if __name__ == '__main__':
    main()
