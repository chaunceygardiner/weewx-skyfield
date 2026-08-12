---
title: Performance
layout: default
nav_order: 10
description: How weewx-skyfield stays fast — the transparent result cache, what each Sky page panel costs, and how to trim generation time on small hardware.
---

# Performance

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Astronomy is expensive: a single rise time is an iterative search, not a formula.  A heavy
skin can ask the almanac thousands of questions per report cycle.  This extension answers
them fast enough to run on a Raspberry Pi, and the reason is one mechanism you never
configure.

## The result cache

Report generation asks the almanac the same expensive questions over and over: every
template mention of `$almanac.moon.rise` runs a fresh rise search, a page rendered in desktop
and smartphone variants repeats each other's work, and the day-window verbs
(`rise`/`set`/`transit`, searched from local midnight) return the same instant for every
almanac time within the day.  Since 1.4, results are cached at the computation layer,
transparently — no configuration, no new tags:

- **Day-window searches** (rise/set/transit, the effective-horizon body radius, and the
  `next_*`/`previous_*` events) are reused across report cycles.  A "next full moon" found
  once is served until it happens; a day's moonrise is computed once, not once per mention
  per page per cycle.
- **Instantaneous positions** (alt/az, ra/dec, magnitudes, moon phase) are keyed on the exact
  timestamp: repeats within a cycle collapse, including desktop/smartphone twin pages, and
  time-traveled tags anchored to fixed instants (`almanac_time=` loops building calendars or
  analemmas) are reused across cycles.  A position at a *new* timestamp is always freshly
  computed — nothing that moves on a page is ever served stale.

Only raw floats are cached, never formatted values, so skins with different formatters cannot
leak into each other.

### The one deliberate tolerance

Rise/set cache keys quantize the effective horizon to 0.002 degrees, because the default
horizon scales refraction by the almanac's current temperature and pressure, which drift a
few thousandths of a degree between report cycles.  Within a day, a cached rise/set may
therefore be served under conditions differing by up to that quantum — worth well under a
second of event time (worst measured 0.64 s over a 15-hour replay of real sensor data), below
the refraction model's own physical uncertainty.  The displayed minute agrees with a fresh
computation except when the true time sits within that fraction of a second of the boundary.

For perspective, an uncached answer is itself a moving target: because refraction follows the
live temperature and pressure, a fresh computation of the same rise or set wanders a few
seconds over the course of a day — the cache tracks that wander well within the wander
itself.

Cache pools are bounded and simply cleared on overflow; correctness never depends on an entry
being present.

### What to expect after a restart

Expect the first report cycle after a WeeWX restart, and the first after local midnight, to
run at full uncached cost while the day's entries repopulate.  In practice the midnight cycle
is often much cheaper: skins with calendar strips or day-window loops have already cached the
new day's searches.

### Measured

On the eight-page paloaltoweather.com site — a heavy consumer, about 3,200 almanac tag
evaluations per cycle, on a Raspberry Pi 5:

| | Template generation |
|---|---|
| Before the cache | ~17.7 s per report cycle |
| Warm cycles | ~4.6 s per report cycle |
| First cycle after a restart | ~10 s |

## What the Sky page costs

[The Sky page](sky-page.md) is one page doing the work of a small skin, so it is the
costliest single page this extension generates — but the result cache is what makes that a
matter of seconds rather than minutes, and on a Raspberry Pi 5 it draws comfortably inside
an archive interval.  What it costs on your station depends mostly on what you have
configured: the star magnitude limit, the constellation figures, and how many satellites and
comets are in the roster.

The work concentrates in a few panels:

| Panel | Cost | Cached across cycles? |
|---|---|---|
| The solar year (`daylength_svg`) | Several hundred rise/set searches | Yes — anchored to fixed weekly instants |
| The analemma (`analemma_svg`) | 54 almanac evaluations | Yes — same anchoring |
| The equation of time (`eot_svg`) | Weekly samples at the analemma's instants | Yes |
| The dome's star field | One vectorized Skyfield observe — a few milliseconds | N/A |
| Everything else | Ordinary per-cycle work | Positions keyed on the instant |

Because the year-scale panels are anchored to fixed instants, the [result
cache](#the-result-cache) reuses them across cycles: the full price is paid once at startup,
not every cycle.

## Trimming it

Only if you want to.  On hardware that is struggling — an older Pi sharing an archive
interval with a large skin — these are the levers, in rough order of how much you gain per
unit of loss:

1. **Generate the page less often.**  Set `report_timing` in the `[[SkyfieldReport]]` stanza.
   The tags keep working at full speed; only the bundled page slows down.
2. **Lower `star_mag_limit`.**  The default 5.0 plots roughly 800 stars; the pre-2.0 sparse
   look (`star_mag_limit = 2.6`, `star_label_mag = 1.1`) plots a fraction of that.  See
   [Configuration](configuration.md#the-sky-pages-report-stanza).
3. **Turn off `constellation_lines`.**  Fewer marks to lay out and fewer label collisions to
   resolve.
4. **Keep the satellite list short.**  Each configured satellite is a separate fetch every
   three hours and its own pass search.
5. **Turn the page off entirely** with `enable = false` in its stanza.  Every `$almanac` tag
   still works — you lose only the bundled showcase page.

## Memory

The ephemeris is read fully into memory at startup, about 16 MB.  That is a deliberate
trade: it is what makes upgrading over a running WeeWX safe, since replacing the extension's
files on disk cannot disturb the running almanac.  The complete Hipparcos catalog is read
lazily and misses are cached, so a station that never asks for an obscure star never pays for
one.

## Comparing with the alternative

An independent extension, weewx-skyfield-almanac, solves the same problem with a different
design.  A 2026 benchmark on identical hardware found the two effectively tied on a cold
first evaluation, with this extension roughly 20× faster in steady state — it caches results,
the other does not — while the other used about 27 MB less resident memory, because it maps
its ephemeris rather than reading it in.  Which trade suits you depends on whether your
station has spare RAM or spare seconds.
