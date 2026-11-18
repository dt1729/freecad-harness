"""CalculiX deck writer, runner and result readers.

We write our own .inp (instead of FreeCAD's ccxtools writer) because the harness needs things the
FEM workbench writer does not offer together: several load cases in one run, reaction totals per
support, point masses coupled to a surface, and per-part modal strain energy.
Units: mm, N, s, tonne, MPa."""
import os
import subprocess
import numpy as np

from . import fcenv, materials

G = 9810.0  # mm/s^2


def _fmt_ids(ids, per=12):
    ids = [int(i) + 1 for i in ids]
    return "\n".join(", ".join(str(x) for x in ids[k:k + per]) for k in range(0, len(ids), per))


def nodal_traction_loads(mesh, tri_idx, force):
    """Consistent nodal loads for a uniform traction on tri6 faces: corners get 0, each mid-node A/3.
    Returns dict node -> np.array(3) summing exactly to `force`."""
    A = mesh.tri_areas(tri_idx)
    t = np.asarray(force, dtype=float) / A.sum()
    out = {}
    for k, a in zip(tri_idx, A):
        for n in mesh.bnd[k, 3:]:
            out[int(n)] = out.get(int(n), 0.0) + t * a / 3.0
    return out


class Model:
    """Everything a deck needs, already resolved to mesh entities.

    supports:     [(name, tri_idx)]
    point_masses: [(name, mass_kg, at_xyz, tri_idx)]
    load_cases:   [(name, gravity_g_vec or None, [(fname, tri_idx, force_vec)])]"""

    def __init__(self, mesh, part_materials, supports, point_masses=(), load_cases=()):
        self.mesh, self.mats = mesh, part_materials
        self.supports, self.point_masses, self.load_cases = supports, list(point_masses), list(load_cases)

    def _common(self):
        m = self.mesh
        L = ["*HEADING", "fcharness deck", "*NODE, NSET=NALL"]
        L += ["%d, %.9g, %.9g, %.9g" % (i + 1, x, y, z) for i, (x, y, z) in enumerate(m.nodes)]
        self.ref_nodes = []
        nn = len(m.nodes)
        for k, (_, _, at, _) in enumerate(self.point_masses):
            L.append("%d, %.9g, %.9g, %.9g" % (nn + k + 1, at[0], at[1], at[2]))
            self.ref_nodes.append(nn + k + 1)
        used = sorted(set(int(p) for p in m.tet_part))
        eid = 0
        for p in used:
            L.append("*ELEMENT, TYPE=C3D10, ELSET=P%d" % p)
            for t in np.where(m.tet_part == p)[0]:
                eid += 1
                L.append("%d, %s" % (t + 1, ", ".join(str(int(n) + 1) for n in m.tets[t])))
        L.append("*ELSET, ELSET=ESOLID")
        L.append(", ".join("P%d" % p for p in used))
        ne = len(m.tets)
        for k, (name, mass, _, tri) in enumerate(self.point_masses):
            # The mass hangs on a rigid spider to its attachment faces (like a stiff pin in a hole).
            # NB: ccx's *COUPLING/*DISTRIBUTING silently drops a MASS element on the reference node from
            # the frequency analysis (effective modal mass excluded it), so we use *RIGID BODY.
            L += ["*ELEMENT, TYPE=MASS, ELSET=PM%d" % k, "%d, %d" % (ne + k + 1, self.ref_nodes[k]),
                  "*MASS, ELSET=PM%d" % k, "%.9g" % (mass * 1e-3)]
            L += ["*NSET, NSET=NPM%d" % k, _fmt_ids(np.unique(m.bnd[tri].ravel())),
                  "*RIGID BODY, NSET=NPM%d, REF NODE=%d" % (k, self.ref_nodes[k])]
        for p in used:
            mat = self.mats[p]
            L += ["*MATERIAL, NAME=M%d" % p, "*ELASTIC", "%.9g, %.6g" % (mat["E"], mat["nu"]),
                  "*DENSITY", "%.6e" % materials.ccx_density(mat),
                  "*SOLID SECTION, ELSET=P%d, MATERIAL=M%d" % (p, p)]
        for k, (name, tri) in enumerate(self.supports):
            nodes = np.unique(m.bnd[tri].ravel())
            L += ["*NSET, NSET=SUP%d" % k, _fmt_ids(nodes)]
        L.append("*BOUNDARY")
        L += ["SUP%d, 1, 3" % k for k in range(len(self.supports))]
        return L

    def write_static(self, path):
        L = self._common()
        for lc_i, (name, grav, forces) in enumerate(self.load_cases):
            L += ["** load case %d: %s" % (lc_i + 1, name), "*STEP", "*STATIC"]
            L.append("*DLOAD, OP=NEW")
            if grav is not None and any(grav):
                g = np.asarray(grav, float)
                gm = np.linalg.norm(g)
                L.append("ESOLID, GRAV, %.9g, %.9g, %.9g, %.9g" % (G * gm, g[0] / gm, g[1] / gm, g[2] / gm))
            loads = {}
            for _, tri, F in forces:
                for n, v in nodal_traction_loads(self.mesh, tri, F).items():
                    loads[n] = loads.get(n, 0.0) + v
            if grav is not None and any(grav):
                for k, (_, mass, _, _) in enumerate(self.point_masses):
                    loads[self.ref_nodes[k] - 1] = loads.get(self.ref_nodes[k] - 1, 0.0) + mass * 9.81 * np.asarray(grav, float)
            L.append("*CLOAD, OP=NEW")
            for n in sorted(loads):
                for d in range(3):
                    if abs(loads[n][d]) > 0:
                        L.append("%d, %d, %.9g" % (n + 1, d + 1, loads[n][d]))
            L += ["*NODE FILE", "U", "*EL FILE", "S"]
            for k in range(len(self.supports)):
                L += ["*NODE PRINT, NSET=SUP%d, TOTALS=ONLY" % k, "RF"]
            L.append("*END STEP")
        open(path, "w").write("\n".join(L) + "\n")

    def write_modal(self, path, modes=6):
        L = self._common()
        L += ["*STEP", "*FREQUENCY", "%d" % modes, "*NODE FILE", "U"]
        for p in sorted(set(int(p) for p in self.mesh.tet_part)):
            L += ["*EL PRINT, ELSET=P%d, TOTALS=ONLY" % p, "ELSE"]
        L.append("*END STEP")
        open(path, "w").write("\n".join(L) + "\n")


def run(workdir, job, nthreads=2, timeout=3600):
    if not fcenv.CCX:
        raise RuntimeError("CalculiX (ccx) not found")
    env = dict(os.environ, OMP_NUM_THREADS=str(nthreads), CCX_NPROC_EQUATION_SOLVER=str(nthreads))
    with open(os.path.join(workdir, job + ".log"), "w") as log:
        p = subprocess.run([fcenv.CCX, "-i", job], cwd=workdir, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    text = open(os.path.join(workdir, job + ".log")).read()
    if p.returncode != 0 or "*ERROR" in text:
        errs = [l.strip() for l in text.splitlines() if "ERROR" in l][:4]
        raise RuntimeError("CalculiX failed (log: %s/%s.log): %s" % (workdir, job, " | ".join(errs) or "exit %d" % p.returncode))
    return text


def read_frd(path, n_nodes):
    """Result blocks of a .frd: list of dict(step, value, name, data (n_nodes, ncomp)) for DISP and STRESS."""
    blocks = []
    cur = None
    with open(path) as f:
        for line in f:
            if line.startswith("  100C"):
                cur = dict(value=float(line[12:24]), step=int(line[58:63]) if len(line) > 63 else 0, name=None, rows={})
                continue
            if cur is None:
                continue
            if line.startswith(" -4 "):
                cur["name"] = line.split()[1]
                blocks.append(cur)
            elif line.startswith(" -1") and cur["name"] in ("DISP", "STRESS"):
                nid = int(line[3:13])
                rest = line[13:].rstrip("\n")
                cur["rows"][nid] = [float(rest[i:i + 12]) for i in range(0, len(rest), 12) if rest[i:i + 12].strip()]
            elif line.startswith(" -3"):
                cur = None
    out = []
    for b in blocks:
        if b["name"] not in ("DISP", "STRESS"):
            continue
        nc = 3 if b["name"] == "DISP" else 6
        a = np.zeros((n_nodes, nc))
        for nid, v in b["rows"].items():
            if nid <= n_nodes:
                a[nid - 1] = v[:nc]
        out.append(dict(step=b["step"], value=b["value"], name=b["name"], data=a))
    return out


def von_mises(S):
    sxx, syy, szz, sxy, syz, szx = S.T
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))


def _isfloat(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def read_dat(path):
    """Parse a .dat: reaction totals per set (in order of appearance), eigenfrequencies, effective
    modal mass and per-set energy totals."""
    lines = open(path).read().splitlines()
    res = dict(rf={}, freq=[], eff_mass=[], energy={}, total_mass=None)
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("total force (fx,fy,fz) for set"):
            setn = s.split("for set")[1].split()[0]
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            res["rf"].setdefault(setn, []).append([float(x) for x in lines[j].split()[:3]])
            i = j
        elif "internal energy" in s and "for set" in s:
            setn = s.split("for set")[1].split()[0]
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            res["energy"].setdefault(setn, []).append(float(lines[j].split()[0]))
            i = j
        elif "E I G E N V A L U E   O U T P U T" in s:
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("MODE NO"):
                j += 1
            j += 1
            while j < len(lines):
                t = lines[j].split()
                if len(t) >= 4 and t[0].isdigit():
                    res["freq"].append(float(t[3]))
                elif res["freq"] and t:
                    break
                j += 1
            i = j - 1
        elif "T O T A L   E F F E C T I V E   M A S S" in s:
            j = i + 1
            while j < len(lines) and not (lines[j].split() and _isfloat(lines[j].split()[0])):
                j += 1
            if j < len(lines):
                res["total_mass"] = [float(x) for x in lines[j].split()[:3]]
            i = j
        elif "E F F E C T I V E   M O D A L   M A S S" in s:
            j = i + 1
            while j < len(lines):
                t = lines[j].split()
                if len(t) >= 7 and t[0].isdigit():
                    res["eff_mass"].append([float(x) for x in t[1:7]])
                elif t and t[0] == "TOTAL":
                    break
                j += 1
            i = j
        i += 1
    return res
