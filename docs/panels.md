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

3. Bring the CSS along.  Text styling and block layout come from CSS classes in the bundled
   skin's stylesheet,
   `skins/Skyfield/sky.css` — `mono`, `cardinal`, `gridlab` and friends for the SVG labels;
   `count`, the `chip` family and the table rules for the HTML blocks.  Copy the rules you
   need (or the whole file) into your skin's stylesheet.  If you copied individual rules,
   re-check on each upgrade: a release that adds marks to a panel can add a class (1.10
   added `moonlab`, the sun-path moon-time labels; 2.0 added `satlab`, the satellite name
   label, and the pass chart's `passhead`/`passname`/`passwhen` head-line rules), and text
   with no rule renders at the
   16px SVG default in the wrong color — changes.txt calls out new classes.
   2.4 added two: `bandlab`, for the labels that sit on the twilight bands rather than on
   the panel, and a `.dot` rule that paints the chip and table swatches from the custom
   property the markup now carries — without that one the swatches have no color at all.
   2.2 added one more, `skylab`, the sky charts' 30°/60° ring-degree labels.

   Those labels carry `class="mono gridlab skylab"`: `skylab` is the hook for text drawn on
   the dome gradient rather than on the panel.  The bundled stylesheet gives it the same
   color as `gridlab`, since every text color there clears its contrast bars on both
   surfaces, so a skin without a `skylab` rule loses nothing.  If you add one to style dome
   text apart, two things matter: `skylab` and `gridlab` are equal specificity and both
   match the element, so the `skylab` rule must come *after* your `gridlab` rule; and if
   your `gridlab` rule is scoped (`.night .gridlab`), scope `skylab` the same way or it
   will lose.  Whatever color you give it must still read against the lighter rim of the
   dome, not just the panel.

   The panels' tooltips are native SVG `<title>` elements, so they work on hover with no
   help — but hover does not exist on a touch screen.  The bundled skin ships
   `skins/Skyfield/sky.js`, a small dependency-free script that shows the same tooltip text
   on tap; copy it (and the `.skytip` rule from `sky.css`) and load it with
   `<script src="sky.js" defer></script>` if your page's visitors use tablets or phones.

4. Non-English skins only: bring the translations along the same way.  The panels read
   `[Texts]` and `[Almanac]` from *your* report, not from the bundled skin, so without this
   step they render in English.  The copy/merge recipe is on the translation page:
   [Copying the dictionary into an embedding skin](i18n.md#copying-the-dictionary-into-an-embedding-skin).
   The `[Almanac]` half — body, constellation and meteor shower names — needs WeeWX 5.3 or
   later; on 5.2 those stay English and Latin while everything in `[Texts]` still translates.

The bundled template, `skins/Skyfield/index.html.tmpl`, shows every panel in use and is the
reference for the wrapper markup mentioned below.  A panel that fails while computing never
takes down report generation: the error is logged and that one panel renders blank.  A mistake
in the call itself — an unknown palette, or a `label_scale` or `label_layers` value that is not
usable — is different: it raises a template error, so it shows up while you are writing the
template rather than shipping as a quietly empty panel (see
[Troubleshooting](troubleshooting.md#a-page-stopped-updating-after-i-changed-a-sky_page-call)).
Body evaluations are memoized, so several panels on one page do not repeat the expensive
rise/set searches.

Every render method takes an optional `palette` argument choosing the panel's colors:
`'night'` (the default, used in the screenshots below) or `'light'`, a paper-atlas
plate for light-themed pages: `$sky_page.analemma_svg($almanac, palette='light')`.  Since 2.4
those colors arrive as overridable defaults rather than as values written onto each mark —
see [the role classes](#restyling-the-marks--the-role-classes).  As of 1.5
both plates draw the bodies in the traditional astronomy colors — yellow sun, silver moon,
gray Mercury, pearly Venus, blue Earth, red Mars and so on — with pale bodies carrying a thin
ring on the light plate so they hold their edge on paper.  Where those same colors are drawn
over the twilight bands rather than over a panel — the Ribbons bars, their transit ticks and
the "now" line — the plate adds a casing beneath the mark, an outline on it, or both, since a
body's color is chosen to say which body it is and no single value can also hold up against
every twilight depth (2.3).

`'classic-night'` and `'classic-light'` named the pre-1.5 body colors.  **They were dropped in
2.3** and now draw as `'night'` and `'light'`; the names still work, and a call that uses one
logs a warning naming its replacement.  They lasted a very short time before 1.5 shipped, and
keeping two frozen color schemes meant arguing every contrast fix twice — the second time on a
plate whose whole premise was that its colors could not move.

## Restyling the marks — the role classes

As of 2.4 every graphical mark in an SVG panel carries a class naming its **role**, and the
panel carries the requested plate's values for the roles it actually used as CSS rules of
*zero specificity*.  A skin that does nothing renders exactly as it did before.  A skin that
writes one rule repaints that role wherever it appears — which is what a per-viewer light/dark
switch needs, since the SVG is written once per report cycle and the reader may flip themes
hours later.

Class names are `sky-<channel>-<role>`, where the channel is `fill` or `stroke`.  The channel
is part of the name because several roles are a fill on one mark and a stroke on another —
one class per role would paint the inside of a stroked curve.

| Class | The mark it paints |
|---|---|
| `sky-fill-ink`, `sky-stroke-ink` | star dots, plotted curves, transit ticks |
| `sky-fill-muted`, `sky-stroke-muted` | secondary chrome — the analemma's weekly dots, the orrery's reference line |
| `sky-fill-brass`, `sky-stroke-brass` | accents and now-markers: today's point, the pass arc, satellite and comet marks, meteor radiants |
| `sky-fill-line`, `sky-stroke-line` | gridlines and orbit circles drawn on the **panel** surface |
| `sky-fill-grid`, `sky-stroke-grid` | the sky charts' altitude rings and the cross through the zenith, which read against the dome gradient instead |
| `sky-fill-bandgrid`, `sky-stroke-bandgrid` | gridlines on the three panels that plot over twilight **bands** |
| `sky-fill-bandcase`, `sky-stroke-bandcase` | the casing under those gridlines, under the data marks that cross the same bands, and under the labels drawn on them.  The night plate's is its night band's color, which covers the sun's arc beneath the sun path's hour numbers; the light plate's is white.  The element is always there, so a reader who flips themes gets the other plate's casing |
| `sky-fill-bandedge`, `sky-stroke-bandedge` | the outline separating a body's identity color from the band under it |
| `sky-fill-halo`, `sky-stroke-halo` | the stroke lifting body dots off the plate; also the interior of a hollow (shadowed satellite, faint comet) marker |
| `sky-fill-conline`, `sky-stroke-conline` | the constellation figures |
| `sky-fill-tw-night`, `-astro`, `-naut`, `-civil`, `-day` | the five twilight bands |
| `sky-fill-body-<name>` | a body's identity color |
| `sky-stroke-body-<name>` | the same color as a line — the sun's rays |
| `sky-stroke-ring-<name>` | a body dot's edge: the plate's per-body ring where it has one, else the plate's halo |
| `sky-stroke-trace-<name>`, `sky-fill-trace-<name>` | a body's plotted track and the dots that terminate it: the ring where the plate has one, else the body's own color (a line cannot wear a halo) |
| `sky-stroke-rim-<name>` | the pale-body lift on the light plate: the ring where the plate has one, else `none` |
| `sky-fill-moon-dark`, `sky-fill-moon-lit`, `sky-stroke-moon-ring` | the moon disc |
| `sky-stroke-dome-rim` | the dome's horizon rim |
| `sky-dome-stop-1`, `-2`, `-3` | the dome gradient's three stops (`stop-color`) |
| `sky-fill-orrery-sun` | the orrery's sun |
| `sky-fill-earth`, `sky-stroke-earth` | the orrery's Earth |

`<name>` is one of the nine bodies these panels draw: `sun`, `moon`, `mercury`, `venus`,
`mars`, `jupiter`, `saturn`, `uranus`, `neptune`.  A skin that shows more than that — Pluto,
say — is drawing its own marks and styles them from its own tokens; there is no
`sky-fill-body-pluto`.

### If your skin reads the markup

The pages render identically, but the markup they render from has changed: what was
`fill="#D3A94C"` on a mark is now `class="sky-fill-brass"`, a mark that already carried a
class carries the role class alongside it (`class="comet-tail sky-stroke-brass"`), and the
charts' gradient and clipPath ids now end in the plate name (`skyg-night`).

Two places that can bite, and the second one bites silently:

- **Your tests.**  A suite that asserts on those attributes or ids needs its assertions
  loosened.  Grep your **whole tree**, not just the code you ship — a consumer's tests are
  precisely where its picture of this markup is written down, and that is where these pins
  turn out to live.
- **Live JavaScript that reads a mark's drawn paint.**  Reading `el.getAttribute('fill')` to
  learn what color the station drew a mark in — a reasonable thing to do, and the way to
  avoid hard-coding a palette — now returns `null`, with no error and no visible symptom
  beyond the thing quietly not happening.  This is not hypothetical: it is how
  weewx-celestial's live dome derived a satellite's sunlit and in-shadow looks, and at 2.4
  the dot simply stopped flipping.

  Two replacements, both palette-agnostic.  `getComputedStyle(el).fill` gives the resolved
  color whether it came from an attribute or a class.  Or read the **class pair** on a mark
  that has two states — a satellite marker (`data-sunlit`) or a comet's (`data-bright`).
  Those are drawn as one pair of roles exchanged: `class="sky-fill-brass sky-stroke-halo"`
  when lit, `class="sky-fill-halo sky-stroke-brass"` when not, so exchanging the two suffixes
  inverts the mark without naming a color — the class form of swapping the `fill` and
  `stroke` attributes 2.3.x wrote.

  Each panel's `<style>` defines **both channels of every role it uses**, precisely so that
  swap always lands on a rule.  Without that guarantee it would depend on what the chart
  happened to draw: a pass chart's satellite is sunlit at culmination — that is what makes
  the pass visible — so nothing on that chart ever fills with halo, the swapped mark would
  ask for `.sky-fill-halo`, find no rule, and fall back to the SVG initial.  Black, for a
  fill: a solid black disc where a hollow white ring belongs, with nothing logged.  The
  guarantee holds for role pairs, not for any two classes on a mark — a planet dot's fill and
  stroke are *different* roles (`body` and `ring`), and exchanging those means nothing.

As of 2.5 the sky charts' labels no longer sit beside their marks.  Every label — the
cardinals, the 30° and 60° ring figures, a pass's rise and set times, and the body, star and
constellation names — is written inside `<g class="dome-labels" data-label-scale="1">` at the
end of the SVG, one group per [label layer](#the-sky-dome--dome_svg), and the `<svg>` root
carries `data-label-layers` (plus `data-label-media` when there is an extra layer).  Positions
and sizes are unchanged, but the ring figures now draw above the stars, and a test that expects
a label next to its mark, or exactly one element per `data-body`, needs loosening.

The consumer hooks are the durable thing to match on: `data-body`, `data-sunlit`,
`data-bright`, `data-rise`/`data-set`, the `dome-body`/`dome-track` classes, and (2.5 and
later) the `dome-labels` groups with their `data-label-scale`.

### How the defaults are scoped

Each `<svg>` carries `class="sky sky-night"` or `class="sky sky-light"`, and its defaults are
written against it:

```css
:where(svg.sky-night) :where(.sky-fill-ink) { fill: #E9E4D4 }
```

Both halves are wrapped in `:where()`, which contributes no specificity, so **any rule naming
one class beats the default** wherever that rule sits:

```css
.theme-light .sky-fill-ink { fill: #1d2c4e }   /* wins */
.sky-fill-ink              { fill: #1d2c4e }   /* also wins */
```

One honest edge: a rule that *also* scores zero — a bare `:where(.sky-fill-ink)` — ties with
the default, and a tie is broken by document order.  The defaults ride inside the SVG, in the
body, so a zero-specificity rule in your `<head>` loses.  Name a class and the question does
not arise.

The plate class is what makes the defaults local to the panel that carries them.  A `<style>`
inside inline SVG is **not** scoped to that SVG in an HTML document — it applies document-wide
— so without it, two panels of different plates on one page would repaint each other, and the
last one in the document would win for both.  That case is real: a night dome beside light
panels is exactly what a skin reconciling a fixed-plate chart with a themed page ends up with.

### The HTML swatches

The `.dot` swatches in the HTML blocks — `chips_html`, `satellites_html` and `table_html` —
are HTML rather than SVG, so they cannot bring a `<style>` element with them and their color
has to ride inline.  It rides as **custom properties**, never as `background` itself:

```html
<div class="chip" data-body="mars"><span class="dot" style="--sky-dot:#b23a24"></span>…
<tr data-body="venus"><td class="tname"><span class="dot"
    style="--sky-dot:#F0E4BE;--sky-dot-ring:#97864A"></span>…
```

(Both from the light plate, which is the one that gives pale bodies a ring.  The night
plate declares none, so it sets no `--sky-dot-ring` at all and the shadow falls back to
transparent.)

That distinction is the whole of it.  An inline `background` would outrank every rule a
consuming skin could write short of `!important`; setting only the variables leaves
`background` free, and `sky.css`'s `.dot` rule reads them:

```css
.dot{background:var(--sky-dot); box-shadow:inset 0 0 0 1.5px var(--sky-dot-ring, transparent)}
```

**If you copy rules piecemeal rather than the whole file, you need that one** — without it the
swatches lose their color.  (`--sky-dot-ring` is set only for the pale bodies the light plate
gives a ring; the fallback keeps the shadow invisible otherwise.)

Every chip is a `<div class="chip" data-body="…">` and every table body row a
`<tr data-body="…">`, carrying the same tag name the dome's marks use — so a theme rule aims
at the body, not at translated text:

```css
.theme-light [data-body="mars"] .dot { background: #b23a24 }
```

`data-body` on these rows is new in 2.4; the satellite and comet rows carry their configured
tag name, exactly as the dome's markers do.

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
smartphone page: `$sky_page.dome_svg($almanac, palette='light', label_scale=2.2)`.  It must
be a positive number — numeric text such as `'0.8'` is accepted — and anything else raises a
template error naming the argument (2.5 and later; before 2.5 a zero rendered 0px labels and
text blanked the panel).

A page that serves more than one layout from a single URL — a desktop layout and, below some
width, a phone layout — asks for both label sizes at once with `label_layers` (2.5 and later), a
list of `(scale, media_query)` pairs:

```
$sky_page.dome_svg($almanac, label_scale=0.8, label_layers=[(2.2, '(max-width: 600px)')])
```

The marks are drawn once.  The labels are laid out once per scale, each layout in its own
`<g class="dome-labels" data-label-scale="…">` (the base layer is wrapped the same way, always,
layers or not), and the chart's own `<style>` shows the layer whose media query the reader's
viewport matches and hides the rest — nothing is fetched and nothing scripted.  The rules are
scoped to the chart's plate, its scales and its queries (`data-label-layers="0.8 2.2"` and a
`data-label-media` key on the `<svg>` root), so any mix of charts shares a page without one
chart's rules reaching another's labels; within one chart, give two extra layers queries that
cannot both match.  A query may contain only letters, digits, spaces and `: ( ) , . -`, with
its parentheses balanced — it is written inside inline SVG, where `<` and `&` are markup — so
`(max-width: 600px)` and `screen and (orientation: portrait)` are fine and the range syntax
`(width < 600px)` is refused.  A bad query, scale or pair raises a template error at render
time rather than blanking the panel.  A live page that moves a mark's label by
its `data-body` must move *every* layer's copy (`querySelectorAll`, not `querySelector`).

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
attribute (one copy per label layer, all of them inside `<g class="dome-labels">` groups —
move every copy), and a satellite's position dot gets its tag name the same way plus
`data-sunlit="1"` or `"0"`, so a live layer can flip the dot between solid and hollow as
the satellite crosses the shadow line.  A comet's diamond carries `data-bright="1"` or
`"0"` the same way.  On the pass chart the arc's own group,
`<g class="dome-track" data-body="iss">`, states the pass's rise and set as epoch seconds
(`data-rise`/`data-set`, 2.3.2 and later), so a live layer can tell whether the pass this
chart depicts is ahead, in progress or over without consulting a feed whose *next* pass
has already rolled on.  These hooks are a
stable contract, and so are `$sky_page.satellite_names()` and `$sky_page.comet_names()`,
through which an embedding skin enumerates the configured satellites and comets — the tag
names in config order, empty when none are configured or the almanac is not registered —
and `$sky_page.can_draw()` (2.3.4 and later), True when the Skyfield almanac is registered
and the page can draw the sky, False on a lesser tier.
It is the same test the dome stands on, without drawing anything, so a page that places
only a satellite roster or the pass chart beside someone else's dome can gate those panels
without rendering a dome to learn whether it could.

Five panels need this extension's almanac and return the empty string without it —
`dome_svg`, `pass_chart_html`, `satellites_html`, `eot_svg` and `moon_apsides_html`, the set
`can_draw()` reports on.  The rest need only an almanac that serves body positions and rise
times, so they draw wherever WeeWX has one.  Either way a panel that cannot get what it
needs comes back empty instead of raising, and weewxd's log says so once — see
[Some `$sky_page` panels are empty](troubleshooting.md#some-sky_page-panels-are-empty).
The answer is to install the almanac; gate panels on `can_draw()` if you would rather your
page reserve no space for them.

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

Like `dome_svg` it takes `palette`, `label_scale` and `label_layers` (the head line is HTML
outside the SVG, sized by the page's own CSS, and takes no part in the layers).  Its SVG ids
(`skygp-night`, `domecp-night`, ending in the plate name like the dome's) stay distinct from
the dome's, so both charts share a page cleanly, and the `data-body` /
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
civil, nautical and astronomical twilight (the USNO geometric definitions).  The tick across
each bar is the transit; the vertical brass line is now, and the rise → set times are listed
at the right.  Bars, ticks and the "now" line are drawn over those bands rather than over the
panel, so on each plate they carry whatever casing or outline it takes to stay readable there
(2.3) — nothing for a skin to configure.

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

The bundled page labels the disc with `$sky_page.moonset_html($almanac)`, a one-line
`<div>` giving tonight's moonset in the report's own time format, and nothing at all where
the almanac has no moonset to give.

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
line counts local calendar days, so it always agrees with the date above it: an event just
after midnight reads "in 1 day", and one later today reads "today at 21:14" — on the day
itself the clock time is the one thing the chip is not already showing.  The
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

## Helpers — `theme`, `palette`, `header_sub` and `sun_is_up`

`$sky_page.theme($almanac)` and `$sky_page.palette($almanac)` are how an embedding skin
offers the two plates without reimplementing anything.  Both read the option from **your**
report's stanza, not from the bundled skin's, so adding `theme = dark | light | auto` to your
own `[[YourReport]]` section is the only step:

```
#set $theme   = $sky_page.theme($almanac)      ## 'dark' or 'light'
#set $palette = $sky_page.palette($almanac)    ## 'night' or 'light'
<html lang="$lang" class="theme-$theme">
```

`theme()` resolves `auto` itself — light while the sun is up at generation time — so you
inherit that logic rather than writing it; `palette()` returns the matching palette name to
hand to every panel call.  Resolve the pair **once** per page and reuse it: each panel call
is individually guarded, so resolving inside each one would let a typo'd theme value cost
every chart while the rest of the page rendered.  The palette a panel is rendered with is
still a generation-time choice — but since 2.4 it is only the *default*: the marks carry role
classes, so a browser toggle can repaint them (see
[the role classes](#restyling-the-marks--the-role-classes)).

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
