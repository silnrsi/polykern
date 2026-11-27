# PolyKern: where things stand

Written 27 November 2026, for picking the work up again after a break.

## What is here

| Path | What it is |
| :--- | :--- |
| `documentation/PolyKernLookup.md` | The proposal: GPOS lookup type 10. Includes the algorithm, the binary format, integration and the FEA syntax. |
| `documentation/ConditionLookupSupport.md` | The companion proposal: condition table format 6 (does the engine support a lookup type?), for fallbacks, plus the FEA `lookup` line, `else` and `replace`. |
| `documentation/PolyKernFAQ.md` | Why the algorithm is the way it is, with test evidence. |
| `tools/polykernlib/` | fontTools extensions: the binary table and TTX, the lookup builder, the FEA parser, AST and builder, boundary generation, the UFO layer. See `tools/README.md`. |
| `tools/polykernglyphs.py`, `polykernlayer.py`, `polykernproof.py` | Make the glyph list, make the `org.sil.polykern` boundary layer, make a PDF proof of it. |
| `tools/psfbuildfea.py`, `tools/psfufo2ttf.py` | Copies of pysilfont scripts that use the PolyKern compiler; each says what changed, so they can go back. |
| `tests/polykern.py` | The reference implementation of the algorithm, written to carry over to C. |
| `tests/test_polykernlib.py`, `tests/test_apps.py` | Fast unit tests: `python3 -m pytest tests/test_polykernlib.py tests/test_apps.py` (56 tests). |
| `tests/stresstest.py`, `featest.py`, `compiletest.py`, `graphitecompare.py`, `awamitest.py`, `widthhunt.py` | Awami tests and comparisons; results go in `tests/results/`. |
| `dev/FontToolsExtensions.md` | Notes on how fontTools is extended, and what else in fontTools needs work. |
| `dev/patches/feax-polykern.patch` | PolyKern support for feax. **Not applied, on purpose**: waiting for wider agreement on the syntax. |

The fonts in the project root are Awami Nastaliq OpenType previews: `AwamiPreviewB_nokern-Regular.ttf` (no kerning, design glyph names, used by the tests) and `AwamiPreviewB-Regular.ttf` (with its own kerning, for comparison). The matching source is `~/Work/NRSI/scripts/font-awami/source/masters/Awami-Regular.ufo`. The Graphite font used for comparison is `/usr/share/fonts/truetype/awami/AwamiNastaliq-Regular.ttf`. The test corpus is `~/Work/dev/awamiot/reslang.txt`.

## Decisions made, and why

- **Clusters and categories:** a skeleton cluster is a run of joined bases plus marks. Categories: ignored, attached (marks and joined bases, from one coverage table, no GDEF), space (a base with no boundary), kernable base, barrier. An attached glyph with no boundary never starts a cluster.
- **The walk back** keeps a running reach per cluster and stops when nothing further back can matter; the shift is capped at minus the previous cluster's width; the kern goes on the space between words where there is one. Evidence is in the FAQ.
- **The format:** 32-bit offsets, coverage plus offsets (not a class map: see Issues in the proposal), optional varIndexBases into the GDEF ItemVariationStore.
- **Fallback:** condition format 6 in FeatureVariations, usable in fonts without `fvar`. In FEA: `conditionset C { lookup GPOS 10 1; } C;` and `variation kern C { lookup PolyKern; } else { fallback } kern;` (`replace` is implemented and proposed too). No FEA without extensions can express a fallback.
- **FEA for the lookup:** `pos polybase GLYPHS <polyboundary x y, ...>;` and `pos polymark ...;`, `<polyboundary NULL>` for spaces and empty marks. The brackets were kept for consistency with `<anchor>` and room to extend.
- **fontTools:** extended by subclassing and monkey patching, not forked.
- **Boundaries** are open contours in the `org.sil.polykern` layer. Generation (see `tools/README.md`): bisect curves (outside the curve), embolden with round joins, take the sides, fill notches under twice the margin, simplify by greedy furthest reach. Defaults: margin 10%em, max error 7.5% of the margin, curve tolerance 2.5% of the margin. The error guarantees at least margin − error clearance; on Awami this gives about 22 points per glyph. The choice came from the chart `tests/results/points_vs_error.svg`.
- **Sizes** are given in %em for margins and as a percentage of the margin for errors, so the same settings work in any font.

## Outstanding

### Waiting on others

1. **FEA syntax agreement** with Adobe (AFDKO), fontTools and fontc: the `lookup` line in condition sets, `else`, `replace`, `pos polybase`/`polymark`, `<polyboundary>`. Until then the feax patch stays unapplied.
2. **feax:** apply `dev/patches/feax-polykern.patch` once agreed (it must be copied into the feax repo by hand). Open question first: should a given `@attached` class add to the derived marks instead of replacing them? As it is, marks left out are no longer attached.

### To report upstream (fontTools)

3. Recompiling Awami's GSUB crashes in `otTables.splitLigatureSubst` (`UnboundLocalError: newLen`). Happens whenever feaLib touches GSUB on a font that has it.
4. `feaLib.builder.makeFeatureVariations` applies a variation block to every feature record with that tag, ignoring `script` and `language` statements in the block. Our builder works per feature record and splits shared records.

### Spec and proposals

5. **Variable fonts** were set aside. Open question: each boundary needs consecutive variation indexes (all its values in one VarData). Require that, or add a DeltaSetIndexMap as COLRv1 does?
6. Add the sentence "glyphs that share a boundary should share a varIndexBase" to the Structure section of the proposal (suggested, never added).
7. `ConditionLookupSupport.md` open question: should the condition also test support for a whole table, or a feature?

### Not started

8. **An engine implementation** (HarfBuzz or similar). Nothing shapes with type 10 yet except `tests/polykern.py`, which was written to carry over to C.
9. **The rest of fontTools:** the subsetter, instancer and master merger know nothing of PolyPos or condition format 6. Subsetting a PolyKern font will probably drop or break the lookup. See `dev/FontToolsExtensions.md`.
10. **A real Awami OpenType build:** generate the layer into `Awami-Regular.ufo` itself (so far only into scratch copies), then feax (once patched), then compile, then test end to end.
11. **Mark margins:** decide whether Awami's marks want a smaller `--markmargin` (the FAQ's initial yeh dots).
12. **pysilfont:** put the changes to `psfbuildfea.py` and `psfufo2ttf.py` back into pysilfont.

### Housekeeping

13. Nothing is committed yet. `tests/__pycache__/` and `tools/polykernlib/__pycache__/` should go in a `.gitignore`. Decide whether `tests/results/` (PDFs and SVGs, several MB) belongs in the repository.

## How to rerun things

```
python3 -m pytest tests/test_polykernlib.py tests/test_apps.py
python3 tests/stresstest.py AwamiPreviewB_nokern-Regular.ttf ~/Work/dev/awamiot/reslang.txt -n 10000 -w 3000
python3 tests/featest.py AwamiPreviewB_nokern-Regular.ttf
python3 tests/compiletest.py AwamiPreviewB_nokern-Regular.ttf /tmp/out.ttf ~/Work/dev/awamiot/reslang.txt -n 1000

# the boundary layer and its proof (into a copy, not the source)
tools/polykernglyphs.py AwamiPreviewB_nokern-Regular.ttf -o tests/results/awami_boundary_glyphs.txt
tools/polykernlayer.py ~/Work/NRSI/scripts/font-awami/source/masters/Awami-Regular.ufo \
    -g tests/results/awami_boundary_glyphs.txt -o /tmp/AwamiPK.ufo
tools/polykernproof.py /tmp/AwamiPK.ufo -g tests/results/awami_boundary_glyphs.txt -o tests/results/awami_boundaries.pdf

# the review PDFs (Graphite, PolyKern and the font's own kerning)
G=/usr/share/fonts/truetype/awami/AwamiNastaliq-Regular.ttf
tests/graphitecompare.py AwamiPreviewB_nokern-Regular.ttf $G tests/results/review_lines.txt \
    -k AwamiPreviewB-Regular.ttf -p tests/results/review.pdf
tests/graphitecompare.py AwamiPreviewB_nokern-Regular.ttf $G tests/results/width_lines.txt \
    -k AwamiPreviewB-Regular.ttf -p tests/results/width_compare.pdf
```
