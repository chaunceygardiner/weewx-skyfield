# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A WeeWX extension with one job: on WeeWX 5.2+, register a `weewx.almanac.AlmanacType` at the
head of `weewx.almanac.almanacs`, so report tags (`$almanac.sunrise`,
`$almanac(horizon=-6).sun(use_center=1).rise`, `$almanac.rigel.mag`, ...) use Skyfield and the
bundled JPL DE421 ephemeris instead of WeeWX's built-in PyEphem/weeutil almanac.

The almanac engine is shared history with the weewx-celestial extension (same author): celestial
3.x embeds the same engine alongside its loop-packet fields.  Bug fixes to the engine should
usually be applied in both repositories.

## Commands

Tests and development require the Python from a WeeWX virtual environment (WeeWX, Skyfield,
NumPy, pytest installed; PyEphem enables the parity audits).  On this machine that venv is
`/home/weewx/weewx-venv`.

```sh
# Full test suite (from the repo root; tests add bin/user to sys.path themselves)
/home/weewx/weewx-venv/bin/python -m pytest tests

# One test
/home/weewx/weewx-venv/bin/python -m pytest tests/test_almanac.py::TestStars::test_hip_number_tags

# Lint — BOTH must stay completely clean
pyflakes3 bin/user/wxskyfield.py tests/test_almanac.py
mypy --ignore-missing-imports bin/user/wxskyfield.py

# Install into a WeeWX instance, then restart weewx.  Deploying requires
# root (WeeWX runs as root on these machines).  Claude: you cannot run
# this (sudo needs a password you don't have); print the command and have
# the human run it in their own terminal.
sudo -- bash -c ". /home/weewx/weewx-venv/bin/activate; weectl extension install /path/to/weewx-skyfield -y"
```

## Architecture

The almanac lives in `bin/user/wxskyfield.py`, in three layers:

- **`WxSkyfield(StdService)`** — reads `[Skyfield]` config (`enable`, `stars`), builds `Sky`,
  and calls `register_almanac()` (which declines gracefully before WeeWX 5.2, and dedups by
  class name *and* module — both weewx-celestial and the independent weewx-skyfield-almanac
  extension use the same class name and must not be removed).  It binds no loop/archive events.
- **`Sky`** — the Skyfield engine: loads the timescale, the ephemeris (`wxskyfield_de421.bsp`),
  and the star catalog.  Its `__init__` NEVER raises: every failure logs and leaves
  `valid=False`, and the service then simply does nothing.  `EPHEMERIS_KEYS` is the single
  source of truth for the bodies served (earth stays out of `Sky.orbs`, whose keys drive
  almanac body dispatch).
- **`SkyfieldAlmanacType` / `SkyfieldAlmanacBinder`** — the report almanac.  Attributes the
  binder does not compute fall through to the built-in PyEphem almanac when installed
  (`pyephem_fallback`); by design the only remaining fallbacks are named stars when the
  catalog is disabled and direct PyEphem attributes we do not compute (e.g.
  `moon.subsolar_lat`).

**The Sky page** — a bundled showcase skin, `skins/Skyfield/` (Cheetah template + `sky.css` +
`skin.conf`), generated at `<HTML_ROOT>/skyfield/index.html` via the `[StdReport]`
`[[SkyfieldReport]]` stanza that install.py merges into weewx.conf.  install.py's
`HTML_ROOT` must stay the RELATIVE `'skyfield'`: weectl prepends the station's own
`[StdReport]` HTML_ROOT at install time (weecfg/extension.py), so writing
`public_html/skyfield` there installs to `public_html/public_html/skyfield`.  All SVG/HTML panels are
produced by the search-list extension `bin/user/wxskyfield_sky.py` (`$sky_page.*` methods),
which uses only public `$almanac` binder tags plus the registered almanac's star catalog; it
memoizes body evaluations per page, and the page must stay self-contained (inline SVG, system
fonts, no JavaScript libraries, nothing fetched at run time).  Keep the CSS in `sky.css`, not
the template: `#hex` colors in a Cheetah template invite directive parsing accidents.  Tests
live in `tests/test_sky_page.py`; run pyflakes/mypy on `wxskyfield_sky.py` too.

IMPORTANT import gotcha: in an installed WeeWX, bin/user modules are importable only as the
`user` package (`user.wxskyfield`) — a plain `import wxskyfield` raises ModuleNotFoundError
at report time even though the test suite (which puts bin/user itself on sys.path) accepts
it.  Cross-module references must go through `wxskyfield_sky._wxskyfield()`, which tries the
installed form first; a bare fallback re-import would also create a second copy of the module
whose classes fail isinstance checks.

**Correctness policy: accepted definitions over PyEphem compatibility.**  PyEphem is
deprecated and measurably wrong in places (its Jupiter CMLs are ~0.8° off the IAU
definition; it applies refraction to custom horizons where USNO twilight is geometric).
Prefer the USNO/IAU/Meeus answer, document every deviation in the README section
"Differences from PyEphem", and give it a changes.txt bullet.  Return conventions:
`FLOAT_ANGLES` attributes are decimal degrees; PyEphem-shaped attributes (`libration_*`,
`colong`, `cmlI/II`, `earth_tilt`, `separation`, `parallactic_angle`) are radians floats,
matching PyEphem's numeric scale.

**Stars**: `NAMED_STARS` maps tag names to Hipparcos numbers — the IAU Catalog of Star
Names (IAU-CSN, every entry with an HIP number) plus PyEphem's names as legacy aliases.
`wxskyfield_stars.dat` is an excerpt of unmodified `hip_main.dat` records covering exactly
those HIPs; a user-installed full `hip_main.dat` (gitignored) is preferred when present and
enables `$almanac.hip_<number>` tags for any Hipparcos star (loaded lazily, misses cached).
A malformed catalog record must only disable that one star.

**Installed file naming**: files this extension installs into `bin/user` are prefixed
`wxskyfield_` (`wxskyfield_de421.bsp`, `wxskyfield_stars.dat`) so no other extension can claim
them — and remove them on its uninstall.  Skyfield does not care about the ephemeris filename.
The module cannot be named `skyfield.py` (bin/user is on sys.path; it would shadow the Skyfield
library), and `skyfieldalmanac.py` is taken by the independent weewx-skyfield-almanac extension.
`hip_main.dat` deliberately keeps its canonical name: it is user-supplied, not installed.

## Tests

`tests/test_almanac.py` pins TZ to America/Los_Angeles and uses fixed regression values for
Palo Alto on 2025-06-21 (`TIME_TS`).  Key fixtures/helpers: `sky` (session-scoped engine),
`almanac` (registers the Skyfield almanac, restores the global list), `skyfield_only_almanac`
(simulates a system without PyEphem), `saved_almanacs()`, `pyephem_observer()`.  Two
permanent audits matter when adding features: `TestPyEphemParityAudit` (with PyEphem,
everything the built-in almanac could do must still evaluate) and `TestSkyfieldOnlyAudit`
(without PyEphem, every supported tag must evaluate — add new native tags to
`SKYFIELD_ONLY_EXPRESSIONS`).  PyEphem-dependent tests skip via `pytest.importorskip`.

## Releasing

Version lives in two places: `install.py` (`version=`) and `WXSKYFIELD_VERSION` in
wxskyfield.py.  Every user-visible change gets a bullet in changes.txt under the release
heading — action-required items (renames, config changes) go at the TOP of the entry.
