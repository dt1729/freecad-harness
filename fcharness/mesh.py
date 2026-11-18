"""Mesh the parts with gmsh (through FreeCAD's FEM workbench) into 10-node tetrahedra.

Touching parts are first split with a general fuse so the mesh is conformal across their shared
faces (= parts bonded together, a sensible default for bolted/glued joints at first look).
Node ordering is rebuilt geometrically into CalculiX order so we never depend on the internal
ordering conventions of SMESH."""
import numpy as np
import FreeCAD as App
import Part
import ObjectsFem

from . import fcenv

# CalculiX C3D10: corners 0-3, then mid-nodes on edges (0,1) (1,2) (2,0) (0,3) (1,3) (2,3)
EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
# tet faces as corner triples, with the opposite corner (to orient normals outward)
FACES = [((0, 1, 2), 3), ((0, 1, 3), 2), ((1, 2, 3), 0), ((0, 2, 3), 1)]


class Mesh:
    """nodes (N,3) mm; tets (M,10) node indices in ccx order; tet_part (M,); bnd (K,6) outward tri6
    [c0,c1,c2,m01,m12,m20]; bnd_tet (K,) owning tet."""

    def __init__(self, nodes, tets, tet_part):
        self.nodes, self.tets, self.tet_part = nodes, tets, tet_part
        self._boundary()

    def _boundary(self):
        T = self.tets
        X = self.nodes
        tris, opp, own, fno = [], [], [], []
        for f, ((a, b, c), o) in enumerate(FACES):
            tris.append(T[:, [a, b, c]])
            opp.append(T[:, o])
            own.append(np.arange(len(T)))
            fno.append(np.full(len(T), f))
        tris = np.concatenate(tris)
        opp = np.concatenate(opp)
        own = np.concatenate(own)
        fno = np.concatenate(fno)
        key = np.sort(tris, axis=1)
        _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
        once = cnt[inv.ravel()] == 1
        tris, opp, own, fno = tris[once], opp[once], own[once], fno[once]
        self.bnd_face = fno  # ccx face label S1..S4 = fno+1 (FACES order matches ccx C3D10 faces)
        n = np.cross(X[tris[:, 1]] - X[tris[:, 0]], X[tris[:, 2]] - X[tris[:, 0]])
        flip = np.einsum("ij,ij->i", n, X[opp] - X[tris[:, 0]]) > 0
        tris[flip] = tris[flip][:, [0, 2, 1]]
        # mid nodes from the owning tet's edge table
        emap = {}
        for k, (a, b) in enumerate(EDGES):
            emap[(a, b)] = 4 + k
            emap[(b, a)] = 4 + k
        mids = np.zeros((len(tris), 3), dtype=np.int64)
        Town = T[own]
        for j, (p, q) in enumerate(((0, 1), (1, 2), (2, 0))):
            # local corner positions of tri corners p and q inside the owning tet
            lp = np.argmax(Town[:, :4] == tris[:, [p]], axis=1)
            lq = np.argmax(Town[:, :4] == tris[:, [q]], axis=1)
            col = np.array([emap[(int(a), int(b))] for a, b in zip(lp, lq)])
            mids[:, j] = Town[np.arange(len(tris)), col]
        self.bnd = np.concatenate([tris, mids], axis=1)
        self.bnd_tet = own

    def tri_areas(self, idx=None):
        B = self.bnd if idx is None else self.bnd[idx]
        X = self.nodes
        return 0.5 * np.linalg.norm(np.cross(X[B[:, 1]] - X[B[:, 0]], X[B[:, 2]] - X[B[:, 0]]), axis=1)

    def boundary_on_face(self, face, tol=0.05):
        """Indices of boundary triangles lying on a B-rep face: all 6 nodes on it (corner and mid-side
        nodes of quadratic elements sit on the true surface; a flat-triangle centroid would not)."""
        X = self.nodes
        B = self.bnd
        cen = X[B[:, :3]].mean(axis=1)
        bb = face.BoundBox
        lo = np.array([bb.XMin, bb.YMin, bb.ZMin]) - 2 * tol
        hi = np.array([bb.XMax, bb.YMax, bb.ZMax]) + 2 * tol
        cand = np.where(np.all((cen >= lo) & (cen <= hi), axis=1))[0]
        out = []
        for k in cand:
            ok = True
            for n in B[k, [3, 4, 5, 0, 1, 2]]:
                if not face.isInside(App.Vector(*X[n]), tol, True):
                    ok = False
                    break
            if ok:
                out.append(k)
        return np.array(out, dtype=np.int64)

    def stats(self):
        return dict(nodes=int(len(self.nodes)), tets=int(len(self.tets)), boundary_tris=int(len(self.bnd)))


def _reorder(nodes, raw):
    """raw (M,10) node indices in unknown quadratic-tet order (corners first) -> ccx order, positive volume."""
    X = nodes
    C = raw[:, :4].copy()
    v = np.einsum("ij,ij->i", np.cross(X[C[:, 1]] - X[C[:, 0]], X[C[:, 2]] - X[C[:, 0]]), X[C[:, 3]] - X[C[:, 0]])
    neg = v < 0
    C[neg] = C[neg][:, [0, 2, 1, 3]]
    M = raw[:, 4:]
    PM = X[M]  # (m,6,3)
    out = np.zeros_like(raw)
    out[:, :4] = C
    for k, (a, b) in enumerate(EDGES):
        mid = 0.5 * (X[C[:, a]] + X[C[:, b]])
        d = np.linalg.norm(PM - mid[:, None, :], axis=2)
        out[:, 4 + k] = M[np.arange(len(M)), np.argmin(d, axis=1)]
    return out


def build_analysis_shape(parts):
    """One solid per part, or a general-fuse compound with shared faces for multi-part models.
    Returns (shape, owner) where owner[i] is the part index of shape.Solids[i]."""
    solids = [(pi, s) for pi, p in enumerate(parts) if not p.get("ignore") for s in p["shape"].Solids]
    if len(solids) == 1:
        return Part.Compound([solids[0][1]]), [solids[0][0]]
    base = solids[0][1]
    res, _ = base.generalFuse([s for _, s in solids[1:]], 0.0)
    owner = []
    out = []
    for s in res.Solids:
        c = s.CenterOfMass
        pi = next((pi for pi, ps in solids if ps.isInside(c, 1e-6, True)), solids[0][0])
        owner.append(pi)
        out.append(s)
    return Part.Compound(out), owner


def mesh_parts(doc, parts, size_mm, min_size_mm=None):
    """gmsh second-order tets of all non-ignored parts. Returns (Mesh, info)."""
    from femmesh.gmshtools import GmshTools
    fcenv.configure_fem_prefs()
    shape, owner = build_analysis_shape(parts)
    feat = doc.addObject("Part::Feature", "AnalysisShape")
    feat.Shape = shape
    msh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    msh.Shape = feat
    msh.CharacteristicLengthMax = size_mm
    msh.CharacteristicLengthMin = min_size_mm or 0.0
    msh.ElementOrder = "2nd"
    msh.SecondOrderLinear = False
    doc.recompute()
    err = GmshTools(msh).create_mesh()
    fm = msh.FemMesh
    if fm.VolumeCount == 0:
        raise RuntimeError("gmsh produced no volume elements (%s). Is the model a closed solid?" % (err or "no message"))
    fnodes = fm.Nodes  # NB: each access of FemMesh.Nodes rebuilds the whole dict - read it once
    ids = sorted(fnodes.keys())
    index = {nid: i for i, nid in enumerate(ids)}
    nodes = np.array([[fnodes[n].x, fnodes[n].y, fnodes[n].z] for n in ids])
    raw = np.array([[index[n] for n in fm.getElementNodes(e)] for e in fm.Volumes], dtype=np.int64)
    if raw.shape[1] != 10:
        raise RuntimeError("expected 10-node tets, got %d-node elements" % raw.shape[1])
    tets = _reorder(nodes, raw)
    # which part does each tet belong to
    if len(set(owner)) == 1:
        tet_part = np.full(len(tets), owner[0], dtype=np.int64)
    else:
        cen = nodes[tets[:, :4]].mean(axis=1)
        tet_part = np.full(len(tets), -1, dtype=np.int64)
        for si, s in enumerate(shape.Solids):
            bb = s.BoundBox
            for k in np.where((cen[:, 0] >= bb.XMin) & (cen[:, 0] <= bb.XMax) & (cen[:, 1] >= bb.YMin) &
                              (cen[:, 1] <= bb.YMax) & (cen[:, 2] >= bb.ZMin) & (cen[:, 2] <= bb.ZMax) & (tet_part < 0))[0]:
                if s.isInside(App.Vector(*cen[k]), 1e-6, True):
                    tet_part[k] = owner[si]
        tet_part[tet_part < 0] = owner[0]
    m = Mesh(nodes, tets, tet_part)
    return m, dict(m.stats(), size_mm=size_mm, solids=len(shape.Solids))
