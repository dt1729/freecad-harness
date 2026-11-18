"""Job description (what to analyse) and its strict structural validation. Pure Python.

A job is a dict (normally read from YAML). Only the keys below are allowed - a typo is an error, not
a silently ignored setting, because a non-ME user cannot tell that "suport" did nothing.

    name: bracket
    model: bracket.step              # FCStd / STEP / STL, relative to the job file
    default_material: al_6061_t6
    materials: {my_steel: {E: 210000, nu: 0.3, rho: 7850, yield_: 355}}   # optional custom materials
    parts:{Bracket: {material: al_6061_t6, print_direction: z}}   # optional per-part overrides
    supports:   [{name, type: fixed, where: <selector>}]
    point_masses: [{name, mass_kg, at: [x,y,z], attach: <selector>}]
    load_cases: [{name, gravity_g: [gx,gy,gz], forces: [{name, where: <selector>, force_N: [fx,fy,fz]}]}]
    analyses: [static, modal]
    modal: {modes: 6, avoid_hz: [lo, hi]}
    mesh: {size_mm: 3.0, order: 2}
    checks: {safety_factor_target: 2.0, safety_factor_min: 1.5}
    drawing: {projection: third_angle, title: "..."}

Selectors pick faces in plain geometric terms (see fcharness/selectors.py):
    {faces: [Face3, Face7]}                       explicit FreeCAD face names
    {plane: {normal: [0,0,-1], at: outermost}}    flat faces facing a direction (outermost | any | coord)
    {cylinders: {diameter: 6.6, near: [x,y,z], kind: hole}}  holes (default) / bosses (kind: boss) / any
    {near_point: [x,y,z]}                         the single face closest to a point
"""
from . import materials

ANALYSES = ("static", "modal", "buckling")
SUPPORT_TYPES = ("fixed",)
SELECTOR_KEYS = ("faces", "plane", "cylinders", "near_point")

TOP = dict(name=str, model=str, default_material=str, materials=dict, parts=dict, supports=list, point_masses=list,
           load_cases=list, analyses=list, modal=dict, mesh=dict, checks=dict, drawing=dict, report=dict)
DEFAULTS = dict(analyses=["static"], modal={"modes": 6}, mesh={"size_mm": 3.0, "order": 2},
                checks={"safety_factor_target": 2.0, "safety_factor_min": 1.5},
                drawing={"projection": "third_angle"}, supports=[], point_masses=[], load_cases=[], parts={}, materials={},
                report={})


class Problem:
    """One validation finding. level: 'error' blocks the run, 'warning' is reported but allowed."""

    def __init__(self, level, where, message, fix=""):
        self.level, self.where, self.message, self.fix = level, where, message, fix

    def as_dict(self):
        return dict(level=self.level, where=self.where, message=self.message, fix=self.fix)

    def __repr__(self):
        return "%s @ %s: %s%s" % (self.level.upper(), self.where, self.message, (" -> " + self.fix) if self.fix else "")


def _vec3(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)


def _check_keys(d, allowed, where, out):
    for k in d:
        if k not in allowed:
            out.append(Problem("error", where, "unknown key %r" % k, "allowed keys: " + ", ".join(sorted(allowed))))


def check_selector(sel, where, out):
    if not isinstance(sel, dict) or len(sel) != 1 or next(iter(sel)) not in SELECTOR_KEYS:
        out.append(Problem("error", where, "a selector must have exactly one of: " + ", ".join(SELECTOR_KEYS),
                           "e.g. where: {cylinders: {diameter: 6.6}}"))
        return
    kind, arg = next(iter(sel.items()))
    if kind == "faces" and not (isinstance(arg, list) and arg and all(isinstance(f, str) and f.startswith("Face") for f in arg)):
        out.append(Problem("error", where, "faces must be a list like [Face1, Face4]"))
    elif kind == "plane":
        if not isinstance(arg, dict) or not _vec3(arg.get("normal")):
            out.append(Problem("error", where, "plane needs normal: [x,y,z]"))
        elif arg.get("at", "outermost") not in ("outermost", "any") and not isinstance(arg.get("at"), (int, float)):
            out.append(Problem("error", where, "plane 'at' must be outermost, any or a coordinate along the normal axis"))
    elif kind == "cylinders":
        if not isinstance(arg, dict) or not isinstance(arg.get("diameter"), (int, float)) or arg["diameter"] <= 0:
            out.append(Problem("error", where, "cylinders needs a positive diameter (mm)"))
        elif "near" in arg and not _vec3(arg["near"]):
            out.append(Problem("error", where, "cylinders 'near' must be [x,y,z]"))
        elif arg.get("kind", "hole") not in ("hole", "boss", "any"):
            out.append(Problem("error", where, "cylinders 'kind' must be hole (default), boss or any"))
    elif kind == "near_point" and not _vec3(arg):
        out.append(Problem("error", where, "near_point must be [x,y,z]"))


def normalise(job):
    """Fill defaults (without mutating the input). Call after validate()."""
    j = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULTS.items()}
    for k, v in job.items():
        if isinstance(v, dict) and isinstance(j.get(k), dict):
            j[k] = dict(j[k], **v)
        else:
            j[k] = v
    return j


def validate(job):
    """Structural validation. Returns a list of Problem (empty = OK)."""
    out = []
    if not isinstance(job, dict):
        return [Problem("error", "job", "job file must be a mapping")]
    _check_keys(job, TOP, "job", out)
    for k, t in TOP.items():
        if k in job and not isinstance(job[k], t):
            out.append(Problem("error", k, "must be a %s" % t.__name__))
    if out:
        return out
    for k in ("name", "model"):
        if not job.get(k):
            out.append(Problem("error", k, "is required"))
    custom = job.get("materials", {})
    for key, m in custom.items():
        w = "materials.%s" % key
        if not isinstance(m, dict):
            out.append(Problem("error", w, "must be a mapping"))
            continue
        _check_keys(m, materials.CUSTOM_KEYS, w, out)
        for k in ("E", "nu", "rho"):
            if not isinstance(m.get(k), (int, float)) or m[k] <= 0:
                out.append(Problem("error", w, "%s must be a positive number (E in MPa, rho in kg/m^3)" % k))
        if m.get("kind", "metal") == "printed":
            if not all(isinstance(m.get(k), (int, float)) for k in ("strength_xy", "strength_z")):
                out.append(Problem("error", w, "printed materials need strength_xy and strength_z (MPa)"))
        elif not isinstance(m.get("yield_"), (int, float)):
            out.append(Problem("error", w, "needs yield_ (MPa), the stress where it starts to bend permanently"))
    mats = [job.get("default_material")] + [p.get("material") for p in job.get("parts", {}).values() if isinstance(p, dict)]
    if not any(mats):
        out.append(Problem("error", "default_material", "no material given", "set default_material: al_6061_t6 (see materials.py)"))
    for m in mats:
        if m and m not in materials.LIBRARY and m not in custom:
            out.append(Problem("error", "material", "unknown material %r" % m, "choose from: " + ", ".join(sorted(materials.LIBRARY))))
    for pname, p in job.get("parts", {}).items():
        if not isinstance(p, dict):
            out.append(Problem("error", "parts.%s" % pname, "must be a mapping"))
            continue
        _check_keys(p, ("material", "print_direction", "ignore"), "parts.%s" % pname, out)
        if p.get("print_direction", "z") not in ("x", "y", "z"):
            out.append(Problem("error", "parts.%s" % pname, "print_direction must be x, y or z"))
    analyses = job.get("analyses", DEFAULTS["analyses"])
    for a in analyses:
        if a not in ANALYSES:
            out.append(Problem("error", "analyses", "unknown analysis %r" % a, "choose from " + ", ".join(ANALYSES)))
    names = set()
    for i, s in enumerate(job.get("supports", [])):
        w = "supports[%d]" % i
        if not isinstance(s, dict):
            out.append(Problem("error", w, "must be a mapping"))
            continue
        _check_keys(s, ("name", "type", "where"), w, out)
        if s.get("type", "fixed") not in SUPPORT_TYPES:
            out.append(Problem("error", w, "unsupported support type %r" % s.get("type"), "use: " + ", ".join(SUPPORT_TYPES)))
        check_selector(s.get("where"), w + ".where", out)
        names.add(s.get("name", w))
    if not job.get("supports"):
        out.append(Problem("error", "supports", "the part is not held anywhere - a static or buckling solve would just fly away",
                           "add at least one support, e.g. the bolt holes: {type: fixed, where: {cylinders: {diameter: 6.6}}}"))
    for i, pm in enumerate(job.get("point_masses", [])):
        w = "point_masses[%d]" % i
        if not isinstance(pm, dict):
            out.append(Problem("error", w, "must be a mapping"))
            continue
        _check_keys(pm, ("name", "mass_kg", "at", "attach", "inertia_kg_mm2"), w, out)
        if not isinstance(pm.get("mass_kg"), (int, float)) or pm["mass_kg"] <= 0:
            out.append(Problem("error", w, "mass_kg must be > 0"))
        if not _vec3(pm.get("at")):
            out.append(Problem("error", w, "at must be [x,y,z] (centre of gravity of the attached item, mm)"))
        check_selector(pm.get("attach"), w + ".attach", out)
        if "inertia_kg_mm2" in pm:
            out.append(Problem("warning", w, "rotary inertia of point masses is not yet applied (translational mass only)"))
    if ("static" in analyses or "buckling" in analyses) and not job.get("load_cases"):
        out.append(Problem("error", "load_cases", "static/buckling requested but no load case given"))
    for i, lc in enumerate(job.get("load_cases", [])):
        w = "load_cases[%d]" % i
        if not isinstance(lc, dict):
            out.append(Problem("error", w, "must be a mapping"))
            continue
        _check_keys(lc, ("name", "gravity_g", "forces"), w, out)
        if not lc.get("name"):
            out.append(Problem("error", w, "needs a name (it is shown in the report)"))
        if "gravity_g" in lc and not _vec3(lc["gravity_g"]):
            out.append(Problem("error", w, "gravity_g must be [gx,gy,gz] in multiples of g, e.g. [0,0,-1]"))
        if not lc.get("forces") and not lc.get("gravity_g"):
            out.append(Problem("error", w, "load case has neither forces nor gravity"))
        for k, f in enumerate(lc.get("forces", [])):
            wf = "%s.forces[%d]" % (w, k)
            if not isinstance(f, dict):
                out.append(Problem("error", wf, "must be a mapping"))
                continue
            _check_keys(f, ("name", "where", "force_N"), wf, out)
            if not _vec3(f.get("force_N")):
                out.append(Problem("error", wf, "force_N must be [fx,fy,fz] in newtons (1 kg weighs ~9.81 N)"))
            check_selector(f.get("where"), wf + ".where", out)
    mesh = job.get("mesh", {})
    _check_keys(mesh, ("size_mm", "order", "min_size_mm"), "mesh", out)
    if not isinstance(mesh.get("size_mm", 3.0), (int, float)) or mesh.get("size_mm", 3.0) <= 0:
        out.append(Problem("error", "mesh.size_mm", "must be a positive number"))
    if mesh.get("order", 2) != 2:
        out.append(Problem("error", "mesh.order", "only 2nd-order (curved, 10-node) tetrahedra are supported",
                           "linear tets are far too stiff in bending and give wrong answers"))
    modal = job.get("modal", {})
    _check_keys(modal, ("modes", "avoid_hz"), "modal", out)
    if "avoid_hz" in modal and not (isinstance(modal["avoid_hz"], list) and len(modal["avoid_hz"]) == 2):
        out.append(Problem("error", "modal.avoid_hz", "must be [low, high] in Hz"))
    _check_keys(job.get("checks", {}), ("safety_factor_target", "safety_factor_min"), "checks", out)
    _check_keys(job.get("drawing", {}), ("projection", "title", "enabled"), "drawing", out)
    if job.get("drawing", {}).get("projection", "third_angle") not in ("third_angle", "first_angle"):
        out.append(Problem("error", "drawing.projection", "must be third_angle or first_angle"))
    return out
