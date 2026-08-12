---
title: Recipes
layout: default
parent: Almanac tags
nav_order: 3
description: Copy-and-paste Cheetah snippets for WeeWX skins — twilight blocks, tonight's ISS pass, the moon with its apsides, comets, countdowns and time travel.
---

# Recipes

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Working snippets for your own skin's Cheetah templates.  Each one uses only public
`$almanac` tags, so it works in any skin with this extension installed — no search list, no
configuration.  For the drawn panels rather than the numbers, see
[Panels in your own skin](panels.md).

{: .note }
Every tag chain on this page is evaluated against a real almanac by the test suite, so these
read correctly as written.  What the suite cannot check is your skin's own HTML around them.

## A twilight block

The four moments that bracket a day, using the USNO's geometric definitions:

```
<table>
  <tr><td>Astronomical dawn</td><td>$almanac(horizon=-18).sun(use_center=1).rise</td></tr>
  <tr><td>Nautical dawn</td>     <td>$almanac(horizon=-12).sun(use_center=1).rise</td></tr>
  <tr><td>Civil dawn</td>        <td>$almanac(horizon=-6).sun(use_center=1).rise</td></tr>
  <tr><td>Sunrise</td>           <td>$almanac.sun.rise</td></tr>
  <tr><td>Sunset</td>            <td>$almanac.sun.set</td></tr>
  <tr><td>Civil dusk</td>        <td>$almanac(horizon=-6).sun(use_center=1).set</td></tr>
  <tr><td>Nautical dusk</td>     <td>$almanac(horizon=-12).sun(use_center=1).set</td></tr>
  <tr><td>Astronomical dark</td> <td>$almanac(horizon=-18).sun(use_center=1).set</td></tr>
</table>
```

`use_center=1` measures to the sun's centre rather than its upper limb, which is what the
twilight definitions specify.  See [Accuracy](accuracy.md#differences-from-pyephem) for why
no refraction is applied to a custom horizon.

## Day length, and whether it is growing

```
Daylight today: $almanac.sun.visible.long_form
That is $almanac.sun.visible_change() #if $almanac.sun.visible_change().raw > 0 then "longer" else "shorter"# than yesterday.
```

`visible_change()` is a **method** — the parentheses are required.  It takes an optional
argument: `visible_change(7)` compares against a week ago.

## The moon, with its apsides

```
$almanac.moon.label is $almanac.moon.phase% illuminated ($almanac.moon_phase).
It rises $almanac.moon.rise and sets $almanac.moon.set,
standing in $almanac.moon.constellation.label.

Next perigee: $almanac.moon.next_perigee
Next apogee: $almanac.moon.next_apogee
```

`$almanac.moon_phase` — the top-level tag — is the phase's *name*, translated by your
report.  `$almanac.moon.phase` is the percentage, and `$almanac.moon.moon_phase` is
PyEphem's 0–1 fraction.  All three are different things; the
[tag index](tag-index.md) keeps them apart.

## Tonight's ISS pass

```
#set $pass = $almanac.iss.next_visible_pass
#if $pass.visible
  The ISS appears $pass.rise ($pass.rise_azimuth.ordinal_compass),
  peaks at $pass.max_altitude ($pass.culmination_azimuth.ordinal_compass),
  and disappears $pass.set ($pass.set_azimuth.ordinal_compass).
  Visible for $pass.duration.
#else
  No visible ISS pass in the coming week.
#end if
```

Guard on `.visible` rather than on a time: with no qualifying pass every attribute is an
empty ValueHelper that renders `N/A`, and `.visible` is the flag that says so.
`next_visible_pass` is deliberately strict — sunlit, sky dark, peaking at least 10° up — so
use `next_pass` when you want every pass regardless of whether you could see it.

If a satellite's elements have gone stale, everything reads `N/A` and these two say why:

```
Elements issued $almanac.iss.elements_epoch ($almanac.iss.elements_age old)
```

## A comet, when there is one worth showing

```
#set $comet = $almanac.halley
#if $comet.mag
  $comet.label is magnitude $comet.mag, $comet.distance from Earth,
  in $comet.constellation.label.  Perihelion: $comet.perihelion
#end if
```

A configured comet the Minor Planet Center has dropped reports `N/A` across the board rather
than stale numbers, so guarding on `mag` keeps the block quiet until there is something to
say.  Remember the magnitude is the MPC's formula — expectation, not measurement.

## The next eclipse visible from here

```
The next eclipse visible from this station is a
$almanac.next_eclipse_type $almanac.next_eclipse_kind eclipse
on $almanac.next_eclipse.format("%B %e, %Y").
```

These three tags are designed to be used together: `next_eclipse` picks the sooner of the
lunar and solar candidates, `_kind` says which it found, and `_type` gives the type *as seen
from your location* — a station catching only the penumbra of a total solar eclipse honestly
reports `partial`.  Include the year: the next visible eclipse can be years out.

## The next meteor shower, and whether the moon will ruin it

```
#set $shower = $almanac.next_meteor_shower
The $shower.label peak $shower.peak.format("%B %e") — up to $shower.zhr per hour,
radiating from $shower.parent's debris.
#set $moon_at_peak = $almanac(almanac_time=$shower.peak.raw).moon.phase
#if $moon_at_peak > 60
  A $moon_at_peak% moon will wash out the fainter meteors.
#end if
```

That `almanac_time=` line is the time-travel idiom: it builds a new almanac at another
instant and asks it an ordinary question.  It is how the Sky page reports the moon's
interference honestly rather than quoting tonight's moon for a shower three weeks away.

## Time travel: the coming supermoon's distance

```
#set $sm = $almanac.next_supermoon
#if $sm.raw
  Next supermoon: $sm.format("%B %e, %Y"),
  when the moon will be $almanac(almanac_time=$sm.raw).moon.distance.km from Earth.
#end if
```

The same idiom, and the reason `next_supermoon` exists as a tag at all: the rule (a full
moon within a day of perigee) lives in the engine, so your page and every live page agree
rather than each re-deriving it.

## A planet roster

```
#for $body in ['mercury', 'venus', 'mars', 'jupiter', 'saturn']
  #set $p = getattr($almanac, $body)
  $p.label: rises $p.rise, magnitude $p.mag, in $p.constellation.label
#end for
```

`getattr` is how a template loops over bodies by name — the almanac binds each one as an
attribute.

## Guarding for "no answer"

Every recipe above assumes the honest-`N/A` contract: a tag with no answer renders `N/A`
rather than breaking your page.  When you want to hide a block instead of printing `N/A`,
test `.raw`:

```
#if $almanac.mars.rise.raw
  Mars rises $almanac.mars.rise
#end if
```

{: .important }
When you do arithmetic on a `.raw` value, pin the unit — `$almanac.sun.visible.second.raw`,
`$almanac.sunrise.unix_epoch.raw`.  An unpinned `.raw` follows the report's own unit
settings, which is how a page can silently start reporting hours where it means seconds.
[Values, units and types](values-and-units.md#the-raw-trap) has the full story.

## Where to go next

- Drawn panels — the dome, ribbons, orrery — are [`$sky_page` methods](panels.md).
- The same tags on a page that updates every few seconds: [Live-updating pages](live-pages.md).
- Everything available: [the tag index](tag-index.md).
