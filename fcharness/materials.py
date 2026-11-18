"""Material library. Pure Python.

Values are typical published figures, good enough for a first look - NOT certified allowables.
Printed plastics are anisotropic: strength across layers ("z", inter-layer) is much lower than along
them ("xy"). Until the harness knows the print orientation of every load path, checks use the
conservative z value; `allowable(mat, direction)` lets callers pick.

Units: E and strengths in MPa, density in kg/m^3.
"""

LIBRARY = {
    "al_6061_t6": dict(
        name="Aluminium 6061-T6", kind="metal", E=68900.0, nu=0.33, rho=2700.0, yield_=276.0, uts=310.0,
        fatigue=96.0, note="General-purpose machined aluminium. Fatigue value: 5e8 cycles, R=-1."),
    "al_5052_h32": dict(
        name="Aluminium 5052-H32", kind="metal", E=70300.0, nu=0.33, rho=2680.0, yield_=193.0, uts=228.0,
        fatigue=117.0, note="Sheet aluminium, bends well; weaker than 6061."),
    "steel_mild": dict(
        name="Mild steel (S235 / 1018-class)", kind="metal", E=205000.0, nu=0.29, rho=7870.0, yield_=235.0,
        uts=370.0, fatigue=180.0, note="Generic structural steel."),
    "stainless_304": dict(
        name="Stainless steel 304", kind="metal", E=193000.0, nu=0.29, rho=8000.0, yield_=215.0, uts=505.0,
        fatigue=240.0, note="Fasteners, shafts, corrosion-resistant parts."),
    "pla_printed": dict(
        name="PLA (FDM printed, ~100% infill)", kind="printed", E=3500.0, E_z=3000.0, nu=0.36, rho=1240.0,
        strength_xy=50.0, strength_z=25.0, note="Brittle, creeps under sustained load and softens above ~55 C."),
    "petg_printed": dict(
        name="PETG (FDM printed, ~100% infill)", kind="printed", E=2000.0, E_z=1800.0, nu=0.38, rho=1270.0,
        strength_xy=45.0, strength_z=25.0, note="Tougher than PLA, ~75 C softening."),
    "pet_cf_printed": dict(
        name="PET-CF (FDM printed, ~100% infill)", kind="printed", E=3500.0, E_z=2000.0, nu=0.35, rho=1300.0,
        strength_xy=60.0, strength_z=25.0, note="Stiff, fibre-filled; inter-layer bond is the weak point."),
    "abs_printed": dict(
        name="ABS (FDM printed, ~100% infill)", kind="printed", E=2100.0, E_z=1800.0, nu=0.35, rho=1040.0,
        strength_xy=35.0, strength_z=20.0, note="Warps when printing large parts; ~95 C softening."),
}


CUSTOM_KEYS = ("name", "kind", "E", "E_z", "nu", "rho", "yield_", "uts", "fatigue", "strength_xy", "strength_z", "note")


def get(key, custom=None):
    """Return a copy of a library (or job-defined custom) material, or raise KeyError listing valid keys."""
    lib = dict(LIBRARY, **(custom or {}))
    if key not in lib:
        raise KeyError("unknown material %r; choose one of: %s" % (key, ", ".join(sorted(lib))))
    m = dict(kind="metal", name=key, note="user-defined")
    m.update(lib[key])
    m["key"] = key
    return m


def allowable(mat, direction="z"):
    """Stress (MPa) at which the part is considered to fail: yield for metals, the in-layer ("xy")
    or inter-layer ("z") strength for printed plastics."""
    if mat["kind"] == "printed":
        return mat["strength_z"] if direction == "z" else mat["strength_xy"]
    return mat["yield_"]


def ccx_density(mat):
    """kg/m^3 -> tonne/mm^3 (CalculiX mm-N-s system)."""
    return mat["rho"] * 1e-12
