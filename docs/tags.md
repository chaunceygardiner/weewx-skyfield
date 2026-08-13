---
title: Almanac tags
layout: default
nav_order: 5
has_children: true
description: The $almanac tags weewx-skyfield computes natively — bodies, stars, satellites, comets, meteor showers, eclipses, constellations — plus its differences from PyEphem and the result cache.
---

# Almanac tags

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

## Bodies

The Skyfield almanac natively computes, for the sun, the moon and all planets (plus Pluto):

- rise/set/transit, including `next_`/`previous_` rising, setting, transit and antitransit;
- custom horizons and `use_center` (for twilight tags such as
  `$almanac(horizon=-6).sun(use_center=1).rise`);
- azimuth/altitude, right ascension/declination (topocentric, astrometric and geocentric) and
  the hour angle;
- heliocentric longitude/latitude, elongation, earth and sun distance, with unit-aware
  `distance`/`distance_from_sun` twins (2.1) described below;
- visible time and its day-over-day change;
- magnitude (`$almanac.venus.mag`), percent illuminated (`$almanac.venus.phase`, with its
  unit-aware twin `illumination` (2.1), plus the moon's PyEphem-style 0–1 fraction,
  `$almanac.moon.moon_phase`), and apparent
  angular size (`$almanac.sun.size`, `$almanac.moon.radius_size`);
- `circumpolar`/`neverup`, parallactic angle, sidereal time, and solar time and the
  equation of time (2.1);
- the moon's libration, selenographic colongitude and subsolar latitude, Jupiter's central
  meridian longitudes and Saturn's ring tilt;
- equinoxes, solstices, moon phases and the moon index;
- the moon's perigee and apogee times (`$almanac.moon.next_perigee`, `previous_perigee`,
  `next_apogee`, `previous_apogee` — 2.1, below).

PyEphem is *not* required for any of these, nor for any tag used by WeeWX's standard skins.

The distances have unit-aware twins (2.1): `$almanac.mars.distance` (from Earth —
mirroring the satellites, whose `.distance` is likewise the distance from the observer) and
`$almanac.mars.distance_from_sun` serve the same values as the raw AU floats
`earth_distance`/`sun_distance`, as ValueHelpers — "1.8588 AU" by default in every unit
system, converting on ask (`$almanac.moon.distance.km`, `$almanac.mars.distance.mile`).
The unit registers with WeeWX as `astronomical_unit` in its own group,
`group_distance_astronomical`, so a skin can restyle the whole family: a `[Units]`
`[[Groups]]` entry `group_distance_astronomical = km` reports kilometers everywhere, and
`[[StringFormats]]`/`[[Labels]]` entries for `astronomical_unit` adjust the precision
(default `%.4f`) and label (default ` AU`).

The moon serves its apsides (2.1): `$almanac.moon.next_perigee`,
`previous_perigee`, `next_apogee` and `previous_apogee` are the times of the moon's closest
and farthest approach — the supermoon machinery.  The extremum is searched on the geometric
center-to-center distance, the definition the published apsis tables (Meeus; Espenak) use,
reproducing them to the minute; the results are cached like the almanac's other event tags,
and near the edges of the ephemeris span the tags report an honest "N/A".  A supermoon's
headline number is then one time-travel away —
`$almanac(almanac_time=$almanac.moon.next_perigee.raw).moon.distance.km` is the perigee
distance.  Moon only: no other served body orbits the observer, so any other body reports a
clean per-tag error — though Earth itself gets the same treatment around the sun:
`$almanac.next_perihelion` and `$almanac.next_aphelion` (with `previous_` twins) are
top-level tags for Earth's closest and farthest approach — early January and early July,
matching the published instants within a minute.  (No namespace clash with a comet's
per-body `.perihelion`.)  As loopdata fields they event-tier by their `next_` names.  And
the supermoon rule itself is a tag: `$almanac.next_supermoon` is
the instant of the next full moon falling within a day of perigee — the engine's single
copy of the definition (searched forward full moon by full moon, one or two qualify per
year), so the Sky page's callout and any live page read it instead of re-deriving it.  As
a loopdata field it event-tiers by its `next_` name.

Two clock tags complete the surface (2.1).  `$almanac.solar_time` is the local apparent
solar time — what a sundial reads — as an angle in decimal degrees like `sidereal_time`
(180° is solar noon), `$almanac.solar_angle` its unit-aware twin, and
`$almanac.equation_of_time` the
equation of time as a signed duration ValueHelper: apparent minus mean solar time, positive
when the sundial runs ahead of the clock — about +16 minutes in early November, −14 in
mid-February (see [Accuracy and conventions](accuracy.md#differences-from-pyephem) for the sign
convention).

There is no `$almanac.earth`: Earth is the observer, not a served body (PyEphem, which this
almanac replaces, has no Earth body either).  Earth's heliocentric coordinates are available
all the same — `$almanac.sun.hlongitude` and `$almanac.sun.hlatitude` report them, per the
XEphem convention (see [Accuracy and conventions](accuracy.md#differences-from-pyephem)).

## Constellations and eclipses

Two tag families (1.9) have no PyEphem counterpart at all.

Every body, stars included, reports the constellation it currently stands in —
`$almanac.saturn.constellation` gives "Pisces" — judged from the observer's topocentric
place against the IAU boundaries (the boundary map ships inside the Skyfield library;
nothing is downloaded).  The value is the Latin name in every language (it is data:
templates comparing it and loopdata fields publishing it always see the same string), and
it carries the other views of the answer as attributes (1.13):
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
`$almanac.moon.label` (1.12).  Add the tag name to the report's `[Almanac]` section —
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

Translating names this way needs **WeeWX 5.3 or later**: 5.3 is what began handing an almanac
the report's whole `[Almanac]` section.  On 5.2 the tag still renders — it gives the English
name — and this applies equally to `.constellation.label` and
`$almanac.next_meteor_shower.label`.

## Stars

Named stars (e.g., `$almanac.rigel.rise`, `$almanac.polaris.circumpolar`,
`$almanac.sirius.mag`) are computed natively.  The names are the official proper names of the
IAU Catalog of Star Names (every entry of the Working Group on Star Names' IAU-CSN list with a
Hipparcos number), plus PyEphem's 115 star names for backward compatibility (a few of those
are legacy spellings of the same stars, e.g. `albereo` for `albireo`) — 420 names in all,
covering 412 stars.  Multi-word names use underscores and diacritics are dropped
(`$almanac.kaus_australis.rise`, `$almanac.barnards_star.mag`).

Any other Hipparcos star can be addressed by catalog number: `$almanac.hip_57939.rise` —
the *complete* Hipparcos Catalogue ships with the extension (2.0) as
`wxskyfield_stars.dat.gz` (The Hipparcos and Tycho Catalogues, ESA SP-1200, 1997;
distributed by CDS as VizieR catalog I/239), so the star positions, proper motions,
parallaxes and magnitudes of all 118,218 stars are available with nothing to download.

Unlike PyEphem, `earth_distance` and `sun_distance` work for stars (in astronomical units,
like the planets — e.g., `$almanac.proxima_centauri.earth_distance`), computed from the star's
Hipparcos parallax.  The unit-aware twins serve stars too — `$almanac.rigel.distance` — and a
star whose catalog record has no measured parallax has no known distance: its twins report
"N/A" rather than a fictitious number.

## Satellites

The almanac tracks earth satellites (2.0).  The `[Skyfield]` `[[Satellites]]` section
of `weewx.conf` maps tag names to NORAD catalog numbers — the installer writes `iss = 25544`
and `tiangong = 48274`, the two naked-eye space stations — and that one list drives both the
tags and the fetch list; how the orbital elements are fetched and kept fresh, the
`satellite_downloads` switch, and the air-gapped alternative are on the
[installation page](installation.md#satellites).

Each entry serves the almanac's usual position surface: `$almanac.iss.alt`/`.az`/`.ra`/`.dec`
(decimal degrees) and their unit-aware siblings `.altitude`/`.azimuth`/`.topo_ra`/`.topo_dec`;
`.distance`, the slant range from observer to satellite, a ValueHelper honoring the report's
distance units; and `.sunlit` — whether the satellite is in sunlight.  `$almanac.sat_25544.alt`
is an alternate spelling for a *listed* satellite, mirroring `hip_<number>`; it never fetches
an unlisted one.  `.rise`, `.transit` and `.set` are the *next* occurrence from the almanac's
time — transit meaning culmination — because passes are minutes long and "today's" is rarely
the interesting one.  The heart of the surface is the pass:

- `$almanac.iss.next_pass` — the next pass, or the one in progress: once the satellite is
  up, `next_pass` is the current pass until it sets.  Its attributes: `.rise`,
  `.culmination` and `.set` (times), `.max_altitude` (an angle ValueHelper),
  `.rise_azimuth`, `.culmination_azimuth` and `.set_azimuth` (compass ValueHelpers, so
  `.ordinal_compass` renders "WSW"), `.duration`, and `.visible`.
- `$almanac.iss.next_visible_pass` — the same attributes, for the next pass *worth
  watching*: the satellite sunlit while your sky is dark (sun below −6° — the
  civil-twilight convention Heavens-Above uses) at some moment of the pass, and peaking at
  least 10° up.

A pass runs rise → culmination → set across the geometric horizon — no refraction, which is
irrelevant to satellite watching — and the almanac's existing horizon argument applies:
`$almanac(horizon=10).iss.next_pass` counts only the portion above 10°.  Passes are searched
within the orbital elements' seven-day validity window; when no qualifying pass exists,
every attribute honestly reads "N/A" — Hubble from northern Europe, for example, never
rises.  Likewise when the elements themselves are unusable (missing, or their epoch more
than seven days older than the almanac's time): every tag reads "N/A" rather than reporting
confidently wrong pass times, and the always-live diagnostics `$almanac.iss.elements_epoch`
and `$almanac.iss.elements_age` say why.

Deliberately absent: an apparent-magnitude tag (satellite brightness models are hand-wavy;
`sunlit` and `.max_altitude` are served honestly instead) and pass *lists* — ask if you need
tonight's passes as a table.

On [live-updating pages](index.md#live-updating-pages), the satellite tags work as loopdata
almanac fields like any others — `almanac.iss.next_pass.rise` included.  Use loopdata 6.9 or
later: earlier versions could cache a temporarily-unavailable satellite field's "N/A" until
the day rolled over, instead of recovering the moment fresh elements arrive.

## Comets

The almanac serves comets (2.1).  The `[Skyfield]` `[[Comets]]` section of
`weewx.conf` maps tag names to Minor Planet Center designations — the installer writes
`halley = 1P` and `hale_bopp = C/1995 O1` — and each entry serves the almanac's full
planet-style surface: rise, set
and transit (with the whole `next_`/`previous_` family), altitude/azimuth, right
ascension/declination in every flavor, `distance` and `distance_from_sun` (the raw AU
floats `earth_distance`/`sun_distance` included), elongation, `visible`, `illumination`,
the constellation it stands in, and `mag` — plus one tag of the comet's own:
`$almanac.halley.perihelion`, the time of perihelion passage straight from the MPC
elements.  It can lie in the past (Hale-Bopp's says 1997) — the current orbit solution's
perihelion is simply a fact — so consumers judge upcoming-ness themselves; the Sky page's
countdown chip shows it only when it lies ahead within a year.  How the one CometEls.txt
element file is fetched and kept fresh, the `comet_downloads` switch, and the air-gapped
alternative are on the [installation page](installation.md#comets).

The friendly name is yours to choose — the tag, the dome label and `.label` ride it, and
`[Almanac]` entries rename it per language, exactly like a satellite's.  The value is the
comet's designation as the MPC's file prints it — `12P`, `220P`, `C/2023 A3`, a fragment
named explicitly as `C/1947 X1-B` — matched after case and whitespace normalization only,
never by fuzzy name.  There is deliberately no pass machinery: a comet rises and sets
daily like a planet, so `next_pass` reports a per-tag error exactly as it does for Mars.
Comet tags never fall through to PyEphem (which has no comets): anything outside the comet
surface is a clean per-tag error, the satellite convention.

Skyfield propagates the elements as unperturbed two-body orbits — where-do-I-look
accuracy, not ephemeris-grade positions far from the elements' epoch; the routine refresh
keeps the epoch current.  The MPC drops comets that have faded from observability, so a
configured comet can vanish from a fresh download: its tags then read "N/A" (a log warning
names it, once at the crossing), never an error and never a stale number, with
`$almanac.halley.elements_epoch` and `.elements_age` always live as diagnostics.  Unlike
satellite elements there is no age cutoff — two-body comet elements degrade gracefully
over months, not days.

`$almanac.halley.mag` is the MPC total magnitude, m = g + 5·log10(Δ) + 2.5·k·log10(r),
from the file's g/k parameters — the standard formula, and comets are notorious for
deviating from it: outbursts brighten them by magnitudes overnight, and famous ones have
fizzled.  Treat it as expectation, not measurement.  (This is a deliberate policy
difference from satellites, which serve no magnitude at all: comets have a standard
formula; satellites do not.)

Comet tags work as loopdata almanac fields like any others, and the engine invalidates its
per-tag caches when the element file refreshes, so live pages never serve old-element
times.

## Meteor showers

The almanac knows the dozen major annual meteor showers of the IMO working list (2.1).  Each peak is anchored to the sun's ecliptic longitude — the Perseids peak when the
sun reaches λ 140.0° — so every year's peak instant is computed from the ephemeris, never
looked up.

`$almanac.next_meteor_shower` always serves the shower whose peak lies next ahead, as
plain attributes: `.name` (stable English data, like `constellation`), `.label` (the
report's `[Almanac]` `[[MeteorShowers]]` translation, falling back to the name), `.peak`
(a time ValueHelper), `.zhr`, `.radiant_ra`/`.radiant_dec` (J2000 degrees) with the live
refracted `.radiant_alt`/`.radiant_az`, and `.parent` — the body whose debris the shower
is.  `$almanac.active_meteor_showers` is the tuple of showers whose activity window
contains the almanac's time, each carrying its own apparition's peak (which may honestly
lie in the past: an active shower past maximum is still active).  As loopdata fields the
`next_meteor_shower` chains tier as event fields by their `next_` prefix, like the moon
phases.

## Where the rest of the story lives

Three topics that used to live on this page now have their own, because they are about
*why* the numbers are what they are rather than *which tag returns them*:

- **[Values, units and types](values-and-units.md)** — degrees versus radians, the
  ValueHelper twins, and the `.raw` trap that silently rescales a duration.
- **[Accuracy and conventions](accuracy.md)** — every difference from PyEphem, why DE421
  is the bundled ephemeris, what comet and satellite predictions can honestly promise, and
  how fallback to PyEphem works.
- **[Performance](performance.md)** — the transparent result cache, what it costs to be
  wrong about it, and the measured numbers.

And **[the tag index](tag-index.md)** is the A-to-Z lookup: every tag, its type, its units
and the release it arrived in.
