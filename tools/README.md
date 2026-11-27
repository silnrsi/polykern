# PolyKern tools

## polykernlib

Extensions to fontTools for the PolyKern lookup (GPOS type 10) and condition table format 6 (lookup support). They are added by subclassing and registering, not by changing fontTools. Importing `polykernlib` installs the new tables into ttLib.

| Module | What it holds |
| :--- | :--- |
| `ottables.py` | The PolyPos subtable and condition format 6 for ttLib, including TTX |
| `otlbuilder.py` | `PolyBoundary`, `PolyKernBuilder`, `buildLookupSupportCondition`, `addConditionalFeature` |
| `feaparser.py`, `feaast.py`, `feabuilder.py` | The feaLib parser, AST and builder with the new syntax |
| `feawriter.py` | Writes a PolyKern lookup as FEA |
| `boundaries.py` | Makes boundaries from glyph outlines; `scriptGlyphs` finds the glyphs a script reaches through GSUB |
| `ufolayer.py` | Writes boundaries into a UFO layer as open contours |

The FEA syntax is described in the proposals: `documentation/PolyKernLookup.md` (Feature file syntax) and `documentation/ConditionLookupSupport.md` (Feature file syntax).

```python
import polykernlib
from polykernlib.feabuilder import addOpenTypeFeatures
addOpenTypeFeatures(font, "features.fea")
```

## Making the boundary layer

Two steps, usually run once and then again whenever outlines change:

```
tools/polykernglyphs.py build/Font-Regular.ttf -o polykern-glyphs.txt
tools/polykernlayer.py source/Font-Regular.ufo -g polykern-glyphs.txt
```

- **`polykernglyphs.py font`** lists the glyphs that need a boundary. These are the glyphs the script (`-s`, default `Arab`) reaches through GSUB, starting from the script's characters in the cmap. The script's characters include Common and Inherited characters in the script's own blocks, such as U+06DD. Glyphs with no outline are left out. The names must be the UFO's. Either compile the font with the UFO's names, or give the UFO with `-u`: glyphs whose names aren't in the UFO are then matched by shape (outline bounds within `--tolerance`, preferring the same advance), and those that match nothing are reported. Unexported UFO glyphs (`public.skipExportGlyphs`, and names matching `--exclude`, default `^_`) are never matched.
- **`polykernlayer.py ufo -g list`** makes a boundary for each glyph in the list from its outline and writes it into the `org.sil.polykern` layer as one open contour, up the left side and down the right, so it is not filled. Without `-g`, every glyph already in the layer is remade from its outline. To keep a hand-edited boundary, leave it out of the list. The options:

  | Option | Meaning | Default |
  | :--- | :--- | :--- |
  | `-m` | Margin: the space kept around the ink, in %em | 10 (205 units at 2048 upm) |
  | `--markmargin` | Margin for glyphs with an `_` anchor, in %em | the same as `-m` |
  | `-e` | Most the simplified boundary may move from the emboldened outline, as % of the glyph's margin | 7.5 |
  | `-t` | How close the lines that replace curves must be to the curve, as % of the margin; they are always outside it | 2.5 |
  | `-l` | Layer name | `org.sil.polykern` |

To check the result, `polykernproof.py ufo -o proof.pdf` makes a PDF with one glyph per page: the filled outline, the boundary (its start marked), the axes and the advance. All pages use one scale, the largest at which every glyph fits its page, so the glyph needing the most room fills its page. `--fit` scales each glyph to fill its own page instead. The other options are `-g` (glyph list), `--pagesize`, `--landscape` and `-l` (layer).

### How a boundary is made

`polykernlib.boundaries.makeBoundary`, in font units:

1. **Lines.** The outline's curves are replaced by their control polygons, split in halves (de Casteljau) until within `tolerance` of the curve. A control polygon is always outside its curve, so these lines never cut into the ink.
2. **Inner contours** (inside another contour) are dropped.
3. **Emboldening.** Every edge is shifted out by the margin. At outward corners the shifted edges are joined round the corner at the margin (round joins: lines touching the circle of radius margin, as many as keep within `tolerance`), so every point is at least the margin from the ink and the end of a spike is rounded. Inward corners need nothing, since the shifted edges cross inside.
4. **Sides.** At the height of every point, and where the outermost line changes between those heights, the leftmost and rightmost lines give the left and right sides. Anything the emboldening has closed off (a c whose mouth is less than twice the margin) drops out here.
5. **Gap filling.** Notches in a side less than `closeGap` high (default twice the margin) are filled: the thinnest part of another boundary is twice the margin, so nothing can get in.
6. **Simplification.** Each side is simplified by greedy furthest reach: from each kept point, go as far as possible while every point passed is within `maxError` of the new line. This is within a few percent of the fewest points possible, and about 16% fewer than Douglas-Peucker.

So every boundary keeps the ink at least margin − maxError away (about 190 units with the defaults at 2048 upm) and adds at most about `tolerance` of extra space. On Awami at the defaults, boundaries average 22 points per glyph (left and right sides together), 47 at most. `tests/results/points_vs_error.svg` shows how the number of points falls as `maxError` rises.

## Scripts

These are copies of pysilfont scripts. Each one starts with a comment that says what has changed, so that it can go back into pysilfont.

- `psfbuildfea.py fea font -o out`: compiles a feature file into a font. Its Builder comes from polykernlib.
- `psfufo2ttf.py ufo ttf [-f fea]`: builds a TTF from a UFO. The `-f` option compiles a feature file into it.

## feax

`dev/patches/feax-polykern.patch` adds PolyKern to feax. It is held back until the syntax has been agreed more widely; it has not been applied to feax.

- it passes the new FEA syntax through;
- `polykern [@attached [@spaces]];` generates the PolyKern lookup's statements from the UFO's `org.sil.polykern` layer. It reads open contours as drawn (reversing them if they were drawn from the right) and also accepts closed ones.
- `polykernlookups TAG LOOKUP { fallback };` writes the support condition set and a `variation ... else` block.

## Tests

- `python3 -m pytest tests/test_polykernlib.py tests/test_apps.py`: fast unit tests on fonts made on the fly. The last test in `test_apps.py` goes from a UFO through feax to a compiled font, and is skipped unless feax has the patch.
- `tests/featest.py font`: writes the Awami test polylines as FEA, compiles them, and checks the result.
- `tests/compiletest.py font out words`: builds the lookup directly, then checks that kerning from the compiled table matches.
- `tests/stresstest.py font words`: kerns the corpus and checks for polyline and ink overlaps.
- `tests/graphitecompare.py`: compares PolyKern with the Graphite font and the font's own kerning, and writes the review PDFs in `tests/results/`.

The Awami test scripts take the margin in font units (`-m`, default 200).
