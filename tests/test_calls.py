"""Call tracking, the contact-names helper and caller-name lookup."""

import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "daemon"))
sys.path.insert(0, HERE)

import stubs  # noqa: E402,F401 - dbus stand-in on machines without dbus-python
from watchbridge import calls as K  # noqa: E402
from watchbridge.contacts import ContactNames, number_key  # noqa: E402


def load_helper():
    path = os.path.join(HERE, "..", "data", "contact-names")
    loader = importlib.machinery.SourceFileLoader("contact_names", path)
    spec = importlib.util.spec_from_loader("contact_names", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestCallTracker(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.t = K.CallTracker(lambda i, n: self.events.append(("incoming", i, n)),
                               lambda i: self.events.append(("answered", i)),
                               lambda i, a: self.events.append(("ended", i, a)))

    def test_rejected_call(self):
        self.t.added("c1", "+43123", True, K.STATUS_INCOMING)
        self.t.status("c1", K.STATUS_INCOMING)  # repeated status: no second event
        self.t.status("c1", K.STATUS_DISCONNECTED)
        self.t.removed("c1")                    # list update after the status: no second end
        self.assertEqual(self.events, [("incoming", "c1", "+43123"), ("ended", "c1", False)])

    def test_answered_call(self):
        self.t.added("c1", "+43123", True, K.STATUS_INCOMING)
        self.t.status("c1", K.STATUS_ACTIVE)
        self.t.status("c1", K.STATUS_HELD)
        self.t.status("c1", K.STATUS_ACTIVE)
        self.t.removed("c1")
        self.assertEqual(self.events, [("incoming", "c1", "+43123"), ("answered", "c1"), ("ended", "c1", True)])

    def test_outgoing_call_is_ignored(self):
        self.t.added("c2", "+43999", False, K.STATUS_DIALING)
        self.t.status("c2", K.STATUS_ACTIVE)
        self.t.status("c2", K.STATUS_DISCONNECTED)
        self.assertEqual(self.events, [])

    def test_call_waiting_during_a_call(self):
        self.t.added("c1", "+431", False, K.STATUS_ACTIVE)
        self.t.added("c2", "+432", True, K.STATUS_WAITING)
        self.t.status("c2", K.STATUS_IGNORED)
        self.assertEqual(self.events, [("incoming", "c2", "+432"), ("ended", "c2", False)])


class TestContactHelper(unittest.TestCase):
    def make_db(self, path):
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE Contacts (contactId INTEGER PRIMARY KEY, collectionId INTEGER, deleted DATETIME);
            CREATE TABLE PhoneNumbers (detailId INTEGER PRIMARY KEY, contactId INTEGER, phoneNumber TEXT,
                                       subTypes TEXT, normalizedNumber TEXT);
            CREATE TABLE DisplayLabels (detailId INTEGER PRIMARY KEY, contactId INTEGER, displayLabel TEXT);
            CREATE TABLE Names (detailId INTEGER PRIMARY KEY, contactId INTEGER, firstName TEXT, lastName TEXT);
            INSERT INTO Contacts VALUES (1, 2, NULL), (2, 2, NULL), (3, 2, '2026-01-01'), (4, 1, NULL);
            INSERT INTO PhoneNumbers VALUES (1, 1, '+43 664 1234567', '', ''), (2, 2, '0699 7654321', '', ''),
                                            (3, 3, '+43 1 555', '', ''), (4, 4, '+43 664 1234567', '', '');
            INSERT INTO DisplayLabels VALUES (1, 1, 'Alice Example'), (2, 2, ''), (4, 4, 'Alice Example');
            INSERT INTO Names VALUES (2, 2, 'Bob', 'Builder');
        """)
        con.commit()
        con.close()

    def test_reads_names_skips_deleted_and_duplicates(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "contacts.db")
            self.make_db(db)
            self.assertEqual(helper.read_contacts(db),
                             [["+43 664 1234567", "Alice Example"], ["0699 7654321", "Bob Builder"]])


class TestContactNames(unittest.TestCase):
    def test_number_key(self):
        self.assertEqual(number_key("+43 664 1234567"), number_key("0043 664 1234567"))
        self.assertEqual(number_key("+43 664 1234567"), number_key("0664/1234567"))
        self.assertEqual(number_key(""), "")

    def test_lookup_through_helper_command(self):
        out = json.dumps({"contacts": [["+43 664 1234567", "Alice"], ["0699 7654321", "Bob"]]})
        names = ContactNames([sys.executable, "-c", "import sys; sys.stdout.write(%r)" % out], run_async=False)
        names.refresh()
        self.assertEqual(names.state, "ready")
        self.assertEqual(names.count, 2)
        self.assertEqual(names.lookup("06641234567"), "Alice")
        self.assertEqual(names.lookup("+43 699 7654321"), "Bob")
        self.assertIsNone(names.lookup("+43 1 999999"))
        self.assertIsNone(names.lookup(""))

    def test_failing_helper_keeps_calls_working(self):
        names = ContactNames([sys.executable, "-c", "import sys; sys.stderr.write('denied'); sys.exit(3)"],
                             run_async=False)
        names.refresh()
        self.assertEqual(names.state, "failed")
        self.assertIn("denied", names.error)
        self.assertIsNone(names.lookup("+43 664 1234567"))

    def test_missing_helper(self):
        names = ContactNames(["/nonexistent/contact-names"], run_async=False)
        names.refresh()
        self.assertEqual(names.state, "failed")


if __name__ == "__main__":
    unittest.main()
