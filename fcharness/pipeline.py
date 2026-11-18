"""Checkpointed analysis pipeline.

    load -> materials -> setup (resolve supports/loads) -> validate (strict) -> mass -> mesh
         -> solve static / modal -> results review -> drawing -> report

Every stage writes out/<job>/checkpoints/NN_<stage>.json (status, summary, problems), so a failed
run says exactly where and why it stopped, and a human or an agent can inspect each step."""
import json
import os
import time
import traceback

import numpy as np
import FreeCAD as App

from . import job as jobmod, materials, model, selectors, mesh as meshmod, ccx, render, drawing, verdict
from .report import Report


class StageError(Exception):
    pass


class Pipeline:
    def __init__(self, job_path, out_root=None):
        import yaml
        self.job_path = os.path.abspath(job_path)
        self.base = os.path.dirname(self.job_path)
        raw = yaml.safe_load(open(self.job_path))
        self.problems = jobmod.validate(raw)
        self.job = jobmod.normalise(raw) if isinstance(raw, dict) else {}
        name = self.job.get("name") or os.path.splitext(os.path.basename(job_path))[0]
        self.out = os.path.join(out_root or os.path.join(self.base, "out"), name)
        self.ck = os.path.join(self.out, "checkpoints")
        self.img = os.path.join(self.out, "img")
        self.work = os.path.join(self.out, "work")
        for d in (self.ck, self.img, self.work):
            os.makedirs(d, exist_ok=True)
        for f in os.listdir(self.ck):  # checkpoints from an earlier run would be misleading
            if f.endswith(".json"):
                os.remove(os.path.join(self.ck, f))
        self.n = 0
        self.state = {}
        self.timings = {}

    # ------------------------------------------------------------------ infrastructure
    def checkpoint(self, stage, status, summary, problems=()):
        self.n += 1
        rec = dict(stage=stage, status=status, time=time.strftime("%Y-%m-%dT%H:%M:%S"), summary=summary,
                   problems=[p.as_dict() if hasattr(p, "as_dict") else p for p in problems])
        with open(os.path.join(self.ck, "%02d_%s.json" % (self.n, stage)), "w") as f:
            json.dump(rec, f, indent=1, default=_jsonable)
        return rec

    def stage(self, name, fn):
        t0 = time.time()
        try:
            summary = fn()
        except StageError as e:
            self.checkpoint(name, "failed", str(e), [p for p in self.problems if p.level == "error"])
            raise
        except Exception as e:
            self.checkpoint(name, "failed", "%s: %s" % (type(e).__name__, e), [dict(trace=traceback.format_exc()[-2000:])])
            raise
        self.timings[name] = round(time.time() - t0, 2)
        self.checkpoint(name, "ok", summary)
        return summary

    def run(self):
        steps = [("load", self.s_load), ("materials", self.s_materials), ("setup", self.s_setup), ("validate", self.s_validate),
                 ("mass", self.s_mass)]
        if self.job["supports"] and (set(self.job["analyses"]) & {"static", "modal"}):
            steps.append(("mesh", self.s_mesh))
            if "static" in self.job["analyses"]:
                steps.append(("solve_static", self.s_static))
            if "modal" in self.job["analyses"]:
                steps.append(("solve_modal", self.s_modal))
            steps.append(("review", self.s_review))
        if self.job["drawing"].get("enabled", True):
            steps.append(("drawing", self.s_drawing))
        failed = None
        try:
            for name, fn in steps:
                self.stage(name, fn)
        except Exception as e:
            failed = (name, e)
        self.write_report(failed)
        self.save_model()
        return failed

    # ------------------------------------------------------------------ stages
    def s_load(self):
        if any(p.level == "error" for p in self.problems):
            raise StageError("the job file has errors: " + "; ".join(repr(p) for p in self.problems if p.level == "error"))
        path = os.path.join(self.base, self.job["model"])
        if not os.path.exists(path):
            self.problems.append(jobmod.Problem("error", "model", "file not found: %s" % path))
            raise StageError("model file not found: %s" % path)
        self.doc, self.parts = model.load(path)
        if not self.parts:
            raise StageError("no solid parts found in %s" % path)
        self.model_path = path
        return dict(parts=[dict(label=p["label"], group=p["group"], faces=len(p["shape"].Faces), volume_mm3=p["shape"].Volume)
                           for p in self.parts])

    def s_materials(self):
        model.assign_materials(self.parts, self.job)
        return {p["label"]: p["material"]["key"] for p in self.parts}

    def s_setup(self):
        j = self.job
        self.sel = dict(supports=[], forces=[], masses=[])
        for s in j["supports"]:
            hits = selectors.select(s["where"], self.parts)
            self.sel["supports"].append((s.get("name", "support"), hits))
        for lc in j["load_cases"]:
            for f in lc.get("forces", []):
                hits = selectors.select(f["where"], self.parts)
                self.sel["forces"].append((lc["name"], f.get("name", "force"), hits, f["force_N"]))
        for pm in j["point_masses"]:
            self.sel["masses"].append((pm.get("name", "mass"), selectors.select(pm["attach"], self.parts), pm))
        out = dict(supports={n: selectors.describe(h, self.parts) for n, h in self.sel["supports"]},
                   forces={"%s / %s" % (a, b): selectors.describe(h, self.parts) for a, b, h, _ in self.sel["forces"]},
                   point_masses={n: selectors.describe(h, self.parts) for n, h, _ in self.sel["masses"]})
        # picture of the set-up: supports blue, loaded faces orange, arrows, masses
        hl, arrows, pts = [], [], []
        for _, hits in self.sel["supports"]:
            hl += [(pi, fi, "#2f6fd6") for pi, fi in hits]
        for lcname, fname, hits, F in self.sel["forces"]:
            hl += [(pi, fi, "#f08a24") for pi, fi in hits if (pi, fi, "#2f6fd6") not in hl]
            if hits:
                c = np.mean([list(self.parts[pi]["shape"].Faces[fi].CenterOfMass) for pi, fi in hits], axis=0)
                arrows.append((c, F, "#d0461b", "%s: %.0f N" % (fname, np.linalg.norm(F))))
        for n, hits, pm in self.sel["masses"]:
            pts.append((pm["at"], "%s %.2f kg" % (n, pm["mass_kg"])))
        self.setup_png = render.parts_figure(self.parts, os.path.join(self.img, "setup.png"),
                                             "Set-up: blue = held fixed, orange = loaded", hl, arrows, pts)
        return out

    def s_validate(self):
        P = jobmod.Problem
        probs = []
        hole_d = sorted({round(2 * f.Surface.Radius, 3) for p in self.parts for f in p["shape"].Faces
                         if f.Surface.__class__.__name__ == "Cylinder"})
        hint = "cylinder diameters in this model: %s" % (", ".join("%g" % d for d in hole_d) or "none")
        for n, hits in self.sel["supports"]:
            if not hits:
                probs.append(P("error", "supports/" + n, "selector matched no faces", hint))
        for lc, fn, hits, F in self.sel["forces"]:
            if not hits:
                probs.append(P("error", "load %s/%s" % (lc, fn), "selector matched no faces", hint))
            sup = {h for _, hs in self.sel["supports"] for h in hs}
            if hits and set(hits) <= sup:
                probs.append(P("error", "load %s/%s" % (lc, fn), "load is applied only to fixed faces - it would do nothing",
                               "move the load or the support"))
        for n, hits, pm in self.sel["masses"]:
            if not hits:
                probs.append(P("error", "point_masses/" + n, "attach selector matched no faces", hint))
        diag = max(p["shape"].BoundBox.DiagonalLength for p in self.parts)
        for n, hits, pm in self.sel["masses"]:
            bb = App.BoundBox()
            for p in self.parts:
                bb.add(p["shape"].BoundBox)
            v = App.Vector(*pm["at"])
            if not bb.isInside(v) and min(abs(v.x - bb.Center.x), 1e9) > 3 * diag:
                probs.append(P("warning", "point_masses/" + n, "mass centre is far outside the model - check units are mm"))
        hmesh = self.job["mesh"]["size_mm"]
        small = [d for d in hole_d if d < hmesh]
        if small:
            probs.append(P("warning", "mesh.size_mm", "mesh size %g mm is larger than holes of %s mm - stresses around them will be rough"
                           % (hmesh, ", ".join("%g" % d for d in small)), "use a smaller size_mm for a final check"))
        thin = min(min(p["shape"].BoundBox.XLength, p["shape"].BoundBox.YLength, p["shape"].BoundBox.ZLength) for p in self.parts)
        if hmesh > thin:
            probs.append(P("error", "mesh.size_mm", "mesh size %g mm exceeds the thinnest part dimension %.1f mm" % (hmesh, thin),
                           "set mesh.size_mm to at most half the wall thickness"))
        for p in self.parts:
            if not p["shape"].isValid():
                probs.append(P("warning", "model/" + p["label"], "solid reports invalid geometry; results may be unreliable"))
        self.problems += probs
        if any(p.level == "error" for p in probs):
            raise StageError("validation failed: " + "; ".join(repr(p) for p in probs if p.level == "error"))
        return dict(warnings=[repr(p) for p in self.problems if p.level == "warning"])

    def s_mass(self):
        self.mass = model.mass_properties(self.parts, self.job["point_masses"])
        return dict(total_mass_kg=self.mass["total_mass_kg"], cg_mm=self.mass["cg_mm"])

    def s_mesh(self):
        mj = self.job["mesh"]
        from .fcenv import QuietConsole
        with QuietConsole(os.path.join(self.work, "gmsh.log")):
            self.mesh, info = meshmod.mesh_parts(self.doc, self.parts, mj["size_mm"], mj.get("min_size_mm"))
        tri = lambda hits: np.unique(np.concatenate([self.mesh.boundary_on_face(self.parts[pi]["shape"].Faces[fi]) for pi, fi in hits]
                                                    + [np.zeros(0, dtype=np.int64)])).astype(np.int64)
        self.msel = dict(supports=[(n, tri(h)) for n, h in self.sel["supports"]],
                         forces=[(lc, fn, tri(h), F) for lc, fn, h, F in self.sel["forces"]],
                         masses=[(n, tri(h), pm) for n, h, pm in self.sel["masses"]])
        empty = [n for n, t in self.msel["supports"] if not len(t)] + [fn for _, fn, t, _ in self.msel["forces"] if not len(t)] + \
                [n for n, t, _ in self.msel["masses"] if not len(t)]
        if empty:
            raise StageError("mesh has no surface elements on: %s (face too small for the mesh size?)" % ", ".join(empty))
        if info["nodes"] > 400000:
            self.problems.append(jobmod.Problem("warning", "mesh", "%d nodes is heavy for a small machine" % info["nodes"]))
        mats = {pi: p["material"] for pi, p in enumerate(self.parts)}
        cases = []
        for lc in self.job["load_cases"]:
            fs = [(fn, t, F) for lcn, fn, t, F in self.msel["forces"] if lcn == lc["name"]]
            cases.append((lc["name"], lc.get("gravity_g"), fs))
        self.fe = ccx.Model(self.mesh, mats, self.msel["supports"],
                            [(n, pm["mass_kg"], pm["at"], t) for n, t, pm in self.msel["masses"]], cases)
        return info

    def s_static(self):
        self.fe.write_static(os.path.join(self.work, "static.inp"))
        ccx.run(self.work, "static")
        nn = len(self.mesh.nodes)
        blocks = ccx.read_frd(os.path.join(self.work, "static.frd"), nn)
        dat = ccx.read_dat(os.path.join(self.work, "static.dat"))
        disp = [b["data"] for b in blocks if b["name"] == "DISP"]
        stress = [b["data"] for b in blocks if b["name"] == "STRESS"]
        if len(disp) != len(self.job["load_cases"]):
            raise StageError("expected %d load-case results, CalculiX returned %d" % (len(self.job["load_cases"]), len(disp)))
        self.static = []
        for k, lc in enumerate(self.job["load_cases"]):
            U, S = disp[k], stress[k]
            vm = ccx.von_mises(S)
            rf = np.sum([dat["rf"]["SUP%d" % s][k] for s in range(len(self.fe.supports))], axis=0)
            applied = np.zeros(3)
            for lcn, fn, t, F in self.msel["forces"]:
                if lcn == lc["name"]:
                    applied += np.asarray(F, float)
            if lc.get("gravity_g"):
                applied += self.mass["total_mass_kg"] * 9.81 * np.asarray(lc["gravity_g"], float)
            self.static.append(dict(name=lc["name"], U=U, vm=vm, reaction_N=rf, applied_N=applied,
                                    reactions_by_support={self.fe.supports[s][0]: dat["rf"]["SUP%d" % s][k] for s in range(len(self.fe.supports))}))
        return [dict(case=r["name"], umax_mm=float(np.linalg.norm(r["U"], axis=1).max()), vm_max_MPa=float(r["vm"].max()),
                     reaction_N=r["reaction_N"], applied_N=r["applied_N"]) for r in self.static]

    def s_modal(self):
        nm = int(self.job["modal"].get("modes", 6))
        self.fe.write_modal(os.path.join(self.work, "modal.inp"), nm)
        ccx.run(self.work, "modal")
        nn = len(self.mesh.nodes)
        blocks = ccx.read_frd(os.path.join(self.work, "modal.frd"), nn)
        dat = ccx.read_dat(os.path.join(self.work, "modal.dat"))
        shapes = [b["data"] for b in blocks if b["name"] == "DISP"]
        freqs = dat["freq"][:len(shapes)]
        energy = {}
        for setn, vals in dat["energy"].items():
            if setn.startswith("P"):
                energy[int(setn[1:])] = vals
        self.modal = dict(freqs=freqs, shapes=shapes, eff_mass=dat["eff_mass"], energy=energy)
        # strict check: the solver must see all the mass we think is there (catches dropped point masses)
        # (ccx's rigid-body MPCs inflate this total by a few % in some directions, so test the minimum)
        solver_kg = 1000.0 * min(dat["total_mass"]) if dat["total_mass"] else None
        if solver_kg is not None:
            expect = sum(r["mass_kg"] for r in self.mass["parts"] if not any(p["ignore"] and p["label"] == r["part"] for p in self.parts))
            if solver_kg < 0.95 * expect:
                raise StageError("the solver only sees %.4f kg of the %.4f kg model mass - a point mass or part was lost"
                                 % (solver_kg, expect))
        return dict(freqs_hz=freqs, eff_mass=dat["eff_mass"], solver_mass_kg=solver_kg, solver_mass_xyz_t=dat["total_mass"])

    def s_review(self):
        chk = self.job["checks"]
        out = dict(cases=[])
        self.review = []
        h = self.job["mesh"]["size_mm"]
        sup_nodes = np.unique(np.concatenate([self.mesh.bnd[t].ravel() for _, t in self.msel["supports"]]))
        X = self.mesh.nodes
        # nodes within ~1 element of a support: peak stress there depends on how the support is modelled
        near = np.zeros(len(X), bool)
        for c in X[sup_nodes][:: max(1, len(sup_nodes) // 400)]:
            near |= np.linalg.norm(X - c, axis=1) < 1.2 * h
        size = max(p["shape"].BoundBox.DiagonalLength for p in self.parts)
        node_part = np.zeros(len(X), dtype=np.int64)
        node_part[self.mesh.tets.ravel()] = np.repeat(self.mesh.tet_part, 10)
        for r in getattr(self, "static", []):
            err = np.linalg.norm(r["reaction_N"] + r["applied_N"]) / max(np.linalg.norm(r["applied_N"]), 1e-9)
            if err > 0.01:
                self.problems.append(jobmod.Problem("error", "results/" + r["name"],
                                                    "reactions do not balance the loads (%.1f%% off) - the model is suspect" % (100 * err)))
            per_part = []
            for pi, p in enumerate(self.parts):
                mask = node_part == pi
                if not mask.any():
                    continue
                allow = materials.allowable(p["material"], "z")
                vm_all = r["vm"][mask].max()
                vm_far = r["vm"][mask & ~near].max() if (mask & ~near).any() else vm_all
                idx = np.where(mask & ~near)[0]
                hot = X[idx[np.argmax(r["vm"][idx])]] if len(idx) else X[np.argmax(r["vm"] * mask)]
                sf = allow / max(vm_far, 1e-9)
                lvl, txt = verdict.strength(sf, chk["safety_factor_target"], chk["safety_factor_min"])
                per_part.append(dict(part=p["label"], allowable_MPa=allow, vm_peak_MPa=vm_all, vm_MPa=vm_far, sf=sf,
                                     hotspot_mm=hot, level=lvl, text=txt))
            umag = np.linalg.norm(r["U"], axis=1)
            dl, dtxt = verdict.deflection(float(umag.max()), size)
            rec = dict(name=r["name"], equilibrium_err=err, parts=per_part, umax=float(umag.max()), umax_at=X[np.argmax(umag)],
                       defl_level=dl, defl_text=dtxt)
            self.review.append(rec)
            k = len(self.review)
            scale = 0.08 * size / max(umag.max(), 1e-12)
            rec["img_stress"] = render.field_figure(self.mesh, r["vm"], os.path.join(self.img, "stress_lc%d.png" % k),
                                                    "Load case %d '%s': stress (deformation x%.0f)" % (k, r["name"], scale),
                                                    "von Mises stress [MPa]", U=r["U"], scale=scale,
                                                    vmax=float(np.percentile(r["vm"], 99.5)),
                                                    note="Colour scale capped at the 99.5th percentile; peaks at sharp corners and supports are partly a modelling artefact.")
            rec["img_disp"] = render.field_figure(self.mesh, umag, os.path.join(self.img, "disp_lc%d.png" % k),
                                                  "Load case %d '%s': how far it moves" % (k, r["name"]), "displacement [mm]",
                                                  U=r["U"], scale=scale, cmap="viridis")
            out["cases"].append(dict(name=r["name"], equilibrium_err=err, umax_mm=rec["umax"],
                                     parts=[{k2: v for k2, v in pp.items() if k2 != "text"} for pp in per_part]))
        if hasattr(self, "modal") and self.modal["freqs"]:
            m = self.modal
            m["img"] = render.modes_figure(self.mesh, m["shapes"], m["freqs"], os.path.join(self.img, "modes.png"))
            lvl, txt = verdict.frequency(m["freqs"][0], self.job["modal"].get("avoid_hz"))
            m["level"], m["text"] = lvl, txt
            out["modal"] = dict(freqs=m["freqs"], level=lvl)
        if any(p.level == "error" for p in self.problems):
            raise StageError("results review found errors")
        return out

    def s_drawing(self):
        title = self.job["drawing"].get("title") or self.job["name"]
        rows = [dict(part=r["part"], material=r["material"], mass_kg=r["mass_kg"]) for r in self.mass["parts"] if r["group"] != "(point mass)"]
        base = os.path.join(self.out, "drawing")
        info = drawing.sheet(self.parts, base, title=title, projection=self.job["drawing"]["projection"], mass_rows=rows)
        page = drawing.add_techdraw_page(self.doc, self.parts, title)
        info["techdraw_page_in_fcstd"] = page is not None
        self.drawing = info
        return info

    def save_model(self):
        try:
            from .fcenv import QuietConsole
            with QuietConsole(os.path.join(self.work, "save.log")):
                self.doc.saveAs(os.path.join(self.out, "model_with_analysis.FCStd"))
        except Exception:
            pass

    # ------------------------------------------------------------------ report
    def write_report(self, failed):
        from .reporting import build
        build(self, failed)


def _jsonable(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, App.Vector):
        return [o.x, o.y, o.z]
    return str(o)
