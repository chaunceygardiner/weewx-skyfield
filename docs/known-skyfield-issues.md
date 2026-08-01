---
title: Known Skyfield issues — weewx-skyfield
description: Upstream Skyfield library issues you might notice while running weewx-skyfield — what they look like, why they are harmless here, and their status.
---

# Known Skyfield issues

[Home](index.md) ·
[Installation](installation.md) ·
[Almanac tags](tags.md) ·
[The Sky page](sky-page.md) ·
[Sky panels in your skin](panels.md) ·
[Translating (i18n)](i18n.md) ·
[GitHub project](https://github.com/chaunceygardiner/weewx-skyfield)

---

This page collects issues in the underlying [Skyfield](https://rhodesmill.org/skyfield/)
library that you might notice while running weewx-skyfield.  None require action; entries
are removed as upstream releases fix them.

## A rare `RuntimeWarning` from `almanac.py` line 339

Very occasionally, report generation prints this warning — in the console when running
reports by hand (`weectl report run`), or in the log of a running WeeWX (at most once per
WeeWX start, since Python deduplicates warnings):

```
skyfield/almanac.py:339: RuntimeWarning: invalid value encountered in divide
  return - 2*c / (b + sign * sqrt(discriminant))
```

**This is an upstream Skyfield bug, tracked as
[skyfield issue #1114](https://github.com/skyfielders/python-skyfield/issues/1114)**, and
it affects recent Skyfield versions through at least 1.54.  The final refinement step of
Skyfield's rise/set solver (`find_risings`/`find_settings`) fits a parabola through its
last two altitude samples; when the solver's iteration happens to land, to the last
floating-point bit, exactly on the horizon, that fit degenerates to a 0/0 division.  It is
a pure floating-point coincidence: it can strike any body, any latitude and any date, and
the affected dates even differ between operating systems, NumPy versions and CPU math
libraries.  Inside Skyfield, the affected event's time becomes NaN.

**weewx-skyfield already contains the failure**: it discards any event time that is not a
finite time within the day being searched, so the worst possible outcome is a single rise
or set tag coming up empty for a while — and in practice pages render complete: on the
one production occurrence that prompted this page, every rise, set, transit and twilight
value was present.  No configuration change, downgrade or workaround is needed.

weewx-skyfield's author diagnosed the root cause and contributed a proposed one-line
fix — along with a deterministic reproduction — to
[issue #1114](https://github.com/skyfielders/python-skyfield/issues/1114).  The
warning will disappear once a Skyfield release newer
than 1.54 ships a fix; upgrading Skyfield is routine — see
[Upgrading Skyfield](installation.md#upgrading-skyfield).
