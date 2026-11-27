'''Write PolyKern boundaries into a UFO layer.

Each boundary is one open contour in the layer: up the left side from the bottom, then
down the right side, with no line back to the start, so it is not filled.
'''

from .boundaries import boundaryOutline, makeBoundary

LAYER = 'org.sil.polykern'


def layerPoints(glyph):
    '''The points of the glyph's first contour, as a list of (x, y), or None.'''
    for contour in glyph.contours:
        if len(contour.points):
            return [(p.x, p.y) for p in contour.points]
    return None


def writeBoundaryGlyph(layer, name, points, width):
    '''Replace the layer's glyph with an open contour through the points.'''
    if name in layer:
        glyph = layer[name]
        glyph.clearContours()
        glyph.clearComponents()
    else:
        glyph = layer.newGlyph(name)
    pen = glyph.getPointPen()
    pen.beginPath()
    for i, p in enumerate(points):
        pen.addPoint(p, segmentType='move' if i == 0 else 'line')
    pen.endPath()
    glyph.width = width


def isAttached(glyph):
    '''A glyph that attaches to another (it has an anchor whose name starts with _).'''
    return any(a.name and a.name.startswith('_') for a in glyph.anchors)


def updateLayer(font, glyphs=None, margin=200, markMargin=None, maxError=7.5,
                layerName=LAYER, tolerance=2.5):
    '''Make boundaries for the glyphs from their outlines and write them into the font's
    layer, creating it if needed. Whatever the layer had for those glyphs is replaced.

    font: a ufoLib2 Font.
    glyphs: names, in the order to process them. By default, the glyphs already in the
        layer, so that their boundaries follow any changes to the outlines.
    markMargin: the margin for attached glyphs (marks); by default the same as margin.
    maxError, tolerance: how far the simplified boundary may be from the emboldened
        outline, and the lines that replace curves from the curves, as percentages of each
        glyph's margin (by default 7.5 and 2.5; see boundaries.makeBoundary).
    Returns {result: [glyph names]}, where result is one of created, updated, unchanged,
    empty (no outline, so no boundary) and missing (not in the UFO).
    '''
    if markMargin is None:
        markMargin = margin
    default = font.layers.defaultLayer
    exists = layerName in font.layers
    layer = font.layers[layerName] if exists else font.newLayer(layerName)
    if glyphs is None:
        glyphs = list(layer.keys())
    report = {k: [] for k in ('created', 'updated', 'unchanged', 'empty', 'missing')}
    for name in glyphs:
        if name not in default:
            report['missing'].append(name)
            continue
        source = default[name]
        m = markMargin if isAttached(source) else margin
        boundary = makeBoundary(default, name, m, tolerance=tolerance * m / 100,
                                maxError=maxError * m / 100)
        if boundary is None:
            report['empty'].append(name)
            continue
        points = boundaryOutline(boundary)
        old = layer[name] if name in layer else None
        if old is not None and layerPoints(old) == points and len(old.contours) == 1 \
                and old.contours[0].points[0].type == 'move' and old.width == source.width:
            report['unchanged'].append(name)
            continue
        writeBoundaryGlyph(layer, name, points, source.width)
        report['updated' if old is not None else 'created'].append(name)
    return report
