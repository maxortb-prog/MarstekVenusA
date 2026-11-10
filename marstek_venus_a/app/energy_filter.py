"""Plausibility filter for energy counters (state_class total_increasing).

EN: The Venus A occasionally reports a single nonsense value for an energy counter
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

_LOG = get_logger("energy")

MAX_VALID = 2 ** 31          # values at / above are firmware garbage (32-bit overflow)
JUMP_FACTOR = 1.5
JUMP_MARGIN_WH = 100.0
CONFIRMATIONS = 3            # consecutive queries that confirm a new level
MIN_PV_RATE_W = 2000.0       # PV counters: at least this rate (PV inputs > AC limit)


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
