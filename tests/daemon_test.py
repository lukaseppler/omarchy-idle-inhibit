#!/usr/bin/env python3
"""Private-bus contract tests for idle-inhibit-daemon."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

DAEMON = Path(__file__).resolve().parents[1] / "bin" / "idle-inhibit-daemon"

Gio = None
GLib = None

STEAL_NAME = r"""
import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib
loop = GLib.MainLoop()
Gio.bus_own_name(
    Gio.BusType.SESSION,
    "org.freedesktop.ScreenSaver",
    Gio.BusNameOwnerFlags.REPLACE,
    None,
    lambda *args: None,
    None,
)
GLib.timeout_add_seconds(8, loop.quit)
loop.run()
"""


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


def write_claim(state_dir: Path, stay: Path) -> None:
    info = stay.stat()
    (state_dir / "idle-inhibit").write_text(
        json.dumps({"dev": info.st_dev, "ino": info.st_ino}),
        encoding="utf-8",
    )


class SessionClient:
    def __init__(self):
        address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )

    def inhibit(self, app="chromium", reason="playing-video", path="/org/freedesktop/ScreenSaver"):
        reply = self.conn.call_sync(
            "org.freedesktop.ScreenSaver",
            path,
            "org.freedesktop.ScreenSaver",
            "Inhibit",
            GLib.Variant("(ss)", (app, reason)),
            GLib.VariantType("(u)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        return int(reply.unpack()[0])

    def uninhibit(self, cookie, path="/org/freedesktop/ScreenSaver"):
        self.conn.call_sync(
            "org.freedesktop.ScreenSaver",
            path,
            "org.freedesktop.ScreenSaver",
            "UnInhibit",
            GLib.Variant("(u)", (int(cookie),)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )

    def close(self):
        try:
            if not self.conn.is_closed():
                self.conn.close_sync(None)
        except GLib.GError:
            pass


def load_daemon_module():
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("idle_inhibit_daemon", str(DAEMON))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class TrustedInterpreterTests(unittest.TestCase):
    def setUp(self):
        Path(os.environ["OMARCHY_IDLE_INHIBIT_STATE_DIR"]).mkdir(parents=True, exist_ok=True)

    def test_rejects_relative_and_user_owned_paths(self):
        module = load_daemon_module()
        self.assertIsNone(module.trusted_interpreter("python3"))
        self.assertIsNone(module.trusted_interpreter("usr/bin/python3"))
        owned = Path(os.environ["OMARCHY_IDLE_INHIBIT_STATE_DIR"]) / "fake-python"
        owned.write_text("#!/bin/sh\n", encoding="utf-8")
        owned.chmod(0o755)
        self.assertIsNone(module.trusted_interpreter(str(owned)))

    def test_accepts_usr_bin_python3(self):
        module = load_daemon_module()
        resolved = module.trusted_interpreter("/usr/bin/python3")
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.startswith("/usr/bin/") or resolved.startswith("/usr/lib/"))
        info = os.stat(resolved)
        self.assertEqual(info.st_uid, 0)
        self.assertFalse(info.st_mode & 0o022)
        self.assertTrue(stat.S_ISREG(info.st_mode))

    def test_check_interpreter_flag(self):
        result = subprocess.run(
            ["/usr/bin/python3", str(DAEMON), "--check-interpreter"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().startswith("/usr/"))


class IdleInhibitTests(unittest.TestCase):
    def setUp(self):
        _load_gi()
        self.state_dir = Path(os.environ["OMARCHY_IDLE_INHIBIT_STATE_DIR"])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.stay = self.state_dir / "stay-awake"
        self.auto = self.state_dir / "idle-inhibit"
        self.stay.unlink(missing_ok=True)
        self.auto.unlink(missing_ok=True)
        self.start_daemon()

    def start_daemon(self):
        self.daemon = Daemon(self.state_dir)
        self.addCleanup(self.daemon.stop)
        self.daemon.wait_for_name()

    def test_chromium_path_toggles_stay_awake(self):
        holder = SessionClient()
        self.addCleanup(holder.close)
        cookie = holder.inhibit()
        wait_for(self.stay.exists, message="stay-awake missing after Inhibit")
        wait_for(self.auto.exists, message="claim missing after Inhibit")
        holder.uninhibit(cookie, path="/ScreenSaver")
        wait_for(lambda: not self.stay.exists(), message="stay-awake lingered after UnInhibit")
        wait_for(lambda: not self.auto.exists(), message="claim lingered after UnInhibit")

    def test_disconnect_reaps_inhibit(self):
        holder = SessionClient()
        holder.inhibit()
        wait_for(self.stay.exists, message="stay-awake missing after Inhibit")
        holder.close()
        wait_for(lambda: not self.stay.exists(), message="stay-awake lingered after disconnect")

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
        self.stay.touch()
        self.auto.unlink(missing_ok=True)
        self.start_daemon()
        holder = SessionClient()
        self.addCleanup(holder.close)
        cookie = holder.inhibit()
        wait_for(lambda: not self.auto.exists(), message="claimed a stay-awake the user already held")
        self.assertTrue(self.stay.exists())
        holder.uninhibit(cookie)
        wait_for(lambda: not self.auto.exists(), message="claim appeared after UnInhibit")
        self.assertTrue(self.stay.exists())

    def test_matching_leftover_claim_cleared_on_start(self):
        self.daemon.stop()
        self.stay.touch()
        write_claim(self.state_dir, self.stay)
        self.start_daemon()
        wait_for(lambda: not self.stay.exists(), message="leftover stay-awake not cleared")
        wait_for(lambda: not self.auto.exists(), message="leftover claim not cleared")

    def test_garbage_leftover_does_not_delete_user_stay_awake(self):
        self.daemon.stop()
        self.stay.touch()
        self.auto.write_text("not-json", encoding="utf-8")
        self.start_daemon()
        wait_for(lambda: not self.auto.exists(), message="garbage claim not cleared")
        self.assertTrue(self.stay.exists())

    def test_cross_sender_uninhibit_rejected(self):
        owner = SessionClient()
        other = SessionClient()
        self.addCleanup(owner.close)
        self.addCleanup(other.close)
        cookie = owner.inhibit()
        wait_for(self.stay.exists, message="stay-awake missing after Inhibit")
        with self.assertRaises(GLib.GError) as ctx:
            other.uninhibit(cookie)
        self.assertIn("AccessDenied", str(ctx.exception))
        self.assertTrue(self.stay.exists())
        owner.uninhibit(cookie)
        wait_for(lambda: not self.stay.exists(), message="owner UnInhibit did not release")

    def test_manual_toggle_does_not_delete_user_stay_awake(self):
        holder = SessionClient()
        self.addCleanup(holder.close)
        cookie = holder.inhibit()
        wait_for(self.stay.exists, message="stay-awake missing after Inhibit")
        wait_for(self.auto.exists, message="claim missing after Inhibit")
        self.stay.unlink()
        self.stay.touch()
        holder.uninhibit(cookie)
        wait_for(lambda: not self.auto.exists(), message="stale claim lingered after UnInhibit")
        self.assertTrue(self.stay.exists())

    def test_name_replacement_stands_down(self):
        holder = SessionClient()
        self.addCleanup(holder.close)
        holder.inhibit()
        wait_for(self.stay.exists, message="stay-awake missing after Inhibit")
        thief = subprocess.Popen(
            [sys.executable, "-c", STEAL_NAME],
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(lambda: thief.send_signal(signal.SIGTERM) if thief.poll() is None else None)
        try:
            code = self.daemon.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.fail("daemon did not stand down after name replacement")
        self.assertEqual(code, 0)
        wait_for(lambda: not self.stay.exists(), message="stay-awake lingered after replacement")
        if thief.poll() is None:
            thief.send_signal(signal.SIGTERM)
            thief.wait(timeout=3)

    def test_oversized_inhibit_rejected(self):
        holder = SessionClient()
        self.addCleanup(holder.close)
        with self.assertRaises(GLib.GError) as ctx:
            holder.inhibit(app="x" * 257, reason="playing-video")
        self.assertIn("InvalidArgs", str(ctx.exception))
        self.assertFalse(self.stay.exists())
        cookie = holder.inhibit(app="ok", reason="y" * 256)
        wait_for(self.stay.exists, message="256-character reason should be accepted")
        holder.uninhibit(cookie)
        wait_for(lambda: not self.stay.exists(), message="accepted inhibit did not release")


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
