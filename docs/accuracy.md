---
title: Accuracy and conventions
layout: default
parent: Almanac tags
nav_order: 4
description: What weewx-skyfield's numbers mean — where it follows USNO/IAU/Meeus rather than PyEphem, why it bundles DE421, and the honest limits of comet, satellite and magnitude predictions.
---

# Accuracy and conventions

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

This extension replaces an almanac that many WeeWX stations have used for years, so where
its answers differ from the old ones, it owes you a reason.  The policy is simple:
**accepted definitions over PyEphem compatibility.**  PyEphem is deprecated by its own
author in favor of Skyfield, and is measurably wrong in places.  Where the two disagree,
this extension follows the USNO, the IAU, or Meeus — and documents the difference here.

## Differences from PyEphem

- **`$almanac.equation_of_time`** (2.1; PyEphem never served it) follows the USNO
  sign convention, apparent minus mean solar time: positive when the sundial runs ahead of
  the clock.  Sources differ on the sign — some publish mean minus apparent — so a template
  porting a formula from elsewhere should check which convention it assumed.

- **A custom horizon** (e.g. `$almanac(horizon=-6)`) is treated as a geometric altitude: no
  atmospheric refraction is applied.  This matches the USNO definitions of civil, nautical
  and astronomical twilight.  PyEphem applies refraction to a custom horizon unless the
  `pressure=0` idiom is used, which shifts twilight times by roughly 2–3 minutes.

  With the *default* horizon, rise and set include standard refraction (34 arcminutes) and
  the body's apparent radius, and `circumpolar`/`neverup` are judged against that same
  effective horizon, so they always agree with rise/set.  Note that an explicit `horizon=0`
  cannot be distinguished from the default (WeeWX supplies 0.0 when no horizon is given), so
  it receives the default refraction-and-radius treatment; for the geometric crossing of the
  true horizon, use `pressure=0` with `use_center=1`.

- **`hlongitude`/`hlatitude`** are true heliocentric (sun-centered) ecliptic coordinates for
  every body, including the moon.  PyEphem reports the moon's *geocentric* ecliptic longitude
  under this name.  For the sun itself, heliocentric coordinates are undefined, so Earth's
  heliocentric coordinates are reported, per the XEphem convention.  Asked for Earth directly
  — `$almanac.earth.hlongitude` — the almanac has no such body: Earth is the observer; ask
  the sun.

- **`$almanac.<body>.ha`**, the local apparent hour angle (1.16, stars included), is a
  signed angle in decimal degrees like the almanac's other plain coordinates: 0 at transit,
  negative east of the meridian, positive west — the standard convention.  PyEphem reports
  the same angle in radians, usually wrapped to [0, 2π), **so a template that read `ha`
  through the PyEphem fallback must drop its `math.degrees()` conversion.**  `hlon` —
  PyEphem's own spelling of `hlong` — is likewise served natively in decimal degrees.

- **The default horizon honors the almanac's `pressure` and `temperature`** for rise/set:
  refraction is scaled from the standard 34 arcminutes, and WeeWX's documented `pressure=0`
  idiom turns it off entirely.

- **`$almanac.separation()`** takes two `(longitude, latitude)` tuples in radians and returns
  radians, per the WeeWX 5.2 almanac API.  It also accepts two of this almanac's own body
  binders — `$almanac.separation($almanac.mars, $almanac.venus)` — computed natively.  Calls
  made with PyEphem `Body` arguments are passed through to PyEphem when it is installed.

- **Jupiter's central meridian longitudes** (`cmlI`/`cmlII`) are computed from the IAU
  rotation elements (pole and System I/II rotation rates) and the light-time corrected
  geometry.  PyEphem's values differ from the IAU definition by about 0.8 degrees.

- **The moon's libration** (`libration_lat`/`libration_long`) and the selenographic position
  of the sun — its colongitude (`colong`) and latitude (`subsolar_lat`) — follow Meeus,
  *Astronomical Algorithms* ch. 53 (optical libration; the physical libration, at most 0.04
  degrees, is neglected).  Saturn's ring tilt (`earth_tilt`/`sun_tilt`) follows Meeus ch. 45.
  All are in radians, like PyEphem's — and each also carries the same answer in decimal
  degrees via `.degrees`.  The values themselves are unchanged, so existing templates,
  including the `math.degrees($...)` idiom, keep working.

## Why the DE421 ephemeris (and not DE440)?

JPL has published newer ephemerides since DE421 (2008) — notably DE440 and its shorter-span
excerpt DE440s (2020), which incorporate another decade of spacecraft ranging data.  This
extension bundles DE421 anyway, deliberately:

- **The accuracy difference is invisible here.**  DE440's corrections are largest for the
  outer planets and amount to well under an arcsecond as seen from Earth for every body this
  almanac serves.  An arcsecond moves a rise or set time by about a fifteenth of a second —
  while atmospheric refraction at the horizon, which no ephemeris can predict, makes every
  real rise and set uncertain by tens of seconds.  At the precision reports display, DE421
  and DE440 are indistinguishable.
- **Half the size.**  DE421 is about 16 MB; DE440s is about 32 MB.  The difference would be
  paid in the release zip and on disk — for corrections no report could display.
- **DE421's span is enough.**  It covers mid-1899 through 2053, and a weather station's
  almanac lives within a few years of now.  DE440s would extend the span to 1849–2150 — the
  only difference a user could ever see.

Should the 2053 horizon ever draw near, swapping the bundled `.bsp` for a newer one is a
small change: Skyfield does not care about the ephemeris file's name.

## What the predictions can and cannot promise

Different tag families rest on different quality of input, and the manual would be lying if
it presented them all as equally solid.

**Sun, moon and planets** are as good as the ephemeris and the refraction model — which
means the *ephemeris* is not the limiting factor.  Refraction at the horizon varies with the
real atmosphere in ways no model captures; every published rise and set time, from any
source, carries tens of seconds of that uncertainty.

**Satellites** are propagated by SGP4 from published TLEs, which age quickly: a reboost or
manoeuvre makes week-old elements minutes wrong.  That is why elements more than seven days
older than the almanac's time are refused outright rather than used — an honest `N/A` beats
a confident wrong pass time.

**Comets** are propagated as unperturbed two-body orbits — where-do-I-look accuracy, not
ephemeris-grade positions far from the elements' epoch.  The routine refresh keeps the epoch
current.  Unlike satellite elements there is no age cutoff, because two-body comet elements
degrade gracefully over months rather than days.

**Comet magnitudes** come from the MPC's published g/k parameters via the standard formula
m = g + 5·log₁₀(Δ) + 2.5·k·log₁₀(r).  Comets are notorious for deviating from it: outbursts
brighten them by magnitudes overnight, and famous ones have fizzled.  Treat the number as
expectation, not measurement.

**Satellite magnitudes are deliberately absent.**  Satellite brightness models are
hand-wavy; `sunlit` and `max_altitude` are served honestly instead.  This is the mirror image
of the comet decision: comets have a standard formula, satellites do not.

**Meteor shower peaks** are computed from the sun's ecliptic longitude — the Perseids peak
when the sun reaches λ 140.0°, whatever the calendar says — so every year's instant comes
from the ephemeris rather than a lookup table.  The ZHR is the published ideal rate under a
dark sky with the radiant overhead; what you actually see is usually a fraction of it, which
is why the Sky page reports the moon's illumination alongside.

## Falling back to PyEphem

Anything this extension does not compute falls through to the next almanac in WeeWX's list —
the built-in PyEphem almanac when PyEphem is installed.  In practice the only remaining
fallbacks are direct PyEphem data attributes this extension does not compute, such as
`$almanac.moon.a_epoch`.

Almanac times outside the span of the bundled DE421 ephemeris (mid-1899 through 2053) fall
through the same way.  Without PyEphem, such tags simply report per-tag errors rather than
breaking report generation.

Satellite and comet tags never fall through: the built-in almanac has neither, so an
unrecognized attribute on one reports a clean per-tag error instead of a mysterious
PyEphem answer.
