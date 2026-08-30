# weewx-skyfield — The drop-in upgrade for WeeWX's almanac
Open source plugin for WeeWX software.

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)

[![Read the manual](assets/btn-manual.svg)](https://chaunceygardiner.github.io/weewx-skyfield/)
[![Download weewx-skyfield.zip](assets/btn-download.svg)](https://github.com/chaunceygardiner/weewx-skyfield/releases/latest/download/weewx-skyfield.zip)
[![Report an issue](assets/btn-issue.svg)](https://github.com/chaunceygardiner/weewx-skyfield/issues)

The manual covers installation, every almanac tag, the Sky page, configuration,
translations and troubleshooting — with search.

**This extension requires Python 3.9 or later, WeeWX 5.2 or later, and the
[Skyfield](https://rhodesmill.org/skyfield/) (1.47 or later) and NumPy libraries.  PyEphem is
NOT required.**

Skyfield 1.47 is the minimum supported version; development and the test suite track the
current Skyfield release (1.55 as of August 2026), so if you have an earlier version
installed, upgrading is recommended — see
[Upgrading Skyfield](https://chaunceygardiner.github.io/weewx-skyfield/installation.html#upgrading-skyfield).

## Description

weewx-skyfield replaces WeeWX's built-in almanac (PyEphem or weeutil) for report
generation.  Report tags such as `$almanac.sunrise`, `$almanac.moon.transit`,
`$almanac(horizon=-6).sun(use_center=1).rise` and `$almanac.next_full_moon` (as used, for
example, in the Seasons skin's Celestial page) are computed with Skyfield and JPL's DE421
ephemeris, which is installed with the extension — *much* more accurate values than PyEphem,
which is deprecated by its own author in favor of Skyfield.

No skin changes are needed: the extension answers the same `$almanac` tags as the built-in
almanac.  Install it, restart WeeWX, and every report generated from then on uses Skyfield
values.  The ephemeris is read fully into memory at startup (about 16 MB), so upgrading over
a running WeeWX cannot disturb — or crash — the running almanac.

Installing the extension also installs **The Sky**, pictured below — a planetarium-style
page drawn entirely from your station's own latitude, longitude and elevation, published at
`<HTML_ROOT>/skyfield/index.html` and regenerated with live values every report cycle.  It is
a showcase for what the almanac now knows: the sky above you right now, today's rise and set
times, the year's arc of the sun, the current lunation, the next satellite pass.  Nothing on
it is fetched from beyond the page's own directory — self-contained HTML and inline SVG,
with a stylesheet and a few lines of script beside it — and every panel on it can be dropped
into a skin of your own.

[Tour the Sky page](https://chaunceygardiner.github.io/weewx-skyfield/sky-page.html) ·
[embed its panels](https://chaunceygardiner.github.io/weewx-skyfield/panels.html)

![The Sky page](https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/SkyfieldSampleReport.png)

## What you get

- **Every standard tag, computed natively.**  Rise/set/transit with custom horizons and
  `use_center`, positions, magnitudes, phases, equinoxes, solstices and moon phases for the
  sun, the moon and all planets (plus Pluto).  PyEphem is not required for any tag used by
  WeeWX's standard skins.
  → [Almanac tags](https://chaunceygardiner.github.io/weewx-skyfield/tags.html) ·
  [the A–Z tag index](https://chaunceygardiner.github.io/weewx-skyfield/tag-index.html)

- **All 118,218 Hipparcos stars, bundled.**  `$almanac.rigel.mag`,
  `$almanac.polaris.circumpolar`, and any catalog star as `$almanac.hip_57939` — the IAU
  Catalog of Star Names plus PyEphem's names for backward compatibility.  Nothing to
  download.

- **Satellites** (2.0).  Track any satellite by NORAD catalog number, with the ISS and
  Tiangong configured out of the box.  `$almanac.iss.next_visible_pass` says when to step
  outside and watch: when it appears, how high it peaks, when it disappears.  Orbital
  elements refresh automatically, with one switch to turn the fetching off.

- **Comets** (2.1).  Any comet the Minor Planet Center tracks, added by designation, with
  Halley and Hale-Bopp configured out of the box — each with the full planet-style tag
  surface, a tailed diamond on the sky dome and a marker in the orrery.

- **Meteor showers, supermoons, the equation of time** (2.1).
  `$almanac.next_meteor_shower` counts down to a peak *computed* from the sun's ecliptic
  longitude; moon perigee/apogee and `$almanac.next_supermoon` bring the supermoon rule into
  the almanac, with Earth's perihelion and aphelion beside them; solar time and the equation
  of time get tags and a chart panel.

- **Eclipses and constellations** — tag families with no PyEphem counterpart at all.
  `$almanac.next_eclipse` finds the next eclipse *visible from your station*, and every body
  reports the constellation it stands in.

- **The Sky page** (pictured above) — a full-sky-map dome, rise & set ribbons, the sun's
  path, the solar year, the lunar month, an orrery, an analemma, an equation-of-time curve,
  satellite pass predictions and a countdown row for the next equinox, eclipse and meteor
  shower — on a night plate or a paper one (`theme = light`, or `auto` to follow the sun;
  [both are pictured](https://chaunceygardiner.github.io/weewx-skyfield/sky-page.html#the-two-plates)).
  Every panel can be embedded in your own skin.
  → [Tour the page](https://chaunceygardiner.github.io/weewx-skyfield/sky-page.html) ·
  [embed its panels](https://chaunceygardiner.github.io/weewx-skyfield/panels.html)

- **Speaks your language** (1.12).  The Sky page, its panels and the almanac's body names are
  translatable through WeeWX's own lang files, with per-string English fallback.  (Body,
  constellation and meteor shower names need WeeWX 5.3 or later; the page itself translates
  on 5.2.)
  Complete German, French and Danish (all from native speakers) and Dutch, Spanish, Italian,
  Norwegian and Swedish (Beta) translations ship with the skin.
  → [How to translate](https://chaunceygardiner.github.io/weewx-skyfield/i18n.html)

- **Fast.**  A transparent result cache reuses expensive rise/set searches within and across
  report cycles — on a heavy eight-page site, template generation dropped from ~17.7 s per
  report cycle to ~4.6 s.
  → [Performance](https://chaunceygardiner.github.io/weewx-skyfield/performance.html)

## Installation

1. Install Skyfield (1.47 or later).  For a pip/venv WeeWX install:

   ```
   source /home/weewx/weewx-venv/bin/activate
   pip install 'skyfield>=1.47'
   ```

2. Download `weewx-skyfield.zip` from the
   [releases page](https://github.com/chaunceygardiner/weewx-skyfield/releases/latest).  It is
   a large download: the bundled DE421 ephemeris (17 MB) and the complete Hipparcos star
   catalog (15 MB gzipped) are most of it, with the documentation's screenshots accounting
   for nearly all the rest.

3. Install it:

   ```
   weectl extension install weewx-skyfield.zip
   ```

4. Restart WeeWX, then check the log for the line that confirms your reports are now using
   Skyfield:

   ```
   Skyfield almanac registered; reports will use Skyfield for almanac computations.
   ```

Reports generated from then on use Skyfield almanac values, and
[the Sky page](https://chaunceygardiner.github.io/weewx-skyfield/sky-page.html) appears at
`<HTML_ROOT>/skyfield/index.html` after the first report cycle.

The manual has the full steps, including Debian package installs, the
[configuration reference](https://chaunceygardiner.github.io/weewx-skyfield/configuration.html),
and what to do when
[something is not working](https://chaunceygardiner.github.io/weewx-skyfield/troubleshooting.html).

Upgrading from an earlier release?  Three things need attention — the removed `stars`
option, the one tag whose units changed, and the `classic-` palettes dropped in 2.3 — and all
three are on the
[Upgrading page](https://chaunceygardiner.github.io/weewx-skyfield/upgrading.html).  The
full history is in
[changes.txt](https://github.com/chaunceygardiner/weewx-skyfield/blob/main/changes.txt).

## Network access, and how to turn it off

Everything this extension needs to compute is bundled — the DE421 ephemeris, the complete
Hipparcos catalog, the constellation figures.  Two things cannot be, because they go stale:

- **satellite orbital elements**, fetched from [CelesTrak](https://celestrak.org) at install
  (unless what is cached is still current), at any startup that finds them missing or stale,
  then about every three hours;
- **comet orbital elements**, one Minor Planet Center file, on the same shape at a gentler
  cadence — about every two days.

Both are on by default, because satellites and comets are configured out of the box.  Each
has a switch, and with both off the extension makes no network request, ever — the behavior
every release before 2.0 had unconditionally:

```
[Skyfield]
    satellite_downloads = false
    comet_downloads = false
```

A fresh install already writes both lines into `[Skyfield]`, commented out and showing their
default of `true`: uncomment them and change the value rather than adding a second copy.  An
upgrade never rewrites an existing `[Skyfield]`, so on a station installed earlier the lines
are either live already or not there at all — set them as shown above.

An isolated station can still use both features by maintaining the element files itself.  See
[Satellites](https://chaunceygardiner.github.io/weewx-skyfield/installation.html#satellites)
and [Comets](https://chaunceygardiner.github.io/weewx-skyfield/installation.html#comets).

## weewx-skyfield in action

The celestial pages of
[www.paloaltoweather.com](https://www.paloaltoweather.com/celestial.html) — Today, Sun, Moon,
Planets and Stars — demonstrate what can be accomplished with this extension, live.

## Live-updating pages

weewx-skyfield computes at report time: its tags, and the Sky page, refresh once per report
cycle.  For pages that update continuously in the browser, add
[weewx-loopdata](https://github.com/chaunceygardiner/weewx-loopdata) (same author, 6.9 or
later): its *almanac fields* — report almanac tags with the `$` removed — are evaluated
against the registered almanac on every loop packet.  One computation engine serves the
report tags and the live values, so they always agree.

![weewx-skyfield's sky dome during a Tiangong zenith pass, animated live on the weewx-celestial page](https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/live_dome_tiangong.gif)

*The animation is the [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial)
live page at work, moved by weewx-loopdata fields — weewx-skyfield's own Sky page stays
static.  The chart itself is this extension's dome, embedded there.  A third of the way
across, still climbing, the marker inverts to a hollow ring as Tiangong slips into Earth's
shadow — and it goes on to cross the exact center of the dome dark, no longer shining.*

→ [Live-updating pages](https://chaunceygardiner.github.io/weewx-skyfield/live-pages.html)

## Relationship to other extensions

- [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) (same author, 8.1 or
  later) ships a live celestial page driven by weewx-loopdata almanac fields.  Since celestial
  6.0 it runs no service and computes nothing itself, so the two extensions coexist with no
  configuration — weewx-skyfield is the atlas, weewx-celestial the live instrument.  (Only the
  historical celestial 3.x, which embedded this same almanac engine, needs
  `replace_builtin_almanac = false` when run alongside weewx-skyfield.)
- weewx-skyfield-almanac (by a different author) is an independent Skyfield almanac extension
  with a different design: it downloads its ephemerides and star catalogs at runtime, where
  this extension bundles them and fetches only the orbital elements that go stale (see
  [Network access](#network-access-and-how-to-turn-it-off) above).  Choose one or the other;
  installing both would leave reports using whichever registered last.

## Testing

A pytest suite lives in the `tests` directory.  It exercises the almanac, the Sky page and
the manual itself.  Two permanent audits guard the almanac — everything the built-in almanac
can do still works with PyEphem installed, and every supported tag works without it — and a
further set keeps the manual and the code in lockstep: every served tag appears in the tag
index, every documented option and default is one the code actually reads, every internal
link and anchor resolves, the translation dictionary matches the skin's `en.conf` verbatim,
the thresholds the manual quotes match the constants they came from, and every tag chain
printed on the recipes page is evaluated against a real almanac.  Run it with the Python from your WeeWX virtual
environment:

```
/home/weewx/weewx-venv/bin/python -m pytest tests
```

The suite never touches the network: the star tests use the bundled catalog, and the
satellite tests use archived orbital-element fixtures in `tests/data`.

## Credits

weewx-skyfield stands on the work of others:

 * **Brandon Rhodes**, author of the [Skyfield](https://rhodesmill.org/skyfield/) astronomy
   library that performs every computation in this extension.
 * **NASA's Jet Propulsion Laboratory (JPL)**, whose DE421 planetary ephemeris (bundled as
   `wxskyfield_de421.bsp`) provides the positions of the sun, moon, and planets.
 * The **European Space Agency (ESA)**, whose Hipparcos mission produced the star catalog
   bundled as `wxskyfield_stars.dat.gz`, and the
   **CDS (Strasbourg astronomical Data Centre)**, which distributes it via VizieR
   (catalog I/239).
 * **[CelesTrak](https://celestrak.org)** (T.S. Kelso), whose GP element service supplies
   the satellite orbital elements.
 * The **[Minor Planet Center](https://www.minorplanetcenter.net)**, whose published
   CometEls.txt supplies the comet orbital elements.
 * The **[International Meteor Organization (IMO)](https://www.imo.net)**, whose working
   list of visual meteor showers supplies the shower dates, radiants, ZHRs and parent
   bodies.
 * The **[Stellarium](https://stellarium.org) project's contributors**, whose "modern" sky
   culture supplies the constellation stick figures (bundled as `wxskyfield_lines.dat`).
 * The **International Astronomical Union (IAU)** Working Group on Star Names, whose Catalog
   of Star Names supplies the named-star tags.
 * The **U.S. Naval Observatory (USNO)** and **Jean Meeus**, whose published definitions and
   algorithms are the reference for rise/set, twilight, and other almanac conventions.
 * **Tom Keffer, Matthew Wall, and the WeeWX project**, whose almanac framework this
   extension plugs into.
 * **Gert Andersen**, who contributed the Danish translation, and **Christian (peters77)**,
   who reviewed the German.
 * **Jacques Terrettaz**, who reviewed the French translation, suggested the dome's
   constellation figures, and spotted that bright unnamed stars — gamma Cassiopeiae chief
   among them — were leaving holes in those figures, which is why the dome now draws the
   complete catalog.

## Licensing

weewx-skyfield is licensed under the GNU Public License v3.

The bundled star catalog (`wxskyfield_stars.dat.gz`) contains data from the Hipparcos and
Tycho Catalogues, which ESA distributes under the
[CC BY-NC 3.0 IGO](https://creativecommons.org/licenses/by-nc/3.0/igo/) licence.  Credit: ESA.

The bundled constellation figures (`wxskyfield_lines.dat`) are distilled from the
[Stellarium](https://stellarium.org) project's "modern" sky culture, whose data is licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).  Credit: the Stellarium
contributors.
