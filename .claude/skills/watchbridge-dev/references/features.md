# Features on the watch: protocol notes

What was learned per feature on the Watch GT 5 (firmware 6.0.0.23). Read the section before changing that feature.

## Watch faces

- **Package (`.hwt`):** a zip with `description.xml` (`title`, `author`, `version`, `screen`, e.g. HWHD09
  = 466×466), `preview/cover.jpg` and `com.huawei.watchface`. That is either a zip with `watchface.bin`
  (newer faces) or the binary itself (older faces). Detect by content, not by extension (".hwf").
- **On the GT 5 (fw 6.0.0.23)** the whole flow works: 0x27/0x01 params (466×466, max version 2.9, others
  2.1–2.8), list (0x27/0x02), names (0x27/0x06, only downloaded faces have names), upload, install
  confirm (0x27/0x05, report type 2 = activate), activate and delete (0x27/0x03). The watch checks the
  file's SHA-256, so "done" means the bytes arrived intact.
- **A face that installs but looks garbled is a file problem**, not a transfer problem. Example: a face
  made for the Huawei Watch 4 (`…watch4….hwt`, raw binary inside), garbled as version 1.0.0 and 2.1.0.
  Ask for a face made for the GT 4/GT 5 before debugging the protocol.
- **HarmonyOS 6.1 (and late 6.0, after 6.0.0.328) signs face uploads** with a server-side RSA
  `contentSign` (Gadgetbridge #6005, #6199). There, installs fail for every face and cannot be fixed
  client-side. Check the watch firmware first when an install "completes but nothing appears".
- The watch cannot send face pictures. The start page shows the current face only if WatchBridge
  installed it and kept its preview (`~/.local/share/harbour-watchbridge/faces/<id>.jpg`).
- Try a face under another version without rebuilding: D-Bus
  `InstallWatchfaceVersion(path, "2.9.0")`. Delete one: `DeleteWatchface(id, version)` (ids from
  `GetStatus` → `watchfaces.list`). The current face cannot be deleted; activate another one first.

## Calendar on the watch

Gate: 0x34/0x01 and expand bit 171, and not bit 184 (Huawei's own calendar service, which Gadgetbridge cannot
sync). Verified on the GT 5 (fw 6.0.0.23), which has 171 and not 184:

1. Ping (from `com.huawei.health` to `in.huawei.calendar`), the app answers code 0xCA, then data `01 01 01 01`.
2. The app sends data: mode 2, major, minor, up to 500 events, 35 days. Ack it with 0xCF.
3. Upload a file of type 7 over 0x28 with the package tags 0x08..0x0C. No 0x27/0x05 confirm follows.

- **A watch with no version sends 64 zero bytes as major.** Java's `trim()` strips those, Python's `strip()`
  does not (`_JAVA_TRIM`). Sent back, the watch stored them as its version.
- The `minor` the watch reports afterwards is Gadgetbridge's odd sum (60 events: 10×1 + … + 10×6 = 210).
- What the watch holds is only known per connection. After a reconnect with a version, an 80-byte empty file
  clears it, it asks again with version 0, and everything goes over (seen on the real watch, about 2 s for 60
  events, 24 KB). `_cleared` stops this repeating if a watch keeps its version.
- Deviation from Gadgetbridge: with more changes than the watch takes, send everything instead of cutting off,
  so `last` stays true.
- Switching sync off answers 7 and leaves the events on the watch, as Gadgetbridge does.
- Sailfish announces no calendar changes, so `CALENDAR_REFRESH` compares every 30 minutes.
- Other apps talk over 0x34 too (a battery JSON arrives from another package); they are ignored by source.

## Alarms and watch settings (0.8)

- **Alarms** (`huawei/alarms.py`, service 0x08): the watch keeps up to five event alarms. The phone always
  sends the whole list (0x08/0x01, indexes 1..5), which replaces the watch's; an empty list is sent as one
  entry with only index 1, which switches them all off (Gadgetbridge does the same). The list is read with
  0x08/0x03 at every connection and after each change (verified on the GT 5: two alarms, repeat 0x1f and
  0x20). Repeat bits: Monday = bit 0 ... Sunday = bit 6, 0 = once. The GT 5 lacks 0x08/0x02, so there is
  no smart alarm. Alarms changed on the watch itself are not announced; they show after the next read.
- **Settings sent to the watch** (`device._apply_settings`): profile (0x07/0x02), move reminder (0x07/0x07),
  automatic SpO2 (0x07/0x24, no answer) and low SpO2 alert (0x07/0x25, no answer). Each is sent at connect
  and right after it changes, but only once it has been set in WatchBridge: `None` (or an empty profile)
  means "leave the watch's own setting alone". The GT 5 does not list 0x07/0x02 because it is not in our
  list of commands to ask about; Gadgetbridge sends it to every watch, and the answer is logged.
- **Do not disturb** is not offered: the GT 5 does not list 0x01/0x0a.
- Java widths matter in these packets: `(byte)` casts for height, weight and age, `int` for the birthday
  (`year << 16 | month << 8 | day`) and the precision weight (kg × 100), `Math.round` (halves up) for the
  stride factors. `tests/test_watch_settings.py` pins the bytes.

## Battery

- The GT 5 does **not** send 0x01/0x27 battery changes (in two days connected, the level only changed at
  reconnects). The service polls 0x01/0x08 every 15 minutes while connected, like Gadgetbridge's
  optional battery polling.
- Charging start and stop come over P2P from `com.huawei.BatteryEventMgr` as JSON (`type: battery`,
  `chargingStatus`, `powerValue`, Gadgetbridge `HuaweiP2PBatteryService`). Ping and data are acked with
  0xCF. `status.batteryCharging` follows it; no low-battery warning while charging.

## Power saving, do not disturb, heart-rate mode (0.9.0-4)

- **Phone state** (`phonestate.py`): battery saver from mce (`get_psm_state`, system-bus signal
  `psm_state_ind`, in mce's powersavemode.so); do not disturb is the dconf key `/lipstick/do_not_disturb`
  (the status bar's moon). dconf announces changes as session-bus `ca.desrt.dconf.Writer.Notify` with the
  full key as prefix and `[""]` as changes (checked on the phone with a test key).
- **Power saving** (`power_save.mode` phone|always|off): the existing timers keep running and skip work
  (`_saving()`); weather is rescheduled when it changes. Quick reconnect retries stay; the 10-minute ones
  become 30.
- **Do not disturb** is done on the phone: the GT 5 lacks 0x01/0x0a (and lift-to-wake 0x01/0x09).
  Notifications are dropped (counted in `status.phone.held`), not queued.
- **Heart-rate mode**: the protocol has no interval. 0x07/0x17 = continuous "smart" mode (measures less
  often at rest), 0x07/0x1c = real-time mode (Gadgetbridge sends one or the other). For "smart" we send
  0x1c off first, then 0x17 on, to leave a real-time mode chosen on the watch. Not yet tried on the GT 5.
- Move reminder intervals above 120 min (180) are not known to be accepted; `_confirm` logs the answer.

## Day and night watch faces (0.9)

- `faceschedule.py` decides; `service._arm_face_timer` wakes once at the next switch (at most an hour
  ahead, so clock changes are caught) and `_check_face_schedule` also runs after each face list and on
  settings changes. Each period (day or night, identified by when it began) is applied once, so a face
  the user picks on the watch stays until the next switch; a settings change applies at once.
- Faces are identified by `file`; the version activated is the one the watch reports now. A chosen face
  that was deleted from the watch is skipped (logged).
- Built-in faces have no names from the watch; the UI numbers them in the watch's order.

## Health views

- `HealthStore.daily(lo, hi)` is the one per-day calculation; `daily.csv`, the month and the week overview
  (`range_summary`, `month_summary`, `week_summary`) all use it. A night counts for the day it ends on.
- Battery levels go to the `battery` table in `health.sqlite` when they change (an unchanged level at most
  every 30 minutes); `GetBatteryHistory(days)` feeds `BatteryPage.qml`.
- The low-battery notification is posted with app name `WatchBridge`, which `NotificationMonitor` skips,
  so it is not forwarded back to the watch. Once per discharge; it re-arms 3 % above the threshold.
