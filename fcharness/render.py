"""Headless pictures (no GUI / OpenGL): shaded parts, analysis set-up (supports, loads, point masses),
stress / displacement contours on the deformed shape, and mode shapes.

Geometry is rasterised with a z-buffer (fcharness.raster) so hidden surfaces stay hidden;
matplotlib only adds the colour bar, labels and arrows on top."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib import colormaps

from .raster import View, Canvas

PART_COLOURS = ["#9db4d3", "#d3b49d", "#a8d3a5", "#d3a5cb", "#d3cf9d", "#9dd3cf", "#bdbdbd"]
VIEW = dict(elev=24, azim=-58)


def tessellate(shape, tol):
    pts, tris = shape.tessellate(tol)
    return np.array([[p.x, p.y, p.z] for p in pts]).reshape(-1, 3), np.array(tris, dtype=np.int64).reshape(-1, 3)


def _edges(shape, n=24):
    out = []
    for e in shape.Edges:
        if e.Curve.__class__.__name__ == "Line":
            out.append(np.array([[v.X, v.Y, v.Z] for v in e.Vertexes]))
        else:
            out.append(np.array([[p.x, p.y, p.z] for p in e.discretize(n)]))
    return out


def _triad(ax, view, img_h):
    o = np.array([45.0, img_h - 45.0])
    for v, lab, col in (((1, 0, 0), "x", "r"), ((0, 1, 0), "y", "g"), ((0, 0, 1), "z", "b")):
        d = np.array([np.dot(v, view.right), -np.dot(v, view.up)]) * 32
        ax.annotate("", xy=o + d, xytext=o, arrowprops=dict(arrowstyle="-|>", color=col, lw=1.3))
        ax.text(*(o + d * 1.3), lab, color=col, fontsize=8, ha="center", va="center")


def _figure(img, title):
    h, w = img.shape[:2]
    fig = plt.figure(figsize=(w / 100.0, h / 100.0 + 0.4), dpi=100)
    ax = fig.add_axes([0, 0, 1, h / (h + 40.0)])
    ax.imshow(img, interpolation="bilinear")
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    if title:
        fig.text(0.5, 1 - 0.5 * 40.0 / (h + 40.0), title, ha="center", va="center", fontsize=11)
    return fig, ax


def parts_figure(parts, path, title="Model", highlights=(), arrows=(), points=(), view=None, size=(900, 680)):
    """highlights: [(part_i, face_i, colour)]; arrows: [(xyz, vector, colour, label)]; points: [(xyz, label)]"""
    view = view or View(**VIEW)
    hl = {(pi, fi): col for pi, fi, col in highlights}
    Xs, Ts, Cs, E = [], [], [], []
    off = 0
    for pi, p in enumerate(parts):
        sh = p["shape"]
        tol = max(0.02, 0.002 * sh.BoundBox.DiagonalLength)
        for fi, f in enumerate(sh.Faces):
            X, T = tessellate(f, tol)
            if not len(T):
                continue
            Xs.append(X)
            Ts.append(T + off)
            off += len(X)
            Cs.append(np.tile(mcolors.to_rgb(hl.get((pi, fi), PART_COLOURS[pi % len(PART_COLOURS)])), (len(T), 1)))
        E += _edges(sh)
    X, T, C = np.concatenate(Xs), np.concatenate(Ts), np.concatenate(Cs)
    span = (X.max(0) - X.min(0)).max()
    extra = [X]
    for a in arrows:
        v = np.asarray(a[1], float)
        extra.append(np.atleast_2d(np.asarray(a[0], float) - 0.3 * span * v / (np.linalg.norm(v) or 1)))
    extra += [np.atleast_2d(np.asarray(p[0], float)) for p in points]
    cv = Canvas(view, np.concatenate(extra), *size)
    cv.triangles(X, T, C)
    cv.lines(E, colour=(0.15, 0.15, 0.2), width=1.0)
    img = cv.image()
    fig, ax = _figure(img, title)
    for xyz, v, col, lab in arrows:
        v = np.asarray(v, float)
        v = v / (np.linalg.norm(v) or 1)
        tip = cv.px(np.asarray(xyz, float))[0]
        tail = cv.px(np.asarray(xyz, float) - 0.3 * span * v)[0]
        ax.annotate("", xy=tip, xytext=tail, arrowprops=dict(arrowstyle="-|>,head_width=0.5,head_length=0.9", color=col, lw=2.5))
        ax.text(*tail, lab, color=col, fontsize=9, weight="bold", ha="center", va="bottom", bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    for xyz, lab in points:
        q = cv.px(np.asarray(xyz, float))[0]
        ax.plot(*q, "o", ms=9, mfc="k", mec="w")
        ax.text(q[0] + 10, q[1] - 10, lab, fontsize=9, bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    _triad(ax, view, img.shape[0])
    fig.savefig(path)
    plt.close(fig)
    return path


def _sub_tris(mesh):
    """each boundary tri6 -> 4 flat triangles (smoother contours on curved faces)"""
    B = mesh.bnd
    return np.concatenate([B[:, [0, 3, 5]], B[:, [3, 1, 4]], B[:, [5, 4, 2]], B[:, [3, 4, 5]]])


def _sharp_edges(mesh, max_n=6000):
    """Boundary edges where the surface folds by > 30 deg (the part's outline), as node pairs."""
    B = mesh.bnd[:, :3]
    P = mesh.nodes
    n = np.cross(P[B[:, 1]] - P[B[:, 0]], P[B[:, 2]] - P[B[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    e = np.concatenate([B[:, [0, 1]], B[:, [1, 2]], B[:, [2, 0]]])
    f = np.tile(np.arange(len(B)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, f = key[order], f[order]
    i = np.where(np.all(key[1:] == key[:-1], axis=1))[0]
    sharp = np.einsum("ij,ij->i", n[f[i]], n[f[i + 1]]) < np.cos(np.radians(30))
    return key[i[sharp]][:max_n]


def field_figure(mesh, values, path, title, label, U=None, scale=0.0, cmap="turbo", vmax=None, note=None, view=None):
    """Colour plot of a nodal scalar on the (optionally deformed) outer surface, with a faint undeformed outline."""
    view = view or View(**VIEW)
    X = mesh.nodes + (scale * U if U is not None else 0.0)
    T = _sub_tris(mesh)
    vmax = float(values.max()) if vmax is None else vmax
    norm = mcolors.Normalize(vmin=float(min(0.0, values.min())), vmax=vmax)
    rgb = colormaps[cmap](norm(values))[:, :3]
    cv = Canvas(view, np.concatenate([X, mesh.nodes]), 900, 680)
    cv.triangles(X, T, rgb, vertex_colours=True)
    E = _sharp_edges(mesh)
    if U is not None and scale:  # visible edges of the undeformed shape, drawn faintly on top for reference
        z0 = cv.depth_of(mesh.nodes, mesh.bnd[:, :3])
        cv.lines([mesh.nodes[e] for e in E], colour=(0.55, 0.55, 0.55), width=0.6, zbuf=z0)
    cv.lines([X[e] for e in E], colour=(0.1, 0.1, 0.1), width=0.8)
    img = cv.image()
    fig, ax = _figure(img, title)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cax = fig.add_axes([0.88, 0.2, 0.025, 0.55])
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label(label)
    if note:
        fig.text(0.01, 0.01, note, fontsize=7.5, color="0.3")
    _triad(ax, view, img.shape[0])
    fig.savefig(path)
    plt.close(fig)
    return path


def modes_figure(mesh, shapes, freqs, path, max_modes=6, view=None):
    """Grid of mode shapes coloured by relative displacement."""
    view = view or View(**VIEW)
    n = min(max_modes, len(shapes))
    cols = 3 if n > 2 else max(n, 1)
    rows = int(np.ceil(n / cols))
    size = (mesh.nodes.max(0) - mesh.nodes.min(0)).max()
    T = _sub_tris(mesh)
    E = _sharp_edges(mesh)
    fig = plt.figure(figsize=(4.4 * cols, 3.6 * rows + 0.5), dpi=100)
    for k in range(n):
        U = shapes[k]
        mag = np.linalg.norm(U, axis=1)
        sc = 0.12 * size / (mag.max() or 1)
        X = mesh.nodes + sc * U
        cv = Canvas(view, np.concatenate([X, mesh.nodes]), 440, 340)
        cv.triangles(X, T, colormaps["viridis"](mag / (mag.max() or 1))[:, :3], vertex_colours=True)
        cv.lines([mesh.nodes[e] for e in E], colour=(0.6, 0.6, 0.6), width=0.5, zbuf=cv.depth_of(mesh.nodes, mesh.bnd[:, :3]))
        ax = fig.add_subplot(rows, cols, k + 1)
        ax.imshow(cv.image(), interpolation="bilinear")
        ax.axis("off")
        ax.set_title("mode %d: %.1f Hz" % (k + 1, freqs[k]), fontsize=10)
    fig.suptitle("How it likes to vibrate (exaggerated; grey outline = at rest, yellow = moves most)", fontsize=11)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
