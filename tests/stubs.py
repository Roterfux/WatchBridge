"""Stand-ins for dbus-python and PyGObject, so the daemon modules import on any desktop.

Real modules are used when they are installed (e.g. in WSL); the stubs only cover
what importing and the tests touch.
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))


def _install_dbus():
    try:
        import dbus  # noqa: F401
        import dbus.service  # noqa: F401
        return
    except ImportError:
        pass
    dbus = types.ModuleType("dbus")
    dbus.DBusException = Exception
    dbus.PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
    dbus.Boolean = bool
    dbus.String = str
    dbus.UInt32 = int
    dbus.Interface = lambda obj, iface: obj
    dbus.bus = types.ModuleType("dbus.bus")
    dbus.service = types.ModuleType("dbus.service")
    dbus.service.Object = object
    dbus.service.BusName = lambda *a, **k: None
    dbus.service.method = lambda *a, **k: (lambda f: f)
    dbus.service.signal = lambda *a, **k: (lambda f: f)
    sys.modules.update({"dbus": dbus, "dbus.bus": dbus.bus, "dbus.service": dbus.service})


def _install_glib():
    try:
        from gi.repository import GLib  # noqa: F401
        return
    except ImportError:
        pass
    glib = types.ModuleType("gi.repository.GLib")
    # Run idle callbacks at once; timers are recorded but never fire
    glib.idle_add = lambda fn, *a: fn(*a)
    glib.timeout_add_seconds = lambda delay, fn, *a: 1
    glib.source_remove = lambda source: None
    gi = types.ModuleType("gi")
    gi.repository = types.ModuleType("gi.repository")
    gi.repository.GLib = glib
    sys.modules.update({"gi": gi, "gi.repository": gi.repository, "gi.repository.GLib": glib})


_install_dbus()
_install_glib()
