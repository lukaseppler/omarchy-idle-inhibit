#!/usr/bin/env python3
"""Private-bus contract tests for idle-inhibit-daemon."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAEMON = ROOT / "bin" / "idle-inhibit-daemon"

Gio = None
GLib = None


def _load_gi():
    global Gio, GLib
    if Gio is not None:
        return
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio as _Gio, GLib as _GLib

    Gio = _Gio
    GLib = _GLib


class Daemon:
    def __init__(self, state_dir: Path):
        self.proc = subprocess.Popen(
            [sys.executable, str(DAEMON)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "OMARCHY_IDLE_INHIBIT_STATE_DIR": str(state_dir)},
        )

    def wait_for_name(self, timeout: float = 4.0) -> None:
        deadline = time.time() + timeout
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"daemon exited {self.proc.returncode}")
            owned = conn.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "NameHasOwner",
                GLib.Variant("(s)", ("org.freedesktop.ScreenSaver",)),
                GLib.VariantType("(b)"),
                Gio.DBusCallFlags.NONE,
                200,
                None,
            ).unpack()[0]
            if owned:
                return
            time.sleep(0.05)
        raise TimeoutError("timed out waiting for org.freedesktop.ScreenSaver")

    def stop(self) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                return self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                return self.proc.wait(timeout=2)
        return self.proc.returncode if self.proc.returncode is not None else 1


def wait_for(predicate, timeout: float = 3.0, message: str = "condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError(message)


class HoldingClient:
    def __init__(self, path="/org/freedesktop/ScreenSaver"):
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        reply = self.conn.call_sync(
            "org.freedesktop.ScreenSaver",
            path,
            "org.freedesktop.ScreenSaver",
            "Inhibit",
            GLib.Variant("(ss)", ("chromium", "playing-video")),
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        self.cookie = int(reply.unpack()[0])

    def uninhibit(self, path="/org/freedesktop/ScreenSaver"):
        self.conn.call_sync(
            "org.freedesktop.ScreenSaver",
            path,
            "org.freedesktop.ScreenSaver",
            "UnInhibit",
            GLib.Variant("(u)", (self.cookie,)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )

    def close(self):
        self.conn.close_sync(None)


class IdleInhibitTests(unittest.TestCase):
    def setUp(self):
        _load_gi()
        self.state_dir = Path(os.environ["OMARCHY_IDLE_INHIBIT_STATE_DIR"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.start_daemon()

    def start_daemon(self):
        self.daemon = Daemon(self.state_dir)
        self.addCleanup(self.daemon.stop)
        self.daemon.wait_for_name()

    def test_chromium_path_toggles_stay_awake(self):
        stay = self.state_dir / "stay-awake"
        auto = self.state_dir / "idle-inhibit"
        holder = HoldingClient()
        wait_for(stay.exists, message="stay-awake missing after Inhibit")
        wait_for(auto.exists, message="auto marker missing after Inhibit")
        holder.uninhibit(path="/ScreenSaver")
        wait_for(lambda: not stay.exists(), message="stay-awake lingered after UnInhibit")
        wait_for(lambda: not auto.exists(), message="auto marker lingered after UnInhibit")
        holder.close()

    def test_disconnect_reaps_inhibit(self):
        stay = self.state_dir / "stay-awake"
        holder = HoldingClient()
        wait_for(stay.exists, message="stay-awake missing after Inhibit")
        holder.close()
        wait_for(lambda: not stay.exists(), message="stay-awake lingered after disconnect")

    def test_second_daemon_stands_down(self):
        second = Daemon(self.state_dir)
        self.addCleanup(second.stop)
        try:
            code = second.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.fail("second daemon did not stand down")
        self.assertEqual(code, 0)

    def test_manual_stay_awake_is_left_alone(self):
        self.daemon.stop()
        stay = self.state_dir / "stay-awake"
        auto = self.state_dir / "idle-inhibit"
        stay.touch()
        auto.unlink(missing_ok=True)
        self.start_daemon()
        holder = HoldingClient()
        time.sleep(0.2)
        self.assertTrue(stay.exists())
        self.assertFalse(auto.exists())
        holder.uninhibit()
        time.sleep(0.2)
        self.assertTrue(stay.exists())
        self.assertFalse(auto.exists())
        holder.close()

    def test_leftover_auto_marker_cleared_on_start(self):
        self.daemon.stop()
        stay = self.state_dir / "stay-awake"
        auto = self.state_dir / "idle-inhibit"
        stay.touch()
        auto.touch()
        self.start_daemon()
        wait_for(lambda: not stay.exists(), message="leftover stay-awake not cleared")
        wait_for(lambda: not auto.exists(), message="leftover auto marker not cleared")


def main() -> int:
    if os.environ.get("IDLE_INHIBIT_TEST_INNER") != "1":
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["IDLE_INHIBIT_TEST_INNER"] = "1"
            env["OMARCHY_IDLE_INHIBIT_STATE_DIR"] = str(Path(tmp) / "indicators")
            return subprocess.run(
                ["dbus-run-session", "--", sys.executable, __file__, *sys.argv[1:]],
                env=env,
            ).returncode

    _load_gi()
    unittest.main(verbosity=2)


if __name__ == "__main__":
    sys.exit(main())
