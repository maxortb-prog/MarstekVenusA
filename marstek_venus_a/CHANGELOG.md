# Changelog

All notable changes to this add-on. / Alle Änderungen an diesem Add-on.
Format: [Keep a Changelog](https://keepachangelog.com), [Semantic Versioning](https://semver.org).

## [1.0.4] – 2026-11-14

### Added / Neu
- Entity *PV1 power (corrected)* = PV1 power ÷ 10. Firmware 150 reports PV1 power 10× too
  high (1543 W while PV2–4 showed 310 / 163 / 39 W and the total PV power ~700 W); PV2–4
  are correct. The raw value is kept; its plausibility range is 0–30 000 W.
  / Neue Entität *PV1 power (corrected)* = Rohwert ÷ 10 (FW 150 liefert PV1 10× zu hoch).

## [1.0.3] – 2026-11-14

### Fixed / Behoben
- **Plausibility checks for all device values** (`plausibility.py`, was `energy_filter.py`).
  Log 2026-11-12: SOC ~4.3e10 % – the firmware overflow value (~2^32 × scale) can appear
  in any field. / Plausibilitätsprüfung für alle Gerätewerte.
  - every number: |value| < 2^31 / jede Zahl: Betrag < 2³¹
  - physical ranges: SOC 0–100 %, battery temperature −30…80 °C, grid / off-grid /
    battery power ±2 × max power, PV power 0–3000 W, PV voltage 0–100 V, PV current
    0–30 A, CT power ±25 000 W, capacities 0–20 000 Wh, WiFi signal −120…0 dBm
  - SOC: change ≤ 5 % + 2 %/min, a new level confirmed by 3 queries in a row is accepted
  - takeover reference (ongrid_power) outside ±2 × max power is ignored and read again
  - energy counters as in 1.0.2
  Rejected values: WARNING `[plausibility]`, HA keeps the last valid value.
  / Verworfene Werte: WARNING, HA behält den letzten gültigen Wert.

## [1.0.2] – 2026-11-10

### Fixed / Behoben
- **Plausibility filter for energy counters** (all `total_increasing` fields). Log 2026-11-09:
  the device reported single nonsense values (Total PV energy ~4.3e14 Wh raw, Total grid
  output ~4.3e14 Wh); HA counted the drop back as a meter reset → TWh in the energy dashboard.
  Rejected: values < 0 or ≥ 2^31, decreases (also to 0), jumps larger than
  max power × time × 1.5 + 100 Wh (PV: at least 2000 W). The last valid value is kept
  (WARNING). A new level confirmed by 3 queries in a row is accepted (INFO).
  / Plausibilitätsfilter für Energiezähler: unplausible Werte werden verworfen, HA behält
  den letzten gültigen Wert; 3 Bestätigungen hintereinander → neuer Stand übernommen.

## [1.0.1] – 2026-11-05

### Added / Neu
- Sensor *Calculated setpoint*: load percentile − reserve, before minimum power and limit.
  / Berechneter Sollwert vor Mindestleistung und Grenze.
- Sensor *Next up check in*: seconds until the up window is complete.
  / Sekunden bis das Fenster fürs Hochregeln vollständig ist.
- DEBUG log *Up check*: why the controller regulates up or not (below minimum, within deadband,
  at limit, …), logged when the outcome or the value changes. Log 2026-11-05: load 51 W −
  reserve 10 W = 41 W < minimum 50 W → setpoint stayed 0 W (correct, but not visible).
  / DEBUG-Log, warum (nicht) hochgeregelt wird.

### Fixed / Behoben
- *Communication established* / availability were published several times at start.
  / Wurden beim Start mehrfach gesendet.

## [1.0.0] – 2026-11-03

First version of the new add-on, successor of *BalconyPowerPlant* v0.3.12
(specification: project doc *MarstekVenusA Spec v1.0.0*, rev. 2).
/ Erste Version des neuen Add-ons, Nachfolger von *BalconyPowerPlant* v0.3.12.

### Kept / Übernommen
- All queries and entities (incl. *Total PV energy (corrected)* ×10 for FW 150), control
  (mode, Passive power, DOD, LED, BLE), queue, strict init sequence, bumpless takeover,
  write-back of runtime settings, MQTT last will. / Alle Abfragen, Steuerung, Warteschlange,
  Init-Ablauf, stoßfreie Übernahme, Zurückschreiben der Einstellungen, Last Will.

### New / Neu
- **Simplified load following** (`controller.py`): up with a time-weighted percentile of the
  load (P30 over 60 s, direct jump), down on small (−15 W / 5 s) or large (−50 W, 2 values)
  export to rest load − reserve or 0 W, cyclic resend every 30 s.
  / Vereinfachte Lastfolge: rauf per Perzentil, runter bei kleiner/großer Einspeisung,
  zyklisches Senden alle 30 s.
- Setpoints do not wait for the request delay; a setpoint change that times out is re-sent once.
  / Sollwerte warten nicht auf den Anfrage-Abstand; Timeout einer Änderung → einmal wiederholt.
- *Communication established* FAIL only after 3 timeouts in a row.
  / FAIL erst nach 3 Timeouts hintereinander.
- Automatic controller tests with simulated time (`tests/`). / Automatische Regler-Tests.

### Removed / Entfernt
- Dropout detection / HOLD, device test guard, jitter, plausibility check, settle-time logic,
  holding back queries, reset suspicion, all diagnostic counters.
  / Aussetzer-Erkennung, Device-Test-Schutz, Jitter, Plausibilitätsprüfung, Settle-Logik,
  Zurückhalten von Abfragen, Reset-Verdacht, alle Diagnose-Zähler.
