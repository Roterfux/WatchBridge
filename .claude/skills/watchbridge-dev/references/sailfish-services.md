# Sailfish services the daemon uses

Read this before touching calls, contacts, notifications, the calendar data service or find my phone.

Verified on Sailfish OS 5.2.0.22. The daemon runs as `defaultuser`, unsandboxed, *without* the
`privileged` group.

**Calls: `org.nemomobile.voicecall` (session bus).** Manager at `/`, interface
`org.nemomobile.voicecall.VoiceCallManager`. The `voiceCalls` property lists handler ids, and
`voiceCallsChanged()` has no arguments. Each call is `/calls/<handler id>` (also `/calls/active`) with
interface `org.nemomobile.voicecall.VoiceCall`, `getProperties()` (`lineId`, `status`, `isIncoming`, …),
`statusChanged(int, string)`, `answer()` and `hangup()`. `silenceRingtone()` is on the manager. Status
values: 0 null, 1 active, 2 held, 3 dialing, 4 alerting, 5 incoming, 6 waiting, 7 disconnected,
8 rejected, 9 ignored. Source: github.com/sailfishos/voicecall `src/dbus/`.

**Watch side of calls (Gadgetbridge `onSetCallState`):** notification type 0x01 with the name as text
and the number as text type 0x07 in the watch's incoming-number format (notification constraints). When
answered, type 0x0D if expand bit 74 is set, else 0x0C (stop); when ended, 0x0C. The watch's buttons
arrive as 0x04/0x01 tag 1: 1 = reject, 2 = accept. Any other value is logged ("Call screen on the watch:
N") and silences the ringtone. The real value of the GT 5's mute button is still unknown.

**Contacts are privileged.** The real database is
`~/.local/share/system/privileged/Contacts/qtcontacts-sqlite/contacts.db`, which `defaultuser` cannot
read. `~/.local/share/system/Contacts/…` is a nearly empty non-privileged copy: use it to read the
*schema* (`PhoneNumbers`, `DisplayLabels`, `Names`, `Contacts.deleted`), never for data. Names come from
`contact-names`, started through sailjail. Hard-won rules:

- sailjail only starts **ELF binaries**, so Exec runs `/usr/bin/python3 <script>`, not the script.
- The command must **match the desktop file's Exec line exactly**. `contacts.HELPER` and the `.desktop`
  are kept in sync by a test.
- Reading contacts needs **`Permissions=Contacts;Privileged`**. `Contacts` alone mounts the folder, but
  firejail fails with "can't chdir to privileged".
- Inside the sandbox most of `/usr/share` is hidden, so the helper lives in `/usr/libexec` and is
  self-contained.
- sailjail logs its refusals to the system log, not stderr. Run
  `sailjail -v -p <desktop> <command>` over SSH to see them.
- Sailfish asks the user once for the permission. Don't test with another app's profile (for example
  `jolla-contacts.desktop`): that borrows its granted permissions and was blocked.
- Privacy: print counts, never names or numbers. The daemon keeps them in memory only.

**Notifications.** The monitor (`BecomeMonitor`) also matches
`type='method_return',sender='org.freedesktop.Notifications'`. A well-known sender name works in match
rules, verified. lipstick's reply to `Notify` carries the notification id (pair it with the call by
destination + reply serial), and `NotificationClosed(id, reason)` names only that id.
- Reasons: 1 expired (the banner timed out, so it stays on the watch), 2 dismissed by the user, 3 closed
  by the app (e.g. the message was read).
- Removal on the watch is 0x02/0x06 with the same key, id (crc32 of the key) and channel as the
  notification. It needs expand bit 94 or 120.
- Updates (`replaces_id`) reuse the old watch key so the watch replaces them.
- **The other direction does not exist:** deleting a notification on the watch sends nothing to the
  phone (checked with a debug log).
- Missed calls: commhistoryd posts category `x-nemo.call.missed` with the caller (contact name or number)
  as summary. They are followed even when not forwarded, for the cover.
- To probe: a small `dbus-python` script that monitors and posts its own notification, then closes it.
  Pass empty containers typed (`dbus.Array([], signature="s")`, `dbus.Dictionary({}, signature="sv")`),
  and give the GLib loop a hard timeout so a failure cannot hang the SSH session.

**Calendar.** Sailfish keeps it in privileged storage (`~/.local/share/system/privileged/Calendar`), but the
session service `org.nemomobile.calendardataservice` may read it, so no sailjail helper is needed. It starts
on demand and exits 2 s after its last answer, so use `bus.call_async`, never a proxy object (that blocks
while it starts and stays bound to a dead owner).
- `getEvents("yyyy-MM-dd", "yyyy-MM-dd")` returns a transaction id. The events follow in the signal
  `getEventsResult`, which **every client receives**: another client's answer did arrive during testing, so
  check the id.
- Recurring events come expanded; occurrences share an instance id and differ by start.
- Real signature `a(ssssbssssb)`, one field more than introspection claims: calendarUid, instanceId,
  start, end, allDay, color, label, description, location, cancelled. calendarUid and location are never
  filled in, and there are no reminders. Source: `lightweight/` in nemo-qml-plugin-calendar.
- Timed events are ISO with `Z` or an offset. All-day events are plain dates and the end date is inclusive
  (a one-day event ends on its start date); the watch wants the next midnight, in local time.
- To look at the data, print masked shapes and counts, never titles (see the contacts rule).

**Find my phone** (`findphone.py`) rings through NGF (`com.nokia.NonGraphicFeedback1`), event `clock`, for
`RING_TIME` seconds, and posts a notification whose `x-nemo-remote-action-*` hints call our `StopFindPhone`.
The UI only follows `status.findingPhone`, because the app is usually closed. A ring that times out must also
send 0x0B/0x02, or the watch keeps searching.

- ngfd is on the **system** bus, the notifications on the session bus. On the session bus `Play` only fails
  with a log warning, and the phone stays quiet (0.6.0-3 did this).
- Properties are `a{sv}`, although ngfd's introspection XML says `a(sv)`. ngfd skips entries it can't parse.
- In upstream ngfd, `ringtone` uses `x-meego-ringing-volume` (the profile's ring volume). Sailfish 5.2's own
  `/usr/share/ngfd/events.d/clock.ini` (checked on the phone) plays the alarm tone on the alarm stream
  (`x-clock-alert-volume`, media role `alarm`), repeating, fading in from 0 to 100 % over 20 s, with the
  alarm vibration, and is silenced only by the alarm-sound setting (`clock.alert.enabled`), not by the
  silent profile. During a call it plays the short SMS tone instead.
- ngfd reports an event it could not play through its `Status` signal (0 = failed), not as a D-Bus error.
