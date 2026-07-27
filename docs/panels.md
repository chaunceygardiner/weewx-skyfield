---
title: Using the Sky panels in your own skin
description: Embedding weewx-skyfield's $sky_page panels — sky dome, ribbons, sun path, orrery, analemma, solar year, lunation and more — in any WeeWX skin.
---

# Using the Sky panels in your own skin

[Home](index.md) ·
[Installation](installation.md) ·
[Almanac tags](tags.md) ·
[The Sky page](sky-page.md) ·
[Translating (i18n)](i18n.md) ·
[GitHub project](https://github.com/chaunceygardiner/weewx-skyfield)

---

Every panel on [The Sky page](sky-page.md) is rendered by `$sky_page` — a standard WeeWX
search-list extension, `user.wxskyfield_sky`, installed along with this extension — and can be
dropped into any skin's Cheetah template.  Three things to arrange — four if your skin is
not in English:

1. Add the search list to your skin's `skin.conf` (if the skin already sets
   `search_list_extensions`, append `user.wxskyfield_sky.SkyfieldSky` to that list):

   ```
   [CheetahGenerator]
       search_list_extensions = user.wxskyfield_sky.SkyfieldSky
   ```

2. Have the Skyfield almanac registered — this extension installed, with `enable = true` (the
   default) in the `Skyfield` section of `weewx.conf`.  The panels compute everything from the
   same public `$almanac` tags available to any template; the dome's stars additionally come
   from the registered almanac's star catalog.

3. Bring the CSS along.  The colors of every mark are baked into the markup, but text styling
   and block layout come from CSS classes in the bundled skin's stylesheet,
   `skins/Skyfield/sky.css` — `mono`, `cardinal`, `gridlab` and friends for the SVG labels;
   `count`, the `chip` family and the table rules for the HTML blocks.  Copy the rules you
   need (or the whole file) into your skin's stylesheet.  If you copied individual rules,
   re-check on each upgrade: a release that adds marks to a panel can add a class (1.10
   added `moonlab`, the sun-path moon-time labels), and text with no rule renders at the
   16px SVG default in the wrong color — changes.txt calls out new classes.

4. Non-English skins only: bring the translations along the same way.  The panels read
   `[Texts]` and `[Almanac]` from *your* report, not from the bundled skin, so without this
   step they render in English.  The copy/merge recipe is on the translation page:
   [Copying the dictionary into an embedding skin](i18n.md#copying-the-dictionary-into-an-embedding-skin).

The bundled template, `skins/Skyfield/index.html.tmpl`, shows every panel in use and is the
reference for the wrapper markup mentioned below.  A failing panel never takes down report
generation: the error is logged and that one panel renders blank.  Body evaluations are
memoized, so several panels on one page do not repeat the expensive rise/set searches.

Every render method takes an optional `palette` argument choosing the colors baked into the
markup: `'night'` (the default, used in the screenshots below) or `'light'`, a paper-atlas
plate for light-themed pages: `$sky_page.analemma_svg($almanac, palette='light')`.  As of 1.5
both plates draw the bodies in the traditional astronomy colors — yellow sun, silver moon,
gray Mercury, pearly Venus, blue Earth, red Mars and so on — with pale bodies carrying a thin
ring on the light plate so they hold their edge on paper; the pre-1.5 colors remain available
as `palette='classic-night'` and `'classic-light'`.

## The sky dome — `dome_svg`

```
$sky_page.dome_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_dome.png" width="600" alt="The sky dome panel">

Everything above the horizon right now, in sky-chart orientation — north at the top, east at
the left, as if lying on your back looking up: the sun, the moon drawn at its true phase, the
planets, and the bright IAU-named stars sized by magnitude, with hover coordinates on every
mark.  When the sun is up the stars are shown dimmed, standing where they are behind the
daylight (`sun_is_up`, below, lets a caption react).  `dome_svg` additionally takes
`label_scale` (default 1.0), which grows every label by that factor with the collision layout
following along — useful when a skin displays the chart scaled down, such as a fixed-canvas
smartphone page: `$sky_page.dome_svg($almanac, palette='light', label_scale=2.2)`.

## Rise & set ribbons — `ribbons_svg`

```
$sky_page.ribbons_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_ribbons.png" width="700" alt="Rise and set ribbons panel">

Today's above-horizon span for the sun, moon and planets, over background bands of tonight's
civil, nautical and astronomical twilight (the USNO geometric definitions).  The ivory tick on
each bar is the transit; the vertical brass line is now, and the rise → set times are listed
at the right.

## The sun's path — `sunpath_svg`

```
$sky_page.sunpath_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_sunpath.png" width="340" alt="Sun path panel">

Today's sun, midnight to midnight, as altitude against azimuth — a dot every hour, labels
every third.  The dashed curve is the moon's path, with the moon drawn at its true phase when
above the plot floor; the bands below the horizon line are civil, nautical and astronomical
twilight depth.  Moonrise, moonset and the transit are ticked and labeled on the moon's curve
with times in the skin's format, and the curve's two ends — the moon's positions at 00:00 and
24:00 — get dots labeled 00 and 24 when they clear the plot floor.  The curve is open between
those ends because a lunar day runs about 50 minutes longer than a calendar day, so a day's
track never quite closes; near full moon, when the moon transits around midnight, the break
sits right at the top of its arc (the endpoint dots' tooltips say so).  The azimuth axis is
the fixed full compass, north to north, so the arc's
seasonal swing between the solstices reads at a glance — and a circumpolar arctic sun needs no
special casing.

## The orrery — `orrery_svg`

```
$sky_page.orrery_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_orrery.png" width="340" alt="Orrery panel">

Today's heliocentric longitudes, viewed from above the north ecliptic pole; orbit spacing is
logarithmic so Mercury through Neptune fit one plate.  The dashed ray marks 0° — the direction
of the vernal equinox.

## The analemma — `analemma_svg`

```
$sky_page.analemma_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_analemma.png" width="340" alt="Analemma panel">

The sun's altitude and azimuth at local standard noon for every week of the year — the
figure-eight sum of Earth's tilt and its elliptical orbit — with this week's point marked in
brass.  It evaluates the almanac 53 times (all cheap instantaneous positions).

## The solar year — `daylength_svg`

```
$sky_page.daylength_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_daylength.png" width="700" alt="Solar year panel">

Sunrise, sunset and solar noon (dashed) for every week of the year, over the same
civil/nautical/astronomical twilight bands as the ribbons — with today's brass line.  Times
are local *clock* time, so the daylight-saving steps in spring and fall are real and
deliberate; the dashed solar-noon curve carries the equation of time (and the same DST steps).
Polar day and polar night render correctly as all-day and no-day columns.  This is the page's
most expensive panel — several hundred rise/set searches — but they are anchored to fixed
weekly instants, so the [result cache](tags.md#the-result-cache) reuses them across report
cycles and the full cost is paid only on the first render after startup.

## The moon disc — `moon_svg`

```
$sky_page.moon_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_moon.png" width="170" alt="Moon disc panel">

The moon at its true phase, waxing and waning on the correct limb.  The optional `size`
argument (default 76) sets the SVG's intrinsic pixel size; with the bundled stylesheet's
`svg{width:100%}` rule the disc fills its container, so size the wrapping element.

## The lunar month — `lunation_svg`

```
$sky_page.lunation_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_lunation.png" width="700" alt="Lunar month panel">

The current lunation, previous new moon to next, as a strip of thirty phase discs — the
principal phases ticked and dated, today's disc ringed in brass, and every disc carrying its
date and illumination on hover.  Waxing and waning fall on the correct limb for your
hemisphere, matching the moon disc above.

## Planet chips — `chips_html`

```
<div class="chips">
  $sky_page.chips_html($almanac)
</div>
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_chips.png" width="340" alt="Planet chips panel">

A summary card per body: daylight (length, sun rise → set, civil dusk and astronomical dark),
then each planet with its rise time or current position, the constellation it stands in,
magnitude, distance and elongation — plus Jupiter's central meridian longitudes and Saturn's
ring tilt.  The `chips` wrapper provides the single-column layout.

## Countdown chips — `countdown_html`

```
<div class="countdown">
  $sky_page.countdown_html($almanac)
</div>
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_countdown.png" width="700" alt="Countdown chips panel">

Date and days-to-go chips for the next new moon, full moon, equinox and solstice, plus the
next eclipse visible from the station (lunar or solar, whichever comes first, labeled with its
locally seen type; its date carries the year, since the next visible eclipse can be years
out).  The `countdown` wrapper lays the chips out as a wrapping row.

## The almanac table — `table_html`

```
<div class="tablewrap">
  $sky_page.table_html($almanac)
</div>
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_table.png" width="700" alt="Almanac table panel">

Rise, transit, set, time up, current altitude and azimuth, magnitude and distance for the sun,
moon and planets.  The `tablewrap` wrapper lets the table scroll sideways on narrow screens
instead of breaking the page.

## Helpers — `header_sub` and `sun_is_up`

`$sky_page.header_sub($almanac)` returns The Sky page's one-line subtitle — station
coordinates and the almanac time, e.g. `37.44° N · 122.14° W · Saturday, June 21 2025,
23:00 PDT`.  `$sky_page.sun_is_up($almanac)` returns a plain boolean for template logic; the
bundled page uses it to switch the dome's caption between day and night wording:

```
#if $sky_page.sun_is_up($almanac)
The sun is up, so the plate shows the stars where they stand behind the daylight.
#else
Dot size follows magnitude; the brighter the star, the larger the mark.
#end if
```
