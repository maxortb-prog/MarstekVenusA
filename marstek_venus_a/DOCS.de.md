# MarstekVenusA

[English](DOCS.md)

Lokale Brücke zwischen einer **Marstek Venus A** (Firmware 150, Open API Rev 2.0, UDP JSON-RPC)
und Home Assistant per MQTT Discovery, mit Lastfolge / Nulleinspeisung.

## Voraussetzungen

- Mosquitto-Broker-Add-on (oder ein anderer MQTT-Broker)
- Open API in der Marstek-App aktiviert, feste IP für das Gerät
- Ein Netzzähler, der die Netzleistung als Zahl in W per MQTT sendet,
  **positiv = Bezug** (z. B. Shelly-3EM-Phase über eine Automation: `Shelly Phase C RAW`)
- Die geräteeigene Messklemme bleibt **abgesteckt** (mit Klemme macht das Gerät eigene
  ±800-W-Sensortests)

## Geräte in Home Assistant

| Gerät | Inhalt |
|---|---|
| MarstekVenusA | *Communication established* (INIT / ON / FAIL / OFF), Neu initialisieren, Alle abfragen, Log-Level |
| … Control | Betriebsart, Passive power (= Grenze für die Lastfolge), Passive countdown, Apply mode |
| … Settings | Entladetiefe (DOD), LED, Bluetooth-Advertising |
| … Communication | Warteschlangen-Einstellungen (Apply settings), Anfragen / Antworten / Timeouts, Antwortzeit |
| … Load following | Schalter, Einstellungen, Zustand, Sollwert, Last (Perzentil), berechneter Sollwert, Leistungsgrenze, nächste Prüfung Hochregeln, letzter Befehl |
| … Device info / WiFi / Bluetooth / Battery / PV / Energy system / Mode | je Abfrage eines, mit *Enable query* und *Request* |

*Total PV energy (corrected)* = Gerätewert × 10 (Firmware 150 liefert ihn 10× zu klein).

Alle Entitäten werden unverfügbar, wenn *Communication established* **OFF** ist
(Add-on gestoppt, oder vom Broker per MQTT Last Will nach einem Absturz gesetzt).

## Kommunikation

- Anfragen laufen über eine Warteschlange: *Request delay* zwischen Abfragen, *Request timeout*
  (Standard 5 s – das Gerät antwortet normal in 50–100 ms; späte Antworten werden trotzdem verarbeitet).
- Sollwerte haben Vorrang, nur der neueste wartende Sollwert wird gesendet, und sie warten
  nicht auf den Request delay.
- Bei Timeout: Abfragen behalten ihre letzten Werte; eine Sollwert**änderung** wird einmal
  sofort wiederholt. *Communication established* geht erst nach **3 Timeouts hintereinander**
  auf FAIL und mit der nächsten Antwort wieder auf ON.
- Initialisierung: GetDevice → DOD → LED → BLE → WLAN → BLE-Status → Batterie → PV → Modus →
  Energiesystem (Referenz für die Übernahme). Ein Timeout bricht ab → FAIL → *Command countdown*
  warten → Neustart.
- Geräte-Reset (z. B. über die App): Die LED geht wieder an – Einstellungen werden **nicht**
  automatisch wiederhergestellt.

## Lastfolge

Asymmetrisch: **runter schnell, rauf langsam.** Kurze Lastspitzen werden bewusst nicht gedeckt.

- `Last = Netz + Sollwert` (rekonstruierte Hauslast)
- **Rauf:** zeitgewichtetes *Up percentile* (30 %) der Last über das *Up window* (60 s).
  Erst wenn das Fenster komplett mit Werten nach der letzten Sollwertänderung gefüllt ist,
  springt der Sollwert direkt auf `Perzentil − Reserve`, wenn das mehr als *Deadband up*
  darüber liegt. Spitzen kürzer als ~40 s verschieben ihn nicht. Grenze = *Passive power*.
- **Runter:**
  - *kleine Einspeisung*: Netz-Mittelwert über *Small export time* (5 s) unter *Small export
    threshold* (−15 W), mindestens zwei Werte darunter
  - *große Einspeisung*: zwei Werte hintereinander unter *Large export threshold* (−50 W)
  - → Sollwert auf `Restlast − Reserve` (*Export reaction* = Rest load) oder 0 W.
    Danach wird die Rampe des Geräts (~15 W/s) abgewartet, bevor wieder auf Einspeisung geprüft wird.
- Sollwerte unter *Minimum power* werden als 0 W gesendet.
- **Wiederholtes Senden:** Der Sollwert wird alle *Resend interval* (30 s) erneut gesendet. Das hält
  Passive aktiv und holt den Ausgang zurück, wenn das Gerät die Endstufe abgeschaltet hat
  (sie kommt ~10 s nach dem nächsten beantworteten Befehl wieder).
- **Sensor-Timeout:** 30 s kein Netzwert → 0 W, mit dem nächsten Wert wird wieder geregelt.
- **Start:** stoßfreie Übernahme der aktuellen Geräteleistung. Ausschalten sendet nichts,
  das Gerät fällt nach dem Countdown zurück.

| Einstellung | Standard |
|---|---|
| Up window / Up percentile | 60 s / 30 % |
| Reserve / Deadband up / Minimum power | 10 W / 15 W / 50 W |
| Small export threshold / time | −15 W / 5 s |
| Large export threshold | −50 W |
| Export reaction | Rest load |
| Resend interval / Command countdown | 30 s / 120 s |
| Sensor timeout | 30 s |

Hinweis: Der Venus A liefert etwa 13 W weniger als vorgegeben, der reale Netzbezug liegt also
bei etwa Reserve + 13 W. Der Regler rechnet immer mit dem gemessenen Netzwert.

## Logging

| Level | Inhalt |
|---|---|
| ERROR (rot) | Fehler, abgelehnte Befehle |
| WARNING (gelb) | Timeouts, späte Antworten, Sensor-Timeout |
| INFO (grün) | jede Sollwertänderung mit Grund, Initialisierung |
| DEBUG (cyan) | *Up check* (warum hochgeregelt wird oder nicht), wiederholtes Senden, Warteschlange, Zustandswechsel |
| TRACE (grau) | roher UDP- / MQTT-Verkehr |

## Umstieg von BalconyPowerPlant

1. Add-on *BalconyPowerPlant* stoppen und deinstallieren (beide dürfen das Gerät nicht gleichzeitig steuern).
2. Altes MQTT-Gerät *BalconyPowerPlant* in HA löschen (*Einstellungen → Geräte → MQTT*).
3. *MarstekVenusA* installieren, Geräte-IP / MQTT übernehmen, Lastfolge-Einstellungen prüfen
   (neue Namen, siehe oben).
4. Automationen anpassen, die alte Entitäten verwendet haben (neue Entitäts-IDs beginnen mit `marstekvenusa_`).
