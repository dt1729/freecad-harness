"""fcharness - a FreeCAD harness that acts as a mechanical-engineering extension for non-mechanical engineers.

Most modules run inside FreeCAD's bundled Python (via `fc run.py`); `materials`, `job` and `verdict`
are pure Python so they can be tested with any interpreter.
Units everywhere inside the harness: mm, N, s, tonne, MPa (CalculiX-consistent).
"""
__version__ = "0.1.0"
