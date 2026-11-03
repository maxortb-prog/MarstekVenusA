# MarstekVenusA – Home Assistant add-on

[Deutsch](README.de.md)

Local bridge between a **Marstek Venus A** battery (Open API Rev 2.0, UDP) and
**Home Assistant** (MQTT discovery), with simple **zero-export load following**.

- All device data as HA entities (device, WiFi, Bluetooth, battery, PV, energy system, mode),
  including the corrected *Total PV energy* for firmware 150
- Control: operating mode, Passive power, DOD, LED, Bluetooth advertising
- Load following: down fast on export, up slowly to a percentile of the load
  (short peaks are ignored), cyclic resend of the setpoint
- Coloured log with TRACE / DEBUG / INFO / WARNING / ERROR

## Installation

1. Home Assistant → *Settings → Add-ons → Add-on store → ⋮ → Repositories*
2. Add `https://github.com/maxortb-prog/MarstekVenusA`
3. Install **MarstekVenusA**, check the configuration (device IP, MQTT), start it.

Enable the Open API in the Marstek app (UDP port 30000). Do **not** connect the
device's own CT clamp – the add-on regulates with your grid meter (e.g. Shelly 3EM).

Coming from *BalconyPowerPlant*? See [DOCS.md → Migration](marstek_venus_a/DOCS.md#migration-from-balconypowerplant).

Documentation: [marstek_venus_a/DOCS.md](marstek_venus_a/DOCS.md) ·
Changelog: [marstek_venus_a/CHANGELOG.md](marstek_venus_a/CHANGELOG.md)

## Development

```
python3 -m unittest discover -s tests -v        # controller tests (simulated time)
python3 tools/marstek_simulator.py --help        # Venus A + household + Shelly simulator
```
