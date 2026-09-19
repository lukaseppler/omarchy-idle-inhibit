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

  function applyStatus(raw) {
    try {
      var next = JSON.parse(String(raw || ""))
      if (next && typeof next === "object") root.status = next
    } catch (error) {}
  }

  function startDaemon() {
    if (!root.daemonPath || daemon.running || root.stoodDown || !root.interpreterOk) return
    daemon.command = [root.python, root.daemonPath]
    daemon.running = true
  }

  function checkThenStart() {
    if (!root.daemonPath || daemon.running || root.stoodDown) return
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
      if (exitCode === 0) {
        root.stoodDown = true
        return
      }
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
        daemonRunning: daemon.running
      })
    }
  }
}
