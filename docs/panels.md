---
title: Panels in your own skin
layout: default
parent: The Sky page
nav_order: 1
description: Embedding weewx-skyfield's $sky_page panels — sky dome, ribbons, sun path, orrery, analemma, solar year, lunation and more — in any WeeWX skin.
---

# Using the Sky panels in your own skin

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

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
   added `moonlab`, the sun-path moon-time labels; 2.0 added `satlab`, the satellite name
   label, and the pass chart's `passhead`/`passname`/`passwhen` head-line rules), and text
   with no rule renders at the
   16px SVG default in the wrong color — changes.txt calls out new classes.

   The panels' tooltips are native SVG `<title>` elements, so they work on hover with no
   help — but hover does not exist on a touch screen.  The bundled skin ships
   `skins/Skyfield/sky.js`, a small dependency-free script that shows the same tooltip text
   on tap; copy it (and the `.skytip` rule from `sky.css`) and load it with
   `<script src="sky.js" defer></script>` if your page's visitors use tablets or phones.

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

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_dome_comet.png" width="600" alt="The sky dome with a comet plotted as a tailed diamond">

*The same panel with a comet risen: a labeled diamond with its tail streaming anti-sunward,
hollow because this one is fainter than naked-eye.*

Everything above the horizon right now, in sky-chart orientation — north at the top, east at
the left, as if lying on your back looking up: the sun, the moon drawn at its true phase, the
planets, and the stars sized by magnitude, with hover coordinates on every
mark.  When the sun is up the stars are shown dimmed, standing where they are behind the
daylight (`sun_is_up`, below, lets a caption react).  `dome_svg` additionally takes
`label_scale` (default 1.0), which grows every label by that factor with the collision layout
following along — useful when a skin displays the chart scaled down, such as a fixed-canvas
smartphone page: `$sky_page.dome_svg($almanac, palette='light', label_scale=2.2)`.

The dome plots *every* star of the bundled Hipparcos catalog down to the magnitude limit — a
true sky map.  Labels stay on named stars; an unnamed star's hover tooltip gives its
Hipparcos number.  The dome also draws the 88 constellations' stick figures, each
substantially-risen figure labeled with the constellation's (translated) name, setting
figures clipped at the horizon rim — and, with satellites configured, a position dot for any
satellite above the horizon at generation time.  A sunlit satellite is a solid dot; one
inside Earth's shadow is drawn as a hollow ring — present but not shining — with its
tooltip saying "in shadow".  A configured [comet](tags.md#comets) above the horizon plots
as a labeled diamond with a small anti-sunward tail (comet tails point away from the sun;
the rays carry `class="comet-tail"`), always (the config list is the filter): solid brass
when its magnitude says plausibly naked-eye (6.0 or brighter), the hollow ring when
fainter — there, but not visible to the eye — with the magnitude in the tooltip.  And
while a [meteor shower](tags.md#meteor-showers) is active, its radiant gets a small rayed
mark when above the horizon — meteors stream outward from that point — labeled (yielding
when space is tight: a radiant is an area of sky, not a body), with ZHR and peak date in
the tooltip.  The dome is
strictly the *current* sky, one
chart, one instant: an upcoming [visible pass](tags.md#satellites) is charted by
[`pass_chart_html`](#the-next-visible-pass-chart--pass_chart_html) below, at the pass's own epoch.
The `star_mag_limit` and `star_label_mag` options set the star cutoffs and
`constellation_lines = false` turns the figures off — see
[Configuration](configuration.md#the-sky-pages-report-stanza); when embedding the panels in your
own skin, set them in that skin's report section the same way.

An embedding skin that repositions dome marks between report cycles — weewx-celestial's live
dome is the consumer — locates them by machine name, never by tooltip text (which is
translated): the sun's, moon's and each planet's marks are wrapped in
`<g class="dome-body" data-body="mars">`, their name labels carry the same `data-body`
attribute, and a satellite's position dot gets its tag name the same way plus
`data-sunlit="1"` or `"0"`, so a live layer can flip the dot between solid and hollow as
the satellite crosses the shadow line.  A comet's diamond carries `data-bright="1"` or
`"0"` the same way.  These hooks are a
stable contract, and so are `$sky_page.satellite_names()` and `$sky_page.comet_names()`,
through which an embedding skin enumerates the configured satellites and comets — the tag
names in config order, empty when none are configured or the almanac is not registered.

## The next visible pass chart — `pass_chart_html`

```
$sky_page.pass_chart_html($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_passchart.png" width="440" alt="The next visible pass chart panel">

The whole sky as it will stand at the culmination of the soonest upcoming
[visible pass](tags.md#satellites) among the configured satellites, with the pass drawn
across it as a dashed arc — rise and set times at the endpoints, the satellite's own dot at
the peak — under a dated head line naming the satellite and the pass ("ISS · Sun Jun 22 ·
03:11 → 03:21 · peak 19°").  The peak dot can be the hollow in-shadow ring: a pass is
visible when *any* of it is sunlit in a dark sky, and a morning pass often exits Earth's
shadow just after culminating — the chart honestly shows it flaring into view mid-sky.  One chart, one epoch: the arc crosses the stars it will
actually cross, the per-pass convention sky-charting has always used for future events (the
sky dome, by contrast, never shows anything but the current sky).  The star field uses
twilight-honest cutoffs — a visible pass happens while the sky is only half dark, so only
stars bright enough to actually show then are plotted (magnitude 3.5, labels at 1.5) —
making it a finder chart rather than a census.

The method returns a `passhead` div followed by the chart SVG, and an **empty string** when
no configured satellite has a visible pass in its elements' validity window (up to a week
out) — wrap it in a guard as the bundled template does:

```
#set $passchart = $sky_page.pass_chart_html($almanac, palette=$palette)
#if $passchart
  ...
#end if
```

Like `dome_svg` it takes `palette` and `label_scale`.  Its SVG ids (`skygp`, `domecp`) stay
distinct from the dome's, so both charts share a page cleanly, and the `data-body` /
`dome-track` hooks appear here exactly as on the dome — the pass arc's group,
`<g class="dome-track" data-body="iss">`, lives on this chart.  New CSS classes: `passhead`,
`passname` and `passwhen` style the head line (see `sky.css`); the arc and its labels reuse
the dome's `satlab`/`nowlab` rules.

## Rise & set ribbons — `ribbons_svg`

```
$sky_page.ribbons_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_ribbons.png" width="700" alt="Rise and set ribbons panel">

Today's above-horizon span for the sun, moon and planets — and every configured
[comet](tags.md#comets) with elements (2.1), as a brass bar — over background bands of tonight's
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
of the vernal equinox.  A configured [comet](tags.md#comets) joins the plate as a diamond at
its *current* sun distance on the same log scale — marker only, no orbit ring, since an
eccentric orbit does not draw as a circle — its tail streaming radially outward (a comet's
tail points away from the sun, and on a sun-centered plan view that is simply outward),
with the true distance in the tooltip and the dome's solid/hollow naked-eye rule; a comet
beyond the outermost ring pins near the rim.
Unlike the dome, the orrery plots a comet whether or not it is above the observer's
horizon: it is a plan view of the solar system, not the observer's sky.

## The equation of time — `eot_svg`

```
$sky_page.eot_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_eot.png" width="440" alt="Equation of time panel">

The equation of time across the year (2.1) — sundial minus clock, per the USNO sign —
sampled at the analemma's own instants, local standard noon each week.  The double-humped
curve is the sum of Earth's tilt and its elliptical orbit, the same pair that draws the
analemma's figure-eight; the brass point is today, labeled with today's standard-noon
value — its own evaluation, not the nearest weekly sample.  The frame is
fixed at ±18 minutes, so the plate looks the same every year.  The bundled page places it in
the left column beside the Solar Year chart, its year-scale sibling.

## The analemma — `analemma_svg`

```
$sky_page.analemma_svg($almanac)
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_analemma.png" width="340" alt="Analemma panel">

The sun's altitude and azimuth at local standard noon for every week of the year — the
figure-eight sum of Earth's tilt and its elliptical orbit — with today's point marked in
brass at its own standard-noon spot on the locus.  It evaluates the almanac 54 times (all
cheap instantaneous positions).

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
weekly instants, so the [result cache](performance.md#the-result-cache) reuses them across report
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

The bundled page follows the strip with `$sky_page.moon_apsides_html($almanac)` (2.1):
the quiet next-perigee/next-apogee line, topped by a brass **supermoon** callout whenever the
next full moon falls within a day of perigee.  Like the satellite pass cards, the callout is
anticipation — it appears ahead of the event and leaves with it.  The styling rides the
`.supermoon` and `.apsis` classes in `sky.css`, and the strings are translated in all nine
bundled languages.

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
ring tilt.  Every configured [comet](tags.md#comets) with elements gets a
brass-dotted chip (2.1) of the same shape (its magnitude a dash when the MPC row has no
parameters), and the bundled page's eyebrow reads "Sun, Planets & Comets" when any comet is
configured.  The `chips` wrapper provides the single-column layout.

## The satellites panel — `satellites_html`

```
#if $sky_page.has_satellites()
<div class="chips">
  $sky_page.satellites_html($almanac)
</div>
#end if
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_satellites.png" width="340" alt="Satellites panel">

One card per configured satellite (see [Satellites](installation.md#satellites)): its
[next visible pass](tags.md#satellites) — the date and countdown in the countdown-chip
idiom, rolling into "overhead now" during the pass itself, then "appears WSW · peaks 45° SSW
· disappears NE · 6 min".  The rows are honest about nothing-to-see: a satellite with no
visible pass in the coming week says so, and one with no usable orbital elements says
*that*, pointing at the weewxd log — the panel never shows a stale pass.
`$sky_page.has_satellites()` returns whether any satellites are configured, so a template
can skip the whole section when there are none — the bundled page does exactly that.

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
out).  A configured [comet](tags.md#comets)'s perihelion joins the row (2.1) when it
lies ahead within a year — the news-cycle countdown; Halley's 2061 date stays quiet until
its time comes — and the next major [meteor shower](tags.md#meteor-showers) is always
there, its detail line carrying the moon's peak-night illumination as the interference
judgment: a bright moon washes out the faint meteors, and the chip says so.  The days-to-go
line counts local calendar days, so it always agrees with the date above it: an event later
today reads "today", and one just after midnight reads "in 1 day".  The
`countdown` wrapper lays the chips out as a wrapping row.

## The almanac table — `table_html`

```
<div class="tablewrap">
  $sky_page.table_html($almanac)
</div>
```

<img src="https://raw.githubusercontent.com/chaunceygardiner/weewx-skyfield/main/screenshots/panel_table.png" width="700" alt="Almanac table panel">

Rise, transit, set, time up, current altitude and azimuth, magnitude and distance for the sun,
moon and planets — and every configured [comet](tags.md#comets) with elements (2.1),
brass-dotted, its magnitude a dash when the MPC row carries no parameters.  The `tablewrap`
wrapper lets the table scroll sideways on narrow screens instead of breaking the page.

## The footer credit — `footer_html`

```
$sky_page.footer_html()
```

The credit line the bundled page carries, and the one panel you should copy if you embed any
of the others: it names the libraries and data sources that actually produced the page —
Skyfield, JPL's DE421, the IAU-CSN star names, the Hipparcos catalog, the Stellarium sky
culture, CelesTrak for satellite elements, the Minor Planet Center for comet elements, and
the IMO for the meteor shower data — and the ESA acknowledgment is
[required](index.md#licensing) exactly when Hipparcos data is shown, which this line handles
for you.

Most of those are conditional on what the page actually drew: the star credits appear only
with a live catalog, Stellarium only when the figures are on *and* the lines file loaded,
CelesTrak only with satellites configured, the Minor Planet Center only with comets.  The
IMO credit is unconditional, because the shower list is built in and the countdown row always
carries the next shower.  Nothing is credited for data the page did not use.

It is also a diagnostic.  The full credit appears only when the registered Skyfield almanac
and its star catalog are live; if the almanac is not registered, or the star catalog failed to
load, the footer says *that* instead and points at the weewxd log.  A page rendering off the
built-in almanac's fall-through therefore admits it in print rather than looking correct.

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
