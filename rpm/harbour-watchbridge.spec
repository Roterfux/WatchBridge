%{!?_userunitdir:%global _userunitdir /usr/lib/systemd/user}

Name:       harbour-watchbridge
Summary:    Huawei Watch GT 5 companion: pairing, notifications and weather
Version:    0.1.0
Release:    5
License:    AGPLv3+
BuildArch:  noarch
Source0:    %{name}-%{version}.tar.bz2

# UI
Requires:   sailfishsilica-qt5 >= 1.1.0
Requires:   mapplauncherd-booster-silica-qt5
Requires:   nemo-qml-plugin-dbus-qt5
Requires:   nemo-qml-plugin-notifications-qt5
Requires:   qt5-qtdeclarative-import-positioning
# Daemon
Requires:   python3-base
Requires:   dbus-python3
Requires:   python3-gobject
Requires:   bluez5
Requires:   systemd

%description
WatchBridge connects a Huawei Watch GT 5 (and GT 5 Pro) to Sailfish OS.
It pairs with the watch using the HiChain protocol, forwards phone
notifications and pushes the weather forecast from Open-Meteo.
The watch protocol is ported from Gadgetbridge.

%prep
%setup -q -n %{name}-%{version}
# Sources may come from a filesystem without Unix modes (e.g. a Windows drive)
find . -type f -exec chmod 0644 {} +
chmod 0755 data/harbour-watchbridge-daemon tools/*.sh

%build
# Nothing to build: QML UI + Python daemon

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_datadir}/%{name}
cp -r qml %{buildroot}%{_datadir}/%{name}/
install -d %{buildroot}%{_datadir}/%{name}/daemon
cp -r daemon/watchbridge %{buildroot}%{_datadir}/%{name}/daemon/
find %{buildroot}%{_datadir}/%{name}/daemon -name __pycache__ -prune -exec rm -rf {} \;

install -D -m 0755 data/harbour-watchbridge-daemon %{buildroot}%{_bindir}/harbour-watchbridge-daemon
sed -i 's/\r$//' %{buildroot}%{_bindir}/harbour-watchbridge-daemon
install -D -m 0644 data/harbour-watchbridge.service %{buildroot}%{_userunitdir}/harbour-watchbridge.service
install -D -m 0644 data/harbour.watchbridge.service %{buildroot}%{_datadir}/dbus-1/services/harbour.watchbridge.service
install -d %{buildroot}%{_userunitdir}/post-user-session.target.wants
ln -s ../harbour-watchbridge.service %{buildroot}%{_userunitdir}/post-user-session.target.wants/harbour-watchbridge.service

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
%{_datadir}/icons/hicolor/*/apps/%{name}.png
%{_datadir}/dbus-1/services/harbour.watchbridge.service
%{_userunitdir}/harbour-watchbridge.service
%{_userunitdir}/post-user-session.target.wants/harbour-watchbridge.service

%changelog
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
