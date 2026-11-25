---
name: watchbridge-dev
description: Development workflow for WatchBridge (harbour-watchbridge), the Sailfish OS companion app for the Huawei Watch GT 5 whose watch protocol is ported from Gadgetbridge. Use it for any work in this repository - building and checking a release (tools/check.sh), running the tests, trying a change on the phone over SSH, reading daemon logs, and especially when the user reports a symptom from the phone or watch ("stuck at Opening the watch connection", "pairing fails", "the watch still shows pairing", "no notifications on the watch", "Starting WatchBridge service forever", weather not showing, calls or caller names not on the watch, "contact helper failed", a notification not cleared from the watch, a watch face that will not install or looks garbled, alarms not showing or not changing, charts empty or in the wrong colour, the week or month overview empty, no sound when finding the phone). Also use it when porting more Gadgetbridge features, touching Sailfish system services (calls, contacts, notifications, calendar, sailjail, ngfd), changing the cover or other UI, bumping the version, or preparing a release.
---

# WatchBridge development

WatchBridge is a Python daemon (dbus-python + GLib, systemd user service, session D-Bus name
`harbour.watchbridge`) plus a QML/Silica UI run by `sailfish-qml`. The watch protocol in
`daemon/watchbridge/huawei/` is a translation of Gadgetbridge's Huawei support. Nothing is compiled; the
RPM is `noarch`.

The single most useful habit on this project: **when something fails on the real watch, get the
daemon's debug log from the phone and compare the bytes and the sequence with Gadgetbridge before
guessing.** Every real protocol bug so far was found that way, and the simulated watch in the tests had
passed every time. The simulator only knows what we told it. For UI problems, ask for a **screenshot**
(volume up + down on the phone saves it to `~/Pictures/Screenshots`, which you can `scp`): the QML bugs
in this project were all invisible to `qmllint` and obvious in a screenshot.

## The loop for every change

1. Change the code. A real-watch bug also gets a test, ideally by teaching `tests/fake_watch.py` the
   behaviour that exposed it.
2. Bump `Release:` (fix) or `Version:` (new feature, `Release: 1`) in `rpm/harbour-watchbridge.spec` and
   add a `%changelog` entry. The phone only upgrades to a higher version-release.
3. Run every check and build the RPM in one go (from Windows, through WSL):

   ```
   wsl -d FedoraLinux-44 --cd <repo> -- sh tools/check.sh --rpm
   ```

   One line per check: unit tests, Python 3.8 syntax, QML syntax plus an ES6 scan, the D-Bus smoke test,
   untracked files (they would end up in the RPM), private data (LAN addresses, real Bluetooth addresses,
   `config.json`). Output of a failing check is shown; the RPM is built only when everything passed.
   A new script or file is reported as untracked until it is committed, so commit before the final run.
4. Commit, tag `v<version>-<release>`, and copy the RPM to the phone (see *Releasing*). Give the user the
   install command; never run `devel-su` for them.
5. Tell the user plainly what was verified where: off-device checks, on the real watch, or not at all.
   Ask them to look at changed screens.

For details per area, read the matching reference file in this skill's folder first:

| File | When |
|---|---|
| `references/sailfish-services.md` | Calls, contacts (sailjail), notifications, the calendar data service, find my phone (ngfd) |
| `references/features.md` | Watch faces, calendar on the watch, alarms and watch settings, health views and battery |
| `references/VLI-B19-6.0.0.23.txt` | The GT 5's supported commands, expand capabilities, and what each feature did on it |
| `scripts/btinfo.py` | BlueZ state of the watch on the phone (see *Trying changes on the phone*) |

## Map of the code

| Path | What it does |
|---|---|
| `daemon/watchbridge/service.py` | D-Bus API for the UI, connect/reconnect logic, pairing state, weather scheduler, alarms and battery glue |
| `daemon/watchbridge/bluez.py` | Discovery, `Device1.Pair`, BlueZ `Profile1` connection, falls back to `rfcomm.py` |
| `daemon/watchbridge/rfcomm.py` | Own SDP search by UUID + RFCOMM socket (native or via libc), like Android |
| `daemon/watchbridge/notifications.py` | Watches `Notify` calls on the session bus, filters (mute/allow lists, system, duplicates); learns lipstick's notification ids from its replies and reports `NotificationClosed` (dismiss sync) and missed-call notifications |
| `daemon/watchbridge/calls.py` | Follows calls through `org.nemomobile.voicecall`; `CallTracker` turns status changes into incoming / answered / ended |
| `daemon/watchbridge/findphone.py` | Find my phone: ring and notification, safe against late D-Bus replies (`PhoneRinger`) |
| `daemon/watchbridge/contacts.py` | Caller names: runs the sandboxed helper, keeps number → name in memory only |
| `data/contact-names`, `data/harbour-watchbridge-contacts.desktop` | The helper (installed to `/usr/libexec/harbour-watchbridge/`) and its sailjail profile (`Contacts;Privileged`) |
| `daemon/watchbridge/phonecalendar.py` | Reads events from `calendardataservice` (not named `calendar.py`: that would shadow the stdlib module) |
| `daemon/watchbridge/weather.py` | Open-Meteo client and WMO-to-Huawei icon mapping |
| `daemon/watchbridge/health.py` | Health store: `~/Documents/WatchBridge/health.sqlite` + CSV; day, week and month summaries; battery history |
| `daemon/watchbridge/config.py` | `~/.config/harbour-watchbridge/config.json`; `public()` hides the pairing secrets |
| `daemon/watchbridge/huawei/device.py` | Handshake, setup sequence, async packets, sending; alarms and watch settings (`_apply_settings`) |
| `daemon/watchbridge/huawei/hichain.py` | HiChain auth (first pairing) and bind (every connection) |
| `daemon/watchbridge/huawei/{packet,tlv,crypto,aes,commands}.py` | Framing, TLV, crypto, packet builders |
| `daemon/watchbridge/huawei/fitness.py` | FitnessData 0x07: totals, per-minute activity, basic sleep, heart-rate and SpO2 switches, profile, move reminder |
| `daemon/watchbridge/huawei/alarms.py` | Alarms 0x08: the event alarm list and replacing it |
| `daemon/watchbridge/huawei/filedownload.py` | File download over 0x2C; `device._download_file` drives it |
| `daemon/watchbridge/huawei/healthfiles.py` | Parsers: TruSleep sequence data (summary + stages), stress (RRI) files |
| `daemon/watchbridge/huawei/{p2p,p2pcalendar}.py` | P2P messages (0x34); calendar requests, JSON file and what the watch holds (`CalendarSync`) |
| `daemon/watchbridge/huawei/watchface.py` | `.hwt` packages, watch-face service 0x27, file upload 0x28 as a pure state machine (`Upload`) |
| `qml/components/Daemon.qml` | Wraps the D-Bus API; also the ring colours (`ringColors`, from the ambience or classic) |
| `qml/components/{ChartCanvas,ActivityRings,MonthBars,DayValues,TimeAxis}.qml` | Charts: every chart is a `ChartCanvas`; goal rings; one bar per day; per-day labels; axis labels |
| `qml/pages/HealthPage.qml`, `MonthPage.qml` | Day view; week and month overview (one page, `mode`) |
| `qml/pages/AlarmsPage.qml`, `AlarmDialog.qml`, `BatteryPage.qml` | Alarms on the watch; watch battery history |
| `qml/pages/WatchfacesPage.qml`, `InstallWatchfaceDialog.qml`, `cover/CoverPage.qml` | Faces; the cover (with `components/CoverInfo.qml`) |
| `tests/fake_watch.py` | Simulated watch (handshake, health, files, faces, calendar, alarms) used by most tests |
| `tests/test_watch_settings.py` | Alarm, profile, reminder and SpO2 packets; battery warning and history |
| `tools/check.sh`, `tools/smoke-daemon.sh`, `tools/build-rpm.sh` | All checks; the D-Bus smoke test; packaging (`rpm/harbour-watchbridge.spec`) |
| `NOTICE.md` | Which file was ported from which Gadgetbridge file, and its authors |
## Gadgetbridge is the reference

Keep a sparse checkout of Gadgetbridge outside the repo (for example in the scratchpad), at the
commit named in `NOTICE.md` or newer:

```
git clone --depth 1 --filter=blob:none --sparse https://codeberg.org/Freeyourgadget/Gadgetbridge.git gb
git -C gb sparse-checkout set app/src/main/java/nodomain/freeyourgadget/gadgetbridge app/src/test
```

`app/src/test` holds Gadgetbridge's unit tests; the packet vectors in `tests/test_protocol.py` come from
there.

Before promising a feature, check that it is really part of the *Huawei* support. Much of
Gadgetbridge is generic or belongs to other brands. Huawei features are often shaped differently from
what their names suggest: "do not disturb", for example, is a schedule on the watch, not an on/off
mirror of the phone.

Where to look, under `app/src/main/java/nodomain/freeyourgadget/gadgetbridge/`:

- `service/devices/huawei/HuaweiSupportProvider.java`: the connect sequence (`initializeDevice*`),
  `initializeDeviceConfigure()` and `initializeDynamicServices()`, which list every setup request in order.
- `service/devices/huawei/requests/*.java`: one class per request, with `requestSupported()` saying when
  it is sent.
- `devices/huawei/packets/*.java`: packet layouts. `devices/huawei/HuaweiState.java`: which supported
  command or expand-capability bit gates each feature.
- `service/devices/huawei/AsynchronousResponse.java`: what the watch sends unprompted and what
  Gadgetbridge answers.

Details that are easy to get wrong when porting:

- **Timeouts.** A Gadgetbridge request has *no* timeout unless it calls `setupTimeoutUntilNext()`, and the
  timeout applies to that request only, not the steps that follow. Copying a short timeout onto every
  step broke first pairing, because the watch waits for the user to tap the checkmark.
- **org.json is lenient.** It ignores trailing bytes after a JSON object, and the watch NUL-terminates its
  HiChain JSON. Python needs `json.JSONDecoder().raw_decode()`.
- **Java bytes are signed.** Mirror `getByte()` with a signed read where the value is compared or XORed.
- **Status codes:** tag `0x7F` in a reply is the result. `0x000186A0` (100000) means success, anything
  else is an error code.
- **`addToResponse = false`.** Such requests get no answer (e.g. `StopNotificationRequest`, the 0x28
  upload steps). Send them with `_send`, not `request`, or the worker waits for a timeout.
- **Flows the watch drives.** For the file upload (0x28) the *watch* sends the next step (hash request,
  consult, "next chunk", result), and Gadgetbridge answers in `AsynchronousResponse`. In WatchBridge such
  packets bypass the request waiter in `_dispatch` and go to a queue for a dedicated thread, like the
  0x2C download blocks. Raw (non-TLV) bodies: `Packet.raw_packet()`; encrypted, they become an
  encryption TLV around the raw bytes. Incoming raw services are listed in `packet._RAW_PAYLOADS`.
- **Sending from two threads.** Calls go out from the GLib main thread (a call cannot wait behind a
  health sync on the worker). `_send` serialises *and* encrypts under `_send_lock`, and `_next_msg_id`
  has its own lock; keep it that way.
- **Gadgetbridge's defaults are not always right for the GT 5.** Example: it registers uploaded faces as
  version `1.0.0`, while the GT 5's own faces all carry a version from the list in 0x27/0x01 (2.1–2.9).
  When a ported default looks arbitrary, compare it with what the real watch reports.

**What the watch supports.** Gate every feature the way Gadgetbridge does, on the watch's supported
commands or expand-capability bits (`HuaweiState.java`), never on the model name. The daemon logs both
sets at connect time (`Supported commands:` and `Expand capabilities:`). The first time you see them for
a watch and firmware, save them to `references/<model>-<firmware>.txt` in this skill's folder, so later
feature work can be planned without the phone.

**Licence notices.** When you port more Gadgetbridge code, keep its copyright line in the target file's
header with a "Translated to Python and modified for WatchBridge, <year>" note. In `NOTICE.md`, name every
Gadgetbridge source file you drew from, and add any authors not listed yet. This applies even when the
code lands in a file that already has a row. The project is AGPL-3.0-or-later because of this code, and
those notices are what the licence requires.

## Build and test on the PC

`tools/check.sh` (above) runs everything. The pieces, for when one needs a closer look:

- **Unit tests:** `python -m unittest discover -s tests` (Windows Python works too). Every change keeps
  them passing.
- **Python version:** the phone runs Python 3.11 on Sailfish OS 5.2. The daemon must still parse as
  Python 3.8 for older releases (`ast.parse(..., feature_version=(3, 8))`).
- **D-Bus smoke test:** `dbus-run-session -- sh tools/smoke-daemon.sh "$PWD"` starts the daemon on a
  private bus and calls every method the UI uses. New D-Bus methods belong in its method list. Errors
  saying BlueZ or voicecall is not available are expected. Its `call` helper always exits 0 through the
  pipe, so it looks at the output.
- **QML:** `qmllint` (Fedora `qt5-qtdeclarative-devel`) checks syntax only. It does not know Silica, does
  not run JavaScript, and missed every QML bug the user found; see *QML on Sailfish* and ask for a
  screenshot. The phone cannot run QML headless (`qmlscene` there has no offscreen graphics).
- **RPM:** `sh tools/build-rpm.sh` writes `RPMS/noarch/harbour-watchbridge-<version>-<release>.noarch.rpm`.
  It packs the working tree, untracked files included (but not `RPMS/`, `.git`, `__pycache__`).

**Windows host.** The Linux steps run in the WSL distro `FedoraLinux-44` (python3 with dbus and gi,
rpm-build, dbus-run-session, qmllint, git). `wsl -d FedoraLinux-44 --cd <Windows path> -- sh tools/check.sh`.
`.gitattributes` keeps shell scripts LF, so no `tr -d '\r'` is needed any more. Git in WSL needs
`-c safe.directory=<repo>` for a Windows checkout; `check.sh` does that itself.

Shell gotchas on this host:

- Inside `wsl ... -- sh -c '...'` from PowerShell, `$var` and `"..."` get mangled: put the logic in a
  script file and pass file names as arguments.
- PowerShell has no `<` redirection. Pipe a local script to the phone with
  `Get-Content -Raw script.py | ssh … 'python3 -'`, or use a quoted heredoc inside the ssh command.
- The phone has no `timeout` command: background a process and `kill` it after `sleep`.
- `python -I`, used for untrusted files such as a user's `.hwt`, ignores `PYTHONIOENCODING`. Call
  `sys.stdout.reconfigure(encoding="utf-8")` in the script.
- Put downloaded or user files in a new, empty scratch folder and only read them, never run anything
  from them.
## Trying changes on the phone

Ask the user to enable *Settings → Developer tools → Remote connection* and to install your SSH key.
They type the phone's password themselves; never type passwords for them. Then:

- **SSH user:** `defaultuser`.
- **No journal access:** `defaultuser` cannot read `journalctl`, so instead of reading the service's log,
  run a copy of the daemon yourself with debug logging.
- **No root:** installing an RPM needs `devel-su` and the root password. Give the user the install
  command rather than running it.

The single-quoted remote commands below work the same from PowerShell and from bash.

**First, find out what is installed and running.** Two daemons running at once (for example a forgotten
dev copy next to the service) cause confusing symptoms:

```
ssh defaultuser@<phone-ip> 'rpm -q harbour-watchbridge; pgrep -af watchbridge; systemctl --user show -p ActiveState,MainPID,NRestarts harbour-watchbridge'
```

Run the `systemctl` part twice, a minute apart. If `MainPID` changes or `NRestarts` grows, the daemon is
crashing; that is a different problem from the watch dropping the link.

**Run the working-tree daemon on the phone, without building an RPM.** This replaces the installed
daemon with whatever is in your working tree. To reproduce a released version, check out its tag
first.

```
ssh defaultuser@<phone-ip> 'systemctl --user stop harbour-watchbridge; pkill -f "^python3 -m watchbridge"; rm -rf ~/wb-dev; mkdir -p ~/wb-dev'
scp -r daemon/watchbridge defaultuser@<phone-ip>:wb-dev/
ssh defaultuser@<phone-ip> 'find ~/wb-dev -name __pycache__ -prune -exec rm -rf {} +; cd ~/wb-dev && PYTHONPATH=$HOME/wb-dev setsid nohup python3 -m watchbridge -v > /tmp/wb.log 2>&1 < /dev/null &'
```

The daemon reconnects to the saved watch within seconds.

**Debug the *installed* code instead** (no copy, same version as the RPM): stop the service and run
`cd /tmp && PYTHONPATH=/usr/share/harbour-watchbridge/daemon setsid nohup python3 -m watchbridge -v > /tmp/wb.log 2>&1 < /dev/null &`.
This is the quickest way to watch a user's test (calls, buttons, uploads) on the real watch.

**While a debug copy runs, the user must not install an RPM and restart the service.** The restart
fails (`ActiveState=failed`) because the copy holds the bus name, and the old code keeps answering. If
the user moves on to other work during a test, put the phone back to normal first. Check before every
test with `rpm -q` and `GetStatus` → `daemonVersion`.

**Reading the log.**

- **Overview:** `ssh defaultuser@<phone-ip> 'grep -E "INFO|WARN|ERROR" /tmp/wb.log | tail -60'`
- **Connection lifecycle only:**
  `grep -nE "State:|RFCOMM connection|ConnectProfile|Socket closed|Timeout waiting|setup failed|Reconnecting in|Disconnection requested|Services BlueZ knows"`
- **Bytes:** read the full log, including `>>`/`<<` packet hex and `Async packet` lines.

The timestamps carry most of the information. Note how long a connection stays up, which side ends it
(`Socket closed` means the watch or BlueZ hung up, `setup failed` means the daemon gave up), and what was
sent or received just before.

**Daemon states vs. what the user reports.** `status.state` goes through `pairing` → `connecting` →
`authenticating` → `initializing` → `connected`, or ends in `disconnected` or `auth_failed`. The UI turns
these into "Pairing over Bluetooth…", "Connecting…", "Authenticating…", "Setting up the watch…" and
"Connected". On the pairing screen, `connecting` shows as the step "Opening the watch connection".
Users often say "connecting" for any of the in-between states.

**Which settings reach the watch when.** `_watch_settings()` in `service.py` is what the watch object
gets. Time format, date format and language are sent at the next connection only. Continuous heart
rate, the profile, the move reminder and SpO2 are sent at connect *and* right after they change
(`device.apply_settings`), but only once the user has set them in WatchBridge: `None` means "leave the
watch's own setting alone". Follow that pattern for new settings, so installing WatchBridge never
silently changes what the user set on the watch.

**Phone state.** For features that send phone state to the watch, find where Sailfish keeps it by
watching it change. Run `dconf dump /` before and after the user toggles the setting, or use
`dbus-monitor` on the session or system bus. Don't guess keys.

**Other checks on the phone:**

- **Status:** `ssh defaultuser@<phone-ip> 'dbus-send --session --print-reply --dest=harbour.watchbridge /harbour/watchbridge harbour.watchbridge.Daemon.GetStatus'`
- **Bluetooth state:** `ssh defaultuser@<phone-ip> 'python3 -' < .claude/skills/watchbridge-dev/scripts/btinfo.py`.
  Check Paired/Bonded/Trusted/Connected and whether BlueZ knows the Huawei UUID.
- **Test notification:** call `...Daemon.SendTestNotification` the same way, and ask the user what the
  watch showed.
- **Calls, caller names, faces, missed calls:** all in `GetStatus` (`calls.names`, `calls.nameCount`,
  `calls.namesError`, `calls.missed`, `watchfaces.list`, `watchfaces.upload`). Decode it on the phone with
  `… | grep -o '"watchfaces": {.*' | python3 -c '…json.JSONDecoder().raw_decode(…)…'`.
  `RefreshWatchfaces` re-reads the list from the watch.
- **Things only the user can do:** make a real call from another phone, press watch buttons, look at the
  watch. Start the debug daemon first, give a numbered list of steps, and read the log when they say
  "done".

QML changes can't be run on the PC, so ask the user to open the changed screen on the phone and say
what they see.

**When you're done, put the phone back to normal, even if the session is interrupted.** A dev copy left
running keeps the bus name, so the installed service fails to start and the user silently runs old code
(this happened once, and the new allow-list "did not work at all"). Stop the dev copy
(`pkill -f "^python3 -m watchbridge"`), delete `~/wb-dev` and `/tmp/wb.log`, and run
`systemctl --user reset-failed harbour-watchbridge; systemctl --user start harbour-watchbridge`. Check
that `pgrep -af watchbridge` shows only `/usr/bin/python3 -m watchbridge`. Then remind the user that the
installed RPM still has the old code until they install the new one.

**Version check.** The packaged daemon and About page carry the exact version, which the spec stamps in
at build time. A dev copy reports `<version>-dev` (`__init__.py` and `AboutPage.qml`; bump both
markers with `Version:`). `GetStatus` returns `daemonVersion`, so you can confirm
which code is answering without asking the user.

## Symptom → cause

These are from real sessions with a Watch GT 5 (firmware 6.0.0.23) on Sailfish OS 5.2. Start from the
log, not from this table. The table tells you where to look first.

| What the user sees / the log shows | Look at |
|---|---|
| UI stuck on "Starting WatchBridge service…" | Daemon is running but lost its bus name. `service.py` must keep the `BusName` object referenced. Test it with the `GetStatus` call above. |
| A new feature "does not work at all" after an update; service `ActiveState=failed` | An old daemon still owns `harbour.watchbridge`, usually a forgotten dev copy (`pgrep -af watchbridge` shows `python3 -m watchbridge -v`), so the installed service exits at start. The About page shows the mismatch: the service version differs from the app's, or reads "older than 0.1.0-7". Kill the old daemon, `systemctl --user reset-failed harbour-watchbridge`, then start the service. |
| Stuck at "Opening the watch connection" | RFCOMM channel never opened. Log line "Services BlueZ knows: none" means BlueZ missed the Huawei UUID, so the direct path in `rfcomm.py` must take over. |
| Lost connection comes back only after the user taps Disconnect, then Connect | BlueZ still held the dropped profile connection, and `ConnectProfile` answered `AlreadyConnected`, which was ignored, so no socket ever arrived. Since 0.6.0-7, every `_connect()` and every dropped link calls `DisconnectProfile` first, and `AlreadyConnected` falls back to the direct connection. |
| Weather section empty, no error shown, "Push weather" does nothing | Before 0.6.0-8, a failed download's `except ... as e` handler passed `str(e)` in a lambda to `GLib.idle_add`. Python unbinds `e` when the except block ends, so the lambda raised NameError and `_weather_busy` stayed True until a restart. Never reference the exception variable inside a deferred lambda; copy it to a local first. The test stubs run `idle_add` immediately, which hides this, so queue the callbacks in tests. |
| `Device or resource busy` on reconnect | An old RFCOMM socket is still open. Sockets must be `shutdown()` before `close()`, otherwise the blocked reader thread keeps the channel. |
| `Host is down` / `Connection refused` | Watch out of range, asleep, or it reset its pairing. Retry later, or re-pair. |
| HiChain step error, `JSONDecodeError: Extra data` | NUL-terminated JSON from the watch (see above). |
| Handshake timeout during first pairing | The watch waits for the user's confirmation. Compare the timeouts with Gadgetbridge. |
| Phone says connected, but the watch still shows "pairing" and drops the link after ~20 s | The watch expects setup messages after connecting. Compare `_initialize_services()` with Gadgetbridge's `initializeDynamicServices()` (account, set-up-device status, connect status, …), including the `requestSupported()` gates, since a missing capability bit silently skips a step. |
| Connection flaps: connected, dropped, reconnected every 20–30 s | Check the timestamps first. Since 0.1.0-7 a late `ConnectProfile` error is ignored once `NewConnection` has delivered a socket, `_on_rfcomm` refuses a second socket while one is alive, and `ReconnectBackoff` only resets after a connection lasted 60 s. If it still flaps, the watch is closing the link: look at what was sent or received just before, and at async packets we never answer (`_handle_async`). |
| Watch disconnects once right after a successful first pairing, then reconnects | Normal: it is creating the permanent Bluetooth bond (Bonded goes 0 → 1). |
| Health sync works but no heart rate (log "minutes per field" has no `heart_rate`) | The watch's continuous measurement is off. The "Measure heart rate continuously" setting sends 0x07/0x17; only minutes recorded after that carry heart rate. |
| Health page shows "sleep" during the day, or none at night | Basic sleep messages: only types 0x06/0x07 are sleep, 0x01/0x03 on a GT 5 are walking. Real sleep comes from the TruSleep file (log "File sequence_data"); the night view prefers its stages. |
| "Health sync: sleep file failed" / "stress file failed" | Check the "File <name>: id, bytes" line. "no valid size" means the watch has no such data. "No data ... for N s" means the 0x2C/0x05 blocks stopped; compare with Gadgetbridge's HuaweiFileDownloadManager. Stress needs "RRI new sync" (SettingRelated bit 0x04) and automatic stress measurement on the watch. |
| Notification answered with `7f04000186a4` | The watch rejected or deferred it. Compare the packet with `SendNotificationRequest` and ask what the watch showed. Unresolved so far. |
| Settings → Calls: "Not available: The contact helper failed (1): no details" (newer builds: "sailjail refused to start it") | sailjail refused: the command is not an ELF binary or differs from the profile's Exec line. Run `sailjail -v -p harbour-watchbridge-contacts.desktop /usr/bin/python3 /usr/libexec/harbour-watchbridge/contact-names > /dev/null` and read its stderr. |
| "Cannot read the contacts: unable to open database file"; sailjail log "can't chdir to privileged" | The profile lacks `Privileged` next to `Contacts`. |
| Calls not shown on the watch | Log "Following phone calls (voice call manager)" at start, then "Call <id>: status 5" and "Incoming call shown on the watch". Calls switch off, watch not ready, or 0x02/0x01 unsupported in the log means it was skipped. |
| A notification dismissed on the phone stays on the watch | Expired banners (reason 1) are left on purpose. Otherwise check the "Remove from the watch when cleared on the phone" setting, expand bits 94/120, and a 0x02/0x06 in the log. A notification forwarded before the daemon started has no known id. |
| Calendar empty on the watch | `GetStatus` → `calendar` (supported, events, error) and the log lines "Calendar request", "Calendar: N events on the phone", "Calendar: sending N bytes". "did not ask for the calendar": no answer to the sync request, compare the P2P packets. "the watch holds N" with nothing shown: check the file's fields against `calendarEventToJson`. |
| Watch face installs ("done") but looks garbled or cannot be selected | The file does not suit the watch (made for another model), not the transfer. See *Watch faces*. |
| Watch face upload "completes" but nothing appears, or the watch refuses every face | Firmware with signed uploads (HarmonyOS 6.1+, possibly late 6.0). Check the firmware on the main page. Error 140004 = too many faces, 140008 = already installed, 140009 = no space. |
| Upload stops with "The watch stopped answering at N %" | 30 s without a 0x28 packet. Compare the step with `AsynchronousResponse.handleFileUpload`, and check whether chunk encryption matches the consult's `no_encrypt` (tag 9). |
| Alarms row on the main page empty, or alarm days never highlighted | `parent` inside a `BackgroundItem` (see *QML on Sailfish*). Data: `GetStatus` → `alarms` (`supported`, `list`, `error`). |
| Charts empty after switching back to the app | A plain `Canvas`: use `ChartCanvas` (repaints when the app becomes active). |
| A chart line or bars in the wrong colour, "most of the time" | A string colour on a Qt 5.6 Canvas (see *QML on Sailfish*). |
| Week or month overview empty when opened from another page | Loading during page creation, before `daemon` was set. Load from `Component.onCompleted`. |
| Stays disconnected / stuck at "Connecting" for hours | Since 0.9.0-3: retries settle at every 10 minutes (`RECONNECT_DELAYS`), and `_reconnect_watchdog` restarts attempts that hung (BlueZ "InProgress" with no socket, a stalled setup) or were never scheduled. It stays off after the user's Disconnect (`_user_disconnected`) and after `auth_failed` (needs pairing again). |
| Battery level stuck between connections | The GT 5 sends no 0x01/0x27 changes: the 15-minute poll (`BATTERY_POLL`) must be running. Check "Battery event from the watch" lines for charging. |
| Watch face does not change at the day/night time | Watch not connected at that moment (applies at the next connection), face deleted from the watch, or the period was already applied ("Face schedule:" log lines). |
| No sound when the watch looks for the phone | ngfd is on the system bus; see `references/sailfish-services.md`. |

A first pairing that fails leaves the watch without a pairing while BlueZ still lists it as paired. Have
the user forget the watch in Sailfish Bluetooth settings, put the watch on its pairing screen
(factory-reset it if it was ever paired elsewhere), and pair from the app again.


## QML on Sailfish (Qt 5.6)

- **JavaScript is ES5:** no arrow functions, `let`/`const`, template strings or `\u{...}` escapes.
- **Reserved word:** `signal` can't be used as an id, and `on` can't be a property name.
- **Pages opened with properties** (`pageStack.push(url, {...})`) get them in no fixed order, and their
  `on...Changed` handlers run during creation, possibly before `daemon` is set. Start loading from
  `Component.onCompleted` (MonthPage 0.8.2: a week opened from the day page stayed empty).
- **Ring and chart colours** come from `daemon.ringColors` (derived from the ambience, or classic).
- **`parent` inside a `BackgroundItem` or `ListItem`** is its `contentItem`, not the item itself. Its custom
  properties must be reached by id. A `parent.active` there was undefined, and the Alarms row on the main
  page showed no text (0.8.0-1). `qmllint` doesn't catch this.
- **Charts use `components/ChartCanvas.qml`, not `Canvas`.** Sailfish frees the window's graphics while the
  app is in the background, and a plain Canvas stays empty when the app comes back. ChartCanvas repaints
  when `Qt.application.active` turns true.
- **Canvas colours must be colour objects** (`Theme.rgba(c, a)`, `Qt.rgba(...)`, a `color` property),
  never strings. In Qt 5.6's `Context2D`, a string `strokeStyle`/`fillStyle` is skipped when it equals the
  remembered state, and a colour object for `strokeStyle` writes the remembered *fill* state. So after one
  object colour, a string colour stops applying from the second paint on. The heart-rate line was drawn in
  the grid's colour after every repaint until 0.6.0-11. Desktop Qt doesn't have this bug, so
  off-device renders won't show it.
- **D-Bus signals:** in `DBusInterface`, they are handled by lower-case functions named after the
  signal (`function statusChanged(json)`).
- **Lists that refresh:** `daemon.settings` is re-read every 30 s. Snapshot data a dialog is editing, or a
  list will rebuild and jump to the top under the user's finger.
- **`import QtQuick 2.0` hides newer properties:** for example `Column.topPadding` (2.6) is "not
  available" even on Qt 5.6. Use spacer `Item`s, or raise the import deliberately.
- **`clip` is rectangular:** a `Rectangle { radius; clip: true }` does not round its children. Use
  `components/RoundImage.qml` (QtGraphicalEffects `OpacityMask`; the spec `Requires:
  qt5-qtgraphicaleffects`).
- **File picker:** Sailfish's `FilePickerPage` always starts in the home folder sorted by name and
  remembers nothing; its folder pages are private. `pages/FacePickerPage.qml` is our own on the public
  `Nemo.FileManager` `FileModel` (path, `sortBy`, `sortOrder`, `nameFilters`, `parentPath()`), storing the
  last folder and sort order with `Nemo.Configuration` (`/apps/harbour-watchbridge/facePicker/*`). A
  picker pops itself, so store the path and open the next dialog in the page's `onStatusChanged` when
  `PageStatus.Active`.
- **Cover:** reload data in `onStatusChanged` when `status === Cover.Active` (covers are only drawn while
  visible). `ListItem.remorseDelete(fn)` gives the usual undo.
- **Canvas:** a thin anti-aliased line looks darker than a block of the same colour. Share one colour
  property, and draw lines ≥ 3 px with round joins.
- `tools/check.sh` scans the QML for `=>`, `let`, `const` and template strings (ES6, which fails only at
  runtime). The phone cannot run a headless QML check: its `qmlscene` has no offscreen graphics.

## UI decisions the user made

Keep these unless the user asks otherwise:

- **Main page, top to bottom:** the current watch face picture (when WatchBridge has its preview, else
  the drawn watch); **Health** (small goal rings, "… steps today", last sync); **Watch** (Watch faces;
  Alarms with the times of the alarms that are on); **Weather** (with Location and Push weather);
  **Watch details** at the bottom (model, firmware without the bracketed build suffix, battery opening the
  battery history, Bluetooth address). No Reconnect button: Connect and Disconnect are in the pull-down
  menu, and reconnecting releases the old connection by itself. The notification switch, counter, last
  notification and test button live in **Settings → Notifications**; "Sync time" in **Settings → Connection**.
- **Health page:** goal rings at the top (steps, distance, calories, sleep) with values and goals beside
  them; the pull-down has Week overview, Month overview, Open data folder, Sync now. The heart-rate line
  uses the same red as "Awake" (`#ff6b5e`, `alertColor`).
- **Colours:** rings, legends and the week/month bars use `daemon.ringColors`, derived from the
  ambience by default (Settings → Health → Ring colours, "Classic" keeps fixed colours). Alert red and
  Huawei's stress bands stay fixed.
- **Cover:** a small drawn watch *without* the battery number inside, then the status with the battery
  ("Connected · 87 %"), the latest missed call with the caller, steps, sleep duration (no score),
  "Heart rate … bpm" (no time) and the weather. Actions: refresh weather, sync health.
- **Watch faces page:** a visible delete button on every deletable face, besides the long-press menu.

## Releasing

**Version numbers.** Bump `Release:` for fixes. Bump `Version:` (and reset `Release:` to 1) for a new
user-visible feature, after asking the user whether they agree. History: 0.2 health sync, 0.3 TruSleep
and stress, 0.4 calls, caller names, dismiss sync and the cover, 0.5 watch faces, 0.6 calendar, find my
phone and reconnect fixes, 0.7 month overview, 0.8 alarms, profile, move reminder, SpO2 and battery,
0.8.1 week overview, 0.8.2 ambience colours. `git tag -l` lists every build that went to the phone, and
`git log v0.8.1-1..v0.8.2-1` answers "what changed?".

Steps: the loop at the top of this file, then:

1. Update the README status table if something was newly verified on a real watch.
2. Commit, and tag the commit `v<version>-<release>`.
3. Copy the RPM to the phone and give the user the install command:

   ```
   scp RPMS/noarch/harbour-watchbridge-<version>-<release>.noarch.rpm defaultuser@<phone-ip>:
   ```

   ```
   devel-su pkcon install-local ~/harbour-watchbridge-<version>-<release>.noarch.rpm
   ```

   The service restarts by itself on install. When the phone is unreachable (ssh times out), say so and
   give both commands. When a build replaces one the user has not installed yet, delete the older RPM on
   the phone (`rm ~/harbour-watchbridge-<old>.noarch.rpm`) so they cannot install the wrong one.
4. When the phone is reachable and the change touches the watch, check it there before reporting: for
   example `GetStatus` for what the daemon read, or a debug copy (see *Trying changes on the phone*).
   Print counts and shapes, not personal data.

**Publishing.** Publishing is outward-facing, so ask the user for the GitHub remote, and confirm before
pushing commits or tags. `RPMS/` is git-ignored, so the RPM goes to a GitHub release as an asset, beside
the source, as the AGPL requires. `tools/check.sh` guards the working tree against private data (the
phone's IP address, the watch's Bluetooth address or serial number, `config.json`), but **not the
history**: an early commit of `tests/test_integration.py` holds what looks like the real watch's
Bluetooth address (replaced in the working tree on 2026-11-14). Before the first push, ask the user
whether to squash or rewrite the history.
