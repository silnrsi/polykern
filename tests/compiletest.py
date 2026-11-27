#!/usr/bin/env python3
'''Round trip test of the PolyKern lookup builder (tools/polykernlib).

Builds a PolyKern lookup from the test polylines for a font, adds it to the font's GPOS
'kern' feature through a FeatureVariations record with a lookup support condition
(format 6), and saves the font. Then reads the saved font back, takes the boundaries and
coverage tables from the compiled lookup, and checks that kerning text with them gives
exactly the same advances as kerning with the polylines it was built from.
'''

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))

import polykernlib                      # installs the new tables into ttLib
from polykernlib.otlbuilder import (PolyBoundary, PolyKernBuilder, addConditionalFeature,
                                    buildLookupSupportCondition)
from polykernlib.ottables import POLYKERN_LOOKUP_TYPE, POLYKERN_FORMAT
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables as ot
import stresstest as st
from makepolylines import Boundary
from polykern import polykern


def buildFont(fontpath, outpath, margin):
    '''Add a PolyKern lookup, built from the test polylines, to the font.'''
    st._init(fontpath, margin, None, True)
    tables = st._tables
    font = TTFont(fontpath)
    pk = PolyKernBuilder(font, None)
    bnd = {g: PolyBoundary(b.left, b.right) for g, b in tables.boundaries.items()}
    for g in sorted(tables.attachedCoverage):
        pk.add_attached(None, [g], bnd.get(g))
    for g in sorted(tables.baseCoverage - tables.attachedCoverage):
        pk.add_base(None, [g], bnd.get(g))
    lookup = pk.build()

    gpos = font['GPOS'].table
    gpos.LookupList.Lookup.append(lookup)
    gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)
    index = gpos.LookupList.LookupCount - 1
    cond = buildLookupSupportCondition(POLYKERN_LOOKUP_TYPE, POLYKERN_FORMAT)
    addConditionalFeature(gpos, 'kern', [cond], [index], replace=True)
    font.save(outpath)
    return tables


def readBack(outpath, tables):
    '''Replace the test tables' boundaries and coverage with those in the compiled font.'''
    font = TTFont(outpath)
    gpos = font['GPOS'].table
    subs = []
    for l in gpos.LookupList.Lookup:
        for s in l.SubTable:
            if l.LookupType == 9:           # Extension: fontTools may use it to fix overflows
                if s.ExtensionLookupType == POLYKERN_LOOKUP_TYPE:
                    subs.append(s.ExtSubTable)
            elif l.LookupType == POLYKERN_LOOKUP_TYPE:
                subs.append(s)
    assert len(subs) == 1
    sub = subs[0]
    assert type(sub).__name__ == 'PolyPos'
    boundaries = {}
    shared = set()
    for g, b in zip(sub.BoundaryCoverage.glyphs, sub.Boundary):
        boundaries[g] = Boundary([(p.x, p.y) for p in b.LeftPoint],
                                 [(p.x, p.y) for p in b.RightPoint])
        assert boundaries[g].bbox == (b.MinPoint.x, b.MinPoint.y, b.MaxPoint.x, b.MaxPoint.y)
        shared.add(id(b))
    rec = gpos.FeatureVariations.FeatureVariationRecord[-1]
    cond = rec.ConditionSet.ConditionTable[0]
    print(f'Compiled: {len(boundaries)} boundaries, {len(sub.BaseCoverage.glyphs)} bases, '
          f'{len(sub.AttachedCoverage.glyphs)} attached; GPOS {len(font.reader["GPOS"])} bytes')
    print(f'Condition: format {cond.Format}, lookup type {cond.LookupType}, '
          f'subtable format {cond.SubtableFormat}; kern lookups when met: '
          f'{rec.FeatureTableSubstitution.SubstitutionRecord[0].Feature.LookupListIndex}')
    orig = tables.boundaries, tables.baseCoverage, tables.attachedCoverage
    tables.boundaries = boundaries
    tables.baseCoverage = set(sub.BaseCoverage.glyphs)
    tables.attachedCoverage = set(sub.AttachedCoverage.glyphs)
    return orig


def ttxRoundTrip(outpath):
    '''Write the font's GPOS as TTX, read it back, compile and decompile it, and check
    the TTX comes out the same.'''
    import io, re
    font = TTFont(outpath)

    def toXML(f):
        x = io.StringIO()
        f.saveXML(x, tables=['GPOS'])
        return x.getvalue()

    xml = toXML(font)
    font2 = TTFont()
    font2.setGlyphOrder(font.getGlyphOrder())
    font2.importXML(io.StringIO(xml))
    buf = io.BytesIO()
    font2.save(buf)
    font3 = TTFont(io.BytesIO(buf.getvalue()))
    font3.setGlyphOrder(font.getGlyphOrder())   # the font holds only GPOS
    def body(x):        # leave out the ttFont tag, which holds the fontTools version
        return re.sub(r'<ttFont[^>]*>', '', x)
    same = body(toXML(font3)) == body(xml)
    print(f'TTX round trip of GPOS (TTX -> binary -> TTX): {"same" if same else "DIFFERENT"}')
    i = xml.find('<Boundary index="0">')
    print('First boundary in TTX:\n' + xml[i:xml.find('</Boundary>', i) + 11])
    i = xml.find('<ConditionTable')
    print('Condition in TTX:\n' + xml[i:xml.find('</ConditionTable>', i) + 17])
    return same


def advances(texts):
    res = []
    for t in texts:
        glyphs, rtl = st._makeGlyphs(t)
        polykern(glyphs, rtl)
        res.append([g.adv for g in glyphs])
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('font', help='OpenType font without kerning')
    p.add_argument('output', help='Font to write, with the PolyKern lookup added')
    p.add_argument('words', help='Word list: lines starting with a quoted word')
    p.add_argument('-m', '--margin', type=int, default=200)
    p.add_argument('-n', '--lines', type=int, default=5000, help='How many lines to check')
    args = p.parse_args()

    tables = buildFont(args.font, args.output, args.margin)
    texts = st.loadWords(args.words)[:args.lines]
    before = advances(texts)
    orig = readBack(args.output, tables)
    # The coverage that was put in must come back out
    assert tables.baseCoverage == orig[1] - orig[2], 'base coverage differs'
    assert tables.attachedCoverage == orig[2], 'attached coverage differs'
    after = advances(texts)
    ttxOk = ttxRoundTrip(args.output)
    diffs = sum(a != b for a, b in zip(before, after))
    print(f'{len(texts)} lines kerned from the compiled lookup: {diffs} differ')
    sys.exit(1 if diffs or not ttxOk else 0)


if __name__ == '__main__':
    main()
