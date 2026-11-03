"""Controller tests with simulated time – spec v1.0.0, chapter 9.

EN: A small plant model of the Venus A (ramp, offset, output-stage-off with soft
    start) and a household with a Shelly that reports every second. Runs without
    MQTT / UDP:  python3 -m unittest discover -s tests -v
DE: Kleines Modell des Venus A (Rampe, Abweichung, Endstufe aus mit Softstart) und
    ein Haushalt mit Shelly (jede Sekunde). Läuft ohne MQTT / UDP.
"""

from __future__ import annotations

import logging
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "marstek_venus_a", "app"))

from controller import (LIMITED, REACTION_ZERO, REGULATING, SENSOR_TIMEOUT,  # noqa: E402
                        LoadFollower)

logging.disable(logging.CRITICAL)


class Opts(dict):
    max_power = 800

    def set(self, key, value):
        self[key] = value


class Device:
    """Venus A model: output follows the setpoint with RAMP W/s and delivers OFFSET W
    less. Output stage off: unreachable for UNREACHABLE s, output 0 until the next
    answered SetMode, then SOFT_START s delay before ramping again (lessons L1-L5)."""
    RAMP, OFFSET, UNREACHABLE, SOFT_START = 15.0, 13.0, 4.0, 10.0

    def __init__(self, output: float = 0.0) -> None:
        self.setpoint = output + self.OFFSET if output else 0.0
        self.output = output
        self.unreachable_until = -1.0
        self.off = False
        self.ramp_from = 0.0            # no ramping before this time (soft start)
        self.commands: list[tuple[float, int]] = []

    def outage(self, t: float) -> None:
        self.off = True
        self.output = 0.0
        self.unreachable_until = t + self.UNREACHABLE

    def command(self, t: float, power: int) -> bool | None:
        if t < self.unreachable_until:
            return None                 # timeout
        self.commands.append((t, power))
        self.setpoint = power
        if self.off:
            self.off = False
            self.ramp_from = t + self.SOFT_START
        return True

    def step(self, t: float, dt: float) -> None:
        if self.off or t < self.ramp_from:
            return
        target = max(0.0, self.setpoint - self.OFFSET) if self.setpoint > 0 else 0.0
        delta = max(-self.RAMP * dt, min(self.RAMP * dt, target - self.output))
        self.output += delta


class Sim:
    def __init__(self, load, start_output: float = 0.0, cap: int = 800, noise: float = 3.0,
                 **opts) -> None:
        self.t = 0.0
        self.load = load
        self.dev = Device(start_output)
        self.rng = random.Random(1)
        self.noise = noise
        self.sensor_on = True
        self.opts = Opts(lf_enabled=True, passive_power=cap, **opts)
        self.lf = LoadFollower(self.opts, send=self._send, request_reference=self._ref,
                               clock=lambda: self.t)
        self.log: list[tuple[float, float, float, int | None]] = []   # t, load, grid, sp

    def _send(self, power, cd_time, done):
        done(self.dev.command(self.t, power))

    def _ref(self, done):
        done(self.dev.output)

    def grid(self) -> float:
        return self.load(self.t) - self.dev.output

    def run(self, until: float, events=None) -> None:
        events = dict(events or {})
        while self.t < until:
            for at in [a for a in events if a <= self.t]:
                events.pop(at)(self)
            self.dev.step(self.t, 1.0)
            if self.sensor_on:
                g = self.grid() + self.rng.uniform(-self.noise, self.noise)
                self.lf.on_sensor(f"{g:.1f}", now=self.t)
            self.lf.tick(now=self.t)
            self.log.append((self.t, self.load(self.t), self.grid(), self.lf.setpoint))
            self.t += 1.0

    # ------------------------------------------------------------ helpers
    def export_wh(self, t0: float = 0, t1: float = 1e9) -> float:
        return sum(-g for t, _, g, _ in self.log if t0 <= t < t1 and g < 0) / 3600.0

    def sp_at(self, t: float) -> int | None:
        return next(sp for tt, _, _, sp in self.log if tt >= t)

    def changes(self) -> list[tuple[float, int]]:
        out, last = [], object()
        for t, _, _, sp in self.log:
            if sp != last:
                out.append((t, sp))
                last = sp
        return out


def steps(*points):
    """Load profile from (time, W) points (step function)."""
    def load(t):
        value = points[0][1]
        for at, w in points:
            if t >= at:
                value = w
        return value
    return load


class TestController(unittest.TestCase):
    def test_takeover_is_bumpless(self):
        sim = Sim(steps((0, 300)), start_output=180)
        sim.run(3)
        self.assertEqual(sim.dev.commands[0][1], 180)

    def test_load_step_up_follows_within_window(self):
        sim = Sim(steps((0, 50), (100, 240)))
        sim.run(260)
        self.assertEqual(sim.sp_at(99), 0)                  # 50 W < min power
        t_up = next(t for t, sp in sim.changes() if t > 100 and sp)
        self.assertLessEqual(t_up - 100, 70)                # within the window (+ margin)
        self.assertTrue(200 <= sim.sp_at(255) <= 240)
        self.assertLess(sim.export_wh(), 0.05)

    def test_short_peaks_are_ignored(self):
        # PC at 190 W, one 20-s peak of 660 W and device peaks of 2 s (lessons L10)
        load = steps((0, 190), (200, 660), (220, 190), (300, 650), (302, 190),
                     (340, 700), (341, 190))
        sim = Sim(load)
        sim.run(160)
        before = sim.lf.setpoint
        sim.run(420)
        self.assertEqual(sim.lf.setpoint, before)
        self.assertEqual([c for c in sim.changes() if c[0] > 160], [])

    def test_pc_shutdown_steps_and_off(self):
        load = steps((0, 280), (200, 200), (230, 160), (260, 40))
        sim = Sim(load)
        sim.run(400)
        self.assertTrue(180 <= sim.sp_at(225) <= 210)       # followed the first step (large)
        self.assertTrue(140 <= sim.sp_at(255) <= 180)       # small export -20 W followed
        self.assertEqual(sim.sp_at(275), 0)                 # rest load 40 W < min -> 0 W
        self.assertLess(sim.export_wh(200, 400), 0.6)       # < 1 Wh per big step (spec 5.3)

    def test_single_outlier_is_ignored(self):
        sim = Sim(steps((0, 250), (200, 20), (201, 250)), noise=0)
        sim.run(260)
        self.assertEqual([c for c in sim.changes() if c[0] > 150], [])

    def test_export_reaction_zero(self):
        sim = Sim(steps((0, 300), (200, 200)), lf_export_reaction=REACTION_ZERO)
        sim.run(230)
        self.assertEqual(sim.sp_at(210), 0)

    def test_output_stage_off_recovers_by_resend(self):
        sim = Sim(steps((0, 300)), cap=250)
        sim.run(200, {150: lambda s: s.dev.outage(s.t)})
        back = next(t for t in range(151, 200) if sim.log[t][1] - sim.log[t][2] > 5)
        self.assertLessEqual(back - 150, 42)                # spec: output back after ~40 s
        self.assertEqual(sim.lf.setpoint, 250)

    def test_limit_and_limited_state(self):
        sim = Sim(steps((0, 500)), cap=300)
        sim.run(150)
        self.assertEqual(sim.lf.setpoint, 300)
        self.assertEqual(sim.lf.state, LIMITED)
        sim.opts["passive_power"] = 100                     # SOC automation lowers the cap
        sim.run(155)
        self.assertEqual(sim.lf.setpoint, 100)

    def test_sensor_timeout_and_recovery(self):
        sim = Sim(steps((0, 300)))
        sim.run(120)
        self.assertGreater(sim.lf.setpoint, 200)
        sim.sensor_on = False
        sim.run(160)
        self.assertEqual(sim.lf.state, SENSOR_TIMEOUT)
        self.assertEqual(sim.lf.setpoint, 0)
        sim.sensor_on = True
        sim.run(260)
        self.assertEqual(sim.lf.state, REGULATING)
        self.assertGreater(sim.lf.setpoint, 200)

    def test_resend_interval(self):
        sim = Sim(steps((0, 300)), cap=200)
        sim.run(400)
        times = [t for t, _ in sim.dev.commands if t > 150]
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(gaps and max(gaps) <= 31 and min(gaps) >= 29)


if __name__ == "__main__":
    unittest.main(verbosity=2)
