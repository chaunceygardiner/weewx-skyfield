---
title: Upgrading
layout: default
nav_order: 4
description: What changed for existing weewx-skyfield users — removed options, the one tag whose units changed, satellite times that now carry their date, markup changes for skins that embed the panels, the download switches, and the companion-extension version floors.
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

Read [Coming from 2.x](#coming-from-2x) as well: everything there applies to you too.

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

### If you print satellite times, one thing needs your attention

**Satellite times carry their date now (2.5).**  A pass's `rise`, `culmination` and `set` — on
`next_pass` and `next_visible_pass` — and a satellite's own `rise`, `transit` and `set`
printed a bare clock time, `03:11:25 AM`; they now print `06/22/2025 03:11:25 AM`.  A pass is
searched up to a week ahead, so a bare time made a pass three days out read as tonight.  To
keep the old look on one tag, format it in place —
`$almanac.iss.next_visible_pass.rise.format(format_string="%X")` — rather than overriding
`ephem_year` in `[Units]` `[[TimeFormats]]`, which would also restyle the equinoxes, the
moon-phase finders, meteor-shower peaks and a comet's perihelion.  Values are unchanged, and a
tag read through `.raw` is untouched.  See [How far away a time can
be](values-and-units.md#how-far-away-a-time-can-be).

### If you embed the panels, seven things need your attention

**Nothing you draw today has moved (2.7).**  Every chart method now takes `narrow`, and the
frame it does *not* take — the wide one, the default — is byte for byte what 2.6.2 drew, apart
from the corrected ring numbers described under *What's fixed* below.  If
you want the second drawing, ask for it: `narrow=True` gives the same data laid out for a
phone, at 360 units across with its type set to read in a hand.  It is a second drawing, not
a scaled one, so a page that serves both emits both and lets a media query choose; the
[panels page](panels.md#two-frames--the-narrow-argument) has the three lines of CSS and what
each panel thins.  Two things to know if a script of yours reads the charts: a narrow sky
chart declares its own center and radius on the `<svg>` root (`data-dome-cx`, `-cy`, `-r`) and
a chart without them is the wide frame's published `340/348/296`; and a page showing both
frames has two copies of every mark, so move them with `querySelectorAll`.

**The charts' labels sit together in one group now (2.5).**  Every `<text>` a sky dome or pass
chart carries — cardinals, ring figures, a pass's clocks, every name — is inside
`<g class="dome-labels" data-label-scale="…">` at the end of the SVG, where the cardinals,
ring figures and clocks used to be written beside the marks they annotate.  Positions and
sizes are unchanged; a stylesheet or a `querySelector` still finds the same elements.  Two
things this can break: *tests that assert on the markup's order*, and *live JavaScript that
moves a label by its `data-body`* on a chart asked for [label
layers](panels.md#the-sky-dome--dome_svg), which has one copy per layer — use
`querySelectorAll` and move them all.  A chart asked for no layers has exactly one.

**`label_scale` is checked (2.5).**  A value that is not a positive number now raises a
template error naming the argument, where it used to render 0px labels or blank the panel —
and a template error skips the whole page, leaving the previous copy on disk (see
[Troubleshooting](troubleshooting.md#a-page-stopped-updating-after-i-changed-a-sky_page-call)).
Numeric text such as `label_scale='0.8'` is still accepted.

**The dome declines to draw without this extension's almanac (2.4).**  On a station that
uses the `$sky_page` panels while the almanac service is *not* running — `enable = false`,
or the service missing from `data_services` — the sky dome now renders empty rather than
drawing a partial chart from PyEphem.  `$sky_page.can_draw()` is a published contract
meaning the dome, the pass chart, the satellite rows, the equation of time and the moon's
apsides come back empty, and a skin that gates on it has to be able to
trust it.  Register the almanac and the full dome returns.  A station running the almanac —
which is every normal install — is unaffected.

**The panels' marks carry classes now, not colors (2.4).**  What was `fill="#D3A94C"` on a
mark is `class="sky-fill-brass"`, marks that already carried a class carry the role class
beside it, and the charts' gradient and clipPath ids end in the plate name.  Two things this
can break in a skin of your own, neither of them the rendering:

- *Tests that assert on the markup.*  Grep your whole tree — a consumer's tests are where its
  picture of this markup is written down.
- *Live JavaScript that reads a mark's drawn paint,* which fails silently.
  `el.getAttribute('fill')` returns `null` now; use `getComputedStyle(el).fill`, or read the
  role classes, whose two states are one pair exchanged.  The `data-body`, `data-sunlit` and
  `data-bright` hooks are untouched and remain the durable way to find a mark.

**Two CSS rules to pick up if you copied rules piecemeal (2.4).**  `.bandlab`, for the labels
that sit on the twilight bands, and `.dot`, which paints the chip and table swatches from the
custom property the markup now carries — without that one the swatches have no color at all.
Taking the whole of `sky.css` needs nothing.  See [Restyling the
marks](panels.md#restyling-the-marks--the-role-classes).

**The `classic-night` and `classic-light` palettes are gone (2.3).**  They held the body
colors used before 1.5.  A skin still passing one to a `$sky_page` panel — or naming one in a
report's `theme` option — keeps rendering: it draws the current `night` or `light` plate and
logs one warning naming the replacement.  Change the name to `night` or `light` to silence
it.  If you have never passed a `palette` argument, there is nothing to do.

## What each release added

| Release | Worth knowing |
|---|---|
| **2.7** | Every chart draws in a second frame on request — `narrow=True` — laid out for a phone rather than scaled down for one: 360 units across, labels that read at 11 px or better on a 320 px screen, and detail thinned rather than shrunk where it will not fit.  The bundled Sky page now serves both and picks by viewport width.  The wide frame is unchanged, byte for byte, apart from the corrected ring numbers, so nothing else you draw today moves.  A narrow sky chart declares its own center and radius for live pages that reposition marks.  **Fixed:** the dome's and pass chart's altitude ring numbers named each other's rings from 1.0 until now — the label reading 30° sat on the 60° ring. |
| **2.6.2** | A deviation from WeeWX's built-in almanac, which is incorrect here: `visible_change()` with `use_center=1` measures both days to the body's center, where WeeWX measures the earlier day to the upper limb and reads about 160 seconds too negative for the sun.  Earlier releases gave WeeWX's answer.  See [Accuracy and conventions](accuracy.md#differences-from-pyephem).  Nothing to configure. |
| **2.6.1** | The English Sky page prints clock times 12-hour ("8:45 PM"), dates with their comma ("Aug 17, 2027") and durations spaced ("14 h 6 m"); the other bundled languages keep 24-hour times.  A skin that overrides one of the date, clock or duration [Texts] keys should take the renamed key (see changes.txt). |
| **2.6** | Every piece of text on the Sky page clears WCAG 4.5 and APCA Lc 60 in both themes: the night theme's gray and brass are lighter, star and constellation names stay legible while the sun is up, and no label lands on a planet, the sun or the moon.  Nothing to configure — but a skin that copied the night colors as hex values should take the new ones (see changes.txt). |
| **2.5** | Label layers on the sky dome and the pass chart: a page that serves a phone layout and a desktop layout from one URL asks for both label sizes at once, and the browser shows the one its viewport matches — nothing fetched, nothing scripted.  Every chart's labels now sit in one group at the end of the SVG (see the item above).  `label_scale` is checked.  Satellite times carry their date (see above).  The dome's 30° and 60° ring figures now draw above the stars, so a star no longer prints over one.  The manual's ISS pass recipe, which could not compile, is fixed. |
| **2.4** | Every mark in an SVG panel carries a class naming its role, and each panel brings its palette as CSS defaults of zero specificity — so an embedding skin can repaint the charts, including for a reader who switches themes in the browser.  See the three items above.  Three label colors changed to clear their contrast floors: on the dark theme, The Sun's Path's hour numbers are lighter, which is the release's only visible change to the default look. |
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
| [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) | **9.1 or later** with weewx-skyfield 2.4; **9.3 or later** to use label layers, which need weewx-skyfield 2.5 | Its live dome and pass chart consume this extension's `data-body` / `data-sunlit` / `data-bright` hooks and the `satellite_names()` / `comet_names()` contract, all of which are unchanged.  But its dome also reads how the station *drew* the pass marker in order to flip it between sunlit and in-shadow, and before 9.1 it read that from the marker's `fill` and `stroke` attributes, which 2.4 replaces with classes.  Under an older celestial the marker stops flipping — silently, with nothing logged; nothing else on either page is affected.  Install both and restart.  (celestial 8.3.3 and later read the `data-rise` / `data-set` window 2.3 added; older ones fall back to the loop feed's.) |

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
