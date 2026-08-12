---
title: Values, units and types
layout: default
parent: Almanac tags
nav_order: 2
description: What weewx-skyfield's tags actually return — plain floats in degrees, PyEphem-shaped radians, ValueHelper twins, the astronomical unit — and the .raw trap that silently changes a number's meaning.
---

# Values, units and types

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Most almanac questions are answered by [the tag index](tag-index.md).  This page answers the
one it can't: *what kind of thing* comes back, and why the same angle is available in three
different forms.  If a number on your page is off by a factor of 3600, or 57.3, or reads
`N/A` when you expected a value, the answer is here.

## Three families

| Family | Example | What it is |
|---|---|---|
| **Plain float, decimal degrees** | `$almanac.mars.alt` | A bare Python float.  No units attached, no formatting. |
| **PyEphem-shaped, radians** | `$almanac.moon.colong` | A bare float in radians, matching PyEphem's numeric scale — which also carries `.degrees` and `.radians`. |
| **ValueHelper** | `$almanac.mars.altitude` | WeeWX's unit-aware value: formats itself, converts on ask, renders `N/A` when there is no answer. |

The split is not arbitrary.  Tags that PyEphem also served keep PyEphem's scale, so a
template ported from the built-in almanac keeps working — including the familiar
`math.degrees($almanac.moon.colong)` idiom.  Tags with no PyEphem counterpart are
ValueHelpers, because that is what a modern WeeWX skin wants.  And where both are useful,
you get both: a plain float and a unit-aware **twin**.

## The twins

Every plain-float angle has a ValueHelper sibling carrying the same answer:

| Plain float (degrees) | Unit-aware twin | Twin's group |
|---|---|---|
| `az` | `azimuth` | `degree_compass` |
| `alt` | `altitude` | `group_angle` |
| `ra` | `topo_ra` | `degree_compass` |
| `dec` | `topo_dec` | `group_angle` |
| `a_ra` / `a_dec` | `astro_ra` / `astro_dec` | `degree_compass` / `group_angle` |
| `g_ra` / `g_dec` | `geo_ra` / `geo_dec` | `degree_compass` / `group_angle` |
| `ha` | `hour_angle` | `group_angle` |
| `hlong` / `hlat` | `hlongitude` / `hlatitude` | `degree_compass` / `group_angle` |
| `elong` | `elongation` | `group_angle` |
| `sidereal_time` | `sidereal_angle` | `degree_compass` |
| `solar_time` | `solar_angle` | `degree_compass` |
| `phase` | `illumination` | `group_percent` |
| `earth_distance` | `distance` | `group_distance_astronomical` |
| `sun_distance` | `distance_from_sun` | `group_distance_astronomical` |
| `radius` | `radius_size` | `group_angle` |

Two consequences worth knowing.  A `degree_compass` twin gives you `.ordinal_compass` for
free, so `$almanac.iss.next_pass.rise_azimuth.ordinal_compass` renders `WSW`.  And a
`group_angle` ValueHelper carries its angle **in radians internally**, converting to whatever
the report displays — so never read `.raw` from one expecting degrees.

`mag` deliberately has no twin: a magnitude is unitless, with nothing to convert or label.

## The `.raw` trap

This one has bitten a real page, and it is the single most important paragraph here.

`ValueHelper.raw` gives you the value **unformatted** — it does *not* give it to you
**unconverted**.  A `.raw` read follows the report's own converter.  So if a report (or a
skin, or a `[[Defaults]]` block) sets

```ini
[Units]
    [[Groups]]
        group_deltatime = hour
```

then `$almanac.sun.visible.raw` returns **hours**, not seconds — and a template doing
seconds arithmetic on it silently produces numbers that are 3600× too small.  That is
[issue #2](https://github.com/chaunceygardiner/weewx-skyfield/issues/2): a page's "visible"
figures all read zero, with nothing in any log to say why.

{: .important }
Pin the unit at every `.raw` read.  Write `$almanac.sun.visible.second.raw`, not
`$almanac.sun.visible.raw`; write `$almanac.sunrise.unix_epoch.raw`, not
`$almanac.sunrise.raw`.  The pinned spelling means the same thing on every station,
whatever its unit settings.

The same applies to weewx-loopdata almanac fields: `almanac.sun.visible.second.raw` and
`almanac.sunrise.unix_epoch.raw` are the spellings that cannot change meaning under you.
See [Live-updating pages](live-pages.md).

## The astronomical unit

`distance` and `distance_from_sun` report in `group_distance_astronomical`, a group this
extension registers with WeeWX.  Its display unit is the astronomical unit in *every* unit
system — US, metric or metricwx — because interplanetary distances read naturally in AU and
absurdly in ten-digit kilometres.  The default rendering is `1.8588 AU`.

Converting is per-tag and needs no configuration: `$almanac.moon.distance.km`,
`$almanac.mars.distance.mile`.  Restyling the whole family is a
[units override](configuration.md#unit-and-format-overrides).

A satellite's `.distance` is the exception, and deliberately so: it is the slant range from
you to the satellite, in ordinary `group_distance`, because nobody measures an overhead pass
in AU.

## Radians that know they are radians

The PyEphem-shaped tags — `libration_lat`, `libration_long`, `colong`, `subsolar_lat`,
`cmlI`, `cmlII`, `earth_tilt`, `sun_tilt`, `parallactic_angle`, and `$almanac.separation()`
— return a float subclass that behaves exactly like the float PyEphem returned, so existing
templates are unaffected, but also answers:

```
$almanac.moon.parallactic_angle           ## the value, in radians
$almanac.moon.parallactic_angle.degrees   ## the same angle in decimal degrees
$almanac.moon.parallactic_angle.radians   ## names the value itself
```

`parallactic_angle` has one extra wrinkle: PyEphem served it as a method, so
`$almanac.moon.parallactic_angle()` — with the parentheses — still works.  The value is
callable as well as readable.

## Attributes, methods, and why it matters

Almost everything this almanac serves is a plain attribute.  That is a deliberate contract,
not an accident: Cheetah calls a method for you automatically, but weewx-loopdata walks
attribute chains with plain `getattr`, which does not.  A tag served as a method would work
in a template and silently fail as a live field.

So [pass attributes](tag-index.md#pass-attributes) (`next_pass.rise`,
`.max_altitude`, `.duration`), [shower attributes](tag-index.md#meteor-shower-attributes),
and `constellation.abbr` are all plain attributes.

The exceptions, which you must call:

| Callable | Why |
|---|---|
| `$almanac.sun.visible_change()` | Takes an argument: `visible_change(2)` compares against two days ago. |
| `$almanac.separation(a, b)` | Takes two bodies. |
| `$almanac(...)` | The almanac itself, to time-travel or set a horizon. |
| `$almanac.sun(use_center=1)` | A body, to measure to its centre. |

## When there is no answer

The almanac never invents a number and never breaks a report to admit it:

- **A ValueHelper with no value renders `N/A`.**  A body that never rises, a satellite with
  no pass this week, a comet the MPC has dropped, a star with no measured parallax — all
  report an empty ValueHelper, and `.raw` is `None`.
- **A plain-value tag reports `None`** in the same situations — `sunlit`, `visible` on a
  pass.
- **A tag outside a surface reports a per-tag error**, which WeeWX renders in place without
  taking down the page.  Asking a satellite for `.phase`, or Mars for `.next_pass`, lands
  here.
- **A time outside the ephemeris** (before mid-1899 or after 2053) falls through to PyEphem
  if installed, and otherwise reports a per-tag error.

The distinction that matters: `N/A` means *the question was valid and the answer is
genuinely unknown or nonexistent*.  It is never a stale value and never a silent zero.

## Diagnosing a wrong number

| Symptom | Almost certainly |
|---|---|
| Value 3600× or 60× out | A `.raw` read on a duration under a `group_deltatime` override — pin the unit. |
| Value 57.3× out | Mixing a radians tag with a degrees tag.  Check the [tag index](tag-index.md) Type column. |
| Angle displays as a compass point when you wanted a number | You read a `degree_compass` twin; use the plain float, or `.raw` with a pinned unit. |
| `N/A` everywhere for one body | Its elements are missing or stale — check `elements_epoch` and `elements_age`, and see [Troubleshooting](troubleshooting.md). |
| Time is right but the date is a day off | A day-window verb (`rise`, `set`, `transit`) answers for the almanac's *day*; you may want `next_rising`. |
