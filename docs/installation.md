---
title: Installing weewx-skyfield
description: Installation, configuration and Skyfield-upgrade instructions for the weewx-skyfield WeeWX extension.
---

# Installation

[Home](index.md) ·
[Almanac tags](tags.md) ·
[The Sky page](sky-page.md) ·
[Sky panels in your skin](panels.md) ·
[Translating (i18n)](i18n.md) ·
[GitHub project](https://github.com/chaunceygardiner/weewx-skyfield)

---

weewx-skyfield requires Python 3.9 or later, WeeWX 5.2 or later, and the
[Skyfield](https://rhodesmill.org/skyfield/) (1.47 or later) and NumPy libraries.  PyEphem is
**not** required.

## Installing the extension

1. Install the prerequisite Skyfield package (1.47 or later).

   For a pip/venv WeeWX install, activate the virtual environment (actual syntax varies by
   type of WeeWX install) and install with pip:

   ```
   source /home/weewx/weewx-venv/bin/activate
   pip install 'skyfield>=1.47'
   ```

   For a Debian package install:

   ```
   sudo apt install python3-skyfield
   ```

   `apt show python3-skyfield` reports the version; Debian 12 "bookworm" ships 1.45, which is
   too old — use pip in that case.  On an older Skyfield, the extension logs an error and
   leaves the built-in almanac in place.

2. Download the latest release, `weewx-skyfield.zip`, from the
   [weewx-skyfield GitHub repository](https://github.com/chaunceygardiner/weewx-skyfield).
   It is about 43 MB: the bundled DE421 ephemeris (16 MB), the complete Hipparcos star
   catalog (15 MB gzipped) and the documentation's screenshots (15 MB) account for nearly
   all of it.

3. Install the extension:

   ```
   weectl extension install weewx-skyfield.zip
   ```

4. Restart WeeWX.

Reports generated from then on (e.g., the Seasons skin's Celestial page) use Skyfield almanac
values.  No skin changes are needed: the extension answers the same `$almanac` tags as the
built-in almanac.  [The Sky page](sky-page.md) appears alongside your existing reports at
`<HTML_ROOT>/skyfield/index.html` after the first report cycle.

Upgrading over a running WeeWX is safe: the ephemeris is read fully into memory at startup, so
replacing the extension's files cannot disturb the running almanac; the new files take effect
on the restart that follows the install.

## Upgrading Skyfield

Skyfield 1.47 or later works, but the extension is developed and its test suite run against
the current Skyfield release — 1.55 as of August 2026 — and upgrading to it is recommended.  To
see what you have:

```
/home/weewx/weewx-venv/bin/python -c 'import skyfield; print(skyfield.__version__)'
```

For a pip/venv WeeWX install, upgrade with the virtual environment's pip, then restart WeeWX:

```
source /home/weewx/weewx-venv/bin/activate
pip install --upgrade skyfield
```

For a Debian package install, `apt` serves the distribution's version, which lags the Skyfield
release (Debian 12 ships 1.45, below even the minimum).  Where the packaged version is too
old, install with pip as described above instead.

## Configuration

The installer adds a `[Skyfield]` section to `weewx.conf` with the defaults:

```
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

- `enable`: When true (the default), the Skyfield almanac is registered and reports are
  generated with Skyfield almanac values rather than WeeWX's built-in PyEphem/weeutil almanac.
- `satellite_downloads`: When true (the default), satellite orbital elements are fetched from
  CelesTrak — at install, at any weewxd startup that finds them missing or stale, then about
  every three hours.  Set it false on an isolated network; see [Satellites](#satellites)
  below for what that changes.
- `comet_downloads`: When true (the default), the MPC's CometEls.txt is fetched — at install,
  at any weewxd startup that finds it missing or stale, then about every two days.  Same
  isolated-network story; see [Comets](#comets) below.
- `[[Satellites]]`: tag name = NORAD catalog number, one line per satellite.  This one list
  drives both the [satellite tags](tags.md#satellites) and the fetch list.
- `[[Comets]]`: tag name = MPC designation, one line per comet — `halley = 1P`,
  `tsuchinshan_atlas = C/2023 A3`; see the [comet tags](tags.md#comets) for the matching
  rules, and the README's Comets section for a ready-to-paste block of famous comets.

These are the section's only entries — anything else there draws a log warning and is
ignored.  (The `stars` option was removed in 2.0: the complete star catalog now ships with
the extension, and stars are simply always available.)  The Sky page's options (`theme`,
`star_mag_limit`, `star_label_mag`, `constellation_lines`, `lang`) are
*report* options and belong under `[StdReport]` `[[SkyfieldReport]]`.

(This is weewx-skyfield's own top-level `[Skyfield]` section.  It is unrelated to the
`[[Skyfield]]` subsection of `[Almanac]` used by the independent weewx-skyfield-almanac
extension.)

The Sky page has its own `[[SkyfieldReport]]` entry under `[StdReport]` — see
[The Sky page](sky-page.md#configuring-the-page) for `enable` and `report_timing` there.

## Satellites

Satellite positions are computed (by Skyfield's SGP4 implementation) from published orbital
elements, which age quickly — a reboost or maneuver makes week-old elements minutes wrong —
so, unlike the ephemeris and the star catalog, they cannot ship in a release.  They are
fetched from [CelesTrak](https://celestrak.org): once at install time, then by weewxd, which
checks for missing or stale elements at every startup — a satellite just added to the
configuration is live seconds after the restart — and refreshes about every three hours
thereafter, on a worker thread that never blocks reports; on a failed fetch the old file is
kept and the retry backs off gently.  Each satellite's elements live
in their own file, `wxskyfield_sat_<norad>.tle`, in a `wxskyfield` directory beside the
station's SQLite database (under `SQLITE_ROOT`), and survive restarts.  Elements whose epoch
is more than seven days older than the almanac's time are *not used*: every tag for that
satellite reads "N/A" rather than reporting confidently wrong pass times, a warning is
logged (once at the crossing, not per tag), and the always-live diagnostic tags
`$almanac.iss.elements_epoch` and `$almanac.iss.elements_age` say why.

**This is the extension's only network access, and it has a switch.**  Set
`satellite_downloads = false` in the `[Skyfield]` section and the extension fetches nothing,
ever — the behavior every release before 2.0 had unconditionally.  In that mode
`[[Satellites]]` still works if you maintain the element files yourself: an air-gapped
station can copy `wxskyfield_sat_<norad>.tle` files in by any means it likes (each file is
one satellite's CelesTrak TLE — the name line and two element lines); the seven-day age
cutoff applies all the same, because stale elements cannot predict passes no matter how they
arrived.  With no `[[Satellites]]` configured, likewise, nothing is ever fetched.  The fetch
identifies itself as `weewx-skyfield/<version>` with the project URL, and `weectl extension
uninstall` does not remove the cached element files — delete the `wxskyfield` directory
yourself if you want them gone.

**Choosing satellites.**  Any satellite CelesTrak carries can be added by NORAD number
([satellite catalog search](https://celestrak.org/satcat/search.php)).  Keep the list
short — each entry is a separate fetch every three hours.  One caveat worth knowing: a
satellite's orbital inclination bounds the latitudes it can appear over.  Hubble
(`hst = 20580`), inclined 28.5°, never climbs usefully above the horizon for stations
poleward of about ±35° latitude — most of Europe and much of North America would see a
permanent "no visible pass", which is the truth, not a bug.  The defaults avoid this: the
ISS (51.6°) and Tiangong (41.5°) put on the show for essentially everyone.

## Comets

Comet orbital elements are the MPC's published
[CometEls.txt](https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt) — one ~160 KB
file carrying every comet with a current orbit, cached as `wxskyfield_comets.txt` in the
same `wxskyfield` directory as the satellite TLEs.  It follows the satellites' fetch shape
at a gentler cadence: fetched at install, at any weewxd startup that finds it missing or
stale, then about every two days, on a worker thread that never blocks reports — written
atomically, the old file kept on any failure, backoff on retry.  Set
`comet_downloads = false` in the `[Skyfield]` section and the extension fetches nothing,
ever: an air-gapped station maintains the one `wxskyfield_comets.txt` file by any means it
likes (it is the MPC file verbatim).  Unlike satellite elements there is no age cutoff —
two-body comet elements degrade gracefully over months, not days — and `weectl extension
uninstall` leaves the cache file, like the satellite TLEs.  The MPC drops comets that have
faded from observability, so a configured comet can vanish from a fresh download: its tags
then read "N/A" with a once-per-crossing log warning naming it — see the
[comet tags](tags.md#comets).

## Serving every Hipparcos star

Nothing to do: as of 2.0 the complete Hipparcos catalog ships with the extension (as
`wxskyfield_stars.dat.gz`), so every catalog star is addressable by number
(`$almanac.hip_57939.rise`) and [The Sky page's dome](sky-page.md#configuring-the-page)
plots the whole field down to `star_mag_limit` out of the box.  Before 2.0 this took
downloading `hip_main.dat` yourself and placing it in WeeWX's user directory; if you did,
that copy is now redundant — the extension no longer reads it, and it can be deleted.

## Why require Python 3.9 or later?

weewx-skyfield uses timezone-aware date features which do not work with Python 2, nor in
versions of Python 3 earlier than 3.9.

## Why the DE421 ephemeris (and not DE440)?

JPL has published newer ephemerides since DE421 (2008) — notably DE440 and its shorter-span
excerpt DE440s (2020), which incorporate another decade of spacecraft ranging data.  This
extension bundles DE421 anyway, deliberately:

- **The accuracy difference is invisible here.**  DE440's corrections are largest for the
  outer planets and amount to well under an arcsecond as seen from Earth for every body this
  almanac serves.  An arcsecond moves a rise or set time by about a fifteenth of a second —
  while atmospheric refraction at the horizon, which no ephemeris can predict, makes every
  real rise and set uncertain by tens of seconds.  At the precision reports display, DE421 and
  DE440 are indistinguishable.
- **Half the size.**  DE421 is about 16 MB; DE440s is about 32 MB.  The difference would be
  paid in the release zip and on disk — for corrections no report could display.
- **DE421's span is enough.**  It covers mid-1899 through 2053, and a weather station's
  almanac lives within a few years of now; times outside the span fall through to PyEphem as
  described in the [tag reference](tags.md#fallback-behavior).  DE440s would extend the span
  to 1849–2150 — the only difference a user could ever see.

Should the 2053 horizon ever draw near, swapping the bundled `.bsp` for a newer one is a small
change: Skyfield does not care about the ephemeris file's name.

## Testing

A pytest test suite lives in the `tests` directory of the repository.  It exercises the
Skyfield almanac (sun/moon rise/set/transit, twilight horizons, equinoxes/solstices, moon
phases, positions, magnitudes/sizes/phases, named stars, satellites and passes, and polar
day/night edge cases).  It
also contains two permanent audits: one verifying that, with PyEphem installed, everything
WeeWX's built-in almanac can do still works (including direct PyEphem attributes such as
`$almanac.moon.a_epoch`); and one verifying that on a system *without* PyEphem, all
standard-skin tags (and much more) work with Skyfield alone.  Run the suite from the root of
the repository with the Python from your WeeWX virtual environment (WeeWX, Skyfield and pytest
must be installed in that environment):

```
/home/weewx/weewx-venv/bin/python -m pytest tests
```

The star tests use the bundled Hipparcos catalog and the satellite tests use archived
orbital-element fixtures in `tests/data`, all part of the repository, so the suite never
touches the network.
