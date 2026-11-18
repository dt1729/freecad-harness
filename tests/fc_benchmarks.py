"""Analytical regression benchmarks, run through the full pipeline inside FreeCAD:

    /usr/local/bin/fc tests/fc_benchmarks.py

Cases adapted from freecad-fem-mcp's acceptance benchmarks (MIT, ymiya55) plus point-mass and gravity
cases that harness-only features need. Writes tests/bench_out/results.json and prints one PASS/FAIL
line per case; exit status is not usable through FreeCADCmd, so CI greps for 'BENCH FAIL'.
NB: FreeCADCmd re-runs a script whose top level raises, so nothing may escape this file."""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import yaml  # noqa: E402
import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Import  # noqa: E402

from fcharness.pipeline import Pipeline  # noqa: E402
from fcharness.fcenv import QuietConsole  # noqa: E402

OUT = os.path.join(HERE, "bench_out")
os.makedirs(OUT, exist_ok=True)
STEEL = {"steel_bench": {"name": "benchmark steel", "E": 210000.0, "nu": 0.3, "rho": 7850.0, "yield_": 250.0}}
E, RHO = 210000.0, 7850e-12


def box(name, L, b, h):
    path = os.path.join(OUT, name + ".step")
    doc = App.newDocument(name)
    o = doc.addObject("Part::Feature", name)
    o.Shape = Part.makeBox(L, b, h)
    doc.recompute()
    Import.export([o], path)
    App.closeDocument(doc.Name)
    return path


def job(name, model, **kw):
    j = dict(name=name, model=os.path.basename(model), default_material="steel_bench", materials=STEEL,
             supports=[dict(name="root", type="fixed", where={"plane": {"normal": [-1, 0, 0]}})],
             drawing={"enabled": False})
    j.update(kw)
    path = os.path.join(OUT, name + ".yaml")
    yaml.safe_dump(j, open(path, "w"), sort_keys=False)
    return path


def run(path):
    pl = Pipeline(path, OUT)
    with QuietConsole(os.path.join(OUT, "bench.log")):
        failed = pl.run()
    if failed:
        raise RuntimeError("pipeline failed at %s: %s" % failed)
    return pl


def cantilever_tip():
    L, b, h, P = 200.0, 20.0, 4.0, 10.0
    m = box("cantilever_solid", L, b, h)
    pl = run(job("cantilever_tip", m, analyses=["static"], mesh={"size_mm": 2.0},
                 load_cases=[dict(name="tip", forces=[dict(name="P", where={"plane": {"normal": [1, 0, 0]}}, force_N=[0, 0, -P])])]))
    I = b * h ** 3 / 12
    return abs(pl.static[0]["U"][:, 2]).max(), P * L ** 3 / (3 * E * I), 0.03


def cantilever_gravity():
    L, b, h, g = 200.0, 20.0, 4.0, 100.0
    m = box("cantilever_solid", L, b, h)
    pl = run(job("cantilever_gravity", m, analyses=["static"], mesh={"size_mm": 2.0},
                 load_cases=[dict(name="100 g", gravity_g=[0, 0, -g])]))
    I = b * h ** 3 / 12
    w = RHO * b * h * 9810.0 * g
    return abs(pl.static[0]["U"][:, 2]).max(), w * L ** 4 / (8 * E * I), 0.03


def modal_first_bending():
    L, b, h = 100.0, 10.0, 10.0
    m = box("modal_bar", L, b, h)
    pl = run(job("modal_bar", m, analyses=["modal"], modal={"modes": 4}, mesh={"size_mm": 2.5}))
    I, A = b * h ** 3 / 12, b * h
    f = 1.8751040687 ** 2 / (2 * math.pi * L ** 2) * math.sqrt(E * I / (RHO * A))  # 835.52 Hz
    return pl.modal["freqs"][0], f, 0.03


def modal_tip_mass():
    L, b, h, M = 100.0, 10.0, 10.0, 0.5
    m = box("modal_bar", L, b, h)
    pl = run(job("modal_tip_mass", m, analyses=["modal"], modal={"modes": 2}, mesh={"size_mm": 2.5},
                 point_masses=[dict(name="tip mass", mass_kg=M, at=[L, b / 2, h / 2], attach={"plane": {"normal": [1, 0, 0]}})]))
    I = b * h ** 3 / 12
    k = 3 * E * I / L ** 3
    m_eff = (M + 0.2357 * 7850.0 * b * h * L * 1e-9) * 1e-3  # Rayleigh: tip mass + 23.57% of beam mass, tonnes
    return pl.modal["freqs"][0], math.sqrt(k / m_eff) / (2 * math.pi), 0.04


results = {}
for fn in (cantilever_tip, cantilever_gravity, modal_first_bending, modal_tip_mass):
    try:
        got, ref, tol = fn()
        err = (got - ref) / ref
        ok = bool(abs(err) <= tol)
        results[fn.__name__] = dict(got=float(got), reference=ref, rel_error=float(err), tolerance=tol, ok=ok)
        print("BENCH %s %-22s got %.6g  theory %.6g  error %+.2f%% (tol %.0f%%)" % ("PASS" if ok else "FAIL", fn.__name__, got, ref, 100 * err, 100 * tol))
    except Exception as e:
        results[fn.__name__] = dict(ok=False, error=str(e)[:300])
        print("BENCH FAIL %-22s %s" % (fn.__name__, str(e)[:200]))
json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)
