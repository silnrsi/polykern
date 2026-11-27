'''feaLib AST with the PolyKern additions. Use it in place of fontTools.feaLib.ast: it holds
everything that module does, plus:

- PolyBoundary: <polyboundary NULL> or <polyboundary x y, x y, ...>
- PolyKernPosStatement: pos polybase / pos polymark
- ConditionsetStatement: a condition set that may also test for lookup support
- VariationBlock: a variation block that may replace the feature's lookups
'''

from fontTools.feaLib import ast as _feaast
from fontTools.feaLib.ast import *                  # noqa: F401,F403 everything else
from fontTools.feaLib.ast import SHIFT, Expression, Statement
from fontTools.feaLib.error import FeatureLibError

from .otlbuilder import PolyBoundary as _OtlPolyBoundary


def __getattr__(name):
    '''Anything not defined here comes from fontTools.feaLib.ast.'''
    return getattr(_feaast, name)


class PolyBoundary(Expression):
    '''A boundary given as one list of points going round the glyph, or NULL (points is
    None).'''

    def __init__(self, points, location=None):
        Expression.__init__(self, location)
        self.points = points

    def makeBoundary(self):
        '''The otlbuilder.PolyBoundary, or None for NULL. Raises FeatureLibError if the
        points don't make a valid boundary.'''
        if self.points is None:
            return None
        try:
            b = _OtlPolyBoundary.fromOutline(self.points)
            b.check()
        except ValueError as e:
            raise FeatureLibError(str(e), self.location)
        return b

    def asFea(self, indent=""):
        if self.points is None:
            return "<polyboundary NULL>"
        return "<polyboundary " + ", ".join(f"{x} {y}" for x, y in self.points) + ">"


class PolyKernPosStatement(Statement):
    '''pos polybase GLYPHS <polyboundary ...>; or pos polymark GLYPHS <polyboundary ...>;

    role is "polybase" (base glyphs, or spaces with a NULL boundary) or "polymark"
    (attached glyphs: marks, and bases joined to the glyph before them).'''

    def __init__(self, role, glyphs, boundary, location=None):
        Statement.__init__(self, location)
        assert role in ("polybase", "polymark")
        self.role, self.glyphs, self.boundary = role, glyphs, boundary

    def build(self, builder):
        builder.add_polykern(self.location, self.role, self.glyphs.glyphSet(),
                             self.boundary.makeBoundary())

    def asFea(self, indent=""):
        return f"pos {self.role} {self.glyphs.asFea()} {self.boundary.asFea()};"


class ConditionsetStatement(_feaast.ConditionsetStatement):
    '''A condition set. As well as axis ranges, it may hold lookup support tests: a list of
    (table tag, lookup type, subtable format), written "lookup GPOS 10 1;".'''

    def __init__(self, name, conditions, lookuptests=(), location=None):
        _feaast.ConditionsetStatement.__init__(self, name, conditions, location=location)
        self.lookuptests = list(lookuptests)

    def build(self, builder):
        builder.add_conditionset(self.location, self.name, self.conditions, self.lookuptests)

    def asFea(self, res="", indent=""):
        res += indent + f"conditionset {self.name} " + "{\n"
        for tag, (minvalue, maxvalue) in self.conditions.items():
            res += indent + SHIFT + f"{tag} {minvalue} {maxvalue};\n"
        for table, lookupType, subtableFormat in self.lookuptests:
            res += indent + SHIFT + f"lookup {table} {lookupType} {subtableFormat};\n"
        res += indent + "}" + f" {self.name};\n"
        return res


class VariationBlock(_feaast.VariationBlock):
    '''A variation block, with two extensions for swapping lookups when the conditions
    are met (for example, a fallback for engines that do not support a lookup type):

    - else: elseBlock is a FeatureBlock for the same feature. It is built into the feature
      as an ordinary feature block would be, so its lookups are the default. When the
      conditions are met, the feature uses its lookups minus those from the else block,
      plus those from this block.
    - replace: when the conditions are met, this block's lookups replace the feature's own
      lookups. If replace names lookups (replaceLookups, a list of LookupBlock), only
      those are taken out of the feature and its other lookups are kept.
    '''

    def __init__(self, name, conditionset, use_extension=False, replace=False,
                 replaceLookups=(), elseBlock=None, location=None):
        _feaast.VariationBlock.__init__(self, name, conditionset, use_extension, location)
        self.replace = replace
        self.replaceLookups = list(replaceLookups)
        self.elseBlock = elseBlock

    def build(self, builder):
        _feaast.VariationBlock.build(self, builder)
        elseLookups = []
        if self.elseBlock is not None:
            builder.else_collect_ = elseLookups
            self.elseBlock.build(builder)
            builder.else_collect_ = None
        if self.replace or self.elseBlock is not None:
            builder.add_variation_replace(
                self.location, self.name, self.conditionset,
                replaceAll=self.replace and not self.replaceLookups,
                lookupNames=[l.name for l in self.replaceLookups], lookups=elseLookups)

    def asFea(self, indent=""):
        res = indent + f"variation {self.name.strip()} {self.conditionset} "
        if self.replace:
            res += " ".join(["replace"] + [l.name for l in self.replaceLookups]) + " "
        if self.use_extension:
            res += "useExtension "
        res += "{\n" + _feaast.Block.asFea(self, indent=indent) + indent + "} "
        if self.elseBlock is not None:
            res += "else {\n" + _feaast.Block.asFea(self.elseBlock, indent=indent) + indent + "} "
        res += f"{self.name.strip()};\n"
        return res
