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

  property var status: ({
    held: false,
    count: 0,
    holders: [],
    stayAwake: false,
    auto: false,
    screensaverName: false,
    powerManagementName: false
  })
  property string lastEvent: "starting"
  property bool stoodDown: false
  property int restartAttempt: 0

  function applyStatus(raw) {
    var next = null
    try {
      next = JSON.parse(String(raw || ""))
    } catch (error) {
      return
    }
    if (!next || typeof next !== "object") return
    root.status = next
    root.lastEvent = next.held ? "inhibited" : "idle"
    if (next.screensaverName) root.stoodDown = false
  }

  function statusJson() {
    return JSON.stringify({
      held: !!root.status.held,
      count: Number(root.status.count || 0),
      holders: root.status.holders || [],
      stayAwake: !!root.status.stayAwake,
      auto: !!root.status.auto,
      screensaverName: !!root.status.screensaverName,
      powerManagementName: !!root.status.powerManagementName,
      stoodDown: root.stoodDown,
      daemonRunning: daemon.running,
      daemonPath: root.daemonPath,
      lastEvent: root.lastEvent
    })
  }

  function startDaemon() {
    if (!root.daemonPath || daemon.running || root.stoodDown) return
    daemon.command = ["python3", root.daemonPath]
    daemon.running = true
  }

  onDaemonPathChanged: startDaemon()

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
        root.lastEvent = "stood-down"
        console.log("idle-inhibit daemon stood down (screensaver name already owned)")
        return
      }

      root.lastEvent = "daemon-exit-" + exitCode
      root.restartAttempt += 1
      var delay = Math.min(8000, 500 * Math.pow(2, Math.min(4, root.restartAttempt - 1)))
      restartTimer.interval = delay
      restartTimer.restart()
    }
    onRunningChanged: {
      if (running) root.lastEvent = "daemon-running"
    }
  }

  Timer {
    id: restartTimer
    interval: 500
    repeat: false
    onTriggered: root.startDaemon()
  }

  Component.onDestruction: {
    restartTimer.stop()
    daemon.running = false
  }

  IpcHandler {
    target: "idle-inhibit"

    function status(): string {
      return root.statusJson()
    }
  }
}
