# Changelog

All notable changes to this add-on. / Alle Änderungen an diesem Add-on.
Format: [Keep a Changelog](https://keepachangelog.com), [Semantic Versioning](https://semver.org).

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
