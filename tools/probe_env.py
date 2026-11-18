"""Probe what FreeCAD's bundled Python offers headless. Writes tools/probe_env.json."""
import os, sys, json, importlib
out = {"python": sys.version, "argv": sys.argv, "env_FCH": os.environ.get("FCH_JOB")}
for m in ("numpy", "matplotlib", "PIL", "scipy", "PySide", "PySide2", "PySide6", "pivy", "yaml", "gmsh", "meshio", "lib3mf", "Mesh", "MeshPart", "TechDraw", "Import", "ObjectsFem", "Fem", "Part"):
    try:
        mod = importlib.import_module(m)
        out[m] = getattr(mod, "__version__", "ok")
    except Exception as e:
        out[m] = "ERR " + str(e)[:120]
import FreeCAD
out["fc_version"] = FreeCAD.Version()[:4]
try:
    import FreeCADGui
    out["FreeCADGui"] = "imported"
except Exception as e:
    out["FreeCADGui"] = "ERR " + str(e)[:120]
out["bins"] = {b: os.path.exists("/snap/freecad/current/usr/bin/" + b) for b in ("ccx", "gmsh", "prusa-slicer", "CuraEngine")}
json.dump(out, open(os.path.dirname(os.path.abspath(__file__)) + "/probe_env.json", "w"), indent=1)
