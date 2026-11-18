"""Traffic-light verdicts and their plain-language explanations. Pure Python."""

GREEN, AMBER, RED = "green", "amber", "red"
ICON = {GREEN: "🟢", AMBER: "🟡", RED: "🔴"}


def strength(sf, target=2.0, minimum=1.5):
    """Safety factor = how many times the load could grow before the material gives way."""
    if sf >= target:
        return GREEN, "Strong enough: it could take about %.1fx this load before the material gives way." % sf
    if sf >= minimum:
        return AMBER, ("Probably OK but thin margin (%.1fx). Fine for a prototype; for anything that must not fail, "
                       "thicken the most-stressed area or use a stronger material." % sf)
    if sf >= 1.0:
        return RED, ("Too little margin (%.1fx): real-world variation (print quality, shocks, fatigue) can break it. "
                     "Strengthen the hot-spot shown in red." % sf)
    return RED, "Will fail: the stress is %.1fx higher than the material can take." % (1.0 / sf)


def deflection(umax_mm, size_mm):
    """Flags visibly large deflection relative to the part size (stiffness judgement, not strength)."""
    ratio = umax_mm / size_mm if size_mm else 0.0
    if ratio < 0.002:
        return GREEN, "Stiff: it moves %.3f mm under load (barely measurable)." % umax_mm
    if ratio < 0.01:
        return AMBER, "Noticeable flex: %.2f mm. Check this is acceptable for alignment or optics." % umax_mm
    return RED, "Floppy: %.2f mm of movement is ~%.0f%% of its size. Add ribs, thickness or support." % (umax_mm, 100 * ratio)


def frequency(f1_hz, avoid=None):
    """First natural frequency vs. a band of excitation (motors, propellers, vehicles) to stay out of."""
    if not avoid:
        return AMBER if f1_hz < 50 else GREEN, (
            "Lowest natural vibration at %.0f Hz. No excitation band given - add modal.avoid_hz "
            "(e.g. motor rpm/60) to get a real verdict." % f1_hz)
    lo, hi = avoid
    if f1_hz > 1.4 * hi:
        return GREEN, "Lowest vibration mode %.0f Hz is safely above the %g-%g Hz excitation band." % (f1_hz, lo, hi)
    if f1_hz > hi:
        return AMBER, "Lowest mode %.0f Hz is just above the %g-%g Hz band (less than 40%% margin)." % (f1_hz, lo, hi)
    return RED, ("Lowest mode %.0f Hz sits at or below the %g-%g Hz excitation band: it can resonate (shake hard). "
                 "Stiffen it or reduce the mass it carries." % (f1_hz, lo, hi))


def worst(levels):
    order = {GREEN: 0, AMBER: 1, RED: 2}
    return max(levels, key=lambda x: order[x]) if levels else GREEN
