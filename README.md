# Idle Inhibit for Omarchy

Keeps the Omarchy screensaver and lock off while a browser or media player is
playing video.

## Why this exists

Omarchy 4 (Quattro) replaced `hypridle` with a Quickshell idle service. That
service honors Wayland `zwp_idle_inhibit_manager_v1` inhibitors only.

Browsers and players request inhibit over D-Bus instead:

- Chromium → `org.freedesktop.ScreenSaver` at `/org/freedesktop/ScreenSaver`
- Firefox / Zen / VLC → the same interface at `/ScreenSaver`
- Chromium also uses `org.freedesktop.PowerManagement.Inhibit`

Nothing owns those names anymore, so `Inhibit()` is a silent no-op and the
screensaver comes up over YouTube, Plex, and local files — windowed or not.

This is a third-party workaround for that gap. Upstream work:

- [omacom/omarchy#6475](https://github.com/omacom/omarchy/issues/6475)
- [omacom/omarchy#8452](https://github.com/omacom/omarchy/pull/8452)
- [omacom/omarchy#6572](https://github.com/omacom/omarchy/pull/6572)

If Omarchy ships a ScreenSaver owner, this plugin stands down (exit 0) and
leaves the name alone.

## Install

```bash
omarchy plugin add https://github.com/lukaseppler/omarchy-idle-inhibit.git --enable --yes
```

Or drop this directory in `~/.config/omarchy/plugins/lukaseppler.idle-inhibit/`,
then:

```bash
omarchy plugin validate ~/.config/omarchy/plugins/lukaseppler.idle-inhibit
omarchy-shell shell rescanPlugins
omarchy plugin enable lukaseppler.idle-inhibit
```

A coffee-cup stay-awake indicator appears in the bar while video is playing,
the same one as `Super+Ctrl+I` / `omarchy toggle idle`. It clears when the
player UnInhibits or disconnects.

If a video is already playing when the plugin first starts, pause and play
once so the browser issues a fresh `Inhibit()`.

## Optional fullscreen window rules

The daemon covers windowed playback. For Firefox-family fullscreen video that
never talks D-Bus, add this to `~/.config/hypr/hyprland.lua`:

```lua
dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/lukaseppler.idle-inhibit/contrib/hyprland.lua")
```

Then `hyprctl reload`. Chromium already inhibits when fullscreen; the extra
rules are harmless.

## How it works

The shell service starts `bin/idle-inhibit-daemon`, which:

1. Owns `org.freedesktop.ScreenSaver` and `org.freedesktop.PowerManagement.Inhibit`.
2. Tracks `Inhibit` cookies and drops them on `UnInhibit` or when the caller
   leaves the bus.
3. Touches Omarchy's `stay-awake` indicator while any cookie is held.
4. Leaves a stay-awake the user turned on themselves alone.

It does **not** replace `omarchy.idle`. Stay-awake is the public hook that
plugin is already watching.

## Status

```bash
omarchy-shell idle-inhibit status
```

## Tests

```bash
~/.config/omarchy/plugins/lukaseppler.idle-inhibit/tests/run.sh
```

Needs `python3`, PyGObject (`python-gobject`), and `dbus-run-session`.

## Uninstall

```bash
omarchy plugin disable lukaseppler.idle-inhibit
omarchy plugin remove lukaseppler.idle-inhibit --yes
```

If you loaded `contrib/hyprland.lua`, remove that `dofile` from `hyprland.lua`
as well.
