import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  property var shell: null
  property var manifest: null
  property var pluginRegistry: null

  readonly property string sourceDir: {
    var url = String(Qt.resolvedUrl("."))
    if (url.indexOf("file://") === 0) url = url.substring(7)
    if (url.length > 1 && url.charAt(url.length - 1) === "/")
      url = url.substring(0, url.length - 1)
    return url
  }
  readonly property string daemonPath: sourceDir ? sourceDir + "/bin/idle-inhibit-daemon" : ""
  readonly property string python: "/usr/bin/python3"

  property var status: ({ held: false, count: 0, holders: [], stayAwake: false, auto: false, screensaverName: false })
  property bool stoodDown: false
  property bool interpreterOk: false
  property bool disposed: false
  property int retryCount: 0
  property int lastExitCode: -1
  property real daemonStart: 0

  function applyStatus(raw) {
    try {
      var next = JSON.parse(String(raw || ""))
      if (next && typeof next === "object") {
        if (next.type !== "heartbeat") root.status = next
      }
    } catch (error) {}
  }

  function startDaemon() {
    if (root.disposed || !root.daemonPath || daemon.running || root.stoodDown || !root.interpreterOk) return
    root.daemonStart = Date.now()
    // argv[1] handshake: the shell pid, so the daemon never mistakes a
    // reparent target for its owner.
    daemon.command = [root.python, root.daemonPath, String(Quickshell.processId)]
    daemon.running = true
  }

  function checkThenStart() {
    if (root.disposed || !root.daemonPath || daemon.running || root.stoodDown) return
    if (root.interpreterOk) {
      startDaemon()
      return
    }
    if (interpreterCheck.running) return
    interpreterCheck.command = [root.python, root.daemonPath, "--check-interpreter"]
    interpreterCheck.running = true
  }

  Process {
    id: interpreterCheck
    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.interpreterOk = true
        startDaemon()
        return
      }
      console.log("idle-inhibit refused untrusted interpreter /usr/bin/python3")
    }
  }

  Process {
    id: daemon
    stdout: SplitParser {
      onRead: function(line) { root.applyStatus(line) }
    }
    stderr: SplitParser {
      onRead: function(line) { console.log("idle-inhibit " + line) }
    }
    onExited: function(exitCode) {
      if (root.disposed) return
      root.lastExitCode = exitCode
      // A run that lasted a while is genuine progress; a flapping spawn is not.
      if ((Date.now() - root.daemonStart) / 1000 >= 20) root.retryCount = 0
      restartTimer.interval = 1000

      if (exitCode === 4) {
        // The daemon only uses this code when a genuinely foreign owner
        // (not another copy of this plugin, e.g. a future Omarchy-native
        // implementation) holds org.freedesktop.ScreenSaver: stand down.
        root.stoodDown = true
        console.log("idle-inhibit stood down: the name is held by a foreign owner")
        return
      }

      if (exitCode === 0) {
        // The name is held by a sibling copy of this daemon. Keep trying at a
        // gentle pace: if the sibling is an orphan or a dying shell's copy it
        // quits within seconds (watchdog / closed-stdout detection), and we
        // take over. While a healthy sibling serves, this is redundant but
        // harmless.
        root.retryCount += 1
        if (root.retryCount > 20) restartTimer.interval = 30000
        else if (root.retryCount > 5) restartTimer.interval = 5000
        restartTimer.restart()
        return
      }

      // Crash or unexpected exit: retry, but do not tight-loop on a
      // repeatedly failing spawn.
      root.retryCount += 1
      if (root.retryCount > 5) restartTimer.interval = 60000
      restartTimer.restart()
    }
  }

  Timer {
    id: restartTimer
    interval: 1000
    repeat: false
    onTriggered: root.startDaemon()
  }

  Component.onCompleted: checkThenStart()
  Component.onDestruction: {
    root.disposed = true
    restartTimer.stop()
    interpreterCheck.running = false
    daemon.running = false
  }

  IpcHandler {
    target: "idle-inhibit"

    function status(): string {
      return JSON.stringify({
        held: !!root.status.held,
        count: Number(root.status.count || 0),
        holders: root.status.holders || [],
        stayAwake: !!root.status.stayAwake,
        auto: !!root.status.auto,
        screensaverName: !!root.status.screensaverName,
        stoodDown: root.stoodDown,
        daemonRunning: daemon.running,
        retryCount: root.retryCount,
        lastExitCode: root.lastExitCode
      })
    }
  }
}
