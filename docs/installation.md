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
the current Skyfield release — 1.54 as of July 2026 — and upgrading to it is recommended.  To
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
    stars = true
```

- `enable`: When true (the default), the Skyfield almanac is registered and reports are
  generated with Skyfield almanac values rather than WeeWX's built-in PyEphem/weeutil almanac.
- `stars`: When true (the default), named stars (e.g., `$almanac.rigel.rise`) are available in
  the report almanac, computed from the bundled Hipparcos catalog excerpt
  (`wxskyfield_stars.dat`).

(This is weewx-skyfield's own top-level `[Skyfield]` section.  It is unrelated to the
`[[Skyfield]]` subsection of `[Almanac]` used by the independent weewx-skyfield-almanac
extension.)

The Sky page has its own `[[SkyfieldReport]]` entry under `[StdReport]` — see
[The Sky page](sky-page.md#configuring-the-page) for `enable` and `report_timing` there.

## Serving every Hipparcos star

The bundled `wxskyfield_stars.dat` covers the 412 named stars.  To address *any* Hipparcos
star by catalog number (`$almanac.hip_57939.rise`), download the full Hipparcos catalog
`hip_main.dat` (from [CDS VizieR I/239](https://cdsarc.cds.unistra.fr/viz-bin/cat/I/239)) and
place it in WeeWX's user directory (e.g., `/home/weewx/bin/user/hip_main.dat`).  When present,
`hip_<number>` lookups read it and all 118,218 stars are served.  (The named stars are still
loaded from the bundled excerpt at startup — its records are identical to the full catalog's,
and reading the excerpt keeps startup fast.)

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
phases, positions, magnitudes/sizes/phases, named stars, and polar day/night edge cases).  It
also contains two permanent audits: one verifying that, with PyEphem installed, everything
WeeWX's built-in almanac can do still works (including direct PyEphem attributes such as
`$almanac.moon.subsolar_lat`); and one verifying that on a system *without* PyEphem, all
standard-skin tags (and much more) work with Skyfield alone.  Run the suite from the root of
the repository with the Python from your WeeWX virtual environment (WeeWX, Skyfield and pytest
must be installed in that environment):

```
/home/weewx/weewx-venv/bin/python -m pytest tests
```

The star tests use the bundled Hipparcos catalog excerpt, which is part of the repository, so
no additional downloads are needed.
