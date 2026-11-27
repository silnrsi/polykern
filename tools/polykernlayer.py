#!/usr/bin/env python3
'''Make PolyKern boundaries from glyph outlines and write them into a UFO layer
(org.sil.polykern by default), for designers to edit.

Each boundary is one open contour: up the left side from the bottom, then down the right
side, with no line back to the start. It is made by moving the outline out by the margin
and simplifying it. Margins are given in %em (percent of the font's units per em); the
simplification error and curve tolerance as percentages of each glyph's margin.

The boundaries for the glyphs in the list are made from their outlines, replacing what
the layer had for them. Without a list, every glyph already in the layer is remade, so
that the boundaries follow changes to the outlines. To keep a hand-edited boundary, leave
it out of the list.
'''

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ufoLib2
from polykernlib.ufolayer import LAYER, updateLayer


def readGlyphList(path):
    names = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if line:
                names.extend(line.split())
    return names


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('ufo', help='UFO to add the layer to')
    p.add_argument('-g', '--glyphs', help='Glyph list, as from polykernglyphs.py (default: '
                   'the glyphs already in the layer)')
    p.add_argument('-o', '--output', help='UFO to write (default: change the input UFO)')
    p.add_argument('-m', '--margin', type=float, default=10,
                   help='Space around each glyph, in %%em (default: 10)')
    p.add_argument('--markmargin', type=float,
                   help='Margin for glyphs with an attachment point starting with _, in %%em '
                   '(default: the same as --margin)')
    p.add_argument('-e', '--maxerror', type=float, default=7.5,
                   help='How far the simplified boundary may be from the emboldened '
                   'outline, as a percentage of the margin (default: 7.5)')
    p.add_argument('-t', '--tolerance', type=float, default=2.5,
                   help='How close the lines that replace curves must be to the curve, as a '
                   'percentage of the margin; they are always outside it (default: 2.5)')
    p.add_argument('-l', '--layer', default=LAYER, help=f'Layer name (default: {LAYER})')
    p.add_argument('-v', '--verbose', action='store_true', help='List the glyphs in each group')
    args = p.parse_args()

    font = ufoLib2.Font.open(args.ufo)
    glyphs = readGlyphList(args.glyphs) if args.glyphs else None
    if glyphs is None and args.layer not in font.layers:
        p.error(f'The UFO has no {args.layer} layer yet, so give a glyph list (-g)')
    upm = font.info.unitsPerEm or 1000

    def units(pct):
        return None if pct is None else pct * upm / 100

    report = updateLayer(font, glyphs, units(args.margin), units(args.markmargin),
                         args.maxerror, args.layer, args.tolerance)
    if args.output:
        font.save(args.output, overwrite=True)
    else:
        font.save()
    for k, names in report.items():
        if names:
            print(f'{k}: {len(names)}' + (': ' + ' '.join(names) if args.verbose or
                                          k == 'missing' else ''))


if __name__ == '__main__':
    main()
