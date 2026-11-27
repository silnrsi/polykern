# PolyKern: Frequently Asked Questions

Questions about the choices made in the PolyKern Lookup proposal (PolyKernLookup.md). The examples come from testing with Awami Nastaliq, using generated polylines and the reference implementation in the tests directory. Unless it says otherwise, the figures are from November 2026: 69,414 lines (every one of the 49,414 words in the test corpus, and 20,000 random phrases of three to five words), with boundaries made by `tools/polykernlayer.py`'s method at a margin of 200 units (about 10% of the em). `tests/faqcheck.py` reproduces them.

## Why does kerning a cluster look further back than the previous cluster?

Because something further back can reach past it. In قِلایاؔہ گُذرانو the takhallus (ؔ) over the alef is wide, and reaches left past the next cluster, ہ, over the start of the next word, where the gaf rises to meet it. Checking only the previous cluster lets the gaf run into the takhallus: their boundaries overlap by 966 units and the ink collides.

Checking only the previous cluster gave ink collisions in 42 of the 69,414 test lines; the full algorithm gave none. The shift was set by a cluster more than one back for 334 of 262,672 kerned clusters (0.13%; 0.49% with 25-unit margins). It is rare, but common enough over a whole text that it has to be handled.

## Why keep a running reach, instead of checking each earlier cluster's own edge?

Because a cluster's marks can reach past the clusters after it. In یوداؔہ اِلتولد the takhallus (ؔ) is attached to an alef, but it is wide and reaches past the next cluster, ہ, to meet the start of the next word. Stopping the walk back once a cluster's own edge is clear of *F* can stop before reaching it: with 25-unit margins the boundaries in this line then overlap by 167 units. Over the test lines with 25-unit margins, stopping at each cluster's own edge gave ink collisions in 3 lines (boundaries overlapping by up to 240 units); the running reach gave none. With 200-unit margins the corpus happens to have no case where the two differ, but the reach costs only one comparison per cluster and is right whatever the margin.

## Why does the walk back stop when no shift has been found yet?

Without that, a small cluster that overlaps nothing near it vertically would walk back to the start of the run, and could be pulled back over all the clusters in between to meet one far behind it. In testing with neither this stop nor the cap below, clusters were pulled back by up to 6,823 units, reordering the text on the page; with either, the largest backward kern was 3,483 units. Stopping once nothing further back could collide with the cluster where it is leaves it in place, and also keeps the walk short.

## Why can a cluster not move back past the start of the previous cluster?

Without that limit, the start of a word can slide back over a short previous cluster until it hangs over the middle of the word before, even though no polylines touch. The limit is the advance width of the previous cluster, so a cluster's origin never moves back past the previous cluster's origin, and the clusters keep the order of the text. In testing the limit applied to 2,624 of 262,672 kerned clusters (1%). Without it, letters were given negative advances in 960 places instead of 612.

## Why does the kern go on the space between words, when there is one?

That is what the Graphite version of Awami Nastaliq does, and it keeps the advances of letters sensible. A large kern between words makes the space narrower, or negative, rather than a letter. In testing, putting the kern on the letter instead gave negative advances to letters in 1,987 places; putting it on the space cut that to 612, all where there is no space to take it.

## Why are the spaces' original advances used, rather than their current ones?

Because later clusters walk back past the same spaces, and need to know how much space the text has there. Once a space's advance holds a kern, it no longer says that.

## Why must the polylines include the margin, rather than the lookup adding space?

Because the algorithm brings polylines into contact, and has no other idea of how much space the designer wants. Putting all the spacing in the polylines leaves it entirely in the designer's hands, and lets it differ from glyph to glyph and from top to bottom of a glyph.

## Why do marks need as much margin as their bases?

So that a mark never ends up closer to another cluster than the glyph it is attached to. This does make PolyKern space some words more widely than Graphite does: the two dots of an initial yeh, which in Nastaliq sit under the previous letter, keep that letter at a distance. Whether a particular mark should tuck in like that is for the font designer to decide, through its polyline.

## Why are the boundaries not stored as glyphs, so that gvar can vary them?

That would add a glyph for every boundary, about a third more glyphs in a font like Awami Nastaliq, and a lot of extra glyph data. The ItemVariationStore that GPOS adjustments already use can vary the boundaries for 4 bytes each, and nothing at all in a font that does not vary.

## Does PolyKern work for left-to-right text?

Yes. Every step is written for both directions. In left-to-right text the earlier clusters are on the left, and the kern goes on the advance of the last glyph of the previous cluster, or on the space after it.
