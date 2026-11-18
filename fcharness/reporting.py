"""Turn a finished (or failed) pipeline into the plain-language report."""
import json
import os

import numpy as np

from . import verdict
from .report import Report

DIRS = ["side-to-side (x)", "front-to-back (y)", "up-and-down (z)", "twisting about x", "twisting about y", "twisting about z"]


def _v(x, fmt="%.1f"):
    return "(" + ", ".join(fmt % c for c in x) + ")"


def build(pl, failed):
    j = pl.job
    R = Report("Design review: %s" % j.get("name", "?"))
    levels = []
    R.p("This report was generated automatically by **fcharness** from `%s`. It is a first engineering look meant to help "
        "you decide - not a certification. Every number comes from a computer model with the assumptions listed at the end."
        % os.path.basename(j.get("model", "?")))
    if failed:
        stage, err = failed
        R.verdict("red", "Analysis stopped at step '%s'" % stage, str(err))
        errs = [p for p in pl.problems if p.level == "error"]
        if errs:
            R.table(["where", "problem", "how to fix"], [[p.where, p.message, p.fix] for p in errs])
    # ---- summary (filled after the sections, inserted at index)
    summary_at = len(R.blocks)
    # ---- model
    if hasattr(pl, "parts"):
        R.h(2, "1. What was analysed")
        if hasattr(pl, "setup_png"):
            R.img("img/setup.png", "The model as the harness sees it. Blue faces are held fixed; orange faces carry the loads (arrows).")
        R.table(["part", "subassembly", "material", "mass (g)", "size x×y×z (mm)"],
                [[r["part"], r["group"] or "-", r["material"], "%.1f" % (1000 * r["mass_kg"]),
                  "×".join("%.0f" % b for b in r["bbox_mm"]) if any(r["bbox_mm"]) else "-"] for r in getattr(pl, "mass", {}).get("parts", [])])
        if hasattr(pl, "mass"):
            m = pl.mass
            R.p("**Total mass %.1f g**, centre of gravity at %s mm." % (1000 * m["total_mass_kg"], _v(m["cg_mm"])))
        if j.get("supports"):
            R.bullets(["**Held:** %s - `%s`" % (s.get("name", "support"), json.dumps(s["where"])) for s in j["supports"]])
        for lc in j.get("load_cases", []):
            parts = ["%s: %.0f N towards %s" % (f.get("name", "force"), np.linalg.norm(f["force_N"]), _v(np.asarray(f["force_N"]) / max(np.linalg.norm(f["force_N"]), 1e-9), "%.2f"))
                     for f in lc.get("forces", [])]
            if lc.get("gravity_g"):
                parts.append("gravity %s g" % _v(lc["gravity_g"], "%g"))
            R.bullets(["**Load case '%s':** %s" % (lc["name"], "; ".join(parts))])
        for pm in j.get("point_masses", []):
            R.bullets(["**Carried mass:** %s, %.2f kg at %s mm" % (pm.get("name", "mass"), pm["mass_kg"], _v(pm["at"]))])
    # ---- strength
    for k, rv in enumerate(getattr(pl, "review", [])):
        R.h(2, "2.%d Strength and stiffness - load case '%s'" % (k + 1, rv["name"]))
        R.img(os.path.relpath(rv["img_stress"], pl.out), "Where the material works hardest (red). The shape is exaggerated so you can see how it bends.")
        for pp in rv["parts"]:
            levels.append(pp["level"])
            R.verdict(pp["level"], "%s: safety factor %.1f" % (pp["part"], pp["sf"]), pp["text"])
        R.table(["part", "highest stress (MPa)", "peak incl. support edges", "material can take (MPa)", "safety factor", "hot-spot at (mm)"],
                [[pp["part"], "%.1f" % pp["vm_MPa"], "%.1f" % pp["vm_peak_MPa"], "%.0f" % pp["allowable_MPa"], "%.2f" % pp["sf"],
                  _v(pp["hotspot_mm"], "%.0f")] for pp in rv["parts"]])
        levels.append(rv["defl_level"])
        R.verdict(rv["defl_level"], "Stiffness", rv["defl_text"] + " Largest movement at %s mm." % _v(rv["umax_at"], "%.0f"))
        R.img(os.path.relpath(rv["img_disp"], pl.out), "How far each point moves under this load case.")
        st = pl.static[k]
        R.p("Check: the supports push back with %s N, balancing the applied %s N (error %.2f%%). Per support: %s."
            % (_v(st["reaction_N"]), _v(st["applied_N"]), 100 * rv["equilibrium_err"],
               "; ".join("%s %s N" % (n, _v(v)) for n, v in st["reactions_by_support"].items())))
        worst = [pp for pp in rv["parts"] if pp["level"] != "green"]
        if worst:
            R.p("**What to change:** the hot-spot near %s mm limits the design. Typical fixes: add material or a fillet/rib there, "
                "spread the load over a bigger area (washer, wider boss), or switch to a stronger material." % _v(worst[0]["hotspot_mm"], "%.0f"))
    # ---- vibration
    if getattr(pl, "modal", None) and pl.modal.get("freqs") and "level" in pl.modal:
        m = pl.modal
        R.h(2, "3. Vibration")
        R.img("img/modes.png", "The first natural vibration shapes. If something shakes the part near one of these frequencies, it can resonate.")
        levels.append(m["level"])
        R.verdict(m["level"], "Lowest natural frequency %.0f Hz" % m["freqs"][0], m["text"])
        rows = []
        tot = sum(sum(v) for v in m["eff_mass"]) if m["eff_mass"] else 0
        for i, f in enumerate(m["freqs"]):
            d = "-"
            if i < len(m["eff_mass"]):
                em = m["eff_mass"][i][:3]
                d = DIRS[int(np.argmax(em))] if max(em) > 0 else "-"
            share = ""
            if m["energy"] and len(pl.parts) > 1:
                es = {pl.parts[p]["label"]: v[i] for p, v in m["energy"].items() if i < len(v)}
                s = sum(es.values()) or 1
                share = ", ".join("%s %.0f%%" % (n, 100 * e / s) for n, e in sorted(es.items(), key=lambda x: -x[1])[:3])
            rows.append([i + 1, "%.1f" % f, d, share or "-"])
        R.table(["mode", "frequency (Hz)", "main motion", "which part flexes (strain energy)"], rows)
        R.p("**What to change:** to raise a frequency, make the part stiffer in the direction it moves in that mode "
            "(ribs, thicker walls, shorter overhangs) or make the carried mass lighter / closer to the supports.")
    # ---- drawing
    if getattr(pl, "drawing", None):
        R.h(2, "4. Drawing")
        R.img("drawing.png", "Auto-generated drawing sheet (%s, scale %s). Full-resolution: drawing.pdf / drawing.svg."
              % (pl.drawing["projection"].replace("_", "-"), pl.drawing["scale_text"]))
        R.p("[drawing.pdf](drawing.pdf) · [drawing.svg](drawing.svg) · the saved `model_with_analysis.FCStd` %s."
            % ("also contains an editable TechDraw page" if pl.drawing.get("techdraw_page_in_fcstd") else "has no TechDraw page (creation failed headless)"))
    # ---- assumptions
    R.h(2, "5. Assumptions and warnings")
    notes = ["Linear-elastic model: valid while nothing yields, buckles or slips. Supports are perfectly rigid (real ones flex a bit, "
             "which lowers frequencies slightly).",
             "Touching parts are treated as glued together; bolt preload, friction and gaps are not modelled.",
             "Printed plastics use the weaker across-layer (z) strength everywhere - conservative.",
             "Stress right at the edge of a fixed face or at a sharp inside corner is not reliable; the safety factor uses the highest "
             "stress at least one element away from supports (the peak is shown for reference)."]
    if hasattr(pl, "mesh"):
        st = pl.mesh.stats()
        notes.append("Mesh: %d nodes, %d quadratic tetrahedra, target size %g mm. Halve size_mm and re-run to confirm results change by only a few %%."
                     % (st["nodes"], st["tets"], j["mesh"]["size_mm"]))
    R.bullets(notes + [repr(p) for p in pl.problems if p.level == "warning"])
    R.h(2, "6. Reproduce")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    R.p("Run `FCH_JOB=%s fc run.py` from the repository. Every step's inputs/outputs are in `checkpoints/`; solver decks and logs in `work/`."
        % os.path.relpath(pl.job_path, repo))
    R.code(open(pl.job_path).read())
    # summary at the top
    overall = verdict.worst(levels) if levels else ("red" if failed else "amber")
    head = [("h", (2, "Verdict")), ("verdict", (overall, {"green": "Looks fine", "amber": "Usable, with caveats", "red": "Needs changes"}[overall],
                                                 "worst of the checks below (%d checked)." % len(levels)))]
    R.blocks[summary_at:summary_at] = head
    pl.report_paths = R.write(pl.out)
    with open(os.path.join(pl.out, "summary.json"), "w") as f:
        json.dump(dict(overall=overall, failed=failed[0] if failed else None, timings=pl.timings,
                       mass_kg=getattr(pl, "mass", {}).get("total_mass_kg"),
                       cases=[dict(name=r["name"], umax_mm=r["umax"], parts=[dict(part=p["part"], sf=p["sf"], vm=p["vm_MPa"]) for p in r["parts"]])
                              for r in getattr(pl, "review", [])],
                       freqs=getattr(pl, "modal", {}).get("freqs") if getattr(pl, "modal", None) else None), f, indent=1)
