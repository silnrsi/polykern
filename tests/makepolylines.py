#!/usr/bin/env python3
'''Boundary generation for the tests. The code is in tools/polykernlib/boundaries.py; this
module re-exports it and adds the Arabic helpers the tests use.'''

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))

from polykernlib.boundaries import *            # noqa: F401,F403
from polykernlib.boundaries import (PointsPen, FlattenPen, Boundary, simplify,  # noqa: F401
                                    embolden, makeBoundary, _inside)


def arabicGlyphs(font):
    '''All glyphs reachable from Arabic characters through GSUB, as a set of names.'''
    from fontTools import subset
    arabic = [u for r in ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                          (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)) for u in range(r[0], r[1] + 1)]
    cmap = font.getBestCmap()
    unicodes = [u for u in arabic if u in cmap]
    opts = subset.Options()
    opts.layout_features = ['*']
    opts.notdef_outline = False
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=unicodes)
    sub._closure_glyphs(font)
    return set(sub.glyphs_retained) - {".notdef"}


def makeAllBoundaries(font, margin=200, glyphs=None, maxArea=None):
    '''Return {glyph name: Boundary} for all Arabic glyphs with outlines.'''
    if glyphs is None:
        glyphs = arabicGlyphs(font)
    glyphSet = font.getGlyphSet()
    res = {}
    for g in sorted(glyphs):
        b = makeBoundary(glyphSet, g, margin, maxArea)
        if b is not None:
            res[g] = b
    return res
