---
title: weewx-skyfield — The drop-in upgrade for WeeWX's almanac
description: Skyfield-powered $almanac tags, stars, eclipses, and a planetarium-style Sky page for WeeWX 5.2+.
---

# weewx-skyfield

**The drop-in upgrade for WeeWX's almanac** — Skyfield-powered `$almanac` tags, stars,
eclipses, and a planetarium-style Sky page.

[Installation](installation.md) ·
[Almanac tags](tags.md) ·
[The Sky page](sky-page.md) ·
[Sky panels in your skin](panels.md) ·
[Translating (i18n)](i18n.md) ·
[GitHub project](https://github.com/chaunceygardiner/weewx-skyfield)

---

weewx-skyfield replaces WeeWX's built-in almanac (PyEphem or weeutil) for report
generation.  Report tags such as `$almanac.sunrise`, `$almanac.moon.transit`,
`$almanac(horizon=-6).sun(use_center=1).rise` and `$almanac.next_full_moon` (as used, for
example, in the Seasons skin's Celestial page) are computed with
[Skyfield](https://rhodesmill.org/skyfield/) and JPL's DE421 ephemeris, which is installed
with the extension — no downloads at runtime, and *much* more accurate values than PyEphem,
which is deprecated by its own author in favor of Skyfield.

No skin changes are needed: the extension answers the same `$almanac` tags as the built-in
almanac.  Install it, restart WeeWX, and every report generated from then on uses Skyfield
values.

![The Sky page](https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/SkyfieldSampleReport.png)

## Highlights

- **Every standard tag, computed natively.**  Rise/set/transit with custom horizons and
  `use_center`, positions, magnitudes, phases, equinoxes, solstices and moon phases for the
  sun, the moon and all planets (plus Pluto) — PyEphem is not required for any tag used by
  WeeWX's standard skins.  See the [almanac tag reference](tags.md).
- **420 named stars, or all 118,218.**  `$almanac.rigel.mag`, `$almanac.polaris.circumpolar` —
  the IAU Catalog of Star Names plus PyEphem's names for backward compatibility, served from a
  bundled Hipparcos excerpt; drop in the full catalog and address any star as
  `$almanac.hip_57939`.
- **Eclipses and constellations** — tag families with no PyEphem counterpart at all:
  `$almanac.next_eclipse` finds the next eclipse *visible from your station*, and every body
  reports the constellation it stands in (`$almanac.saturn.constellation`).
- **The Sky page** — a bundled, self-contained, planetarium-style showcase page computed for
  your station's location: a sky dome, rise & set ribbons, the sun's path, the solar year, the
  lunar month, an orrery, an analemma and more.  [Tour the page](sky-page.md), or
  [embed its panels in your own skin](panels.md).
- **Speaks your language** — new in 1.12: the Sky page, its panels and the almanac's body
  names (`$almanac.moon.label`) are fully translatable through WeeWX's own lang files, with
  per-string English fallback; complete German (native-speaker reviewed) and French (Beta)
  translations ship with the skin.
  1.13 adds the constellations (`$almanac.saturn.constellation.label`), all 88 in each.
  [How to translate](i18n.md).
- **Safe to upgrade over a running WeeWX.**  The ephemeris is read fully into memory at
  startup (about 16 MB), so replacing the extension's files cannot disturb — or crash — the
  running almanac; the new files take effect on the restart that follows the install.
- **Fast.**  A transparent result cache reuses expensive rise/set searches within and across
  report cycles — on a heavy eight-page site, template generation dropped from ~17.7 s per
  report cycle to ~4.6 s.  Details under [the result cache](tags.md#the-result-cache).

## Requirements

- Python 3.9 or later
- WeeWX 5.2 or later
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
[weewx-loopdata](https://github.com/chaunceygardiner/weewx-loopdata) (same author, 5.0 or
later): its *almanac fields* — report almanac tags with the `$` removed — are evaluated
against the registered almanac (this extension's, once installed) on every loop packet and
published in `loop-data.txt` for the page's JavaScript to pick up.  One computation engine
serves the report tags and the live values, so they always agree.
[weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) is a complete worked
example — a live Geocentric panel built entirely from loopdata almanac fields — and the
paloaltoweather.com pages above update the same way.

## Relationship to other extensions

- [weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) (same author) ships a
  live celestial page driven by weewx-loopdata almanac fields (see
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
Centre)**, which distributes it via VizieR; the **International Astronomical Union (IAU)**
Working Group on Star Names, whose Catalog of Star Names supplies the named-star tags; the
**U.S. Naval Observatory (USNO)** and **Jean Meeus**, whose published definitions and
algorithms are the reference for rise/set, twilight, and other almanac conventions; and
**Tom Keffer, Matthew Wall, and the WeeWX project**, whose almanac framework this extension
plugs into.

## Licensing

weewx-skyfield is Copyright (C)2022-2026 by John A Kline and licensed under the GNU Public
License v3.  The bundled star catalog excerpt contains data from the Hipparcos and Tycho
Catalogues, which ESA distributes under the
[CC BY-NC 3.0 IGO](https://creativecommons.org/licenses/by-nc/3.0/igo/) licence.  Credit: ESA.
