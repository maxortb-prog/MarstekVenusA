# Changelog

All notable changes to this add-on. / Alle Änderungen an diesem Add-on.
Format: [Keep a Changelog](https://keepachangelog.com), [Semantic Versioning](https://semver.org).

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
