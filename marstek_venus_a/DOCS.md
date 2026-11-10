# MarstekVenusA

[Deutsch](DOCS.de.md)

Local bridge between a **Marstek Venus A** (firmware 150, Open API Rev 2.0, UDP JSON-RPC)
and Home Assistant via MQTT discovery, with zero-export load following.

## Requirements

- Mosquitto broker add-on (or another MQTT broker)
- Open API enabled in the Marstek app, static IP for the device
- A grid meter that publishes the grid power to MQTT as a plain number in W,
  **positive = import** (e.g. Shelly 3EM phase via an automation: `Shelly Phase C RAW`)
- The device's own CT clamp stays **disconnected** (with the CT the device runs its own
  ±800 W sensor tests)

## Home Assistant devices

| Device | Content |
|---|---|
| MarstekVenusA | *Communication established* (INIT / ON / FAIL / OFF), Reinitialize, Request all, Log level |
| … Control | Operating mode, Passive power (= limit for load following), Passive countdown, Apply mode |
| … Settings | Depth of discharge, LED, Bluetooth advertising |
| … Communication | Queue settings (Apply settings), requests / responses / timeouts, round-trip time |
| … Load following | Switch, settings, State, Setpoint, Load (percentile), Calculated setpoint, Power limit, Next up check in, last command |
| … Device info / WiFi / Bluetooth / Battery / PV / Energy system / Mode | one per query, with *Enable query* and *Request* |

*Total PV energy (corrected)* = device value × 10 (firmware 150 reports it 10× too small).

**Energy counters are checked for plausibility.** The device occasionally reports a single
nonsense value (e.g. ~4.3e14 Wh). Values below 0 or ≥ 2^31, decreases and jumps larger than
max power × time × 1.5 + 100 Wh are ignored (WARNING in the log), HA keeps the last valid
value. A new level confirmed by 3 queries in a row is accepted (e.g. a real counter reset).
Wrong values that already reached the energy dashboard: *Developer tools → Statistics →
Adjust a statistic*.

All entities become unavailable when *Communication established* is **OFF**
(add-on stopped, or set by the broker via the MQTT last will after a crash).

## Communication

- Requests run through a queue: *Request delay* between queries, *Request timeout*
  (default 5 s – the device normally answers in 50–100 ms; late answers are still processed).
- Setpoints have priority, only the newest queued setpoint is sent, and they do not wait
  for the request delay.
- On a timeout: queries keep their last values; a setpoint **change** is re-sent once
  immediately. *Communication established* turns FAIL only after **3 timeouts in a row**
  and ON again with the next answer.
- Initialization: GetDevice → DOD → LED → BLE → WiFi → BLE status → battery → PV → mode →
  energy system (reference for the takeover). A timeout aborts → FAIL → wait
  *Command countdown* → start again.
- Device reset (e.g. via the app): the LED turns on again – settings are **not** restored
  automatically.

## Load following

Asymmetric: **down fast, up slowly.** Short load peaks are deliberately not covered.

- `load = grid + setpoint` (reconstructed household load)
- **Up:** time-weighted *Up percentile* (30 %) of the load over the *Up window* (60 s).
  Only when the window is completely filled with values after the last setpoint change,
  the setpoint jumps directly to `percentile − reserve` if that is more than *Deadband up*
  above it. Peaks shorter than ~40 s do not move it. Limit = *Passive power*.
- **Down:**
  - *small export*: grid average over *Small export time* (5 s) below *Small export
    threshold* (−15 W), at least two values below it
  - *large export*: two consecutive values below *Large export threshold* (−50 W)
  - → setpoint to `rest load − reserve` (*Export reaction* = Rest load) or 0 W.
    Afterwards the device ramp (~15 W/s) is awaited before export is checked again.
- Setpoints below *Minimum power* are sent as 0 W.
- **Resend:** the setpoint is re-sent every *Resend interval* (30 s). This keeps Passive
  mode alive and brings the output back when the device switched its output stage off
  (it returns ~10 s after the next answered command).
- **Sensor timeout:** no grid value for 30 s → 0 W, regulation resumes with the next value.
- **Start:** bumpless takeover of the current device output. Switching off sends nothing,
  the device falls back after the countdown.

| Setting | Default |
|---|---|
| Up window / Up percentile | 60 s / 30 % |
| Reserve / Deadband up / Minimum power | 10 W / 15 W / 50 W |
| Small export threshold / time | −15 W / 5 s |
| Large export threshold | −50 W |
| Export reaction | Rest load |
| Resend interval / Command countdown | 30 s / 120 s |
| Sensor timeout | 30 s |

Note: the Venus A delivers about 13 W less than commanded, so the real import is
about reserve + 13 W. The controller always calculates with the measured grid value.

## Logging

| Level | Content |
|---|---|
| ERROR (red) | failures, rejected commands |
| WARNING (yellow) | timeouts, late answers, sensor timeout |
| INFO (green) | every setpoint change with reason, initialization |
| DEBUG (cyan) | *Up check* (why the controller regulates up or not), resends, queue, state changes |
| TRACE (grey) | raw UDP / MQTT traffic |

## Migration from BalconyPowerPlant

1. Stop and uninstall the *BalconyPowerPlant* add-on (both must not control the device).
2. Delete the old MQTT device *BalconyPowerPlant* in HA (*Settings → Devices → MQTT*).
3. Install *MarstekVenusA*, take over device IP / MQTT settings, check the load following
   settings (new names, see above).
4. Update automations that used old entities (new entity ids start with `marstekvenusa_`).
