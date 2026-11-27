#!/usr/bin/env python3
'''Make a PDF proof of PolyKern boundaries: one glyph per page, showing the filled glyph
outline, its boundary from the PolyKern layer, the x and y axes, and the advance.

All pages use the same scale, so glyphs can be compared: the scale at which the glyph that
needs the most room fills its page. With --fit, each glyph is scaled to fill its own page.
'''

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ufoLib2
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.basePen import BasePen
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import FILL_NON_ZERO

from polykernlib.ufolayer import LAYER

PAGESIZES = {'A4': A4, 'letter': letter}
PAGE_MARGIN = 36            # points around the page
TITLE_HEIGHT = 40           # points above the box for the glyph name

INK = colors.Color(0.25, 0.25, 0.25)
BOUNDARY = colors.Color(0.85, 0.1, 0.1)
AXIS = colors.Color(0.55, 0.55, 0.55)
ADVANCE = colors.Color(0.1, 0.35, 0.8)
FRAME = colors.Color(0.75, 0.75, 0.75)


class CanvasPathPen(BasePen):
    '''Draws a glyph into a reportlab canvas path. Quadratic curves are turned into
    cubic ones by BasePen.'''

    def __init__(self, glyphSet, path):
        super().__init__(glyphSet)
        self.path = path

    def _moveTo(self, p):
        self.path.moveTo(*p)

    def _lineTo(self, p):
        self.path.lineTo(*p)

    def _curveToOne(self, p1, p2, p3):
        self.path.curveTo(*p1, *p2, *p3)

    def _closePath(self):
        self.path.close()

    def _endPath(self):
        pass


def readGlyphList(path):
    names = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            names.extend(line.split('#', 1)[0].split())
    return names


def boundaryPoints(layer, name):
    '''The points of the glyph's boundary in the layer: its first contour, or None.'''
    if layer is None or name not in layer:
        return None
    for c in layer[name].contours:
        if len(c.points):
            return [(p.x, p.y) for p in c.points], c.open
    return None


def extents(font, layer, name):
    '''(xMin, yMin, xMax, yMax) of everything drawn for the glyph: the outline, the
    boundary, the origin and the advance.'''
    glyph = font[name]
    pen = BoundsPen(font.layers.defaultLayer)
    glyph.draw(pen)
    xs, ys = [0, glyph.width], [0]
    if pen.bounds:
        xs += [pen.bounds[0], pen.bounds[2]]
        ys += [pen.bounds[1], pen.bounds[3]]
    bp = boundaryPoints(layer, name)
    if bp:
        xs += [x for x, y in bp[0]]
        ys += [y for x, y in bp[0]]
    return min(xs), min(ys), max(xs), max(ys)


def padded(box):
    xMin, yMin, xMax, yMax = box
    pad = 0.01 * max(xMax - xMin, yMax - yMin, 1)     # keeps the frame off the boundary
    return xMin - pad, yMin - pad, xMax + pad, yMax + pad


def drawingArea(pagesize):
    pw, ph = pagesize
    return pw - 2 * PAGE_MARGIN, ph - 2 * PAGE_MARGIN - TITLE_HEIGHT


def fitScale(box, pagesize):
    '''Points per font unit at which the box (with its padding) just fills the page.'''
    xMin, yMin, xMax, yMax = padded(box)
    areaW, areaH = drawingArea(pagesize)
    return min(areaW / (xMax - xMin), areaH / (yMax - yMin))


def drawPage(c, font, layer, name, box, pagesize, scale=None):
    '''Draw one glyph on the current page. box is the extent (font units) the drawing
    area must hold; scale, if given, is the points per font unit to use.'''
    pw, ph = pagesize
    areaW, areaH = drawingArea(pagesize)
    xMin, yMin, xMax, yMax = padded(box)
    if scale is None:
        scale = fitScale(box, pagesize)
    # centre the box in the drawing area
    ox = PAGE_MARGIN + (areaW - (xMax - xMin) * scale) / 2 - xMin * scale
    oy = PAGE_MARGIN + (areaH - (yMax - yMin) * scale) / 2 - yMin * scale
    glyph = font[name]
    bp = boundaryPoints(layer, name)

    # title
    c.setFillColor(colors.black)
    c.setFont('Helvetica-Bold', 16)
    c.drawString(PAGE_MARGIN, ph - PAGE_MARGIN - 18, name)
    c.setFont('Helvetica', 9)
    info = [f'advance {round(glyph.width)}']
    if glyph.unicodes:
        info.append(' '.join(f'U+{u:04X}' for u in glyph.unicodes))
    if bp is None:
        info.append('no boundary')
    else:
        info.append(f'boundary: {len(bp[0])} points' + ('' if bp[1] else ', closed contour'))
    info.append(f'scale {scale * 1000:.1f} pt/1000 units')
    c.drawString(PAGE_MARGIN, ph - PAGE_MARGIN - 32, '   '.join(info))

    # frame around the drawing area
    frameX0, frameY0 = ox + xMin * scale, oy + yMin * scale
    frameX1, frameY1 = ox + xMax * scale, oy + yMax * scale
    c.setStrokeColor(FRAME)
    c.setLineWidth(0.5)
    c.setDash()
    c.rect(frameX0, frameY0, frameX1 - frameX0, frameY1 - frameY0)

    # axes, and the advance
    c.setStrokeColor(AXIS)
    c.setLineWidth(0.6)
    c.line(frameX0, oy, frameX1, oy)                    # y = 0, the baseline
    c.line(ox, frameY0, ox, frameY1)                    # x = 0, the origin
    c.setFillColor(AXIS)
    c.setFont('Helvetica', 7)
    c.drawString(ox + 2, frameY0 + 2, 'x=0')
    c.drawString(frameX0 + 2, oy + 2, 'y=0')
    ax = ox + glyph.width * scale
    c.setStrokeColor(ADVANCE)
    c.setDash(4, 3)
    c.line(ax, frameY0, ax, frameY1)
    c.setDash()
    c.setFillColor(ADVANCE)
    c.drawString(ax + 2, frameY1 - 9, f'advance {round(glyph.width)}')

    # the filled outline
    c.saveState()
    c.translate(ox, oy)
    c.scale(scale, scale)
    path = c.beginPath()
    glyph.draw(CanvasPathPen(font.layers.defaultLayer, path))
    c.setFillColor(INK)
    c.drawPath(path, stroke=0, fill=1, fillMode=FILL_NON_ZERO)
    c.restoreState()

    # the boundary: a line through its points, which are marked
    if bp:
        pts = [(ox + x * scale, oy + y * scale) for x, y in bp[0]]
        p = c.beginPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        if not bp[1]:
            p.close()
        c.setStrokeColor(BOUNDARY)
        c.setLineWidth(1)
        c.drawPath(p, stroke=1, fill=0)
        c.setFillColor(BOUNDARY)
        r = 1.6
        for x, y in pts:
            c.circle(x, y, r, stroke=0, fill=1)
        # mark the start (bottom of the left side) with a larger dot
        c.circle(pts[0][0], pts[0][1], 2 * r, stroke=0, fill=1)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('ufo', help='UFO with a PolyKern layer')
    p.add_argument('-o', '--output', required=True, help='PDF to write')
    p.add_argument('-g', '--glyphs', help='Glyph list (default: the glyphs in the layer, '
                   'in the UFO\'s glyph order)')
    p.add_argument('-l', '--layer', default=LAYER, help=f'Layer name (default: {LAYER})')
    p.add_argument('--fit', action='store_true', help='Scale each glyph to fill its page')
    p.add_argument('--pagesize', choices=sorted(PAGESIZES), default='A4')
    p.add_argument('--landscape', action='store_true')
    args = p.parse_args()

    font = ufoLib2.Font.open(args.ufo)
    layer = font.layers[args.layer] if args.layer in font.layers else None
    if args.glyphs:
        names = readGlyphList(args.glyphs)
    else:
        if layer is None:
            p.error(f'The UFO has no {args.layer} layer; give a glyph list (-g)')
        order = font.glyphOrder or sorted(font.keys())
        inLayer = set(layer.keys())
        names = [g for g in order if g in inLayer] + sorted(inLayer - set(order))
    missing = [g for g in names if g not in font]
    names = [g for g in names if g in font]
    if missing:
        print(f'Not in the UFO, left out: {" ".join(missing)}', file=sys.stderr)
    if not names:
        p.error('No glyphs to show')

    pagesize = PAGESIZES[args.pagesize]
    if args.landscape:
        pagesize = landscape(pagesize)
    boxes = {g: extents(font, layer, g) for g in names}
    # one scale for every page: the largest at which every glyph still fits its page
    common = min(fitScale(b, pagesize) for b in boxes.values())
    c = canvas.Canvas(args.output, pagesize=pagesize)
    c.setTitle(f'PolyKern boundaries: {os.path.basename(os.path.normpath(args.ufo))}')
    for g in names:
        drawPage(c, font, layer, g, boxes[g], pagesize, None if args.fit else common)
        c.showPage()
    c.save()
    print(f'{len(names)} pages written to {args.output}', file=sys.stderr)


if __name__ == '__main__':
    main()
