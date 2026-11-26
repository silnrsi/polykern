#!/usr/bin/env python3
'''Test PolyKern on real text.

Each line of text is shaped with HarfBuzz. PolyKern (polykern.py) is then applied to
HarfBuzz's final positions, as if it were the last GPOS lookup. Polylines are generated
from the glyph outlines (makepolylines.py).

The result is checked so that no two clusters come closer than their polylines allow,
and an SVG is written showing each line before and after kerning.
'''

import argparse
import os
import re
import sys

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from makepolylines import makeAllBoundaries, arabicGlyphs
from polykern import (Glyph, polykern, positions, worstOverlap,
                      IGNORED, MARK, ATTACHED, SPACE, KERNABLE, BARRIER, CATNAMES)

DEFAULT_TEXTS = [
    'پاکستان',
    'اردو زبان',
    'یہ ایک مثال ہے',
    'نستعلیق خط',
    'کتاب میں',
    'سب سے بہتر',
    'بیچ میں',
    'ہم نے دیکھا',
]


def cursiveEntryGlyphs(font):
    '''Glyphs with an entry anchor in any cursive attachment subtable.'''
    res = set()
    if 'GPOS' not in font:
        return res
    for lk in font['GPOS'].table.LookupList.Lookup:
        for st in lk.SubTable:
            t = lk.LookupType
            if t == 9:
                t = st.ExtensionLookupType
                st = st.ExtSubTable
            if t != 3:
                continue
            for g, rec in zip(st.Coverage.glyphs, st.EntryExitRecord):
                if rec.EntryAnchor is not None:
                    res.add(g)
    return res


class Tables:
    '''The data a PolyKern subtable would hold, worked out from the font.'''

    def __init__(self, fontpath, margin, ignore=None, maxArea=1000):
        self.ignore = re.compile(ignore) if ignore else None
        self.font = TTFont(fontpath)
        self.glyphOrder = self.font.getGlyphOrder()
        self.glyphClass = {}
        if 'GDEF' in self.font and self.font['GDEF'].table.GlyphClassDef:
            self.glyphClass = self.font['GDEF'].table.GlyphClassDef.classDefs
        arabic = arabicGlyphs(TTFont(fontpath))
        self.boundaries = makeAllBoundaries(self.font, margin=margin, glyphs=arabic,
                                            maxArea=maxArea)
        cmap = self.font.getBestCmap()
        spaces = {cmap[u] for u in (0x20, 0xA0) if u in cmap}
        # baseCoverage: Arabic bases and spaces. Spaces are the ones with no boundary.
        self.baseCoverage = {g for g in arabic if self.glyphClass.get(g, 1) != 3} | spaces
        self.attachedCoverage = cursiveEntryGlyphs(self.font) - {
            g for g, c in self.glyphClass.items() if c == 3}

    def category(self, name):
        if self.ignore and self.ignore.search(name):
            return IGNORED
        if self.glyphClass.get(name) == 3:
            return MARK
        if name in self.attachedCoverage:
            return ATTACHED
        if name in self.baseCoverage:
            return KERNABLE if name in self.boundaries else SPACE
        return BARRIER


def shape(hbfont, text, features):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf, features)
    rtl = buf.direction == 'rtl'
    infos = buf.glyph_infos
    poss = buf.glyph_positions
    if rtl:     # HarfBuzz returns visual order; PolyKern works in logical order
        infos = list(reversed(infos))
        poss = list(reversed(poss))
    return infos, poss, rtl


def run(tables, hbfont, text, features, cap=True):
    infos, poss, rtl = shape(hbfont, text, features)
    glyphs = []
    for info, pos in zip(infos, poss):
        name = tables.glyphOrder[info.codepoint]
        cat = tables.category(name)
        glyphs.append(Glyph(name, cat, tables.boundaries.get(name), pos.x_advance,
                            pos.x_offset, pos.y_offset))
    before = [g.adv for g in glyphs]
    xsBefore = positions(glyphs, rtl)
    # Cluster numbers are only set by polykern(), so check "before" on a copy afterwards.
    stats = polykern(glyphs, rtl, cap=cap)
    xsAfter = positions(glyphs, rtl)
    after = [g.adv for g in glyphs]
    worstAfter = worstOverlap(glyphs, rtl)
    for g, a in zip(glyphs, before):
        g.adv = a
    worstBefore = worstOverlap(glyphs, rtl)
    for g, a in zip(glyphs, after):
        g.adv = a
    return dict(text=text, rtl=rtl, glyphs=glyphs, xsBefore=xsBefore, xsAfter=xsAfter,
                stats=stats, worstBefore=worstBefore, worstAfter=worstAfter,
                changes=[(g.name, b, a) for g, b, a in zip(glyphs, before, after) if a != b])


def svgLine(tables, paths, res, xs, yorig, showPolys):
    out = []
    glyphs = res['glyphs']
    minx = min(xs)
    for g, x in zip(glyphs, xs):
        if g.name not in paths:
            pen = SVGPathPen(tables.font.getGlyphSet())
            tables.font.getGlyphSet()[g.name].draw(pen)
            paths[g.name] = pen.getCommands()
        tx = x - minx
        colour = {MARK: '#1f6fb2', ATTACHED: '#222', KERNABLE: '#222'}.get(g.cat, '#b22')
        out.append(f'<path transform="translate({tx},{yorig - g.yoff}) scale(1,-1)" '
                   f'd="{paths[g.name]}" fill="{colour}"/>')
        if showPolys and g.hasBoundary():
            pts = g.bnd.left + g.bnd.right
            ptstr = ' '.join(f'{px},{py}' for px, py in pts)
            out.append(f'<polygon transform="translate({tx},{yorig - g.yoff}) scale(1,-1)" '
                       f'points="{ptstr}" fill="none" stroke="#e07000" stroke-width="4"/>')
    return out


def writeSvg(tables, results, path, showPolys):
    paths = {}
    rowh = 4500
    width = 0
    body = []
    y = 0
    for res in results:
        for label, xs in (('before', res['xsBefore']), ('after', res['xsAfter'])):
            y += rowh
            body.append(f'<text x="0" y="{y - rowh + 300}" font-size="160" '
                        f'font-family="sans-serif">{label}: worst gap '
                        f'{res["worstBefore" if label == "before" else "worstAfter"][0]}</text>')
            body.extend(svgLine(tables, paths, res, xs, y - 1400, showPolys))
            width = max(width, max(xs) - min(xs) + 3000)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-500 0 {width} {y + 500}" '
           f'width="{width / 10}" height="{(y + 500) / 10}">\n'
           f'<rect x="-500" y="0" width="{width}" height="{y + 500}" fill="white"/>\n'
           + '\n'.join(body) + '\n</svg>\n')
    with open(path, 'w') as f:
        f.write(svg)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('font', help='Font file (OpenType, ideally without kerning)')
    p.add_argument('-t', '--text', help='File of test lines (default: built-in lines)')
    p.add_argument('-m', '--margin', type=int, default=200, help='Polyline margin in font units')
    p.add_argument('-o', '--svg', help='Write an SVG showing before and after')
    p.add_argument('-p', '--polylines', action='store_true', help='Draw polylines in the SVG')
    p.add_argument('--nokern', action='store_true', help="Turn off the font's own kern feature")
    p.add_argument('-i', '--ignore', help='Regular expression for glyph names to treat as ignored')
    p.add_argument('-a', '--maxarea', type=float, default=1000,
                   help='Simplify polylines while the error triangle is below this area')
    p.add_argument('-v', '--verbose', action='store_true', help='List glyphs and changes')
    p.add_argument('--nocap', action='store_true',
                   help='Leave out step 9.1, which stops a cluster moving back past the one before')
    args = p.parse_args()

    tables = Tables(args.font, args.margin, args.ignore, args.maxarea)
    hbfont = hb.Font(hb.Face(hb.Blob.from_file_path(args.font)))
    features = {'kern': False} if args.nokern else {}
    if args.text:
        with open(args.text, encoding='utf-8') as f:
            texts = [l.strip() for l in f if l.strip()]
    else:
        texts = DEFAULT_TEXTS

    print(f'{len(tables.boundaries)} boundaries, {len(tables.baseCoverage)} in baseCoverage, '
          f'{len(tables.attachedCoverage)} in baseAttachedCoverage')
    results = []
    failures = 0
    for text in texts:
        res = run(tables, hbfont, text, features, not args.nocap)
        results.append(res)
        s = res['stats']
        bad = res['worstAfter'][0] is not None and res['worstAfter'][0] < -1
        failures += bad
        print(f'{"FAIL" if bad else "ok  "} {text}: {s["clusters"]} clusters, '
              f'{s["kerned"]} kerned, walked {s["walked"]}, {s["separations"]} separations, '
              f'worst gap before {res["worstBefore"][0]} after {res["worstAfter"][0]}')
        if args.verbose:
            print('    ' + ' '.join(f'{g.name}/{CATNAMES[g.cat]}' for g in res['glyphs']))
            for name, b, a in res['changes']:
                print(f'    {name}: advance {b} -> {a}')
    if args.svg:
        writeSvg(tables, results, args.svg, args.polylines)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
