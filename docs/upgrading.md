---
title: Upgrading
layout: default
nav_order: 4
description: What changed for existing weewx-skyfield users — the removed options, the one tag whose units changed, the new download switches, and the companion-extension version floors.
---

# Upgrading

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Upgrading is a drop-in: install the new zip and restart.

```
weectl extension install weewx-skyfield.zip
```

Doing it over a *running* WeeWX is safe.  The ephemeris is read fully into memory at
startup, so replacing the extension's files on disk cannot disturb — or crash — the running
almanac; the new files take effect on the restart that follows.

This page covers what an existing user needs to *know*, release by release.  Everything
else is additive: new tags, new panels, nothing to change.  The full record is in
[changes.txt](https://github.com/chaunceygardiner/weewx-skyfield/blob/main/changes.txt).

## Coming from 1.x

### Two things need your attention

**The `stars` option is gone (2.0).**  The complete Hipparcos catalog now ships with the
extension, so stars are simply always available.  A leftover `stars` key in `[Skyfield]`
draws an "Ignoring unrecognized option" warning and is otherwise harmless — delete it.

If you previously downloaded `hip_main.dat` yourself and pointed the extension at it, that
copy is now redundant: the extension no longer reads it, and you can delete it.

**`ha` changed units (1.16).**  `$almanac.<body>.ha`, the local apparent hour angle, is now
served natively in **decimal degrees**, signed, 0 at transit.  Before 1.16 it fell through to
PyEphem, which returned **radians** wrapped to [0, 2π).

{: .important }
A template that read `ha` through the old PyEphem fallback must drop its `math.degrees()`
conversion, or it will now be wrong by a factor of 57.3.  This is the only tag in the
extension's history whose units changed.

### Two things start happening

**The extension now uses the network (2.0, 2.1).**  Before 2.0 it never made a network
request.  It now fetches satellite orbital elements from CelesTrak (about every three hours)
and the Minor Planet Center's comet elements (about every two days), because neither can
ship in a release and stay useful.  Both have switches:

```ini
[Skyfield]
    satellite_downloads = false
    comet_downloads = false
```

With both false the extension fetches nothing, ever — the pre-2.0 behavior exactly.  An
air-gapped station can still use satellites and comets by maintaining the element files
itself; see [Satellites](installation.md#satellites) and [Comets](installation.md#comets).

**The Sky page's dome got denser (2.0).**  With the complete catalog bundled, the defaults
changed to `star_mag_limit = 5.0` and `star_label_mag = 2.5` — roughly 800 stars, a true sky
map.  To restore the sparse pre-2.0 look:

```ini
[StdReport]
    [[SkyfieldReport]]
        star_mag_limit = 2.6
        star_label_mag = 1.1
```

## Coming from 2.x

### One thing needs your attention, and only if you embed the panels

**The `classic-night` and `classic-light` palettes are gone (2.3).**  They held the body
colors used before 1.5.  A skin still passing one to a `$sky_page` panel — or naming one in a
report's `theme` option — keeps rendering: it draws the current `night` or `light` plate and
logs one warning naming the replacement.  Change the name to `night` or `light` to silence
it.  If you have never passed a `palette` argument, there is nothing to do.

## What each release added

| Release | Worth knowing |
|---|---|
| **2.3** | Rise & Set, The Sun's Path and The Solar Year are readable on the light theme — their bars, ticks, arcs and traces are drawn over twilight bands and had taken colors chosen for a panel surface.  The manual now [shows](sky-page.md#the-two-plates) that theme.  The `classic-night` and `classic-light` palettes are dropped: a skin that passes one keeps rendering — it draws the current plate and logs a warning — but the pre-1.5 body colors are gone. |
| **2.2** | The sky charts are easier to read: the altitude rings and the cross through the zenith were invisible against the dome and now have their own color, and the small labels are lifted to a readable contrast.  Nothing to configure — but a skin that [embeds the panels](panels.md) and copied individual CSS rules should pick up the new `skylab` class. |
| **2.1** | Comets (`[[Comets]]`, Halley and Hale-Bopp by default), the twelve major meteor showers, moon perigee/apogee and `next_supermoon`, Earth's perihelion/aphelion, solar time and the equation of time.  Unit-aware `distance`/`distance_from_sun` twins and `illumination`. |
| **2.0** | Satellites (`[[Satellites]]`, ISS and Tiangong by default) with the pass family; the complete Hipparcos catalog bundled; `sky.js` so tooltips answer taps on touch screens. |
| **1.19** | The dome draws the 88 constellations' stick figures. |
| **1.16** | `ha`/`hour_angle`, `hlon`, `subsolar_lat`, `moon.moon_phase`.  See the units note above. |
| **1.15** | The Sky page's `theme` option; `.degrees` on every radians tag. |
| **1.13** | `constellation` became a string carrying `.name`, `.abbr` and `.label`. |
| **1.12** | `$almanac.<body>.label` and the translatable Sky page. |
| **1.9** | Eclipses and constellations — tag families with no PyEphem counterpart. |
| **1.4** | The transparent [result cache](performance.md#the-result-cache). |

## Companion extensions

If you run the author's other extensions, these are the floors that matter:

| Extension | Version | Why |
|---|---|---|
| [weewx-loopdata](https://github.com/chaunceygardiner/weewx-loopdata) | 6.9 or later | Earlier versions could cache a temporarily-unavailable satellite field's `N/A` until the day rolled over, instead of recovering the moment fresh elements arrive. |
| [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) | 8.1 or later | Its live dome and pass chart consume this extension's `data-body` / `data-sunlit` / `data-bright` hooks and the `satellite_names()` / `comet_names()` contract. |

Only the historical celestial 3.x — which embedded this same almanac engine — needs
`replace_builtin_almanac = false` when run alongside weewx-skyfield.  Since celestial 6.0 it
runs no service and computes nothing itself, so the two coexist with no configuration at all.

## After upgrading

Restart WeeWX and check the log for:

```
Skyfield almanac registered; reports will use Skyfield for almanac computations.
```

Then look for any `Ignoring unrecognized [Skyfield] option` warnings — that is where a
removed option announces itself.  [Troubleshooting](troubleshooting.md) lists every startup
message and what it means.

## Uninstalling

```
weectl extension uninstall weewx-skyfield
```

Reports revert to WeeWX's built-in almanac on the next restart.  One thing is deliberately
left behind: the cached orbital elements in the `wxskyfield` directory beside your SQLite
database.  Delete that directory yourself if you want them gone.
