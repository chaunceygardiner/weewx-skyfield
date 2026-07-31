---
title: weewx-skyfield almanac tag reference
description: The $almanac tags weewx-skyfield computes natively — bodies, stars, eclipses, constellations — plus its differences from PyEphem and the result cache.
---

# Almanac tag reference

[Home](index.md) ·
[Installation](installation.md) ·
[The Sky page](sky-page.md) ·
[Sky panels in your skin](panels.md) ·
[Translating (i18n)](i18n.md) ·
[GitHub project](https://github.com/chaunceygardiner/weewx-skyfield)

---

## Bodies

The Skyfield almanac natively computes, for the sun, the moon and all planets (plus Pluto):

- rise/set/transit, including `next_`/`previous_` rising, setting, transit and antitransit;
- custom horizons and `use_center` (for twilight tags such as
  `$almanac(horizon=-6).sun(use_center=1).rise`);
- azimuth/altitude, right ascension/declination (topocentric, astrometric and geocentric) and
  the hour angle;
- heliocentric longitude/latitude, elongation, earth and sun distance;
- visible time and its day-over-day change;
- magnitude (`$almanac.venus.mag`), percent illuminated (`$almanac.venus.phase`, plus the
  moon's PyEphem-style 0–1 fraction, `$almanac.moon.moon_phase`), and apparent
  angular size (`$almanac.sun.size`, `$almanac.moon.radius_size`);
- `circumpolar`/`neverup`, parallactic angle and sidereal time;
- the moon's libration, selenographic colongitude and subsolar latitude, Jupiter's central
  meridian longitudes and Saturn's ring tilt;
- equinoxes, solstices, moon phases and the moon index.

PyEphem is *not* required for any of these, nor for any tag used by WeeWX's standard skins.

There is no `$almanac.earth`: Earth is the observer, not a served body (PyEphem, which this
almanac replaces, has no Earth body either).  Earth's heliocentric coordinates are available
all the same — `$almanac.sun.hlongitude` and `$almanac.sun.hlatitude` report them, per the
XEphem convention (see [Differences from PyEphem](#differences-from-pyephem)).

## Constellations and eclipses

Two tag families (new in 1.9) have no PyEphem counterpart at all.

Every body, stars included, reports the constellation it currently stands in —
`$almanac.saturn.constellation` gives "Pisces" — judged from the observer's topocentric
place against the IAU boundaries (the boundary map ships inside the Skyfield library;
nothing is downloaded).  The value is the Latin name in every language (it is data:
templates comparing it and loopdata fields publishing it always see the same string), and
as of 1.13 it carries the other views of the answer as attributes:
`$almanac.saturn.constellation.abbr` gives "Psc", `.label` the translated display name from
the report's `[Almanac]` `[[Constellations]]` section keyed by IAU abbreviation
(`Psc = Fische`) falling back to the Latin, and `.name` the Latin name again.
`$almanac.saturn.constellation_abbr` remains as a legacy alias for `.abbr` — see
[Translating the Sky page](i18n.md).

And the almanac finds eclipses: `$almanac.next_lunar_eclipse` and
`$almanac.next_solar_eclipse` (with `previous_` counterparts) give the time of maximum eclipse
of the nearest eclipse *visible from the station* — the eclipsed body must be above the
horizon at maximum — and each has a `_type` companion: `penumbral`/`partial`/`total` for lunar
eclipses, and for solar eclipses the type as seen from *your* location
(`partial`/`annular`/`total`) — a station that catches only the penumbra of a total eclipse
reports `partial`, which is exactly what an observer there sees.  Lunar eclipses come from
Skyfield's `eclipselib`; solar eclipses this extension finds directly, testing each new moon
for a topocentric overlap of the solar and lunar discs at the station.  When a skin just wants
"the next eclipse, whichever kind", the combined `$almanac.next_eclipse` (and
`previous_eclipse`) picks the sooner (later) of the two, with `_kind` ("lunar"/"solar") and
`_type` companions — the Sky page's eclipse chip is written with exactly these three tags.

## Translated body names

Every body, stars included, carries a display name a skin can translate:
`$almanac.moon.label` (new in 1.12).  Add the tag name to the report's `[Almanac]` section —
the same section that holds `moon_phases`, so usually in a lang file — for example:

```ini
[Almanac]
    moon = Mond
    polaris = Polarstern
```

and `$almanac.moon.label` renders "Mond", `$almanac.polaris.label` "Polarstern".  Bodies the
report does not translate fall back to the English name, so a partial list is fine, and the
lookup follows each report's own language — the entry belongs in the report that uses the
tag, in its lang file or `skin.conf`, or per report in `weewx.conf`:

```ini
[StdReport]
    [[MyReport]]
        [[[Almanac]]]
            polaris = Polarstern
```

(the `weewx.conf` form survives skin and extension upgrades; under `[[Defaults]]` instead
of `[[MyReport]]` it applies to every report at once — see
[Your own reports and skins](i18n.md#your-own-reports-and-skins) and
[One place for the whole station](i18n.md#one-place-for-the-whole-station-defaults) on the
translation page).
On [live-updating pages](index.md#live-updating-pages), a weewx-loopdata almanac field such
as `almanac.moon.label` renders in the language of loopdata's target report — one language
per loopdata instance.

## Stars

Named stars (e.g., `$almanac.rigel.rise`, `$almanac.polaris.circumpolar`,
`$almanac.sirius.mag`) are computed natively.  The names are the official proper names of the
IAU Catalog of Star Names (every entry of the Working Group on Star Names' IAU-CSN list with a
Hipparcos number), plus PyEphem's 115 star names for backward compatibility (a few of those
are legacy spellings of the same stars, e.g. `albereo` for `albireo`) — 420 names in all,
covering 412 stars.  Multi-word names use underscores and diacritics are dropped
(`$almanac.kaus_australis.rise`, `$almanac.barnards_star.mag`).

Any other Hipparcos star can be addressed by catalog number: `$almanac.hip_57939.rise` — the
bundled catalog excerpt covers the named stars, and a user-installed full `hip_main.dat`
serves all 118,218 (see [Serving every Hipparcos star](installation.md#serving-every-hipparcos-star)).
The star positions, proper motions, parallaxes and magnitudes come from
`wxskyfield_stars.dat`, an excerpt of the Hipparcos Catalogue (The Hipparcos and Tycho
Catalogues, ESA SP-1200, 1997; distributed by CDS as VizieR catalog I/239) which is installed
along with the extension.

Unlike PyEphem, `earth_distance` and `sun_distance` work for stars (in astronomical units,
like the planets — e.g., `$almanac.proxima_centauri.earth_distance`), computed from the star's
Hipparcos parallax.

Star support can be turned off by setting `stars = false` in the `Skyfield` section of
`weewx.conf`.

## Fallback behavior

Anything this extension does not compute falls through to the next almanac in WeeWX's list —
the built-in PyEphem almanac when PyEphem is installed (e.g., named stars when the star
catalog is disabled, or direct PyEphem data attributes such as `$almanac.moon.a_epoch`).
Almanac times outside the span of the bundled DE421 ephemeris (mid-1899 through 2053) fall
through the same way.  Without PyEphem, such tags simply report per-tag errors rather than
breaking report generation.

## Differences from PyEphem

Where PyEphem and standard astronomical conventions differ, weewx-skyfield follows the
standard definitions rather than PyEphem:

- A custom horizon (e.g., `$almanac(horizon=-6)`) is treated as a geometric altitude: no
  atmospheric refraction is applied.  This matches the USNO definitions of civil, nautical and
  astronomical twilight.  (PyEphem applies refraction to a custom horizon unless the
  `pressure=0` idiom is used, which shifts twilight times by roughly 2-3 minutes.)  With the
  default horizon, rise and set include standard refraction (34 arcminutes) and the body's
  apparent radius, and `circumpolar`/`neverup` are judged against that same effective horizon,
  so they always agree with rise/set.  Note that an explicit `horizon=0` cannot be
  distinguished from the default (WeeWX supplies 0.0 when no horizon is given), so it receives
  the default refraction-and-radius treatment; for the geometric crossing of the true horizon,
  use `pressure=0` with `use_center=1`.
- `hlongitude`/`hlatitude` are true heliocentric (sun-centered) ecliptic coordinates for every
  body, including the moon.  (PyEphem reports the moon's *geocentric* ecliptic longitude under
  this name.)  For the sun itself, heliocentric coordinates are undefined, so Earth's
  heliocentric coordinates are reported, per the XEphem convention.  (Asked for Earth directly
  — `$almanac.earth.hlongitude` — the almanac has no such body: Earth is the observer; ask the
  sun.)
- `$almanac.<body>.ha`, the local apparent hour angle (new in 1.16, stars included), is a
  signed angle in decimal degrees like the almanac's other plain coordinates: 0 at transit,
  negative east of the meridian, positive west — the standard convention.  PyEphem reports
  the same angle in radians, usually wrapped to [0, 2π), so a template that read `ha`
  through the PyEphem fallback must drop its `math.degrees()` conversion.  `hlon` — PyEphem's
  own spelling of `hlong` — is likewise served natively in decimal degrees (radians via the
  old fallback), sun-reports-Earth convention included.  Like every plain-float angle, `ha`
  has a unit-aware sibling: `$almanac.<body>.hour_angle` is a ValueHelper honoring the
  report's unit settings and formatting, beside `azimuth`, `altitude` and `hlongitude`.
- The default horizon honors the almanac's `pressure` and `temperature` for rise/set:
  refraction is scaled from the standard 34 arcminutes, and WeeWX's documented `pressure=0`
  idiom turns it off entirely.
- `$almanac.separation()` takes two `(longitude, latitude)` tuples in radians and returns
  radians, per the WeeWX 5.2 almanac API.  It also accepts two of this almanac's own body
  binders — `$almanac.separation($almanac.mars, $almanac.venus)` — computed natively.  Calls
  made with PyEphem `Body` arguments are passed through to PyEphem when it is installed.
- Jupiter's central meridian longitudes (`$almanac.jupiter.cmlI`/`cmlII`) are computed from
  the IAU rotation elements (pole and System I/II rotation rates) and the light-time corrected
  geometry.  PyEphem's values differ from the IAU definition by about 0.8 degrees.
- The moon's libration (`libration_lat`/`libration_long`) and the selenographic position of
  the sun — its colongitude (`colong`) and latitude (`subsolar_lat`, new in 1.16) — follow
  Meeus, Astronomical Algorithms ch. 53 (optical libration; the physical libration, at most
  0.04 degrees, is neglected).  Saturn's ring tilt (`earth_tilt`/`sun_tilt`)
  follows Meeus ch. 45.  All are in radians, like PyEphem's — and each of these, along with
  `parallactic_angle` and `$almanac.separation()`, also carries the same answer in decimal
  degrees: append `.degrees` (`$almanac.moon.parallactic_angle.degrees`); `.radians` names the
  value itself.  The values are unchanged (plain floats in radians), so existing templates —
  including the `math.degrees($...)` idiom — keep working.

## The result cache

Report generation asks the almanac the same expensive questions over and over: every template
mention of `$almanac.moon.rise` runs a fresh rise search, a page rendered in desktop and
smartphone variants repeats each other's work, and the day-window verbs
(`rise`/`set`/`transit`, searched from local midnight) return the same instant for every
almanac time within the day.  Since 1.4, results are cached at the computation layer,
transparently — no configuration, no new tags:

- **Day-window searches** (rise/set/transit, the effective-horizon body radius, and the
  `next_*`/`previous_*` events) are reused across report cycles.  A "next full moon" found
  once is served until it happens; a day's moonrise is computed once, not once per mention per
  page per cycle.
- **Instantaneous positions** (alt/az, ra/dec, magnitudes, moon phase) are keyed on the exact
  timestamp: repeats within a cycle collapse (including desktop/smartphone twin pages), and
  time-traveled tags anchored to fixed instants (`almanac_time=` loops building calendars or
  analemmas) are reused across cycles.  A position at a *new* timestamp is always freshly
  computed — nothing that moves on a page is ever served stale.

Only raw floats are cached, never formatted values, so skins with different formatters cannot
leak into each other.  The one deliberate tolerance: rise/set cache keys quantize the
effective horizon to 0.002 degrees, because the default horizon scales refraction by the
almanac's current temperature and pressure, which drift a few thousandths of a degree between
report cycles.  Within a day, a cached rise/set may therefore be served under conditions
differing by up to that quantum — worth well under a second of event time (worst measured
0.64 s over a 15-hour replay of real sensor data), below the refraction model's own physical
uncertainty; the displayed minute agrees with a fresh computation except when the true time
sits within that fraction of a second of the boundary.  For perspective, an uncached answer is
itself a moving target: because refraction follows the live temperature and pressure, a fresh
computation of the same rise or set wanders a few seconds over the course of a day — the cache
tracks that wander well within the wander itself.  Cache pools are bounded and simply cleared
on overflow; correctness never depends on an entry being present.  Expect the first report
cycle after a WeeWX restart, and the first after local midnight, to run at full uncached cost
while the day's entries repopulate (in practice the midnight cycle is often much cheaper:
skins with calendar strips or day-window loops have already cached the new day's searches).

Measured on the eight-page paloaltoweather.com site (a heavy consumer: ~3,200 almanac tag
evaluations per cycle, Raspberry Pi 5): template generation dropped from ~17.7 s per report
cycle to ~4.6 s on warm cycles, with ~10 s for the first cycle after a restart.
