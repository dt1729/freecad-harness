"""Automatic 2D drawings, fully headless.

Hidden-line removal is done by FreeCAD's TechDraw engine (TechDraw.projectEx); the sheet (views,
dimensions, hole callouts, parts list, title block) is laid out with matplotlib and written as
PDF + SVG. A real TechDraw page is also added to the saved FCStd so it can be edited in the GUI."""
import datetime
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import FreeCAD as App
import TechDraw

from . import fcenv

A3 = (420.0, 297.0)
SCALES = [10, 5, 4, 2, 1, 0.5, 0.4, 0.25, 0.2, 0.1, 0.05, 0.02, 0.01]

# view name -> (right, up, toward viewer) in model coordinates
VIEWS = {
    "front": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "top": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "right": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    "left": ((0, -1, 0), (0, 0, 1), (-1, 0, 0)),
}


def _iso_frame():
    t = np.array([1.0, -1.0, 1.0]) / math.sqrt(3)
    r = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)
    u = np.cross(t, r)
    return tuple(r), tuple(u), tuple(t)


def _to_view(shape, frame):
    r, u, t = (App.Vector(*v) for v in frame)
    m = App.Matrix(r.x, r.y, r.z, 0, u.x, u.y, u.z, 0, t.x, t.y, t.z, 0, 0, 0, 0, 1)
    s = shape.copy()
    s.transformShape(m)
    return s


def project(shape, frame):
    """Returns dict(visible=[polyline], smooth=[...], hidden=[...], bbox=(xmin,ymin,xmax,ymax)) in model mm."""
    s = _to_view(shape, frame)
    res = TechDraw.projectEx(s, App.Vector(0, 0, 1))
    groups = dict(visible=(0, 3), smooth=(1,), hidden=(5, 8))
    out = {k: [] for k in groups}
    pts = []
    for k, idx in groups.items():
        for i in idx:
            comp = res[i]
            if comp is None or comp.isNull():
                continue
            for e in comp.Edges:
                n = 2 if e.Curve.__class__.__name__ == "Line" else max(8, min(200, int(e.Length / 0.5) + 1))
                P = np.array([[p.x, p.y] for p in e.discretize(n)])
                out[k].append(P)
                if k != "hidden":
                    pts.append(P)
    allp = np.concatenate(pts) if pts else np.zeros((1, 2))
    out["bbox"] = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    return out


def holes(shape):
    """Cylindrical faces grouped by (diameter, axis): [dict(d, axis, centres, hole)]"""
    groups = []
    for f in shape.Faces:
        s = f.Surface
        if s.__class__.__name__ != "Cylinder":
            continue
        u0, u1, v0, v1 = f.ParameterRange
        p = f.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        n = f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        ax = s.Axis
        c = s.Center
        radial = (p - c) - ax * (p - c).dot(ax)
        is_hole = n.dot(radial) < 0
        cc = c + ax * (f.CenterOfMass - c).dot(ax)
        d = 2 * s.Radius
        g = next((g for g in groups if abs(g["d"] - d) < 1e-3 and abs(abs(g["axis"].dot(ax)) - 1) < 1e-6 and g["hole"] == is_hole), None)
        if g is None:
            g = dict(d=d, axis=App.Vector(ax), centres=[], hole=is_hole)
            groups.append(g)
        # a hole is often split into two half-cylinder faces: merge by axis line
        if not any(((cc - q) - g["axis"] * (cc - q).dot(g["axis"])).Length < 1e-3 for q in g["centres"]):
            g["centres"].append(cc)
    return groups


def _dim(ax, a, b, off, text, horizontal=True, fs=7):
    """Linear dimension between paper points a and b, offset `off` mm (sign = side)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if horizontal:
        y = (min(a[1], b[1]) if off < 0 else max(a[1], b[1])) + off
        pa, pb = (a[0], y), (b[0], y)
        ax.plot([a[0], a[0]], [a[1], y + math.copysign(1.5, off)], color="k", lw=0.25)
        ax.plot([b[0], b[0]], [b[1], y + math.copysign(1.5, off)], color="k", lw=0.25)
        tp, rot = ((a[0] + b[0]) / 2, y + 0.8), 0
    else:
        x = (min(a[0], b[0]) if off < 0 else max(a[0], b[0])) + off
        pa, pb = (x, a[1]), (x, b[1])
        ax.plot([a[0], x + math.copysign(1.5, off)], [a[1], a[1]], color="k", lw=0.25)
        ax.plot([b[0], x + math.copysign(1.5, off)], [b[1], b[1]], color="k", lw=0.25)
        tp, rot = (x - 0.8, (a[1] + b[1]) / 2), 90
    ax.annotate("", xy=pa, xytext=pb, arrowprops=dict(arrowstyle="<|-|>", lw=0.3, color="k", shrinkA=0, shrinkB=0, mutation_scale=5))
    ax.text(*tp, text, fontsize=fs, ha="center", va="bottom" if horizontal else "center", rotation=rot,
            bbox=dict(fc="white", ec="none", pad=0.3))


def _scale_txt(s):
    return "%g:1" % s if s >= 1 else "1:%g" % (1 / s)


def sheet(parts, path_base, title="Drawing", projection="third_angle", mass_rows=None, number="FCH-001", author="fcharness"):
    """One A3 sheet for the given parts. Writes <path_base>.pdf/.svg/.png. Returns info dict (scale, view sizes)."""
    import Part
    shape = Part.Compound([p["shape"] for p in parts])
    bb = shape.BoundBox
    W, H = A3
    area_w, area_h = 260.0, 230.0
    sx, sy, sz = bb.XLength, bb.YLength, bb.ZLength
    scale = next((s for s in SCALES if (sx + sy + 40) * s <= area_w and (sz + sy + 40) * s <= area_h), SCALES[-1])
    fig = plt.figure(figsize=(W / 25.4, H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(plt.Rectangle((10, 10), W - 20, H - 20, fill=False, lw=0.7))
    third = projection == "third_angle"
    fx = 30.0
    if third:
        fy = 30.0
        pos = {"front": (fx, fy), "top": (fx, fy + sz * scale + 22), "right": (fx + sx * scale + 22, fy)}
        views = {"front": "front", "top": "top", "right": "right"}
    else:  # first angle: plan below the elevation, the view from the left drawn on the right
        pos = {"top": (fx, 30.0), "front": (fx, 30.0 + sy * scale + 22)}
        pos["right"] = (fx + sx * scale + 22, pos["front"][1])
        views = {"front": "front", "top": "top", "right": "left"}
    info = dict(scale=scale, scale_text=_scale_txt(scale), projection=projection, views={})
    for slot, vname in views.items():
        pr = project(shape, VIEWS[vname])
        x0, y0, x1, y1 = pr["bbox"]
        ox, oy = pos[slot][0] - x0 * scale, pos[slot][1] - y0 * scale
        tf = lambda P, ox=ox, oy=oy: np.column_stack([P[:, 0] * scale + ox, P[:, 1] * scale + oy])
        for P in pr["hidden"]:
            Q = tf(P)
            ax.plot(Q[:, 0], Q[:, 1], color="0.4", lw=0.25, ls=(0, (3, 1.5)))
        for P in pr["smooth"]:
            Q = tf(P)
            ax.plot(Q[:, 0], Q[:, 1], color="0.25", lw=0.2)
        for P in pr["visible"]:
            Q = tf(P)
            ax.plot(Q[:, 0], Q[:, 1], color="k", lw=0.5)
        a = (x0 * scale + ox, y0 * scale + oy)
        b = (x1 * scale + ox, y1 * scale + oy)
        info["views"][slot] = dict(view=vname, width=x1 - x0, height=y1 - y0)
        ax.text(a[0], b[1] + 3, vname.upper() + " VIEW", fontsize=6, color="0.3")
        if slot == "front":
            _dim(ax, a, (b[0], a[1]), -8, "%.1f" % (x1 - x0))
            _dim(ax, a, (a[0], b[1]), -8, "%.1f" % (y1 - y0), horizontal=False)
        elif slot == "top":
            _dim(ax, (b[0], a[1]), b, 8, "%.1f" % (y1 - y0), horizontal=False)
        else:
            _dim(ax, a, (b[0], a[1]), -8, "%.1f" % (x1 - x0))
        r, u, t = (np.array(v, float) for v in VIEWS[vname])
        for g in holes(shape):
            axv = np.array([g["axis"].x, g["axis"].y, g["axis"].z])
            if not g["hole"] or abs(abs(axv @ t) - 1) > 1e-6:
                continue
            c3 = np.array([[c.x, c.y, c.z] for c in g["centres"]])
            Q = tf(np.column_stack([c3 @ r, c3 @ u]))
            rr = g["d"] * scale / 2
            for q in Q:
                ax.plot([q[0] - rr - 1.5, q[0] + rr + 1.5], [q[1], q[1]], color="0.4", lw=0.2, ls="-.")
                ax.plot([q[0], q[0]], [q[1] - rr - 1.5, q[1] + rr + 1.5], color="0.4", lw=0.2, ls="-.")
            q = Q[np.argmax(Q[:, 0] + Q[:, 1])]
            txt = ("%dx " % len(Q) if len(Q) > 1 else "") + "Ø%.1f" % g["d"]
            ax.annotate(txt, xy=(q[0] + rr * 0.71, q[1] + rr * 0.71), xytext=(q[0] + rr + 10, q[1] + rr + 8), fontsize=6.5,
                        arrowprops=dict(arrowstyle="-|>", lw=0.3, color="k", mutation_scale=5))
    # isometric picture (top right)
    pr = project(shape, _iso_frame())
    x0, y0, x1, y1 = pr["bbox"]
    bx0, by0, bw0, bh0 = 300.0, 170.0, 100.0, 105.0
    s_iso = min(bw0 / max(x1 - x0, 1e-6), bh0 / max(y1 - y0, 1e-6))
    ox, oy = bx0 - x0 * s_iso, by0 - y0 * s_iso
    for P in pr["visible"] + pr["smooth"]:
        ax.plot(P[:, 0] * s_iso + ox, P[:, 1] * s_iso + oy, color="k", lw=0.35)
    ax.text(bx0, by0 - 5, "ISOMETRIC (not to scale)", fontsize=6, color="0.3")
    # parts list
    rows = mass_rows or [dict(part=p["label"], material=p["material"]["name"], mass_kg=float("nan")) for p in parts]
    tx, ty = 230.0, 62.0
    ax.text(tx, ty + 6 + 5 * len(rows), "PARTS LIST", fontsize=7, weight="bold")
    colx = (0, 12, 70, 82, 160)
    for k, h in enumerate(("ITEM", "PART", "QTY", "MATERIAL", "MASS g")):
        ax.text(tx + colx[k], ty + 1 + 5 * len(rows), h, fontsize=6, weight="bold")
    for i, rw in enumerate(rows):
        yy = ty + 1 + 5 * (len(rows) - 1 - i)
        vals = (str(i + 1), rw["part"][:28], "1", rw["material"][:36], "%.1f" % (1000 * rw["mass_kg"]))
        for k, v in enumerate(vals):
            ax.text(tx + colx[k], yy, v, fontsize=6)
        ax.plot([tx, tx + 180], [yy - 1, yy - 1], color="0.6", lw=0.2)
    # title block
    bx, by, bw, bh = 230.0, 10.0, 180.0, 45.0
    ax.add_patch(plt.Rectangle((bx, by), bw, bh, fill=False, lw=0.6))
    for yy in (by + 15, by + 30):
        ax.plot([bx, bx + bw], [yy, yy], color="k", lw=0.3)
    ax.plot([bx + 110, bx + 110], [by, by + 30], color="k", lw=0.3)
    ax.text(bx + 3, by + 36, title, fontsize=11, weight="bold")
    ax.text(bx + 3, by + 20, "DRAWING No. %s" % number, fontsize=7)
    ax.text(bx + 3, by + 5, "UNITS: mm   SCALE %s   %s PROJECTION" % (_scale_txt(scale), "THIRD-ANGLE" if third else "FIRST-ANGLE"), fontsize=6.5)
    ax.text(bx + 113, by + 20, "DRAWN: %s" % author, fontsize=6.5)
    ax.text(bx + 113, by + 5, "DATE: %s" % datetime.date.today().isoformat(), fontsize=6.5)
    ax.text(bx + 3, by + 31, "Auto-generated from the 3D model - check before manufacture. Unless noted: tol ±0.2, break sharp edges.",
            fontsize=5, color="0.3", va="bottom")
    for ext in ("pdf", "svg"):
        fig.savefig(path_base + "." + ext)
    fig.savefig(path_base + ".png", dpi=110)
    plt.close(fig)
    return info


def add_techdraw_page(doc, parts, title="Drawing"):
    """Add an editable TechDraw page (projection group) to `doc` for GUI users. Returns the page or None."""
    try:
        tpl_path = fcenv.techdraw_template()
        page = doc.addObject("TechDraw::DrawPage", "AutoDrawing")
        if tpl_path:
            tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
            tpl.Template = tpl_path
            page.Template = tpl
        grp = doc.addObject("TechDraw::DrawProjGroup", "Views")
        page.addView(grp)
        grp.Source = [p["object"] for p in parts if p.get("object") is not None]
        grp.ProjectionType = "Third angle"
        for v in ("Front", "Top", "Right"):
            grp.addProjection(v)
        page.Label = title
        doc.recompute()
        return page
    except Exception as e:  # depends on the FreeCAD build
        App.Console.PrintWarning("TechDraw page not created: %s\n" % e)
        return None
