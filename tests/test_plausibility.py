"""Plausibility checks – spikes of 2026-11-09 / 2026-11-12 and edge cases.

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "marstek_venus_a", "app"))

from plausibility import EnergyFilter, ValueFilter  # noqa: E402
from controller import LoadFollower  # noqa: E402

logging.disable(logging.CRITICAL)

QUERY = 60.0       # s between two ES.GetStatus answers


class Feed:
    def __init__(self, max_power: float = 800) -> None:
        self.t = 0.0
        self.f = EnergyFilter(lambda: max_power, clock=lambda: self.t)

    def __call__(self, key: str, value):
        out = self.f.check(key, key, value)
        self.t += QUERY
        return out


class TestEnergyFilter(unittest.TestCase):
    def test_pv_spike_2026_11_09(self):
        # raw total_pv_energy ~20 590 Wh, corrected x10; one nonsense value
        feed = Feed()
        self.assertEqual(feed("es_status.total_pv_energy_corrected", 205_900), 205_900)
        self.assertEqual(feed("es_status.total_pv_energy_corrected", 4.3e15), 205_900)
        self.assertEqual(feed("es_status.total_pv_energy_corrected", 205_910), 205_910)

    def test_grid_output_spike_2026_11_09(self):
        feed = Feed()
        self.assertEqual(feed("es_status.total_grid_output_energy", 29_176), 29_176)
        self.assertEqual(feed("es_status.total_grid_output_energy", 4.3e14), 29_176)
        self.assertEqual(feed("es_status.total_grid_output_energy", 29_180), 29_180)

    def test_spike_in_valid_range_is_a_jump(self):
        feed = Feed()
        feed("es_status.total_load_energy", 10_000)
        self.assertEqual(feed("es_status.total_load_energy", 4_294_967), 10_000)
        self.assertEqual(feed("es_status.total_load_energy", 10_010), 10_010)

    def test_drop_to_zero_and_negative_ignored(self):
        feed = Feed()
        feed("es_status.total_grid_input_energy", 5_000)
        self.assertEqual(feed("es_status.total_grid_input_energy", 0), 5_000)
        self.assertEqual(feed("es_status.total_grid_input_energy", -1), 5_000)
        self.assertEqual(feed("es_status.total_grid_input_energy", 5_001), 5_001)

    def test_normal_increase_at_full_power_accepted(self):
        feed = Feed()
        feed("es_status.total_grid_output_energy", 1_000)
        # 800 W for 60 s = 13.3 Wh per query
        self.assertEqual(feed("es_status.total_grid_output_energy", 1_014), 1_014)

    def test_real_counter_reset_confirmed_after_three(self):
        feed = Feed()
        feed("es_status.total_grid_output_energy", 29_176)
        self.assertEqual(feed("es_status.total_grid_output_energy", 3), 29_176)
        self.assertEqual(feed("es_status.total_grid_output_energy", 5), 29_176)
        self.assertEqual(feed("es_status.total_grid_output_energy", 8), 8)
        self.assertEqual(feed("es_status.total_grid_output_energy", 10), 10)

    def test_garbage_never_confirmed(self):
        feed = Feed()
        feed("es_status.total_pv_energy", 20_590)
        for _ in range(5):
            self.assertEqual(feed("es_status.total_pv_energy", 4.3e14), 20_590)

    def test_first_value_after_start(self):
        feed = Feed()
        self.assertIsNone(feed("es_mode.input_energy_wh", 4.3e14))
        self.assertEqual(feed("es_mode.input_energy_wh", 123), 123)
        self.assertEqual(feed("es_mode.input_energy_wh", None), 123)


class Values:
    """Feeds whole query results through ValueFilter (one query per minute)."""

    def __init__(self, max_power: float = 800) -> None:
        self.t = 0.0
        self.f = ValueFilter(lambda: max_power, clock=lambda: self.t)

    def __call__(self, query: str, **values) -> dict:
        data = dict(values)
        self.f.apply(query, query, data, {"total_pv_energy"}, {})
        self.t += QUERY
        return data


class TestValueFilter(unittest.TestCase):
    def test_soc_spike_2026_11_12(self):
        v = Values()
        self.assertEqual(v("es_status", bat_soc=21)["bat_soc"], 21)
        self.assertEqual(v("es_status", bat_soc=4.3e10)["bat_soc"], 21)
        self.assertEqual(v("es_status", bat_soc=21)["bat_soc"], 21)

    def test_soc_range_and_jump(self):
        v = Values()
        v("battery", soc=21)
        self.assertEqual(v("battery", soc=101)["soc"], 21)          # outside 0..100
        self.assertEqual(v("battery", soc=95)["soc"], 21)           # jump +74 %
        self.assertEqual(v("battery", soc=22)["soc"], 22)           # normal change

    def test_soc_new_level_confirmed(self):
        v = Values()
        v("battery", soc=80)
        self.assertEqual(v("battery", soc=10)["soc"], 80)
        self.assertEqual(v("battery", soc=10)["soc"], 80)
        self.assertEqual(v("battery", soc=11)["soc"], 11)          # 3rd confirmation

    def test_ranges(self):
        v = Values()
        good = v("es_status", ongrid_power=-500, bat_power=800, pv_power=1200,
                 bat_cap=2560, bat_temp=21.5)
        self.assertEqual(good, dict(ongrid_power=-500, bat_power=800, pv_power=1200,
                                    bat_cap=2560, bat_temp=21.5))
        bad = v("es_status", ongrid_power=5000, bat_power=-1700, pv_power=-5,
                bat_cap=4.3e9, bat_temp=150)
        self.assertEqual(bad, good)                                 # last valid values
        self.assertEqual(v("wifi", rssi=-59)["rssi"], -59)
        self.assertEqual(v("wifi", rssi=12)["rssi"], -59)
        self.assertEqual(v("pv", pv1_voltage=4.3e10, pv1_current=40)["pv1_voltage"], None)

    def test_unknown_numbers_overflow_only(self):
        v = Values()
        self.assertEqual(v("es_mode", foo=123456)["foo"], 123456)  # no range known
        self.assertEqual(v("es_mode", foo=4.3e10)["foo"], 123456)  # overflow
        self.assertEqual(v("es_mode", mode="Passive", id=4.3e10)["mode"], "Passive")

    def test_energy_counter_still_checked(self):
        v = Values()
        v("es_status", total_pv_energy=20_590)
        self.assertEqual(v("es_status", total_pv_energy=4.3e14)["total_pv_energy"], 20_590)

    def test_takeover_reference_overflow_ignored(self):
        class Opts(dict):
            max_power = 800
        lf = LoadFollower(Opts(lf_enabled=True), send=lambda *a: None,
                          request_reference=lambda done: None, clock=lambda: 0.0)
        lf.set_reference(4.3e10, "test")
        self.assertIsNone(lf.reference)
        lf.set_reference(180, "test")
        self.assertEqual(lf.reference, 180)


if __name__ == "__main__":
    unittest.main(verbosity=2)
