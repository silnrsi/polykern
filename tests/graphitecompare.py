#!/usr/bin/env python3
'''Compare PolyKern with the Graphite build of Awami Nastaliq.

Each line is shaped with the Graphite font (using hb-shape with the graphite2 shaper),
and with the OpenType font without kerning plus PolyKern. With --kernfont it also shapes
the line with an OpenType font that does its own kerning, for a three-way review. The SVG shows, for each line, the Graphite
rendering, then PolyKern without step 9.1 (the cap), then with the experimental
ordering rule in place of the cap, then PolyKern as specified (with the cap).

Positions are compared by character cluster: for each character that starts a cluster
with a spacing glyph in both renderings, the x of that glyph's origin, measured from
the start of the line. The score is the mean absolute difference in font units.
'''

import argparse
import json
import os
import subprocess
import sys

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from awamitest import Tables, shape
from polykern import Glyph, polykern, positions, MARK, KERNABLE, ATTACHED


def graphiteShape(fontpath, text):
    '''Glyph ids, clusters and x, y positions (visual order, left to right).'''
    out = subprocess.run(['hb-shape', '--shapers=graphite2', '--output-format=json',
                          '--no-glyph-names', '--font-file=' + fontpath, '--text=' + text],
                         capture_output=True, text=True, check=True).stdout
    res = []
    pen = 0
    for g in json.loads(out):
        res.append((g['g'], g['cl'], pen + g['dx'], g['dy'], g['ax']))
        pen += g['ax']
    return res


def polykernShape(tables, hbfont, text, features, **kw):
    infos, poss, rtl = shape(hbfont, text, features)
    glyphs = []
    for info, pos in zip(infos, poss):
        name = tables.glyphOrder[info.codepoint]
        g = Glyph(name, tables.category(name), tables.boundaries.get(name),
                  pos.x_advance, pos.x_offset, pos.y_offset)
        g.hbcluster = info.cluster
        glyphs.append(g)
    polykern(glyphs, rtl, **kw)
    xs = positions(glyphs, rtl)
    lo = min(xs)
    return [(tables.font.getGlyphID(g.name), g.hbcluster, x - lo, g.yoff, g.adv)
            for g, x in zip(glyphs, xs)]


def otShape(hbfont, text):
    '''Shape with an OpenType font and all its own features, including its kerning.'''
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf, {})
    res = []
    pen = 0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        res.append((info.codepoint, info.cluster, pen + pos.x_offset, pos.y_offset, pos.x_advance))
        pen += pos.x_advance
    return res


def clusterOrigins(glyphs):
    '''{cluster: x} for each character cluster: the origin of its first glyph with ink
    (a nonzero advance in the font), measured from the right end of the line (the start
    of RTL text). The origin is where the ink is drawn from, so this doesn't depend on
    which glyph's advance holds a kern.'''
    right = max(x + a for _, _, x, _, a in glyphs)
    res = {}
    for gid, cl, x, y, adv in glyphs:
        if adv != 0 and cl not in res:
            res[cl] = right - x
    return res


def score(a, b):
    ca, cb = clusterOrigins(a), clusterOrigins(b)
    common = sorted(set(ca) & set(cb))
    if not common:
        return None
    return sum(abs(ca[c] - cb[c]) for c in common) / len(common)


def gapScore(a, b):
    '''Mean absolute difference between the two renderings in the distance from each
    character cluster to the next, so that one difference doesn't count again for every
    cluster after it.'''
    ca, cb = clusterOrigins(a), clusterOrigins(b)
    common = sorted(set(ca) & set(cb))
    if len(common) < 2:
        return None
    diffs = [abs((ca[c1] - ca[c0]) - (cb[c1] - cb[c0])) for c0, c1 in zip(common, common[1:])]
    return sum(diffs) / len(diffs)


def svgRow(font, glyphs, yorig, colour, paths):
    gs = font.getGlyphSet()
    order = font.getGlyphOrder()
    out = []
    right = max(x + a for _, _, x, _, a in glyphs)
    for gid, cl, x, y, adv in glyphs:
        name = order[gid]
        key = (id(font), name)
        if key not in paths:
            pen = SVGPathPen(gs)
            gs[name].draw(pen)
            paths[key] = pen.getCommands()
        # right-align every row so that the starts of the RTL lines line up
        out.append(f'<path transform="translate({x - right},{yorig - y}) scale(1,-1)" '
                   f'd="{paths[key]}" fill="{colour}"/>')
    return out


def readLines(path):
    '''Test lines, with lines starting # giving a heading for the lines that follow.'''
    res = []
    heading = None
    with open(path, encoding='utf-8') as f:
        for l in f:
            l = l.strip()
            if l.startswith('#'):
                heading = l.lstrip('#').strip()
            elif l:
                res.append((heading, l))
                heading = None
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('otfont', help='OpenType font (without kerning)')
    p.add_argument('grfont', help='Graphite font')
    p.add_argument('lines', help='File of test lines; lines starting # are headings')
    p.add_argument('-m', '--margin', type=int, default=125)
    p.add_argument('-o', '--svg', help='Write the comparison SVG here')
    p.add_argument('-p', '--pdf', help='Write the comparison as an A4 PDF, laid out as a grid')
    p.add_argument('--margins', help='Comma separated margins to score, e.g. 100,150,200')
    p.add_argument('--pair', action='store_true',
                   help='Show just Graphite and PolyKern for each line')
    p.add_argument('-k', '--kernfont', help='OpenType font with its own kerning: compare '
                   'Graphite, this font and PolyKern (the three-way review)')
    args = p.parse_args()

    lines = readLines(args.lines)
    texts = [t for _, t in lines]
    grfont = TTFont(args.grfont)
    hbfont = hb.Font(hb.Face(hb.Blob.from_file_path(args.otfont)))
    features = {'kern': False}
    if args.kernfont:
        kfont = TTFont(args.kernfont)
        khbfont = hb.Font(hb.Face(hb.Blob.from_file_path(args.kernfont)))
        kscores = [gapScore(graphiteShape(args.grfont, t), otShape(khbfont, t)) for t in texts]
        kvalid = [s for s in kscores if s is not None]
        print(f'OpenType kerning font: mean gap difference from Graphite '
              f'{sum(kvalid) / len(kvalid):4.0f}', flush=True)

    margins = [int(m) for m in args.margins.split(',')] if args.margins else [args.margin]
    modes = ((('cap', {}),) if args.kernfont else
             (('no cap', {'cap': False}), ('order', {'cap': False, 'order': True}), ('cap', {})))
    for m in margins:
        tables = Tables(args.otfont, m)
        for label, kw in modes:
            scores = []
            gaps = []
            for text in texts:
                gr = graphiteShape(args.grfont, text)
                pk = polykernShape(tables, hbfont, text, features, **kw)
                scores.append(score(gr, pk))
                gaps.append(gapScore(gr, pk))
            valid = [s for s in scores if s is not None]
            gvalid = [s for s in gaps if s is not None]
            print(f'PolyKern margin {m:4d} {label:7s}: mean cluster offset {sum(valid) / len(valid):5.0f};'
                  f' mean gap difference {sum(gvalid) / len(gvalid):4.0f}', flush=True)

    if args.svg or args.pdf:
        tables = Tables(args.otfont, args.margin)
        paths = {}
        pages = []          # one page per heading: (heading, [rows for each line])
        for heading, text in lines:
            if args.pair:
                rows = [('Graphite', grfont, graphiteShape(args.grfont, text), '#1b2f7a'),
                        (f'PolyKern (margin {args.margin})', tables.font,
                         polykernShape(tables, hbfont, text, features), '#000000')]
            elif args.kernfont:
                rows = [('Graphite', grfont, graphiteShape(args.grfont, text), '#1b2f7a'),
                        (f'PolyKern (margin {args.margin})', tables.font,
                         polykernShape(tables, hbfont, text, features), '#000000'),
                        ('OpenType kerning lookups', kfont, otShape(khbfont, text), '#0d5a1e')]
            else:
                rows = [('Graphite', grfont, graphiteShape(args.grfont, text), '#1f5fbf'),
                        (f'PolyKern margin {args.margin}, no cap', tables.font,
                         polykernShape(tables, hbfont, text, features, cap=False), '#000000'),
                        (f'PolyKern margin {args.margin}, ordering rule instead of cap',
                         tables.font,
                         polykernShape(tables, hbfont, text, features, cap=False, order=True),
                         '#1a8a2a'),
                        (f'PolyKern margin {args.margin}, with cap (as specified)', tables.font,
                         polykernShape(tables, hbfont, text, features), '#c0281e')]
            if heading or not pages:
                pages.append((heading, []))
            pages[-1][1].append(rows)
        if args.svg:
            with open(args.svg, 'w') as f:
                f.write(makeSvg(pages, paths))
        if args.pdf:
            makePdf(pages, paths, args.pdf)


SHORT = {'Graphite': 'G', 'OpenType kerning lookups': 'OT'}


def makePdf(pages, paths, outpdf, pagesize=(595, 842), margin=36, scale=0.0075):
    '''Lay out the lines as a grid of cells on A4 pages and write a PDF. Each cell holds
    one test line, with a row for each rendering. Cells flow right to left, as many to a
    row as fit; each heading starts a new row.'''
    import tempfile
    pw, ph = pagesize
    rowh = 4800 * scale             # height of one rendering, in points
    above = 3300 * scale            # baseline position within a rendering
    pad = 6
    labelw = 14
    gap = 8
    headh = 18
    legendh = 16
    out = []                        # list of pages, each a list of SVG elements
    state = {}

    def newPage():
        out.append([])
        y = margin
        # the key at the top of each page
        x = margin
        for label, _, _, colour in pages[0][1][0]:
            short = SHORT.get(label, 'PK')
            out[-1].append(f'<text x="{x}" y="{y + 10}" font-size="8" font-family="sans-serif" '
                           f'fill="{colour}">{short} = {label}</text>')
            x += 150
        state.update(x=pw - margin, y=y + legendh, rowmax=0)

    def newRow():
        state['y'] += state['rowmax']
        state.update(x=pw - margin, rowmax=0)

    def fits(h):
        return state['y'] + h <= ph - margin

    newPage()
    for heading, lines in pages:
        if heading:
            if state['x'] < pw - margin:
                newRow()
            first = lines[0]
            if not fits(headh + len(first) * rowh + pad):
                newPage()
            out[-1].append(f'<text x="{margin}" y="{state["y"] + 13}" font-size="11" '
                           f'font-weight="bold" font-family="sans-serif" fill="#000">'
                           f'{heading}</text>')
            state['y'] += headh
        for rows in lines:
            gw = max(max(x + a for _, _, x, _, a in g) - min(x for _, _, x, _, _ in g)
                     for _, _, g, _ in rows)
            w = gw * scale + 2 * pad + labelw
            h = len(rows) * rowh + pad
            if state['x'] - w < margin and state['x'] < pw - margin:
                newRow()
            if not fits(h):
                newPage()
            right = state['x']
            left = right - w
            top = state['y']
            out[-1].append(f'<rect x="{left}" y="{top}" width="{w}" height="{h}" fill="none" '
                           f'stroke="#bbb" stroke-width="0.4"/>')
            for r, (label, font, glyphs, colour) in enumerate(rows):
                base = top + pad / 2 + r * rowh + above
                out[-1].append(f'<text x="{left + 2}" y="{base}" font-size="6" '
                               f'font-family="sans-serif" fill="{colour}">'
                               f'{SHORT.get(label, "PK")}</text>')
                out[-1].append(f'<g transform="translate({right - pad},{base}) '
                               f'scale({scale},{-scale})">')
                gs = font.getGlyphSet()
                order = font.getGlyphOrder()
                gright = max(x + a for _, _, x, _, a in glyphs)
                for gid, cl, x, y, adv in glyphs:
                    name = order[gid]
                    key = (id(font), name)
                    if key not in paths:
                        pen = SVGPathPen(gs)
                        gs[name].draw(pen)
                        paths[key] = pen.getCommands()
                    if paths[key]:
                        out[-1].append(f'<path transform="translate({x - gright},{y})" '
                                       f'd="{paths[key]}" fill="{colour}"/>')
                out[-1].append('</g>')
            state['x'] = left - gap
            state['rowmax'] = max(state['rowmax'], h + gap)

    with tempfile.TemporaryDirectory() as tmp:
        pdfs = []
        for i, elems in enumerate(out):
            svgpath = os.path.join(tmp, f'page{i:03d}.svg')
            with open(svgpath, 'w') as f:
                f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw}pt" height="{ph}pt" '
                        f'viewBox="0 0 {pw} {ph}">\n<rect width="{pw}" height="{ph}" fill="white"/>\n'
                        + '\n'.join(elems) + '\n</svg>\n')
            pdfs.append(os.path.join(tmp, f'page{i:03d}.pdf'))
            subprocess.run(['inkscape', svgpath, '--export-type=pdf',
                            '--export-filename=' + pdfs[-1]], check=True, capture_output=True)
        subprocess.run(['pdfunite'] + pdfs + [outpdf], check=True)


def makeSvg(pages, paths):
    '''An SVG of the given pages, one after the other.'''
    body = []
    y = 0
    rowh = 4500
    width = 0
    for heading, lines in pages:
        if heading:
            y += 1600
            body.append(f'<text x="LEFT" y="{y}" font-size="900" font-weight="bold" '
                        f'font-family="sans-serif" fill="#333">{heading}</text>')
        for rows in lines:
            for label, font, glyphs, colour in rows:
                y += rowh
                width = max(width, max(x + a for _, _, x, _, a in glyphs)
                            - min(x for _, _, x, _, _ in glyphs))
                body.append(f'<text x="LEFT" y="{y - rowh + 700}" font-size="450" '
                            f'font-family="sans-serif" fill="{colour}">{label}</text>')
                body.extend(svgRow(font, glyphs, y - 1400, colour, paths))
            y += 1000
    width = max(width + 3000, 24000)     # room for the headings
    body = [b.replace('x="LEFT"', f'x="{-width + 300}"') for b in body]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-width} 0 {width + 2000} {y}" '
            f'width="{(width + 2000) / 20}" height="{y / 20}">\n'
            f'<rect x="{-width}" y="0" width="{width + 2000}" height="{y}" fill="white"/>\n'
            + '\n'.join(body) + '\n</svg>\n')


if __name__ == '__main__':
    main()
