# PolyKern: Frequently Asked Questions

Questions about the choices made in the PolyKern Lookup proposal (PolyKernLookup.md). The examples come from testing with Awami Nastaliq, using generated polylines and the reference implementation in the tests directory.

## Why does kerning a cluster look further back than the previous cluster?

Because something further back can reach past it. In آرام ٻُجھسی the madda of the first letter, آ, is wide and leans left over the letters after it, ر and ا. The next word starts high, and the nearest thing at that height is the madda, four clusters back. Checking only the previous cluster, or stopping at the first earlier cluster that doesn't change the shift, lets the start of ٻُجھسی run into the madda: by 494 font units in testing.

In testing over 100,000 lines, the shift was set by a cluster more than one back in about 1% of kerned clusters. It is rare, but common enough over a whole text that it has to be handled.

## Why keep a running reach, instead of checking each earlier cluster's own edge?

Because a cluster's marks can reach past the clusters after it. In یوداؔہ اِلتولد the takhallus (ؔ) is attached to an alef, but it is wide and reaches past the next cluster, ہ, to meet the start of the next word. Stopping the walk back once a cluster's own edge is clear of *F* misses it. With 25-unit margins this caused collisions in 12 of 50,000 test lines; the running reach caused none, and costs one comparison per cluster.

## Why does the walk back stop when no shift has been found yet?

Without that, a small cluster that overlaps nothing near it vertically would walk back to the start of the run, and could be pulled back over all the clusters in between to meet one far behind it. In testing, walking all the way back moved such clusters up to 6,000 units backwards, reordering the text on the page. Stopping once nothing further back could collide with the cluster where it is leaves it in place.

## Why can a cluster not move back past the start of the previous cluster?

Without that limit, the start of a word can slide back over a short previous cluster until it hangs over the middle of the word before, even though no polylines touch. The limit is the advance width of the previous cluster, so a cluster's origin never moves back past the previous cluster's origin, and the clusters keep the order of the text.

## Why does the kern go on the space between words, when there is one?

That is what the Graphite version of Awami Nastaliq does, and it keeps the advances of letters sensible. A large kern between words makes the space narrower, or negative, rather than a letter. In testing, putting the kern on the letter instead gave negative advances to letters in 1,461 places in 20,000 lines; putting it on the space cut that to 414, all inside words where there is no space.

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
