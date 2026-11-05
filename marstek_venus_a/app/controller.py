"""Load following (zero export) for the Marstek Venus A – spec v1.0.0, chapter 5.

EN: Asymmetric control: down fast, up slow.
    * Up:   time-weighted percentile of the household load over a window (default
            P30 over 60 s). Short peaks (device maintenance charging, kettle, ...)
            do not move it. Once the window is completely filled with values after
            the last setpoint change, the setpoint jumps directly to
            percentile - reserve (no steps). -> at most one up-jump per window.
    * Down: small export (average over a few seconds below a threshold) or large
            export (two consecutive values below a threshold) -> setpoint jumps to
            rest load - reserve (or 0 W). After a down step the device ramps
            (~15 W/s), export checks wait for that ramp.
    * The setpoint is re-sent cyclically (default every 30 s). This also brings the
      output back after the device switched its output stage off.
DE: Asymmetrische Regelung: runter schnell, rauf langsam.
    * Rauf:   zeitgewichtetes Perzentil der Hauslast im Fenster (Standard P30 über
              60 s). Kurze Spitzen verschieben es nicht. Ist das Fenster komplett mit
              Werten nach der letzten Änderung gefüllt, springt der Sollwert direkt
              auf Perzentil - Reserve.
    * Runter: kleine Einspeisung (Mittelwert über wenige Sekunden) oder große
              Einspeisung (zwei Werte hintereinander) -> Sollwert auf Restlast -
              Reserve (oder 0 W). Danach wird die Rampe des Geräts abgewartet.
    * Der Sollwert wird zyklisch erneut gesendet (Standard alle 30 s).

Terms / Begriffe:
    grid      Shelly value in W, positive = import (Netzbezug)
    setpoint  last commanded passive power (positive = output)
    load      grid + setpoint (reconstructed household load / Hauslast)
    cap       HA "Passive power" = upper limit (set e.g. by an SOC automation)

The controller has no own task and no MQTT/UDP code: the bridge feeds sensor
values and a 1-s tick, and executes the commands through callbacks. Every method
takes an optional `now`, so the controller can be tested with simulated time.
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

from logger import get_logger

_LOG = get_logger("control")

# ---------------------------------------------------------------- states
OFF = "OFF"                        # load following disabled
WAITING = "WAITING"                # enabled, waiting for initialization / reference
REGULATING = "REGULATING"          # normal operation
LIMITED = "LIMITED"                # load above the limit (cap), setpoint = cap
SENSOR_TIMEOUT = "SENSOR_TIMEOUT"  # no grid value -> 0 W
STATES = [OFF, WAITING, REGULATING, LIMITED, SENSOR_TIMEOUT]

REACTION_REST = "Rest load"
REACTION_ZERO = "0 W"
EXPORT_REACTIONS = [REACTION_REST, REACTION_ZERO]

# ------------------------------------------------------- fixed constants
DEVICE_RAMP = 15.0        # W/s, slowest observed output ramp of the Venus A (lessons L2)
RAMP_MARGIN = 2.0         # s added to the ramp time after a down step
HISTORY = 330.0           # s of grid samples kept (max. window 300 s + margin)
REFERENCE_RETRY = 10.0    # s between reference reads (ES.GetStatus) at takeover
INVALID_LOG_EVERY = 60.0  # s, invalid sensor payloads are logged at most this often

# ------------------------------------------- settings (HA number entities)
#  key: (name, min, max, step, unit, default)
NUMBERS: dict[str, tuple[str, float, float, float, str, float]] = {
    "lf_window":            ("Up window",              10, 300, 1, "s", 60),
    "lf_percentile":        ("Up percentile",          10, 50, 1, "%", 30),
    "lf_reserve":           ("Reserve",                0, 100, 1, "W", 10),
    "lf_deadband":          ("Deadband up",            0, 100, 1, "W", 15),
    "lf_min_power":         ("Minimum power",          0, 400, 1, "W", 50),
    "lf_export_small":      ("Small export threshold", -100, 0, 1, "W", -15),
    "lf_export_small_time": ("Small export time",      1, 30, 1, "s", 5),
    "lf_export_large":      ("Large export threshold", -400, -10, 1, "W", -50),
    "lf_resend_interval":   ("Resend interval",        10, 60, 1, "s", 30),
    "lf_cd_time":           ("Command countdown",      30, 3600, 1, "s", 120),
    "lf_sensor_timeout":    ("Sensor timeout",         5, 300, 1, "s", 30),
}

# send(power, cd_time, done) -> done(True = confirmed, False = rejected, None = timeout)
SendFn = Callable[[int, int, Callable[[bool | None], None]], None]
# request_reference(done) -> done(ongrid_power or None)
RefFn = Callable[[Callable[[Any], None]], None]


def parse_grid(payload: str) -> float | None:
    """Plain number ("123.4") or JSON with a number / power field."""
    text = payload.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return float(data)
    if isinstance(data, dict):
        for key in ("power", "value", "act_power", "apower", "state"):
            try:
                return float(data[key])
            except (KeyError, TypeError, ValueError):
                continue
    return None


class LoadFollower:
    def __init__(
        self,
        opts: Any,
        send: SendFn,
        request_reference: RefFn,
        ready: Callable[[], bool] = lambda: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.opts = opts
        self._send_fn = send
        self._request_ref_fn = request_reference
        self._ready = ready
        self._clock = clock
        self.samples: deque[tuple[float, float]] = deque()
        self.reset()
        self.last_reason: str | None = None
        self.last_command: str | None = None
        self.dirty = True
        self._last_invalid_log = -1e9

    # ============================================================ options
    def o(self, key: str) -> float:
        try:
            return float(self.opts.get(key, NUMBERS[key][5]))
        except (TypeError, ValueError):
            return float(NUMBERS[key][5])

    @property
    def enabled(self) -> bool:
        return bool(self.opts.get("lf_enabled", False))

    @property
    def export_reaction(self) -> str:
        value = str(self.opts.get("lf_export_reaction", REACTION_REST))
        return value if value in EXPORT_REACTIONS else REACTION_REST

    @property
    def cap(self) -> int:
        """Upper limit = HA Passive power, limited to max_power, >= 0."""
        try:
            p = int(self.opts.get("passive_power", 0))
        except (TypeError, ValueError):
            p = 0
        return max(0, min(p, int(getattr(self.opts, "max_power", 800))))

    # ========================================================== lifecycle
    def reset(self, now: float | None = None) -> None:
        """Forget setpoint and reference (new initialization / switched on)."""
        now = self._clock() if now is None else now
        self.setpoint: int | None = None
        self.reference: float | None = None
        self._ref_pending = False
        self._ref_next_try = 0.0
        self.last_send = -1e9
        self.last_change = now
        self.fresh_since = now          # up window only uses values after this
        self.settle_until = now         # export checks wait for the device ramp
        self.load_percentile: float | None = None
        self.calculated: int | None = None      # percentile - reserve, before limits
        self.up_in: int | None = None           # s until the up window is complete
        self._up_note: tuple[str, int] | None = None
        self.state = WAITING if self.enabled else OFF
        self._enabled_at = now
        self._timeout_retry_for: int | None = None
        self.dirty = True

    def set_enabled(self, on: bool, reason: str, now: float | None = None) -> None:
        if on == self.enabled:
            return
        self.opts.set("lf_enabled", on)
        self.reset(now)
        if on:
            _LOG.info("Load following ENABLED (%s) - limit %d W", reason, self.cap)
            self.evaluate(now)
        else:
            _LOG.info("Load following DISABLED (%s) - no more commands, the device falls "
                      "back after cd_time", reason)

    def set_reference(self, ongrid_power: Any, source: str) -> None:
        """Current device output from ES.GetStatus (ongrid_power, positive = output)."""
        try:
            value = float(ongrid_power)
        except (TypeError, ValueError):
            _LOG.warning("Reference from %s unusable: ongrid_power=%r", source, ongrid_power)
            return
        self.reference = value
        self._ref_pending = False
        _LOG.info("Reference from %s: device output %.0f W", source, value)

    # ============================================================= sensor
    def on_sensor(self, payload: str, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        value = parse_grid(payload)
        if value is None:
            if now - self._last_invalid_log > INVALID_LOG_EVERY:
                self._last_invalid_log = now
                _LOG.warning("Grid sensor: invalid payload %r ignored", payload)
            return
        if self.state == SENSOR_TIMEOUT:
            _LOG.info("Grid sensor back (%.0f W) - regulating again", value)
            self.fresh_since = now
            self._set_state(REGULATING)
        self.samples.append((now, value))
        # keep one sample older than the history: it is the held value
        while len(self.samples) > 1 and now - self.samples[1][0] > HISTORY:
            self.samples.popleft()
        _LOG.trace("Grid sensor %.0f W", value)
        self.dirty = True
        if self.enabled:
            self.evaluate(now)

    def tick(self, now: float | None = None) -> None:
        """Called every second by the bridge (timeouts, cyclic resend)."""
        if self.enabled:
            self.evaluate(now)

    # ======================================================== time series
    def _segments(self, t0: float, t1: float) -> list[tuple[float, float]]:
        """(value, duration) pieces between t0 and t1 – sample and hold: a value is
        valid until the next one arrives (the sensor may only report changes)."""
        out: list[tuple[float, float]] = []
        held: float | None = None
        seg_start = t0
        for t, v in self.samples:
            if t <= t0:
                held = v
                continue
            if t >= t1:
                break
            if held is not None and t > seg_start:
                out.append((held, t - seg_start))
            seg_start, held = t, v
        if held is not None and t1 > seg_start:
            out.append((held, t1 - seg_start))
        return out

    def average(self, t0: float, t1: float) -> float | None:
        segs = self._segments(t0, t1)
        total = sum(d for _, d in segs)
        return sum(v * d for v, d in segs) / total if total > 0 else None

    def percentile(self, t0: float, t1: float, pct: float) -> float | None:
        """Time-weighted percentile: the value the grid stays below pct % of the time."""
        segs = sorted(self._segments(t0, t1))
        total = sum(d for _, d in segs)
        if total <= 0:
            return None
        limit, acc = total * pct / 100.0, 0.0
        for v, d in segs:
            acc += d
            if acc >= limit:
                return v
        return segs[-1][0]

    def _covered(self, t0: float) -> bool:
        """Is there a value at (or before) t0? Otherwise the window is incomplete."""
        return bool(self.samples) and self.samples[0][0] <= t0

    # ========================================================= regulation
    def evaluate(self, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        if not self.enabled:
            self._set_state(OFF)
            return
        if not self._ready():
            self._set_state(WAITING)
            return

        # --- takeover (bumpless) -----------------------------------------
        if self.setpoint is None:
            if self.reference is None:
                self._set_state(WAITING)
                self._request_reference(now)
                return
            sp = self._limit(round(self.reference))
            _LOG.info("Takeover: device output %.0f W -> setpoint %d W (limit %d W)",
                      self.reference, sp, self.cap)
            self.reference = None
            self._command(sp, "takeover", now)
            self._set_state(REGULATING)
            return

        self._regulate(now)

        # --- cyclic resend ------------------------------------------------
        if self.setpoint is not None and now - self.last_send >= self.o("lf_resend_interval"):
            self._command(self.setpoint, "resend", now, change=False)

    def _regulate(self, now: float) -> None:
        assert self.setpoint is not None
        cap, min_p = self.cap, int(self.o("lf_min_power"))

        # --- sensor timeout ---------------------------------------------
        last_value_at = self.samples[-1][0] if self.samples else self._enabled_at
        if now - max(last_value_at, self._enabled_at) > self.o("lf_sensor_timeout"):
            if self.state != SENSOR_TIMEOUT:
                _LOG.warning("Grid sensor: no value for %.0f s - setpoint 0 W",
                             now - last_value_at)
                self._set_state(SENSOR_TIMEOUT)
                if self.setpoint != 0:
                    self._command(0, "sensor timeout", now)
            return

        if not self.samples:
            return

        # --- limit lowered in HA -------------------------------------------
        if self.setpoint > cap:
            self._command(self._limit(cap), f"limit lowered to {cap} W", now)
            return

        grid = self.samples[-1][1]
        reserve = self.o("lf_reserve")

        # --- regulate down: export -----------------------------------------
        if now >= self.settle_until and self.setpoint > 0:
            reason = None
            large = self.o("lf_export_large")
            last2 = list(self.samples)[-2:]
            if (len(last2) == 2 and all(t >= self.settle_until and v < large for t, v in last2)):
                reason = "large export"
            else:
                t_small = self.o("lf_export_small_time")
                start = now - t_small
                small = self.o("lf_export_small")
                if start >= self.settle_until and self._covered(start):
                    avg = self.average(start, now)
                    # at least 2 values below the threshold: a single outlier can
                    # not trigger it (same protection as for a large export)
                    below = sum(1 for t, v in self.samples if t > start and v < small)
                    if avg is not None and avg < small and below >= 2:
                        reason = "small export"
            if reason:
                load = grid + self.setpoint
                new = 0 if self.export_reaction == REACTION_ZERO else self._limit(round(load - reserve))
                if new < self.setpoint:
                    self._command(new, f"{reason} {grid:+.0f} W, load {load:.0f} W", now)
                    self._set_state(REGULATING)
                    return

        # --- regulate up: percentile over a fresh window -------------------
        window = self.o("lf_window")
        start = now - window
        if start < self.fresh_since or not self._covered(start):
            first = self.samples[0][0] if self.samples else now
            up_in = round(max(self.fresh_since, first) + window - now)
            if up_in != self.up_in:
                self.up_in = max(0, up_in)
                self.dirty = True
            return
        if self.up_in != 0:
            self.up_in = 0
            self.dirty = True
        pct = self.o("lf_percentile")
        p = self.percentile(start, now, pct)
        if p is None:
            return
        self.load_percentile = p + self.setpoint
        target = self.load_percentile - reserve
        calculated = round(target)
        if calculated != self.calculated:
            self.calculated = calculated
            self.dirty = True
        new = self._limit(calculated)
        deadband = self.o("lf_deadband")
        min_p = self.o("lf_min_power")
        go_up = new - self.setpoint > deadband or (new == cap > self.setpoint)

        # debug: why (not) up - logged when the outcome or the value changes
        if go_up:
            note = "up"
        elif calculated > cap and self.setpoint >= cap:
            note = f"at limit {cap} W"
        elif 0 < calculated < min_p and self.setpoint == 0:
            note = f"below minimum {min_p:.0f} W, stays 0 W"
        elif calculated <= self.setpoint:
            note = "not above setpoint"
        else:
            note = f"within deadband {deadband:.0f} W"
        if self._up_note is None or self._up_note[0] != note \
                or abs(self._up_note[1] - calculated) >= 5:
            self._up_note = (note, calculated)
            _LOG.debug("Up check: load P%.0f %.0f W - reserve %.0f W = %d W (setpoint %d W) -> %s",
                       pct, self.load_percentile, reserve, calculated, self.setpoint, note)

        if go_up:
            self._command(new, f"up, load P{pct:.0f} {self.load_percentile:.0f} W", now)
        self._set_state(LIMITED if target > cap and self.setpoint >= cap else REGULATING)

    def _limit(self, value: int) -> int:
        """Limit to [0, cap]; below the minimum power -> 0 W."""
        value = max(0, min(int(value), self.cap))
        return 0 if value < self.o("lf_min_power") else value

    def _request_reference(self, now: float) -> None:
        if self._ref_pending or now < self._ref_next_try:
            return
        self._ref_pending = True
        _LOG.info("Reading ES.GetStatus as reference for the takeover")

        def done(value: Any) -> None:
            self._ref_pending = False
            if value is None:
                self._ref_next_try = self._clock() + REFERENCE_RETRY
                _LOG.warning("Reference read failed - next try in %.0f s", REFERENCE_RETRY)
                return
            self.set_reference(value, "ES.GetStatus")
            self.evaluate()
        self._request_ref_fn(done)

    # ============================================================ commands
    def _command(self, power: int, reason: str, now: float, change: bool = True) -> None:
        old = self.setpoint
        cd_time = int(self.o("lf_cd_time"))
        self.setpoint = power
        self.last_send = now
        if change:
            self.last_change = now
            self.fresh_since = max(self.fresh_since, now)
            if old is not None and power < old:
                # the device ramps down: export checks wait until it has followed
                self.settle_until = now + (old - power) / DEVICE_RAMP + RAMP_MARGIN
            self.last_reason = reason
            self.last_command = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _LOG.info("Setpoint %s -> %d W (%s)", "-" if old is None else f"{old} W",
                      power, reason)
        else:
            _LOG.debug("Setpoint %d W re-sent (%s)", power, reason)
        self.dirty = True

        def done(ok: bool | None) -> None:
            if ok is None and change and self.setpoint == power \
                    and self._timeout_retry_for != power:
                # a setpoint CHANGE timed out -> re-send it once immediately (spec 4.4)
                self._timeout_retry_for = power
                _LOG.warning("Setpoint %d W: timeout - re-sending once", power)
                self.last_send = self._clock()
                self._send_fn(power, cd_time, lambda _ok: None)
            elif ok is False:
                _LOG.error("Setpoint %d W rejected by the device", power)
        self._timeout_retry_for = None if change else self._timeout_retry_for
        self._send_fn(power, cd_time, done)

    def _set_state(self, state: str) -> None:
        if state != self.state:
            _LOG.debug("State %s -> %s", self.state, state)
            self.state = state
            self.dirty = True

    # ============================================================ snapshot
    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "setpoint": self.setpoint,
            "load_percentile": None if self.load_percentile is None
            else round(self.load_percentile),
            "limit": self.cap,
            "calculated_setpoint": self.calculated,
            "up_in": self.up_in,
            "last_reason": self.last_reason,
            "last_command": self.last_command,
        }
