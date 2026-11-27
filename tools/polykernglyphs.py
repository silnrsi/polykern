#!/usr/bin/env python3
'''List the glyphs that need a PolyKern boundary: those a script can reach through GSUB,
starting from the characters of the script in the cmap. Glyphs with no outline are left
out, since they need no boundary.

The glyph names in the list must be the UFO's. Either compile the font with the UFO's
glyph names (psfufo2ttf, and fontmake without production names, keep them), or give the
UFO with --ufo: glyphs whose names are not in the UFO are then matched to UFO glyphs by
their advance and outline bounds, and any that match nothing are reported.
'''

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fontTools.ttLib import TTFont
from polykernlib.boundaries import mapToUfo, scriptGlyphs


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('font', help='Compiled font (TTF or OTF) with GSUB')
    p.add_argument('-o', '--output', help='Glyph list to write, one name per line '
                   '(default: standard output)')
    p.add_argument('-s', '--script', default='Arab',
                   help='ISO 15924 script code (default: Arab)')
    p.add_argument('--all', action='store_true',
                   help='Include glyphs with no outline as well')
    p.add_argument('-u', '--ufo', help='UFO to give the glyph names of, matching glyphs '
                   'by shape where the font\'s names differ')
    p.add_argument('--tolerance', type=int, default=2,
                   help='With --ufo: how far outline bounds may differ (default: 2)')
    p.add_argument('--exclude', default=r'^_',
                   help='With --ufo: regular expression for UFO glyphs that are not exported '
                   'and so never matched (default: ^_); public.skipExportGlyphs are left '
                   'out too')
    args = p.parse_args()

    font = TTFont(args.font)
    glyphs = scriptGlyphs(font, args.script, withOutlines=not args.all)
    if args.ufo:
        import ufoLib2
        glyphs, missing = mapToUfo(TTFont(args.font), glyphs, ufoLib2.Font.open(args.ufo),
                                   args.tolerance, args.exclude)
        if missing:
            print(f'{len(missing)} glyphs match nothing in the UFO: {" ".join(missing)}',
                  file=sys.stderr)
    text = ''.join(g + '\n' for g in glyphs)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'{len(glyphs)} glyphs written to {args.output}', file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
