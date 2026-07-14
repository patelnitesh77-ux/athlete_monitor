"""Unit tests for lib/metrics.py (stdlib unittest; run: python -m unittest discover tests)."""
import sys, os, unittest
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from lib import metrics as M


def sessions_df(rows):
    return pd.DataFrame(rows, columns=["session_date", "load_au", "arrows"])


def wellness_df(rows):
    cols = ["entry_date", "sleep_quality", "sleep_hours", "fatigue", "soreness",
            "stress", "mood", "hydration", "body_weight_kg", "pain_flag", "pain_location"]
    return pd.DataFrame(rows, columns=cols)


def steady_wellness(start: date, days: int, overrides=None):
    overrides = overrides or {}
    rows = []
    for i in range(days):
        d = start + timedelta(days=i)
        row = dict(entry_date=d, sleep_quality=4, sleep_hours=8.0, fatigue=4,
                   soreness=4, stress=4, mood=4, hydration=4,
                   body_weight_kg=None, pain_flag=False, pain_location=None)
        if d in overrides:
            row.update(overrides[d])
        rows.append([row[c] for c in ["entry_date", "sleep_quality", "sleep_hours",
                    "fatigue", "soreness", "stress", "mood", "hydration",
                    "body_weight_kg", "pain_flag", "pain_location"]])
    return wellness_df(rows)


class TestDailyLoad(unittest.TestCase):
    def test_fills_rest_days_with_zero(self):
        d0 = date(2026, 6, 1)
        s = sessions_df([[d0, 400.0, None], [d0 + timedelta(days=3), 300.0, None]])
        daily = M.daily_load_series(s, d0 + timedelta(days=4))
        self.assertEqual(len(daily), 5)
        self.assertEqual(daily.iloc[1], 0.0)
        self.assertEqual(daily.sum(), 700.0)

    def test_multiple_sessions_same_day_sum(self):
        d0 = date(2026, 6, 1)
        s = sessions_df([[d0, 200.0, None], [d0, 150.0, None]])
        daily = M.daily_load_series(s, d0)
        self.assertEqual(daily.iloc[0], 350.0)  # rehab-double-count rule: sum sources


class TestACWR(unittest.TestCase):
    def _uniform(self, days, load=300.0, end=None):
        end = end or date(2026, 6, 30)
        start = end - timedelta(days=days - 1)
        rows = [[start + timedelta(days=i), load, None] for i in range(days)]
        return M.daily_load_series(sessions_df(rows), end), end

    def test_insufficient_history_returns_none(self):
        daily, end = self._uniform(20)
        self.assertIsNone(M.acwr(daily, end))          # cold start < 28 days

    def test_uniform_load_gives_one(self):
        daily, end = self._uniform(35)
        self.assertAlmostEqual(M.acwr(daily, end), 1.0, places=6)

    def test_spike_raises_ratio(self):
        daily, end = self._uniform(35, load=300.0)
        daily.iloc[-7:] = 600.0                        # doubled acute week
        r = M.acwr(daily, end)
        self.assertGreater(r, 1.5)

    def test_zero_chronic_returns_none(self):
        daily, end = self._uniform(35, load=0.0)
        self.assertIsNone(M.acwr(daily, end))


class TestMonotonyStrain(unittest.TestCase):
    def test_constant_week_sd_zero_none(self):
        daily, end = TestACWR()._uniform(10, load=300.0)
        mono, strain = M.monotony_strain(daily, end)
        self.assertIsNone(mono)                        # SD == 0 guard

    def test_varied_week_computes(self):
        end = date(2026, 6, 30)
        start = end - timedelta(days=6)
        loads = [300, 0, 450, 300, 0, 500, 250]
        rows = [[start + timedelta(days=i), float(l), None] for i, l in enumerate(loads)]
        daily = M.daily_load_series(sessions_df(rows), end)
        mono, strain = M.monotony_strain(daily, end)
        self.assertIsNotNone(mono)
        self.assertAlmostEqual(strain, mono * sum(loads), places=4)


class TestWellnessZ(unittest.TestCase):
    def test_cold_start_returns_none(self):
        start = date(2026, 6, 1)
        w = steady_wellness(start, 5)
        zs = M.wellness_z(w, start + timedelta(days=4))
        self.assertTrue(all(v is None for v in zs.values()))

    def test_dip_detected_after_baseline(self):
        start = date(2026, 6, 1)
        # 20 varied-baseline days then a crash day
        rows = []
        for i in range(20):
            d = start + timedelta(days=i)
            v = 4 if i % 2 == 0 else 5                 # SD > 0
            rows.append([d, v, 8.0, v, v, v, v, v, None, False, None])
        crash = start + timedelta(days=20)
        rows.append([crash, 1, 4.0, 1, 1, 1, 1, 1, None, False, None])
        w = wellness_df(rows)
        zs = M.wellness_z(w, crash)
        self.assertLess(zs["fatigue"], M.Z_RED)


class TestFlags(unittest.TestCase):
    def test_missed_form_is_amber(self):
        f = M.compute_flags(on=date(2026, 6, 30), sport="archery",
                            daily=pd.Series(dtype=float), wellness=pd.DataFrame())
        self.assertEqual(f.level, "amber")
        self.assertIn("No wellness form today", f.reasons)

    def test_pain_is_red(self):
        d = date(2026, 6, 30)
        w = steady_wellness(d, 1, {d: dict(pain_flag=True, pain_location="knee")})
        f = M.compute_flags(on=d, sport="wrestling", daily=pd.Series(dtype=float), wellness=w)
        self.assertEqual(f.level, "red")
        self.assertTrue(any("knee" in r for r in f.reasons))

    def test_cold_start_absolute_low_is_red(self):
        d = date(2026, 6, 30)
        w = steady_wellness(d, 1, {d: dict(sleep_quality=2)})   # day 1, no baseline
        f = M.compute_flags(on=d, sport="archery", daily=pd.Series(dtype=float), wellness=w)
        self.assertEqual(f.level, "red")

    def test_wrestler_weight_drop_red_and_archer_ignored(self):
        d = date(2026, 6, 30)
        w = steady_wellness(d - timedelta(days=1), 2, {
            d - timedelta(days=1): dict(body_weight_kg=70.0),
            d: dict(body_weight_kg=68.0),              # -2.86% in 24h
        })
        fw = M.compute_flags(on=d, sport="wrestling", daily=pd.Series(dtype=float), wellness=w)
        fa = M.compute_flags(on=d, sport="archery", daily=pd.Series(dtype=float), wellness=w)
        self.assertEqual(fw.level, "red")
        self.assertTrue(any("Weight" in r for r in fw.reasons))
        self.assertFalse(any("Weight" in r for r in fa.reasons))

    def test_acwr_spike_red(self):
        end = date(2026, 6, 30)
        daily, _ = TestACWR()._uniform(35, load=300.0)
        daily.iloc[-7:] = 650.0
        w = steady_wellness(end, 1)
        f = M.compute_flags(on=end, sport="archery", daily=daily, wellness=w)
        self.assertEqual(f.level, "red")
        self.assertTrue(any("ACWR" in r for r in f.reasons))

    def test_all_good_is_green_with_baseline(self):
        end = date(2026, 6, 30)
        start = end - timedelta(days=34)
        rows = [[start + timedelta(days=i), 300.0 + (i % 3) * 20, None] for i in range(35)]
        daily = M.daily_load_series(sessions_df(rows), end)
        wrows = []
        for i in range(21):
            d = end - timedelta(days=20 - i)
            v = 4 if i % 2 == 0 else 5
            wrows.append([d, v, 8.0, v, v, v, v, v, None, False, None])
        w = wellness_df(wrows)
        f = M.compute_flags(on=end, sport="archery", daily=daily, wellness=w)
        self.assertEqual(f.level, "green")


class TestArrows(unittest.TestCase):
    def test_weekly_arrow_sum(self):
        end = date(2026, 6, 30)
        s = sessions_df([
            [end - timedelta(days=8), 300.0, 120],     # outside window
            [end - timedelta(days=3), 300.0, 150],
            [end, 250.0, 90],
        ])
        self.assertEqual(M.weekly_arrows(s, end), 240)


if __name__ == "__main__":
    unittest.main()
