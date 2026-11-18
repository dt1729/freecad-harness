"""FreeCAD runtime helpers: quiet console, solver binaries, gmsh/ccx preferences."""
import os
import glob

_SNAP_BIN = "/snap/freecad/current/usr/bin/"


def find_binary(name):
    """Bundled binary of the FreeCAD snap, else whatever is on PATH, else None."""
    if os.path.exists(_SNAP_BIN + name):
        return _SNAP_BIN + name
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


CCX = find_binary("ccx")
GMSH = find_binary("gmsh")


class QuietConsole:
    """Redirect process-level stdout/stderr (fds 1 and 2) to a log file.

    FreeCAD, gmsh and CalculiX print progress bars to the raw file descriptors, which floods agent
    transcripts and CI logs; Python-level redirection does not catch them."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        self.s1, self.s2 = os.dup(1), os.dup(2)
        os.dup2(self.fd, 1)
        os.dup2(self.fd, 2)
        return self

    def __exit__(self, *exc):
        os.dup2(self.s1, 1)
        os.dup2(self.s2, 2)
        os.close(self.fd)
        return False


def configure_fem_prefs():
    """Point FreeCAD's FEM workbench at the bundled gmsh/ccx (headless runs have no prefs dialog)."""
    import FreeCAD as App
    if GMSH:
        pg = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Gmsh")
        pg.SetBool("UseStandardGmshLocation", False)
        pg.SetString("gmshBinaryPath", GMSH)
    if CCX:
        pc = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx")
        pc.SetBool("UseStandardCcxLocation", False)
        pc.SetString("ccxBinaryPath", CCX)


def techdraw_template(name="A3_Landscape_blank.svg"):
    """FreeCAD's own template if installed, else the minimal A3 template shipped with fcharness
    (the snap build has no TechDraw template files)."""
    hits = glob.glob("/snap/freecad/current/usr/share/freecad/Mod/TechDraw/Templates/**/" + name, recursive=True)
    return hits[0] if hits else os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "A3_blank.svg")
