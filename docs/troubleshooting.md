---
title: Troubleshooting
layout: default
nav_order: 12
description: Diagnosing weewx-skyfield — confirming the almanac is registered, why a tag reads N/A, what each log message means, and the upstream Skyfield issues you might notice.
---

# Troubleshooting

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Start here: **is the Skyfield almanac actually registered?**  Nearly every "my values didn't
change" report answers itself at this line.  Restart WeeWX and look in the log for:

```
Skyfield almanac registered; reports will use Skyfield for almanac computations.
```

If that line is present, this extension is answering your `$almanac` tags.  If it is absent,
one of the [startup messages](#startup-messages) below says why.

## Symptoms

### The Sky page never appeared

It lands at `<HTML_ROOT>/skyfield/index.html` after the first report cycle — not
immediately on restart.  If it is still missing:

- Check `enable` in the `[[SkyfieldReport]]` stanza under `[StdReport]`.
- Check where it actually went.  If you see `public_html/public_html/skyfield`, `HTML_ROOT`
  in that stanza was written as an absolute-looking path; it must stay
  [relative](configuration.md#the-sky-pages-report-stanza).
- Look for a Cheetah error in the log naming `index.html.tmpl`.

### My almanac values didn't change after installing

If the registration line is in the log, they did change — but the two almanacs agree closely
for common tags, so sunrise moving by a few seconds is easy to miss.  Compare something with
a real difference: a twilight tag with a custom horizon
(`$almanac(horizon=-6).sun(use_center=1).rise`) differs from PyEphem by two to three
minutes, because this extension follows the USNO's geometric definition.  See
[Accuracy and conventions](accuracy.md).

### One body reads `N/A` for everything

Expected, and the diagnosis is built in.  A satellite whose elements are missing or more
than seven days old collapses every tag to `N/A` rather than reporting confidently wrong
pass times; a comet the MPC has dropped from CometEls.txt does the same.  Two tags stay live
precisely so you can see why:

```
$almanac.iss.elements_epoch      ## when the elements were issued
$almanac.iss.elements_age        ## how old they are now
```

The log names it once per crossing — see [element messages](#element-messages).  If the age
keeps growing, the fetch is failing: check network access to CelesTrak or the Minor Planet
Center, and confirm `satellite_downloads` / `comet_downloads` are not `false`.

### A satellite never has a visible pass

Often the truth rather than a fault.  A satellite's orbital inclination bounds the latitudes
it can appear over: Hubble, inclined 28.5°, never climbs usefully above the horizon for
stations poleward of about ±35°.  The configured defaults — ISS at 51.6° and Tiangong at
41.5° — put on a show for essentially everyone.  See
[Choosing satellites](installation.md#satellites).

Remember also that `next_visible_pass` is deliberately strict: sunlit, against a sky with the
sun below −6°, peaking at least 10° up.  `next_pass` is the unfiltered fact and will often
have an answer when `next_visible_pass` does not.

### A number looks wrong by a factor of 3600 or 57.3

A units problem, not an astronomy problem, and
[Values, units and types](values-and-units.md#the-raw-trap) diagnoses it — most often an
unpinned `.raw` read on a duration.

### A tag reports an error instead of a value

Per-tag errors are by design: they appear in place without taking down the page.  The usual
causes are asking a body for something outside its surface (a satellite has no `.phase`;
Mars has no `.next_pass`), or an almanac time outside the bundled ephemeris's span
(mid-1899 to 2053).  Satellite and comet tags never fall through to PyEphem, so an
unrecognized attribute on one is always a clean error rather than a mysterious PyEphem
value.

### Reports got slower

The first report cycle after a restart, and the first after local midnight, pay full
uncached cost while the day's entries repopulate; the cycles after them run warm.  If it is
slow *every* cycle, the Sky page is the busiest page here, and
[Performance](performance.md) explains what costs what and which options move the needle —
`star_mag_limit`, `constellation_lines`, `report_timing`, or `enable = false` on the page
while keeping every tag.

## Startup messages

| Message | Meaning |
|---|---|
| `Skyfield almanac registered; reports will use Skyfield…` | Working.  This is the line to look for. |
| `WxSkyfield status: disabled...enable it in the Skyfield section of weewx.conf.` | `enable = false` in `[Skyfield]`. |
| `This version of WeeWX (…) does not support almanac extensions` | WeeWX older than 5.2.  The extension declines gracefully and the built-in almanac stays in place. |
| `weewx-skyfield requires Skyfield 1.47 or later, found …` | Upgrade Skyfield — see [Upgrading Skyfield](installation.md#upgrading-skyfield).  Debian 12 ships 1.45, which is too old. |
| `Could not load …  The Skyfield almanac will not run.` | The ephemeris file could not be read.  Reinstall the extension. |
| `Could not build the skyfield timescale…` | Skyfield could not initialize; usually a broken or partial Skyfield install. |
| `init: Could not load the Hipparcos star catalog: … Star support disabled.` | Everything except star tags keeps working. |
| `Loaded N stars to magnitude M from the full Hipparcos catalog.` | Normal: the dome's star field. |
| `Ignoring unrecognized [Skyfield] option: …` | A typo, or a leftover from an older release — the pre-2.0 `stars` option lands here.  See [Configuration](configuration.md#the-skyfield-section). |
| `Ignoring [Skyfield] [[Satellites]] entry …` | The tag name shadows a planet, star, `hip_` or `sat_` name, or the NORAD number is not a number. |
| `Ignoring [Skyfield] [[Comets]] entry …` | Same, for a comet's name or designation. |

## Element messages

| Message | Meaning |
|---|---|
| `Fetched satellite elements for N.` / `Fetched comet elements into …` | A refresh succeeded. |
| `Could not fetch satellite elements for N (…); keeping the …` | A fetch failed; the previous file is kept and the retry backs off.  Harmless in isolation — a transient CelesTrak timeout recovers on its own. |
| `Satellite N has no usable elements (missing, unreadable, …)` | Every tag for that satellite now reads `N/A`.  Logged once at the crossing, not per tag. |
| `Satellite N has usable elements again.` | Recovered. |
| `Comet X (…) has no elements in the cached CometEls…` | The MPC dropped it, or the cache is missing.  Tags read `N/A`. |
| `Comet X (…) has elements again.` | Recovered. |

## Known Skyfield issues

Issues in the underlying [Skyfield](https://rhodesmill.org/skyfield/) library that you might
notice.  None require action; entries are removed as upstream releases fix them.

### A rare `RuntimeWarning` from `almanac.py` line 339

Very occasionally, report generation prints this — in the console when running reports by
hand, or in the log of a running WeeWX (at most once per start, since Python deduplicates
warnings):

```
skyfield/almanac.py:339: RuntimeWarning: invalid value encountered in divide
  return - 2*c / (b + sign * sqrt(discriminant))
```

This is an upstream Skyfield bug, tracked as
[skyfield issue #1114](https://github.com/skyfielders/python-skyfield/issues/1114), and it
affects Skyfield releases through 1.54.  The final refinement step of Skyfield's rise/set
solver fits a parabola through its last two altitude samples; when the solver's iteration
happens to land, to the last floating-point bit, exactly on the horizon, that fit degenerates
to a 0/0 division.  It is a pure floating-point coincidence: it can strike any body, any
latitude and any date, and the affected dates even differ between operating systems, NumPy
versions and CPU math libraries.  Inside Skyfield, the affected event's time becomes NaN.

**weewx-skyfield already contains the failure**: it discards any event time that is not a
finite time within the day being searched, so the worst possible outcome is a single rise or
set tag coming up empty for a while — and in practice pages render complete.  No
configuration change, downgrade or workaround is needed.

weewx-skyfield's author diagnosed the root cause — with a deterministic reproduction — in
[issue #1114](https://github.com/skyfielders/python-skyfield/issues/1114) and submitted
[pull request #1140](https://github.com/skyfielders/python-skyfield/pull/1140) with the fix
and a regression test.  **Skyfield merged the fix on August 4, 2026, closing the issue, and
shipped it in Skyfield 1.55 on August 7, 2026** — upgrading to Skyfield 1.55 or later makes
the warning disappear.  Upgrading is routine — see
[Upgrading Skyfield](installation.md#upgrading-skyfield).

## Still stuck

Open an issue on the
[weewx-skyfield GitHub project](https://github.com/chaunceygardiner/weewx-skyfield/issues)
with your WeeWX version, your Skyfield version
(`python -c 'import skyfield; print(skyfield.__version__)'`), the `[Skyfield]` section of
your `weewx.conf`, and the startup lines from your log.
