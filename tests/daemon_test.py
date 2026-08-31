#!/usr/bin/env python3
"""Private-bus contract tests for idle-inhibit-daemon."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAEMON = ROOT / "bin" / "idle-inhibit-daemon"

gi = None
Gio = None
GLib = None


def _load_gi():
    global gi, Gio, GLib
    if Gio is not None:
        return
    import gi as _gi

    _gi.require_version("Gio", "2.0")
    _gi.require_version("GLib", "2.0")
    from gi.repository import Gio as _Gio, GLib as _GLib

    gi = _gi
    Gio = _Gio
    GLib = _GLib


class Daemon:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.proc = subprocess.Popen(
            [sys.executable, str(DAEMON)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ, "OMARCHY_IDLE_INHIBIT_STATE_DIR": str(state_dir)},
            text=True,
        )

    def wait_for_name(self, name: str, timeout: float = 4.0) -> None:
        deadline = time.time() + timeout
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"daemon exited {self.proc.returncode}: {self.proc.stderr.read()}")
            try:
                conn.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "NameHasOwner",
                    GLib.Variant("(s)", (name,)),
                    GLib.VariantType("(b)"),
                    Gio.DBusCallFlags.NONE,
                    200,
                    None,
                )
                owned = conn.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "NameHasOwner",
                    GLib.Variant("(s)", (name,)),
                    GLib.VariantType("(b)"),
                    Gio.DBusCallFlags.NONE,
                    200,
                    None,
                ).unpack()[0]
                if owned:
                    return
            except Exception:
                pass
            time.sleep(0.05)
        raise TimeoutError(f"timed out waiting for {name}: {self.proc.stderr.read()}")

    def stop(self) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                code = self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                code = self.proc.wait(timeout=2)
        else:
            code = self.proc.returncode if self.proc.returncode is not None else 1
        if self.proc.stderr:
            self.proc.stderr.close()
        return code


def wait_for(predicate, timeout: float = 3.0, message: str = "condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError(message)


def bus_call(dest, path, iface, method, parameters=None, reply_type=None):
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return conn.call_sync(
        dest,
        path,
        iface,
        method,
        parameters,
        reply_type,
        Gio.DBusCallFlags.NONE,
        2000,
        None,
    )


class HoldingClient:
    def __init__(self, path="/org/freedesktop/ScreenSaver", dest="org.freedesktop.ScreenSaver", iface="org.freedesktop.ScreenSaver"):
        # A private connection so close() drops this client's unique name
        # without tearing down the shared session bus used by the rest of the
        # test process.
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        reply = self.conn.call_sync(
            dest,
            path,
            iface,
            "Inhibit",
            GLib.Variant("(ss)", ("chromium", "playing-video")),
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        self.cookie = int(reply.unpack()[0])

    def uninhibit(self, path="/org/freedesktop/ScreenSaver", dest="org.freedesktop.ScreenSaver", iface="org.freedesktop.ScreenSaver"):
        self.conn.call_sync(
            dest,
            path,
            iface,
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
        self.daemon = Daemon(self.state_dir)
        self.addCleanup(self.daemon.stop)
        self.daemon.wait_for_name("org.freedesktop.ScreenSaver")
        self.daemon.wait_for_name("org.freedesktop.PowerManagement.Inhibit")

    def test_chromium_path_toggles_stay_awake(self):
        stay = self.state_dir / "stay-awake"
        auto = self.state_dir / "idle-inhibit"
        holder = HoldingClient()
        wait_for(stay.exists, message="stay-awake missing after Inhibit")
        wait_for(auto.exists, message="auto marker missing after Inhibit")
        has = bus_call(
            "org.freedesktop.PowerManagement.Inhibit",
            "/org/freedesktop/PowerManagement/Inhibit",
            "org.freedesktop.PowerManagement.Inhibit",
            "HasInhibit",
            reply_type=GLib.VariantType("(b)"),
        ).unpack()[0]
        self.assertTrue(has)
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
        try:
            code = second.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            second.proc.kill()
            self.fail("second daemon did not stand down")
        self.assertEqual(code, 0)

    def test_manual_stay_awake_is_left_alone(self):
        self.daemon.stop()
        stay = self.state_dir / "stay-awake"
        auto = self.state_dir / "idle-inhibit"
        stay.touch()
        if auto.exists():
            auto.unlink()
        self.daemon = Daemon(self.state_dir)
        self.daemon.wait_for_name("org.freedesktop.ScreenSaver")
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
        self.daemon = Daemon(self.state_dir)
        self.daemon.wait_for_name("org.freedesktop.ScreenSaver")
        wait_for(lambda: not stay.exists(), message="leftover stay-awake not cleared")
        wait_for(lambda: not auto.exists(), message="leftover auto marker not cleared")


def main() -> int:
    if os.environ.get("IDLE_INHIBIT_TEST_INNER") != "1":
        with __import__("tempfile").TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["IDLE_INHIBIT_TEST_INNER"] = "1"
            env["OMARCHY_IDLE_INHIBIT_STATE_DIR"] = str(Path(tmp) / "indicators")
            return subprocess.run(
                ["dbus-run-session", "--", sys.executable, __file__] + sys.argv[1:],
                env=env,
            ).returncode

    _load_gi()
    unittest.main(verbosity=2)


if __name__ == "__main__":
    sys.exit(main())
