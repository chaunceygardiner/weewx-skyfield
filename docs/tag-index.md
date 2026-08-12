---
title: Tag index
layout: default
parent: Almanac tags
nav_order: 1
description: Every $almanac tag weewx-skyfield serves, A to Z — what each one returns, in what units, on which bodies, and the release it arrived in.
---

# Tag index

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Every tag this extension serves, with its type, its units and the release it arrived in.
[Almanac tags](tags.md) explains what the families *mean*; this page is the lookup.

A test keeps this page honest: `tests/test_docs_coverage.py` extracts the served tag names
from the source and fails if one is missing here, so a tag added without a line on this page
turns the suite red.

## How to read the Type column

Types matter more here than in most almanacs, because two tags can carry the same number in
different clothes — `$almanac.mars.alt` is a bare float, `$almanac.mars.altitude` is a
ValueHelper of the same angle.  [Values, units and types](values-and-units.md) is the full
story; the short version:

| Type in this page | What you get |
|---|---|
| **time** | A time ValueHelper.  Renders as a formatted time; `.raw` is a unix timestamp.  Empty (`N/A`) when there is no answer. |
| **duration** | A `group_deltatime` ValueHelper.  Pin the unit when reading `.raw` — see [the .raw trap](values-and-units.md#the-raw-trap). |
| **angle** | A `group_angle` ValueHelper, carried internally in radians and rendered per the report's settings. |
| **compass** | A `degree_compass` ValueHelper, so `.ordinal_compass` renders `WSW`. |
| **AU** | A `group_distance_astronomical` ValueHelper — "1.8588 AU" by default, converting on ask (`.km`, `.mile`). |
| **percent** | A `group_percent` ValueHelper. |
| **float °** | A plain float in decimal degrees. |
| **radians** | A plain float in radians, PyEphem's scale, which also carries `.degrees` and `.radians`. |
| **float** | A plain number, unitless or as noted. |
| **bool**, **str**, **int** | Plain Python values. |
| **object** | A value with attributes of its own, listed in its own section below. |

Two conventions apply throughout.  Anything with no answer — a body that never rises, a
satellite with stale elements, a comet the MPC has dropped — reports an honest empty
ValueHelper (`N/A`) or `None` rather than a wrong number or an exception.  And every tag
this page lists is computed natively: nothing here requires PyEphem.

## Top-level tags

Tags on the almanac itself: `$almanac.sunrise`, `$almanac.next_full_moon`.

| Tag | Type | Since | Notes |
|---|---|---|---|
| `active_meteor_showers` | object tuple | 2.1 | Showers whose activity window contains the almanac's time; each item carries the [shower attributes](#meteor-shower-attributes).  Empty tuple when none are active. |
| `equation_of_time` | duration | 2.1 | Apparent minus mean solar time, signed, USNO convention: positive when the sundial leads the clock. |
| `moon_fullness` | int | 1.0 | Percent of the moon illuminated, rounded to a whole number. |
| `moon_index` | int | 1.0 | Index into the report's `moon_phases` list. |
| `moon_phase` | str | 1.0 | The moon phase's name, from the report's `moon_phases` (translated).  Not to be confused with `$almanac.moon.moon_phase`, a 0–1 float. |
| `next_aphelion` | time | 2.1 | Earth's farthest approach to the sun — early July. |
| `next_autumnal_equinox` | time | 1.0 | |
| `next_eclipse` | time | 1.9 | Maximum of the next eclipse visible from the station, lunar or solar, whichever is sooner. |
| `next_eclipse_kind` | str | 1.9 | `lunar` or `solar` — which kind `next_eclipse` found. |
| `next_eclipse_type` | str | 1.9 | The type of that eclipse, as seen from your station. |
| `next_equinox` | time | 1.0 | |
| `next_first_quarter_moon` | time | 1.0 | |
| `next_full_moon` | time | 1.0 | |
| `next_last_quarter_moon` | time | 1.0 | |
| `next_lunar_eclipse` | time | 1.9 | Maximum of the next lunar eclipse with the moon above your horizon. |
| `next_lunar_eclipse_type` | str | 1.9 | `penumbral`, `partial` or `total`. |
| `next_meteor_shower` | object | 2.1 | The shower whose peak lies next ahead; see [shower attributes](#meteor-shower-attributes). |
| `next_new_moon` | time | 1.0 | |
| `next_perihelion` | time | 2.1 | Earth's closest approach to the sun — early January. |
| `next_solar_eclipse` | time | 1.9 | Maximum of the next solar eclipse visible from your station. |
| `next_solar_eclipse_type` | str | 1.9 | `partial`, `annular` or `total`, as seen from *your* location. |
| `next_solstice` | time | 1.0 | |
| `next_summer_solstice` | time | 1.0 | |
| `next_supermoon` | time | 2.1 | The next full moon falling within a day of perigee. |
| `next_vernal_equinox` | time | 1.0 | |
| `next_winter_solstice` | time | 1.0 | |
| `previous_aphelion` | time | 2.1 | |
| `previous_autumnal_equinox` | time | 1.0 | |
| `previous_eclipse` | time | 1.9 | |
| `previous_eclipse_kind` | str | 1.9 | |
| `previous_eclipse_type` | str | 1.9 | |
| `previous_equinox` | time | 1.0 | |
| `previous_first_quarter_moon` | time | 1.0 | |
| `previous_full_moon` | time | 1.0 | |
| `previous_last_quarter_moon` | time | 1.0 | |
| `previous_lunar_eclipse` | time | 1.9 | |
| `previous_lunar_eclipse_type` | str | 1.9 | |
| `previous_new_moon` | time | 1.0 | |
| `previous_perihelion` | time | 2.1 | |
| `previous_solar_eclipse` | time | 1.9 | |
| `previous_solar_eclipse_type` | str | 1.9 | |
| `previous_solstice` | time | 1.0 | |
| `previous_summer_solstice` | time | 1.0 | |
| `previous_vernal_equinox` | time | 1.0 | |
| `previous_winter_solstice` | time | 1.0 | |
| `separation(a, b)` | radians | 1.0 | Angular separation.  Takes two `(longitude, latitude)` radian tuples, or two of this almanac's body binders. |
| `sidereal_angle` | compass | 1.0 | Unit-aware twin of `sidereal_time`. |
| `sidereal_time` | float ° | 1.0 | Local apparent sidereal time as an angle. |
| `solar_angle` | compass | 2.1 | Unit-aware twin of `solar_time`. |
| `solar_time` | float ° | 2.1 | Local apparent solar time — what a sundial reads.  180° is solar noon. |
| `sunrise` | time | 1.0 | Shorthand for `$almanac.sun.rise`. |
| `sunset` | time | 1.0 | Shorthand for `$almanac.sun.set`. |

## Body tags

Tags on a body: `$almanac.mars.rise`, `$almanac.moon.phase`.  The **Bodies** column says
where a tag applies — unmarked tags work on the sun, the moon, every planet, Pluto, every
star and every configured comet.

### Rise, set and transit

| Tag | Type | Since | Bodies | Notes |
|---|---|---|---|---|
| `rise` | time | 1.0 | | The rise occurring on the almanac's day, searched from local midnight — not necessarily the next one.  For a satellite, the *next* rise. |
| `set` | time | 1.0 | | The set occurring on the almanac's day.  For a satellite, the next set. |
| `transit` | time | 1.0 | | The body's meridian crossing on the almanac's day.  For a satellite, the next culmination. |
| `next_rising` | time | 1.0 | | Relative to the almanac's time, not the day. |
| `next_setting` | time | 1.0 | | |
| `next_transit` | time | 1.0 | | |
| `next_antitransit` | time | 1.0 | | The crossing of the lower meridian. |
| `previous_rising` | time | 1.0 | | |
| `previous_setting` | time | 1.0 | | |
| `previous_transit` | time | 1.0 | | |
| `previous_antitransit` | time | 1.0 | | |
| `visible` | duration | 1.0 | | How long the body is above the horizon on the almanac's day. |
| `visible_change(days_ago=1)` | duration | 1.0 | | **A method, not an attribute** — call it.  The change in `visible` against a day ago, anchored at local noon so DST cannot skew it. |
| `circumpolar` | bool | 1.0 | | Never sets, judged against the same effective horizon as `rise`/`set`. |
| `neverup` | bool | 1.0 | | Never rises. |

### Position

Each plain-float angle has a unit-aware twin; both are listed, twin second.

| Tag | Type | Since | Bodies | Notes |
|---|---|---|---|---|
| `az` / `azimuth` | float ° / compass | 1.0 | | Apparent azimuth, refracted with the almanac's temperature and pressure. |
| `alt` / `altitude` | float ° / angle | 1.0 | | Apparent altitude. |
| `ra` / `topo_ra` | float ° / compass | 1.0 | | Topocentric right ascension of date. |
| `dec` / `topo_dec` | float ° / angle | 1.0 | | Topocentric declination of date. |
| `a_ra` / `astro_ra` | float ° / compass | 1.0 | | Astrometric right ascension, J2000. |
| `a_dec` / `astro_dec` | float ° / angle | 1.0 | | Astrometric declination, J2000. |
| `g_ra` / `geo_ra` | float ° / compass | 1.0 | | Geocentric apparent right ascension. |
| `g_dec` / `geo_dec` | float ° / angle | 1.0 | | Geocentric apparent declination. |
| `ha` / `hour_angle` | float ° / angle | 1.16 | | Local apparent hour angle: 0 at transit, negative east of the meridian, positive west.  PyEphem reported radians wrapped to [0, 2π) — see [Accuracy and conventions](accuracy.md). |
| `hlong` / `hlongitude` | float ° / compass | 1.0 | not stars | True heliocentric ecliptic longitude.  For the sun, Earth's own, per the XEphem convention. |
| `hlat` / `hlatitude` | float ° / angle | 1.0 | not stars | True heliocentric ecliptic latitude. |
| `hlon` | float ° | 1.16 | not stars | PyEphem's spelling of `hlong`. |
| `elong` / `elongation` | float ° / angle | 1.0 | | Elongation from the sun. |
| `parallactic_angle` | radians | 1.0 | | The value itself, also callable as `parallactic_angle()` for the legacy PyEphem idiom. |
| `constellation` | str | 1.9 | | The Latin name, in every language, carrying [its own attributes](#constellation-attributes). |
| `constellation_abbr` | str | 1.9 | | Legacy alias for `constellation.abbr`. |

### Brightness, size and distance

| Tag | Type | Since | Bodies | Notes |
|---|---|---|---|---|
| `mag` | float | 1.0 | | Apparent visual magnitude.  For a comet, the MPC's g/k formula — expectation, not measurement. |
| `phase` | float | 1.0 | not stars | Percent of the body's disc illuminated.  The sun reports 100. |
| `illumination` | percent | 2.1 | not stars | Unit-aware twin of `phase`. |
| `moon_fullness` | float | 1.0 | moon | Same value as `phase`. |
| `moon_phase` | float | 1.16 | moon | PyEphem's raw illuminated fraction, 0–1. |
| `earth_distance` | float | 1.0 | | Distance from Earth, in AU.  Stars need a measured parallax. |
| `sun_distance` | float | 1.0 | | Distance from the sun, in AU. |
| `distance` | AU | 2.0 sat · 2.1 | | Unit-aware twin of `earth_distance`.  On a satellite it is the slant range in `group_distance`, and it arrived in 2.0; on every other body it is AU, from 2.1. |
| `distance_from_sun` | AU | 2.1 | | Unit-aware twin of `sun_distance`. |
| `size` | float | 1.0 | | Apparent angular diameter, arcseconds.  A comet is a point source: 0. |
| `radius` | float ° | 1.0 | | Apparent angular radius, decimal degrees. |
| `radius_size` | angle | 1.0 | | Unit-aware twin of `radius`. |

### Names

| Tag | Type | Since | Bodies | Notes |
|---|---|---|---|---|
| `name` | str | 1.0 | | The English display name, from the tag name. |
| `label` | str | 1.12 | | The translated display name, from the report's `[Almanac]` section, falling back to `name`.  See [Translations](i18n.md). |

### The moon only

| Tag | Type | Since | Notes |
|---|---|---|---|
| `next_perigee` | time | 2.1 | The moon's closest approach, on the geometric centre-to-centre distance the published apsis tables use. |
| `previous_perigee` | time | 2.1 | |
| `next_apogee` | time | 2.1 | The moon's farthest approach. |
| `previous_apogee` | time | 2.1 | |
| `libration_lat` | radians | 1.0 | Optical libration in latitude, per Meeus ch. 53. |
| `libration_long` | radians | 1.0 | Optical libration in longitude. |
| `colong` | radians | 1.0 | The sun's selenographic colongitude. |
| `subsolar_lat` | radians | 1.16 | The sun's selenographic latitude. |

### Jupiter and Saturn only

| Tag | Type | Since | Body | Notes |
|---|---|---|---|---|
| `cmlI` | radians | 1.0 | jupiter | Central meridian longitude, System I, from the IAU rotation elements. |
| `cmlII` | radians | 1.0 | jupiter | System II. |
| `earth_tilt` | radians | 1.0 | saturn | Ring tilt toward Earth, per Meeus ch. 45. |
| `sun_tilt` | radians | 1.0 | saturn | Ring tilt toward the sun. |

### Comets only

| Tag | Type | Since | Notes |
|---|---|---|---|
| `perihelion` | time | 2.1 | Time of perihelion passage, straight from the MPC elements.  It can lie in the past. |
| `elements_epoch` | time | 2.1 | The epoch of the elements in use.  Always live, even when everything else reads N/A. |
| `elements_age` | duration | 2.1 | How old those elements are.  Comets have no age cutoff. |

## Satellite tags

A satellite's surface is its own: the tags below and nothing else.  Anything outside it
reports a clean per-tag error rather than falling through to PyEphem, which has no
satellites.  Configure them under `[Skyfield]` `[[Satellites]]` — see
[Configuration](configuration.md).

| Tag | Type | Since | Notes |
|---|---|---|---|
| `alt` / `altitude` | float ° / angle | 2.0 | Apparent altitude. |
| `az` / `azimuth` | float ° / compass | 2.0 | Apparent azimuth. |
| `ra` / `topo_ra` | float ° / compass | 2.0 | Topocentric right ascension of date. |
| `dec` / `topo_dec` | float ° / angle | 2.0 | Topocentric declination of date. |
| `distance` | distance | 2.0 | Slant range, observer to satellite: a `group_distance` ValueHelper honoring the report's distance units, not the bodies' AU. |
| `sunlit` | bool | 2.0 | Whether the satellite is in sunlight.  `None` with no usable elements. |
| `rise` | time | 2.0 | The *next* rise, not today's. |
| `transit` | time | 2.0 | The next culmination. |
| `set` | time | 2.0 | The next set. |
| `next_pass` | object | 2.0 | The next pass, or the one in progress — see [pass attributes](#pass-attributes). |
| `next_visible_pass` | object | 2.0 | The next pass worth watching: sunlit against a sky with the sun below −6°, peaking at least 10° up. |
| `elements_epoch` | time | 2.0 | The TLE's epoch.  Always live. |
| `elements_age` | duration | 2.0 | Age of the elements.  Past seven days, every other tag reads N/A. |

### Pass attributes

Attributes of `next_pass` and `next_visible_pass`.  All are plain attributes, never methods,
so `getattr` chains (loopdata almanac fields) walk them.  With no qualifying pass, every one
is empty.

| Attribute | Type | Notes |
|---|---|---|
| `rise` | time | When the satellite crosses the horizon. |
| `culmination` | time | When it peaks. |
| `set` | time | When it goes back down. |
| `max_altitude` | angle | Peak altitude. |
| `rise_azimuth` | compass | Where it appears — `.ordinal_compass` gives `WSW`. |
| `culmination_azimuth` | compass | Where it peaks. |
| `set_azimuth` | compass | Where it disappears. |
| `duration` | duration | Horizon to horizon. |
| `visible` | bool | Whether this pass meets the visible test.  `None` with no usable elements. |

## Meteor shower attributes

Attributes of `$almanac.next_meteor_shower` and of each item of
`$almanac.active_meteor_showers`.

| Attribute | Type | Notes |
|---|---|---|
| `name` | str | Stable English data, like `constellation`. |
| `label` | str | The report's `[Almanac]` `[[MeteorShowers]]` translation, falling back to `name`. |
| `peak` | time | This apparition's peak, computed from the sun's ecliptic longitude.  For an active shower it may lie in the past. |
| `zhr` | int | Zenithal hourly rate at the peak — see the [glossary](glossary.md). |
| `parent` | str | The body whose debris the shower is. |
| `radiant_ra` | float ° | Radiant right ascension, J2000. |
| `radiant_dec` | float ° | Radiant declination, J2000. |
| `radiant_alt` | float ° | The radiant's current altitude, refracted. |
| `radiant_az` | float ° | The radiant's current azimuth. |

## Constellation attributes

Attributes of `$almanac.<body>.constellation`.  The value itself is the Latin name, so
templates comparing it and loopdata fields publishing it always see the same string
regardless of the report's language.

| Attribute | Type | Notes |
|---|---|---|
| `name` | str | The Latin name again. |
| `abbr` | str | The IAU abbreviation — `Psc`. |
| `label` | str | The translated display name, from `[Almanac]` `[[Constellations]]` keyed by abbreviation, falling back to the Latin. |

## Almanac arguments

Not tags, but part of the same surface: arguments to `$almanac(...)`, which return a new
almanac you then read tags from.

| Argument | Effect |
|---|---|
| `almanac_time` | Evaluate every tag at another instant — the time-travel idiom behind calendars and analemmas.  `$almanac(almanac_time=$almanac.moon.next_perigee.raw).moon.distance.km` |
| `horizon` | A custom horizon in degrees, treated as a *geometric* altitude with no refraction, per the USNO twilight definitions.  For satellites it clips the pass. |
| `use_center` | Measure to the body's centre rather than its limb: `$almanac(horizon=-6).sun(use_center=1).rise`. |
| `pressure` | Station pressure for the refraction model; `pressure=0` turns refraction off entirely. |
| `temperature` | Station temperature for the refraction model. |

## Naming patterns

| Pattern | Meaning |
|---|---|
| `$almanac.<planet>` | The sun, the moon, Mercury through Neptune, and Pluto. |
| `$almanac.<star name>` | Any of 420 names covering 412 stars — the IAU Catalog of Star Names plus PyEphem's names as legacy aliases.  Multi-word names use underscores, diacritics dropped: `kaus_australis`. |
| `$almanac.hip_<number>` | Any of the 118,218 Hipparcos catalog stars: `$almanac.hip_57939`.  Zero-padded numbers work too. |
| `$almanac.<satellite name>` | A satellite's `[[Satellites]]` tag name. |
| `$almanac.sat_<norad>` | An alternate spelling for a *configured* satellite.  It never fetches an unconfigured one. |
| `$almanac.<comet name>` | A comet's `[[Comets]]` tag name.  Comets have no numeric alternate spelling. |

## What this extension does not serve

Anything not listed above falls through to WeeWX's built-in PyEphem almanac when PyEphem is
installed — direct PyEphem data attributes such as `$almanac.moon.a_epoch`, and any almanac
time outside the bundled ephemeris's span (mid-1899 to 2053).  Without PyEphem those report
a per-tag error rather than breaking the report.  Satellite and comet tags never fall
through: PyEphem has neither.

Deliberately absent, with reasons in [Accuracy and conventions](accuracy.md): an apparent
magnitude for satellites, pass *lists*, and `$almanac.earth` — Earth is the observer, and
its heliocentric coordinates are served as the sun's.
