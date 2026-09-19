# Idle Inhibit for Omarchy

Keeps the screensaver off while a browser or player is playing video.

Omarchy’s idle service only honors Wayland inhibitors. Chromium, Firefox/Zen,
and VLC call `org.freedesktop.ScreenSaver.Inhibit()` instead. This plugin owns
that name, turns on stay-awake for as long as a player holds `Inhibit()`, and
stands down if Omarchy later takes the name.

Upstream: [omacom/omarchy#6475](https://github.com/omacom/omarchy/issues/6475).

## Install

```bash
omarchy plugin add https://github.com/lukaseppler/omarchy-idle-inhibit.git --enable --yes
```

The coffee cup appears while video is playing and clears on pause/stop. If a
video was already running when the plugin started, pause and play once.

## Optional fullscreen rules

Firefox-family fullscreen video that never talks D-Bus can use compositor
inhibit. Add this to `~/.config/hypr/hyprland.lua`, then `hyprctl reload`:

```lua
dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/lukaseppler.idle-inhibit/contrib/hyprland.lua")
```

## Status

```bash
omarchy-shell idle-inhibit status
```

## Tests

```bash
./tests/run.sh
```

Needs `python3`, `python-gobject`, and `dbus-run-session`.

## Uninstall

```bash
omarchy plugin disable lukaseppler.idle-inhibit
omarchy plugin remove lukaseppler.idle-inhibit --yes
```
