# WatchBridge for Sailfish OS

A companion app that connects a **Huawei Watch GT 5 / GT 5 Pro** to **Sailfish OS 5**: pairing,
notification sync, weather and health data, with no Huawei Health app and no Android App Support needed.

The watch protocol is a Python port of the Huawei support in
[Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge), so this project is licensed AGPL-3.0 as well.

## Features

- **Pairing:** Bluetooth bonding plus Huawei's HiChain handshake, with a step-by-step pairing screen
- **Notification sync:** phone notifications (native apps and Android App Support apps) are forwarded to the
  watch. Forward everything except muted apps, or only the apps you select. Apps are picked from a list of
  apps that recently sent notifications. You can also choose whether system messages are included.
- **Weather:** current conditions, a 24-hour hourly forecast and an 8-day forecast from
  [Open-Meteo](https://open-meteo.com) (no API key needed). Pushed on a schedule and whenever the watch asks.
- **Health data:** today's totals, per-minute steps and heart rate (and SpO2 where the watch records it),
  and basic sleep (light/deep) are fetched from the watch every few hours. Heart rate needs the watch's
  continuous measurement, which you can switch on in the app's settings. On a Watch GT 5, sleep only comes
  through TruSleep files, which aren't supported yet. They're stored on the phone in
  `~/Documents/WatchBridge/` as an SQLite database plus CSV files: `activity-YYYY-MM.csv`, `sleep.csv` and
  `daily.csv`. Open them in any spreadsheet, copy them over USB, or sync them with Nextcloud. A health
  page shows steps per hour, the heart-rate curve and last night's sleep for any day.
- **Extras:** time and time-zone sync, battery level, "find my phone" (the watch makes the phone ring),
  automatic reconnect, and a live status cover

## Status

| | |
|---|---|
| Tested with | Huawei Watch GT 5 (VLI-B19, firmware 6.0.0.23) on a Sony Xperia with Sailfish OS 5.2.0.22 (aarch64) |
| Verified on that watch | Pairing, HiChain authentication, encrypted connection, automatic reconnect, battery level, notification allow-list, health sync (totals, steps, distance, calories, heart rate) |
| Implemented, verified against a simulated watch | Notifications on the watch, weather, find my phone, time sync |

This is an early release. Please report what works and what doesn't on your watch and phone in the issues.
Bluetooth logs help a lot (see [Troubleshooting](#troubleshooting)).

## Installation

1. Download the latest `harbour-watchbridge-<version>.noarch.rpm` from the **Releases** page.
2. Copy it to the phone and install it in a terminal (enable *Settings → Developer tools* first):

   ```bash
   devel-su pkcon install-local harbour-watchbridge-*.noarch.rpm
   ```

3. Start the background service, or simply reboot:

   ```bash
   systemctl --user restart harbour-watchbridge
   ```

The package is `noarch` and works on aarch64, armv7hl and i486 devices. All dependencies come from the
official Jolla repositories.

> WatchBridge is not in the Jolla Store (Harbour) and cannot be: Harbour forbids background services,
> custom D-Bus services and reading other apps' notifications.

## Pairing a watch

1. **Start clean.** In *Settings → Bluetooth* on the phone, forget the watch if it is listed. If the watch has
   ever been paired with another phone or with Huawei Health, factory-reset it
   (*Settings → System & updates → Reset* on the watch).
2. Open **WatchBridge → Pair a watch** and tap the watch in the list.
3. Accept the Bluetooth pairing request on the phone and on the watch.
4. Keep the watch screen on. If the watch asks you to confirm the connection, tap ✓.
5. Under **Weather → Location**, choose a city or use GPS.

Pair through the app, not through the Sailfish Bluetooth settings: the watch expects the app's handshake right
after the Bluetooth pairing and gives up after a short time. If a pairing attempt fails, start again from
step 1, because the watch usually discards its half-finished pairing.

## Settings

- **Connection:** reconnect automatically
- **Notifications:** forward notifications; include system notifications; forward from all apps (minus muted
  apps) or from selected apps only. The app lists show every app that sent a notification recently, even
  filtered ones, and you can type in apps that haven't sent one yet.
- **Weather:** on/off, location, units (°C / °F), update interval
- **Health:** automatic sync on/off, sync interval, how far back the first sync reaches (1–30 days)
- **Watch display:** 24-hour clock, date format
- **Forget watch:** removes the pairing keys and the Bluetooth bond

## Troubleshooting

**Stuck at "Opening the watch connection".** The Bluetooth pairing worked, but the Huawei data channel did not
open. Make sure the watch is close by and on its pairing screen, then forget it on the phone and pair again.

**The watch keeps showing "pairing" and then fails.** Factory-reset the watch, forget it on the phone, and
pair again from the app.

**"WatchBridge service is not responding".** Restart the service:
`systemctl --user restart harbour-watchbridge`.

**Logs.** For a bug report, run the service in the foreground with protocol logging and attach the output:

```bash
systemctl --user stop harbour-watchbridge
harbour-watchbridge-daemon -v 2>&1 | tee /tmp/watchbridge.log
```

Stop it with Ctrl+C, then start the service again. The log contains your watch's Bluetooth address and
serial number; remove them before posting if you prefer.

## How it works

```
┌────────────── QML / Silica UI (sailfish-qml, no compilation) ──────────────┐
│ MainPage · PairPage · PairingProgressPage · SettingsPage · LocationPage    │
└──────────────────────── Nemo.DBus, session bus ────────────────────────────┘
                     harbour.watchbridge  /harbour/watchbridge
┌──────────────── watchbridge daemon (Python 3, systemd user service) ───────┐
│ service.py        D-Bus API, reconnect logic, weather scheduler            │
│ bluez.py          discovery, pairing, BlueZ Profile1 connection            │
│ rfcomm.py         own SDP lookup + RFCOMM socket (fallback, like Android)  │
│ notifications.py  org.freedesktop.Notifications monitor (BecomeMonitor)    │
│ weather.py        Open-Meteo client, WMO → Huawei icon mapping             │
│ huawei/           protocol port of Gadgetbridge:                           │
│   packet.py tlv.py crypto.py aes.py   framing, slicing, CRC16, AES-CBC/GCM │
│   hichain.py                          HiChain ISO auth + bind              │
│   commands.py                         DeviceConfig/Notifications/Weather   │
│   device.py                           auth flow, init, async events        │
└────────────────────────────────────────────────────────────────────────────┘
```

- The GT 5 speaks over **Bluetooth Classic RFCOMM**; Bluetooth LE is not used. Its service UUID is
  `82FF3820-8411-400C-B85A-55BDB32CF060`.
- The daemon first asks BlueZ to connect through a registered client profile. BlueZ only knows the services
  it found while pairing, and it misses Huawei's, so the daemon falls back to its own SDP search and a plain
  RFCOMM socket. This is the same thing Android's `createRfcommSocketToServiceRecord` does.
- **Connection sequence** (mirrors Gadgetbridge's `HuaweiSupportProvider`):
  `LinkParams → DeviceStatus → SecurityNegotiation → PinCode → HiChain auth (first pairing only) → HiChain bind
  → ProductInfo → Time → Battery → SupportedServices/Commands → ExpandCapability`, followed by account,
  agreements, set-up-device status, notification, time-zone, language and date-format settings.
- **No crypto library needed:** AES-CBC and AES-GCM are implemented in pure Python (`huawei/aes.py`),
  because Sailfish OS ships no Python crypto library. The code is checked against the FIPS-197 and GCM test
  vectors.

## Building

There is no compiled code, so plain `rpmbuild` works on any RPM-based Linux. On Windows, a WSL Fedora distro
works (`dnf install rpm-build bzip2 tar`).

```bash
sh tools/build-rpm.sh        # -> RPMS/noarch/harbour-watchbridge-<version>-<release>.noarch.rpm
```

The Sailfish SDK works too (`sfdk build`). To regenerate the icons, run `python3 tools/make_icons.py`.

**Phone-side dependencies:** `python3-base`, `dbus-python3`, `python3-gobject`, `bluez5`,
`sailfishsilica-qt5`, `nemo-qml-plugin-dbus-qt5`, `nemo-qml-plugin-notifications-qt5`,
`qt5-qtdeclarative-import-positioning`.

## Development

The daemon runs straight from the source tree, so you can try a change on the phone without building an RPM.
Over SSH (Developer mode → Remote connection):

```bash
scp -r daemon/watchbridge defaultuser@<phone-ip>:wb-dev/
ssh defaultuser@<phone-ip>
systemctl --user stop harbour-watchbridge
cd ~/wb-dev && PYTHONPATH=$HOME/wb-dev python3 -m watchbridge -v
```

## Tests

The tests run on any desktop with Python 3.8 or newer. They cover the protocol against Gadgetbridge's packet
vectors and against a simulated watch (`tests/fake_watch.py`), which implements the watch side of HiChain
auth/bind, setup, notifications and weather. Real-watch quirks such as NUL-terminated JSON and delayed
confirmations are included.

```bash
python3 -m unittest discover -s tests
```

`tools/smoke-daemon.sh` starts the daemon on a private D-Bus session and calls every method the UI uses
(Linux, needs `dbus-python` and `pygobject`):

```bash
dbus-run-session -- sh tools/smoke-daemon.sh "$PWD"
```

## Not (yet) ported

Detailed sleep (TruSleep), stress and ECG, which the watch sends as files; SpO2, HRV and skin temperature from the
newer "data dictionary" sync; workouts with GPS tracks; music control, call control, alarms, watchface and
app installation, OTA updates and canned replies. Gadgetbridge supports all of these, and they can be built on
top of `huawei/device.py`. Contributions are welcome.

Honor watches that use the PAKE/STS handshake are not supported.

## Credits

This app would not exist without **[Gadgetbridge](https://gadgetbridge.org)**. Its Huawei developers,
among them Damien Gaignon, Martin.JM, José Rebelo and Vitalii Tomin, reverse-engineered the watch protocol
over years of careful work: the framing, the encryption, HiChain pairing, and every notification and weather
packet. All of the protocol code in `daemon/watchbridge/huawei/` is a Python translation of their Java code.
If WatchBridge is useful to you, please consider supporting Gadgetbridge. See [NOTICE.md](NOTICE.md) for which
files come from where.

Weather data by [Open-Meteo.com](https://open-meteo.com) (CC BY 4.0).

## How this project was made

The code was written with **[Claude](https://claude.ai)**, Anthropic's AI assistant, using Claude Code. Claude
translated Gadgetbridge's Huawei protocol from Java to Python and wrote the Sailfish OS app, the tests and this
documentation. Pairing problems were debugged live over SSH on a real phone and watch. The result was then tested
on that hardware. Please review the code with that in mind, and report anything that looks wrong.

## License

[AGPL-3.0-or-later](LICENSE), the same licence as Gadgetbridge. If you distribute a modified version, you must
publish its source code under the same licence.

WatchBridge is an independent project and is not affiliated with or endorsed by Gadgetbridge, Huawei or Jolla.
Huawei and Watch GT are trademarks of Huawei Technologies Co., Ltd., and Sailfish OS is a trademark of Jolla Ltd.
