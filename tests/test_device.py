"""End-to-end tests of HuaweiWatch against the simulated watch."""

import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
sys.path.insert(0, os.path.dirname(__file__))

from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei.tlv import TLV  # noqa: E402
from watchbridge import weather  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402

SAMPLE = {
    "current": {"time": 1761800000, "temperature_2m": 11.6, "relative_humidity_2m": 80,
                "apparent_temperature": 9.2, "weather_code": 61, "wind_speed_10m": 14.0,
                "wind_direction_10m": 225, "uv_index": 1.4},
    "hourly": {"time": [1761800000 + 3600 * i for i in range(30)],
               "temperature_2m": [10 + i % 5 for i in range(30)],
               "weather_code": [3] * 30, "precipitation_probability": [20] * 30, "uv_index": [0.5] * 30},
    "daily": {"time": [1761782400 + 86400 * i for i in range(8)],
              "weather_code": [61, 3, 0, 1, 2, 45, 95, 71],
              "temperature_2m_max": [13, 14, 15, 12, 11, 10, 9, 2],
              "temperature_2m_min": [7, 6, 5, 4, -1, -2, -3, -6],
              "sunrise": [1761804000 + 86400 * i for i in range(8)],
              "sunset": [1761840000 + 86400 * i for i in range(8)]},
}


class Recorder(D.Listener):
    def __init__(self):
        self.states = []
        self.battery = None
        self.info = None
        self.weather_requests = 0
        self.call_actions = []
        self.connected = threading.Event()
        self.failed = threading.Event()

    def on_state(self, state, detail=""):
        self.states.append((state, detail))
        if state == D.STATE_CONNECTED:
            self.connected.set()
        if state in (D.STATE_AUTH_FAILED, D.STATE_DISCONNECTED):
            self.failed.set()

    def on_battery(self, level):
        self.battery = level

    def on_device_info(self, info):
        self.info = info

    def on_weather_requested(self):
        self.weather_requests += 1

    def on_call_action(self, action):
        self.call_actions.append(action)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestDevice(unittest.TestCase):
    def make(self, store_data, **watch_kw):
        phone_sock, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock, **watch_kw).start()
        rec = Recorder()
        store = D.DeviceStore(store_data, lambda: None)
        dev = D.HuaweiWatch(phone_sock, "AA:BB:CC:DD:EE:FF", store, rec)
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        return dev, watch, rec, store

    def test_first_pairing_then_features(self):
        dev, watch, rec, store = self.make({})
        dev.start()
        self.assertTrue(rec.connected.wait(10), rec.states)
        self.assertEqual(store.auth_key(), watch.auth_token)
        self.assertEqual(dev.params.secret_key, watch.params.secret_key)
        self.assertEqual(rec.battery, 87)
        self.assertEqual(rec.info["model"], "HUAWEI WATCH GT 5")
        self.assertEqual(dev.notification_constraints["content_length"], 500)
        # every post-auth packet the watch saw was encrypted
        self.assertTrue(all(p.was_encrypted for p in watch.received))

        dev.send_notification("Alice", "Hello from Sailfish ❤", app_id="org.sailfishos.messages", key="n1")
        self.assertTrue(wait_for(lambda: watch.notifications))
        n = watch.notifications[0]
        texts = [e.get_string(0x10, "") for e in n.get_object(0x84).get_object(0x8C).get_objects(0x8D)]
        self.assertEqual(texts, ["Alice", "Alice", "Hello from Sailfish ❤"])
        self.assertEqual(n.get_string(0x11), "org.sailfishos.messages")
        self.assertTrue(n.contains(0x15) and n.contains(0x19))  # timestamp / repeat-notify caps

        report = weather.parse_open_meteo(SAMPLE, "Helsinki", now=1761800000)
        dev.send_weather(report)
        self.assertTrue(wait_for(lambda: watch.forecasts))
        f = watch.forecasts[0]
        self.assertEqual(len(f.get_object(0x81).get_objects(0x82)), 24)
        days = f.get_object(0x90).get_objects(0x91)
        self.assertEqual(len(days), 8)
        self.assertEqual(days[4].get_byte(0x15), 0xFF)  # -1 degC as signed byte
        current = [p for p in watch.received if (p.service, p.command) == (0x0F, 0x01)][0].tlv
        self.assertEqual(current.get_string(0x08), "Helsinki")
        self.assertEqual(current.get_byte(0x09), 12)
        self.assertEqual(current.get_byte(0x0F), 1)  # uv index (expand cap 0x2f)

        watch.push(0x0F, 0x04, TLV().put_int(0x7F, 0x000186AA))
        self.assertTrue(wait_for(lambda: rec.weather_requests == 1))
        watch.push(0x01, 0x27, TLV().put_byte(0x01, 55))
        self.assertTrue(wait_for(lambda: rec.battery == 55))

    def test_incoming_call(self):
        dev, watch, rec, store = self.make({})
        dev.start()
        self.assertTrue(rec.connected.wait(10), rec.states)
        self.assertEqual(dev.notification_constraints["incoming_number_format"], 0x01)

        def elements(n):
            return [(e.get_byte(0x0E), e.get_byte(0x0F), e.get_string(0x10, ""))
                    for e in n.get_object(0x84).get_object(0x8C).get_objects(0x8D)]

        self.assertTrue(dev.send_incoming_call("Bob", "+43 664 1234567"))
        self.assertTrue(wait_for(lambda: len(watch.notifications) == 1))
        call = watch.notifications[0]
        self.assertEqual(call.get_byte(0x02), 0x01)  # call
        # Gadgetbridge: the name as text, the number as "flight" element in the number format
        self.assertEqual(elements(call), [(0x01, 0x02, "Bob"), (0x07, 0x01, "+43 664 1234567")])
        self.assertFalse(call.contains(0x11))  # no source app for a phone call

        dev.end_call(answered=True)   # expand capability 74 -> "call started"
        dev.end_call()
        self.assertTrue(wait_for(lambda: len(watch.notifications) == 3))
        self.assertEqual([n.get_byte(0x02) for n in watch.notifications[1:]], [0x0D, 0x0C])
        self.assertEqual(elements(watch.notifications[2]), [(0x01, 0x02, "")])

        for value in (0x01, 0x02, 0x05):
            watch.push(0x04, 0x01, TLV().put_byte(0x01, value))
        self.assertTrue(wait_for(lambda: len(rec.call_actions) == 3))
        self.assertEqual(rec.call_actions, ["reject", "accept", 5])

    def test_reconnect_with_stored_token(self):
        token = os.urandom(32)
        dev, watch, rec, store = self.make({}, auth_token=token)
        store.set_auth_key(token)
        dev.start()
        self.assertTrue(rec.connected.wait(10), rec.states)
        self.assertEqual(dev.params.secret_key, watch.params.secret_key)

    def test_stale_pairing_fails_cleanly(self):
        dev, watch, rec, store = self.make({}, auth_token=os.urandom(32))
        store.set_auth_key(os.urandom(32))
        dev.start()
        self.assertTrue(rec.failed.wait(10))
        self.assertIn(D.STATE_AUTH_FAILED, [s for s, _ in rec.states])

    def test_first_pairing_waits_for_confirmation_on_watch(self):
        # Gadgetbridge has no timeout here; the old 5 s limit dropped the link
        # while the user was still tapping the checkmark on the watch.
        dev, watch, rec, store = self.make({}, confirm_delay=D.INIT_TIMEOUT + 1.5)
        dev.start()
        self.assertTrue(rec.connected.wait(20), rec.states)
        self.assertEqual(rec.states[0], (D.STATE_AUTHENTICATING, "confirm_on_watch"))

    def test_dropped_link_names_the_step(self):
        dev, watch, rec, store = self.make({}, drop_at=(0x01, 0x2C))
        dev.start()
        self.assertTrue(rec.failed.wait(10), rec.states)
        state, detail = rec.states[-1]
        self.assertEqual(state, D.STATE_DISCONNECTED)
        self.assertIn("pin code", detail)

    def test_cbc_counter_mode_device(self):
        dev, watch, rec, store = self.make({}, device_support_type=1, encrypt_method=0)
        dev.start()
        self.assertTrue(rec.connected.wait(10), rec.states)


if __name__ == "__main__":
    unittest.main()
