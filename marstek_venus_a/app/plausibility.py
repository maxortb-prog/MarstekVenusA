"""Plausibility checks for all values reported by the device.

EN: The Venus A firmware occasionally reports a single nonsense value (32-bit overflow,
    ~2^32 x scale) for ANY field: energy counters on 2026-11-09, SOC ~4.3e10 % on
    2026-11-12. Wrong values are never published; HA keeps the last valid value.

    1. Every number:  |value| < 2^31
    2. Measurements:  physical range per field (RANGES), e.g. SOC 0-100 %
    3. SOC:           change <= 5 % + 2 %/min since the last valid value; a new level
                      confirmed by 3 queries in a row is accepted
    4. Energy counters (state_class total_increasing): EnergyFilter below.
DE: Plausibilitätsprüfung für alle Werte des Geräts: Überlauf-Werte, physikalische
    Grenzen je Messgröße, Sprungprüfung für SOC, Energiezähler wie bisher.

Energy counters:
    The Venus A occasionally reports a single nonsense value for an energy counter
    (log 2026-11-09: Total PV energy ~4.3e14 Wh raw, Total grid output ~4.3e14 Wh),
    the next query is normal again. Home Assistant treats the drop back as a meter
    reset and keeps the huge value in the energy statistics for good.
    A new value is only published if it is plausible:
      * range:  0 <= value < 2^31
      * no decrease (also no drop to 0)
      * increase <= rate * elapsed time * 1.5 + 100 Wh
    Otherwise the last valid value is published again (WARNING in the log).
    If 3 queries in a row confirm the same new level (e.g. a real counter reset after
    a firmware update), it is accepted (INFO). After a start, the first value in the
    valid range is accepted.
DE: Plausibilitätsfilter für Energiezähler. Unplausible Werte (Bereich, Rückgang,
    unmöglicher Sprung) werden verworfen, HA behält den letzten gültigen Wert.
    Bestätigen 3 Abfragen hintereinander einen neuen Stand, wird er übernommen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from logger import get_logger

_LOG = get_logger("plausibility")

MAX_VALID = 2 ** 31          # values at / above are firmware garbage (32-bit overflow)
JUMP_FACTOR = 1.5
JUMP_MARGIN_WH = 100.0
CONFIRMATIONS = 3            # consecutive queries that confirm a new level
MIN_PV_RATE_W = 2000.0       # PV counters: at least this rate (PV inputs > AC limit)


# physical ranges per field key; "2xmax" = +-2 x max_power
RANGES: dict[str, tuple[float | str, float | str]] = {
    "soc": (0, 100), "bat_soc": (0, 100),
    "bat_temp": (-30, 80),
    "ongrid_power": ("-2xmax", "2xmax"), "offgrid_power": ("-2xmax", "2xmax"),
    "bat_power": ("-2xmax", "2xmax"),
    "pv_power": (0, 3000),
    **{f"pv{i}_power": (0, 3000) for i in range(1, 5)},
    **{f"pv{i}_voltage": (0, 100) for i in range(1, 5)},
    **{f"pv{i}_current": (0, 30) for i in range(1, 5)},
    "a_power": (-25000, 25000), "b_power": (-25000, 25000),
    "c_power": (-25000, 25000), "total_power": (-25000, 25000),
    "bat_capacity": (0, 20000), "rated_capacity": (0, 20000), "bat_cap": (0, 20000),
    "rssi": (-120, 0),
}
SOC_KEYS = ("soc", "bat_soc")
SOC_STEP = 5.0               # % allowed at once ...
SOC_RATE = 2.0               # ... plus % per minute since the last valid value


@dataclass
class _Track:
    value: float             # last valid value
    at: float                # time of the last valid value
    cand: float | None = None
    cand_at: float = 0.0
    cand_count: int = 0


class EnergyFilter:
    def __init__(self, max_power: Callable[[], float],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._max_power = max_power
        self._clock = clock
        self._tracks: dict[str, _Track] = {}
        self.rejected = 0

    def _rate(self, key: str) -> float:
        rate = float(self._max_power())
        return max(rate, MIN_PV_RATE_W) if "pv" in key else rate

    def _max_step(self, key: str, dt: float) -> float:
        return self._rate(key) * max(dt, 0.0) / 3600.0 * JUMP_FACTOR + JUMP_MARGIN_WH

    def check(self, key: str, name: str, value, now: float | None = None):
        """Return the value to publish for counter `key` (None = nothing known yet)."""
        now = self._clock() if now is None else now
        track = self._tracks.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None if track is None else track.value
        in_range = 0 <= value < MAX_VALID

        if track is None:                       # first value after start
            if in_range:
                self._tracks[key] = _Track(value, now)
                return value
            self._reject(name, value, "out of range", None)
            return None

        reason = None
        if not in_range:
            reason = "out of range"
        elif value < track.value:
            reason = f"decrease from {track.value:g}"
        elif value - track.value > self._max_step(key, now - track.at):
            reason = (f"jump +{value - track.value:g} in {now - track.at:.0f} s "
                      f"(max {self._max_step(key, now - track.at):.0f})")
        if reason is None:
            track.value, track.at, track.cand, track.cand_count = value, now, None, 0
            return value

        # implausible: is it confirmed by consecutive queries?
        if in_range:
            if (track.cand is not None and value >= track.cand
                    and value - track.cand <= self._max_step(key, now - track.cand_at)):
                track.cand_count += 1
            else:
                track.cand_count = 1
            track.cand, track.cand_at = value, now
            if track.cand_count >= CONFIRMATIONS:
                _LOG.info("%s: new level %g confirmed by %d queries in a row - accepted "
                          "(was %g)", name, value, CONFIRMATIONS, track.value)
                track.value, track.at, track.cand, track.cand_count = value, now, None, 0
                return value
        self._reject(name, value, reason, track.value)
        return track.value

    def _reject(self, name: str, value, reason: str, kept) -> None:
        self.rejected += 1
        _LOG.warning("%s: implausible value %g ignored (%s) - keeping %s",
                     name, value, reason, "nothing" if kept is None else f"{kept:g}")


class ValueFilter:
    """Checks one query result in place: overflow for every number, ranges for
    measurements, SOC jumps; energy counters are delegated to EnergyFilter."""

    def __init__(self, max_power: Callable[[], float],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._max_power = max_power
        self._clock = clock
        self.energy = EnergyFilter(max_power, clock)
        self._last: dict[str, float] = {}           # last valid measurement
        self._soc: dict[str, _Track] = {}
        self.rejected = 0

    def _bounds(self, key: str) -> tuple[float, float] | None:
        rng = RANGES.get(key)
        if rng is None:
            return None
        mp = float(self._max_power())
        return tuple(2 * mp * (-1 if str(b).startswith("-") else 1)  # type: ignore[return-value]
                     if isinstance(b, str) else float(b) for b in rng)

    def apply(self, query_key: str, label: str, data: dict, energy_keys: set[str],
              names: dict[str, str], now: float | None = None) -> None:
        now = self._clock() if now is None else now
        for key, value in list(data.items()):
            if key == "id" or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            name = f"{label} {names.get(key, key)}"
            full = f"{query_key}.{key}"
            if key in energy_keys:
                data[key] = self.energy.check(full, name, value, now)
                continue
            reason = None
            if abs(value) >= MAX_VALID:
                reason = "overflow value"
            else:
                bounds = self._bounds(key)
                if bounds and not bounds[0] <= value <= bounds[1]:
                    reason = f"outside {bounds[0]:g}..{bounds[1]:g}"
            if reason is None and key in SOC_KEYS:
                reason = self._soc_jump(full, value, now)
                if reason == "confirmed":
                    _LOG.info("%s: new value %g confirmed by %d queries in a row - accepted",
                              name, value, CONFIRMATIONS)
                    reason = None
            if reason is None:
                self._last[full] = value
                continue
            self.rejected += 1
            kept = self._last.get(full)
            _LOG.warning("%s: implausible value %g ignored (%s) - keeping %s", name, value,
                         reason, "nothing" if kept is None else f"{kept:g}")
            data[key] = kept

    def _soc_jump(self, full: str, value: float, now: float) -> str | None:
        track = self._soc.get(full)
        if track is None:
            self._soc[full] = _Track(value, now)
            return None
        allowed = SOC_STEP + SOC_RATE * max(now - track.at, 0.0) / 60.0
        if abs(value - track.value) <= allowed:
            track.value, track.at, track.cand, track.cand_count = value, now, None, 0
            return None
        if track.cand is not None and abs(value - track.cand) <= SOC_STEP:
            track.cand_count += 1
        else:
            track.cand_count = 1
        track.cand, track.cand_at = value, now
        if track.cand_count >= CONFIRMATIONS:
            track.value, track.at, track.cand, track.cand_count = value, now, None, 0
            return "confirmed"
        return f"jump {value - track.value:+g} % (max {allowed:.0f} %)"
