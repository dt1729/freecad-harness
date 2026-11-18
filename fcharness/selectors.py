"""Turn plain geometric descriptions into face lists, so users never have to know "Face17".

Each selector returns a list of (part_index, face_index) tuples; face_index is 0-based (FreeCAD's
"Face%d" % (i+1))."""
import FreeCAD as App

TOL = 1e-3


def _cyl_radius(face):
    s = face.Surface
    return s.Radius if s.__class__.__name__ == "Cylinder" else None


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def is_hole(face):
    """True for a concave cylinder (hole, slot end), False for a convex one (pin, boss, outside fillet)."""
    s = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    n = face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    radial = (p - s.Center) - s.Axis * (p - s.Center).dot(s.Axis)
    return n.dot(radial) < 0


def select(sel, parts):
    kind, arg = next(iter(sel.items()))
    hits = []
    if kind == "faces":
        for pi, p in enumerate(parts):
            for fname in arg:
                i = int(fname[4:]) - 1
                if 0 <= i < len(p["shape"].Faces):
                    hits.append((pi, i))
        return hits
    if kind == "near_point":
        pt = App.Vector(*arg)
        best = None
        for pi, p in enumerate(parts):
            for i, f in enumerate(p["shape"].Faces):
                d = f.distToShape(Part_vertex(pt))[0]
                if best is None or d < best[0]:
                    best = (d, pi, i)
        return [best[1:]] if best else []
    if kind == "cylinders":
        r = 0.5 * arg["diameter"]
        tol = arg.get("tol", 0.02 * r + 0.01)
        kind = arg.get("kind", "hole")  # default: holes only - an R4 outside fillet is not a d8 hole
        for pi, p in enumerate(parts):
            for i, f in enumerate(p["shape"].Faces):
                rr = _cyl_radius(f)
                if rr is None or abs(rr - r) > tol:
                    continue
                if kind == "any" or (kind == "hole") == is_hole(f):
                    hits.append((pi, i))
        if "near" in arg and hits:
            pt = App.Vector(*arg["near"])
            # keep only faces of the cylinder (axis) closest to the point - a hole is often split in two faces
            def axis_dist(h):
                s = parts[h[0]]["shape"].Faces[h[1]].Surface
                c, a = s.Center, s.Axis
                v = pt - c
                return (v - a * v.dot(a)).Length
            dmin = min(axis_dist(h) for h in hits)
            hits = [h for h in hits if axis_dist(h) <= dmin + TOL]
        return hits
    if kind == "plane":
        n = App.Vector(*arg["normal"])
        n.normalize()
        at = arg.get("at", "outermost")
        ax = max(range(3), key=lambda k: abs(arg["normal"][k]))
        cand = []
        for pi, p in enumerate(parts):
            for i, f in enumerate(p["shape"].Faces):
                if f.Surface.__class__.__name__ != "Plane":
                    continue
                if _normal(f).dot(n) > 0.999:
                    c = f.CenterOfMass
                    cand.append((c.dot(n), (c.x, c.y, c.z)[ax], pi, i))
        if not cand:
            return []
        if at == "any":
            return [(pi, i) for _, _, pi, i in cand]
        if at == "outermost":
            # the face(s) furthest out in the direction they face, e.g. the underside for normal [0,0,-1]
            target = max(c[0] for c in cand)
            return [(pi, i) for d, _, pi, i in cand if abs(d - target) < 1e-2]
        return [(pi, i) for _, coord, pi, i in cand if abs(coord - float(at)) < 1e-2]
    raise ValueError("unknown selector %r" % kind)


def Part_vertex(pt):
    import Part
    return Part.Vertex(pt)


def describe(hits, parts):
    """Short human description: 'Bracket: Face3, Face5 (2 faces, 312 mm^2)'."""
    if not hits:
        return "nothing"
    by = {}
    area = 0.0
    for pi, i in hits:
        by.setdefault(parts[pi]["label"], []).append("Face%d" % (i + 1))
        area += parts[pi]["shape"].Faces[i].Area
    return "; ".join("%s: %s" % (k, ", ".join(v)) for k, v in by.items()) + " (%d faces, %.0f mm^2)" % (len(hits), area)
