"""Load a model (FCStd / STEP / STL) and identify its parts and subassemblies; mass properties."""
import os
import FreeCAD as App
import Part

from . import materials

CONTAINERS = ("App::Part", "App::DocumentObjectGroup", "Assembly::AssemblyObject")


def _group_path(obj):
    path, cur = [], obj
    while True:
        parents = [p for p in cur.InList if p.TypeId in CONTAINERS]
        if not parents:
            break
        cur = parents[0]
        path.insert(0, cur.Label)
    return "/".join(path)


def _is_leaf(obj):
    """A solid nobody else consumes (e.g. not the Base of a Cut/Fusion/Pad chain)."""
    for p in obj.InList:
        if p.TypeId in CONTAINERS or p.TypeId.startswith("TechDraw") or p.TypeId.startswith("Fem"):
            continue
        if p.isDerivedFrom("Part::Feature") or p.TypeId == "PartDesign::Body":
            return False
    return True


def load(path):
    """Returns (doc, parts). parts: list of dict(name, label, group, shape) with shapes in global coords."""
    path = os.path.abspath(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fcstd":
        doc = App.openDocument(path)
    elif ext in (".step", ".stp", ".iges", ".igs", ".brep"):
        import Import
        doc = App.newDocument("model")
        if ext == ".brep":
            Part.show(Part.read(path), "Part")
        else:
            Import.insert(path, doc.Name)
    elif ext == ".stl":
        import Mesh
        doc = App.newDocument("model")
        m = Mesh.Mesh(path)
        sh = Part.Shape()
        sh.makeShapeFromMesh(m.Topology, 0.05)
        sol = Part.makeSolid(Part.makeShell(sh.Faces)) if sh.Faces else sh
        f = doc.addObject("Part::Feature", os.path.splitext(os.path.basename(path))[0])
        f.Shape = sol.removeSplitter() if sol.Faces else sol
    else:
        raise ValueError("unsupported model type %r (use FCStd, STEP, IGES, BREP or STL)" % ext)
    doc.recompute()
    parts = []
    for o in doc.Objects:
        if not hasattr(o, "Shape") or o.TypeId in CONTAINERS or o.TypeId.startswith(("TechDraw", "Fem", "App::")):
            continue
        if o.TypeId.startswith("PartDesign::") and o.TypeId != "PartDesign::Body":
            continue  # features inside a Body; the Body carries the final solid
        sh = o.Shape
        if sh.isNull() or not sh.Solids or not _is_leaf(o):
            continue
        g = sh.copy()
        try:
            g.Placement = o.getGlobalPlacement()
        except Exception:
            pass
        parts.append(dict(name=o.Name, label=o.Label, group=_group_path(o), shape=g, object=o))
    return doc, parts


def assign_materials(parts, job):
    for p in parts:
        over = job["parts"].get(p["label"]) or job["parts"].get(p["name"]) or {}
        key = over.get("material") or job.get("default_material")
        p["material"] = materials.get(key, job.get("materials"))
        p["print_direction"] = over.get("print_direction", "z")
        p["ignore"] = bool(over.get("ignore", False))
    return parts


def mass_properties(parts, point_masses=()):
    """Per-part and total mass (kg), CG (mm) and inertia about the total CG (kg*mm^2)."""
    rows, tm, mx = [], 0.0, App.Vector()
    for p in parts:
        sh = p["shape"]
        rho = p["material"]["rho"] * 1e-9  # kg/mm^3
        m = sh.Volume * rho
        cg = sh.CenterOfMass if hasattr(sh, "CenterOfMass") else sh.Solids[0].CenterOfMass
        rows.append(dict(part=p["label"], group=p["group"], material=p["material"]["name"], volume_cm3=sh.Volume / 1000.0,
                         mass_kg=m, cg_mm=[cg.x, cg.y, cg.z], bbox_mm=[sh.BoundBox.XLength, sh.BoundBox.YLength, sh.BoundBox.ZLength],
                         _I=sh.MatrixOfInertia, _rho=rho))
        tm += m
        mx += cg * m
    for pm in point_masses:
        v = App.Vector(*pm["at"])
        rows.append(dict(part=pm.get("name", "point mass"), group="(point mass)", material="-", volume_cm3=0.0,
                         mass_kg=pm["mass_kg"], cg_mm=list(pm["at"]), bbox_mm=[0, 0, 0], _I=None, _rho=0.0))
        tm += pm["mass_kg"]
        mx += v * pm["mass_kg"]
    cg = mx * (1.0 / tm) if tm else App.Vector()
    # inertia about total CG: own inertia + parallel axis
    J = [[0.0] * 3 for _ in range(3)]
    for r in rows:
        d = App.Vector(*r["cg_mm"]) - cg
        dv = [d.x, d.y, d.z]
        for i in range(3):
            for k in range(3):
                own = r["_I"].A[4 * i + k] * r["_rho"] if r["_I"] is not None else 0.0
                J[i][k] += own + r["mass_kg"] * ((d.Length ** 2 if i == k else 0.0) - dv[i] * dv[k])
    for r in rows:
        r.pop("_I")
        r.pop("_rho")
    return dict(parts=rows, total_mass_kg=tm, cg_mm=[cg.x, cg.y, cg.z], inertia_kg_mm2=J)
