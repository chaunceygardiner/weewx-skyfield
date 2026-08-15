---
title: Glossary
layout: default
nav_order: 11
description: The astronomical terms this manual uses — transit, culmination, elongation, colongitude, apsis, ZHR, analemma and the rest — in plain language.
---

# Glossary

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

This manual is written for people who run weather stations, not for astronomers.  Where it
uses a term of art, this page explains it.

**Altitude** — how high something is above the horizon, in degrees.  0° is the horizon, 90°
is straight overhead.  Not to be confused with your station's *elevation*, which WeeWX also
calls altitude.

**Analemma** — the figure-eight the sun traces if you photograph it at the same clock time
all year.  It is the sum of Earth's axial tilt and its elliptical orbit.

**Antitransit** — the moment a body crosses the *lower* meridian: the midnight counterpart
of transit, when it is as far below your horizon as it will get.

**Apogee / perigee** — the moon's farthest and closest points from Earth.  Collectively,
**apsides**.

**Aphelion / perihelion** — Earth's farthest and closest points from the sun (early July and
early January).  For a comet, perihelion is its closest approach to the sun — the moment it
is likely to be brightest.

**Astrometric position** — a body's position corrected for light travel time but not for
the aberration and refraction that affect what you actually see.  Contrast *apparent* and
*topocentric*.

**Azimuth** — compass direction, in degrees: 0° north, 90° east, 180° south, 270° west.

**Circumpolar** — never sets, from your latitude.  Its opposite here is **neverup**.

**Colongitude** — the selenographic longitude of the sunrise line on the moon, the standard
way of saying which part of the lunar surface is lit.

**Culmination** — the highest point of a pass; for satellites, this manual's word for
transit.

**Declination** — celestial latitude: how far north or south of the celestial equator a body
sits.  Paired with *right ascension*.

**Ecliptic** — the plane of Earth's orbit, and so the line the sun appears to follow through
the year.  The planets stay near it.

**Elongation** — the angle between a body and the sun as seen from Earth.  Small elongation
means the body is lost in the sun's glare; large elongation means it is well placed.

**Ephemeris** — a table (here, JPL's DE421 file) from which the positions of the sun, moon
and planets are computed.

**Equation of time** — the difference between what a sundial reads and what a clock reads,
swinging roughly ±16 minutes across the year.  See [the tag](tag-index.md#top-level-tags).

**Geocentric** — measured from Earth's centre.  Contrast *topocentric*.

**Heliocentric** — measured from the sun's centre.  The orrery panel is a heliocentric view.

**Hipparcos** — the ESA satellite mission whose catalog of 118,218 stars ships with this
extension.  A star's catalog number is its HIP number.

**Hour angle** — how far a body is from your meridian, measured along its daily path: 0 at
transit, negative before, positive after.

**Libration** — the moon's slight rocking, which lets us see about 59% of its surface over
time rather than exactly half.

**Lunation** — one complete cycle of moon phases, new moon to new moon, about 29.5 days.

**Magnitude** — brightness, on a backwards scale: smaller is brighter, and each step of 1 is
about 2.5×.  Sirius is −1.4; the naked-eye limit under a dark sky is about 6.5.

**Meridian** — the imaginary north–south line passing directly overhead.  A body *transits*
when it crosses it.

**NORAD catalog number** — the number that identifies a satellite: 25544 is the ISS.

**Parallactic angle** — the angle between "up" as seen by an observer and celestial north,
which is what tells you how a chart's orientation relates to the view through a telescope.

**Parallax** — the tiny shift in a star's apparent position as Earth orbits, and the only
direct measure of its distance.  A star without a measured parallax has no known distance,
which is why this extension reports `N/A` rather than a fictitious number.

**Plate** — this manual's word for one of the Sky page's two color schemes, borrowed from
printed star atlases: the **night plate** (the default dark theme) and the **paper plate**
(the light one).  A plate is chosen at generation time by the `theme`
[option](configuration.md#the-sky-pages-report-stanza) and baked into the page; see
[the two plates](sky-page.md#the-two-plates).

**Radiant** — the point on the sky meteors in a shower appear to stream away from.

**Refraction** — the atmosphere bending light near the horizon, which makes bodies appear
slightly higher than they are and shifts every rise and set time.  It varies with the real
atmosphere in ways no model captures — see [Accuracy](accuracy.md).

**Right ascension** — celestial longitude, the east–west companion to declination.

**Sidereal time** — time kept by the stars rather than the sun.  A sidereal day is about
four minutes shorter than a solar one, which is why the same stars rise four minutes earlier
each night.

**SGP4** — the standard model that turns a satellite's published orbital elements into a
position.  Its input ages quickly, which is why this extension refuses elements more than
seven days old.

**Solar time** — time as a sundial keeps it, running ahead of or behind clock time by the
*equation of time*.

**Supermoon** — a full moon falling within about a day of perigee, so it appears slightly
larger and brighter.  This extension's tag uses exactly that rule.

**TLE (two-line element set)** — the compact text format satellite orbital elements come in.
Each cached file here holds one satellite's.

**Topocentric** — measured from where *you* stand on Earth's surface, rather than from its
centre.  This is what you actually see, and what most of this extension's position tags
report.

**Transit** — the moment a body crosses your meridian, which is when it is highest in your
sky.

**Twilight** — the time between sunset and full darkness, in three defined stages: **civil**
(sun 6° below the horizon; you can still read outside), **nautical** (12°; the horizon is
still discernible at sea), and **astronomical** (18°; the sky is as dark as it will get).

**ZHR (zenithal hourly rate)** — the number of meteors an ideal observer would see per hour
under a perfectly dark sky with the radiant directly overhead.  Real counts are always
lower, which is why the Sky page reports the moon's illumination beside it.
