#!/usr/bin/env python3
'''Unit tests for tools/polykernlib, using a small font made on the fly. Run with pytest.

The slower tests against Awami Nastaliq are compiletest.py and featest.py.
'''

import io
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', 'tools')
sys.path.insert(0, TOOLS)

import polykernlib                                      # noqa: E402 installs the tables
from polykernlib.otlbuilder import (PolyBoundary, PolyKernBuilder,  # noqa: E402
                                    addConditionalFeature, buildLookupSupportCondition,
                                    buildPolyPosSubtable)
from polykernlib.feabuilder import addOpenTypeFeaturesFromString  # noqa: E402
from polykernlib.feaparser import Parser                # noqa: E402
from polykernlib.feawriter import polykernLookupFea, outlineOf  # noqa: E402
from fontTools.feaLib.error import FeatureLibError      # noqa: E402
from fontTools.fontBuilder import FontBuilder           # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen        # noqa: E402
from fontTools.ttLib import TTFont                      # noqa: E402

GLYPHS = ['.notdef', 'space', 'a', 'v', 'beh', 'reh', 'alef', 'fatha', 'behmedi', 'empty']


def makeFont():
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(GLYPHS)
    fb.setupCharacterMap({0x20: 'space', 0x61: 'a', 0x76: 'v', 0x628: 'beh', 0x631: 'reh',
                          0x627: 'alef', 0x64E: 'fatha'})
    glyphs = {}
    for g in GLYPHS:
        pen = TTGlyphPen(None)
        if g not in ('space', 'empty'):
            pen.moveTo((0, 0)); pen.lineTo((0, 500)); pen.lineTo((400, 500)); pen.lineTo((400, 0))
            pen.closePath()
        glyphs[g] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({g: (500, 0) for g in GLYPHS})
    fb.setupHorizontalHeader()
    fb.setupNameTable({'familyName': 'PolyKern Test', 'styleName': 'Regular'})
    fb.setupOS2()
    fb.setupPost()
    return fb.font


def roundTrip(font):
    buf = io.BytesIO()
    font.save(buf)
    return TTFont(io.BytesIO(buf.getvalue()))


def compileFea(fea):
    font = makeFont()
    addOpenTypeFeaturesFromString(font, fea)
    return roundTrip(font)


def polyPos(font):
    for l in font['GPOS'].table.LookupList.Lookup:
        st = l.SubTable[0]
        if l.LookupType == 9 and st.ExtensionLookupType == 10:
            return st.ExtSubTable
        if l.LookupType == 10:
            return st
    return None


def points(ps):
    return [(p.x, p.y) for p in ps]


HEAD = 'languagesystem DFLT dflt;\nlanguagesystem arab dflt;\n'
BOX = '<polyboundary 0 -100, 50 600, 350 600, 400 -100>'
PK = ('lookup PK {\n    pos polybase [beh reh] ' + BOX + ';\n'
      '    pos polybase space <polyboundary NULL>;\n'
      '    pos polymark [fatha behmedi] <polyboundary 100 550, 120 750, 280 750, 300 550>;\n'
      '    pos polymark empty <polyboundary NULL>;\n} PK;\n')


# ---- PolyBoundary

class TestPolyBoundary:

    def test_split_single_top(self):
        b = PolyBoundary.fromOutline([(0, 0), (30, 100), (60, 0)])
        assert b.left == [(0, 0), (30, 100)] and b.right == [(30, 100), (60, 0)]

    def test_split_flat_top_uses_extremes(self):
        b = PolyBoundary.fromOutline([(0, 0), (10, 100), (50, 100), (30, 100), (60, 0)])
        assert b.left == [(0, 0), (10, 100)]
        assert b.right == [(50, 100), (30, 100), (60, 0)]

    def test_split_wrong_way_round(self):
        with pytest.raises(ValueError, match='up the left side'):
            PolyBoundary.fromOutline([(60, 0), (50, 100), (10, 100), (0, 0)])

    def test_check(self):
        PolyBoundary([(0, 0), (0, 10)], [(5, 10), (5, 0)]).check()
        with pytest.raises(ValueError, match='at least 2'):
            PolyBoundary([(0, 0)], [(5, 10), (5, 0)]).check()
        with pytest.raises(ValueError, match='left polyline goes down'):
            PolyBoundary([(0, 0), (0, 10), (0, 5)], [(5, 10), (5, 0)]).check()
        with pytest.raises(ValueError, match='right polyline goes up'):
            PolyBoundary([(0, 0), (0, 10)], [(5, 0), (5, 10)]).check()
        with pytest.raises(ValueError, match='more than 255'):
            PolyBoundary([(0, y) for y in range(256)], [(5, 10), (5, 0)]).check()

    def test_horizontal_segments_allowed(self):
        PolyBoundary([(0, 0), (10, 0), (10, 10)], [(5, 10), (0, 10), (0, 0)]).check()

    def test_bbox_and_equality(self):
        a = PolyBoundary([(0, -5), (2, 10)], [(8, 12), (9, 0)])
        assert a.bbox == (0, -5, 9, 12)
        assert a == PolyBoundary([(0, -5), (2, 10)], [(8, 12), (9, 0)])
        assert len({a, PolyBoundary([(0, -5), (2, 10)], [(8, 12), (9, 0)])}) == 1


# ---- otlLib-level builder and the binary table

class TestBuilder:

    def build(self):
        font = makeFont()
        pk = PolyKernBuilder(font, None)
        box = PolyBoundary.fromOutline([(0, -100), (50, 600), (350, 600), (400, -100)])
        pk.add_base(None, ['beh', 'reh'], box)
        pk.add_base(None, ['space'], None)
        pk.add_attached(None, ['fatha'], PolyBoundary.fromOutline([(100, 550), (300, 750), (300, 550)]))
        pk.add_attached(None, ['empty'], None)
        return font, pk

    def test_coverages(self):
        font, pk = self.build()
        st = pk.build().SubTable[0]
        assert st.BoundaryCoverage.glyphs == ['beh', 'reh', 'fatha']
        assert st.BaseCoverage.glyphs == ['space', 'beh', 'reh']
        assert st.AttachedCoverage.glyphs == ['fatha', 'empty']
        assert st.BoundaryCount == 3 and st.VarIndexBases is None

    def test_shared_boundary_written_once(self):
        '''A second glyph sharing a boundary adds 6 bytes: one coverage entry (the boundary
        and base coverage tables are the same, so fontTools writes them once) and one
        offset. Another boundary structure would add 28 more.'''
        box = PolyBoundary.fromOutline([(0, -100), (50, 600), (350, 600), (400, -100)])
        sizes = []
        for glyphs in (['beh'], ['beh', 'reh']):
            font = makeFont()
            pk = PolyKernBuilder(font, None)
            pk.add_base(None, glyphs, box)
            lookup = pk.build()
            if len(glyphs) == 2:
                assert lookup.SubTable[0].Boundary[0] is lookup.SubTable[0].Boundary[1]
            addGPOS(font, [lookup])
            sizes.append(len(font['GPOS'].compile(font)))
        assert sizes[1] - sizes[0] == 2 + 4

    def test_bounding_box(self):
        font, pk = self.build()
        addGPOS(font, [pk.build()])
        b = polyPos(roundTrip(font)).Boundary[0]
        assert points([b.MinPoint, b.MaxPoint]) == [(0, -100), (400, 600)]

    def test_errors(self):
        font, pk = self.build()
        with pytest.raises(FeatureLibError, match='already a base'):
            pk.add_attached(None, ['beh'], None)
        with pytest.raises(FeatureLibError, match='already a mark'):
            pk.add_base(None, ['fatha'], None)
        with pytest.raises(FeatureLibError, match='different boundary'):
            pk.add_base(None, ['beh'], None)
        with pytest.raises(FeatureLibError, match='more than one subtable'):
            pk.add_subtable_break(None)
        pk.add_base(None, ['beh'], pk.bases['beh'])     # the same again is fine

    def test_both_roles_in_subtable_builder(self):
        with pytest.raises(ValueError, match='both base and attached'):
            buildPolyPosSubtable({'beh': None}, {'beh': None}, makeFont().getReverseGlyphMap())


def addGPOS(font, lookups):
    '''Give the font a GPOS with the lookups and a kern feature that uses none of them.'''
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables import otTables as ot
    gpos = newTable('GPOS')
    t = gpos.table = ot.GPOS()
    t.Version = 0x00010000
    t.LookupList = ot.LookupList()
    t.LookupList.Lookup = list(lookups)
    t.LookupList.LookupCount = len(lookups)
    t.FeatureList = ot.FeatureList()
    fr = ot.FeatureRecord()
    fr.FeatureTag = 'kern'
    fr.Feature = ot.Feature()
    fr.Feature.FeatureParams = None
    fr.Feature.LookupListIndex = []
    fr.Feature.LookupCount = 0
    t.FeatureList.FeatureRecord = [fr]
    t.FeatureList.FeatureCount = 1
    t.ScriptList = ot.ScriptList()
    sr = ot.ScriptRecord()
    sr.ScriptTag = 'DFLT'
    sr.Script = ot.Script()
    ls = sr.Script.DefaultLangSys = ot.DefaultLangSys()
    ls.LookupOrder = None
    ls.ReqFeatureIndex = 0xFFFF
    ls.FeatureIndex = [0]
    ls.FeatureCount = 1
    sr.Script.LangSysRecord = []
    sr.Script.LangSysCount = 0
    t.ScriptList.ScriptRecord = [sr]
    t.ScriptList.ScriptCount = 1
    font['GPOS'] = gpos
    return None


# ---- conditions

class TestConditions:

    def test_condition_in_font_without_fvar(self):
        font = makeFont()
        pk = PolyKernBuilder(font, None)
        pk.add_base(None, ['beh'], None)
        addGPOS(font, [pk.build()])
        gpos = font['GPOS'].table
        addConditionalFeature(gpos, 'kern', [buildLookupSupportCondition(10, 1)], [0])
        f2 = roundTrip(font)
        rec = f2['GPOS'].table.FeatureVariations.FeatureVariationRecord[0]
        c = rec.ConditionSet.ConditionTable[0]
        assert (c.Format, c.LookupType, c.SubtableFormat) == (6, 10, 1)
        assert rec.FeatureTableSubstitution.SubstitutionRecord[0].Feature.LookupListIndex == [0]
        assert 'fvar' not in f2

    def test_new_feature_added(self):
        font = makeFont()
        pk = PolyKernBuilder(font, None)
        pk.add_base(None, ['beh'], None)
        addGPOS(font, [pk.build()])
        gpos = font['GPOS'].table
        addConditionalFeature(gpos, 'dist', [buildLookupSupportCondition(10, 1)], [0])
        tags = [fr.FeatureTag for fr in gpos.FeatureList.FeatureRecord]
        assert tags == ['dist', 'kern']
        assert gpos.ScriptList.ScriptRecord[0].Script.DefaultLangSys.FeatureIndex == [0, 1]

    def test_same_conditions_merge(self):
        font = makeFont()
        pk = PolyKernBuilder(font, None)
        pk.add_base(None, ['beh'], None)
        addGPOS(font, [pk.build()])
        gpos = font['GPOS'].table
        addConditionalFeature(gpos, 'kern', [buildLookupSupportCondition(10, 1)], [0])
        addConditionalFeature(gpos, 'dist', [buildLookupSupportCondition(10, 1)], [0])
        assert gpos.FeatureVariations.FeatureVariationCount == 1
        subs = gpos.FeatureVariations.FeatureVariationRecord[0].FeatureTableSubstitution
        assert subs.SubstitutionCount == 2

    def test_ttx(self):
        font = compileFea(HEAD + PK + 'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { } kern;\nvariation kern C replace { lookup PK; } kern;\n')
        out = io.StringIO()
        font.saveXML(out, tables=['GPOS'])
        xml = out.getvalue()
        assert '<LeftPoint index="0" x="0" y="-100"/>' in xml
        assert '<!-- LeftPointCount=2 -->' in xml
        assert '<ConditionTable index="0" Format="6">' in xml
        f2 = TTFont()
        f2.setGlyphOrder(font.getGlyphOrder())
        f2.importXML(io.StringIO(xml))
        out2 = io.StringIO()
        f3 = roundTrip(f2)
        f3.setGlyphOrder(font.getGlyphOrder())
        f3.saveXML(out2, tables=['GPOS'])
        strip = lambda x: x[x.index('<GPOS>'):]
        assert strip(out2.getvalue()) == strip(xml)


# ---- FEA

def kinds(font):
    '''A short name for each lookup, from what it does.'''
    res = []
    for l in font['GPOS'].table.LookupList.Lookup:
        st = l.SubTable[0]
        if l.LookupType == 10:
            res.append('PK')
        else:
            res.append('+'.join(st.Coverage.glyphs))
    return res


def featureLookups(font, tag):
    g = font['GPOS'].table
    k = kinds(font)
    default = [fr.Feature.LookupListIndex for fr in g.FeatureList.FeatureRecord
               if fr.FeatureTag == tag][0]
    supported = None
    if getattr(g, 'FeatureVariations', None):
        for rec in g.FeatureVariations.FeatureVariationRecord:
            for sr in rec.FeatureTableSubstitution.SubstitutionRecord:
                if g.FeatureList.FeatureRecord[sr.FeatureIndex].FeatureTag == tag:
                    supported = sorted(k[i] for i in sr.Feature.LookupListIndex)
    return sorted(k[i] for i in default), supported


class TestFea:

    def test_polykern_statements(self):
        st = polyPos(compileFea(HEAD + PK))
        assert st.BoundaryCoverage.glyphs == ['beh', 'reh', 'fatha', 'behmedi']
        assert st.BaseCoverage.glyphs == ['space', 'beh', 'reh']
        assert st.AttachedCoverage.glyphs == ['fatha', 'behmedi', 'empty']
        assert points(st.Boundary[0].LeftPoint) == [(0, -100), (50, 600)]
        assert points(st.Boundary[0].RightPoint) == [(350, 600), (400, -100)]

    def test_else(self):
        font = compileFea(HEAD + PK +
                          'lookup Latin { pos a v -40; } Latin;\n'
                          'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { lookup Latin; } kern;\n'
                          'variation kern C { lookup PK; } else { pos beh reh -50; } kern;\n')
        assert featureLookups(font, 'kern') == (['a', 'beh'], ['PK', 'a'])

    def test_replace_all(self):
        font = compileFea(HEAD + PK + 'lookup Latin { pos a v -40; } Latin;\n'
                          'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { lookup Latin; } kern;\n'
                          'variation kern C replace { lookup PK; } kern;\n')
        assert featureLookups(font, 'kern') == (['a'], ['PK'])

    def test_replace_named(self):
        font = compileFea(HEAD + PK + 'lookup Latin { pos a v -40; } Latin;\n'
                          'lookup Fallback { pos beh reh -50; } Fallback;\n'
                          'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { pos alef beh -5; lookup Latin; lookup Fallback; } kern;\n'
                          'variation kern C replace Fallback { lookup PK; } kern;\n')
        assert featureLookups(font, 'kern') == (['a', 'alef', 'beh'], ['PK', 'a', 'alef'])

    def test_plain_variation_adds(self):
        font = compileFea(HEAD + PK + 'lookup Latin { pos a v -40; } Latin;\n'
                          'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { lookup Latin; } kern;\n'
                          'variation kern C { lookup PK; } kern;\n')
        assert featureLookups(font, 'kern') == (['a'], ['PK', 'a'])

    def test_else_with_scripts(self):
        '''script statements in the blocks: only Arabic swaps its fallback for PolyKern.'''
        font = compileFea(HEAD.replace('arab', 'latn') + 'languagesystem arab dflt;\n' + PK +
                          'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { script latn; pos a v -40; } kern;\n'
                          'variation kern C { script arab; lookup PK; } else '
                          '{ script arab; pos beh reh -50; } kern;\n')
        g = font['GPOS'].table
        k = kinds(font)
        subst = {}
        for rec in g.FeatureVariations.FeatureVariationRecord:
            for sr in rec.FeatureTableSubstitution.SubstitutionRecord:
                subst[sr.FeatureIndex] = sorted(k[i] for i in sr.Feature.LookupListIndex)
        res = {}
        for sr in g.ScriptList.ScriptRecord:
            for fi in sr.Script.DefaultLangSys.FeatureIndex:
                fr = g.FeatureList.FeatureRecord[fi]
                if fr.FeatureTag == 'kern':
                    res[sr.ScriptTag] = (sorted(k[i] for i in fr.Feature.LookupListIndex),
                                         subst.get(fi))
        assert res['latn'][0] == ['a'] and res['latn'][1] in (None, ['a'])
        assert res['arab'] == (['beh'], ['PK'])

    def test_shared_feature_split(self):
        '''DFLT and arab share a kern feature record, but only arab has PolyKern: the record
        is split so that DFLT keeps its lookups when PolyKern is supported.'''
        font = compileFea(HEAD + PK + 'lookup Latin { pos a v -40; } Latin;\n'
                          'conditionset C { lookup GPOS 10 1; } C;\n'
                          'feature kern { lookup Latin; } kern;\n'
                          'variation kern C { script arab; lookup PK; } kern;\n')
        g = font['GPOS'].table
        k = kinds(font)
        subst = {}
        for rec in g.FeatureVariations.FeatureVariationRecord:
            for sr in rec.FeatureTableSubstitution.SubstitutionRecord:
                subst[sr.FeatureIndex] = sorted(k[i] for i in sr.Feature.LookupListIndex)
        res = {}
        for sr in g.ScriptList.ScriptRecord:
            for fi in sr.Script.DefaultLangSys.FeatureIndex:
                if g.FeatureList.FeatureRecord[fi].FeatureTag == 'kern':
                    res[sr.ScriptTag] = (sorted(k[i] for i in g.FeatureList.FeatureRecord[fi].Feature.LookupListIndex),
                                         subst.get(fi))
        assert res['DFLT'] == (['a'], None)
        assert res['arab'] == (['a'], ['PK', 'a'])
        tags = [fr.FeatureTag for fr in g.FeatureList.FeatureRecord]
        assert tags == sorted(tags)

    def test_asfea_round_trip(self):
        fea = (HEAD + PK + 'lookup Latin { pos a v -40; } Latin;\n'
               'conditionset C { lookup GPOS 10 1; } C;\n'
               'conditionset D { lookup GPOS 10 1; } D;\n'
               'feature kern { lookup Latin; } kern;\n'
               'feature dist { lookup Latin; } dist;\n'
               'variation kern C { lookup PK; } else { pos beh reh -50; } kern;\n'
               'variation dist D replace Latin { lookup PK; } dist;\n')
        glyphMap = makeFont().getReverseGlyphMap()
        once = Parser(io.StringIO(fea), glyphMap).parse().asFea()
        twice = Parser(io.StringIO(once), glyphMap).parse().asFea()
        assert once == twice
        assert '} else {' in once and 'replace Latin {' in once and 'lookup GPOS 10 1;' in once
        a, b = compileFea(fea), compileFea(once)
        assert featureLookups(a, 'kern') == featureLookups(b, 'kern')

    def test_feawriter(self):
        box = PolyBoundary.fromOutline([(0, -100), (50, 600), (350, 600), (400, -100)])
        fea = polykernLookupFea('PK', {'beh': box, 'reh': box, 'space': None},
                                {'fatha': PolyBoundary.fromOutline([(100, 550), (200, 750), (300, 550)])},
                                glyphOrder=GLYPHS)
        assert 'pos polybase [beh reh] ' + BOX + ';' in fea
        assert 'pos polybase space <polyboundary NULL>;' in fea
        st = polyPos(compileFea(HEAD + fea))
        assert st.BoundaryCoverage.glyphs == ['beh', 'reh', 'fatha']

    def test_feawriter_needs_both_sides_at_top(self):
        with pytest.raises(ValueError, match='reach the top'):
            outlineOf(PolyBoundary([(0, 0), (0, 50)], [(10, 100), (10, 0)]))

    @pytest.mark.parametrize('fea, message', [
        ('lookup A { pos polybase beh <polyboundary 0 0, 5 50, 3 40, 10 100, 30 0>; } A;',
         'left polyline goes down'),
        ('lookup A { pos polybase beh <polyboundary 0 0>; } A;', 'at least 2'),
        ('lookup A { pos polybase beh <polyboundary NULL>; pos polymark beh <polyboundary NULL>; } A;',
         'already a base'),
        ('lookup A { pos polybase beh <polyboundary NULL>; subtable; pos polybase reh <polyboundary NULL>; } A;',
         'more than one subtable'),
        ('lookup A { pos polybase beh <polyboundary NULL>; pos beh reh -50; } A;', 'same lookup type'),
        ('lookup A { pos polybase beh <polyboundary NULL>; } A;\nconditionset C { lookup GSUB 10 1; } C;\n'
         'feature kern { } kern;\nvariation kern C replace { lookup A; } kern;', 'tests for a GSUB lookup'),
        ('lookup A { pos polybase beh <polyboundary NULL>; } A;\nlookup B { pos beh reh -50; } B;\n'
         'conditionset C { lookup GPOS 10 1; } C;\nfeature kern { lookup A; } kern;\n'
         'variation kern C replace B { lookup A; } kern;', 'not in feature kern'),
        ('lookup A { pos polybase beh <polyboundary NULL>; } A;\nconditionset C { lookup GPOS 10 1; } C;\n'
         'variation kern C replace { lookup A; } else { pos beh reh -5; } kern;', 'both replace and else'),
        ('conditionset C { lookup BASE 10 1; } C;', 'Expected GPOS or GSUB'),
        ('lookup A { pos polybase beh <polyboundary NULL>; } A;\nconditionset C { lookup GPOS 10 1; } C;\n'
         'variation kern C replace Nope { lookup A; } kern;', 'Unknown lookup'),
        ('conditionset C { wght 400 700; } C;\nlookup A { pos polybase beh <polyboundary NULL>; } A;\n'
         'feature kern { } kern;\nvariation kern C { lookup A; } kern;', 'fvar'),
        ('feature vkrn { pos polybase beh <polyboundary NULL>; } vkrn;', 'horizontal text only'),
    ])
    def test_errors(self, fea, message):
        with pytest.raises(FeatureLibError, match=message):
            compileFea(HEAD + fea)


# ---- the build scripts

class TestScripts:

    def test_psfbuildfea(self, tmp_path):
        font = makeFont()
        fontpath = tmp_path / 'in.ttf'
        font.save(fontpath)
        feapath = tmp_path / 'f.fea'
        feapath.write_text(HEAD + PK + 'conditionset C { lookup GPOS 10 1; } C;\n'
                           'feature kern { pos beh reh -50; } kern;\n'
                           'variation kern C { lookup PK; } else { pos alef beh -5; } kern;\n')
        out = tmp_path / 'out.ttf'
        mapfile = tmp_path / 'map.txt'
        subprocess.run([sys.executable, os.path.join(TOOLS, 'psfbuildfea.py'), str(feapath),
                        str(fontpath), '-o', str(out), '-m', str(mapfile)], check=True)
        f = TTFont(out)
        assert polyPos(f) is not None
        assert 'PK,GPOS,' in mapfile.read_text()
