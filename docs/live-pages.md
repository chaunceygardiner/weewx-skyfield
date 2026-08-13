---
title: Live-updating pages
layout: default
nav_order: 7
description: Driving a continuously-updating page from weewx-skyfield — weewx-loopdata almanac fields, event tiering, pinned units, and the dome's machine-readable hooks.
---

# Live-updating pages

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

weewx-skyfield computes at **report time**.  Its tags, and the Sky page, refresh once per
report cycle — typically every few minutes.  That is right for an almanac: rise times do not
change between cycles.

But some of what this extension knows *does* move on a human timescale.  A satellite crosses
the whole sky in six minutes.  A countdown to sunset ticks.  For those, a page that redraws
in the browser needs values more often than a report cycle can deliver them — and that is a
different extension's job.

## How it fits together

Add [weewx-loopdata](https://github.com/chaunceygardiner/weewx-loopdata) (same author, **6.9
or later**).  Since loopdata 5.0 it evaluates *almanac fields* — report almanac tags with the
`$` removed — against whatever almanac is registered, which is this one once installed.  It
does that on every loop packet and writes the results to `loop-data.txt` for your page's
JavaScript to pick up.

```
$almanac.iss.next_pass.rise        ← the report tag
almanac.iss.next_pass.rise         ← the same thing as a loopdata field
```

One computation engine serves both, so the live values and the report values can never
disagree.  There is no second implementation to keep in step — which is exactly why this
extension is the engine's only home.

## Writing fields

Three rules cover almost everything.

**Drop the `$`, keep the chain.**  Anything in the [tag index](tag-index.md) works, including
the chains: `almanac.moon.constellation.label`, `almanac.iss.next_visible_pass.max_altitude`,
`almanac.next_meteor_shower.peak`.

**Pin the unit on every `.raw`.**  loopdata walks your target report's converter, so an
unpinned `.raw` means whatever that report's units say.  Write
`almanac.sunrise.unix_epoch.raw` and `almanac.sun.visible.second.raw`.  A `[Units]`
`[[Groups]]` override on the target report can otherwise silently change what a field means —
see [the `.raw` trap](values-and-units.md#the-raw-trap).

**Everything is a plain attribute.**  loopdata resolves chains with plain `getattr`, which —
unlike Cheetah — does not call methods for you.  This extension serves pass attributes,
shower attributes and `constellation.abbr` as plain attributes precisely so they work as
fields.  The exceptions are the callables listed in
[Values, units and types](values-and-units.md#attributes-methods-and-why-it-matters);
`visible_change()` and `separation()` cannot be loopdata fields.

## Event fields and why the names matter

loopdata tiers almanac fields by their names: a field whose leaf begins with `next_` or
`previous_` is an **event field**, computed once and held until it expires rather than
re-derived on every loop packet.  A moon-phase or eclipse search on every packet would be
ruinous; held as an event, it costs nothing.

This is why several tags here are spelled the way they are.  `next_perigee`,
`next_supermoon`, `next_perihelion` and the rest carry the `next_` prefix deliberately — an
unprefixed spelling would rerun an extremum search on every loop packet.  When you add a
field, prefer the `next_`-prefixed spelling where one exists.

Event expiry is also what rolls a finished satellite pass forward to the next one the moment
it ends, which is loopdata 6.9 behavior: earlier versions could cache a temporarily
unavailable satellite field's `N/A` until the day rolled over, instead of recovering as soon
as fresh elements arrived.  That is the reason for the 6.9 floor.

## Language

Live values follow the language of loopdata's *target report* — one language per loopdata
instance.  A field such as `almanac.moon.label` renders in that report's language, so a
station serving two languages needs the label resolved per page rather than per field.  See
[Translations](i18n.md).  Body, constellation and meteor shower names need WeeWX 5.3 or
later; on 5.2 the fields still publish, in English and Latin.

## Reusing this extension's charts, live

[The Sky page's panels](panels.md) are static SVG, but they are built to be *moved* by
someone else.  Every mark a live layer might reposition carries a machine-readable name, and
these are a stable contract:

| Hook | On | Meaning |
|---|---|---|
| `<g class="dome-body" data-body="mars">` | dome, pass chart | The sun's, moon's and each planet's mark; name labels carry the same `data-body`. |
| `data-body="<satellite>"` + `data-sunlit="1"`/`"0"` | dome | A satellite's position dot, and whether it is in sunlight — flip the dot between solid and hollow as it crosses the shadow line. |
| `data-bright="1"`/`"0"` | dome, orrery | A comet's diamond, and whether it is plausibly naked-eye. |
| `<g class="dome-track" data-body="iss">` | pass chart | The pass arc's group. |
| `$sky_page.satellite_names()` | template | The configured satellite tag names, in config order. |
| `$sky_page.comet_names()` | template | The configured comet tag names, in config order. |

Locate marks by these names, never by tooltip text — tooltips are translated.

## A worked example

[weewx-celestial](https://github.com/chaunceygardiner/weewx-celestial) (**8.1 or later**) is
the reference implementation: a complete live celestial page built entirely from loopdata
almanac fields, including this extension's own dome embedded as a live instrument, with each
satellite's marker swept across the sky in real time and flipping between sunlit and shadow
from the same `sunlit` flag the dome bakes in.

![weewx-skyfield's sky dome during a Tiangong zenith pass, animated live on the weewx-celestial page](https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/live_dome_tiangong.gif)

*The animation is weewx-celestial's live page, moved by weewx-loopdata fields —
weewx-skyfield's own Sky page stays static, refreshing once per report cycle.  The chart
itself is this extension's dome, embedded there.  Tiangong crosses the exact centre of the
dome, and partway across the marker inverts to a hollow ring as it slips into Earth's shadow
— still overhead, no longer shining.  In the opening seconds Terra is finishing its own low
western pass: two satellites on the dome at once.*

The [paloaltoweather.com celestial pages](https://www.paloaltoweather.com/celestial.html)
update the same way.

## Do you need this?

No, and most stations do not.  Every tag and every panel works with this extension alone.
Add loopdata when a page needs to show something *moving* — a pass in progress, a ticking
countdown — and not before.
