"""Tiny z-buffer triangle rasteriser (numpy only).

matplotlib's 3D axes sort whole polygons back-to-front, which shows hidden faces through solid
parts. For engineering pictures that is misleading, so we rasterise ourselves: orthographic view,
per-pixel depth test, Lambert shading, per-vertex colour interpolation (smooth contour plots),
depth-tested feature lines, 2x supersampling."""
import math
import numpy as np


class View:
    def __init__(self, elev=24.0, azim=-58.0):
        e, a = math.radians(elev), math.radians(azim)
        # camera direction (from the scene toward the viewer), matplotlib-style elev/azim
        self.toward = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
        up = np.array([0.0, 0.0, 1.0])
        self.right = np.cross(up, self.toward)
        self.right /= np.linalg.norm(self.right)
        self.up = np.cross(self.toward, self.right)

    def project(self, X):
        """model xyz -> (u right, v up, depth toward viewer)"""
        return np.column_stack([X @ self.right, X @ self.up, X @ self.toward])


class Canvas:
    def __init__(self, view, points, width=900, height=720, margin=0.08, ss=2):
        self.view, self.ss = view, ss
        self.W, self.H = width * ss, height * ss
        P = view.project(points)
        lo, hi = P[:, :2].min(0), P[:, :2].max(0)
        span = np.maximum(hi - lo, 1e-9)
        self.s = min(self.W * (1 - 2 * margin) / span[0], self.H * (1 - 2 * margin) / span[1])
        self.c = 0.5 * (lo + hi)
        self.rgb = np.ones((self.H, self.W, 3))
        self.z = np.full((self.H, self.W), -np.inf)
        self.light = 0.55 * view.toward + 0.45 * (view.up * 0.8 - view.right * 0.6)
        self.light /= np.linalg.norm(self.light)

    def to_px(self, X):
        P = self.view.project(np.atleast_2d(X))
        x = (P[:, 0] - self.c[0]) * self.s + self.W / 2
        y = self.H / 2 - (P[:, 1] - self.c[1]) * self.s
        return np.column_stack([x, y, P[:, 2]])

    def triangles(self, X, T, colours, vertex_colours=False):
        """X (n,3) vertices, T (m,3) indices, colours (m,3) per triangle or (n,3) per vertex."""
        Q = self.to_px(X)
        tri = X[T]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        shade = 0.38 + 0.62 * np.abs(n @ self.light)
        for k in range(len(T)):
            a, b, c = Q[T[k]]
            x0, x1 = int(max(0, math.floor(min(a[0], b[0], c[0])))), int(min(self.W - 1, math.ceil(max(a[0], b[0], c[0]))))
            y0, y1 = int(max(0, math.floor(min(a[1], b[1], c[1])))), int(min(self.H - 1, math.ceil(max(a[1], b[1], c[1]))))
            if x1 < x0 or y1 < y0:
                continue
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-12:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / den
            w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            d = w0 * a[2] + w1 * b[2] + w2 * c[2]
            zb = self.z[y0:y1 + 1, x0:x1 + 1]
            m = inside & (d > zb)
            if not m.any():
                continue
            zb[m] = d[m]
            if vertex_colours:
                ca, cb, cc = colours[T[k]]
                col = (w0[m, None] * ca + w1[m, None] * cb + w2[m, None] * cc) * shade[k]
            else:
                col = colours[k] * shade[k]
            self.rgb[y0:y1 + 1, x0:x1 + 1][m] = np.clip(col, 0, 1)

    def depth_of(self, X, T):
        """Depth buffer of another surface in the same view (e.g. the undeformed shape) without drawing it."""
        rgb, z = self.rgb, self.z
        self.rgb, self.z = np.ones_like(rgb), np.full_like(z, -np.inf)
        self.triangles(X, T, np.zeros((len(T), 3)))
        zb = self.z
        self.rgb, self.z = rgb, z
        return zb

    def lines(self, polylines, colour=(0.1, 0.1, 0.1), width=1.0, tol_frac=0.004, zbuf=None):
        """Depth-tested polylines (feature edges) against this canvas or a given depth buffer.
        Points slightly behind the surface still count as visible."""
        zref = self.z if zbuf is None else zbuf
        tol = tol_frac * max(self.W, self.H) / self.s
        r = max(0, int(round(width * self.ss / 2)))
        col = np.asarray(colour, float)
        for P in polylines:
            Q = self.to_px(P)
            for i in range(len(Q) - 1):
                a, b = Q[i], Q[i + 1]
                n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
                t = np.linspace(0, 1, n + 1)
                pts = a[None, :] + (b - a)[None, :] * t[:, None]
                xi, yi = pts[:, 0].astype(int), pts[:, 1].astype(int)
                ok = (xi >= r) & (xi < self.W - r) & (yi >= r) & (yi < self.H - r)
                xi, yi, dz = xi[ok], yi[ok], pts[ok, 2]
                vis = dz >= zref[yi, xi] - tol
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        self.rgb[yi[vis] + dy, xi[vis] + dx] = col

    def image(self):
        s = self.ss
        H, W = self.H // s, self.W // s
        return self.rgb[:H * s, :W * s].reshape(H, s, W, s, 3).mean(axis=(1, 3))

    def px(self, X):
        """Final-image pixel coordinates (after supersampling) for overlays."""
        Q = self.to_px(X)
        return Q[:, :2] / self.ss
