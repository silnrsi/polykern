'''feaLib Builder with the PolyKern additions. It parses with polykernlib.feaparser, builds
PolyKern lookups, and builds FeatureVariations itself so that it can use lookup support
conditions, fonts without fvar, and variation blocks that replace a feature's lookups.

Variable fonts are not handled yet beyond what fontTools already does.
'''

import copy

from fontTools.feaLib import builder as _feabuilder
from fontTools.varLib import featureVars
from fontTools.feaLib.error import FeatureLibError

from .feaparser import Parser
from .otlbuilder import (PolyKernBuilder, addConditionalFeature, buildAxisCondition,
                         buildLookupSupportCondition)


class Builder(_feabuilder.Builder):

    def __init__(self, font, featurefile):
        _feabuilder.Builder.__init__(self, font, featurefile)
        self.lookuptests_ = {}              # condition set name -> [(table, type, format)]
        # (feature tag, condition set name) -> (location, replace all, names of lookups to
        # replace, lookup builders to replace (from an else block))
        self.replace_variations_ = {}
        self.else_collect_ = None           # while building an else block: its lookups

    def build(self, tables=None, debug=False):
        if self.parseTree is None:
            self.parseTree = Parser(self.file, self.glyphMap).parse()
        _feabuilder.Builder.build(self, tables, debug)

    # PolyKern

    def add_polykern(self, location, role, glyphs, boundary):
        lookup = self.get_lookup_(location, PolyKernBuilder)
        if role == "polybase":
            lookup.add_base(location, glyphs, boundary)
        else:
            lookup.add_attached(location, glyphs, boundary)

    # Conditions and feature variations

    def add_conditionset(self, location, key, value, lookuptests=()):
        if value:       # axis ranges, which fontTools normalises (and which need fvar)
            _feabuilder.Builder.add_conditionset(self, location, key, value)
        else:
            if key in self.conditionsets_:
                raise FeatureLibError(
                    f"Condition set '{key}' has the same name as a previous condition set",
                    location)
            self.conditionsets_[key] = {}
        self.lookuptests_[key] = list(lookuptests)

    def add_variation_replace(self, location, featureTag, conditionset, replaceAll=False,
                              lookupNames=(), lookups=()):
        key = (featureTag, conditionset)
        if key in self.replace_variations_:
            raise FeatureLibError(f"More than one replace or else for feature {featureTag} "
                                  f"with condition set {conditionset}", location)
        self.replace_variations_[key] = (location, replaceAll, list(lookupNames), list(lookups))

    def add_lookup_to_feature_(self, lookup, feature_name):
        _feabuilder.Builder.add_lookup_to_feature_(self, lookup, feature_name)
        if self.else_collect_ is not None and lookup not in self.else_collect_:
            self.else_collect_.append(lookup)

    @staticmethod
    def _langSystems(table):
        '''{feature index: {(script, language)}}: which language systems use each feature
        record. feaLib merges the records of language systems that have the same lookups.'''
        res = {}
        for sr in table.ScriptList.ScriptRecord:
            for lang, ls in Builder._langSysPairs(sr):
                for fi in ls.FeatureIndex:
                    res.setdefault(fi, set()).add((sr.ScriptTag, lang))
        return res

    @staticmethod
    def _langSysPairs(scriptRecord):
        pairs = [("dflt", scriptRecord.Script.DefaultLangSys)] + \
                [(r.LangSysTag, r.LangSys) for r in scriptRecord.Script.LangSysRecord]
        return [(lang, ls) for lang, ls in pairs if ls is not None]

    def _variationLookups(self, script, lang, featureTag, conditionset, table_tag):
        builders = self.feature_variations_.get((script, lang, featureTag), {}) \
                                           .get(conditionset, [])
        return tuple(sorted(set(b.lookup_index for b in builders if b.table == table_tag)))

    def _splitFeatures(self, table, table_tag, keys):
        '''Where language systems share a feature record but have different lookups for a
        condition set, give them their own copies of the record.'''
        records = table.FeatureList.FeatureRecord
        split = False
        while True:
            langSystems = self._langSystems(table)
            todo = None
            for featureTag, conditionset in keys:
                for fi, fr in enumerate(records):
                    if fr.FeatureTag != featureTag:
                        continue
                    groups = {}
                    for script, lang in sorted(langSystems.get(fi, ())):
                        groups.setdefault(self._variationLookups(
                            script, lang, featureTag, conditionset, table_tag), []).append(
                            (script, lang))
                    if len(groups) > 1:
                        todo = (fi, list(groups.values())[1:])
                        break
                if todo:
                    break
            if todo is None:
                break
            fi, moves = todo
            for pairs in moves:
                records.append(copy.deepcopy(records[fi]))
                newIndex = len(records) - 1
                for sr in table.ScriptList.ScriptRecord:
                    for lang, ls in self._langSysPairs(sr):
                        if (sr.ScriptTag, lang) in pairs:
                            ls.FeatureIndex = sorted(newIndex if i == fi else i
                                                     for i in ls.FeatureIndex)
            split = True
        if split:
            table.FeatureList.FeatureCount = len(records)
            featureVars.sortFeatureList(table)

    def makeFeatureVariations(self, table, table_tag):
        keys = set(self.replace_variations_)
        for (_, _, featureTag), variations in self.feature_variations_.items():
            keys.update((featureTag, cs) for cs in variations)
        keys = sorted(keys)
        self._splitFeatures(table, table_tag, keys)
        langSystems = self._langSystems(table)
        for featureTag, conditionset in keys:
            # the variation's lookups in this table, for each feature record with the tag
            lookupsByFeature = {}
            for fi, fr in enumerate(table.FeatureList.FeatureRecord):
                if fr.FeatureTag != featureTag:
                    continue
                pairs = sorted(langSystems.get(fi, ()))
                lookupsByFeature[fi] = list(self._variationLookups(
                    pairs[0][0], pairs[0][1], featureTag, conditionset, table_tag)) if pairs else []

            replace, remove = False, None
            if (featureTag, conditionset) in self.replace_variations_:
                location, replace, names, lookups = \
                    self.replace_variations_[(featureTag, conditionset)]
                if not replace:
                    remove = [l.lookup_index for l in lookups if l.table == table_tag]
                    for name in names:
                        lookup = self.named_lookups_.get(name)
                        if lookup is None or lookup.table != table_tag:
                            continue    # a lookup in the other table
                        if not self._in_feature(lookup, featureTag):
                            raise FeatureLibError(f"Lookup {name} is not in feature "
                                                  f"{featureTag}, so it cannot be replaced",
                                                  location)
                        remove.append(lookup.lookup_index)

            # only features that change get a substitution
            fl = table.FeatureList.FeatureRecord
            changing = {fi: idx for fi, idx in lookupsByFeature.items()
                        if idx or (remove and set(remove) & set(fl[fi].Feature.LookupListIndex))}
            if not changing:
                continue

            conditions = []
            for axis, (lo, hi) in sorted(self.conditionsets_.get(conditionset, {}).items()):
                try:
                    conditions.append(buildAxisCondition(self.font, axis, lo, hi))
                except ValueError as e:
                    raise FeatureLibError(f"Condition set {conditionset}: {e}", None)
            for testTable, lookupType, subtableFormat in self.lookuptests_.get(conditionset, []):
                if testTable != table_tag:
                    raise FeatureLibError(
                        f"Condition set {conditionset} tests for a {testTable} lookup, but "
                        f"is used for {table_tag} lookups in feature {featureTag}", None)
                conditions.append(buildLookupSupportCondition(lookupType, subtableFormat))
            addConditionalFeature(table, featureTag, conditions, [], replace=replace,
                                  remove=remove, lookupsByFeature=changing)

    def _in_feature(self, lookup, featureTag):
        return any(lookup in builders for (_, _, tag), builders in self.features_.items()
                   if tag == featureTag)


def addOpenTypeFeatures(font, featurefile, tables=None, debug=False):
    '''As fontTools.feaLib.builder.addOpenTypeFeatures, with the PolyKern additions.'''
    Builder(font, featurefile).build(tables=tables, debug=debug)


def addOpenTypeFeaturesFromString(font, features, filename=None, tables=None, debug=False):
    import io
    featurefile = io.StringIO(features)
    if filename:
        featurefile.name = filename
    addOpenTypeFeatures(font, featurefile, tables=tables, debug=debug)
