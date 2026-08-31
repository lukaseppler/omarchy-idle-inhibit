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

  property var status: ({ held: false, count: 0, holders: [], stayAwake: false, auto: false, screensaverName: false })
  property bool stoodDown: false

  function applyStatus(raw) {
    var next = null
    try {
      next = JSON.parse(String(raw || ""))
    } catch (error) {
      return
    }
    if (!next || typeof next !== "object") return
    root.status = next
    if (next.screensaverName) root.stoodDown = false
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
        console.log("idle-inhibit daemon stood down (screensaver name already owned)")
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

  Component.onDestruction: {
    restartTimer.stop()
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
