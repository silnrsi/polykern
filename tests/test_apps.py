#!/usr/bin/env python3
'''Tests for the boundary apps, tools/polykernglyphs.py and tools/polykernlayer.py, on a
small font and UFO made on the fly. Run with pytest.

The last test goes all the way from a UFO to a compiled font through feax. It is skipped
unless the installed feax has the PolyKern patch (dev/patches/feax-polykern.patch).
'''

import io
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', 'tools')
sys.path.insert(0, TOOLS)

import polykernlib                                          # noqa: E402,F401
from polykernlib.boundaries import boundaryOutline, makeBoundary, scriptGlyphs  # noqa: E402
from polykernlib.ufolayer import LAYER, updateLayer, layerPoints  # noqa: E402
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString as plainFea  # noqa: E402
from fontTools.fontBuilder import FontBuilder               # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen            # noqa: E402
from fontTools.ttLib import TTFont                          # noqa: E402
import ufoLib2                                              # noqa: E402


# ---- polykernglyphs

def makeTTF(path):
    '''A font with Arabic and Latin glyphs, and GSUB rules for each script.'''
    names = ['.notdef', 'space', 'A', 'A.sc', 'beh', 'beh.init', 'uni06DD', 'ayah.alt',
             'unused', 'zwj']
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({0x20: 'space', 0x41: 'A', 0x628: 'beh', 0x6DD: 'uni06DD',
                          0x200D: 'zwj'})
    glyphs = {}
    for g in names:
        pen = TTGlyphPen(None)
        if g not in ('space', 'zwj', '.notdef'):
            pen.moveTo((0, 0)); pen.lineTo((0, 500)); pen.lineTo((400, 500)); pen.lineTo((400, 0))
            pen.closePath()
        glyphs[g] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({g: (500, 0) for g in names})
    fb.setupHorizontalHeader()
    fb.setupNameTable({'familyName': 'Apps Test', 'styleName': 'Regular'})
    fb.setupOS2()
    fb.setupPost()
    plainFea(fb.font, 'languagesystem arab dflt;\nlanguagesystem latn dflt;\n'
             'feature init { script arab; sub beh by beh.init; } init;\n'
             'feature salt { script arab; sub uni06DD by ayah.alt; } salt;\n'
             'feature smcp { script latn; sub A by A.sc; } smcp;\n')
    fb.font.save(path)


class TestGlyphs:

    def test_script_closure(self, tmp_path):
        path = tmp_path / 'f.ttf'
        makeTTF(path)
        # U+06DD is Common, but in the Arabic block; zwj has no outline
        assert scriptGlyphs(TTFont(path), 'Arab') == ['beh', 'beh.init', 'uni06DD', 'ayah.alt']
        assert scriptGlyphs(TTFont(path), 'Latn') == ['A', 'A.sc']

    def test_cli(self, tmp_path):
        path = tmp_path / 'f.ttf'
        makeTTF(path)
        out = tmp_path / 'g.txt'
        subprocess.run([sys.executable, os.path.join(TOOLS, 'polykernglyphs.py'), str(path),
                        '-o', str(out)], check=True, capture_output=True)
        assert out.read_text().split() == ['beh', 'beh.init', 'uni06DD', 'ayah.alt']


# ---- boundary generation

class _Glyph:
    def __init__(self, contours):
        self.contours = contours

    def draw(self, pen):
        for c in self.contours:
            pen.moveTo(c[0])
            for p in c[1:]:
                pen.lineTo(p)
            pen.closePath()


def cShape(gapDegrees, R=400, r=250, cx=500, cy=400, n=48):
    '''A c: a ring with a gap of gapDegrees centred on the right.'''
    import math
    a0, a1 = math.radians(gapDegrees / 2), math.radians(360 - gapDegrees / 2)
    outer = [(cx + R * math.cos(a0 + (a1 - a0) * i / n), cy + R * math.sin(a0 + (a1 - a0) * i / n))
             for i in range(n + 1)]
    inner = [(cx + r * math.cos(a1 - (a1 - a0) * i / n), cy + r * math.sin(a1 - (a1 - a0) * i / n))
             for i in range(n + 1)]
    return _Glyph([[(round(x), round(y)) for x, y in outer + inner]])


def _xAt(points, y):
    '''x at height y on a side of a boundary.'''
    pts = sorted(points, key=lambda p: p[1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 <= y <= y1:
            return x0 if y1 == y0 else x0 + (y - y0) * (x1 - x0) / (y1 - y0)


class TestBoundaryGeneration:

    def test_closed_mouth_is_filled(self):
        '''A c whose mouth (139 units high at the outside) is closed up by a 125 margin:
        the right side barely goes into it.'''
        b = makeBoundary({'c': cShape(20)}, 'c', margin=125)
        assert max(x for x, y in b.right) - _xAt(b.right, 400) < 40

    def test_open_mouth_is_kept(self):
        '''A c whose mouth (566 units high at the outside) stays open: the right side goes
        into it, but only as far as it is at least twice the margin high.'''
        b = makeBoundary({'c': cShape(90)}, 'c', margin=125)
        x = _xAt(b.right, 400)
        assert x < max(x for x, y in b.right) - 50
        # a 2m-thick end fits no further in than where the mouth narrows to 2m
        assert x > _xAt(makeBoundary({'c': cShape(90)}, 'c', margin=125, closeGap=0).right, 400)

    def test_narrow_notches_filled(self):
        '''Filling notches less than 2m high only ever moves the boundary out.'''
        for gap in (20, 40, 60, 90):
            # without simplification, which can move a side a unit or two either way
            closed = makeBoundary({'c': cShape(gap)}, 'c', margin=125, maxArea=0)
            open_ = makeBoundary({'c': cShape(gap)}, 'c', margin=125, maxArea=0, closeGap=0)
            for y in range(0, 800, 25):
                a, b = _xAt(closed.right, y), _xAt(open_.right, y)
                if a is not None and b is not None:
                    assert a >= b - 1e-6
            assert _xAt(closed.right, 400) > _xAt(open_.right, 400)

    def test_integer_points(self):
        '''Boundaries go into FEA and the font, so every coordinate is a whole number,
        including where a notch has been filled.'''
        for gap in (20, 40, 60, 90):
            b = makeBoundary({'c': cShape(gap)}, 'c', margin=125)
            assert all(isinstance(v, int) for p in b.left + b.right for v in p)

    def test_curve_not_cut(self):
        '''A boundary follows a curve closely but never cuts into it: the split control
        polygon is always outside the curve. A cubic arch from x=0 to 1000, 600 high.'''
        import math

        class Arch:
            def draw(self, pen):
                pen.moveTo((0, 0))
                pen.curveTo((0, 800), (1000, 800), (1000, 0))
                pen.closePath()
        def top(t):                     # the curve at parameter t
            mt = 1 - t
            return (3 * mt * t * t * 1000 + t ** 3 * 1000, 3 * mt * mt * t * 800 + 3 * mt * t * t * 800)
        b = makeBoundary({'g': Arch()}, 'g', margin=0, maxArea=0, closeGap=0)
        b0 = makeBoundary({'g': Arch()}, 'g', margin=0, maxArea=0, closeGap=0, tolerance=math.inf)
        assert max(y for x, y in b.left) <= 600 + 2           # close: the curve peaks at 600
        assert max(y for x, y in b0.left) == 800             # the control points stick out
        for i in range(1, 50):
            x, y = top(i / 100)                                # left half of the arch
            if y < max(p[1] for p in b.left):
                # at or left of the curve, to within 1 unit for rounding y to whole units
                assert _xAt(b.left, y) <= x + 1

    def test_spike_rounded(self):
        '''The end of a thin spike is rounded at the margin: it reaches just the margin
        beyond the tip, and every point of the end is at least the margin from the tip.'''
        import math
        spike = _Glyph([[(0, 0), (0, 100), (1000, 50)]])
        b = makeBoundary({'s': spike}, 's', margin=125, maxArea=0, closeGap=0, tolerance=2)
        assert 1000 + 125 - 1 <= max(x for x, y in b.right) <= 1000 + 125 + 2
        assert all(math.hypot(x - 1000, y - 50) >= 125 - 1 for x, y in b.right if x > 1000)

    def test_outline_doubling_back(self):
        '''An outline that runs straight back on itself (as a control polygon can) is
        capped round the far end of the reversal, not through the glyph.'''
        g = _Glyph([[(0, 0), (0, 344), (0, 342), (0, 362), (0, 600), (300, 600), (300, 0)]])
        b = makeBoundary({'g': g}, 'g', margin=100, maxArea=0, closeGap=0)
        assert all(x <= -99 for x, y in b.left if 0 <= y <= 600)

    def test_corners_rounded(self):
        '''Corners are rounded at the margin: no point of a square's boundary is more than
        the margin plus the tolerance from the square, or less than the margin.'''
        import math
        sq = _Glyph([[(0, 0), (0, 400), (400, 400), (400, 0)]])
        b = makeBoundary({'s': sq}, 's', margin=100, maxArea=0, closeGap=0, tolerance=2)
        def dist(x, y):
            dx = max(0 - x, 0, x - 400); dy = max(0 - y, 0, y - 400)
            return math.hypot(dx, dy)
        for x, y in b.left + b.right:
            assert 100 - 1 <= dist(x, y) <= 100 + 2 + 1

    def test_no_jump_at_threshold(self):
        '''Corners just either side of 90 degrees reach the same distance: nothing jumps.'''
        import math
        reach = []
        for deg in (89.5, 90.5):
            h = 500 * math.tan(math.radians(deg / 2))     # isosceles corner pointing right
            g = _Glyph([[(0, -h), (0, h), (500, 0)]])
            # the corner at (500, 0) has angle 2 * atan(h / 500)
            b = makeBoundary({'g': g}, 'g', margin=100, maxArea=0, closeGap=0)
            reach.append(max(x for x, y in b.right))
        assert abs(reach[0] - reach[1]) <= 3


# ---- polykernlayer

def makeUFO(path):
    '''A UFO with a base, a composite, a mark (with an _ anchor) and a space.'''
    font = ufoLib2.Font()
    def box(name, x0, y0, x1, y1, width=500):
        g = font.newGlyph(name)
        g.width = width
        pen = g.getPen()
        pen.moveTo((x0, y0)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y0))
        pen.closePath()
        return g
    box('beh', 50, 0, 450, 300)
    box('fatha', 100, 600, 300, 700, width=0).appendAnchor({'name': '_top', 'x': 200, 'y': 550})
    comp = font.newGlyph('behfatha')
    comp.width = 500
    comp.getPen().addComponent('beh', (1, 0, 0, 1, 0, 0))
    comp.getPen().addComponent('fatha', (1, 0, 0, 1, 50, 0))
    font.newGlyph('space').width = 250
    font.save(path)


class TestLayer:

    def test_create(self, tmp_path):
        path = tmp_path / 'f.ufo'
        makeUFO(path)
        font = ufoLib2.Font.open(path)
        report = updateLayer(font, ['beh', 'behfatha', 'fatha', 'space', 'nope'], margin=100,
                             markMargin=40)
        assert report['created'] == ['beh', 'behfatha', 'fatha']
        assert report['empty'] == ['space'] and report['missing'] == ['nope']
        layer = font.layers[LAYER]
        for name in ('beh', 'behfatha', 'fatha'):
            g = layer[name]
            assert len(g.contours) == 1 and g.contours[0].open      # not closed: not filled
            assert g.width == font[name].width
        # the points are the generated boundary, left side then right side
        b = makeBoundary(font.layers.defaultLayer, 'beh', 100)
        assert layerPoints(layer['beh']) == boundaryOutline(b)
        assert layerPoints(layer['beh'])[0] == b.left[0] and layerPoints(layer['beh'])[-1] == b.right[-1]
        # the composite's boundary covers both components; the mark has the smaller margin
        ys = [y for x, y in layerPoints(layer['behfatha'])]
        assert min(ys) <= -100 and max(ys) >= 800
        xs = [x for x, y in layerPoints(layer['fatha'])]
        assert min(xs) >= 100 - 40 - 1 and max(xs) <= 300 + 40 + 1

    def test_rerun_follows_outlines(self, tmp_path):
        path = tmp_path / 'f.ufo'
        makeUFO(path)
        font = ufoLib2.Font.open(path)
        updateLayer(font, ['beh', 'fatha'])
        assert updateLayer(font)['unchanged'] == ['beh', 'fatha']
        # change an outline: with no list, every glyph in the layer is remade
        font['beh'].contours[0].points[1].y = 400
        report = updateLayer(font)
        assert report['updated'] == ['beh'] and report['unchanged'] == ['fatha']

    def test_list_limits_what_changes(self, tmp_path):
        '''A hand-edited boundary is kept by leaving it out of the list.'''
        path = tmp_path / 'f.ufo'
        makeUFO(path)
        font = ufoLib2.Font.open(path)
        updateLayer(font, ['beh', 'fatha'])
        font.layers[LAYER]['fatha'].contours[0].points[1].x -= 30
        edited = layerPoints(font.layers[LAYER]['fatha'])
        font['beh'].contours[0].points[1].y = 400
        report = updateLayer(font, ['beh'])
        assert report['updated'] == ['beh']
        assert layerPoints(font.layers[LAYER]['fatha']) == edited

    def test_cli(self, tmp_path):
        path = tmp_path / 'f.ufo'
        makeUFO(path)
        tool = os.path.join(TOOLS, 'polykernlayer.py')
        r = subprocess.run([sys.executable, tool, str(path)], capture_output=True, text=True)
        assert r.returncode != 0 and 'give a glyph list' in r.stderr
        glyphs = tmp_path / 'g.txt'
        glyphs.write_text('beh  # a comment\nfatha behfatha\n')
        out = tmp_path / 'out.ufo'
        r = subprocess.run([sys.executable, tool, str(path), '-g', str(glyphs), '-o', str(out),
                            '-m', '8'], capture_output=True, text=True, check=True)
        assert 'created: 3' in r.stdout
        assert set(ufoLib2.Font.open(out).layers[LAYER].keys()) == {'beh', 'fatha', 'behfatha'}
        assert LAYER not in ufoLib2.Font.open(path).layers            # input left alone


# ---- all the way through feax

def patchedFeax():
    try:
        import feaxlib
    except ImportError:
        return None
    return feaxlib if hasattr(feaxlib, 'contour_to_polyboundary') else None


@pytest.mark.skipif(patchedFeax() is None, reason='feax without the PolyKern patch')
def test_ufo_to_font(tmp_path):
    '''UFO -> polykernlayer -> feax (polykern;) -> polykernlib compiler: the compiled
    boundaries are the ones in the layer.'''
    feaxlib = patchedFeax()
    from polykernlib.feabuilder import addOpenTypeFeaturesFromString
    path = tmp_path / 'f.ufo'
    makeUFO(path)
    font = ufoLib2.Font.open(path)
    updateLayer(font, ['beh', 'behfatha', 'fatha'], margin=100, markMargin=40)
    font.save()
    feax = tmp_path / 'f.feax'
    feax.write_text('languagesystem DFLT dflt;\nlookup PolyKern {\n    polykern;\n} PolyKern;\n'
                    'polykernlookups kern PolyKern {\n    pos beh beh -20;\n};\n')
    fea = feaxlib.feax_get_features(ufoLib2.Font.open(path), feaxfile=str(feax))
    assert 'pos polymark fatha' in fea and 'pos polybase space <polyboundary NULL>;' in fea
    assert '} else {' in fea and 'lookup GPOS 10 1;' in fea

    fb = FontBuilder(1000, isTTF=True)
    order = ['.notdef'] + sorted(font.keys())
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({})
    fb.setupGlyf({g: TTGlyphPen(None).glyph() for g in order})
    fb.setupHorizontalMetrics({g: (500, 0) for g in order})
    fb.setupHorizontalHeader()
    fb.setupNameTable({'familyName': 'Apps Test', 'styleName': 'Regular'})
    fb.setupOS2()
    fb.setupPost()
    addOpenTypeFeaturesFromString(fb.font, fea)
    buf = io.BytesIO()
    fb.font.save(buf)
    ttf = TTFont(io.BytesIO(buf.getvalue()))
    st = [l.SubTable[0] for l in ttf['GPOS'].table.LookupList.Lookup if l.LookupType == 10][0]
    layer = font.layers[LAYER]
    for g, b in zip(st.BoundaryCoverage.glyphs, st.Boundary):
        compiled = [(p.x, p.y) for p in b.LeftPoint] + [(p.x, p.y) for p in b.RightPoint]
        assert compiled == layerPoints(layer[g])
    assert st.AttachedCoverage.glyphs == ['fatha']
    assert st.BaseCoverage.glyphs == sorted(['beh', 'behfatha', 'space'], key=order.index)


# ---- matching a compiled font's glyphs to the UFO by shape

def test_map_to_ufo(tmp_path):
    from polykernlib.boundaries import mapToUfo
    path = tmp_path / 'f.ufo'
    makeUFO(path)
    ufo = ufoLib2.Font.open(path)
    comp = ufo.newGlyph('_dot')         # a component glyph, the same shape as fatha
    comp.width = 0
    ufo['fatha'].draw(comp.getPen())
    # a compiled font with other glyph names: g1 is beh; g2 is fatha with another advance;
    # g3 matches nothing; beh is named as in the UFO
    fb = FontBuilder(1000, isTTF=True)
    order = ['.notdef', 'g1', 'g2', 'g3', 'beh']
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({})
    layer = ufo.layers.defaultLayer
    glyphs = {}
    for name, source in (('.notdef', None), ('g1', 'beh'), ('g2', 'fatha'), ('g3', None),
                         ('beh', 'beh')):
        pen = TTGlyphPen(layer)
        if source:
            ufo[source].draw(pen)
        elif name == 'g3':
            pen.moveTo((0, 0)); pen.lineTo((0, 9)); pen.lineTo((9, 9)); pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({'.notdef': (500, 0), 'g1': (500, 50), 'g2': (77, 100),
                               'g3': (10, 0), 'beh': (500, 50)})
    fb.setupHorizontalHeader()
    fb.setupNameTable({'familyName': 'Map Test', 'styleName': 'Regular'})
    fb.setupOS2()
    fb.setupPost()
    names, missing = mapToUfo(fb.font, ['g1', 'g2', 'g3', 'beh'], ufo)
    assert set(names) == {'beh', 'fatha'} and missing == ['g3']
    names, missing = mapToUfo(fb.font, ['g2'], ufo, exclude='')
    assert set(names) == {'fatha', '_dot'}          # glyphs drawn the same all match


# ---- polykernproof

def test_proof(tmp_path):
    path = tmp_path / 'f.ufo'
    makeUFO(path)
    font = ufoLib2.Font.open(path)
    updateLayer(font, ['beh', 'behfatha', 'fatha'])
    font.save()
    tool = os.path.join(TOOLS, 'polykernproof.py')
    for extra in ([], ['--fit'], ['--pagesize', 'letter', '--landscape']):
        out = tmp_path / 'p.pdf'
        subprocess.run([sys.executable, tool, str(path), '-o', str(out)] + extra, check=True,
                       capture_output=True)
        data = out.read_bytes()
        assert data.startswith(b'%PDF')
        pages = data.count(b'/Type /Page\n') + data.count(b'/Type /Page ') + \
            data.count(b'/Type /Page/') + data.count(b'/Type /Page>')
        try:
            import pypdf
            pages = len(pypdf.PdfReader(str(out)).pages)
        except ImportError:
            pass
        assert pages == 3
    # glyphs from a list, including one with no boundary and one not in the UFO
    glyphs = tmp_path / 'g.txt'
    glyphs.write_text('space beh nope\n')
    r = subprocess.run([sys.executable, tool, str(path), '-o', str(out), '-g', str(glyphs)],
                       check=True, capture_output=True, text=True)
    assert '2 pages' in r.stderr and 'nope' in r.stderr
