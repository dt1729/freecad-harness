"""Entry point, run inside FreeCAD's Python:

    FCH_JOB=examples/bracket/job.yaml /usr/local/bin/fc /path/to/freecad-harness/run.py

(FreeCADCmd treats extra command-line words as files to open, so the job is passed in the FCH_JOB
environment variable.) Console noise from FreeCAD/gmsh/CalculiX goes to <out>/run.log; a one-line
result is printed at the end."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fcharness.pipeline import Pipeline  # noqa: E402
from fcharness.fcenv import QuietConsole  # noqa: E402



def main():
    job = os.environ.get("FCH_JOB")
    if not job:
        print("set FCH_JOB=<job.yaml>")
        return
    job = job if os.path.isabs(job) else os.path.join(HERE, job)
    pl = Pipeline(job, os.environ.get("FCH_OUT"))
    with QuietConsole(os.path.join(pl.out, "run.log")):
        failed = pl.run()
    print("FCH_RESULT %s %s -> %s" % ("FAILED at " + failed[0] if failed else "OK", pl.job["name"], pl.report_paths[1]))
    if failed:
        print("FCH_ERROR %s" % str(failed[1])[:400])


# FreeCADCmd re-executes a script whose top level raises - never let an exception escape.
try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    print("FCH_CRASH %s: %s" % (type(e).__name__, e))
    print(traceback.format_exc()[-1500:])
