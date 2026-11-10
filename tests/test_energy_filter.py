"""Energy counter plausibility filter – spikes of 2026-11-09 and edge cases.

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "marstek_venus_a", "app"))

from energy_filter import EnergyFilter  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
