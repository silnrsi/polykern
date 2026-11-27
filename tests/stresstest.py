#!/usr/bin/env python3
'''Stress test PolyKern over a large set of lines.

For each line this checks:
  1. after kerning, no two clusters' polylines come closer than the spaces between them;
  2. the result is the same as walking all the way back (no early stop);
  3. after kerning, no two clusters' actual ink overlaps (by rasterising the outlines).
It also gathers statistics on how far back the walk goes, and how far back the cluster
that limited the shift was.
'''

import argparse
import multiprocessing
import os
import random
import re
import sys
import time
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uharfbuzz as hb
from awamitest import Tables, shape
from makepolylines import FlattenPen
from polykern import Glyph, polykern, positions, worstOverlap, BARRIER

SCALE = 4       # font units per pixel for the ink check

_tables = _hbfont = _features = None
_inkcache = {}


def _init(fontpath, margin, ignore, nokern, maxArea=None):
    global _tables, _hbfont, _features
    _tables = Tables(fontpath, margin, ignore, maxArea)
    _hbfont = hb.Font(hb.Face(hb.Blob.from_file_path(fontpath)))
    _features = {'kern': False} if nokern else {}


def _contours(name):
    '''Flattened contours of a glyph, as lists of points.'''
    if name not in _inkcache:
        pen = FlattenPen(_tables.font.getGlyphSet())
        _tables.font.getGlyphSet()[name].draw(pen)
        contours = []
        cur = []
        for (p0, p1) in pen.edges:
            if cur and cur[-1] != p0:
                contours.append(cur)
                cur = []
            if not cur:
                cur.append(p0)
            cur.append(p1)
        if cur:
            contours.append(cur)
        _inkcache[name] = contours
    return _inkcache[name]


def _makeGlyphs(text):
    infos, poss, rtl = shape(_hbfont, text, _features)
    glyphs = []
    for info, pos in zip(infos, poss):
        name = _tables.glyphOrder[info.codepoint]
        glyphs.append(Glyph(name, _tables.category(name), _tables.boundaries.get(name),
                            pos.x_advance, pos.x_offset, pos.y_offset))
    return glyphs, rtl


def inkOverlaps(glyphs, rtl):
    '''Rasterise each cluster's ink and return the number of pixels shared by two
    clusters with no barrier between them, and the pair of clusters with most overlap.'''
    xs = positions(glyphs, rtl)
    clusters = {}
    for k, g in enumerate(glyphs):
        if g.cluster is None or not _contours(g.name):
            continue
        polys = [[((x + xs[k]) / SCALE, (y + g.yoff) / SCALE) for x, y in c]
                 for c in _contours(g.name)]
        clusters.setdefault(g.cluster, []).extend(polys)
    masks = {}
    for c, polys in clusters.items():
        allx = [p[0] for poly in polys for p in poly]
        ally = [p[1] for poly in polys for p in poly]
        x0, y0 = int(min(allx)) - 1, int(min(ally)) - 1
        w, h = int(max(allx)) - x0 + 2, int(max(ally)) - y0 + 2
        img = Image.new('1', (w, h), 0)
        d = ImageDraw.Draw(img)
        for poly in polys:
            if len(poly) > 2:
                d.polygon([(x - x0, y - y0) for x, y in poly], fill=1)
        masks[c] = (x0, y0, np.array(img, dtype=bool))
    keys = sorted(masks)
    total = 0
    worst = None
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if any(glyphs[k].cat == BARRIER for k in range(a, b)):
                continue
            ax, ay, am = masks[a]
            bx, by, bm = masks[b]
            lx, ly = max(ax, bx), max(ay, by)
            hx = min(ax + am.shape[1], bx + bm.shape[1])
            hy = min(ay + am.shape[0], by + bm.shape[0])
            if lx >= hx or ly >= hy:
                continue
            n = int(np.count_nonzero(am[ly - ay:hy - ay, lx - ax:hx - ax]
                                     & bm[ly - by:hy - by, lx - bx:hx - bx]))
            if n:
                total += n
                if worst is None or n > worst[0]:
                    worst = (n, a, b)
    return total, worst


def check(text):
    t0 = time.perf_counter()
    glyphs, rtl = _makeGlyphs(text)
    stats = polykern(glyphs, rtl)
    elapsed = time.perf_counter() - t0
    advs = [g.adv for g in glyphs]
    worst = worstOverlap(glyphs, rtl)[0]
    ink, inkWorst = inkOverlaps(glyphs, rtl)

    full, _ = _makeGlyphs(text)
    polykern(full, rtl, stop=False)
    fullAdvs = [g.adv for g in full]

    return dict(text=text, n=len(glyphs), worst=worst, ink=ink,
                inkWorst=None if inkWorst is None else
                (inkWorst[0], glyphs[inkWorst[1]].name, glyphs[inkWorst[2]].name),
                differs=advs != fullAdvs,
                fullWorst=worstOverlap(full, rtl)[0] if advs != fullAdvs else None,
                stats=stats, time=elapsed)


def loadWords(path):
    words = []
    seen = set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'"([^"]+)"', line)
            if m:
                w = m.group(1).replace('​', '')
                if w and w not in seen:
                    seen.add(w)
                    words.append(w)
    return words


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('font')
    p.add_argument('words', help='Word list: lines starting with a quoted word')
    p.add_argument('-n', '--phrases', type=int, default=20000, help='Number of random phrases')
    p.add_argument('-w', '--maxwords', type=int, default=0, help='Limit single words tested (0 = all, -1 = none)')
    p.add_argument('-l', '--phraselen', default='3,5', help='Words per phrase: min,max')
    p.add_argument('-m', '--margin', type=int, default=200, help='Polyline margin in font units')
    p.add_argument('-i', '--ignore')
    p.add_argument('--nokern', action='store_true')
    p.add_argument('-a', '--maxarea', type=float, default=None,
                   help='Simplify polylines while the error triangle is below this area')
    p.add_argument('-j', '--jobs', type=int, default=os.cpu_count())
    p.add_argument('-o', '--output', help='Write failing and interesting lines here')
    p.add_argument('--seed', type=int, default=1)
    args = p.parse_args()

    words = loadWords(args.words)
    rnd = random.Random(args.seed)
    singles = words[:args.maxwords] if args.maxwords >= 0 else []
    if args.maxwords == 0:
        singles = words
    lo, hi = (int(v) for v in args.phraselen.split(','))
    phrases = [' '.join(rnd.choice(words) for _ in range(rnd.randint(lo, hi)))
               for _ in range(args.phrases)]
    print(f'{len(words)} words; testing {len(singles)} single words and {len(phrases)} phrases',
          flush=True)

    out = open(args.output, 'w', encoding='utf-8') if args.output else None
    t0 = time.time()
    with multiprocessing.Pool(args.jobs, _init,
                              (args.font, args.margin, args.ignore, args.nokern,
                               args.maxarea)) as pool:
        for label, texts in (('words', singles), ('phrases', phrases)):
            if not texts:
                continue
            fails = inkFails = differs = differsWorse = lines = clusters = kerned = 0
            walkDepth = Counter()
            bindDepth = Counter()
            walked = 0
            times = []
            inkPairs = Counter()
            for r in pool.imap_unordered(check, texts, chunksize=20):
                lines += 1
                s = r['stats']
                clusters += s['clusters']
                kerned += s['kerned']
                walked += s['walked']
                walkDepth.update(s['walkDepth'])
                bindDepth.update(s['bindDepth'])
                times.append((r['time'], r['n']))
                bad = r['worst'] is not None and r['worst'] < -1
                fails += bad
                if r['ink']:
                    inkFails += 1
                    inkPairs[r['inkWorst'][1:]] += 1
                if r['differs']:
                    differs += 1
                    if r['fullWorst'] is not None and r['worst'] is not None \
                            and r['fullWorst'] > r['worst']:
                        differsWorse += 1
                if out and (bad or r['ink'] or r['differs']):
                    out.write(f'{label}\t{r["text"]}\tworst={r["worst"]}\tink={r["ink"]}'
                              f'\tinkWorst={r["inkWorst"]}\tdiffers={r["differs"]}'
                              f'\tfullWorst={r["fullWorst"]}\n')
                if lines % 5000 == 0:
                    print(f'  {label}: {lines}/{len(texts)} done, {time.time() - t0:.0f}s',
                          flush=True)
            times.sort()
            print(f'\n== {label}: {lines} lines, {clusters} clusters, {kerned} kerned')
            print(f'  polyline overlaps after kerning: {fails}')
            print(f'  lines with ink overlap after kerning: {inkFails}')
            for pair, n in inkPairs.most_common(10):
                print(f'      {n:6d}  {pair[0]} / {pair[1]}')
            print(f'  lines where early stop changed the result: {differs}'
                  f' (of which unlimited walk was better: {differsWorse})')
            print(f'  glyphs walked back: {walked}, {walked / max(clusters, 1):.1f} per cluster')
            print('  walk depth (clusters back reached): '
                  + ', '.join(f'{d}:{n}' for d, n in sorted(walkDepth.items(), key=lambda t: str(t[0]))))
            print('  limiting cluster (clusters back): '
                  + ', '.join(f'{d}:{n}' for d, n in sorted(bindDepth.items(), key=lambda t: str(t[0]))))
            slow = max(times, key=lambda t: t[0])
            print(f'  kerning time per line: median {times[len(times) // 2][0] * 1000:.1f}ms,'
                  f' max {slow[0] * 1000:.1f}ms ({slow[1]} glyphs)', flush=True)
    if out:
        out.close()
    print(f'\nTotal time {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
