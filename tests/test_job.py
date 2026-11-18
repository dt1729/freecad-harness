"""Pure-Python tests (no FreeCAD needed):  python3 -m unittest discover -s tests -p 'test_*.py'"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fcharness import job, materials, verdict  # noqa: E402

GOOD = dict(name="b", model="b.step", default_material="al_6061_t6",
            supports=[dict(name="s", type="fixed", where={"cylinders": {"diameter": 6.6}})],
            load_cases=[dict(name="lc", forces=[dict(where={"plane": {"normal": [0, 0, 1]}}, force_N=[0, 0, -10])])],
            analyses=["static", "modal"])


def errors(j):
    return [p for p in job.validate(j) if p.level == "error"]


class JobValidation(unittest.TestCase):
    def test_good_job_passes(self):
        self.assertEqual(errors(GOOD), [])

    def test_typo_in_key_is_an_error(self):
        j = dict(GOOD, suports=[])
        self.assertTrue(any("suports" in p.message for p in errors(j)))

    def test_missing_supports_explains_why(self):
        j = dict(GOOD, supports=[])
        e = errors(j)
        self.assertTrue(any(p.where == "supports" and "fly away" in p.message for p in e))

    def test_unknown_material_lists_choices(self):
        e = errors(dict(GOOD, default_material="unobtainium"))
        self.assertTrue(any("al_6061_t6" in p.fix for p in e))

    def test_bad_selector(self):
        j = dict(GOOD, supports=[dict(where={"holes": 6})])
        self.assertTrue(errors(j))

    def test_force_must_be_vector(self):
        j = dict(GOOD, load_cases=[dict(name="x", forces=[dict(where={"near_point": [0, 0, 0]}, force_N=10)])])
        self.assertTrue(any("force_N" in p.message for p in errors(j)))

    def test_linear_tets_rejected(self):
        self.assertTrue(errors(dict(GOOD, mesh={"order": 1})))

    def test_static_needs_load_case(self):
        self.assertTrue(errors(dict(GOOD, load_cases=[])))

    def test_normalise_fills_defaults_without_mutating(self):
        n = job.normalise(GOOD)
        self.assertEqual(n["mesh"]["size_mm"], 3.0)
        self.assertNotIn("mesh", GOOD)


class Materials(unittest.TestCase):
    def test_printed_uses_interlayer_strength(self):
        m = materials.get("pet_cf_printed")
        self.assertLess(materials.allowable(m, "z"), materials.allowable(m, "xy"))

    def test_metal_allowable_is_yield(self):
        self.assertEqual(materials.allowable(materials.get("al_6061_t6")), 276.0)

    def test_density_units(self):
        self.assertAlmostEqual(materials.ccx_density(materials.get("steel_mild")), 7.87e-9)

    def test_unknown(self):
        with self.assertRaises(KeyError):
            materials.get("nope")


class Verdicts(unittest.TestCase):
    def test_strength_levels(self):
        self.assertEqual(verdict.strength(3.0)[0], verdict.GREEN)
        self.assertEqual(verdict.strength(1.7)[0], verdict.AMBER)
        self.assertEqual(verdict.strength(1.2)[0], verdict.RED)
        self.assertIn("fail", verdict.strength(0.5)[1])

    def test_frequency_band(self):
        self.assertEqual(verdict.frequency(80, [50, 120])[0], verdict.RED)
        self.assertEqual(verdict.frequency(150, [50, 120])[0], verdict.AMBER)
        self.assertEqual(verdict.frequency(400, [50, 120])[0], verdict.GREEN)


if __name__ == "__main__":
    unittest.main()
