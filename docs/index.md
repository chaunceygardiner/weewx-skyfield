---
title: Home
layout: default
nav_order: 1
permalink: /
description: Skyfield-powered $almanac tags, stars, satellites, comets, eclipses, and a planetarium-style Sky page for WeeWX 5.2+.
---

# weewx-skyfield — The drop-in upgrade for WeeWX's almanac

**The drop-in upgrade for WeeWX's almanac** — Skyfield-powered `$almanac` tags, stars,
satellites, comets, eclipses, and a planetarium-style Sky page.

[View on GitHub](https://github.com/chaunceygardiner/weewx-skyfield){: .btn .btn-primary }
[Download weewx-skyfield.zip](https://github.com/chaunceygardiner/weewx-skyfield/releases/latest/download/weewx-skyfield.zip){: .btn }
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues){: .btn }

weewx-skyfield replaces WeeWX's built-in almanac (PyEphem or weeutil) for report
generation.  Report tags such as `$almanac.sunrise`, `$almanac.moon.transit`,
`$almanac(horizon=-6).sun(use_center=1).rise` and `$almanac.next_full_moon` (as used, for
example, in the Seasons skin's Celestial page) are computed with
[Skyfield](https://rhodesmill.org/skyfield/) and JPL's DE421 ephemeris, which is installed
with the extension — *much* more accurate values than PyEphem,
which is deprecated by its own author in favor of Skyfield.

No skin changes are needed: the extension answers the same `$almanac` tags as the built-in
almanac.  Install it, restart WeeWX, and every report generated from then on uses Skyfield
values.

Installing the extension also installs **The Sky**, pictured below — a planetarium-style
page drawn entirely from your station's own latitude, longitude and elevation, published at
`<HTML_ROOT>/skyfield/index.html` and regenerated with live values every report cycle.  It
is a showcase for what the almanac now knows: the sky above you right now, today's rise and
set times, the year's arc of the sun, the current lunation, the next satellite pass.
Nothing on it is fetched from beyond the page's own directory — self-contained HTML and
inline SVG, with a stylesheet and a few lines of script beside it — and every panel on it can
be dropped into a skin of your own.

[Tour the Sky page](sky-page.md) · [embed its panels](panels.md)

![The Sky page](https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/SkyfieldSampleReport.png)

## Highlights

- **Every standard tag, computed natively.**  Rise/set/transit with custom horizons and
  `use_center`, positions, magnitudes, phases, equinoxes, solstices and moon phases for the
  sun, the moon and all planets (plus Pluto) — PyEphem is not required for any tag used by
  WeeWX's standard skins.  See the [almanac tag reference](tags.md).
- **All 118,218 Hipparcos stars, bundled.**  `$almanac.rigel.mag`,
  `$almanac.polaris.circumpolar` — the IAU Catalog of Star Names plus PyEphem's names for
  backward compatibility — and, as of 2.0, the *complete* Hipparcos catalog ships with the
  extension, so any star answers as `$almanac.hip_57939`, nothing to download.
- **Satellites** — new in 2.0: track any satellite, by NORAD catalog number, with the ISS
  and Tiangong configured out of the box.  `$almanac.iss.next_visible_pass` says when to
  step outside and watch the ISS cross your sky — when it appears, how high it peaks, when
  it disappears — with orbital elements kept fresh automatically (one switch turns the
  fetching off).  See [the satellite tags](tags.md#satellites).
- **Comets** — new in 2.1: any comet the Minor Planet Center tracks, added to `weewx.conf`
  by designation, with Halley and Hale-Bopp configured out of the box.  Each serves the full
  planet-style tag surface (`$almanac.halley.rise`, `.mag`, `.perihelion`) and rides the Sky
  page — a tailed diamond on the dome, a marker in the orrery — with elements kept fresh
  automatically, the satellites' way (one switch turns the fetching off).  See
  [the comet tags](tags.md#comets).
- **Meteor showers, supermoons, the equation of time** — also new in 2.1:
  `$almanac.next_meteor_shower` counts down to a peak *computed* from the sun's ecliptic
  longitude (the radiant marked on the dome while a shower is active); moon perigee/apogee
  and `$almanac.next_supermoon` bring the supermoon rule into the almanac, with Earth's
  perihelion and aphelion beside them; and solar time and the equation of time get tags and
  a chart panel.  See [the meteor shower tags](tags.md#meteor-showers).
- **Eclipses and constellations** — tag families with no PyEphem counterpart at all:
  `$almanac.next_eclipse` finds the next eclipse *visible from your station*, and every body
  reports the constellation it stands in (`$almanac.saturn.constellation`).
- **The Sky page** (pictured above) — a full-sky-map dome, rise & set ribbons, the sun's
  path, the solar year, the lunar month, an orrery, an analemma, an equation-of-time curve,
  satellite pass predictions and a countdown row for the next equinox, eclipse and meteor
  shower — on a night plate or a paper one (`theme = light`, or `auto` to follow the sun).
  [Tour the page](sky-page.md), see [both plates](sky-page.md#the-two-plates), or
  [embed its panels in your own skin](panels.md).
- **Speaks your language** — new in 1.12: the Sky page, its panels and the almanac's body
  names (`$almanac.moon.label`) are translatable through WeeWX's own lang files, with
  per-string English fallback; complete German, French and Danish (all from native
  speakers) and Dutch, Spanish, Italian, Norwegian and Swedish (Beta) translations ship
  with the skin.
  1.13 adds the constellations (`$almanac.saturn.constellation.label`), all 88 in each.
  (Body, constellation and meteor shower names need WeeWX 5.3 or later; the page itself
  translates on 5.2.)  [How to translate](i18n.md).
- **Safe to upgrade over a running WeeWX.**  The ephemeris is read fully into memory at
  startup (about 16 MB), so replacing the extension's files cannot disturb — or crash — the
  running almanac; the new files take effect on the restart that follows the install.
- **Fast.**  A transparent result cache reuses expensive rise/set searches within and across
  report cycles — on a heavy eight-page site, template generation dropped from ~17.7 s per
  report cycle to ~4.6 s.  Details under [the result cache](performance.md#the-result-cache).

## The manual

| Start here | |
|---|---|
| [Installation](installation.md) | Install, upgrade Skyfield, confirm it took, uninstall |
| [Configuration](configuration.md) | Every option in one place, with its default |
| [Upgrading](upgrading.md) | What an existing user needs to know, release by release |

| Using the almanac | |
|---|---|
| [Almanac tags](tags.md) | What the tag families mean |
| [Tag index](tag-index.md) | Every tag A–Z: type, units, and the release it arrived in |
| [Values, units and types](values-and-units.md) | Degrees vs radians, ValueHelpers, and the `.raw` trap |
| [Recipes](recipes.md) | Paste-able template snippets |
| [Accuracy and conventions](accuracy.md) | Where this differs from PyEphem, and why |

| The page, and beyond it | |
|---|---|
| [The Sky page](sky-page.md) | The bundled showcase page, panel by panel |
| [Panels in your own skin](panels.md) | Embedding `$sky_page` in any skin |
| [Live-updating pages](live-pages.md) | Driving a continuously-updating page with weewx-loopdata |

| Reference | |
|---|---|
| [Translations](i18n.md) | The eight bundled translations, and how to add one |
| [Performance](performance.md) | The result cache, and tuning for small hardware |
| [Glossary](glossary.md) | Transit, elongation, ZHR — the vocabulary this manual uses |
| [Troubleshooting](troubleshooting.md) | Symptoms, log messages, and known Skyfield issues |

## Requirements

- Python 3.9 or later
- WeeWX 5.2 or later (translated body, constellation and meteor shower names need 5.3 —
  see [Translating the Sky page](i18n.md#how-it-works))
- [Skyfield](https://rhodesmill.org/skyfield/) 1.47 or later, and NumPy
- PyEphem is **not** required

Skyfield 1.47 is the minimum supported version; development and the test suite track the
current Skyfield release, so upgrading is recommended — see
[Upgrading Skyfield](installation.md#upgrading-skyfield).

## Quick start

```
weectl extension install weewx-skyfield.zip
```

then restart WeeWX — the [installation page](installation.md) has the full steps, including
installing the Skyfield prerequisite.

## weewx-skyfield in action

The celestial pages of
[www.paloaltoweather.com](https://www.paloaltoweather.com/celestial.html) — Today, Sun, Moon,
Planets and Stars — demonstrate what can be accomplished with this extension, live.

## Live-updating pages

weewx-skyfield computes at report time: its tags — and the Sky page — refresh once per report
cycle.  For pages that update continuously in the browser, add
[weewx-loopdata](https://github.com/chaunceygardiner/weewx-loopdata) (same author, 6.9 or
later): its *almanac fields* — report almanac tags with the `$` removed — are evaluated
against the registered almanac (this extension's, once installed) on every loop packet and
published in `loop-data.txt` for the page's JavaScript to pick up.  One computation engine
serves the report tags and the live values, so they always agree.
[weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) (8.1 or later) is a
complete worked example — a live Geocentric panel built entirely from loopdata almanac fields — and the
paloaltoweather.com pages above update the same way.

![weewx-skyfield's sky dome during a Tiangong zenith pass, animated live on the weewx-celestial page](https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/live_dome_tiangong.gif)

*The animation is the [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial)
live page at work, moved by
[weewx-loopdata](https://github.com/chaunceygardiner/weewx-loopdata) fields —
weewx-skyfield's own Sky page stays static, refreshing once per report cycle.  The chart
itself is this extension's dome, embedded there.  A third of the way across, still climbing, the marker
inverts to a hollow ring as Tiangong — one of the two satellites the installer configures
out of the box — slips into Earth's shadow; it goes on to cross the exact center of the
dome dark, no longer shining.  In the opening seconds Terra is finishing its own low western
pass: two satellites on the dome at once.  2-second frames played at 15 fps (about 30×
speed), replayed through the live page with the orbital elements Space-Track archived for
July 15.*

## Relationship to other extensions

- [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) (same author, 8.1 or
  later) ships a live celestial page driven by weewx-loopdata almanac fields (see
  [Live-updating pages](#live-updating-pages) above).  Since celestial 6.0 it runs no service
  and computes nothing itself, so the two extensions coexist with no configuration —
  weewx-skyfield is the atlas, weewx-celestial the live instrument.  (Only the historical
  celestial 3.x, which embedded this same almanac engine, needs `replace_builtin_almanac =
  false` in the `[Celestial]` section of `weewx.conf` when run alongside weewx-skyfield.)
- weewx-skyfield-almanac (by a different author) is an independent Skyfield almanac extension
  with a different design (it downloads its ephemerides and catalogs at runtime).  Choose one
  or the other; installing both would leave reports using whichever registered last.

## Credits

weewx-skyfield stands on the work of others: **Brandon Rhodes**, author of the
[Skyfield](https://rhodesmill.org/skyfield/) astronomy library that performs every computation
in this extension; **NASA's Jet Propulsion Laboratory (JPL)**, whose DE421 planetary ephemeris
provides the positions of the sun, moon, and planets; the **European Space Agency (ESA)**,
whose Hipparcos mission produced the star catalog, and the **CDS (Strasbourg astronomical Data
Centre)**, which distributes it via VizieR; **[CelesTrak](https://celestrak.org)**
(T.S. Kelso), whose GP element service supplies the satellite orbital elements; the
**[Minor Planet Center](https://www.minorplanetcenter.net)**, whose CometEls.txt supplies
the comet orbital elements; the
**[International Meteor Organization (IMO)](https://www.imo.net)**, whose working list of
visual meteor showers supplies the shower dates, radiants, ZHRs and parent bodies; the
**[Stellarium](https://stellarium.org) project's contributors**, whose "modern" sky culture
supplies the constellation stick figures; the
**International Astronomical Union (IAU)**
Working Group on Star Names, whose Catalog of Star Names supplies the named-star tags; the
**U.S. Naval Observatory (USNO)** and **Jean Meeus**, whose published definitions and
algorithms are the reference for rise/set, twilight, and other almanac conventions; and
**Tom Keffer, Matthew Wall, and the WeeWX project**, whose almanac framework this extension
plugs into.  **Gert Andersen** contributed the Danish translation and
**Christian (peters77)** reviewed the German.  **Jacques Terrettaz** reviewed the French,
suggested the dome's constellation figures, and spotted that bright unnamed stars were
leaving holes in them — which is why the dome now draws the complete catalog.

## Licensing

weewx-skyfield is Copyright (C)2022-2026 by John A Kline and licensed under the GNU Public
License v3.  The bundled star catalog contains data from the Hipparcos and Tycho
Catalogues, which ESA distributes under the
[CC BY-NC 3.0 IGO](https://creativecommons.org/licenses/by-nc/3.0/igo/) licence.  Credit: ESA.
The bundled constellation figures are distilled from the
[Stellarium](https://stellarium.org) project's "modern" sky culture, whose data is licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).  Credit: the Stellarium
contributors.
