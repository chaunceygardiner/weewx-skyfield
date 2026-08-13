---
title: Configuration
layout: default
nav_order: 3
description: Every weewx-skyfield option in one place — the [Skyfield] section of weewx.conf, the SkyfieldReport stanza for the Sky page, the [Almanac] translation keys and the astronomical-unit overrides.
---

# Configuration

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Every option this extension reads, in one place.  There are four settings groups, and which
file they belong in is not arbitrary — it follows what each one governs:

| Group | Governs | Lives in |
|---|---|---|
| [`[Skyfield]`](#the-skyfield-section) | The almanac engine: what it serves, what it downloads | `weewx.conf`, top level |
| [`[[SkyfieldReport]]`](#the-sky-pages-report-stanza) | The bundled Sky page: whether, when and how it renders | `weewx.conf`, under `[StdReport]` |
| [`[Almanac]`](#translation-keys) | Display names in a report's own language | A lang file, `skin.conf`, or `weewx.conf` per report |
| [`[Units]`](#unit-and-format-overrides) | How this extension's units print | Wherever your skin sets units |

The installer writes the first two.  The other two are optional.

## The `[Skyfield]` section

The installer adds this to `weewx.conf` with these defaults:

```ini
[Skyfield]
    enable = true
    satellite_downloads = true
    comet_downloads = true
    [[Satellites]]
        iss = 25544
        tiangong = 48274
    [[Comets]]
        halley = 1P
        hale_bopp = C/1995 O1
```

| Option | Default | Effect |
|---|---|---|
| `enable` | `true` | Register the Skyfield almanac.  Set `false` and reports fall back to WeeWX's built-in PyEphem/weeutil almanac — the extension stays installed and does nothing. |
| `satellite_downloads` | `true` | Fetch satellite orbital elements from CelesTrak: at install, at any startup finding them missing or stale, then about every three hours.  See [Satellites](installation.md#satellites). |
| `comet_downloads` | `true` | Fetch the MPC's CometEls.txt: at install, at any startup finding it missing or stale, then about every two days.  See [Comets](installation.md#comets). |
| `[[Satellites]]` | ISS, Tiangong | `tag name = NORAD catalog number`, one line each.  This one list drives both the [satellite tags](tag-index.md#satellite-tags) and the fetch list. |
| `[[Comets]]` | Halley, Hale-Bopp | `tag name = MPC designation`, one line each — `tsuchinshan_atlas = C/2023 A3`. |

{: .important }
These are the section's only entries.  Anything else draws a log warning and is ignored —
which is how a typo announces itself rather than silently doing nothing.

### Comets worth configuring

The defaults tell the two comet stories: Halley returns (2061; a hollow diamond on the dome
until then), and Hale-Bopp — the great comet of 1997 — left for millennia: now about 49 AU
out and receding, a number the almanac table watches creep outward year over year.

Other famous comets currently in the MPC file, ready to paste:

```
[Skyfield]
    [[Comets]]
        encke = 2P                        # shortest period known (3.3 yr); Taurids parent
        tsuchinshan_atlas = C/2023 A3     # 2024's naked-eye comet
        pons_brooks = 12P                 # the 2024 "devil comet"
        churyumov_gerasimenko = 67P       # the Rosetta comet
        tempel1 = 9P                      # Deep Impact's target
        wild = 81P                        # Stardust's target
        hartley = 103P                    # EPOXI's target
        machholz = 96P                    # Southern Delta Aquariids parent
        giacobini_zinner = 21P            # Draconids parent
```

Some famous names are honestly absent from the current-elements file — 109P/Swift-Tuttle and
55P/Tempel-Tuttle among them, their long-period orbits retired by the MPC — and configuring
them would serve `N/A`, per the vanishing-row policy.

The tag name on the left of each satellite and comet line is yours to choose: it becomes the
tag (`$almanac.iss.next_pass`), the label on the Sky page, and the key for
[translating](i18n.md) that body's name.  Names that would shadow a planet, a star, `hip_`
or `sat_` are rejected.

{: .note }
This is weewx-skyfield's own top-level `[Skyfield]` section.  It is unrelated to the
`[[Skyfield]]` subsection of `[Almanac]` used by the independent weewx-skyfield-almanac
extension, which is a different project.

### Turning the downloads off

Both download switches exist for the same reason: an isolated network.  With
`satellite_downloads = false` or `comet_downloads = false` the extension fetches nothing,
ever — the behavior every release before 2.0 had unconditionally — and you maintain the
element files yourself.  The details, including where the files live and what an air-gapped
station copies in, are on the [installation page](installation.md#satellites).

## The Sky page's report stanza

[The Sky page](sky-page.md) is generated by the `[[SkyfieldReport]]` stanza the installer
adds under `[StdReport]`:

```ini
[StdReport]
    [[SkyfieldReport]]
        skin = Skyfield
        enable = true
        HTML_ROOT = skyfield
```

Every option below can be set there, overriding the bundled `skin.conf`.  Setting them in
`weewx.conf` rather than editing `skin.conf` is what makes them survive an upgrade.

| Option | Default | Effect |
|---|---|---|
| `enable` | `true` | Set `false` to skip generating the page entirely.  The almanac tags keep working — this governs only the bundled page. |
| `theme` | `dark` | `dark` (the night plate), `light` (a paper-atlas plate), or `auto` — light while the sun is up at generation time, dark otherwise.  Colors are baked in at generation, not switched in the browser, so `auto` follows sunrise and sunset within one archive interval. |
| `star_mag_limit` | `5.0` | Plot stars at least this bright.  Magnitudes run backwards: 6.5 is the naked-eye limit, Sirius is −1.4.  The default is roughly 800 stars. |
| `star_label_mag` | `2.5` | Label named stars at least this bright. |
| `constellation_lines` | `true` | Draw the 88 IAU constellations' stick figures under the stars.  `false` gives the plain dome. |
| `lang` | `en` | The page's language.  Eight translations ship, beside the English reference — see [Translations](i18n.md). |
| `report_timing` | *(none)* | Standard WeeWX report timing.  By default the page redraws every archive interval, which is what keeps the dome current; set this to draw it on a schedule of your own instead.  Most stations leave it alone — see [Performance](performance.md). |
| `HTML_ROOT` | `skyfield` | Where the page lands, *relative to* your station's `[StdReport]` `HTML_ROOT`. |

{: .important }
Keep `HTML_ROOT` relative.  weectl prepends the station's own `[StdReport]` `HTML_ROOT` at
install time, so writing `public_html/skyfield` here installs the page to
`public_html/public_html/skyfield`.

To restore the sparse pre-2.0 dome — named stars only, before the complete catalog
shipped:

```ini
[StdReport]
    [[SkyfieldReport]]
        star_mag_limit = 2.6
        star_label_mag = 1.1
```

## Translation keys

Display names come from the report's `[Almanac]` section — the same section that holds
`moon_phases`, so usually a lang file.  Every key is optional; anything untranslated falls
back to English, so a partial list is fine.

```ini
[Almanac]
    moon = Mond
    polaris = Polarstern
    halley = Halley
    [[Constellations]]
        Psc = Fische
    [[MeteorShowers]]
        perseids = Perseiden
```

| Key | Read by |
|---|---|
| *body tag name* | `$almanac.<body>.label` — planets, stars, satellites and comets alike, keyed by the tag name |
| `[[Constellations]]` | `$almanac.<body>.constellation.label`, keyed by IAU abbreviation |
| `[[MeteorShowers]]` | `$almanac.next_meteor_shower.label`, keyed by shower name |

This whole section needs **WeeWX 5.3 or later**, which is what began handing an almanac the
report's `[Almanac]` texts.  On 5.2 the keys above are read by nothing — the names stay
English and Latin — while `moon_phases`, in the same section, still works, as does the rest
of the Sky page's translation.

The lookup follows each report's own language, so the entry belongs in the report that uses
the tag.  Putting it under `[StdReport]` `[[Defaults]]` `[[[Almanac]]]` in `weewx.conf`
applies it to every report at once and survives skin upgrades — see
[Translations](i18n.md#one-place-for-the-whole-station-defaults).

## Unit and format overrides

The unit-aware distance tags (`$almanac.mars.distance`, `.distance_from_sun`) report in
`group_distance_astronomical`, whose display unit is the astronomical unit in every unit
system — interplanetary distances read naturally in AU, not in ten-digit kilometres.  A skin
can restyle the whole family:

```ini
[Units]
    [[Groups]]
        group_distance_astronomical = km      # report kilometres everywhere instead
    [[StringFormats]]
        astronomical_unit = %.4f              # the default precision
    [[Labels]]
        astronomical_unit = " AU"             # the default label
```

Individual tags still convert on ask without any of this: `$almanac.moon.distance.km`,
`$almanac.mars.distance.mile`.

{: .note }
If you override `group_deltatime` or `group_time` for a report that weewx-loopdata reads,
pin the unit when a template consumes a `.raw` value — an unpinned `.raw` follows the
report's converter.  This is the trap behind [issue #2](values-and-units.md#the-raw-trap),
and [Values, units and types](values-and-units.md) has the full explanation.

## Checking what took effect

After any change, restart WeeWX and watch the log.  The extension announces itself, names
what it registered, and warns about anything in `[Skyfield]` it did not recognize.
[Troubleshooting](troubleshooting.md) lists the log lines and what each one means.
