from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

def _xinterp(top, bottom, y, d):
    t = (y - d - bottom.y) / (top.y - bottom.y)
    x = t * top.x + (1 - t) * bottom.x
    return int(x + 0.5)

def calckern(lefts, rights, xd, yd, es=0):
    ''' lefts is all left boundaries top to bottom
        rights is all right boundaries top to bottom
        xd is difference of right to left (right - left) in x
        yd is difference of right to left in y
        es is the extra separation due to in between spaces'''
    i = len(lefts) - 1      # process from top to bottom
    j = 0
    kern = 1e6              # call that infinity
    l = 0
    r = 0
    y = min(lefts[i].y, rights[j].y + yd)
    while i >= 0 and j < len(rights):
        while i > 0 and lefts[i].y >= y:
            i -= 1
        while j < len(rights) and rights[j].y + yd >= y:
            j += 1
        if lefts[i+1].y == y:
            l = lefts[i+1].x
        elif i < len(lefts):
            l = _xinterp(lefts[i+1], lefts[i], y, 0)
        else:
            l = None
        if rights[j-1].y + yd == y:
            r = rights[j-1].x + xd
        elif j < len(rights):
            r = _xinterp(rights[j-1], rights[j], y, yd) + xd
        else:
            r = None
        # i or j can now be out of range, while l & r are useful
        if l is not None and r is not None:
            kern = min(kern, r-l)
            print(f"{r},{l}={kern}; {y}; {i}, {j}")
            if i >= 0 and j < len(rights):
                print(f"        ({i}={lefts[i].y}, {j}={rights[j].y+yd})")
                y = max(lefts[i].y, rights[j].y + yd)
    return kern

tests = [
    [[(1125, -600), (1546, 66), (1753, 881), (1889, 897), (2265, 1082), (2369, 1321), (2369, 1698), (2331, 1692)],      # absSad
     [(82, -10), (64, 28), (555, 322), (647, 459), (789, 992)],     # absReh
     (2472, -50)]
]

def main():
    for i, t in enumerate(tests):
        ls = [Point(*p) for p in t[0]]              # bottom to top
        rs = [Point(*p) for p in reversed(t[1])]    # top to bottom
        xd, yd = t[2]
        k = calckern(ls, rs, xd, yd)
        print(f"{i}: {k}")

if __name__ == "__main__":
    main()
