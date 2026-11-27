'''Teach fontTools' ttLib about the PolyKern lookup (GPOS lookup type 10, format 1) and
condition table format 6 (lookup support), without changing fontTools.

Importing this module is enough. It must be imported before any GPOS or GSUB table is read
or compiled. The tables are described in the same way as in fontTools' otData, and their
classes and converters are built the same way as otTables._buildClasses builds them.
'''

from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables.otBase import BaseTable
from fontTools.misc.textTools import safeEval
from fontTools.ttLib.tables.otConverters import buildConverters, Table, ExtSubTable, Struct
from fontTools.ttLib.tables.otDataSchema import FieldSpec

POLYKERN_LOOKUP_TYPE = 10       # GPOS lookup type of PolyKern
POLYKERN_FORMAT = 1             # the subtable format defined here
LOOKUP_SUPPORT_CONDITION = 6    # condition table format for lookup support

# The PolyPos subtable, as documentation/PolyKernLookup.md "Structure". Offsets must name
# the table they point to (LOffsetTo(...)); a bare LOffset takes the class from the field name.
polyData = [
    ("PolyPosFormat1", [
        FieldSpec("uint16", "PosFormat", description="Format identifier, = 1"),
        FieldSpec("uint16", "BoundaryCount",
                  description="Number of glyphs in the boundary coverage table"),
        FieldSpec("LOffsetTo(Coverage)", "BoundaryCoverage",
                  description="Glyphs that have a boundary"),
        FieldSpec("LOffsetTo(Coverage)", "BaseCoverage",
                  description="Base glyphs to kern, including spaces"),
        FieldSpec("LOffsetTo(Coverage)", "AttachedCoverage",
                  description="Attached glyphs: marks, and bases joined to the glyph before"),
        FieldSpec("LOffsetTo(VarIndexBases)", "VarIndexBases",
                  description="Variation index bases, or NULL if no boundary varies"),
        FieldSpec("LOffsetTo(Boundary)", "Boundary", repeat="BoundaryCount", aux=0,
                  description="Boundaries, in boundary coverage index order"),
    ]),
    ("VarIndexBases", [
        # BoundaryCount comes from the PolyPos subtable that points here
        FieldSpec("uint32", "VarIndexBase", repeat="BoundaryCount", aux=0,
                  description="First variation index for each boundary, or 0xFFFFFFFF"),
    ]),
    ("Boundary", [
        # Fields named ...Count are worked out when compiling, and written to TTX as comments
        FieldSpec("uint8", "LeftPointCount", description="numLeftPoints"),
        FieldSpec("uint8", "RightPointCount", description="numRightPoints"),
        FieldSpec("PolyPoint", "MinPoint", description="Bottom left of the bounding box"),
        FieldSpec("PolyPoint", "MaxPoint", description="Top right of the bounding box"),
        FieldSpec("PolyPoint", "LeftPoint", repeat="LeftPointCount", aux=0,
                  description="Left polyline, bottom to top"),
        FieldSpec("PolyPoint", "RightPoint", repeat="RightPointCount", aux=0,
                  description="Right polyline, top to bottom"),
    ]),
    ("PolyPoint", [
        FieldSpec("int16", "x"),
        FieldSpec("int16", "y"),
    ]),
]

conditionFormat6 = [
    FieldSpec("uint16", "Format", description="Format, = 6"),
    FieldSpec("uint16", "LookupType", description="The lookup type to test for"),
    FieldSpec("uint16", "SubtableFormat", description="The subtable format to test for"),
]


class PointStruct(Struct):
    """Converter for a PolyPoint that writes it to TTX as one element with x and y
    attributes, <LeftPoint index="0" x="107" y="-94"/>, rather than nested elements."""

    def xmlWrite(self, xmlWriter, font, value, name, attrs):
        xmlWriter.simpletag(name, list(attrs or []) + [("x", value.x), ("y", value.y)])
        xmlWriter.newline()

    def xmlRead(self, attrs, content, font):
        value = self.tableClass()
        value.x = safeEval(attrs["x"])
        value.y = safeEval(attrs["y"])
        return value


def _install():
    ns = vars(otTables)
    if "PolyPos" in ns:     # already installed
        return

    # Create the classes, then their converters (converters refer to the classes by name)
    ns["PolyPos"] = type("PolyPos", (otTables.getFormatSwitchingBaseTableClass("uint16"),), {})
    for name, _ in polyData[1:]:
        ns[name] = type(name, (BaseTable,), {})
    polyPos = ns["PolyPos"]
    polyPos.converters, polyPos.convertersByName = {}, {}
    polyPos.converters[POLYKERN_FORMAT], polyPos.convertersByName[POLYKERN_FORMAT] = \
        buildConverters(polyData[0][1][1:], ns)
    for name, fields in polyData[1:]:
        ns[name].converters, ns[name].convertersByName = buildConverters(fields, ns)
    for conv in ns["Boundary"].converters:
        if conv.tableClass is ns["PolyPoint"]:
            conv.__class__ = PointStruct

    # Register the lookup type. The SubTable converters hold this same dict (JSTF shares the
    # GPOS one), so they see the new entry.
    otTables.lookupTypes["GPOS"][POLYKERN_LOOKUP_TYPE] = polyPos
    polyPos.LookupType = POLYKERN_LOOKUP_TYPE
    # The reverse mappings used when reading TTX were filled in when fontTools built its
    # classes, so add ours by hand: subtables of a Lookup, and of an Extension lookup.
    otTables.Lookup.convertersByName["PolyPos"] = Table("SubTable", "SubTableCount", 0, polyPos)
    for byName in otTables.ExtensionPos.convertersByName.values():
        byName["PolyPos"] = ExtSubTable("ExtSubTable", None, None, polyPos)

    # Condition table format 6
    cond = otTables.ConditionTable
    cond.converters[LOOKUP_SUPPORT_CONDITION], cond.convertersByName[LOOKUP_SUPPORT_CONDITION] = \
        buildConverters(conditionFormat6[1:], ns)


_install()
PolyPos = otTables.PolyPos
Boundary = otTables.Boundary
PolyPoint = otTables.PolyPoint
VarIndexBases = otTables.VarIndexBases
