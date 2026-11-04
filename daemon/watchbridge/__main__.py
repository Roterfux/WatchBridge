# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point: python3 -m watchbridge [-v]"""

import argparse
import logging
import signal
import sys


def main():
    parser = argparse.ArgumentParser(prog="watchbridge", description="WatchBridge daemon")
    parser.add_argument("-v", "--verbose", action="store_true", help="log protocol traffic")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib

    from . import __version__
    from .service import Service

    logging.info("WatchBridge daemon %s", __version__)
    dbus.mainloop.glib.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    loop = GLib.MainLoop()
    session = dbus.SessionBus()
    if session.name_has_owner("harbour.watchbridge"):
        logging.error("Another WatchBridge daemon (perhaps a debug copy started by hand) already owns "
                      "harbour.watchbridge; stop it first")
        return 1
    Service(session, dbus.SystemBus())

    def quit_(*_):
        loop.quit()
        return False

    # GLib-level handlers: Python signal handlers would not run while the loop sleeps in C
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, quit_)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, quit_)
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
