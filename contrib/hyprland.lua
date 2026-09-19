-- Optional: compositor idle-inhibit for fullscreen browsers that never talk D-Bus.
-- Load from ~/.config/hypr/hyprland.lua:
--   dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/lukaseppler.idle-inhibit/contrib/hyprland.lua")

o.window("((google-)?[cC]hrom(e|ium)|[bB]rave-browser|[mM]icrosoft-edge|Vivaldi-stable|helium)", { idle_inhibit = "fullscreen" })
o.window("([fF]irefox|zen|librewolf)", { idle_inhibit = "fullscreen" })
o.window("(^.+-youtube\\.com__.*$|^.+-app\\.zoom\\.us__wc_home.*$)", { idle_inhibit = "fullscreen" })
