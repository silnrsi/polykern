#!/usr/bin/env python3
'''Find the lines where PolyKern and Graphite give the most different overall widths.

Each line is shaped with the Graphite font (hb-shape, graphite2 shaper, one batch run)
and with PolyKern on the OpenType font without kerning. The overall width is the total
advance of the line. Lines where the OpenType font inserts a dotted circle are left out,
since that font bug alone changes the width.

Writes the most different lines, both wider and narrower, to a file of test lines that
graphitecompare.py can render.
'''

import argparse
import json
import multiprocessing
import os
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stresstest as st
from polykern import polykern

_dotted = None


def _init(otfont, margin):
    global _dotted
    st._init(otfont, margin, None, True)
    _dotted = st._tables.font.getBestCmap().get(0x25CC)


def pkWidth(text):
    glyphs, rtl = st._makeGlyphs(text)
    if any(g.name == _dotted for g in glyphs):
        return text, None, None
    before = sum(g.adv for g in glyphs)
    polykern(glyphs, rtl)
    return text, before, sum(g.adv for g in glyphs)


def graphiteWidths(grfont, texts):
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.txt', delete=False) as f:
        f.write('\n'.join(texts) + '\n')
        name = f.name
    try:
        out = subprocess.run(['hb-shape', '--shapers=graphite2', '--output-format=json',
                              '--no-glyph-names', '--font-file=' + grfont, '--text-file=' + name],
                             capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(name)
    res = [sum(g['ax'] for g in json.loads(l)) for l in out.splitlines() if l.strip()]
    assert len(res) == len(texts), (len(res), len(texts))
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('otfont', help='OpenType font without kerning')
    p.add_argument('grfont', help='Graphite font')
    p.add_argument('words', help='Word list: lines starting with a quoted word')
    p.add_argument('-o', '--output', required=True, help='Test lines file to write')
    p.add_argument('-m', '--margin', type=int, default=125)
    p.add_argument('-n', '--phrases', type=int, default=20000)
    p.add_argument('-t', '--top', type=int, default=12, help='How many of each kind to keep')
    p.add_argument('--seed', type=int, default=1)
    args = p.parse_args()

    words = st.loadWords(args.words)
    rnd = random.Random(args.seed)
    phrases = [' '.join(rnd.choice(words) for _ in range(rnd.randint(2, 4)))
               for _ in range(args.phrases)]
    texts = words + phrases
    print(f'{len(texts)} lines', flush=True)
    gr = dict(zip(texts, graphiteWidths(args.grfont, texts)))
    print('Graphite done', flush=True)
    rows = []
    with multiprocessing.Pool(os.cpu_count(), _init, (args.otfont, args.margin)) as pool:
        for text, unkerned, kerned in pool.imap_unordered(pkWidth, texts, chunksize=100):
            if kerned is None:
                continue
            rows.append((kerned - gr[text], (kerned - gr[text]) / max(gr[text], 1),
                         text, gr[text], kerned, unkerned))
    print(f'{len(rows)} lines compared (others had the dotted circle bug)')
    diffs = sorted(r[0] for r in rows)
    print(f'PolyKern minus Graphite width: median {diffs[len(diffs) // 2]}, '
          f'10% {diffs[len(diffs) // 10]}, 90% {diffs[9 * len(diffs) // 10]}')
    rows.sort()
    groups = [('PolyKern much narrower than Graphite', rows[:args.top]),
              ('PolyKern much wider than Graphite', rows[::-1][:args.top]),
              ('PolyKern much narrower, relative to the line',
               sorted(rows, key=lambda r: r[1])[:args.top]),
              ('PolyKern much wider, relative to the line',
               sorted(rows, key=lambda r: -r[1])[:args.top])]
    with open(args.output, 'w', encoding='utf-8') as f:
        seen = set()
        for title, rs in groups:
            print(f'\n{title}:')
            f.write(f'# {title}\n')
            for d, rel, text, g, k, u in rs:
                print(f'  {d:+6d} ({rel:+.0%})  Graphite {g:6d}  PolyKern {k:6d}  unkerned {u:6d}  {text}')
                if text not in seen:
                    f.write(text + '\n')
                    seen.add(text)


if __name__ == '__main__':
    main()
