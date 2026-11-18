# Design review: bracket_pla

This report was generated automatically by **fcharness** from `bracket.step`. It is a first engineering look meant to help you decide - not a certification. Every number comes from a computer model with the assumptions listed at the end.

## Verdict

> 🔴 **Needs changes** — worst of the checks below (5 checked).

## 1. What was analysed

![The model as the harness sees it. Blue faces are held fixed; orange faces carry the loads (arrows).](img/setup.png)

*The model as the harness sees it. Blue faces are held fixed; orange faces carry the loads (arrows).*

| part | subassembly | material | mass (g) | size x×y×z (mm) |
|---|---|---|---|---|
| Bracket | - | PLA (FDM printed, ~100% infill) | 45.0 | 80×40×70 |
| sensor | (point mass) | - | 200.0 | - |

**Total mass 245.0 g**, centre of gravity at (40.0, 45.9, 50.7) mm.

- **Held:** bolt holes - `{"cylinders": {"diameter": 6.6}}`

- **Load case 'hanging 15 kg':** pull: 150 N towards (0.00, 0.00, -1.00)

- **Load case 'side knock + gravity':** knock: 40 N towards (1.00, 0.00, 0.00); gravity (0, 0, -1) g

- **Carried mass:** sensor, 0.20 kg at (40.0, 50.0, 58.0) mm

## 2.1 Strength and stiffness - load case 'hanging 15 kg'

![Where the material works hardest (red). The shape is exaggerated so you can see how it bends.](img/stress_lc1.png)

*Where the material works hardest (red). The shape is exaggerated so you can see how it bends.*

> 🟢 **Bracket: safety factor 3.1** — Strong enough: it could take about 3.1x this load before the material gives way.

| part | highest stress (MPa) | peak incl. support edges | material can take (MPa) | safety factor | hot-spot at (mm) |
|---|---|---|---|---|---|
| Bracket | 7.9 | 17.7 | 25 | 3.15 | (60, 34, 7) |

> 🟡 **Stiffness** — Noticeable flex: 0.32 mm. Check this is acceptable for alignment or optics. Largest movement at (40, 40, 70) mm.

![How far each point moves under this load case.](img/disp_lc1.png)

*How far each point moves under this load case.*

Check: the supports push back with (0.0, 0.0, 150.0) N, balancing the applied (0.0, 0.0, -150.0) N (error 0.00%). Per support: bolt holes (0.0, 0.0, 150.0) N.

## 2.2 Strength and stiffness - load case 'side knock + gravity'

![Where the material works hardest (red). The shape is exaggerated so you can see how it bends.](img/stress_lc2.png)

*Where the material works hardest (red). The shape is exaggerated so you can see how it bends.*

> 🟢 **Bracket: safety factor 3.5** — Strong enough: it could take about 3.5x this load before the material gives way.

| part | highest stress (MPa) | peak incl. support edges | material can take (MPa) | safety factor | hot-spot at (mm) |
|---|---|---|---|---|---|
| Bracket | 7.1 | 7.1 | 25 | 3.51 | (60, 34, 7) |

> 🟢 **Stiffness** — Stiff: it moves 0.144 mm under load (barely measurable). Largest movement at (60, 34, 70) mm.

![How far each point moves under this load case.](img/disp_lc2.png)

*How far each point moves under this load case.*

Check: the supports push back with (-40.0, 0.0, 2.4) N, balancing the applied (40.0, 0.0, -2.4) N (error 0.00%). Per support: bolt holes (-40.0, 0.0, 2.4) N.

## 3. Vibration

![The first natural vibration shapes. If something shakes the part near one of these frequencies, it can resonate.](img/modes.png)

*The first natural vibration shapes. If something shakes the part near one of these frequencies, it can resonate.*

> 🔴 **Lowest natural frequency 94 Hz** — Lowest mode 94 Hz sits at or below the 50-120 Hz excitation band: it can resonate (shake hard). Stiffen it or reduce the mass it carries.

| mode | frequency (Hz) | main motion | which part flexes (strain energy) |
|---|---|---|---|
| 1 | 93.8 | front-to-back (y) | - |
| 2 | 168.9 | side-to-side (x) | - |
| 3 | 407.5 | up-and-down (z) | - |
| 4 | 1106.9 | side-to-side (x) | - |
| 5 | 1449.1 | up-and-down (z) | - |
| 6 | 2942.3 | up-and-down (z) | - |

**What to change:** to raise a frequency, make the part stiffer in the direction it moves in that mode (ribs, thicker walls, shorter overhangs) or make the carried mass lighter / closer to the supports.

## 4. Drawing

![Auto-generated drawing sheet (third-angle, scale 1:1). Full-resolution: drawing.pdf / drawing.svg.](drawing.png)

*Auto-generated drawing sheet (third-angle, scale 1:1). Full-resolution: drawing.pdf / drawing.svg.*

[drawing.pdf](drawing.pdf) · [drawing.svg](drawing.svg) · the saved `model_with_analysis.FCStd` also contains an editable TechDraw page.

## 5. Assumptions and warnings

- Linear-elastic model: valid while nothing yields, buckles or slips. Supports are perfectly rigid (real ones flex a bit, which lowers frequencies slightly).
- Touching parts are treated as glued together; bolt preload, friction and gaps are not modelled.
- Printed plastics use the weaker across-layer (z) strength everywhere - conservative.
- Stress right at the edge of a fixed face or at a sharp inside corner is not reliable; the safety factor uses the highest stress at least one element away from supports (the peak is shown for reference).
- Mesh: 20090 nodes, 10856 quadratic tetrahedra, target size 3 mm. Halve size_mm and re-run to confirm results change by only a few %.

## 6. Reproduce

Run `FCH_JOB=examples/bracket/job_pla.yaml fc run.py` from the repository. Every step's inputs/outputs are in `checkpoints/`; solver decks and logs in `work/`.

```
# Same bracket and loads as job.yaml, but 3D-printed in PLA instead of machined 6061.
# Shows the trade-off a non-ME usually misses: the print is strong enough, yet ~20x less stiff,
# so its first vibration mode drops into the motor's excitation band.
name: bracket_pla
model: bracket.step
default_material: pla_printed
parts: {Bracket: {material: pla_printed, print_direction: z}}

supports:
  - name: bolt holes
    type: fixed
    where: {cylinders: {diameter: 6.6}}

point_masses:
  - name: sensor
    mass_kg: 0.2
    at: [40, 50, 58]
    attach: {cylinders: {diameter: 8}}

load_cases:
  - name: hanging 15 kg
    forces:
      - name: pull
        where: {cylinders: {diameter: 8}}
        force_N: [0, 0, -150]
  - name: side knock + gravity
    gravity_g: [0, 0, -1]
    forces:
      - name: knock
        where: {cylinders: {diameter: 8}}
        force_N: [40, 0, 0]

analyses: [static, modal]
modal: {modes: 6, avoid_hz: [50, 120]}
mesh: {size_mm: 3.0}
drawing: {projection: third_angle, title: "L-bracket, PLA print"}
```
