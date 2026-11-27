# Condition Table Format 6: Lookup Support

M. Hosken, WSTech, SIL Global

# Introduction

When a new lookup type is added to OpenType, fonts that use it still need to work in shaping engines that do not support it. A font can include ordinary lookups that approximate the new one, but an engine that supports the new lookup would then apply both. There is currently no way for a font to say "use these lookups only if the engine does not support that one".

This proposal adds a condition table format, for use in FeatureVariations, that tests whether the shaping engine supports a given lookup type and subtable format. A font can then give a feature its fallback lookups by default, and substitute the new lookups when the engine supports them.

# Condition table format 6: lookup support

_ConditionTableFormat6_

| Type | Name | Description |
| :--- | :--- | :---------- |
| uint16 | format | Format identifier ― format \= 6 |
| uint16 | lookupType | The lookup type to test for |
| uint16 | subtableFormat | The subtable format to test for |

The condition is met if the shaping engine supports subtables of type `lookupType` and format `subtableFormat`, in the table (GSUB or GPOS) whose FeatureVariations contain the condition. Supports means that the engine processes such subtables as they are specified, wherever they are specified. Each engine answers for itself: for example, HarfBuzz might support a new lookup type while DirectWrite does not, and the same font then gets the new lookup in one and its fallback in the other. An engine that implements a subtable format only in part does not support it.

The test is of the subtable format, not just the lookup type, so that a later subtable format of an existing type can be tested for in the same way.

# Fonts that do not vary

FeatureVariations, and this condition in particular, may be used in a font that has no `fvar` table. Format 6 does not depend on the font varying, and most fonts that need a fallback for a new lookup will not vary. An engine that supports format 6 must evaluate FeatureVariations whether or not the font is variable. A condition set that holds only conditions that do not refer to an axis is evaluated in the same way in either kind of font. Font compilers that refuse to build FeatureVariations without an `fvar` table, as fontTools feaLib currently does, will need to allow it.

# Fallback

Formats 2 to 5 are already defined (ConditionValue, and, or, negate). Format 6 relies on what engines already do with a condition format they don't recognise: the condition is not met, so the condition set does not match, and the feature keeps its default lookups. So:

- An engine that does not support FeatureVariations uses the default lookups.
- An engine that supports FeatureVariations but not format 6 uses the default lookups.
- An engine that supports format 6 uses the substituted lookups if it supports the lookup being tested for, and the default lookups otherwise.

In each case the engine gets lookups it can process, and never both sets.

# Example

A font kerns with a new GPOS lookup type 10, format 1, and also has ordinary pair kerning for engines that don't support it. The `kern` feature's default lookups are the pair-kerning lookups. Its FeatureVariations has a record whose condition set holds one ConditionTableFormat6 with `lookupType` 10 and `subtableFormat` 1, and whose FeatureTableSubstitution replaces the `kern` feature with one that lists the type 10 lookup instead.

A variable font that also varies the `kern` feature by axis can combine the two, using an and condition (format 3), or by giving each FeatureVariation record both conditions in its condition set.

# Feature file syntax

The feature file syntax for FeatureVariations, implemented in fontTools and fontc, has `conditionset` statements, each of which may only hold axis ranges, and `variation` blocks, whose lookups are added to the feature's own lookups when the conditions are met. This proposal adds three things.

Without them, a fallback cannot be written in a feature file at all. There is no way to write a condition other than an axis range. And even with one, a `variation` block cannot take a lookup out of a feature: the FeatureTableSubstitution in the font replaces the feature's lookup list, but the compiler always builds that list from the feature's own lookups plus the block's. Putting the fallback in a `variation` block of its own, under the opposite condition, does not help either. The fallback must be in the default feature, for engines that do not understand the condition or do not support FeatureVariations. Today the only way is to edit the compiled table afterwards.

**A lookup support test in a condition set.** A line in a condition set may give a table, a lookup type and a subtable format:

```
conditionset PolyKernSupported {
    lookup GPOS 10 1;
} PolyKernSupported;
```

This becomes a ConditionTableFormat6. Since the condition tests the table that holds it, a condition set with a `lookup GPOS` line may only be used for GPOS lookups, and the same for GSUB; anything else is an error. A condition set may hold both axis ranges and lookup tests, which are then all ANDed. A condition set that holds no axis ranges does not need the font to have an `fvar` table.

**An else block.** A fallback needs the lookups it falls back from to be *replaced*, not added to. A `variation` block may be followed by an `else` block:

```
variation kern PolyKernSupported {
    lookup PolyKern;
} else {
    lookup PairKernFallback;
    pos uni0627 uni0628 -10;
} kern;
```

The `else` block is built into the feature just as a `feature` block would be, so its lookups are the feature's default lookups. When the conditions are met, the feature uses its lookups minus those from the `else` block, plus those from the `variation` block. This matches how FeatureVariations works: a default feature, and a substitute for it. Lookups that are in the feature from elsewhere, such as kerning for other scripts, stay in both. Inline rules and `script` and `language` statements may be used in either block.

**Replace.** As an alternative to `else`, `replace` after the condition set name says that the block's lookups replace the feature's own lookups when the conditions are met:

```
variation kern PolyKernSupported replace { lookup PolyKern; } kern;
variation kern PolyKernSupported replace PairKernFallback { lookup PolyKern; } kern;
```

On its own, `replace` replaces all the feature's lookups. Followed by lookup names, it replaces only those, and they must be in the feature. A block may not have both `replace` and `else`. `else` is usually clearer, since the fallback and its replacement are written together, and it allows the fallback to be written as inline rules.

# Questions

1. Should the condition also be able to test support for a whole table, or for a feature of a table, so that it can be used for things other than lookups?
