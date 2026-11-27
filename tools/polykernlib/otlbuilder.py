'''Builders for the PolyKern lookup and the lookup support condition, in the style of
fontTools.otlLib.builder.

- PolyBoundary: a glyph's boundary (left and right polylines), with checking.
- PolyKernBuilder: an otlLib LookupBuilder for GPOS lookup type 10.
- buildPolyPosSubtable: builds the subtable from glyph to boundary mappings.
- buildLookupSupportCondition: builds a condition table format 6.
- addConditionalFeature: adds a FeatureVariations record to GSUB or GPOS, for any kind of
  condition, in fonts with or without fvar.
'''

from fontTools.feaLib.error import FeatureLibError
from fontTools.otlLib.builder import LookupBuilder, buildCoverage
from fontTools.ttLib.tables import otTables as ot
from fontTools.varLib import featureVars

from . import ottables
from .ottables import POLYKERN_LOOKUP_TYPE, POLYKERN_FORMAT, LOOKUP_SUPPORT_CONDITION

MAX_POINTS = 255    # each polyline's point count is a uint8


class PolyBoundary:
    '''A glyph's boundary: the left polyline from bottom to top and the right polyline from
    top to bottom, each a list of (x, y). Points are integers for now; variable values
    are not yet supported.'''

    def __init__(self, left, right):
        self.left = [tuple(p) for p in left]
        self.right = [tuple(p) for p in right]

    @classmethod
    def fromOutline(cls, points):
        '''Make a boundary from one list of points going round the glyph: the left side
        bottom to top, then the right side top to bottom. The list is split at the top: the
        left polyline runs to the leftmost point at the greatest y, and the right polyline
        starts at the rightmost point at the greatest y. Points between them are dropped.'''
        points = [tuple(p) for p in points]
        if not points:
            raise ValueError("A boundary needs points")
        top = max(p[1] for p in points)
        tops = [i for i, p in enumerate(points) if p[1] == top]
        left = min(tops, key=lambda i: (points[i][0], i))      # leftmost, first if tied
        right = max(tops, key=lambda i: (points[i][0], i))     # rightmost, last if tied
        if left > right:
            raise ValueError("The boundary must go up the left side and down the right side")
        return cls(points[:left + 1], points[right:])

    def check(self):
        '''Raise ValueError if the boundary breaks the rules for polylines.'''
        for name, pts, up in (("left", self.left, True), ("right", self.right, False)):
            if len(pts) < 2:
                raise ValueError(f"The {name} polyline needs at least 2 points")
            if len(pts) > MAX_POINTS:
                raise ValueError(f"The {name} polyline has more than {MAX_POINTS} points")
            for a, b in zip(pts, pts[1:]):
                if (b[1] < a[1]) if up else (b[1] > a[1]):
                    raise ValueError(f"The {name} polyline goes {'down' if up else 'up'} "
                                     f"from {a} to {b}; it must go "
                                     f"{'bottom to top' if up else 'top to bottom'}")

    @property
    def bbox(self):
        pts = self.left + self.right
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))

    def key(self):
        return (tuple(self.left), tuple(self.right))

    def __eq__(self, other):
        return isinstance(other, PolyBoundary) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def __repr__(self):
        return f"PolyBoundary({self.left!r}, {self.right!r})"


def _point(x, y):
    p = ot.PolyPoint()
    p.x, p.y = x, y
    return p


def buildBoundary(boundary):
    '''PolyBoundary -> otTables.Boundary.'''
    boundary.check()
    res = ot.Boundary()
    xMin, yMin, xMax, yMax = boundary.bbox
    res.MinPoint = _point(xMin, yMin)
    res.MaxPoint = _point(xMax, yMax)
    res.LeftPoint = [_point(*p) for p in boundary.left]
    res.RightPoint = [_point(*p) for p in boundary.right]
    return res


def buildPolyPosSubtable(bases, attached, glyphMap):
    '''Build a PolyPos subtable.

    bases: {glyph name: PolyBoundary or None}. Glyphs with None are spaces.
    attached: {glyph name: PolyBoundary or None}. Glyphs with None are attached glyphs
        with no boundary.
    glyphMap: {glyph name: glyph ID}.

    Glyphs that are given equal boundaries share one boundary structure in the font.
    '''
    both = set(bases) & set(attached)
    if both:
        raise ValueError(f"Glyphs both base and attached: {' '.join(sorted(both))}")
    withBoundary = {g: b for g, b in list(bases.items()) + list(attached.items())
                    if b is not None}
    order = sorted(withBoundary, key=glyphMap.__getitem__)
    built = {}          # boundary key -> otTables.Boundary, so equal boundaries share
    st = ot.PolyPos()
    st.Format = POLYKERN_FORMAT
    st.BoundaryCoverage = buildCoverage(order, glyphMap)
    st.BaseCoverage = buildCoverage(bases, glyphMap)
    st.AttachedCoverage = buildCoverage(attached, glyphMap)
    st.VarIndexBases = None
    st.Boundary = []
    for g in order:
        b = withBoundary[g]
        if b.key() not in built:
            built[b.key()] = buildBoundary(b)
        st.Boundary.append(built[b.key()])
    st.BoundaryCount = len(st.Boundary)
    return st


class PolyKernBuilder(LookupBuilder):
    '''Builds a PolyKern (GPOS type 10) lookup. It always has exactly one subtable.

    Attributes:
        bases: {glyph name: PolyBoundary or None}, from add_base.
        attached: {glyph name: PolyBoundary or None}, from add_attached.
    '''

    def __init__(self, font, location):
        LookupBuilder.__init__(self, font, location, "GPOS", POLYKERN_LOOKUP_TYPE)
        self.bases = {}
        self.attached = {}

    def equals(self, other):
        return (LookupBuilder.equals(self, other)
                and self.bases == other.bases and self.attached == other.attached)

    def _add(self, location, glyphs, boundary, mine, other, role):
        if boundary is not None:
            try:
                boundary.check()
            except ValueError as e:
                raise FeatureLibError(str(e), location)
        for g in glyphs:
            if g in other:
                raise FeatureLibError(
                    f"Glyph {g} is already a {'mark' if role == 'base' else 'base'} "
                    f"in this PolyKern lookup", location)
            if g in mine and mine[g] != boundary:
                raise FeatureLibError(
                    f"Glyph {g} already has a different boundary in this PolyKern lookup",
                    location)
            mine[g] = boundary

    def add_base(self, location, glyphs, boundary):
        '''Add base glyphs (pos polybase). boundary is a PolyBoundary, or None for spaces.'''
        self._add(location, glyphs, boundary, self.bases, self.attached, "base")

    def add_attached(self, location, glyphs, boundary):
        '''Add attached glyphs (pos polymark): marks, and bases joined to the glyph
        before them. boundary is a PolyBoundary, or None for glyphs with no boundary.'''
        self._add(location, glyphs, boundary, self.attached, self.bases, "mark")

    def add_subtable_break(self, location):
        raise FeatureLibError("A PolyKern lookup cannot have more than one subtable",
                              location)

    def can_add_mapping(self, mapping):
        return True

    def build(self):
        return self.buildLookup_([buildPolyPosSubtable(self.bases, self.attached,
                                                       self.glyphMap)])


# ----------------------------------------------------------------------------------------
# Conditions


def buildLookupSupportCondition(lookupType, subtableFormat):
    '''Build a condition table format 6: met if the engine supports subtables of the given
    lookup type and format, in the table whose FeatureVariations contain it.'''
    ct = ot.ConditionTable()
    ct.Format = LOOKUP_SUPPORT_CONDITION
    ct.LookupType = lookupType
    ct.SubtableFormat = subtableFormat
    return ct


def buildAxisCondition(font, axisTag, minValue, maxValue):
    '''Build a condition table format 1 from normalised axis values.'''
    if "fvar" not in font:
        raise ValueError(f"Axis condition on {axisTag} in a font without an fvar table")
    axes = [a.axisTag for a in font["fvar"].axes]
    if axisTag not in axes:
        raise ValueError(f"Axis condition on {axisTag}, which is not in the font")
    if minValue > maxValue:
        raise ValueError("A condition has a minimum value above the maximum value")
    return featureVars.buildConditionTable(axes.index(axisTag), minValue, maxValue)


def addConditionalFeature(table, featureTag, conditions, lookupIndices, replace=True, remove=None,
                          lookupsByFeature=None):
    '''Add a FeatureVariations record to a GSUB or GPOS table (the otTables object, such as
    font["GPOS"].table), so that when all the conditions are met, the features with the
    given tag use other lookups.

    conditions: a list of otTables.ConditionTable, of any format. The table does not need
        to be in a variable font.
    lookupIndices: the lookups to use when the conditions are met.
    replace: if true, the feature uses only these lookups when the conditions are met,
        which is what a fallback needs. If false, they are added to the feature's own
        lookups, as fontTools' feaLib does for a variation block.
    remove: lookup indices to take out of the feature's own lookups before adding these.
        It applies only when replace is false, and allows a fallback to be swapped out
        while the feature's other lookups are kept.

    lookupsByFeature: optionally {feature index: lookup indices}, to give each feature
        record with the tag its own lookups (for example when a variation block has script
        statements). Only the features listed get substitutions, and lookupIndices is
        not used.

    If the font has no such feature, an empty one is added to every language system.
    A record with the same conditions as an existing one is merged into it.
    '''
    featureList = ot._getLayoutList(table, "FeatureList")
    scriptList = ot._getLayoutList(table, "ScriptList")
    if table.Version < 0x00010001:
        table.Version = 0x00010001  # allows FeatureVariations

    if not any(fr.FeatureTag == featureTag for fr in featureList.FeatureRecord):
        newFeature = featureVars.buildFeatureRecord(featureTag, [])
        featureList.FeatureRecord.append(newFeature)
        featureList.FeatureCount = len(featureList.FeatureRecord)
        featureVars.sortFeatureList(table)
        newIndex = featureList.FeatureRecord.index(newFeature)
        for sr in scriptList.ScriptRecord:
            if sr.Script.DefaultLangSys is None:
                ls = ot.LangSys()
                ls.LookupOrder = None
                ls.ReqFeatureIndex = 0xFFFF
                ls.FeatureIndex = []
                ls.FeatureCount = 0
                sr.Script.DefaultLangSys = ls
            for ls in [sr.Script.DefaultLangSys] + [r.LangSys for r in sr.Script.LangSysRecord]:
                ls.FeatureIndex.append(newIndex)
                ls.FeatureIndex.sort()
                ls.FeatureCount = len(ls.FeatureIndex)

    records = []
    for i, fr in enumerate(featureList.FeatureRecord):
        if fr.FeatureTag != featureTag:
            continue
        if lookupsByFeature is not None:
            if i not in lookupsByFeature:
                continue
            lookupIndices = lookupsByFeature[i]
        if replace:
            lookups = list(lookupIndices)
        else:
            gone = set(remove or ())
            lookups = [i for i in fr.Feature.LookupListIndex if i not in gone] + list(lookupIndices)
        records.append(featureVars.buildFeatureTableSubstitutionRecord(
            i, sorted(set(lookups))))

    if not records:
        return
    fvs = getattr(table, "FeatureVariations", None)
    fvr = featureVars.findFeatureVariationRecord(fvs, conditions) if fvs is not None else None
    if fvr is None:
        fvr = featureVars.buildFeatureVariationRecord(conditions, records)
        if fvs is None:
            table.FeatureVariations = featureVars.buildFeatureVariations([fvr])
        else:
            fvs.FeatureVariationRecord.append(fvr)
            fvs.FeatureVariationCount = len(fvs.FeatureVariationRecord)
    else:
        subs = fvr.FeatureTableSubstitution.SubstitutionRecord
        existing = {r.FeatureIndex for r in subs}
        for r in records:
            if r.FeatureIndex in existing:
                raise ValueError(f"Feature {featureTag} already has substitutions for "
                                 f"these conditions")
            subs.append(r)
        subs.sort(key=lambda r: r.FeatureIndex)
        fvr.FeatureTableSubstitution.SubstitutionCount = len(subs)
