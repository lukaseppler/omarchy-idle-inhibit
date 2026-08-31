-- Optional compositor-side idle inhibit for fullscreen browser windows.
--
-- Chromium already asserts Wayland idle-inhibit when a tab goes fullscreen.
-- Firefox-family browsers often do not, and YouTube/Zoom webapps are untagged
-- from chromium-based-browser, so they miss any tag-based rule.
--
-- Load from ~/.config/hypr/hyprland.lua:
--
--   dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/lukaseppler.idle-inhibit/contrib/hyprland.lua")
--
-- Windowed playback still needs the D-Bus daemon in this plugin.

o.window("((google-)?[cC]hrom(e|ium)|[bB]rave-browser|[mM]icrosoft-edge|Vivaldi-stable|helium)", { idle_inhibit = "fullscreen" })
o.window("([fF]irefox|zen|librewolf)", { idle_inhibit = "fullscreen" })
o.window("(^.+-youtube\\.com__.*$|^.+-app\\.zoom\\.us__wc_home.*$)", { idle_inhibit = "fullscreen" })
