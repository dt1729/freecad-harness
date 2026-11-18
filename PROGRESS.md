# Progress log

- 2026-11-18 16:40 probed FreeCAD 1.1.4 snap: numpy/scipy/matplotlib/PySide6/yaml bundled; ccx + gmsh present; env vars pass through `fc`
- 2026-11-18 16:50 skeleton: job validator, materials, model loader, geometric selectors, gmsh tet10 mesher, own ccx deck writer
- 2026-11-18 17:00 fixed O(N^2) FemMesh.Nodes access (run went from >10 min to ~40 s)
- 2026-11-18 17:02 cylinder selectors default to holes: an R4 outside fillet had matched a d8 hole
- 2026-11-18 17:05 replaced matplotlib 3D (painter's sorting showed hidden faces) with a numpy z-buffer renderer
- 2026-11-18 17:08 ccx *COUPLING/*DISTRIBUTING silently dropped MASS elements in *FREQUENCY -> *RIGID BODY + solver-mass self-check
- 2026-11-18 17:15 benchmarks pass: cantilever tip -0.9 %, gravity -1.1 %, modal -0.3 %, tip-mass modal +0.0 %
- 2026-11-18 17:20 vertical slice done: bracket (6061 + PLA) reports with setup/stress/displacement/mode pictures and A3 drawing
