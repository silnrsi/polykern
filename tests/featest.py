#!/usr/bin/env python3
'''Test the PolyKern FEA compiler (tools/polykernlib).

Writes the test polylines for a font as FEA, with a fallback pair kerning lookup, a
condition set testing for PolyKern support, and a variation block that replaces the kern
feature's lookups. Compiles it with the PolyKern feaLib Builder, and checks:

- the PolyPos subtable is the same as one built directly with PolyKernBuilder;
- the FeatureVariations record has the format 6 condition and replaces the lookups;
- parsing the FEA and writing it out again (asFea) gives FEA that builds the same table;
- some bad FEA gives the expected errors.
'''

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))

import polykernlib                      # installs the new tables into ttLib
from polykernlib.otlbuilder import PolyBoundary, PolyKernBuilder
from polykernlib.feabuilder import addOpenTypeFeaturesFromString
from polykernlib.feaparser import Parser
from polykernlib.feawriter import polykernLookupFea, outlineOf
from fontTools.feaLib.error import FeatureLibError
from fontTools.ttLib import TTFont
import stresstest as st


def toXML(table, font):
    from fontTools.misc.xmlWriter import XMLWriter
    out = io.BytesIO()
    w = XMLWriter(out)
    table.toXML(w, font)
    return out.getvalue().decode('utf-8')


def polyPos(font):
    gpos = font['GPOS'].table
    for l in gpos.LookupList.Lookup:
        for s in l.SubTable:
            if l.LookupType == 9 and s.ExtensionLookupType == 10:
                return s.ExtSubTable
            if l.LookupType == 10:
                return s
    return None


# The test FEA below names glyphs by character (uni0628 and so on); these are turned into
# the font's own glyph names through its cmap.
NAMES = {}


def realNames(fea):
    import re
    return re.sub(r'(?<![\w.@\\])(uni0627|uni0628|uni0631|a|v)(?![\w.])',
                  lambda m: NAMES.get(m.group(1), m.group(1)), fea)


def compileFea(fontpath, fea):
    fea = realNames(fea)
    font = TTFont(fontpath)
    addOpenTypeFeaturesFromString(font, fea, tables=['GPOS'])
    # feaLib reads GSUB to set OS/2 usMaxContext. Recompiling Awami's GSUB hits a fontTools
    # bug in splitLigatureSubst, so drop the decompiled copy and keep the original bytes.
    font.tables.pop('GSUB', None)
    buf = io.BytesIO()
    font.save(buf)
    return TTFont(io.BytesIO(buf.getvalue()))


def expectError(fontpath, fea, text):
    try:
        compileFea(fontpath, fea)
    except FeatureLibError as e:
        ok = text in str(e)
        print(f'  {"ok  " if ok else "FAIL"} error: {e}')
        return ok
    print(f'  FAIL no error, expected: {text}')
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('font', help='OpenType font without kerning')
    p.add_argument('-m', '--margin', type=int, default=200)
    p.add_argument('-o', '--output', help='Write the generated FEA here')
    args = p.parse_args()

    st._init(args.font, args.margin, None, True)
    cmap = TTFont(args.font).getBestCmap()
    NAMES.update({'uni0627': cmap[0x627], 'uni0628': cmap[0x628], 'uni0631': cmap[0x631],
                  'a': cmap[0x61], 'v': cmap[0x76]})
    tables = st._tables
    font = TTFont(args.font)
    glyphOrder = font.getGlyphOrder()
    bnd = {g: PolyBoundary(b.left, b.right) for g, b in tables.boundaries.items()}
    attached = {g: bnd.get(g) for g in tables.attachedCoverage}
    bases = {g: bnd.get(g) for g in tables.baseCoverage - tables.attachedCoverage}

    bad = 0
    for g, b in list(attached.items()) + list(bases.items()):
        if b is not None:
            try:
                outlineOf(b)
            except ValueError:
                bad += 1
    print(f'{bad} boundaries cannot be written as one outline')

    fea = ('languagesystem DFLT dflt;\nlanguagesystem arab dflt;\n\n'
           'lookup PairKernFallback {\n    pos uni0628 uni0631 -50;\n} PairKernFallback;\n\n'
           + polykernLookupFea('PolyKern', bases, attached, glyphOrder=glyphOrder) +
           '\nconditionset HavePolyKern {\n    lookup GPOS 10 1;\n} HavePolyKern;\n\n'
           'feature kern {\n    lookup PairKernFallback;\n} kern;\n\n'
           'variation kern HavePolyKern replace {\n    lookup PolyKern;\n} kern;\n')
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(fea)
    print(f'FEA: {len(fea)} bytes, {fea.count("pos poly")} pos poly statements')

    ok = True
    compiled = compileFea(args.font, fea)
    pk = PolyKernBuilder(font, None)
    for g, b in attached.items():
        pk.add_attached(None, [g], b)
    for g, b in bases.items():
        pk.add_base(None, [g], b)
    direct = pk.build().SubTable[0]
    def contents(sub):
        pts = lambda ps: [(p.x, p.y) for p in ps]
        return (sub.BoundaryCoverage.glyphs, sub.BaseCoverage.glyphs, sub.AttachedCoverage.glyphs,
                [(pts([b.MinPoint, b.MaxPoint]), pts(b.LeftPoint), pts(b.RightPoint))
                 for b in sub.Boundary])
    a, b = contents(polyPos(compiled)), contents(direct)
    same = a == b
    if not same:
        for name, x, y in zip(('boundary coverage', 'base coverage', 'attached coverage', 'boundaries'), a, b):
            if x != y:
                diff = [i for i, (p, q) in enumerate(zip(x, y)) if p != q][:3]
                print(f'  {name} differs ({len(x)} vs {len(y)}), first at {diff}: '
                      f'{[x[i] for i in diff]} vs {[y[i] for i in diff]}')
    ok &= same
    print(f'PolyPos from FEA is {"the same as" if same else "DIFFERENT from"} the direct build')

    gpos = compiled['GPOS'].table
    names = [l for l in gpos.LookupList.Lookup]
    kern = [fr for fr in gpos.FeatureList.FeatureRecord if fr.FeatureTag == 'kern']
    rec = gpos.FeatureVariations.FeatureVariationRecord
    cond = rec[0].ConditionSet.ConditionTable
    subst = rec[0].FeatureTableSubstitution.SubstitutionRecord[0].Feature.LookupListIndex
    types = [l.LookupType if l.LookupType != 9 else l.SubTable[0].ExtensionLookupType
             for l in names]
    good = (len(rec) == 1 and len(cond) == 1 and cond[0].Format == 6
            and cond[0].LookupType == 10 and cond[0].SubtableFormat == 1
            and [types[i] for i in kern[0].Feature.LookupListIndex] == [2]
            and [types[i] for i in subst] == [10])
    ok &= good
    print(f'kern default lookups types {[types[i] for i in kern[0].Feature.LookupListIndex]}, '
          f'when PolyKern supported {[types[i] for i in subst]}: {"ok" if good else "FAIL"}')

    again = Parser(io.StringIO(realNames(fea)), compiled.getReverseGlyphMap()).parse().asFea()
    compiled2 = compileFea(args.font, again)
    same = toXML(compiled2['GPOS'].table, compiled2) == toXML(gpos, compiled)
    ok &= same
    print(f'FEA written back out with asFea builds {"the same" if same else "a DIFFERENT"} GPOS')

    # replace with named lookups keeps the feature's other lookups, including anonymous ones
    fea2 = ('languagesystem DFLT dflt;\nlanguagesystem arab dflt;\n'
            'lookup Latin { pos a v -40; } Latin;\n'
            'lookup Fallback { pos uni0628 uni0631 -50; } Fallback;\n'
            'lookup PK { pos polybase uni0628 <polyboundary 0 0, 0 100, 50 100, 50 0>; } PK;\n'
            'conditionset C { lookup GPOS 10 1; } C;\n'
            'feature kern { pos uni0627 uni0628 -10; lookup Latin; lookup Fallback; } kern;\n'
            'variation kern C replace Fallback { lookup PK; } kern;\n')
    f2 = compileFea(args.font, fea2)
    g2 = f2['GPOS'].table
    kinds = []
    for l in g2.LookupList.Lookup:
        st0 = l.SubTable[0]
        kinds.append('PK' if l.LookupType == 10 else
                     'Latin' if NAMES['a'] in getattr(st0.Coverage, 'glyphs', []) else
                     'Fallback' if NAMES['uni0628'] in st0.Coverage.glyphs else 'inline')
    kernf = [fr.Feature.LookupListIndex for fr in g2.FeatureList.FeatureRecord if fr.FeatureTag == 'kern'][0]
    subs = g2.FeatureVariations.FeatureVariationRecord[0].FeatureTableSubstitution.SubstitutionRecord[0].Feature.LookupListIndex
    good = (sorted(kinds[i] for i in kernf) == ['Fallback', 'Latin', 'inline']
            and sorted(kinds[i] for i in subs) == ['Latin', 'PK', 'inline'])
    ok &= good
    print(f'replace Fallback: default {[kinds[i] for i in kernf]}, when supported '
          f'{[kinds[i] for i in subs]}: {"ok" if good else "FAIL"}')
    again = Parser(io.StringIO(realNames(fea2)), f2.getReverseGlyphMap()).parse().asFea()
    good = 'replace Fallback {' in again
    ok &= good
    print(f'asFea keeps "replace Fallback": {"ok" if good else "FAIL"}')

    # else: the else block is the default, swapped for the first block when supported
    fea3 = ('languagesystem DFLT dflt;\nlanguagesystem arab dflt;\n'
            'lookup Latin { pos a v -40; } Latin;\n'
            'lookup PK { pos polybase uni0628 <polyboundary 0 0, 0 100, 50 100, 50 0>; } PK;\n'
            'conditionset C { lookup GPOS 10 1; } C;\n'
            'feature kern { lookup Latin; } kern;\n'
            'variation kern C {\n    lookup PK;\n} else {\n    pos uni0628 uni0631 -50;\n} kern;\n')
    f3 = compileFea(args.font, fea3)
    g3 = f3['GPOS'].table
    kinds = []
    for l in g3.LookupList.Lookup:
        st0 = l.SubTable[0]
        kinds.append('PK' if l.LookupType == 10 else
                     'Latin' if NAMES['a'] in getattr(st0.Coverage, 'glyphs', []) else 'Fallback')
    kernf = [fr.Feature.LookupListIndex for fr in g3.FeatureList.FeatureRecord if fr.FeatureTag == 'kern'][0]
    subs = g3.FeatureVariations.FeatureVariationRecord[0].FeatureTableSubstitution.SubstitutionRecord[0].Feature.LookupListIndex
    good = (sorted(kinds[i] for i in kernf) == ['Fallback', 'Latin']
            and sorted(kinds[i] for i in subs) == ['Latin', 'PK'])
    ok &= good
    print(f'else: default {[kinds[i] for i in kernf]}, when supported '
          f'{[kinds[i] for i in subs]}: {"ok" if good else "FAIL"}')
    again = Parser(io.StringIO(realNames(fea3)), f3.getReverseGlyphMap()).parse().asFea()
    f3b = compileFea(args.font, again)
    good = '} else {' in again and toXML(f3b['GPOS'].table, f3b) == toXML(g3, f3)
    ok &= good
    print(f'asFea of else builds the same GPOS: {"ok" if good else "FAIL"}')

    print('Errors:')
    head = 'languagesystem DFLT dflt;\n'
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary 0 0, 5 50, 3 40, 10 100, 30 0>; } A;',
                      'left polyline')
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary NULL>; pos polymark uni0628 <polyboundary NULL>; } A;',
                      'already a base')
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary NULL>; subtable; pos polybase uni0631 <polyboundary NULL>; } A;',
                      'more than one subtable')
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary NULL>; pos uni0628 uni0631 -50; } A;',
                      'same lookup type')
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary NULL>; } A;\n'
                      'conditionset C { lookup GSUB 10 1; } C;\nfeature kern { } kern;\n'
                      'variation kern C replace { lookup A; } kern;',
                      'tests for a GSUB lookup')
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary NULL>; } A;\n'
                      'lookup B { pos uni0628 uni0631 -50; } B;\n'
                      'conditionset C { lookup GPOS 10 1; } C;\nfeature kern { lookup A; } kern;\n'
                      'variation kern C replace B { lookup A; } kern;',
                      'not in feature kern')
    ok &= expectError(args.font, head + 'lookup A { pos polybase uni0628 <polyboundary NULL>; } A;\n'
                      'conditionset C { lookup GPOS 10 1; } C;\n'
                      'variation kern C replace { lookup A; } else { pos uni0628 uni0631 -5; } kern;',
                      'both replace and else')
    print('All ok' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
