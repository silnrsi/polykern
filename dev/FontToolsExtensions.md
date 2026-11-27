# fontTools extensions needed for PolyKern

Notes on what our own tools will need to add to fontTools, by subclassing rather than forking. Line numbers are from fontTools 4.69.2.dev0 and will drift.

## FEA syntax to support

```
lookup PolyKern {
    lookupflag UseMarkFilteringSet @KernMarks;
    pos polybase [absReh absReh.fina] <polyboundary x y, x y, ...>;
    pos polybase [space uni00A0] <polyboundary NULL>;
    pos polymark [fatha kasra @AttachedBases] <polyboundary x y, x y, ...>;
    pos polymark glyph01922 <polyboundary NULL>;
} PolyKern;

conditionset HavePolyKern { lookup GPOS 10 1; } HavePolyKern;
variation kern HavePolyKern {
    lookup PolyKern;
} else {
    lookup PairKernFallback;
} kern;
```

The proposals describe the syntax in full: `documentation/PolyKernLookup.md` and `documentation/ConditionLookupSupport.md`, each under "Feature file syntax".

- **`pos polybase`:** adds the glyphs to the base coverage, and to the boundary coverage unless the boundary is NULL. A NULL boundary means the glyphs are spaces.
- **`pos polymark`:** adds the glyphs to the attached coverage, and to the boundary coverage unless the boundary is NULL. No GDEF is needed.
- **Sharing:** a class on the left means one shared boundary structure, and one varIndexBase for it.
- **`<polyboundary>` points:** one list of points going round the glyph, left side bottom to top, then right side top to bottom. The compiler splits it at the top:
  - left polyline: the first point through the leftmost point at the greatest y;
  - right polyline: the rightmost point at the greatest y through the end.
- **Compiler checks and calculations:** it checks the y order of each side and that each side has at least 2 points, and it calculates minPoint and maxPoint.
- **Variation:** any number may be a variable scalar. (Not implemented yet: variable fonts are set aside.)
- **Errors:**
  - a glyph given two roles in one lookup;
  - a `subtable` statement in a PolyKern lookup;
  - rules of any other type mixed into the lookup.
- **Warning:** `polybase` used on a GDEF mark.

## feaLib.parser, feaLib.ast, feaLib.builder

**Done:** `tools/polykernlib/feaparser.py`, `feaast.py`, `feabuilder.py`, and `feawriter.py`, which writes PolyKern lookups as FEA. They are tested by `tests/featest.py`. Variable fonts are left out for now.

- **Parser:**
  - `parse_position_` handles `pos polybase` and `pos polymark`;
  - `parse_polyboundary_` reads `<polyboundary NULL>` or `<polyboundary x y, x y, ...>`;
  - `parse_conditionset_` also accepts `lookup GPOS|GSUB <type> <format>;`;
  - `parse_feature_block_` accepts `replace` after a variation block's condition set, optionally with lookup names, and an `else` block after a variation block. This is a copy of fontTools' version, because there is no hook in the middle of it.
  - `parse_block_` is a copy of fontTools' version that can stop after the closing brace, so that `else` can follow. fontTools' version always reads the closing `TAG ;` itself.
- **AST:** `feaast` re-exports fontTools' ast and adds `PolyBoundary`, `PolyKernPosStatement`, and versions of `ConditionsetStatement` and `VariationBlock` that carry the lookup tests and the replace flag. All of them have `asFea`.
- **Builder:**
  - `add_polykern` adds the statements to a lookup;
  - `add_conditionset` doesn't need `fvar` when a condition set has no axis ranges;
  - `makeFeatureVariations` is replaced: it builds axis and lookup support conditions and uses `addConditionalFeature`. It handles `else`, where the substitute is the feature's lookups minus the else block's plus the variation block's, and `replace`, bare or with lookup names. It reports an error if a lookup support test names the other table.
  - `add_lookup_to_feature_` records the lookups an else block adds, while it is being built.
  - **Per feature record:** substitutions are worked out for each feature record, from the language systems that use it, so `script` statements in variation blocks are honoured. Where language systems share a record but need different substitutes, the record is split. fontTools' own `makeFeatureVariations` groups by feature tag only, so a variation for one script reaches every script's feature. That is worth reporting upstream.
  - `addOpenTypeFeatures` and `addOpenTypeFeaturesFromString` are stand-ins for feaLib's.
- **Outline splitting:** the left polyline ends at the leftmost point at the greatest y, and the right polyline starts at the rightmost one.

**fontTools bug found:** feaLib reads GSUB to set OS/2 `usMaxContext`, so GSUB is recompiled when the font is saved. Recompiling Awami's GSUB fails in `otTables.splitLigatureSubst` with an `UnboundLocalError` on `newLen`. The test works round this by keeping the original GSUB bytes.

## otlLib.builder

**Done:** `tools/polykernlib/otlbuilder.py`.

- **`PolyBoundary`:** a boundary, with `fromOutline` (splits the single list of points at the top) and `check` (point counts and y order).
- **`PolyKernBuilder(LookupBuilder)`:** `add_base` and `add_attached` take a boundary or None. It reports an error for a glyph given two roles or two different boundaries, and for a subtable break. It builds exactly one subtable, and equal boundaries share one structure.
- **`buildLookupSupportCondition`:** builds a condition table format 6.
- **`addConditionalFeature`:**
  - adds a FeatureVariations record for any kind of condition, without needing `fvar`;
  - creates the feature if it is missing, and merges records that have the same conditions;
  - has `replace` (use only the new lookups) and `remove` (take these lookups out, add the new ones) options, and `lookupsByFeature` to give each feature record its own lookups.

**Replace or add:** fontTools' `addFeatureVariationsRaw`, which feaLib uses for `variation` blocks, *adds* the variation's lookups to the feature's own lookups for every feature except `rvrn`. A fallback needs them to *replace* the fallback lookups, otherwise an engine that supports PolyKern gets the pair kerning as well. In FEA this is the `else` block (or `replace`).

**Still to do:** variable boundary values (see Variation under feaLib.builder).

## ttLib (a new GPOS subtable type)

**Done:** `tools/polykernlib/ottables.py`. ttLib is monkey patched without forking. Importing `polykernlib` is enough, and order does not matter as long as it comes before any GPOS or GSUB table is read or compiled. `tests/compiletest.py` checks it with Awami: binary and TTX round trips, extension lookups, and kerning from the compiled table.

How the prototype works:

- **The tables:** it describes the tables in the otData style (`FieldSpec` rows), creates the classes in the `otTables` namespace, and builds their converters with `otConverters.buildConverters`, just as `otTables._buildClasses` does.
  - `PolyPos` is a format switching table; `Boundary`, `VarIndexBases` and `PolyPoint` are plain tables.
  - Offsets must be typed, `LOffsetTo(Coverage)` and so on. A bare `LOffset` looks the class up by field name, which only works when the field is named after the table.
  - `VarIndexBase[BoundaryCount]` takes its count from the parent subtable, as `BaseRecord` does with `ClassCount`.
- **The lookup type:** it adds `otTables.lookupTypes["GPOS"][10] = PolyPos` and sets `PolyPos.LookupType = 10`. The converters hold a reference to the same dict object, not a copy, so they see the addition. JSTF shares the GPOS dict.
- **TTX reading:** it adds `PolyPos` to the reverse mappings, `Lookup.convertersByName` and each format of `ExtensionPos.convertersByName`. These were filled in when the classes were built, so they need the entry added by hand.
- **Condition format 6:** it adds format 6 to `ConditionTable.converters` and `ConditionTable.convertersByName`.
- **Sharing:** fontTools' compiler already writes identical subtables once. Shared boundary structures, and coverage tables shared with other lookups, cost nothing extra.

Also done:

- **Extension lookups:** work. fontTools wraps the Awami PolyKern lookup in an extension lookup when it resolves overflows, and it reads back correctly.
- **TTX layout:** points are written as attributes, `<LeftPoint index="0" x="107" y="-94"/>` (a `Struct` converter subclass), and the point counts as comments.

Still to do:

- **Variable boundaries:** each boundary needs a run of consecutive variation indexes, so all its values must be in one VarData. Decide whether to require that, or add a DeltaSetIndexMap as COLRv1 does.

## Elsewhere in fontTools to check

- **subset:** an unknown lookup type will probably be dropped or crash. It needs to subset the coverages and boundaries.
- **varLib.instancer:** must apply the deltas to the boundaries and drop the varIndexBases, and must keep format 6 conditions, which aren't axis based, when it instances FeatureVariations.
- **varLib merger:** if fonts are built by merging masters rather than from variable FEA, PolyKern subtables need a merger.
- **otTables overflow splitting** (otTables.py:2668): not needed, since the subtable has 32-bit offsets inside it, but check that nothing tries to split it.

## Outside fontTools

- **feaxlib:** done as a patch, `dev/patches/feax-polykern.patch`, made against feax e8eb01d, and **deliberately not applied** until the syntax has wider agreement. It adds:
  - pass-through for the new syntax;
  - `polykern [@attached [@spaces]];` to generate the lookup from the `org.sil.polykern` layer. Attached glyphs are those with an `_` anchor, spaces are other glyphs with no outline, bases are other glyphs with a layer contour. NULL in place of a class means work it out. Layer contours may be open (the normal form) or closed.
  - `polykernlookups TAG LOOKUP { fallback };` for the condition set and the `variation ... else` block.

  It includes tests (`tests/test_polykern.py`), and all 12 feax tests pass with it. **Trap:** a given `@attached` class replaces the derived list completely, so marks left out of it are no longer attached. Undecided whether it should add to the derived marks instead.
- **ufo2ft:** not pursued; feax does the UFO to FEA step.
- **The boundary layer tools:** done, `tools/polykernglyphs.py`, `tools/polykernlayer.py` and `tools/polykernproof.py` (see `tools/README.md`). Boundaries are open contours in `org.sil.polykern`.

## Open questions

- **FEA for replacing lookups:** decided: `variation kern C { ... } else { ... } kern;` is preferred, and `replace` (bare or with lookup names) is implemented and proposed as well. Both are written up in ConditionLookupSupport.md.
- **Variable fonts:** left out for now.
- **Upstream reports to make:** the `splitLigatureSubst` crash, and `makeFeatureVariations` ignoring `script` statements (both above).
