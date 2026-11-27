'''Write PolyKern lookups as FEA.'''

from .otlbuilder import PolyBoundary


def outlineOf(boundary):
    '''The single list of points going round the glyph, as <polyboundary> takes it.
    Raises ValueError if splitting that list at the top would not give back the same
    polylines (both polylines must reach the top of the boundary, with the left one
    ending at the leftmost top point and the right one starting at the rightmost).'''
    points = boundary.left + boundary.right
    if PolyBoundary.fromOutline(points) != boundary:
        raise ValueError("Both polylines must reach the top of the boundary")
    return points


def polyboundaryFea(boundary):
    if boundary is None:
        return "<polyboundary NULL>"
    return "<polyboundary " + ", ".join(f"{x} {y}" for x, y in outlineOf(boundary)) + ">"


def glyphsFea(glyphs):
    glyphs = list(glyphs)
    return glyphs[0] if len(glyphs) == 1 else "[" + " ".join(glyphs) + "]"


def polykernLookupFea(name, bases, attached, lookupflag=None, glyphOrder=None):
    '''FEA for a named PolyKern lookup.

    bases, attached: {glyph name: otlbuilder.PolyBoundary or None}.
    Glyphs with equal boundaries are put in one statement, so they share a boundary.
    glyphOrder, if given, orders the glyphs; otherwise they are sorted by name.
    '''
    order = {g: i for i, g in enumerate(glyphOrder)} if glyphOrder else None

    def key(g):
        return order[g] if order else g

    lines = [f"lookup {name} {{"]
    if lookupflag:
        lines.append(f"    lookupflag {lookupflag};")
    for role, mapping in (("polybase", bases), ("polymark", attached)):
        groups = {}                 # boundary -> glyphs, in first seen order
        for g in sorted(mapping, key=key):
            groups.setdefault(mapping[g], []).append(g)
        for boundary, glyphs in groups.items():
            lines.append(f"    pos {role} {glyphsFea(glyphs)} {polyboundaryFea(boundary)};")
    lines.append(f"}} {name};")
    return "\n".join(lines) + "\n"
