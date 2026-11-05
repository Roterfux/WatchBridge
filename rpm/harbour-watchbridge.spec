%{!?_userunitdir:%global _userunitdir /usr/lib/systemd/user}

Name:       harbour-watchbridge
Summary:    Huawei Watch GT 5 companion: pairing, notifications and weather
Version:    0.6.0
Release:    1
License:    AGPLv3+
BuildArch:  noarch
Source0:    %{name}-%{version}.tar.bz2

# UI
Requires:   sailfishsilica-qt5 >= 1.1.0
Requires:   mapplauncherd-booster-silica-qt5
Requires:   nemo-qml-plugin-dbus-qt5
Requires:   nemo-qml-plugin-notifications-qt5
Requires:   qt5-qtdeclarative-import-positioning
Requires:   qt5-qtgraphicaleffects
# Daemon
Requires:   python3-base
Requires:   dbus-python3
Requires:   python3-gobject
Requires:   bluez5
Requires:   systemd

%description
WatchBridge connects a Huawei Watch GT 5 (and GT 5 Pro) to Sailfish OS.
It pairs with the watch using the HiChain protocol, forwards phone
notifications and incoming calls, pushes the weather forecast from
Open-Meteo and syncs health data back to the phone.
The watch protocol is ported from Gadgetbridge.

%prep
%setup -q -n %{name}-%{version}
# Sources may come from a filesystem without Unix modes (e.g. a Windows drive)
find . -type f -exec chmod 0644 {} +
chmod 0755 data/harbour-watchbridge-daemon data/contact-names tools/*.sh

%build
# Nothing to build: QML UI + Python daemon

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_datadir}/%{name}
cp -r qml %{buildroot}%{_datadir}/%{name}/
install -d %{buildroot}%{_datadir}/%{name}/daemon
cp -r daemon/watchbridge %{buildroot}%{_datadir}/%{name}/daemon/
find %{buildroot}%{_datadir}/%{name}/daemon -name __pycache__ -prune -exec rm -rf {} \;
# Stamp the exact package version into the daemon and the About page (fail if a marker moved)
sed -i 's/^__version__ = .*/__version__ = "%{version}-%{release}"/' \
    %{buildroot}%{_datadir}/%{name}/daemon/watchbridge/__init__.py
sed -i 's/appVersion: "[^"]*"/appVersion: "%{version}-%{release}"/' \
    %{buildroot}%{_datadir}/%{name}/qml/pages/AboutPage.qml
grep -q '"%{version}-%{release}"' %{buildroot}%{_datadir}/%{name}/daemon/watchbridge/__init__.py
grep -q 'appVersion: "%{version}-%{release}"' %{buildroot}%{_datadir}/%{name}/qml/pages/AboutPage.qml

install -D -m 0755 data/harbour-watchbridge-daemon %{buildroot}%{_bindir}/harbour-watchbridge-daemon
sed -i 's/\r$//' %{buildroot}%{_bindir}/harbour-watchbridge-daemon
install -D -m 0644 data/harbour-watchbridge.service %{buildroot}%{_userunitdir}/harbour-watchbridge.service
install -D -m 0644 data/harbour.watchbridge.service %{buildroot}%{_datadir}/dbus-1/services/harbour.watchbridge.service
install -d %{buildroot}%{_userunitdir}/post-user-session.target.wants
ln -s ../harbour-watchbridge.service %{buildroot}%{_userunitdir}/post-user-session.target.wants/harbour-watchbridge.service

# Caller names: a helper that sailjail starts with the Contacts permission
install -D -m 0755 data/contact-names %{buildroot}%{_libexecdir}/%{name}/contact-names
sed -i 's/\r$//' %{buildroot}%{_libexecdir}/%{name}/contact-names
install -D -m 0644 data/%{name}-contacts.desktop %{buildroot}%{_datadir}/applications/%{name}-contacts.desktop

install -D -m 0644 harbour-watchbridge.desktop %{buildroot}%{_datadir}/applications/%{name}.desktop
for size in 86x86 108x108 128x128 172x172; do
    install -D -m 0644 icons/$size/%{name}.png %{buildroot}%{_datadir}/icons/hicolor/$size/apps/%{name}.png
done

%post
# Start (or restart) the daemon for the logged-in user
if [ "$1" -ge 1 ]; then
    systemctl-user daemon-reload >/dev/null 2>&1 || :
    systemctl-user try-restart harbour-watchbridge.service >/dev/null 2>&1 || :
fi

%preun
if [ "$1" -eq 0 ]; then
    systemctl-user stop harbour-watchbridge.service >/dev/null 2>&1 || :
fi

%postun
systemctl-user daemon-reload >/dev/null 2>&1 || :

%files
%defattr(-,root,root,-)
%license LICENSE NOTICE.md
%{_bindir}/harbour-watchbridge-daemon
%{_datadir}/%{name}
%{_datadir}/applications/%{name}.desktop
%{_datadir}/applications/%{name}-contacts.desktop
%{_libexecdir}/%{name}
%{_datadir}/icons/hicolor/*/apps/%{name}.png
%{_datadir}/dbus-1/services/harbour.watchbridge.service
%{_userunitdir}/harbour-watchbridge.service
%{_userunitdir}/post-user-session.target.wants/harbour-watchbridge.service

%changelog
* Thu Nov 05 2026 WatchBridge contributors - 0.6.0-1
- Calendar: the phone's events appear in the calendar app on the watch, for as many days as
  the watch asks for (35 on a GT 5), recurring events included. Sent after connecting and,
  when something changed, every 30 minutes; only the changes go over
- New "Calendar" section in the settings with a switch, the sync status and "Sync calendar now"

* Thu Nov 05 2026 WatchBridge contributors - 0.5.0-4
- Main page: the "Sync time" and "Reconnect" buttons moved to the bottom of the page

* Thu Nov 05 2026 WatchBridge contributors - 0.5.0-3
- About page: link to the source code on GitHub

* Thu Nov 05 2026 WatchBridge contributors - 0.5.0-2
- Watch faces are registered under a face-format version the watch supports (the oldest
  it lists, 2.1 on a GT 5) instead of 1.0.0; a face sent as 1.0.0 showed up garbled and
  could not be selected
- Delete button next to every face that can be deleted
- The start page shows the face that is on the watch when it was installed with WatchBridge
  (its preview is kept); otherwise the drawn watch as before. The face list is read after
  connecting and when the app comes to the front
- Round previews in the install dialog and in the list

* Thu Nov 05 2026 WatchBridge contributors - 0.5.0-1
- Watch faces: list the faces on the watch, switch to one, delete downloaded ones, and install
  .hwt packages with a preview, a screen-size check and upload progress (file upload service
  0x28 and watch-face service 0x27, ported from Gadgetbridge)
- No automatic health sync while a watch face is being sent

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-9
- The notifications part (forward switch with its counter, last notification, test
  notification) moved from the main page to the settings

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-8
- Main page: firmware version without the build suffix in brackets

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-7
- Cover: no battery number inside the watch dial (the status line has it), no sleep score
  and no time next to the heart rate

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-6
- Cover: the latest missed call with the caller's name, from Sailfish's missed-call
  notification; it disappears when the missed calls are cleared on the phone

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-5
- Cover: battery in percent, today's steps, last night's sleep with its score and the
  latest heart-rate reading (from the last health sync), plus a "sync health" action

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-4
- Notifications dismissed on the phone, or closed by their app (e.g. the message was read),
  are removed from the watch as well; switch in the settings
- An updated notification replaces the old one on the watch instead of appearing twice
- Health page: heart-rate line in exactly the "awake" colour, drawn thicker

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-3
- Caller names: ask for the Privileged permission too; Contacts alone does not open the
  contacts storage ("unable to open database file")
- Contact helper: the read-only fallback now really applies, and a missing database is
  reported as missing access

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-2
- Caller names: start the contact helper through python3, since sailjail only starts
  binaries listed in the profile's Exec line (0.4.0-1 failed with "no details")

* Thu Nov 05 2026 WatchBridge contributors - 0.4.0-1
- Incoming calls on the watch: caller name or number, reject (or answer) on the watch,
  the call screen closes when the call is answered or ends on the phone
- Caller names from Contacts through a small sandboxed helper; Sailfish asks once for the
  Contacts permission. Names stay in memory only
- New "Calls" section in the settings

* Thu Nov 05 2026 WatchBridge contributors - 0.3.0-2
- Health page: time axes and guide lines under the steps, heart-rate and sleep charts
- Sleep chart: legend for awake, REM, light and deep sleep

* Wed Nov 04 2026 WatchBridge contributors - 0.3.0-1
- File download over service 0x2C, ported from Gadgetbridge
- TruSleep: sleep stages (light, deep, REM, awake), sleep score, efficiency, time to fall
  asleep and breathing rate; hypnogram on the health page
- Stress measurements (needs automatic stress measurement on the watch)
- New sleep-sessions.csv and stress.csv; daily.csv gains REM minutes, sleep score and stress
- A failing health sync always reports back instead of staying in "syncing"

* Wed Nov 04 2026 WatchBridge contributors - 0.2.0-1
- Health sync: daily totals, per-minute steps and heart rate (SpO2 where recorded) and basic
  sleep from the watch, every few hours and on demand
- Stored in ~/Documents/WatchBridge as health.sqlite plus monthly activity, sleep and daily CSV files
- New health page with hourly steps, heart-rate curve and last night's sleep for any day
- Announce heart-rate capability to the watch and offer a "measure heart rate continuously"
  switch; without it a GT 5 records no heart rate between workouts
- Per-minute calories converted to kcal; non-sleep period types are no longer counted as sleep

* Wed Nov 04 2026 WatchBridge contributors - 0.1.0-7
- About page shows the exact app version and the running background service's version,
  and warns when they differ (e.g. an old service is still answering)
- Never let a late or second Bluetooth connection replace a working one
- Reconnect backoff only starts over after a connection lasted a minute
- Main page explains when "selected apps only" is on but no app is selected

* Tue Nov 03 2026 WatchBridge contributors - 0.1.0-6
- Notifications: "selected apps only" mode (allow-list) next to the existing muted apps
- Remember apps that sent notifications and offer them as switches in the app lists

* Tue Nov 03 2026 WatchBridge contributors - 0.1.0-5
- First version tested on a real Watch GT 5 (firmware 6.0.0.23) with Sailfish OS 5.2
- Accept the NUL-terminated HiChain JSON sent by the watch
- Shut the RFCOMM socket down on disconnect (reconnects failed with EBUSY)
- Mark the watch as trusted after connecting so it can reconnect by itself
- Send the account, setting, reverse-capability, set-up-device and connect-status
  messages after connecting, as Gadgetbridge does

* Tue Nov 03 2026 WatchBridge contributors - 0.1.0-4
- Open the watch connection with our own SDP search + RFCOMM socket when BlueZ
  does not know the Huawei service (connection got stuck after Bluetooth pairing)
- Stop a first pairing with an error instead of retrying when the connection cannot be opened

* Tue Nov 03 2026 WatchBridge contributors - 0.1.0-3
- Wait up to 90 s for the watch during first pairing (was 5 s) so the user can confirm on the watch
- Name the failing handshake step in the log and the UI; never hang in "authenticating"
- Stop retrying a failed first pairing in the background

* Tue Nov 03 2026 WatchBridge contributors - 0.1.0-2
- Fix daemon losing its D-Bus name at startup (UI stuck on "Starting service")
- Fail pairing cleanly when no Bluetooth adapter is available
- Show the D-Bus error in the UI when the service does not answer

* Mon Nov 02 2026 WatchBridge contributors - 0.1.0-1
- Initial release: Watch GT 5 pairing (HiChain), notification sync, weather push
