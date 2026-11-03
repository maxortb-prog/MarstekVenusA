# MarstekVenusA – Home-Assistant-Add-on

[English](README.md)

Lokale Brücke zwischen einer **Marstek Venus A** (Open API Rev 2.0, UDP) und
**Home Assistant** (MQTT Discovery), mit einfacher **Lastfolge / Nulleinspeisung**.

- Alle Gerätedaten als HA-Entitäten (Gerät, WLAN, Bluetooth, Batterie, PV, Energiesystem, Modus),
  inkl. korrigierter *Total PV energy* für Firmware 150
- Steuerung: Betriebsart, Passive-Leistung, DOD, LED, Bluetooth-Advertising
- Lastfolge: bei Einspeisung schnell runter, langsam rauf auf ein Perzentil der Last
  (kurze Spitzen werden ignoriert), zyklisches Senden des Sollwerts
- Farbiges Log mit TRACE / DEBUG / INFO / WARNING / ERROR

## Installation

1. Home Assistant → *Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories*
2. `https://github.com/maxortb-prog/MarstekVenusA` hinzufügen
3. **MarstekVenusA** installieren, Konfiguration prüfen (Geräte-IP, MQTT), starten.

Open API in der Marstek-App aktivieren (UDP-Port 30000). Die geräteeigene
Messklemme **nicht** anschließen – das Add-on regelt mit deinem Netzzähler (z. B. Shelly 3EM).

Umstieg von *BalconyPowerPlant*? Siehe [DOCS.de.md → Umstieg](marstek_venus_a/DOCS.de.md#umstieg-von-balconypowerplant).

Dokumentation: [marstek_venus_a/DOCS.de.md](marstek_venus_a/DOCS.de.md) ·
Änderungen: [marstek_venus_a/CHANGELOG.md](marstek_venus_a/CHANGELOG.md)

## Entwicklung

```
python3 -m unittest discover -s tests -v        # Regler-Tests (simulierte Zeit)
python3 tools/marstek_simulator.py --help        # Simulator Venus A + Haushalt + Shelly
```
