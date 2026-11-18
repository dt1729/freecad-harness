# Roadmap

Status legend: ✅ done · 🚧 next · 📋 planned

## Analysis
- ✅ Static, multiple load cases, gravity, point masses (rigid spider), reactions per support
- ✅ Modal with effective-mass direction and solver-mass self-check
- 🚧 Linear buckling (`*BUCKLE`; apply loads directly at members — lever arms bias factors)
- 🚧 Per-part modal strain-energy share for assemblies (ccx `ELSE` totals already parsed)
- 📋 Pinned / sliding / symmetry supports; bearings as joints (rotation-free couplings)
- 📋 Point-mass rotary inertia; free-free modal for "first elastic mode" of floating frames
- 📋 Mesh convergence helper (auto re-run at half size and report the change)

## Design review checks
- 📋 Interference and minimum clearance between parts
- 📋 Holes / fasteners vs stack-ups, thread engagement, edge distance
- 📋 Printability: bed size, overhang map, minimum wall, orientation suggestion
- 📋 Drawing-vs-model consistency: TechDraw dimensions vs the current solids (catches stale drawings)
- 📋 Mass / CG budget checks against limits

## Drawings & CAM
- ✅ A3 sheet: 3 orthographic views + isometric, overall dims, hole callouts, parts list, title block
- 📋 Per-part sheets for assemblies, more dimensions (hole positions, thickness), GD&T notes
- 📋 Per-part STL/3MF with print orientation; slicing via a CLI slicer (PrusaSlicer/CuraEngine) if available

## Interfaces
- 📋 MCP server exposing the typed operations (load, describe, set-up, validate, solve, review, report)
