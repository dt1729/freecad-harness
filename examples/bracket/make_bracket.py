"""Build the example L-bracket (bracket.FCStd + bracket.step) with plain Part operations.

    /usr/local/bin/fc examples/bracket/make_bracket.py

Base plate 80x40x6 with two M6 clearance holes (d6.6) to bolt it down, an upright 40x6x70 with a
d8 hole near the top where something hangs, and a central gusset."""
import os
import FreeCAD as App
import Part
import Import
from FreeCAD import Vector as V

HERE = os.path.dirname(os.path.abspath(__file__))

base = Part.makeBox(80, 40, 6)
upright = Part.makeBox(40, 6, 70, V(20, 34, 0))
gusset = Part.Face(Part.makePolygon([V(37, 34, 6), V(37, 10, 6), V(37, 34, 40), V(37, 34, 6)])).extrude(V(6, 0, 0))
shape = base.fuse(upright).fuse(gusset)
for x in (12, 68):
    shape = shape.cut(Part.makeCylinder(3.3, 20, V(x, 20, -5)))
shape = shape.cut(Part.makeCylinder(4.0, 20, V(40, 30, 58), V(0, 1, 0)))
shape = shape.removeSplitter()
# soften the outer upright corners a little (what a machinist would do)
edges = [e for e in shape.Edges if e.Curve.__class__.__name__ == "Line" and abs(e.BoundBox.ZMin - 0) < 1e-6
         and abs(e.BoundBox.ZMax - 6) < 1e-6 and e.BoundBox.YMin < 1e-6]
if edges:
    shape = shape.makeFillet(4.0, edges)

doc = App.newDocument("bracket")
obj = doc.addObject("Part::Feature", "Bracket")
obj.Shape = shape
obj.Label = "Bracket"
doc.recompute()
doc.saveAs(os.path.join(HERE, "bracket.FCStd"))
Import.export([obj], os.path.join(HERE, "bracket.step"))
open(os.path.join(HERE, "bracket_info.txt"), "w").write("volume_mm3 %.3f faces %d valid %s\n" % (shape.Volume, len(shape.Faces), shape.isValid()))
