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

# Fallback

Formats 2 to 5 are already defined (ConditionValue, and, or, negate). Format 6 relies on what engines already do with a condition format they don't recognise: the condition is not met, so the condition set does not match, and the feature keeps its default lookups. So:

- An engine that does not support FeatureVariations uses the default lookups.
- An engine that supports FeatureVariations but not format 6 uses the default lookups.
- An engine that supports format 6 uses the substituted lookups if it supports the lookup being tested for, and the default lookups otherwise.

In each case the engine gets lookups it can process, and never both sets.

# Example

A font kerns with a new GPOS lookup type 10, format 1, and also has ordinary pair kerning for engines that don't support it. The `kern` feature's default lookups are the pair-kerning lookups. Its FeatureVariations has a record whose condition set holds one ConditionTableFormat6 with `lookupType` 10 and `subtableFormat` 1, and whose FeatureTableSubstitution replaces the `kern` feature with one that lists the type 10 lookup instead.

A variable font that also varies the `kern` feature by axis can combine the two, using an and condition (format 3), or by giving each FeatureVariation record both conditions in its condition set.

# Questions

1. Should the condition also be able to test support for a whole table, or for a feature of a table, so that it can be used for things other than lookups?
