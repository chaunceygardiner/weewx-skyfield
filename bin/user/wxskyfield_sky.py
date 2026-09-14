"""
wxskyfield_sky.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

Search-list extension for the bundled Skyfield skin: renders the "Sky" page's
SVG panels (sky dome, rise/set ribbons, sun path, day length, lunation strip,
orrery, analemma, moon disc) and HTML blocks server-side, from the same
$almanac binder tags any template could use.  The page is self-contained -- inline SVG, system fonts, no
JavaScript libraries and nothing fetched at run time.
"""

import datetime
import functools
import hashlib
import logging
import math
import re
import time

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import weewx.almanac

from weewx.cheetahgenerator import SearchList

log = logging.getLogger(__name__)

# ── palettes ─────────────────────────────────────────────────────────────────
# Every render method takes palette= naming an entry here.  'night' is the
# bundled Sky page's plate (see skins/Skyfield/sky.css); 'light' is the
# "paper atlas" plate for light-themed consuming skins.  As of 2.4 these
# values do not reach the markup as attributes: each SVG carries them as
# CSS defaults of zero specificity, keyed by the role classes its marks
# wear, so a consuming skin can repaint any of them (see _sky_classes and
# _style_block).  The HTML blocks' swatches, which cannot carry a <style>,
# pass their value inline as the custom property --sky-dot instead.
# Typography was always class-based and is styled by the consuming skin's
# CSS.  Keys: ink (star dots, curves, transit ticks),
# muted, brass (accents, now-markers), line (gridlines and orbit circles on
# the PANEL surface), grid (the sky charts' altitude rings and the cross
# through the zenith -- the meridian and the prime vertical -- which read
# against the dome gradient instead and so cannot share line's value; see
# 2.2.  The HORIZON is the rim, drawn in dome_rim, not either of those
# lines), bandgrid (the gridlines of the
# three panels that plot over twilight BANDS -- ribbons, sun path, day
# length -- a third surface again, and the third value), bandcase (the
# casing under those gridlines and under the DATA marks that cross the
# same bands, None where the plate does not need one -- see _band_rule and
# _band_bar), bandedge (the outline that separates a body's own identity
# color from the band under it, since an identity color is chosen for what
# the body IS and cannot also be chosen for contrast -- see _band_bar),
# halo (the stroke lifting body dots off the plate), body
# (identity colors, colorblind-validated against the plate surface), ring
# (per-body override of the halo for bodies too pale to hold an edge on the
# plate; pale ribbon bars also take it as a 1px stroke), twilight (mid-tone
# enough that identity-colored ribbon bars stay readable on every band), the
# moon-disc fills/ring, the dome gradient stops and rim, and the orrery's
# sun and Earth.
#
# As of 1.5 the body colors follow the traditional astronomy scheme: yellow
# sun, silver moon, gray Mercury, pearly Venus, blue Earth (Mars, Jupiter,
# Saturn, Uranus and Neptune were traditional already).  Two values bend
# tradition for legibility, the same compromise printed atlases make:
# Mercury keeps the gray FAMILY at two weights (dark on paper, light on
# navy), and Neptune stays a readable mid-blue on the night plate.
#
# 2.2 audited every mark against the surface it actually sits on and moved
# what fell short: `grid` on both plates, and night Mars, the one body dot
# under 3:1 on its own dome (2.34, now 3.02).  2.3 did the same for the
# marks that cross the twilight BANDS -- see _band_bar.
PALETTES: Dict[str, Dict[str, Any]] = {
    'night': {
        'ink': '#E9E4D4', 'muted': '#C0C5D9', 'brass': '#E0C27F',
        'line': '#2A3358', 'grid': '#6E7DBA', 'bandgrid': '#6E7DBA',
        'bandcase': '#0B1129', 'bandedge': '#8B93B8', 'halo': '#0A0F22',
        'body': {'sun': '#FFD75E', 'moon': '#C9D0DA', 'mercury': '#9CA0AC',
                 'venus': '#F0E3BE', 'mars': '#D06C56', 'jupiter': '#D89A56',
                 'saturn': '#AC8F3E', 'uranus': '#35A8BE', 'neptune': '#5F85E6'},
        'ring': {},
        'twilight': {'night': '#0B1129', 'astro': '#131B38', 'naut': '#1A2547',
                     'civil': '#233153', 'day': '#2E3D5C'},
        'moon_dark': '#1E2745', 'moon_lit': '#DDD8C4', 'moon_ring': '#2A3358',
        'dome_stops': (('0%', '#161F3D'), ('72%', '#1B2749'), ('100%', '#2A3A63')),
        'dome_rim': '#E0C27F',
        'conline': '#6C82C4',
        'orrery_sun': '#FFD75E',
        'earth_fill': '#4FA3E3', 'earth_stroke': '#E9E4D4',
    },
    'light': {
        'ink': '#1d2c4e', 'muted': '#5c6672', 'brass': '#A44A08',
        'line': '#c9cfd8', 'grid': '#7A899F', 'bandgrid': '#1d2c4e',
        'bandcase': '#ffffff', 'bandedge': '#1d2c4e', 'halo': '#ffffff',
        'body': {'sun': '#FACC15', 'moon': '#D6DAE0', 'mercury': '#52525B',
                 'venus': '#F0E4BE', 'mars': '#b23a24', 'jupiter': '#b06f2e',
                 'saturn': '#8f7524', 'uranus': '#20808f', 'neptune': '#3a63c4'},
        'ring': {'sun': '#BC7800', 'moon': '#767E8A', 'venus': '#97864A'},
        'twilight': {'night': '#3A5175', 'astro': '#4A648C', 'naut': '#6C8FBF',
                     'civil': '#9FBCDE', 'day': '#D7E6F5'},
        'moon_dark': '#26314F', 'moon_lit': '#F2ECD8', 'moon_ring': '#868686',
        # Three stops, like the night plate's: a stop's OFFSET is an
        # attribute and not a CSS property, so it cannot follow a reader's
        # theme switch -- two plates with different offsets would leave a
        # flipped page drawing the other plate's geometry.  The middle
        # value is this ramp's own color at 72%, so the gradient is the
        # straight line it always was (2.4).
        'dome_stops': (('0%', '#ffffff'), ('72%', '#F3F1EA'),
                       ('100%', '#efece2')),
        'dome_rim': '#8a94a6',
        'conline': '#93A5C4',
        'orrery_sun': '#FACC15',
        'earth_fill': '#2E7DBE', 'earth_stroke': '#1B5C8F',
    },
}

# 'classic-night' and 'classic-light' named the pre-1.5 body colors, kept
# for skins that had attached to them.  They lasted a very short time
# before 1.5 shipped, nothing was ever attached to them, and carrying two frozen
# color schemes meant every contrast fix afterwards had to be argued twice
# -- the second time on a plate whose whole premise was that its colors
# could not move.  As of 2.3 both names resolve to the current plates.
# They stay ACCEPTED rather than removed: a skin passing one must keep
# rendering, not start raising SkyPageUsageError at report time.
PALETTE_ALIASES = {'classic-night': 'night', 'classic-light': 'light'}
# The same names as a THEME option value, which takes dark/light/auto
# rather than palette names.  'classic-dark' was never a name this
# extension used, but it is what someone writing a theme line from memory
# would reach for, so it resolves too rather than failing the page.
THEME_ALIASES = {'classic-night': 'dark', 'classic-dark': 'dark',
                 'classic-light': 'light'}
# What has already been warned about in this process -- see _palette and
# .theme.  Keyed by (surface, name), not by name alone: a station can hit
# BOTH surfaces with the same spelling (a template passing
# palette='classic-night' on a report whose theme option says the same),
# and a bare-name key would tell it about only whichever fired first.
_warned_palettes: set = set()


def _ring(pal: Dict[str, Any], name: str) -> str:
    """The stroke for a body's mark: its ring color if the palette gives it
    one (pale bodies on the light plate), else the plate's uniform halo."""
    return pal.get('ring', {}).get(name, pal['halo'])


# A band gridline's casing: the wide under-stroke that lets a rule cross
# twilight bands of any depth.  See _band_rule.
BAND_CASING_OPACITY = 0.55
BAND_CASING_WIDTH = 3

# The DATA marks that cross the same bands -- a body's above-horizon bar,
# its transit tick, the "now" line -- need a more opaque casing than a
# gridline does, and for a reason worth writing down: a gridline's color is
# chosen for contrast, where a body's is chosen for identity (Mars is red
# because Mars is red) and cannot also be chosen to clear a floor against
# five twilight depths.  The casing has to do all the work, so it is nearly
# solid.  0.55 leaves the "now" line at 2.31:1 on the paper plate's night
# band; 0.8 brings it to 3.65.
BAND_MARK_CASING_OPACITY = 0.8
# A bar carries two layers -- a casing under it AND an outline on it -- so
# its casing may be translucent.  A CURVE cannot take an outline (an
# outline on a 2px stroke is just a wider stroke), so its casing is the
# only thing between it and the band and has to be opaque: at 0.8 the
# sun-path arc drawn in the paper plate's dark gold still measured 2.62:1
# over the night band, at 1.0 it reads 3.61.
BAND_CURVE_CASING_OPACITY = 1.0
# The width of the casing behind a LABEL over the bands -- see
# _band_text.  Wide enough to close the gaps between glyph strokes at the
# 10px these labels are drawn at, narrow enough not to thicken the letters
# into a blur.
BAND_TEXT_CASING_WIDTH = 3
# How far a bar's casing stands out past the bar on every side, and the
# stroke width of a line mark's casing.
BAND_MARK_CASING_PAD = 1.5
BAND_MARK_CASING_WIDTH = 4

# The only two weights a band gridline may take.  A rank rather than a
# number at each call site, so a panel cannot quietly invent a third
# weight that no contrast audit knows to measure: the audit walks this
# mapping.  Primary carries a label (the hours, the altitudes), secondary
# is the finer rule between them -- the same pair, and the same values,
# the dome's rings and cross use.
BAND_RULE_OPACITY = {'primary': 0.75, 'secondary': 0.65}

# The sky charts' own chrome and star field.  Named for the same reason:
# the contrast audit READS these rather than grepping _sky_chart for the
# numbers, so changing one makes the audit recompute against it -- a value
# that stops clearing its floor fails, instead of quietly turning every
# ratio the audit reports into fiction.
DOME_RING_OPACITY = 0.75
DOME_CROSS_OPACITY = 0.65
# The star field dims while the sun is up, because those stars are not
# visible and the chart should not pretend otherwise.  Only the MARKS dim:
# a star's or constellation's name is drawn at full strength at every hour,
# since a name that is drawn is read, and text dimmed to 0.55 measured Lc 23
# against the dome.  Text is held to WCAG 4.5 and APCA Lc 60 with no
# opacity relief.
STAR_OPACITY_SUN_UP = 0.55
STAR_OPACITY_DARK = 0.95
# The constellation figures are background context and dim further still.
CONLINE_OPACITY_SUN_UP = 0.40
CONLINE_OPACITY_DARK = 0.55


def _num(v: float) -> str:
    """An SVG coordinate: integral values without a decimal point.  The
    sites feeding _band_rule mix ints and floats (an hour rule's x is
    computed, an altitude rule's y is not), and formatting them all %.1f
    would spell whole numbers 118.0 -- so normalize here instead."""
    return '%d' % v if float(v).is_integer() else '%.1f' % v


def _band_rule(x1: float, y1: float, x2: float,
               y2: float, rank: str) -> str:
    """One gridline drawn over the TWILIGHT BANDS -- the surface the ribbons,
    sun-path and day-length panels plot on.

    On the night plate the bands are all dark, so `bandgrid` alone reads
    against every one of them (1.97-3.17:1); its casing there is the night
    band's own color, which only deepens the band a little under the rule.
    The light plate cannot work that way: its ramp runs #3A5175 to
    #D7E6F5, a wider luminance span than any single stroke color can
    straddle -- the best candidate measured bottoms out at 1.72.  So they
    give `bandcase`, and the rule is drawn twice: a wide pale casing, then
    the rule itself on top of it.  The rule then reads against its own
    casing rather than against the band (3.15-4.36:1 on every band), which
    is the cartographer's answer to a line crossing varied ground, and the
    same trick the dome's labels already use as a halo.  New in 2.2.

    The casing is emitted on BOTH plates as of 2.4: a reader flipping a
    night page to light gets the casing the light plate's ratios assume,
    which a stylesheet could not conjure if the element were not there."""
    coords = ('x1="%s" y1="%s" x2="%s" y2="%s"'
              % (_num(x1), _num(y1), _num(x2), _num(y2)))
    strokes = ((_CASING, BAND_CASING_WIDTH, BAND_CASING_OPACITY),
               ('sky-stroke-bandgrid', 1, BAND_RULE_OPACITY[rank]))
    return ''.join('<line %s class="%s" stroke-width="%s" opacity="%s"/>'
                   % ((coords,) + s) for s in strokes)


def _band_bar(x: float, y: float, w: float, h: float,
              rx: float, fill_cls: str, inner: str = '') -> str:
    """A filled DATA mark drawn over the twilight bands: a body's
    above-horizon bar on the ribbons panel.

    Same surface as _band_rule, same problem, one extra twist.  A gridline
    may be any color that reads; a body's bar may not -- it carries the
    body's identity color, which is the whole point of the panel, so the
    contrast has to come from around it rather than from it.  Two layers do
    that between them, and which one carries a given band is decided by the
    band, not by us:

      * `bandcase`, a near-solid casing standing BAND_MARK_CASING_PAD past
        the bar, reads on the dark end of the ramp (3.65-4.9:1 on the paper
        plate's night and astro bands) and vanishes into the pale end --
      * where `bandedge`, a one-pixel outline on the bar itself, reads
        instead (4.2-10.9:1 on naut, civil and day).

    So every band is covered by one layer or the other, which no single
    color can do: the paper plate's ramp runs #3A5175 to #D7E6F5.  On the
    night plate the bands are all dark and the bar's own fill nearly
    carries it alone -- its casing, the night band's own color, adds a dark
    rim the outline sits inside.  Be honest about what that outline bought
    there when it was added: exactly one body (Mars, 2.93:1 on the day band)
    missed the floor, by 0.07.  The outline itself is not invisible -- it measures 3.59 to 6.18:1 against the
    bands, which is the point -- but at page scale it reads as a hairline
    rim rather than a restyle, and the regenerated screenshot is the place
    to judge that.  It costs one attribute on a rect already being drawn, and it means the audit holds for whatever body
    color changes next without an exemption to argue about.

    `inner` is markup nested inside the bar itself -- the <title> that makes
    the tooltip -- and deliberately does NOT go on the casing: the casing is
    decoration and should not be a second hover target.

    Both layers are emitted on both plates as of 2.4, and a layer a plate
    declines paints nothing.  Before that, the casing's absence was
    decided HERE, in the markup, where no stylesheet could reach it -- so a
    night page flipped to light by its reader lost the contrast this whole
    docstring is about."""
    return ('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" '
            'class="%s" opacity="%s"/>'
            '<rect x="%s" y="%s" width="%s" height="%s" rx="%s" '
            'class="%s sky-stroke-bandedge" stroke-width="1">%s</rect>'
            % (_num(x - BAND_MARK_CASING_PAD),
               _num(y - BAND_MARK_CASING_PAD),
               _num(w + 2 * BAND_MARK_CASING_PAD),
               _num(h + 2 * BAND_MARK_CASING_PAD),
               _num(rx + BAND_MARK_CASING_PAD), _CASING_FILL,
               BAND_MARK_CASING_OPACITY,
               _num(x), _num(y), _num(w), _num(h), _num(rx), fill_cls, inner))


def _ring_or_body(pal: Dict[str, Any], name: str) -> str:
    """The color to STROKE a body with: its ring where the plate gives it
    one (the paper plate's dark edges for pale bodies), else its own fill.
    Distinct from _ring, which falls back to the plate's halo -- a halo is
    right behind a dot and wrong as the color of a line."""
    return pal.get('ring', {}).get(name, pal['body'][name])


def _band_curve(d: str, stroke_cls: str, width: float,
                dash: str = '', opacity: str = '') -> str:
    """A plotted CURVE over the twilight bands: the sun's and moon's arcs on
    the sun-path panel, the sunrise/sunset/solar-noon traces on the solar
    year.  Same problem and same answer as _band_bar -- these carry body and
    ink colors chosen for a panel surface, and cross a ramp of bands they
    were never measured against -- but a curve cannot take an outline the
    way a bar can (an outline on a 2px stroke is just a wider stroke), so
    the casing carries it alone: one pale stroke, wider, painted first.  A
    dashed curve's casing takes the same dash, or a solid casing would
    quietly fill the gaps and turn the moon's track solid.

    On the night plate every one of these marks already clears the floor
    by its own color (4.93:1 worst); the casing there is the night band's
    own color and only deepens the band along the curve."""
    geom = 'd="M%s" fill="none"' % d
    return ('<path %s class="%s" stroke-width="%s" opacity="%s"%s/>'
            '<path %s class="%s" stroke-width="%s"%s%s/>'
            % (geom, _CASING, _num(width + 2 * BAND_MARK_CASING_PAD),
               BAND_CURVE_CASING_OPACITY, dash,
               geom, stroke_cls, _num(width), dash,
               ' opacity="%s"' % opacity if opacity else ''))


def _band_dot(cx: float, cy: float, r: float, fill_cls: str,
              inner: str = '', opacity: str = '') -> str:
    """A small filled mark over the bands -- the sun-path panel's hour dots
    and the moon track's endpoint dots.  A dot is too small to carry a
    casing as a second element underneath, so the casing is its own edge:
    one pale ring, which is what lifts it off a band its fill matches.  The
    ring is written on both plates as of 2.4."""
    return ('<circle cx="%s" cy="%s" r="%s" class="%s %s" '
            'stroke-width="%s" stroke-opacity="%s"%s>%s</circle>'
            % (_num(cx), _num(cy), _num(r), fill_cls, _CASING,
               _num(BAND_MARK_CASING_PAD), BAND_CURVE_CASING_OPACITY,
               ' opacity="%s"' % opacity if opacity else '', inner))


def _band_text(x: float, y: float, anchor: str, cls: str, text: str) -> str:
    """A LABEL drawn over the twilight bands, carrying its own casing.

    Same problem as _band_rule and the same answer, for the one mark type
    2.2 and 2.3 did not cover: text.  A label over the bands has no color
    that works -- the ramp runs #3A5175 to #D7E6F5 on the paper plate and
    NOTHING clears 4.5:1 against all five, not the plate's muted, not its
    ink, not pure black (2.35 on the night band).  So the label reads
    against a casing of its own instead, which is what every other mark
    over these bands already does.

    Drawn as the same text twice: a fattened silhouette in the casing
    color, then the label on top of it.  Two elements rather than
    `paint-order: stroke`, which is the obvious way and which the Nu
    validator rejects as an unknown property -- and shipped CSS has to
    pass that gate.  The casing copy is aria-hidden, or a screen reader
    reads every one of these labels twice.

    The night plate's labels clear every one of its bands by color alone,
    but not what is DRAWN on the bands: the sun-path hour numbers sit on
    the sun's own arc, and ink over that yellow read 1.17:1.  So the night
    plate carries a casing too, in its night band's own color, which cannot
    be seen over that band and covers whatever arc or dot runs under the
    glyphs."""
    geom = '<text x="%.1f" y="%.1f" text-anchor="%s" ' % (x, y, anchor)
    return (geom + 'class="%s sky-fill-bandcase sky-stroke-bandcase" '
                   'stroke-width="%s" stroke-linejoin="round" '
                   'aria-hidden="true">%s</text>'
                   % (cls, BAND_TEXT_CASING_WIDTH, text)
            + geom + 'class="%s">%s</text>' % (cls, text))


def _band_tick(x1: float, y1: float, x2: float,
               y2: float, stroke_cls: str, width: float, cls: str = '',
               attrs: str = '', inner: str = '') -> str:
    """A line DATA mark over the same bands: the transit tick, the "now"
    line.  The casing half of _band_bar, without the outline -- an outline
    on a 1.5px line would just be a wider line, and these marks read
    against their casing directly (3.65-10.9:1 on the paper plate).  On the
    night plate these already clear the floor on every band by their own
    color (4.93:1 worst), and the casing, the night band's own color, only
    deepens the band under them.

    `cls` is the mark's own class (the pulsing "now" line has one); it
    joins the stroke role rather than replacing it."""
    coords = ('x1="%s" y1="%s" x2="%s" y2="%s"'
              % (_num(x1), _num(y1), _num(x2), _num(y2)))
    return ('<line %s class="%s" stroke-width="%s" opacity="%s"/>'
            '<line %s class="%s" stroke-width="%s"%s>%s</line>'
            % (coords, _CASING, BAND_MARK_CASING_WIDTH,
               BAND_MARK_CASING_OPACITY,
               coords, ' '.join(filter(None, (stroke_cls, cls))),
               _num(width), attrs, inner))


class SkyPageUsageError(ValueError):
    """A template-author error (e.g. an unknown palette name).  Re-raised
    through the panel guard: it should fail loudly at development time,
    not blank a panel."""


def _palette(name: str) -> Dict[str, Any]:
    if name in PALETTE_ALIASES:
        # Once per name per process, not per call: a page asks for its
        # palette a dozen times per report cycle, and this must not turn
        # into a dozen lines in the log every five minutes.
        if ('palette', name) not in _warned_palettes:
            _warned_palettes.add(('palette', name))
            log.warning("palette %r was dropped in 2.3 and is being drawn as "
                        "%r; update the skin to say %r.",
                        name, PALETTE_ALIASES[name], PALETTE_ALIASES[name])
        name = PALETTE_ALIASES[name]
    if name not in PALETTES:
        raise SkyPageUsageError('unknown palette %r; valid palettes: %s'
                                % (name, ', '.join(sorted(PALETTES))))
    return PALETTES[name]


def _resolve_palette(name: str) -> Tuple[str, Dict[str, Any]]:
    """The palette's RESOLVED name and its values.  The name is half the
    answer now: it scopes the class defaults each SVG carries (see
    _style_block), so an alias must resolve before it reaches the markup or
    a page asking for 'classic-night' would emit rules no selector matches."""
    pal = _palette(name)          # warns on an alias, raises on an unknown name
    return PALETTE_ALIASES.get(name, name), pal


# ── the class contract ───────────────────────────────────────────────────────
# Every graphical mark carries a class naming its ROLE, and each SVG carries
# the requested palette's values for the roles it actually used, as rules of
# ZERO specificity.  A consuming skin can then repaint any mark from its own
# stylesheet -- which is what a per-viewer light/dark switch needs, since the
# SVG is written once per report cycle and the reader flips themes long
# afterwards -- while a consumer that does nothing renders exactly as before.
#
# Three things make that work, and all three are load-bearing:
#
#   * The PAINT CHANNEL is in the class name.  `ink`, `brass`, `muted` and
#     `halo` are each a fill on one mark and a stroke on another, so one
#     class per role would paint the inside of a stroked curve.
#   * Both halves of the selector are wrapped in :where(), which contributes
#     no specificity, so a rule naming even one class -- a bare
#     `.sky-fill-ink` -- outranks it wherever that rule sits.
#     `svg :where(.sky-fill-ink)` would NOT do: a type selector scores
#     (0,0,1) and would beat the consumer's rule.  The honest edge: a
#     consumer rule that ALSO scores zero ties, and a tie goes to document
#     order, which these defaults win from inside the body.  Named in
#     docs/panels.md and pinned in tests/verify_sky_classes.py.
#   * The rules are scoped to a palette class on the <svg> ITSELF.  A <style>
#     inside inline SVG is not scoped to that SVG in an HTML document -- it
#     applies document-wide -- so two panels of different palettes on one
#     page (a night dome on a light page, which is exactly what weewx-
#     celestial reconciles today) would otherwise collide, last one winning
#     for both.
#
# The class list is a published contract; see docs/panels.md.  It covers the
# nine bodies THIS page draws (CHART_BODIES) -- a consuming skin that shows
# more, as weewx-celestial does, styles those from its own tokens.
# Role classes are read back out of the markup's class ATTRIBUTES -- never
# out of the markup as a whole, which also carries body tag names and
# translated tooltip text that a station could spell like a class.
_CLASS_ATTR_RE = re.compile(r'class="([^"]*)"')
# Roles that appear in both channels; a plate's value is one color and the
# class says which side of the mark it paints.
_DUAL_ROLES = ('ink', 'muted', 'brass', 'line', 'grid', 'bandgrid',
               'halo', 'conline')
# Roles a plate may decline: the casing under a band mark and the outline on
# it, the light plate's two answers to a ramp no single color straddles.  The
# night plate declared no casing until its labels were measured over the
# sun's arc (see _band_text).  Declining paints nothing; it does not decide
# whether the element exists (see _band_bar).
_OPTIONAL_ROLES = ('bandcase', 'bandedge')
# The two classes the band helpers reach for by name, often enough to be
# worth spelling once.
_CASING = 'sky-stroke-bandcase'
_CASING_FILL = 'sky-fill-bandcase'


def _sky_classes(pal: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """{class name: (CSS property, value)} for one plate.

    Generated from the palette, so a color added there reaches the markup
    without a second list to keep in step.  A plate may decline the two
    _OPTIONAL_ROLES, and a declined role resolves to `none`: the mark is
    emitted either way and simply paints nothing, because an element that was never written cannot be
    styled back into existence by a reader who flips to a plate that wants
    one."""
    d: Dict[str, Tuple[str, str]] = {}
    for role in _DUAL_ROLES:
        d['sky-fill-%s' % role] = ('fill', pal[role])
        d['sky-stroke-%s' % role] = ('stroke', pal[role])
    for role in _OPTIONAL_ROLES:
        d['sky-fill-%s' % role] = ('fill', pal[role] or 'none')
        d['sky-stroke-%s' % role] = ('stroke', pal[role] or 'none')
    d['sky-fill-orrery-sun'] = ('fill', pal['orrery_sun'])
    d['sky-stroke-dome-rim'] = ('stroke', pal['dome_rim'])
    d['sky-fill-earth'] = ('fill', pal['earth_fill'])
    d['sky-stroke-earth'] = ('stroke', pal['earth_stroke'])
    d['sky-fill-moon-dark'] = ('fill', pal['moon_dark'])
    d['sky-fill-moon-lit'] = ('fill', pal['moon_lit'])
    d['sky-stroke-moon-ring'] = ('stroke', pal['moon_ring'])
    for shade, color in pal['twilight'].items():
        d['sky-fill-tw-%s' % shade] = ('fill', color)
    for name, color in pal['body'].items():
        # The four strokes a body mark can take differ in what they fall
        # back to where the plate declares no ring for that body: `body` is
        # the identity color itself (the sun's rays, which are its disc's
        # color drawn as lines), `ring` falls back to the plate's halo (a
        # dot's edge), `trace` to the body's own color (a line cannot wear
        # a halo), `rim` to nothing at all (the light plate's lift for pale
        # bodies, which the night plate neither needs nor drew).
        d['sky-fill-body-%s' % name] = ('fill', color)
        d['sky-stroke-body-%s' % name] = ('stroke', color)
        d['sky-stroke-ring-%s' % name] = ('stroke', _ring(pal, name))
        d['sky-stroke-trace-%s' % name] = ('stroke', _ring_or_body(pal, name))
        # ... and as a fill, for the dots that terminate a trace and must
        # match the line they end (the moon track's midnight endpoints).
        d['sky-fill-trace-%s' % name] = ('fill', _ring_or_body(pal, name))
        d['sky-stroke-rim-%s' % name] = ('stroke',
                                         pal.get('ring', {}).get(name) or 'none')
    for i, (_offset, color) in enumerate(pal['dome_stops'], 1):
        d['sky-dome-stop-%d' % i] = ('stop-color', color)
    return d


def _partner(cls: str) -> Optional[str]:
    """The same role in the other paint channel, or None for a role that
    exists in one channel only (`dome-rim` strokes, `tw-civil` fills)."""
    for here, there in (('sky-fill-', 'sky-stroke-'),
                        ('sky-stroke-', 'sky-fill-')):
        if cls.startswith(here):
            return there + cls[len(here):]
    return None


def _style_block(markup: str, pal_name: str, extra: str = '') -> str:
    """The <style> an SVG carries: a zero-specificity default for every
    role class the markup actually used -- AND for each of those roles in
    the other paint channel -- scoped to this plate.  `extra` is appended
    inside the same block: the sky charts' label-layer rules
    (_layer_rules), which are the one thing here that is NOT
    zero-specificity, for a reason given there.

    Driven by the markup rather than by a per-panel list of roles, so it
    cannot go stale -- a mark whose class nobody declared would render
    unpainted, and a list is exactly the thing that drifts from the code
    beside it (see CHART_BODIES for how that goes).

    The partner is why this is not simply "what the markup used".  A mark
    whose two states are one another's inverse -- a sunlit satellite is
    `sky-fill-brass sky-stroke-halo`, a shadowed one the same pair
    exchanged -- lets a live consumer flip it by exchanging the suffixes,
    which is the documented way to invert a mark without naming a color
    (docs/panels.md).  Emitting only what the chart HAPPENED to draw
    breaks that: a chart whose satellite is sunlit never fills with halo,
    so the swapped mark asks for `sky-fill-halo`, finds no rule, and falls
    back to the SVG initial -- BLACK for a fill, `none` for a stroke.  A
    solid black disc where a hollow white ring belongs, on the light
    plate, with nothing logged.  Found by weewx-celestial's code review on
    the day 2.4 was written, in the technique this file recommends.
    Completing the pair costs about a third more style bytes, roughly 1%
    of the page, and makes the recommendation true for every consumer
    rather than for the states a given chart happened to be in."""
    defs = _sky_classes(PALETTES[pal_name])
    seen = set()
    for attr in _CLASS_ATTR_RE.findall(markup):
        seen.update(attr.split())
    used_now = seen & set(defs)
    partners = {p for p in (_partner(c) for c in used_now)
                if p is not None and p in defs}
    used = sorted(used_now | partners)
    return '<style>%s%s</style>' % (''.join(
        ':where(svg.sky-%s) :where(.%s){%s:%s}'
        % (pal_name, cls, defs[cls][0], defs[cls][1]) for cls in used), extra)


def _svg_out(p: List[str], pal_name: str, extra_css: str = '') -> str:
    """Assemble an SVG built as [open tag, ...body..., '</svg>'].

    The style block is spliced in after the open tag, which is p[0] by
    construction -- never by searching the markup for the first '>', which
    a translated aria-label could carry."""
    body = ''.join(p[1:])
    return p[0] + _style_block(p[0] + body, pal_name, extra_css) + body


# ── label layers ─────────────────────────────────────────────────────────
# A media query is written into the chart's own <style>, which sits inside
# inline SVG inside an HTML document -- and in foreign content the HTML
# parser does NOT treat <style> as raw text, so a `<` or `&` in the query
# would be parsed as markup.  The whitelist admits `(max-width: 600px)`
# and its kin and refuses the Level 4 range syntax `(width < 600px)`,
# along with anything that could close the block or the element.  The
# parentheses must also balance: an unclosed `(` is a CSS block that runs to
# the end of the stylesheet, so it would swallow every rule written after
# it -- a later layer's hide rule among them, and that layer would then
# show on top of the base.
_MEDIA_QUERY_RE = re.compile(r'^[A-Za-z0-9 :(),.-]+$')


def _parens_balance(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
MEDIA_QUERY_CHARS = "letters, digits, spaces and : ( ) , . -"


def _fmt_scale(scale: float) -> str:
    """A label scale as it appears in markup and in the rules that select
    it: `%g`, so 1.0 reads `1` and 2.2 reads `2.2`, and the attribute and
    the selector cannot disagree by a trailing zero."""
    return '%g' % scale


def _scale_or_raise(value: Any, what: str) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        raise SkyPageUsageError('%s must be a number, not %r' % (what, value)) from None
    if not math.isfinite(scale) or scale <= 0:
        raise SkyPageUsageError('%s must be a positive number, not %r' % (what, value))
    return scale


def _label_layers(label_scale: Any, label_layers: Any
                  ) -> List[Tuple[float, Optional[str]]]:
    """The label layers a sky chart draws, base first: [(scale, None),
    (scale, media_query), ...].  Every input is checked here, and a bad
    one is a SkyPageUsageError -- the template author's mistake, raised
    through the panel guard rather than swallowed into a blank panel.

    Scales must be distinct as FORMATTED (_fmt_scale): two layers that
    format alike would carry the same data-label-scale, and the rules
    that pick a layer by it could not tell them apart."""
    layers: List[Tuple[float, Optional[str]]] = [
        (_scale_or_raise(label_scale, 'label_scale'), None)]
    if label_layers is None:
        return layers
    try:
        pairs = list(label_layers)
    except TypeError:
        raise SkyPageUsageError(
            'label_layers must be a list of (scale, media_query) pairs, not %r'
            % (label_layers,)) from None
    for pair in pairs:
        try:
            scale_in, query = pair
        except (TypeError, ValueError):
            raise SkyPageUsageError(
                'each label_layers entry must be a (scale, media_query) pair, not %r'
                % (pair,)) from None
        scale = _scale_or_raise(scale_in, 'label_layers scale')
        if any(_fmt_scale(scale) == _fmt_scale(s) for s, _q in layers):
            raise SkyPageUsageError(
                'label_layers scale %s repeats a scale the chart already draws; '
                'each layer needs its own' % _fmt_scale(scale))
        clean = query.strip() if isinstance(query, str) else ''
        if not clean or not _MEDIA_QUERY_RE.match(clean) or not _parens_balance(clean):
            raise SkyPageUsageError(
                "label_layers media query %r is not usable: it is written into the "
                "chart's own <style>, so it may contain only %s, with its "
                "parentheses balanced -- for example '(max-width: 600px)'"
                % (query, MEDIA_QUERY_CHARS))
        layers.append((scale, clean))
    return layers


def _layer_set(layers: List[Tuple[float, Optional[str]]]) -> str:
    """The chart's scales, base first, as `data-label-layers` spells them
    on the svg root.  One function, because the rules select on this
    exact string: were the attribute and the selector built separately, a
    change to either would silently unscope every rule."""
    return ' '.join(_fmt_scale(s) for s, _q in layers)


def _layer_media_key(layers: List[Tuple[float, Optional[str]]]) -> str:
    """A short key naming the chart's extra layers' media queries, in layer
    order -- the `data-label-media` value.  Empty with no extra layer: a
    chart with no rules has nothing to scope.  A hash rather than the
    queries themselves, since a query's spaces, colons and parentheses
    would have to survive an attribute value AND a quoted CSS attribute
    selector; the whitelist forbids a newline, so the joined text is
    unambiguous."""
    queries = [q for _s, q in layers[1:] if q is not None]
    if not queries:
        return ''
    return hashlib.sha1('\n'.join(queries).encode('utf-8')).hexdigest()[:8]


def _layer_attrs(layers: List[Tuple[float, Optional[str]]]) -> str:
    """The svg root's layer attributes: `data-label-layers` always, and
    `data-label-media` when the chart has an extra layer."""
    key = _layer_media_key(layers)
    return (' data-label-layers="%s"' % _layer_set(layers)
            + (' data-label-media="%s"' % key if key else ''))


def _layer_rules(pal_name: str, layers: List[Tuple[float, Optional[str]]]) -> str:
    """The rules that pick ONE label layer for the reader's viewport: each
    extra layer hidden, and under its media query the base layer hidden
    and that one shown.  Empty with no extra layers, so a chart that asked
    for none carries no rule.

    Scoped to EVERYTHING the rules depend on -- the plate, the scales and
    the queries: `svg.sky-night[data-label-layers="0.8 2.2"][data-label-
    media="3f9a0c1e"]` -- because a <style> in an HTML page reaches every
    element on it, so any chart whose root matched the selector would obey
    this chart's queries.  The plate alone let a layered dome hide an
    unlayered pass chart's only labels; plate and scales alone let two
    charts with the same scales but different queries -- a width query on
    one, a portrait query on the other -- each switch the other's labels.
    This is the 2.4 rule for gradient ids applied to rules: charts whose
    key matches emit identical rules, which is harmless, and a chart whose
    key differs can never match.

    Plain specificity, NOT :where.  The zero specificity of the paint
    defaults exists so an embedding skin wins with any rule; the layer is
    the caller's own request, and a consumer's `.dome-labels{display:
    block}` or a generic `svg g{...}` reset must not silently show both
    layers.  A consumer that wants to force a layer can still out-specify
    these.  With two extra layers whose queries both match, both show and
    the base hides: keeping the queries disjoint is the caller's business."""
    if len(layers) == 1:
        return ''
    scope = ('svg.sky-%s[data-label-layers="%s"][data-label-media="%s"]'
             % (pal_name, _layer_set(layers), _layer_media_key(layers)))

    def sel(scale: float) -> str:
        return '%s .dome-labels[data-label-scale="%s"]' % (scope, _fmt_scale(scale))

    base = sel(layers[0][0])
    return ''.join(
        '%s{display:none}@media %s{%s{display:none}%s{display:inline}}'
        % (sel(scale), query, base, sel(scale))
        for scale, query in layers[1:])


def _svg_open(attrs: str, pal_name: str) -> str:
    """An SVG root tag carrying the plate class its defaults are scoped to."""
    return '<svg %s class="sky sky-%s">' % (attrs, pal_name)


def _panel_guard(fallback: Any = '', needs: int = 0) -> Callable:
    """Wrap a $sky_page render method so a failure costs only its own panel:
    the error is logged and the panel renders as `fallback`.  Without this,
    one raising tag takes out the whole Sky page for that report cycle --
    exactly how the (since-guarded) wild skyfield event time fixed in 1.3
    presented.  SkyPageUsageError passes through unchanged.

    `needs` is the panel's FLOOR on the tier ladder above (TIER_BASIC,
    TIER_EXTRAS, TIER_ENGINE), read from the almanac the panel was handed.
    Below its floor the panel returns `fallback` deliberately, and the tier
    says so once in the log, instead of throwing its way to the same blank
    panel: the station that found this had a Sky page but no almanac
    service, and every report cycle wrote a TypeError per dome into a log
    nobody was reading while the pages merely looked empty.

    The TIER_ENGINE floor is a DELIBERATE TRADE, and worth stating
    plainly because the code cannot show it: three of those five panels
    are unusable below it anyway, but dome_svg is NOT -- on the PyEphem
    tier it draws about 5 KB of working chart, the sun, the moon and the
    seven planets correctly placed, with no stars and no constellation
    figures.  We decline to draw that, for two reasons.  can_draw() is a
    published contract that has meant "these five panels come back empty"
    since 2.3.4, and weewx-celestial 9.0 already gates on it: let the dome
    draw below the floor and a consumer that gated correctly hides a dome
    that would have rendered, which is worse than not gating at all.  And
    the tier is a misconfiguration we now diagnose in the log -- a blank
    panel beside that line reads as "not configured", where a starless
    night dome reads as "the sky is empty", a claim nothing on the page
    corrects at a glance.  Moving dome_svg to TIER_EXTRAS is a one-word
    change; it is also a change to a shipped contract, and weewx-celestial
    would need to hear about it.

    Below that floor the requirement is per panel: most panels need only a
    body's position and a rise time (TIER_EXTRAS), and a handful -- the
    header, the footer, the theme -- need no almanac data at all and draw
    on any station."""
    def decorate(method: Callable) -> Callable:
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            try:
                # INSIDE the try: _almanac_tier() imports the almanac module
                # to identify the registered type, and a gate that could
                # raise past the guard would cost the whole page the one
                # failure this decorator exists to contain.
                if needs > TIER_BASIC:
                    # The almanac is the first positional for every panel
                    # that takes one -- but read the keyword too, because a
                    # template writing alm=$almanac would otherwise read as
                    # no almanac at all and drop a panel to the basic tier
                    # on a station that can draw it.
                    tier = _almanac_tier(args[0] if args else kwargs.get('alm'))
                    if tier < needs:
                        _note_tier(tier)
                        return fallback
                return method(self, *args, **kwargs)
            except SkyPageUsageError:
                raise
            except Exception as e:
                log.error('sky_page.%s failed (%s: %s); rendering that panel blank.'
                          % (method.__name__, type(e).__name__, e))
                return fallback
        return wrapper
    return decorate

PLANETS = ['mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune']
# Every body the panels paint, and so exactly the bodies a plate gives a
# color to.  The two must not drift: the contrast audits walk the PALETTE,
# so a color for a body nothing draws is a ratio measured on a mark that
# does not exist -- the light plate carried a `pluto` from 1.5 to 2.4, and
# 2.3's change log reported having fixed its contrast against the twilight
# bands, where no Pluto has ever been drawn.  The almanac serves Pluto in
# full ($almanac.pluto); these are the CHART's bodies, which are the
# classical planets.  test_a_plate_colors_exactly_the_drawn_bodies pins it.
CHART_BODIES = ['sun', 'moon'] + PLANETS
SEMI_MAJOR_AU = {'mercury': 0.387, 'venus': 0.723, 'earth': 1.0, 'mars': 1.524,
                 'jupiter': 5.203, 'saturn': 9.537, 'uranus': 19.19, 'neptune': 30.07}

STAR_MAG_LIMIT = 5.0          # dome shows stars at least this bright (default)
STAR_LABEL_MAG = 2.5          # ... and labels these (default)
# The pass chart's cutoffs.  A visible pass happens while the sky is only
# half dark, so the chart plots roughly the stars a twilight sky actually
# shows and labels only the brightest -- a finder chart, not a census.
# Constants, not options, until a consumer asks.
PASS_STAR_MAG_LIMIT = 3.5
PASS_STAR_LABEL_MAG = 1.5
# The dome keeps constellation line vertices down to this altitude: a
# just-set star still anchors its segment (the dome's clipPath trims it at
# the rim), while the polar projection's blowup toward the antipode stays
# far away from the chart.
CON_ALT_FLOOR = -15.0
# The supermoon callout fires when the next full moon falls within a day
# of perigee -- the popular definition.  A constant, not an option, until
# a consumer asks.
# A comet brighter than this is plausibly naked-eye: the dome's solid
# marker.  Anything fainter -- or with no magnitude parameters in its MPC
# row -- draws as the hollow ring: present but not visible to the eye.
# A constant, not an option, until a consumer asks.
COMET_NAKED_EYE_MAG = 6.0
# The countdown row shows a comet's perihelion only when it lies ahead
# within this window: the news-cycle chip, without Halley's 2061 date
# squatting on the header for decades.
COMET_PERIHELION_COUNTDOWN_S = 365 * 86400

REPO_URL = 'https://github.com/chaunceygardiner/weewx-skyfield'


def _raw(value_helper, unit: str) -> Optional[float]:
    """The tag's value as a float in the given unit, or None.

    Never read .raw without pinning the unit: a ValueHelper converts to
    the report's preferred units at construction, so .raw honors any
    [Units] [[Groups]] override (field case: a station-wide
    group_deltatime = hour turned every 'visible' into hours, and the
    panels' seconds arithmetic rendered every duration as 0h 00m).
    Times are 'unix_epoch', durations 'second'."""
    try:
        return value_helper.convert(unit).raw
    except Exception:
        return None


def _tag_raw(obj: Any, path: str, unit: str) -> Optional[float]:
    """_raw(), but reading the tag itself INSIDE the guard.

    `_raw(alm.next_supermoon, 'unix_epoch')` evaluates the attribute
    before _raw is even called, so an almanac that does not serve that
    tag raises straight past _raw's except -- the same wrong-half mistake
    the dome's meteor-shower guard made.  Use this wherever the tag
    itself, and not merely its value, may be unserved.

    `path` may be dotted ('moon.next_perigee'), and EVERY hop is read in
    here: the receiver is an argument too, so `_tag_raw(alm.moon,
    'next_perigee', ...)` would evaluate alm.moon outside the guard --
    the identical mistake, one level shallower."""
    try:
        value = obj
        for step in path.split('.'):
            value = getattr(value, step)
        return _raw(value, unit)
    except Exception:
        return None


def _t_hm(ts: Optional[float]) -> str:
    return time.strftime('%H:%M', time.localtime(ts)) if ts else '&#8212;'


def _days_until(now_ts: float, ts: float) -> int:
    """Whole LOCAL CALENDAR DAYS from now_ts to ts, never negative.

    The count labels a chip whose value line is a calendar date, so it
    has to be reckoned the way a person reading that date reckons it --
    by which day of the month the event falls on, not by how many
    24-hour periods away it is.  Elapsed-seconds arithmetic disagrees
    with the date beside it twice a day: rounding up calls an event
    later this evening "in 1 day" (Jacques Terrettaz's report, the
    2026-08-12 partial solar eclipse, issue #6), and rounding down calls
    one just after midnight "today".  Differencing the two local dates
    cannot disagree with a date it is computed from, and it costs
    nothing to be DST-correct as well: the day a clock shifts is still
    one day.

    The clamp is belt-and-braces -- every caller passes a next_* event,
    which cannot fall on an earlier date than now -- but it keeps a
    stray past timestamp reading "today" rather than "in -1 days"."""
    return max(0, (datetime.datetime.fromtimestamp(ts).date()
                   - datetime.datetime.fromtimestamp(now_ts).date()).days)


def _comet_tail(x: float, y: float, ux: float, uy: float, cls: str) -> str:
    """Three short rays fanning out from a comet marker along (ux, uy),
    the unit ANTI-SUNWARD direction in chart coordinates -- a comet's
    tail always points away from the sun, so the glyph is honest physics
    as well as iconography (a bare diamond says nothing; a tailed one
    reads as a comet at a glance)."""
    rays = []
    for angle, length, opacity in ((-0.18, 9.0, '0.55'), (0.0, 12.0, '0.9'),
                                   (0.18, 9.0, '0.55')):
        ca, sa = math.cos(angle), math.sin(angle)
        rx, ry = ux * ca - uy * sa, ux * sa + uy * ca
        rays.append('<line class="comet-tail %s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                    'stroke-width="1.2" opacity="%s"/>'
                    % (cls, x + 6.0 * rx, y + 6.0 * ry, x + (6.0 + length) * rx,
                       y + (6.0 + length) * ry, opacity))
    return ''.join(rays)


def _esc(s: str) -> str:
    # Quotes too: translated text lands inside attribute values (titles,
    # aria-labels), and translators control that text.
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _wxskyfield():
    """The almanac module.  In an installed WeeWX, bin/user modules are
    importable only as the 'user' package (user.wxskyfield); the test
    suite imports them top-level.  Try the installed form first."""
    try:
        import user.wxskyfield as m
    except ImportError:
        import wxskyfield as m
    return m


def _find_almanac_type():
    """The registered Skyfield almanac type, or None."""
    for a in getattr(weewx.almanac, 'almanacs', []):
        if isinstance(a, _wxskyfield().SkyfieldAlmanacType):
            return a
    return None


def _find_sky():
    """The Sky engine of the registered Skyfield almanac (for the star
    catalog and its magnitudes), or None."""
    a = _find_almanac_type()
    return a.sky if a is not None else None


def _have_engine() -> bool:
    """Whether the registered Skyfield almanac is serving this page.

    THE one predicate behind both can_draw() -- the public contract an
    embedding skin gates on -- and the top rung of the tier ladder below.
    One function, so what can_draw() reports and what the TIER_ENGINE
    panels actually do can never disagree.  Keeping those two in step is
    the whole reason the ladder's top rung is drawn where it is: see
    _panel_guard, where declining above TIER_EXTRAS is a deliberate
    trade, not a limitation."""
    return _find_sky() is not None


# ── the almanac tiers a $sky_page panel can land on ──────────────────────
#
# A WeeWX station serves $almanac from one of three things, and the page
# can draw a different amount on each.  Weakest first; each tier serves
# everything the tier below it does, so a panel names only its FLOOR and
# the guard compares.
#
#   TIER_BASIC    WeeWX's own weeutil almanac, which weewx/almanac.py
#                 registers when PyEphem is not installed.  It serves
#                 sunrise, sunset and the moon's phase, and raises for
#                 everything else -- no body positions, no rise/set for
#                 anything but the sun, no phase events.
#   TIER_EXTRAS   Any almanac reporting hasExtras -- in practice PyEphem.
#                 Bodies with alt/az/rise/set/transit/distance, the moon's
#                 quarters, the equinox and the solstice.
#   TIER_ENGINE   This extension's Skyfield almanac.  Everything above,
#                 plus the star catalog, satellites, comets, meteor
#                 showers, the equation of time and the moon's apsides.
#
# Written down here, and not inferred panel by panel, because inferring it
# went wrong: the first cut of this modeled only two tiers -- engine and
# not-engine -- and so put PyEphem's eleven panels on the basic tier,
# where every one of them threw an AttributeError per page per report
# cycle.  A panel added later states its floor here or it states nothing,
# and tests/test_sky_page.py pins every panel to a rung.
TIER_BASIC = 0
TIER_EXTRAS = 1
TIER_ENGINE = 2


def _almanac_tier(alm) -> int:
    """Which rung of the ladder is serving this page.

    Two different questions, deliberately: _have_engine() reads WeeWX's
    almanac REGISTRY, where our type sits at the head, while hasExtras is
    WeeWX's own question about the almanac object the report built.  A
    missing or None almanac reads as the weakest tier, so a panel called
    without one declines instead of raising."""
    if _have_engine():
        return TIER_ENGINE
    return TIER_EXTRAS if getattr(alm, 'hasExtras', False) else TIER_BASIC


# The tiers this process has already reported -- see _note_tier.  Keyed by
# the tier found rather than the tier wanted: one station sits on exactly
# one rung, and every panel that declines there declines for the same
# reason and wants the same sentence.
_warned_tiers: set = set()


def _note_tier(tier: int) -> None:
    """Say ONCE per process, per tier, what this station's almanac cannot
    draw and how to fix it.

    Once, not once per panel per report cycle: the tier cannot change
    while weewxd runs -- the almanac registers at engine startup or never
    -- and a skin with sixteen domes would otherwise write sixteen lines
    every archive interval, which is precisely the noise this replaced.
    The page's own footer carries the same diagnosis permanently ('weewx-
    skyfield is not active -- see the weewxd log'), so the log line only
    has to be findable once, and it is what that footer points at.

    WARNING, not ERROR: both lesser tiers are legitimate configurations --
    the almanac service and the $sky_page search-list extension install
    and configure separately, so a station can reasonably have one without
    the other -- but a station that went to the trouble of adding the page
    probably did not mean to get the empty half of it."""
    if tier in _warned_tiers:
        return
    _warned_tiers.add(tier)
    fix = ('Add user.wxskyfield.WxSkyfield to data_services and a [Skyfield] '
           'section to weewx.conf (installing this extension does both), or '
           'gate the panels on $sky_page.can_draw() to stop reserving space '
           'for them.')
    if tier == TIER_BASIC:
        log.warning('WeeWX is computing $almanac with its own sunrise/sunset '
                    'formulas -- neither the Skyfield almanac nor PyEphem is '
                    'available -- and almost every $sky_page panel renders '
                    'empty on it: they need body positions, rise and set '
                    'times and phase events that this almanac does not '
                    'serve.  ' + fix)
    else:
        log.warning('the Skyfield almanac is not registered, so $sky_page '
                    'cannot draw the sky: the dome, the pass chart, the '
                    'satellite rows, the equation of time and the moon '
                    'apsides render empty.  The remaining panels draw from '
                    'the almanac WeeWX has.  ' + fix)


_HIP_NAMES: Optional[Dict[int, str]] = None


def _hip_names() -> Dict[int, str]:
    """NAMED_STARS reversed: Hipparcos number to tag name.  The first
    name in NAMED_STARS order wins, matching the named-star dome's
    dedup, so a star labels identically on both paths."""
    global _HIP_NAMES
    if _HIP_NAMES is None:
        names: Dict[int, str] = {}
        for name, hip in _wxskyfield().NAMED_STARS.items():
            names.setdefault(hip, name)
        _HIP_NAMES = names
    return _HIP_NAMES


def _opt_float(sd: Dict[str, Any], key: str, default: float) -> float:
    """The skin option as a float, clamped to the magnitudes the dome
    can sensibly draw (-2, brighter than Sirius, through 6.5, the
    naked-eye limit); the default on a missing or malformed value -- a
    bad option must never blank the page."""
    try:
        v = float(sd.get(key, default))
    except (TypeError, ValueError):
        return default
    return min(max(v, -2.0), 6.5)


class SkyPage:
    """The template-facing helper: each method returns a finished SVG or
    HTML fragment for one panel of the Sky page.

    Constructed with the report's skin_dict, whose [Texts] section
    translates the panels' own strings: gettext-style, the English string
    is the key and a missing entry falls back to it, so a partial
    translation degrades one string at a time, never a panel.  The other
    translated words come from the core-standard sources, not invented
    keys: body display names from the almanac's texts (the [Almanac]
    section -- the same source as $almanac.<body>.label), compass
    cardinals from the report formatter's [Units][[Ordinates]] directions,
    and the coordinate hemisphere letters from [Labels] hemispheres."""

    def __init__(self, skin_dict: Optional[Dict[str, Any]] = None) -> None:
        # Per-page memo of body evaluations: rise/set searches are the
        # expensive tags and three panels need them.
        self._memo: Dict[Tuple[float, str], Dict[str, Any]] = {}
        sd: Dict[str, Any] = skin_dict if skin_dict is not None else {}
        # The report's theme option (dark | light | auto); resolved by
        # .theme() -- auto needs the almanac.
        self._theme_conf: str = str(sd.get('theme', 'dark')).lower()
        # The dome's magnitude cutoffs (skin.conf star_mag_limit /
        # star_label_mag, overridable per report).
        self._star_mag_limit: float = _opt_float(sd, 'star_mag_limit', STAR_MAG_LIMIT)
        self._star_label_mag: float = _opt_float(sd, 'star_label_mag', STAR_LABEL_MAG)
        # The dome's constellation figures (skin.conf constellation_lines,
        # overridable per report).  Only an explicit "off" value turns them
        # off: a malformed value must never change the page's look.
        self._constellation_lines: bool = (
            str(sd.get('constellation_lines', True)).strip().lower()
            not in ('false', 'no', '0', 'off'))
        self._texts: Dict[str, Any] = sd.get('Texts', {}) or {}
        hemis = (sd.get('Labels', {}) or {}).get('hemispheres', ())
        if isinstance(hemis, str):
            hemis = (hemis,)
        self._hemispheres: Tuple[str, ...] = (
            tuple(str(h) for h in hemis)[:4] if len(hemis) >= 4
            else ('N', 'S', 'E', 'W'))

    # ── translation ──────────────────────────────────────────────────────────
    def _t(self, key: str, **values: Any) -> str:
        """The [Texts] translation for key (gettext-style: the English
        string IS the key, a missing entry falls back to it), escaped for
        markup, then {name} placeholders filled from values.  Call sites
        always pass the key as a single-line literal: the test suite reads
        them from this source file to enforce that lang/en.conf ships
        exactly the keys that render, in both directions."""
        s = self._texts.get(key, key)
        if not isinstance(s, str):
            s = key
        s = _esc(s)
        if not values:
            return s
        try:
            return s.format(**values)
        except (KeyError, IndexError, ValueError):
            # A translation with broken placeholders must not blank the
            # panel (the guard would eat the whole SVG): fall back to the
            # English key, which the tests guarantee formats.
            return _esc(key).format(**values)

    @staticmethod
    def _label(alm, name: str) -> str:
        """The body's display name, unescaped: the report's [Almanac]
        texts (the same source $almanac.<body>.label reads), else the
        English name.  Read straight off the almanac's texts so the page
        keeps rendering when a non-Skyfield almanac serves it."""
        val = _wxskyfield().almanac_texts(alm).get(name)
        if isinstance(val, str):
            return val
        return name.replace('_', ' ').title()

    def _cardinals(self, alm) -> Tuple[str, str, str, str]:
        """The report's N, E, S, W, from the formatter's [Units]
        [[Ordinates]] directions -- the core-standard translated compass."""
        try:
            o = alm.formatter.ordinate_names
            return str(o[0]), str(o[4]), str(o[8]), str(o[12])
        except Exception:
            return 'N', 'E', 'S', 'W'

    def _dur(self, seconds: Optional[float]) -> str:
        if seconds is None:
            return '&#8212;'
        return self._t('{h}h {m}m', h=int(seconds // 3600),
                       m='%02d' % int(seconds % 3600 // 60))

    def _date(self, ts: float) -> str:
        """A short panel date.  The strftime format itself is a [Texts]
        key, so a language reorders it (day-month for Danish or German);
        the month and weekday NAMES come from strftime, i.e. the weewxd
        process locale, like the panels' month axis labels."""
        return time.strftime(self._t('%b %-d'), time.localtime(ts))

    def _date_hm(self, ts: Optional[float]) -> str:
        """A short panel date with its clock time, em-dash when unknown."""
        return '%s %s' % (self._date(ts), _t_hm(ts)) if ts else '&#8212;'

    # ── shared data access (plain $almanac tags) ─────────────────────────────
    def _body(self, alm, name: str) -> Dict[str, Any]:
        key = (alm.time_ts, name)
        if key in self._memo:
            return self._memo[key]
        b = getattr(alm, name)
        try:
            mag: Optional[float] = b.mag
        except AttributeError:
            # A comet row without g/k parameters serves no magnitude at
            # all; renderers show a dash.
            mag = None
        d: Dict[str, Any] = {
            'name': name, 'az': b.az, 'alt': b.alt, 'mag': mag,
            'rise': _raw(b.rise, 'unix_epoch'), 'set': _raw(b.set, 'unix_epoch'),
            'transit': _raw(b.transit, 'unix_epoch'),
            'visible': _raw(b.visible, 'second'),
            'circumpolar': bool(b.circumpolar), 'neverup': bool(b.neverup),
            'dist_au': b.earth_distance,
        }
        # The constellation tag can legitimately be unserved (the boundary
        # map failed to load and there is no PyEphem to fall through to);
        # that must cost the chip its constellation, not the page its panels.
        # .label is the translated display name (the report's [Almanac]
        # [[Constellations]] entry, else Latin); an almanac serving the tag
        # as a plain string shows it untranslated rather than lose the chip.
        try:
            c = b.constellation
            d['constellation'] = str(getattr(c, 'label', c))
        except Exception:
            d['constellation'] = None
        if name != 'moon':
            d['elong'] = b.elong
        if name not in ('sun', 'moon'):
            d['hlong'] = b.hlong
        self._memo[key] = d
        return d

    def _twilight(self, alm) -> Dict[str, Optional[float]]:
        key = (alm.time_ts, '_twilight')
        if key in self._memo:
            return self._memo[key]
        tw: Dict[str, Optional[float]] = {}
        for label, hz in (('civil', -6), ('nautical', -12), ('astro', -18)):
            a = alm(horizon=hz)
            tw[label + '_dawn'] = _raw(a.sun(use_center=1).rise, 'unix_epoch')
            tw[label + '_dusk'] = _raw(a.sun(use_center=1).set, 'unix_epoch')
        self._memo[key] = tw
        return tw

    def _stars(self, alm, limit: float) -> List[Dict[str, Any]]:
        sky = _find_sky()
        if sky is None or not sky.stars:
            return []
        catalog = self._catalog_stars(alm, sky, limit)
        if catalog is not None:
            return catalog
        seen, out = set(), []
        for name, hip in _wxskyfield().NAMED_STARS.items():
            if hip in seen or name not in sky.stars:
                continue
            mag = sky.stars[name][1]
            if mag is None or (mag > limit and name != 'polaris'):
                continue
            seen.add(hip)
            b = getattr(alm, name)
            alt = b.alt
            if alt <= 0:
                continue
            out.append({'name': self._label(alm, name), 'named': True,
                        'az': b.az, 'alt': alt, 'mag': mag})
        return out

    def _catalog_stars(self, alm, sky, limit: float) -> Optional[List[Dict[str, Any]]]:
        """The chart's stars from the full Hipparcos catalog: every
        catalog star above the horizon at least `limit` bright,
        dimmest first so the bright dots paint on top.  Stars with a
        NAMED_STARS name keep their translated label; the rest are
        anonymous dots whose tooltip names the Hipparcos number.  None
        when the catalog is unreadable -- the chart then falls back to
        the named stars."""
        amt = _find_almanac_type()
        if amt is None:
            return None
        field = amt.star_field(alm, limit)
        if field is None:
            return None
        names = _hip_names()
        out = []
        for hip, az, alt, mag in field:
            name = names.get(hip)
            out.append({'name': self._label(alm, name) if name else 'HIP %d' % hip,
                        'named': name is not None,
                        'az': az, 'alt': alt, 'mag': mag})
        polaris_hip = _wxskyfield().NAMED_STARS.get('polaris')
        if not any(hip == polaris_hip for hip, _az, _alt, _mag in field):
            # The named-star dome shows Polaris regardless of the limit --
            # the pole star anchors the chart; keep that promise here.
            mag = sky.stars.get('polaris', (None, None))[1]
            b = getattr(alm, 'polaris')
            if mag is not None and b.alt > 0:
                out.append({'name': self._label(alm, 'polaris'), 'named': True,
                            'az': b.az, 'alt': b.alt, 'mag': mag})
        out.sort(key=lambda s: -s['mag'])
        return out

    def _constellation_layer(self, alm, cx: float, cy: float, R: float
                             ) -> Tuple[List[str], List[Tuple[float, float, str]]]:
        """The dome's constellation figures: the line segments as SVG
        polyline fragments (projected but unclipped -- the caller wraps
        them in the dome's clipPath, which trims a setting figure at the
        rim), and a (x, y, name) label for each constellation at least
        half risen, anchored at the centroid of its visible stars.  A
        vertex missing from the field drops only the segments touching
        it; a segment is drawn when both endpoints are at least
        CON_ALT_FLOOR high and at least one is above the horizon --
        both-below chords would otherwise cut across the dome even
        though the segment is below the horizon its whole length."""
        amt, sky = _find_almanac_type(), _find_sky()
        if amt is None or sky is None:
            return [], []
        polylines = sky.constellation_lines()
        field = amt.constellation_field(alm) if polylines else None
        if not polylines or not field:
            return [], []
        segs: List[str] = []
        vis: Dict[str, Dict[int, Tuple[float, float]]] = {}
        tot: Dict[str, set] = {}
        for abbr, hips in polylines:
            tot.setdefault(abbr, set()).update(hips)
            pts: List[Optional[Tuple[float, float, float]]] = []
            for hip in hips:
                azalt = field.get(hip)
                if azalt is None or azalt[1] < CON_ALT_FLOOR:
                    pts.append(None)
                    continue
                x, y = self._dome_xy(cx, cy, R, azalt[0], azalt[1])
                pts.append((x, y, azalt[1]))
                if azalt[1] > 0.0:
                    vis.setdefault(abbr, {})[hip] = (x, y)
            run: List[Tuple[float, float, float]] = []
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if a is not None and b is not None and max(a[2], b[2]) > 0.0:
                    if not run:
                        run.append(a)
                    run.append(b)
                elif run:
                    segs.append(self._con_polyline(run))
                    run = []
            if run:
                segs.append(self._con_polyline(run))
        labels: List[Tuple[float, float, str]] = []
        con_names = _wxskyfield().almanac_texts(alm).get('Constellations')
        if not isinstance(con_names, dict):
            con_names = {}
        latin = _wxskyfield().CONSTELLATION_NAMES
        for abbr, seen in vis.items():
            # Label constellations substantially risen: rising and setting
            # figures keep their lines, but a name centered on a sliver of
            # a figure would crowd the rim.
            if len(seen) < 2 or 2 * len(seen) < len(tot[abbr]):
                continue
            name = str(con_names.get(abbr, latin.get(abbr, abbr)))
            xs = [xy[0] for xy in seen.values()]
            ys = [xy[1] for xy in seen.values()]
            labels.append((sum(xs) / len(xs), sum(ys) / len(ys), name))
        return segs, labels

    @staticmethod
    def _con_polyline(run: List[Tuple[float, float, float]]) -> str:
        return ('<polyline points="%s"/>'
                % ' '.join('%.1f,%.1f' % (pt[0], pt[1]) for pt in run))

    # ── satellites ───────────────────────────────────────────────────────────
    def satellite_names(self) -> List[str]:
        """The configured satellites' tag names ([Skyfield] [[Satellites]]),
        in config order, from the registered engine.  Empty when none are
        configured or the Skyfield almanac is not registered.  PUBLIC
        CONTRACT: embedding skins enumerate the satellites through this
        (weewx-celestial builds its live roster and satellite layer from
        it -- celestial 8.0), so the name and semantics are stable."""
        sky = _find_sky()
        return list(sky.satellites) if sky is not None else []

    @_panel_guard(fallback=False)
    def has_satellites(self) -> bool:
        """Whether the page shows its satellite panel -- the template's
        guard: a station with no [[Satellites]] hides the section."""
        return bool(self.satellite_names())

    @_panel_guard(fallback=False)
    def can_draw(self) -> bool:
        """Whether this page can draw the sky at all: the Skyfield almanac
        is registered, so the dome, the pass chart and every body tag
        draw from it; False on a lesser tier (PyEphem, the built-in
        almanac), where dome_svg comes back empty.  PUBLIC CONTRACT like
        satellite_names: weewx-celestial 9.0 gates the panels it places
        beside the dome on this, so a page showing only a satellite
        roster or the pass chart need not draw a dome to learn whether
        it could.  The engine-dependent panels ask the same
        _have_engine(), so False here is exactly the tier on which they
        decline."""
        return _have_engine()

    def comet_names(self) -> List[str]:
        """The configured comets' tag names ([Skyfield] [[Comets]]), in
        config order, from the registered engine.  Empty when none are
        configured or the Skyfield almanac is not registered.  PUBLIC
        CONTRACT like satellite_names: embedding skins enumerate the
        comets through this, so the name and semantics are stable."""
        sky = _find_sky()
        return list(sky.comets) if sky is not None else []

    def _comet_pos(self, alm, name: str) -> Dict[str, Any]:
        """The comet's place and magnitude for the dome -- deliberately
        NOT _body(): its rise/set/visible reads would cost day-window
        searches per comet per render for marks the dome doesn't need.
        alt/az are None when the comet has no elements (the marker simply
        does not plot); mag is None when the MPC row carries no g/k
        parameters (drawn as fainter than naked-eye)."""
        key = (alm.time_ts, 'comet:' + name)
        if key in self._memo:
            return self._memo[key]
        b = getattr(alm, name)
        try:
            mag: Optional[float] = b.mag
        except AttributeError:
            mag = None
        d = {'alt': b.alt, 'az': b.az, 'mag': mag}
        self._memo[key] = d
        return d

    def _sat_pass(self, alm, name: str) -> Dict[str, Any]:
        """The satellite's next visible pass as plain numbers ('pass', None
        when there is none in the elements' validity window) -- 'usable'
        then says whether that is honest sky truth (a satellite that just
        never qualifies, HST from high latitudes) or missing/stale
        elements, which point at the log instead."""
        key = (alm.time_ts, 'sat:' + name)
        if key in self._memo:
            return self._memo[key]
        b = getattr(alm, name)
        p = b.next_visible_pass
        rise = _raw(p.rise, 'unix_epoch')
        d: Dict[str, Any] = {'usable': b.sunlit is not None, 'pass': None}
        if rise is not None:
            d['pass'] = {
                'rise': rise,
                'culmination': _raw(p.culmination, 'unix_epoch'),
                'set': _raw(p.set, 'unix_epoch'),
                'max_alt': _raw(p.max_altitude, 'degree_angle'),
                'rise_ord': str(p.rise_azimuth.ordinal_compass()),
                'culm_ord': str(p.culmination_azimuth.ordinal_compass()),
                'set_ord': str(p.set_azimuth.ordinal_compass()),
                'duration': _raw(p.duration, 'second'),
            }
        self._memo[key] = d
        return d

    def _satellite_track(self, alm) -> Optional[Dict[str, Any]]:
        """The pass chart's arc: the soonest upcoming visible pass among
        the configured satellites, sampled along its path (a pass in
        progress counts -- its rise is simply in the past).  One track
        only: the next thing worth watching; several arcs would be
        clutter."""
        best: Optional[str] = None
        for name in self.satellite_names():
            q = self._sat_pass(alm, name)['pass']
            if q is not None and (best is None or
                                  q['rise'] < self._sat_pass(alm, best)['pass']['rise']):
                best = name
        if best is None:
            return None
        q = dict(self._sat_pass(alm, best)['pass'])
        n = 24
        pts: List[Tuple[float, float]] = []
        for i in range(n + 1):
            ts = q['rise'] + (q['set'] - q['rise']) * i / n
            b = getattr(alm(almanac_time=int(round(ts))), best)
            alt, az = b.alt, b.az
            if alt is None or az is None:
                return None
            pts.append((az, alt))
        q.update(name=best, label=self._label(alm, best), pts=pts,
                 culm_i=min(n, max(0, round(n * (q['culmination'] - q['rise'])
                                            / (q['set'] - q['rise'])))))
        return q

    # ── template conveniences ─────────────────────────────────────────────────
    @_panel_guard(fallback=False, needs=TIER_EXTRAS)
    def sun_is_up(self, alm) -> bool:
        return bool(self._body(alm, 'sun')['alt'] > 0)

    @_panel_guard(fallback='dark')
    def theme(self, alm) -> str:
        """The page's resolved theme, 'dark' or 'light', from the report's
        theme option (dark | light | auto; default dark).  auto follows the
        sun at generation time: light while it is up, dark otherwise.  The
        page regenerates each report cycle, so the auto flip lags
        sunrise/sunset by at most one archive interval.  The theme is
        resolved once, at generation: this option cannot follow a reader
        who flips a control in the browser.  Since 2.4 that is only the
        DEFAULT, though -- the marks carry role classes and a consuming
        skin's stylesheet can repaint them per viewer (see _style_block
        and docs/panels.md).

        A classic-* value is accepted here and drawn as the plate that
        replaced it (2.3).  Strictly it never WAS a legal theme -- the
        classic names were palette arguments a template passed to a panel,
        never a report option -- but a station that reached for one after
        reading about the palettes deserves the same warning-and-carry-on
        the palette argument gets, not a page that fails to render."""
        if self._theme_conf in THEME_ALIASES:
            if ('theme', self._theme_conf) not in _warned_palettes:
                _warned_palettes.add(('theme', self._theme_conf))
                # NOT necessarily [[SkyfieldReport]]: the option comes from
                # whichever report built this SkyPage, which for an
                # embedding skin is that skin's own stanza.
                log.warning("theme %r was dropped in 2.3 and is being drawn "
                            "as %r; set theme = %s in the report stanza that "
                            "sets it.", self._theme_conf,
                            THEME_ALIASES[self._theme_conf],
                            THEME_ALIASES[self._theme_conf])
            return THEME_ALIASES[self._theme_conf]
        if self._theme_conf not in ('auto', 'dark', 'light'):
            raise SkyPageUsageError('unknown theme %r; valid themes: auto, dark, light'
                                    % self._theme_conf)
        if self._theme_conf == 'auto':
            return 'light' if self.sun_is_up(alm) else 'dark'
        return self._theme_conf

    @_panel_guard(fallback='night')
    def palette(self, alm) -> str:
        """The palette name matching .theme -- 'light' on the light theme,
        'night' otherwise -- for the template to hand every panel call."""
        return 'light' if self.theme(alm) == 'light' else 'night'

    @_panel_guard()
    def header_sub(self, alm, palette: str = 'night') -> str:
        _palette(palette)
        lat, lon = alm.lat, alm.lon
        hemi = self._hemispheres
        return '%.2f&#176; %s &#183; %.2f&#176; %s &#183; %s' % (
            abs(lat), _esc(hemi[0] if lat >= 0 else hemi[1]),
            abs(lon), _esc(hemi[2] if lon >= 0 else hemi[3]),
            time.strftime(self._t('%A, %B %-d %Y, %-H:%M %Z'),
                          time.localtime(alm.time_ts)))

    @_panel_guard()
    def footer_html(self) -> str:
        """The footer credit line, true for what actually computed the page.
        The full Skyfield/DE421/Hipparcos credit appears only when the
        registered Skyfield almanac and its star catalog are live; a stars
        problem or an unregistered almanac (the page then renders off the
        built-in almanac's fall-through) is named instead, with a pointer at
        the weewxd log -- the footer doubles as a diagnostic.  The ESA
        acknowledgment is required exactly when Hipparcos data is shown,
        and the Stellarium credit (its skyculture data draws the dome's
        constellation figures, CC BY-SA 4.0) exactly when the figures are:
        the option on and the lines file loaded -- a failed load draws
        nothing and credits nothing.
        The extension's name becomes a link to the project page: it is a
        proper noun every translation keeps verbatim, so the substitution
        is done after translation (a translation that dropped it would
        just render unlinked)."""
        sep = '<span class="sep">&#183;</span>'
        sky = _find_sky()
        if sky is None:
            parts = [self._t('Computed with the station’s built-in almanac'),
                     self._t('weewx-skyfield is not active — see the weewxd log'),
                     self._t('Regenerated every report cycle')]
        else:
            parts = [self._t('Computed with weewx-skyfield'),
                     self._t('Skyfield and the JPL DE421 ephemeris')]
            if sky.stars:
                parts += [self._t('IAU-CSN star names'),
                          self._t('Hipparcos star data Credit: ESA')]
                if self._constellation_lines and sky.constellation_lines():
                    parts.append(self._t('Constellation figures: Stellarium'))
            elif sky.stars_requested:
                parts.append(self._t('star catalog unavailable — see the weewxd log'))
            else:
                parts.append(self._t('star catalog disabled'))
            if sky.satellites:
                parts.append(self._t('Satellite elements: CelesTrak'))
            if sky.comets:
                parts.append(self._t('Comet elements: Minor Planet Center'))
            # The shower data is built in and the countdown row always
            # carries the next shower, so this credit is unconditional --
            # unlike the two element feeds, which a station can decline to
            # configure.
            parts.append(self._t('Meteor shower data: IMO'))
            parts.append(self._t('Regenerated every report cycle'))
        return sep.join(parts).replace(
            'weewx-skyfield', '<a href="%s">weewx-skyfield</a>' % REPO_URL)

    @_panel_guard(needs=TIER_EXTRAS)
    def countdown_html(self, alm, palette: str = 'night') -> str:
        _palette(palette)

        def when_str(ts: float) -> str:
            n = _days_until(alm.time_ts, ts)
            if n == 0:
                # The one case where the day count alone leaves the reader
                # worse off: on the day itself, "today" does not say whether
                # the event is still ahead.  The clock time is the fact that
                # matters exactly when interest is highest, and it is the
                # only thing the chip does not already carry (the line above
                # is the date).  One phrase, not "today" + "at" + the clock:
                # word order is the translator's to choose, and a lone "at"
                # is a fragment no one can translate in isolation.
                # Jacques Terrettaz's follow-up on issue #6.
                return self._t('today at {time}', time=_t_hm(ts))
            if n == 1:
                return self._t('in {n} day', n=1)
            return self._t('in {n} days', n=n)

        chips = []
        for label, vh in ((self._t('new moon'), alm.next_new_moon),
                          (self._t('full moon'), alm.next_full_moon),
                          (self._t('equinox'), alm.next_equinox),
                          (self._t('solstice'), alm.next_solstice)):
            ts = _raw(vh, 'unix_epoch')
            if ts is None:
                continue
            chips.append('<div class="count"><span class="k">%s</span>'
                         '<span class="v mono">%s</span><span class="d">%s</span></div>'
                         % (label, self._date(ts), when_str(ts)))
        # The next eclipse visible from the station, via the combined tag
        # (which already picks the sooner of lunar/solar).  Unlike the
        # chips above, an eclipse can be years out, so its date carries
        # the year.  A tag failure (e.g. a non-Skyfield almanac serving
        # the page) drops this chip, not the row.
        eclipse = None
        try:
            ts = _raw(alm.next_eclipse, 'unix_epoch')
            if ts is not None:
                eclipse = (ts, str(alm.next_eclipse_kind), str(alm.next_eclipse_type))
        except Exception:
            pass
        if eclipse is not None:
            ts, kind, etype = eclipse
            # The tags serve English data (loopdata consumers rely on it);
            # the panel translates on display.
            kind_label = (self._t('lunar eclipse') if kind == 'lunar'
                          else self._t('solar eclipse'))
            type_label = {'penumbral': self._t('penumbral'),
                          'partial': self._t('partial'),
                          'total': self._t('total'),
                          'annular': self._t('annular')}.get(etype, _esc(etype))
            chips.append('<div class="count"><span class="k">%s</span>'
                         '<span class="v mono">%s</span><span class="d">%s &#183; %s</span></div>'
                         % (kind_label,
                            time.strftime(self._t('%b %-d %Y'), time.localtime(ts)),
                            type_label, when_str(ts)))
        # The next major meteor shower -- always: there is always a next
        # one, rolling to the following shower as each peak passes.  The
        # detail line carries the moon's interference judgment for the
        # peak night (a bright moon washes out the faint meteors), the
        # almanac-quality half of the chip.  A tag failure drops the
        # chip, not the row.
        try:
            shower = alm.next_meteor_shower
            shower_ts = _raw(shower.peak, 'unix_epoch')
        except Exception:
            shower, shower_ts = None, None
        if shower is not None and shower_ts is not None:
            moon_pct = int(round(alm(almanac_time=shower_ts).moon.phase))
            chips.append('<div class="count"><span class="k">%s</span>'
                         '<span class="v mono">%s</span><span class="d">%s &#183; %s</span></div>'
                         % (_esc(shower.label), self._date(shower_ts),
                            when_str(shower_ts),
                            self._t('moon {pct}%', pct=moon_pct)))
        # A configured comet's perihelion, when it lies ahead within the
        # countdown window -- the news-cycle chip.  Halley's 2061 date
        # stays quiet until its time comes; a past perihelion
        # (Hale-Bopp's 1997) never shows.  A tag failure drops the chip,
        # not the row, like the eclipse chip above.
        for name in self.comet_names():
            try:
                ts = _raw(getattr(alm, name).perihelion, 'unix_epoch')
            except Exception:
                ts = None
            if ts is None or not (0.0 <= ts - alm.time_ts <= COMET_PERIHELION_COUNTDOWN_S):
                continue
            chips.append('<div class="count"><span class="k">%s</span>'
                         '<span class="v mono">%s</span><span class="d">%s</span></div>'
                         % (self._t('{name} perihelion',
                                    name=_esc(self._label(alm, name))),
                            self._date(ts), when_str(ts)))
        return '\n'.join(chips)

    # ── moon disc ─────────────────────────────────────────────────────────────
    def _moon_disc(self, alm, cx: float, cy: float, R: float,
                   ring: bool = True) -> str:
        frac = alm.moon.phase / 100.0
        waxing = alm.moon_index <= 3
        # Northern hemisphere: waxing is lit on the west (right); flip south.
        lit_left = (not waxing) if alm.lat >= 0 else waxing
        rx = abs(2.0 * frac - 1.0) * R
        limb_sweep = 0 if lit_left else 1
        if frac >= 0.5:
            term_sweep = 0 if lit_left else 1    # terminator bulges into the dark side
        else:
            term_sweep = 1 if lit_left else 0    # crescent: bulges into the lit side
        path = ('M %.1f %.1f A %.1f %.1f 0 0 %d %.1f %.1f A %.1f %.1f 0 0 %d %.1f %.1f Z'
                % (cx, cy - R, R, R, limb_sweep, cx, cy + R,
                   rx, R, term_sweep, cx, cy - R))
        out = ['<circle cx="%.1f" cy="%.1f" r="%.1f" class="sky-fill-moon-dark"/>'
               % (cx, cy, R),
               '<path d="%s" class="sky-fill-moon-lit"/>' % path]
        if ring:
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" '
                       'class="sky-stroke-moon-ring" stroke-width="1"/>'
                       % (cx, cy, R))
        return ''.join(out)

    @_panel_guard(needs=TIER_EXTRAS)
    def moon_svg(self, alm, size: int = 76, palette: str = 'night') -> str:
        pal_name, _pal = _resolve_palette(palette)
        c = size / 2.0
        return _svg_out([_svg_open('width="%d" height="%d" viewBox="0 0 %d %d" '
                                   'aria-label="%s"'
                                   % (size, size, size, size, self._t('Moon phase')),
                                   pal_name),
                         self._moon_disc(alm, c, c, c - 4),
                         '</svg>'], pal_name)

    @_panel_guard(needs=TIER_EXTRAS)
    def moonset_html(self, alm) -> str:
        """The moon card's moonset line, or nothing when the almanac
        serving the page has no moonset to give.

        In Python rather than in the template because the template cannot
        guard it: the moon card used to read $almanac.moon.set directly,
        and on a station whose almanac serves no body binder that raised
        through Cheetah and took the WHOLE page with it -- not the line,
        the page.  A Cheetah #try does not help, because the <div> is
        already written to the output stream by the time the tag fails,
        which would leave the markup unbalanced.  The value keeps the
        ValueHelper's own .format(), so the rendered text is unchanged
        wherever it rendered before."""
        return ('<div class="mpct mono">%s</div>'
                % self._t('moonset {time}', time=alm.moon.set.format("%H:%M")))

    # ── sky dome ─────────────────────────────────────────────────────────────
    @staticmethod
    def _dome_xy(cx: float, cy: float, R: float, az: float, alt: float) -> Tuple[float, float]:
        r = R * (90.0 - alt) / 90.0
        a = math.radians(az)
        return cx - r * math.sin(a), cy - r * math.cos(a)

    @_panel_guard(needs=TIER_ENGINE)
    def dome_svg(self, alm, palette: str = 'night', label_scale: float = 1.0,
                 label_layers: Optional[Sequence[Tuple[Any, Any]]] = None) -> str:
        """label_scale grows every dome label (stars, bodies, cardinals, ring
        degrees) by that factor -- font sizes are emitted inline so the
        collision layout always matches the rendered size.  Useful for skins
        whose pages are scaled down (fixed-canvas smartphone layouts).

        label_layers adds further label layers, [(scale, media_query),
        ...], for a page that serves more than one layout from one URL:
        the marks are drawn once and the labels laid out once per scale,
        each layout in its own `<g class="dome-labels" data-label-scale=
        ...>`, and the chart's own <style> shows the layer whose media
        query the reader's viewport matches (the base layer otherwise).
        Nothing fetches and nothing scripts.  See _label_layers for what
        a query may contain and _layer_rules for how a layer is picked."""
        pal_name, pal = _resolve_palette(palette)
        return self._sky_chart(alm, pal, pal_name,
                               _label_layers(label_scale, label_layers),
                               self._star_mag_limit, self._star_label_mag,
                               track=None, grad_id='skyg-%s' % pal_name,
                               clip_id='domec-%s' % pal_name,
                               aria=self._t('Sky dome chart'))

    def _sky_chart(self, alm, pal: Dict[str, Any], pal_name: str,
                   layers: List[Tuple[float, Optional[str]]],
                   star_limit: float, star_label_mag: float,
                   track: Optional[Dict[str, Any]], grad_id: str, clip_id: str,
                   aria: str) -> str:
        """The all-sky chart core shared by the dome (the sky at the
        almanac's time) and the pass chart (the sky at a pass's
        culmination): frame, stars, constellation figures, bodies, and any
        configured satellite above the horizon at the chart's epoch.
        `track` adds the satellite pass arc -- the pass chart's reason to
        exist; the dome stopped drawing it in 2.0, because an undated
        future track on the now-sky read as tonight's.

        grad_id/clip_id keep the charts' SVG ids distinct on the one page,
        and every caller ENDS THEM WITH THE PLATE NAME, because an id is
        global to the HTML document and the FIRST element wins every
        `url(#id)` in it.  Two dome_svg calls on one page both said `skyg`
        through 2.4's first cut, so a light dome placed after a night one
        painted its sky with the night gradient -- navy, under light-plate
        stars.  Deriving the id from the plate is what makes that safe, and
        two charts of the SAME plate may share an id precisely because they
        would define identical gradients.  A `<style>` block has the same
        document-wide reach and is handled the same way, by scoping every
        rule to the plate class (see _style_block).

        `layers` is the label layers to lay out (_label_layers), base
        first.  Every label the chart carries -- cardinals, ring figures,
        body, satellite, comet and radiant names, the pass arc's times and
        name, star names, constellation names -- is REQUESTED into
        `labels` in placement order as the marks are drawn, and placed by
        _place_labels once per layer, each layout with its own collision
        list, because where a label fits depends on how big it is.  The
        marks are drawn once and shared by every layer.  The order of the
        requests is the layout: a must-place label is nudged clear of the
        ones before it, and a star or constellation name is dropped when
        anything placed earlier is in the way."""
        S, cx, cy, R = 680, 340, 348, 296
        sun = self._body(alm, 'sun')
        star_op = (STAR_OPACITY_SUN_UP if sun['alt'] > 0
                   else STAR_OPACITY_DARK)
        p = [_svg_open('viewBox="0 0 %d 706" role="img" aria-label="%s"%s'
                       % (S, aria, _layer_attrs(layers)), pal_name)]
        p.append('<defs><radialGradient id="%s">%s</radialGradient>'
                 '<clipPath id="%s"><circle cx="%d" cy="%d" r="%d"/></clipPath></defs>'
                 % (grad_id,
                    ''.join('<stop offset="%s" class="sky-dome-stop-%d"/>'
                            % (offset, i)
                            for i, (offset, _c) in enumerate(pal['dome_stops'], 1)),
                    clip_id, cx, cy, R))
        p.append('<circle cx="%d" cy="%d" r="%d" fill="url(#%s)"/>' % (cx, cy, R, grad_id))
        # The altitude rings and the two diameters through the zenith -- the
        # meridian north to south, the prime vertical east to west; the
        # horizon is the rim, not either of these -- read against the dome
        # gradient, not against a panel edge, so they take the palette's
        # own `grid` rather than `line` (the section-border color, which on
        # both plates is within a hair of the dome's own luminance -- 1.07:1
        # on the night plate, invisible).  Fixed in 2.2.
        for alt in (30, 60):
            p.append('<circle cx="%d" cy="%d" r="%.1f" fill="none" '
                     'class="sky-stroke-grid" '
                     'stroke-width="1" stroke-dasharray="3 5" opacity="%s"/>'
                     % (cx, cy, R * (90 - alt) / 90.0, DOME_RING_OPACITY))
        for x1, y1, x2, y2 in ((cx - R, cy, cx + R, cy), (cx, cy - R, cx, cy + R)):
            p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" '
                     'class="sky-stroke-grid" stroke-width="1" opacity="%s"/>'
                     % (x1, y1, x2, y2, DOME_CROSS_OPACITY))
        p.append('<circle cx="%d" cy="%d" r="%d" fill="none" '
                 'class="sky-stroke-dome-rim" stroke-width="1.5"/>'
                 % (cx, cy, R))
        # The chrome labels go first: they are always placed, and seed the
        # collision list so every later label dodges them.
        labels: List[Tuple[Any, ...]] = []
        c_n, c_e, c_s, c_w = self._cardinals(alm)
        for label, dx, dy, anch in ((c_n, 0, -R - 12, 'middle'), (c_s, 0, R + 22, 'middle'),
                                    (c_e, -R - 14, 5, 'end'), (c_w, R + 14, 5, 'start')):
            labels.append(('cardinal', cx + dx, cy + dy, anch, _esc(label)))
        labels.append(('ring', cx + 6 + R / 3.0, cy - 6, '30&#176;'))
        labels.append(('ring', cx + 8 + R * 2 / 3.0, cy - 6, '60&#176;'))
        con_labels: List[Tuple[float, float, str]] = []
        if self._constellation_lines:
            segs, con_labels = self._constellation_layer(alm, cx, cy, R)
            if segs:
                p.append('<g clip-path="url(#%s)" fill="none" '
                         'class="sky-stroke-conline" '
                         'stroke-width="1" stroke-linecap="round" opacity="%.2f">%s</g>'
                         % (clip_id,
                            CONLINE_OPACITY_SUN_UP if sun['alt'] > 0
                            else CONLINE_OPACITY_DARK,
                            ''.join(segs)))
        # Labels are placed after every mark is drawn: body labels first (each
        # nudged vertically until it clears the ones already placed), then
        # star labels, which are simply dropped on a collision -- their dots
        # keep the hover title.  Bunched-up bodies (planets crowd the ecliptic)
        # otherwise print over each other.  The layout itself is
        # _place_labels; a mark's label is requested here, beside its mark.
        # Every body mark is a keep-out box for the labels, seeded before any
        # label is placed: a label over a disc reads against the disc, not
        # the sky -- a planet's name over the noon sun measured 1.09:1.  In
        # chart units, and not scaled with the labels, because the marks
        # are not.  Each half-size covers the mark's stroke (the sun's, its
        # rays) and is smaller than the gap its own label is set at.
        keep: List[Tuple[float, float, float, float]] = []

        def _keep(x: float, y: float, half: float) -> None:
            keep.append((x - half, y - half, x + half, y + half))

        def _want(x: float, y: float, text: str, cls: str, gap: float,
                  must: bool, body: Optional[str] = None) -> None:
            labels.append(('mark', x, y, text, cls, gap, must, body))

        star_labels: List[Tuple[float, float, str]] = []
        for s in self._stars(alm, star_limit):
            x, y = self._dome_xy(cx, cy, R, s['az'], s['alt'])
            r = max(1.0, min(4.0, 3.2 - 0.62 * s['mag']))
            p.append('<circle cx="%.1f" cy="%.1f" r="%.1f" class="sky-fill-ink" '
                     'opacity="%.2f">'
                     '<title>%s</title></circle>'
                     % (x, y, r, star_op,
                        self._t('{name} — alt {alt}°, az {az}°, mag {mag}',
                                name=_esc(s['name']), alt='%.1f' % s['alt'],
                                az='%.1f' % s['az'], mag='%.2f' % s['mag'])))
            if s['named'] and s['mag'] <= star_label_mag:
                star_labels.append((x, y - 8, _esc(s['name'])))
        # Body marks and their labels carry data-body="<tag name>" (groups
        # classed dome-body): a consumer contract -- weewx-celestial's live
        # dome locates marks through it to reposition them between report
        # cycles.  The <title> text is translated and cannot serve.
        for name in PLANETS:
            b = self._body(alm, name)
            if b['alt'] <= 0:
                continue
            x, y = self._dome_xy(cx, cy, R, b['az'], b['alt'])
            label = self._label(alm, name)
            p.append('<g class="dome-body" data-body="%s">'
                     '<circle cx="%.1f" cy="%.1f" r="5.5" '
                     'class="sky-fill-body-%s sky-stroke-ring-%s" stroke-width="2">'
                     '<title>%s</title></circle></g>'
                     % (_esc(name), x, y, name, name,
                        self._t('{name} — alt {alt}°, az {az}°, mag {mag}',
                                name=_esc(label), alt='%.1f' % b['alt'],
                                az='%.1f' % b['az'], mag='%.1f' % b['mag'])))
            _keep(x, y, 6.5)
            _want(x, y, _esc(label), 'bodylab', 8, must=True, body=name)
        if sun['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, sun['az'], sun['alt'])
            p.append('<g class="dome-body" data-body="sun">')
            for i in range(8):
                a = math.pi * i / 4
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'class="sky-stroke-body-sun" stroke-width="1.5"/>'
                         % (x + 11 * math.cos(a), y + 11 * math.sin(a),
                            x + 16 * math.cos(a), y + 16 * math.sin(a)))
            p.append('<circle cx="%.1f" cy="%.1f" r="9" '
                     'class="sky-fill-body-sun sky-stroke-ring-sun" stroke-width="1.5">'
                     '<title>%s</title></circle></g>'
                     % (x, y,
                        self._t('{name} — alt {alt}°, az {az}°',
                                name=_esc(self._label(alm, 'sun')),
                                alt='%.1f' % sun['alt'], az='%.1f' % sun['az'])))
            _keep(x, y, 17.0)
            _want(x, y, _esc(self._label(alm, 'sun')), 'bodylab', 19, must=True,
                       body='sun')
        moon = self._body(alm, 'moon')
        if moon['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, moon['az'], moon['alt'])
            p.append('<g class="dome-body" data-body="moon">%s<title>%s</title></g>'
                     % (self._moon_disc(alm, x, y, 8, ring=False),
                        self._t('{name} — alt {alt}°, az {az}°, {pct}% illuminated',
                                name=_esc(self._label(alm, 'moon')),
                                alt='%.1f' % moon['alt'], az='%.1f' % moon['az'],
                                pct='%d' % alm.moon_fullness)))
            _keep(x, y, 8.5)
            _want(x, y, _esc(self._label(alm, 'moon')), 'bodylab', 12, must=True,
                       body='moon')
        # Satellites: a marker for any satellite above the horizon at the
        # chart's epoch -- the "sky at time T" contract.  On the pass
        # chart, whose epoch is the pass's culmination, this is what puts
        # the tracked satellite's dot at the peak of its arc.  A marker's
        # name label doubles as the arc's when the tracked satellite is
        # the one overhead.  A sunlit satellite is the solid brass dot; one
        # inside Earth's shadow inverts to a hollow ring (the open-symbol
        # convention for present-but-not-shining -- unlike a daytime star,
        # a shadowed satellite emits nothing).  The ring keeps the marker's
        # footprint, and its interior is the halo color rather than
        # fill="none" so the tooltip still triggers anywhere on the dot.
        overhead: List[str] = []
        for name in self.satellite_names():
            binder = getattr(alm, name)
            s_alt, s_az = binder.alt, binder.az
            if s_alt is None or s_alt <= 0:
                continue
            overhead.append(name)
            x, y = self._dome_xy(cx, cy, R, s_az, s_alt)
            label = self._label(alm, name)
            lit = binder.sunlit is not False
            if lit:
                title = self._t('{name} — alt {alt}°, az {az}°',
                                name=_esc(label), alt='%.1f' % s_alt,
                                az='%.1f' % s_az)
            else:
                title = self._t('{name} — alt {alt}°, az {az}° — in shadow',
                                name=_esc(label), alt='%.1f' % s_alt,
                                az='%.1f' % s_az)
            fill_cls, ring_cls = (('sky-fill-brass', 'sky-stroke-halo') if lit
                                  else ('sky-fill-halo', 'sky-stroke-brass'))
            p.append('<g class="dome-body" data-body="%s" data-sunlit="%d">'
                     '<circle cx="%.1f" cy="%.1f" r="4" class="%s %s" stroke-width="2">'
                     '<title>%s</title></circle></g>'
                     % (_esc(name), 1 if lit else 0, x, y, fill_cls, ring_cls,
                        title))
            _keep(x, y, 5.0)
            _want(x, y, _esc(label), 'satlab', 8, must=True, body=name)
        # Comets: a diamond for any configured comet above the horizon --
        # always plotted and always labeled (the config list IS the
        # filter; star_mag_limit is a census cutoff for the unconfigured
        # star field, a different kind of population).  Solid brass when
        # plausibly naked-eye (mag <= COMET_NAKED_EYE_MAG), the hollow
        # ring otherwise -- the satellite in-shadow convention: present,
        # but you will not see it by eye.  data-bright mirrors the
        # data-sunlit hook for embedding skins.  A comet with no elements
        # serves alt None and simply does not plot.  The tail rays point
        # anti-sunward -- away from the sun's own projected chart point,
        # which serves as the direction anchor even when the sun is below
        # the horizon (the projection keeps working at negative
        # altitudes).
        sun_b = self._body(alm, 'sun')
        sun_xy = self._dome_xy(cx, cy, R, sun_b['az'], sun_b['alt'])
        for name in self.comet_names():
            c = self._comet_pos(alm, name)
            if c['alt'] is None or c['alt'] <= 0:
                continue
            x, y = self._dome_xy(cx, cy, R, c['az'], c['alt'])
            label = self._label(alm, name)
            bright = c['mag'] is not None and c['mag'] <= COMET_NAKED_EYE_MAG
            if c['mag'] is not None:
                title = self._t('{name} — alt {alt}°, az {az}°, mag {mag}',
                                name=_esc(label), alt='%.1f' % c['alt'],
                                az='%.1f' % c['az'], mag='%.1f' % c['mag'])
            else:
                title = self._t('{name} — alt {alt}°, az {az}°',
                                name=_esc(label), alt='%.1f' % c['alt'],
                                az='%.1f' % c['az'])
            fill_cls, ring_cls = (('sky-fill-brass', 'sky-stroke-halo') if bright
                                  else ('sky-fill-halo', 'sky-stroke-brass'))
            n = math.hypot(x - sun_xy[0], y - sun_xy[1])
            tail = (_comet_tail(x, y, (x - sun_xy[0]) / n, (y - sun_xy[1]) / n,
                                'sky-stroke-brass') if n > 1.0 else '')
            p.append('<g class="dome-body" data-body="%s" data-bright="%d">%s'
                     '<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f L%.1f %.1f Z"'
                     ' class="%s %s" stroke-width="2">'
                     '<title>%s</title></path></g>'
                     % (_esc(name), 1 if bright else 0, tail,
                        x, y - 5.0, x + 5.0, y, x, y + 5.0, x - 5.0, y,
                        fill_cls, ring_cls, title))
            _keep(x, y, 6.0)
            _want(x, y, _esc(label), 'satlab', 8, must=True, body=name)
        # Meteor-shower radiants: while a shower is active, a rayed mark
        # at the radiant when it stands above the horizon -- meteors
        # stream outward FROM this point, so the glyph is six short rays
        # diverging from a center dot.  The label yields when space is
        # tight (must=False): a radiant is an area of sky, not a body.
        # list() INSIDE the guard, not just the attribute read: WeeWX's
        # built-in almanac answers any unknown name with an AlmanacBinder
        # rather than raising, so the read succeeds and the iteration is
        # what fails.  Guarding only the read let a TypeError past and
        # blanked the whole dome.
        try:
            active_showers = list(alm.active_meteor_showers)
        except Exception:
            active_showers = []
        for shower in active_showers:
            if shower.radiant_alt is None or shower.radiant_alt <= 0:
                continue
            x, y = self._dome_xy(cx, cy, R, shower.radiant_az, shower.radiant_alt)
            peak_ts = _raw(shower.peak, 'unix_epoch')
            title = self._t('{name} radiant — ZHR {zhr}, peak {date}',
                            name=_esc(shower.label), zhr=shower.zhr,
                            date=self._date(peak_ts) if peak_ts else '&#8212;')
            rays = []
            for k in range(6):
                a = math.radians(60.0 * k + 15.0)
                rays.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                            'class="sky-stroke-brass" stroke-width="1.2" '
                            'opacity="0.8"/>'
                            % (x + 3.5 * math.cos(a), y + 3.5 * math.sin(a),
                               x + 9.0 * math.cos(a), y + 9.0 * math.sin(a)))
            p.append('<g class="dome-body radiant" data-body="%s">%s'
                     '<circle cx="%.1f" cy="%.1f" r="1.8" class="sky-fill-brass">'
                     '<title>%s</title></circle></g>'
                     % (_esc(shower.key), ''.join(rays), x, y, title))
            _keep(x, y, 9.5)
            _want(x, y, _esc(shower.label), 'satlab', 10, must=False,
                       body=shower.key)
        if track is not None:
            xy = [self._dome_xy(cx, cy, R, az, alt) for az, alt in track['pts']]
            # data-rise/data-set: the pass's own window, epoch seconds, on
            # the consumer-contract element -- the chart saying when the
            # pass it depicts begins and ends, the way the dome fragment
            # declares its own epoch (data-dome-ts).  weewx-celestial's
            # live sweep judges the chart against this rather than against
            # the loop feed's next_visible_pass, which rolls to the
            # FOLLOWING pass moments after this one sets: without the
            # chart's own times, a mark that had just ridden the arc to its
            # end was put back at the culmination -- mid-arc, under a header
            # naming the finished pass -- for up to the refetch interval
            # (celestial 8.3.3, from NOAA-21's 2026-08-15 capture).
            p.append('<g class="dome-track" data-body="%s" '
                     'data-rise="%d" data-set="%d" '
                     'clip-path="url(#%s)"><path d="M%s" fill="none" '
                     'class="sky-stroke-brass" '
                     'stroke-width="1.6" stroke-dasharray="6 4" opacity="0.9"/>'
                     '<title>%s</title></g>'
                     % (_esc(track['name']),
                        int(round(track['rise'])), int(round(track['set'])),
                        clip_id,
                        ' L'.join('%.1f %.1f' % pt for pt in xy),
                        self._t('{name} pass — {rise} → {set}, peak {alt}°',
                                name=_esc(track['label']), rise=_t_hm(track['rise']),
                                set=_t_hm(track['set']), alt='%.0f' % track['max_alt'])))
            for end_i, ts in ((0, track['rise']), (-1, track['set'])):
                x, y = xy[end_i]
                # The ends sit on the rim; nudge each time label toward the
                # dome's center so it stays inside, and log its box so the
                # remaining labels dodge it.
                away = math.hypot(cx - x, cy - y) or 1.0
                lx = x + 18.0 * (cx - x) / away
                ly = y + 18.0 * (cy - y) / away
                p.append('<circle cx="%.1f" cy="%.1f" r="2.2" class="sky-fill-brass"/>'
                         % (x, y))
                labels.append(('time', lx, ly, _t_hm(ts),
                               (cx - x) / away, (cy - y) / away))
            if track['name'] not in overhead:
                xc, yc = xy[track['culm_i']]
                _want(xc, yc, _esc(track['label']), 'satlab', 8, must=True,
                           body=track['name'])
        for x, y, name in star_labels:
            _want(x, y, name, 'starlab', 6, must=False)
        # Constellation names go last: background context that yields to
        # every body and star label (a collision simply drops the name --
        # its figure still shows).
        for x, y, name in con_labels:
            labels.append(('con', x, y, name))
        for scale, _query in layers:
            p.append(self._place_labels(labels, scale, S, keep))
        p.append('</svg>')
        return _svg_out(p, pal_name, _layer_rules(pal_name, layers))

    @staticmethod
    def _place_labels(labels: List[Tuple[Any, ...]], scale: float, S: int,
                      keep: Optional[List[Tuple[float, float, float, float]]] = None) -> str:
        """One label layer: the collision layout run over a sky chart's
        label requests at one scale, wrapped in `<g class="dome-labels"
        data-label-scale="...">`.  Called once per layer by _sky_chart;
        the requests are the same for every layer, and only the sizes --
        and so what fits -- differ.

        Five kinds of request, in the order _sky_chart makes them:
        `cardinal` and `ring` are the chrome (always placed, and the seed
        the rest dodge); `mark` is a body's, satellite's, comet's or
        radiant's name, or a star's -- placed beside its mark, nudged down
        a row at a time when it must land (up to five rows) and dropped
        when it need not; `time` is a pass arc's rise or set clock, always
        placed, but stepped further in along its own ray until it clears;
        `con` is a constellation name, centered on its figure and dropped
        on any collision.  Body and satellite names carry
        data-body, the consumer contract that lets a live page move a
        label with its mark -- on every layer, so a consumer that moves a
        mark must move every layer's copy (querySelectorAll, not
        querySelector).

        `keep` is the chart's body marks as boxes, counted as placed before
        anything else, so no label lands on a mark."""
        star_px = 10.0 * scale
        body_px = 11.0 * scale
        card_px = 14.0 * scale
        grid_px = 10.0 * scale
        con_px = 10.0 * scale
        placed: List[Tuple[float, float, float, float]] = list(keep or [])
        out = ['<g class="dome-labels" data-label-scale="%s">' % _fmt_scale(scale)]

        def clear(box: Tuple[float, float, float, float]) -> bool:
            return not any(box[0] < o[2] and box[2] > o[0] and
                           box[1] < o[3] and box[3] > o[1] for o in placed)

        for req in labels:
            kind = req[0]
            if kind == 'cardinal':
                _k, x, y, anch, text = req
                out.append('<text x="%d" y="%d" text-anchor="%s" class="mono cardinal" '
                           'style="font-size:%.1fpx">%s</text>'
                           % (x, y, anch, card_px, text))
                placed.append((x - card_px, y - card_px, x + card_px, y + 4))
            elif kind == 'ring':
                # skylab, not plain gridlab: these two sit on the dome
                # gradient, where the axis-label gray every other panel
                # uses reaches only 3.70:1.  The other panels' labels are
                # on the panel surface and keep it (2.2).
                _k, x, y, text = req
                out.append('<text x="%d" y="%d" text-anchor="middle" '
                           'class="mono gridlab skylab" style="font-size:%.1fpx">%s</text>'
                           % (int(x), y, grid_px, text))
                placed.append((x - 2.0 * grid_px, y - card_px, x + 2.0 * grid_px, y + 4))
            elif kind == 'time':
                # Always placed, but not on top of what is already there:
                # stepped in along its own ray toward the center, a row at a
                # time, until it clears.  A pass's set time otherwise sat on
                # the moon's dark disc when the moon was low over the same
                # stretch of horizon (2.18:1).
                _k, x, y, text, ux, uy = req
                box = (x - 2.0 * grid_px, y - grid_px, x + 2.0 * grid_px, y + 5)
                for _tries in range(5):
                    if clear(box):
                        break
                    x += ux * grid_px
                    y += uy * grid_px
                    box = (x - 2.0 * grid_px, y - grid_px, x + 2.0 * grid_px, y + 5)
                out.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="mono nowlab" '
                           'style="font-size:%.1fpx">%s</text>'
                           % (x, y + 3, grid_px, text))
                placed.append(box)
            elif kind == 'con':
                _k, x, y, name = req
                # Wider glyph estimate than the star labels': .conlab
                # renders uppercase with letter-spacing.
                est_w = 0.85 * con_px * len(name)
                box = (x - est_w / 2, y - con_px, x + est_w / 2, y + 3)
                if not clear(box):
                    continue
                placed.append(box)
                out.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="conlab" '
                           'style="font-size:%.1fpx">%s</text>'
                           % (x, y, con_px, _esc(name)))
            else:
                _k, x, y, text, cls, gap, must, body = req
                px = body_px if cls in ('bodylab', 'satlab') else star_px
                est_w = 0.62 * px * len(text)
                row_h = px + 3.0
                anchor = 'start'
                lx = x + gap
                if lx + est_w > S - 4:
                    anchor = 'end'
                    lx = x - gap
                ly = min(max(y + 4, row_h), 700.0)
                fits = False
                for _tries in range(5):
                    x0 = lx if anchor == 'start' else lx - est_w
                    box = (x0, ly - px, x0 + est_w, ly + 2)
                    if clear(box):
                        fits = True
                        break
                    if not must:
                        break
                    ly = min(ly + row_h, 700.0)
                if not fits and not must:
                    continue
                placed.append(box)
                dat = '' if body is None else ' data-body="%s"' % _esc(body)
                out.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="%s" '
                           'style="font-size:%.1fpx"%s>%s</text>'
                           % (lx, ly, anchor, cls, px, dat, text))
        out.append('</g>')
        return ''.join(out)

    # ── pass chart ───────────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_ENGINE)
    def pass_chart_html(self, alm, palette: str = 'night',
                        label_scale: float = 1.0,
                        label_layers: Optional[Sequence[Tuple[Any, Any]]] = None) -> str:
        """The Next Visible Pass panel: the whole sky as it will stand at the
        soonest upcoming visible pass's culmination, the pass's arc drawn
        across it -- one chart, one epoch, so the arc crosses the stars
        it will actually cross (the per-pass chart convention
        Heavens-Above set).  A dated head line names the satellite and
        the pass's times; the chart itself is the dome renderer pointed
        at the culmination, with twilight-honest star cutoffs, and the
        chart-epoch satellite loop puts the satellite's own dot at the
        peak of its arc.  Empty string when no configured satellite has a
        visible pass in its elements' validity window -- the satellite
        panel's rows then tell that story.  The data-body/dome-track
        hooks (the weewx-celestial consumer contract) appear here exactly
        as on the dome, and so do label_scale and label_layers (see
        dome_svg); the head line is HTML outside the SVG, sized by the
        page's own CSS, and takes part in neither."""
        pal_name, pal = _resolve_palette(palette)
        layers = _label_layers(label_scale, label_layers)
        track = self._satellite_track(alm)
        if track is None:
            return ''
        culm = alm(almanac_time=int(round(track['culmination'])))
        head = ('<div class="passhead"><span class="passname">%s</span>'
                '<span class="passwhen mono">%s</span></div>'
                % (_esc(track['label']),
                   self._t('{date} · {rise} → {set} · peak {alt}°',
                           date=_esc(time.strftime(
                               self._t('%a %b %-d'),
                               time.localtime(track['culmination']))),
                           rise=_t_hm(track['rise']), set=_t_hm(track['set']),
                           alt='%.0f' % track['max_alt'])))
        return head + self._sky_chart(culm, pal, pal_name, layers,
                                      PASS_STAR_MAG_LIMIT, PASS_STAR_LABEL_MAG,
                                      track=track, grad_id='skygp-%s' % pal_name,
                                      clip_id='domecp-%s' % pal_name,
                                      aria=self._t('Pass sky chart'))

    # ── rise/set ribbons ─────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_EXTRAS)
    def ribbons_svg(self, alm, palette: str = 'night') -> str:
        import weeutil.weeutil
        pal_name, _pal = _resolve_palette(palette)
        sod = weeutil.weeutil.startOfDay(alm.time_ts)
        eod = sod + 86400
        X0, X1, ROW, TOP = 118, 952, 30, 34
        # Configured comets with elements ride the same rows (brass bars);
        # one without elements is simply absent, the dome convention.
        bodies = [self._body(alm, n) for n in CHART_BODIES]
        bodies += [b for b in (self._body(alm, n) for n in self.comet_names())
                   if b['dist_au'] is not None]
        H = TOP + ROW * len(bodies) + 34
        plot_h = ROW * len(bodies)

        def X(ts: float) -> float:
            return X0 + (X1 - X0) * (min(max(ts, sod), eod) - sod) / 86400.0

        p = [_svg_open('viewBox="0 0 1080 %d" role="img" aria-label="%s"'
                       % (H, self._t('Rise and set timeline')), pal_name)]
        tw = self._twilight(alm)
        sun = bodies[0]
        edges = [(sod, 'night'), (tw['astro_dawn'], 'astro'), (tw['nautical_dawn'], 'naut'),
                 (tw['civil_dawn'], 'civil'), (sun['rise'], 'day'), (sun['set'], 'civil'),
                 (tw['civil_dusk'], 'naut'), (tw['nautical_dusk'], 'astro'),
                 (tw['astro_dusk'], 'night')]
        edges = [(ts, shade) for ts, shade in edges if ts is not None]
        for i, (ts, shade) in enumerate(edges):
            end = edges[i + 1][0] if i + 1 < len(edges) else eod
            p.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" '
                     'class="sky-fill-tw-%s"/>'
                     % (X(ts), TOP, max(0.0, X(end) - X(ts)), plot_h, shade))
        # These cross the twilight bands, not the panel surface -- in `line`
        # at 0.35 they measured 1.02-1.13:1 on the night plate, the dome's
        # 2.1.3 defect exactly.  See _band_rule (2.2).
        for h in range(0, 25, 3):
            x = X0 + (X1 - X0) * h / 24.0
            p.append(_band_rule(x, TOP, x, TOP + plot_h, 'primary'))
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%02d</text>'
                     % (x, TOP + plot_h + 18, h % 24))
        for i, b in enumerate(bodies):
            y = TOP + i * ROW
            cy = y + ROW / 2.0
            # Comets ride the same rows in brass; they are not palette
            # bodies and so carry no identity or rim class of their own.
            # Pale bodies (palette 'ring' entries) get a 1px edge on their
            # LEGEND DOT -- only there, whatever the comment here said
            # before 2.4: a bar's outline is the plate's uniform `bandedge`
            # and its transit tick has none.  Saturated bodies have no rim
            # color and the stroke paints nothing, as before.
            name = b['name']
            fill_cls = ('sky-fill-body-%s' % name if name in CHART_BODIES
                        else 'sky-fill-brass')
            # The legend dot alone takes the per-body rim; the BAR's outline
            # is the plate's uniform `bandedge`, which _band_bar adds -- two
            # stroke roles on one mark would leave the winner to the order
            # the defaults happen to be written in.
            dot_cls = ('%s sky-stroke-rim-%s' % (fill_cls, name)
                       if name in CHART_BODIES else fill_cls)
            label = self._label(alm, name)
            p.append('<circle cx="14" cy="%.1f" r="4" class="%s" stroke-width="1"/>'
                     % (cy, dot_cls))
            p.append('<text x="26" y="%.1f" class="rowlab">%s</text>' % (cy + 4, _esc(label)))
            segs: List[Tuple[float, float]] = []
            if b['circumpolar']:
                segs, right = [(sod, eod)], self._t('always up')
            elif b['neverup']:
                right = self._t('never up')
            else:
                r, s = b['rise'], b['set']
                if r is not None and s is not None:
                    segs = [(r, s)] if r <= s else [(sod, s), (r, eod)]
                elif r is not None:
                    segs = [(r, eod)]
                elif s is not None:
                    segs = [(sod, s)]
                right = '%s &#8594; %s' % (_t_hm(r), _t_hm(s))
            for a, z in segs:
                xa, xz = X(a), X(z)
                if xz - xa < 0.5:
                    continue
                # The bar crosses the twilight bands, not the panel
                # surface, so its contrast comes from _band_bar's casing
                # and outline rather than from the identity color it
                # carries -- through 2.2 it was the fill alone, which on
                # the paper plate measured 1.01:1 for Mars.
                p.append(_band_bar(
                    xa, cy - 5, xz - xa, 10, 4, fill_cls,
                    inner='<title>%s</title>'
                    % self._t('{name} above the horizon ({duration})',
                              name=_esc(label),
                              duration=self._dur(b['visible']))))
            if b['transit'] is not None and sod <= b['transit'] <= eod:
                xt = X(b['transit'])
                p.append(_band_tick(
                    xt, cy - 8, xt, cy + 8, 'sky-stroke-ink', 2,
                    inner='<title>%s</title>'
                    % self._t('{name} transit {time}', name=_esc(label),
                              time=_t_hm(b['transit']))))
            p.append('<text x="%d" y="%.1f" class="mono timelab">%s</text>' % (X1 + 12, cy + 4, right))
        xn = X(alm.time_ts)
        p.append(_band_tick(xn, TOP - 8, xn, TOP + plot_h, 'sky-stroke-brass',
                            1.5, cls='nowpulse'))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono nowlab">%s</text>'
                 % (xn, TOP - 14, self._t('now {time}', time=_t_hm(alm.time_ts))))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── orrery ───────────────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_EXTRAS)
    def orrery_svg(self, alm, palette: str = 'night') -> str:
        pal_name, _pal = _resolve_palette(palette)
        S, cx = 480, 240
        lo, hi = math.log(0.387), math.log(30.07)

        def orbit_r(a: float) -> float:
            return 44 + 176 * (math.log(a) - lo) / (hi - lo)

        p = [_svg_open('viewBox="0 0 %d %d" role="img" aria-label="%s"'
                       % (S, S, self._t('Solar system plan view')), pal_name)]
        for a in SEMI_MAJOR_AU.values():
            p.append('<circle cx="%d" cy="%d" r="%.1f" fill="none" '
                     'class="sky-stroke-line" stroke-width="1" opacity="0.8"/>'
                     % (cx, cx, orbit_r(a)))
        p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" class="sky-stroke-muted" '
                 'stroke-width="1" stroke-dasharray="2 5" opacity="0.6"/>'
                 % (cx + 44, cx, S - 12, cx))
        p.append('<text x="%d" y="%d" text-anchor="end" class="mono gridlab">0&#176;</text>'
                 % (S - 8, cx - 8))
        # The rim paints only where the plate gives the sun a ring (the
        # paper plate does; navy needs none), so the stroke is written
        # either way and the class decides.
        p.append('<circle cx="%d" cy="%d" r="8" '
                 'class="sky-fill-orrery-sun sky-stroke-rim-sun" stroke-width="1.5">'
                 '<title>%s</title></circle>'
                 % (cx, cx, _esc(self._label(alm, 'sun'))))
        hlongs = {name: self._body(alm, name)['hlong'] for name in PLANETS}
        hlongs['earth'] = alm.sun.hlong    # the sun tag reports Earth's, per XEphem
        labels: List[List[Any]] = []

        def queue_label(x: float, y: float, disp: str) -> None:
            # Label away from center, flipped when its estimated width would
            # leave the viewBox (a body near 0 degrees sits at the right rim
            # for years at a time), then clamped vertically.
            est_w = 8 + 7.0 * len(disp)
            anchor = 'start' if x >= cx else 'end'
            if anchor == 'start' and x + est_w > S - 6:
                anchor = 'end'
            elif anchor == 'end' and x - est_w < 6:
                anchor = 'start'
            lx = x + (8 if anchor == 'start' else -8)
            ly = min(max(y + 4, 14.0), S - 8.0)
            x0 = lx if anchor == 'start' else lx - est_w
            labels.append([lx, ly, anchor, _esc(disp), x0, x0 + est_w])

        for name, a in SEMI_MAJOR_AU.items():
            h = math.radians(hlongs[name])
            r = orbit_r(a)
            x, y = cx + r * math.cos(h), cx - r * math.sin(h)
            disp = self._label(alm, name)
            title = self._t('{name} — heliocentric longitude {deg}°',
                            name=_esc(disp), deg='%.1f' % hlongs[name])
            if name == 'earth':
                p.append('<circle cx="%.1f" cy="%.1f" r="5" '
                         'class="sky-fill-earth sky-stroke-earth" stroke-width="2">'
                         '<title>%s</title></circle>'
                         % (x, y, title))
            else:
                p.append('<circle cx="%.1f" cy="%.1f" r="5" '
                         'class="sky-fill-body-%s sky-stroke-ring-%s" stroke-width="1.5">'
                         '<title>%s</title></circle>'
                         % (x, y, name, name, title))
            queue_label(x, y, disp)
        # Comets: a diamond at the comet's CURRENT sun distance on the
        # same log scale as the rings, at its heliocentric longitude --
        # marker only, no orbit ring: a circle would misdraw an eccentric
        # orbit.  This is the panel that tells a news-cycle comet's story
        # (inbound past Jupiter, inside Earth's orbit) as the diamond
        # creeps sunward across report cycles.  Solid/hollow follows the
        # dome's naked-eye rule, one convention everywhere.  The radius is
        # clamped inside the chart (a far-aphelion comet pins near the
        # rim; one diving inside Mercury stays clear of the sun's disc) --
        # the tooltip carries the true distance either way.
        for name in self.comet_names():
            binder = getattr(alm, name)
            hlong, r_au = binder.hlong, binder.sun_distance
            if hlong is None or r_au is None:
                continue
            bright_mag = self._comet_pos(alm, name)['mag']
            h = math.radians(hlong)
            r = min(max(orbit_r(r_au), 16.0), 228.0)
            x, y = cx + r * math.cos(h), cx - r * math.sin(h)
            disp = self._label(alm, name)
            bright = bright_mag is not None and bright_mag <= COMET_NAKED_EYE_MAG
            fill_cls, ring_cls = (('sky-fill-brass', 'sky-stroke-halo') if bright
                                  else ('sky-fill-halo', 'sky-stroke-brass'))
            title = self._t('{name} — heliocentric longitude {deg}°, {dist} au',
                            name=_esc(disp), deg='%.1f' % hlong,
                            dist='%.1f' % r_au)
            # The tail points anti-sunward, which on a sun-centered plan
            # view is simply radially outward.
            p.append(_comet_tail(x, y, (x - cx) / r, (y - cx) / r,
                                 'sky-stroke-brass'))
            p.append('<path d="M%.1f %.1f L%.1f %.1f L%.1f %.1f L%.1f %.1f Z" '
                     'class="%s %s" stroke-width="1.5">'
                     '<title>%s</title></path>'
                     % (x, y - 5.0, x + 5.0, y, x, y + 5.0, x - 5.0, y,
                        fill_cls, ring_cls, title))
            queue_label(x, y, disp)
        # Neighbors sharing a rim (Saturn/Neptune near 0 degrees) collide;
        # push the later label down in 13 px steps until it clears.
        placed: List[List[Any]] = []
        for lab in labels:
            for _tries in range(6):
                if not any(lab[4] < o[5] and lab[5] > o[4] and abs(lab[1] - o[1]) < 12
                           for o in placed):
                    break
                lab[1] = min(lab[1] + 13, S - 8.0)
            placed.append(lab)
            p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="bodylab">%s</text>'
                     % (lab[0], lab[1], lab[2], lab[3]))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── analemma ─────────────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_EXTRAS)
    def analemma_svg(self, alm, palette: str = 'night') -> str:
        import calendar
        pal_name, _pal = _resolve_palette(palette)
        year = time.localtime(alm.time_ts).tm_year
        # Local standard (not DST) noon, each week of the year.
        noon0 = calendar.timegm((year, 1, 1, 12, 0, 0)) + time.timezone
        pts = []
        for week in range(53):
            ts = noon0 + week * 7 * 86400
            a = alm(almanac_time=ts)
            pts.append({'ts': ts, 'alt': a.sun.alt, 'az': a.sun.az})
        # The brass marker is TODAY's standard noon, its own evaluation on
        # the same locus -- not the nearest weekly sample, which can sit
        # 3.5 days along the figure-eight from the real sun.
        tm_now = time.localtime(alm.time_ts)
        noon_today = calendar.timegm((tm_now.tm_year, tm_now.tm_mon,
                                      tm_now.tm_mday, 12, 0, 0)) + time.timezone
        a = alm(almanac_time=noon_today)
        today = {'ts': noon_today, 'alt': a.sun.alt, 'az': a.sun.az}
        S = 480
        azs = [q['az'] for q in pts + [today]]
        alts = [q['alt'] for q in pts + [today]]
        az0, az1 = min(azs) - 4, max(azs) + 4
        al0 = math.floor(min(alts) / 10.0) * 10 - 4
        al1 = math.ceil(max(alts) / 10.0) * 10 + 4

        def X(az: float) -> float:
            return 54 + (S - 78) * (az - az0) / (az1 - az0)

        def Y(al: float) -> float:
            return 20 + (S - 74) * (al1 - al) / (al1 - al0)

        p = [_svg_open('viewBox="0 0 %d %d" role="img" aria-label="%s"'
                       % (S, S, self._t('Analemma')), pal_name)]
        for al in range(int(al0) + 4, int(al1), 10):
            p.append('<line x1="54" y1="%.1f" x2="%d" y2="%.1f" '
                     'class="sky-stroke-line" stroke-width="1" opacity="0.55"/>'
                     % (Y(al), S - 24, Y(al)))
            p.append('<text x="48" y="%.1f" text-anchor="end" class="mono gridlab">%d&#176;</text>'
                     % (Y(al) + 4, al))
        for az in range(int(az0) + 4, int(az1), 10):
            p.append('<line x1="%.1f" y1="20" x2="%.1f" y2="%d" '
                     'class="sky-stroke-line" stroke-width="1" opacity="0.35"/>'
                     % (X(az), X(az), S - 54))
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%d&#176;</text>'
                     % (X(az), S - 36, az))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%s</text>'
                 % (X((az0 + az1) / 2), S - 18, self._t('azimuth')))
        path = ' '.join('%s%.1f %.1f' % ('M' if i == 0 else 'L', X(q['az']), Y(q['alt']))
                        for i, q in enumerate(pts)) + ' Z'
        p.append('<path d="%s" fill="none" class="sky-stroke-ink" '
                 'stroke-width="1.5" opacity="0.9"/>' % path)
        # Labels sit radially outward from the figure's centroid, clear of the
        # curve at the lobes (Jun at the top, Dec/Jan at the bottom) and of
        # the axis labels; the today label owns its spot -- a month label
        # falling on it is skipped.
        az_c = sum(q['az'] for q in pts) / len(pts)
        al_c = sum(q['alt'] for q in pts) / len(pts)

        def _outward(q, dist: float) -> Tuple[float, float, str]:
            dx, dy = X(q['az']) - X(az_c), Y(q['alt']) - Y(al_c)
            n = math.hypot(dx, dy) or 1.0
            lx = X(q['az']) + dist * dx / n
            ly = min(max(Y(q['alt']) + dist * dy / n + 3, 14.0), S - 60.0)
            return lx, ly, ('start' if dx >= 0 else 'end')

        # Months to label are picked by number — comparing strftime('%b')
        # output against English abbreviations loses every label on a
        # non-English OS locale.  The label text itself is strftime output,
        # so it renders in the station's locale like the panel dates do.
        month_seen: set = set()
        for q in pts:
            tm = time.localtime(q['ts'])
            first = tm.tm_mon not in month_seen
            month_seen.add(tm.tm_mon)
            p.append('<circle cx="%.1f" cy="%.1f" r="2" class="sky-fill-muted">'
                     '<title>%s</title></circle>'
                     % (X(q['az']), Y(q['alt']),
                        self._t('{date} — alt {alt}°, az {az}°', date=self._date(q['ts']),
                                alt='%.1f' % q['alt'], az='%.1f' % q['az'])))
            if first and tm.tm_mon in (1, 3, 6, 9, 11):
                if (abs(X(q['az']) - X(today['az'])) < 30
                        and abs(Y(q['alt']) - Y(today['alt'])) < 18):
                    continue
                lx, ly, anchor = _outward(q, 13)
                p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="mono gridlab">%s</text>'
                         % (lx, ly, anchor, time.strftime('%b', tm)))
        p.append('<circle cx="%.1f" cy="%.1f" r="5.5" '
                 'class="sky-fill-brass sky-stroke-halo" stroke-width="1.5">'
                 '<title>%s</title></circle>'
                 % (X(today['az']), Y(today['alt']),
                    self._t('{date} — alt {alt}°, az {az}°', date=self._date(today['ts']),
                            alt='%.1f' % today['alt'], az='%.1f' % today['az'])))
        lx, ly, anchor = _outward(today, 17)
        p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="todaylab">%s</text>'
                 % (lx, ly, anchor, self._t('today')))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── equation of time ─────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_ENGINE)
    def eot_svg(self, alm, palette: str = 'night') -> str:
        """The equation of time across the year: sundial minus clock (the
        USNO sign -- positive above the zero line means the sundial runs
        ahead), sampled at the analemma's own instants, local standard
        noon each week, so the two charts describe the same sun.  The
        brass point and its label are TODAY's standard-noon value, its
        own evaluation rather than the nearest weekly sample: the curve
        is steep enough near the solstices that snapping to the grid
        mislabels the seconds-precision value by up to ~90 s (late
        December).  The fixed ±18-minute frame holds the yearly extremes
        (+16m26s early November, −14m14s mid-February) with margin, so
        the plate looks the same every year."""
        import calendar
        pal_name, _pal = _resolve_palette(palette)
        year = time.localtime(alm.time_ts).tm_year
        # Local standard (not DST) noon, each week of the year.
        noon0 = calendar.timegm((year, 1, 1, 12, 0, 0)) + time.timezone
        pts = []
        for week in range(53):
            ts = noon0 + week * 7 * 86400
            seconds = _raw(alm(almanac_time=ts).equation_of_time, 'second')
            if seconds is None:
                continue
            pts.append({'ts': ts, 'eot': seconds / 60.0})
        W, H = 480, 300
        t0, t1 = float(noon0), float(noon0 + 52 * 7 * 86400)
        M0, M1 = -18.0, 18.0

        def X(ts: float) -> float:
            return 54 + (W - 78) * (ts - t0) / (t1 - t0)

        def Y(minutes: float) -> float:
            return 16 + (H - 66) * (M1 - minutes) / (M1 - M0)

        p = [_svg_open('viewBox="0 0 %d %d" role="img" aria-label="%s"'
                       % (W, H, self._t('Equation of time')), pal_name)]
        for m in range(-15, 16, 5):
            strong = (m == 0)
            p.append('<line x1="54" y1="%.1f" x2="%d" y2="%.1f" class="%s" '
                     'stroke-width="1" opacity="%s"/>'
                     % (Y(m), W - 24, Y(m),
                        'sky-stroke-ink' if strong else 'sky-stroke-line',
                        '0.7' if strong else '0.5'))
            p.append('<text x="48" y="%.1f" text-anchor="end" class="mono gridlab">%+dm</text>'
                     % (Y(m) + 4, m) if m else
                     '<text x="48" y="%.1f" text-anchor="end" class="mono gridlab">0</text>'
                     % (Y(0) + 4))
        # Month ticks and labels, by month number (never by comparing
        # strftime output -- the analemma's locale lesson); the label text
        # itself is strftime output, so it follows the station's locale.
        for mon in range(1, 13):
            ts_m = calendar.timegm((year, mon, 1, 12, 0, 0)) + time.timezone
            x = X(ts_m)
            p.append('<line x1="%.1f" y1="16" x2="%.1f" y2="%d" '
                     'class="sky-stroke-line" stroke-width="1" opacity="0.3"/>'
                     % (x, x, H - 50))
            if mon % 2:
                p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%s</text>'
                         % (x, H - 32, time.strftime('%b', time.localtime(ts_m))))
        path = ' '.join('%s%.1f %.1f' % ('M' if i == 0 else 'L', X(q['ts']), Y(q['eot']))
                        for i, q in enumerate(pts))
        p.append('<path d="%s" fill="none" class="sky-stroke-ink" '
                 'stroke-width="1.5" opacity="0.9"/>' % path)
        tm_now = time.localtime(alm.time_ts)
        noon_today = calendar.timegm((tm_now.tm_year, tm_now.tm_mon,
                                      tm_now.tm_mday, 12, 0, 0)) + time.timezone
        now_seconds = _raw(alm(almanac_time=noon_today).equation_of_time, 'second')
        if now_seconds is None:
            raise ValueError('equation_of_time unavailable')  # -> panel guard
        today = {'ts': noon_today, 'eot': now_seconds / 60.0}
        tx, ty = X(today['ts']), Y(today['eot'])
        p.append('<circle cx="%.1f" cy="%.1f" r="3.5" class="sky-fill-brass"/>'
                 % (tx, ty))
        # Today's value beside the point, in the almanac convention
        # (16m 26s style), nudged to stay inside the frame.
        total = int(round(abs(today['eot']) * 60.0))
        value = '%s%dm %02ds' % ('-' if today['eot'] < 0 else '+',
                                 total // 60, total % 60)
        anchor = 'start' if tx < W - 96 else 'end'
        lx = tx + (8 if anchor == 'start' else -8)
        ly = min(max(ty + 4, 14.0), H - 56.0)
        p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="mono nowlab">%s</text>'
                 % (lx, ly, anchor, value))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── sun path ─────────────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_EXTRAS)
    def sunpath_svg(self, alm, palette: str = 'night') -> str:
        """The sun's altitude/azimuth arc across today, midnight to midnight,
        over twilight-depth bands below the horizon; the moon's path dashed.
        The azimuth axis is the fixed full circle (N through E, S, W back to
        N) so the arc's seasonal swing reads at a glance and a circumpolar
        sun needs no special casing."""
        import weeutil.weeutil
        pal_name, _pal = _resolve_palette(palette)
        sod = weeutil.weeutil.startOfDay(alm.time_ts)
        FLOOR = -24.0
        sun_pts, moon_pts = [], []
        for i in range(97):                   # every 15 minutes, both ends
            a = alm(almanac_time=sod + i * 900)
            sun_pts.append((i, a.sun.alt, a.sun.az))
            moon_pts.append((i, a.moon.alt, a.moon.az))
        alts = [alt for _i, alt, _az in sun_pts + moon_pts if alt >= FLOOR]
        top = min(94.0, max(alts) + 8.0) if alts else 30.0
        S, PX0, PX1, PY0, PY1 = 480, 46, 464, 18, 430

        def X(az: float) -> float:
            return PX0 + (PX1 - PX0) * az / 360.0

        def Y(alt: float) -> float:
            return PY0 + (PY1 - PY0) * (top - alt) / (top - FLOOR)

        p = [_svg_open('viewBox="0 0 %d %d" role="img" aria-label="%s"'
                       % (S, S, self._t('Sun path today')), pal_name)]
        # Day above the horizon, then the twilight depths below it.
        bands = [(top, 0.0, 'day'), (0.0, -6.0, 'civil'), (-6.0, -12.0, 'naut'),
                 (-12.0, -18.0, 'astro'), (-18.0, FLOOR, 'night')]
        for hi, lo, shade in bands:
            hi, lo = min(hi, top), max(lo, FLOOR)
            if hi <= lo:
                continue
            p.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" '
                     'class="sky-fill-tw-%s"/>'
                     % (PX0, Y(hi), PX1 - PX0, Y(lo) - Y(hi), shade))
        # Altitude rules and, below, the azimuth rules: both are drawn over the
        # day/twilight bands rather than the panel surface, so both go through
        # _band_rule (2.2) -- 1.02-1.15:1 in `line` on the night plate.
        for alt in (30, 60, 90):
            if alt >= top:
                continue
            p.append(_band_rule(PX0, Y(alt), PX1, Y(alt), 'primary'))
            p.append('<text x="%d" y="%.1f" text-anchor="end" class="mono gridlab">%d&#176;</text>'
                     % (PX0 - 6, Y(alt) + 4, alt))
        p.append(_band_tick(PX0, Y(0), PX1, Y(0), 'sky-stroke-ink', 1,
                            attrs=' opacity="0.8"'))
        p.append('<text x="%d" y="%.1f" text-anchor="end" class="mono gridlab">0&#176;</text>'
                 % (PX0 - 6, Y(0) + 4, ))
        for az in range(45, 360, 45):
            p.append(_band_rule(X(az), PY0, X(az), PY1, 'secondary'))
        c_n, c_e, c_s, c_w = self._cardinals(alm)
        for az, label in ((0, c_n), (90, c_e), (180, c_s), (270, c_w), (360, c_n)):
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono cardinal" '
                     'style="font-size:12px">%s</text>' % (X(az), PY1 + 20, _esc(label)))

        # Both arcs cross the twilight bands, not the panel, so they go
        # through _band_curve: on the paper plate the sun's own yellow is
        # 1.21:1 against the daytime band and the moon's silver 1.10, which
        # is the panel's subject drawn invisibly.
        def _paths(pts: List[Tuple[int, float, float]], stroke_cls: str,
                   width: float, dash: str = '', opacity: str = '') -> None:
            seg: List[str] = []
            prev_az: Optional[float] = None

            def flush() -> None:
                if len(seg) > 1:
                    p.append(_band_curve(' L'.join(seg), stroke_cls, width,
                                         dash, opacity))
            for _i, alt, az in pts:
                if alt < FLOOR or (prev_az is not None and abs(az - prev_az) > 180):
                    flush()
                    seg = []
                    prev_az = None
                if alt >= FLOOR:
                    seg.append('%.1f %.1f' % (X(az), Y(alt)))
                    prev_az = az
            flush()

        # On the paper plate a body's own fill is the wrong color for a
        # LINE -- the sun's yellow reads 1.11:1 against the casing under
        # it -- so an arc takes the plate's `ring` value where it has one,
        # the same dark edge the pale bodies' dots wear there.  The night
        # plate defines no rings and the arcs stay body-colored.
        _paths(moon_pts, 'sky-stroke-trace-moon', 1.3,
               dash=' stroke-dasharray="4 4"', opacity='0.85')
        _paths(sun_pts, 'sky-stroke-trace-sun', 2.2, opacity='0.95')
        sun_labels: List[Tuple[float, float]] = []
        for i, alt, az in sun_pts[:-1]:
            if i % 4 or alt < FLOOR:
                continue
            p.append(_band_dot(X(az), Y(alt), 1.9, 'sky-fill-ink', opacity='0.9'))
            if i % 12 == 0 and alt > FLOOR + 4:
                sun_labels.append((X(az), Y(alt) - 7))
                # bandlab, not plain gridlab: these follow the arc down
                # through the twilight bands, where the panel-surface gray
                # reads 3.59:1 on the night plate and 1.03 on the paper
                # one.  Same reasoning as .skylab on the dome (2.2).
                p.append(_band_text(X(az), Y(alt) - 7, 'middle',
                                    'mono gridlab bandlab', '%02d' % (i // 4)))

        # ── times on the moon's curve ────────────────────────────────────────
        # The moon's 24-hour track is an open curve -- a lunar day outruns the
        # calendar day by ~50 minutes, so the track ends where it began minus
        # ~12 degrees of azimuth.  The two midnight endpoints get dots labeled
        # 00/24 when they clear the plot floor (near full moon that break sits
        # at the apex, where a user once reported it as a bug); rise, set and
        # transit are ticked and labeled with skin-formatted times.  Labels
        # dodge the sun's hour labels; the transit label yields to a nearby
        # endpoint label rather than crowd it.
        moon_ink = 'sky-stroke-trace-moon'

        def _dodge(x: float, y: float, dy: float) -> float:
            for lx, ly in sun_labels:
                if abs(x - lx) < 26 and abs(y - ly) < 11:
                    return ly + dy
            return y

        ends = [(i, alt, az) for i, alt, az in (moon_pts[0], moon_pts[96])
                if alt >= FLOOR]
        for i, alt, az in ends:
            x, y = X(az), Y(alt)
            p.append('<g><title>%s</title>%s%s</g>'
                     % (self._t('Moon at {time} — the day’s track is open here: a lunar day runs about 50 minutes longer than a calendar day',
                                time='00:00' if i == 0 else '24:00'),
                        _band_dot(x, y, 2.2, 'sky-fill-trace-moon'),
                        _band_text(x + (5 if i == 0 else -5), y - 5,
                                   'start' if i == 0 else 'end',
                                   'mono moonlab bandlab',
                                   '00' if i == 0 else '24')))
        for kind, glyph in (('rise', '&#8599;'), ('set', '&#8600;'), ('transit', '')):
            vh = getattr(alm.moon, kind)
            event_ts = _raw(vh, 'unix_epoch')
            if event_ts is None or not sod <= event_ts < sod + 86400:
                continue
            e = alm(almanac_time=event_ts)
            alt, az = e.moon.alt, e.moon.az
            if alt < FLOOR:
                continue
            x, y = X(az), Y(alt)
            if kind == 'transit':
                if any(abs(x - X(eaz)) < 34 for _i, _a, eaz in ends):
                    continue
                p.append('<g><title>%s</title>%s%s</g>'
                         % (self._t('Moon transit {time} — altitude {alt}°',
                                    time=str(vh), alt='%.1f' % alt),
                            _band_tick(x, y - 3, x, y - 8, moon_ink, 1.3),
                            _band_text(x, _dodge(x, y - 12, -12), 'middle',
                                       'mono moonlab bandlab', str(vh))))
            else:
                title = (self._t('Moonrise {time}', time=str(vh)) if kind == 'rise'
                         else self._t('Moonset {time}', time=str(vh)))
                p.append('<g><title>%s</title>'
                         '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'class="%s" stroke-width="1.3"/>%s</g>'
                         % (title, x, y - 4, x, y + 4, moon_ink,
                            _band_text(x, _dodge(x, y + 15, 12), 'middle',
                                       'mono moonlab bandlab',
                                       '%s%s' % (glyph, vh))))
        moon = self._body(alm, 'moon')
        if moon['alt'] >= FLOOR:
            x, y = X(moon['az']), Y(moon['alt'])
            p.append('<g>%s<title>%s</title></g>'
                     % (self._moon_disc(alm, x, y, 7, ring=False),
                        self._t('Moon now — alt {alt}°, az {az}°',
                                alt='%.1f' % moon['alt'], az='%.1f' % moon['az'])))
        sun = self._body(alm, 'sun')
        if sun['alt'] >= FLOOR:
            x, y = X(sun['az']), Y(sun['alt'])
            for k in range(8):
                a = math.pi * k / 4
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'class="sky-stroke-body-sun" stroke-width="1.5"/>'
                         % (x + 9 * math.cos(a), y + 9 * math.sin(a),
                            x + 13 * math.cos(a), y + 13 * math.sin(a)))
            p.append('<circle cx="%.1f" cy="%.1f" r="7" '
                     'class="sky-fill-body-sun sky-stroke-ring-sun" stroke-width="1.5">'
                     '<title>%s</title></circle>'
                     % (x, y,
                        self._t('Sun now — alt {alt}°, az {az}°',
                                alt='%.1f' % sun['alt'], az='%.1f' % sun['az'])))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── day length through the year ──────────────────────────────────────────
    @staticmethod
    def _daylight_state(alt: float) -> str:
        """The twilight shade for a sun altitude -- seeds each day-length
        column's state at the start of day, so polar day and polar night
        (no rise/set events at all) still shade correctly."""
        if alt >= 0:
            return 'day'
        if alt >= -6:
            return 'civil'
        if alt >= -12:
            return 'naut'
        if alt >= -18:
            return 'astro'
        return 'night'

    @_panel_guard(needs=TIER_EXTRAS)
    def daylength_svg(self, alm, palette: str = 'night') -> str:
        """Sunrise, sunset and the twilight depths for every week of the
        year, columns of local CLOCK time -- the DST steps are real and
        deliberate.  The solid curves are sunrise and sunset, the dashed
        curve is solar noon (the transit), the brass line is today."""
        import calendar
        pal_name, _pal = _resolve_palette(palette)
        year = time.localtime(alm.time_ts).tm_year
        # Local standard noon Jan 1, stepped weekly (as the analemma does).
        noon0 = calendar.timegm((year, 1, 1, 12, 0, 0)) + time.timezone
        WEEKS = 53
        X0, X1, TOP, PH = 64, 1016, 24, 300
        H = TOP + PH + 48
        colw = (X1 - X0) / float(WEEKS)

        def hod(ts: float) -> float:
            lt = time.localtime(ts)
            return lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0

        def XW(w: float) -> float:
            return X0 + colw * w

        def Y(h: float) -> float:
            return TOP + PH * (24.0 - h) / 24.0

        rise_h: List[Optional[float]] = []
        set_h: List[Optional[float]] = []
        noon_h: List[Optional[float]] = []
        cols = []
        for w in range(WEEKS):
            ts = noon0 + w * 7 * 86400
            a = alm(almanac_time=ts)
            rise, sset = _raw(a.sun.rise, 'unix_epoch'), _raw(a.sun.set, 'unix_epoch')
            noon = _raw(a.sun.transit, 'unix_epoch')
            tw = self._twilight(a)
            start = self._daylight_state(alm(almanac_time=ts - 43200).sun.alt)
            edges: List[Tuple[float, str]] = [(0.0, start)]
            for tsv, shade in ((tw['astro_dawn'], 'astro'), (tw['nautical_dawn'], 'naut'),
                               (tw['civil_dawn'], 'civil'), (rise, 'day'),
                               (sset, 'civil'), (tw['civil_dusk'], 'naut'),
                               (tw['nautical_dusk'], 'astro'), (tw['astro_dusk'], 'night')):
                if tsv is not None:
                    edges.append((hod(tsv), shade))
            edges.sort(key=lambda e: e[0])    # a shade is the state AFTER its edge
            cols.append((ts, edges, rise, sset))
            rise_h.append(hod(rise) if rise is not None else None)
            set_h.append(hod(sset) if sset is not None else None)
            noon_h.append(hod(noon) if noon is not None else None)

        p = [_svg_open('viewBox="0 0 1080 %d" role="img" aria-label="%s"'
                       % (H, self._t('Day length through the year')), pal_name)]
        for w, (ts, edges, rise, sset) in enumerate(cols):
            x = XW(w)
            for i, (h, shade) in enumerate(edges):
                h2 = edges[i + 1][0] if i + 1 < len(edges) else 24.0
                if h2 <= h:
                    continue
                rect = ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                        'class="sky-fill-tw-%s"/>'
                        % (x, Y(h2), colw + 0.4, Y(h) - Y(h2), shade))
                if shade == 'day' and rise is not None and sset is not None:
                    rect = rect[:-2] + ('><title>%s</title></rect>'
                                        % self._t('{date} — daylight {duration}',
                                                  date=self._date(ts),
                                                  duration=self._dur(max(0.0, sset - rise))))
                p.append(rect)
        # Hour rules and month rules alike sit on the twilight columns, so
        # both go through _band_rule rather than taking the panel-surface
        # `line` they had through 2.1.3 (2.2).
        for h in range(0, 25, 3):
            p.append(_band_rule(X0, Y(h), X1, Y(h), 'primary'))
            p.append('<text x="%d" y="%.1f" text-anchor="end" class="mono gridlab">%02d</text>'
                     % (X0 - 8, Y(h) + 4, h % 24))
        for mon in range(1, 13):
            ts_m = calendar.timegm((year, mon, 1, 12, 0, 0)) + time.timezone
            wf = (ts_m - noon0) / (7 * 86400.0)
            if wf > 0.2:
                p.append(_band_rule(XW(wf), TOP, XW(wf), TOP + PH, 'secondary'))
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%s</text>'
                     % (min(XW(wf + 2.2), X1 - 10.0), TOP + PH + 20,
                        time.strftime('%b', time.localtime(ts_m))))

        # The three traces and the "today" line are drawn over the twilight
        # COLUMNS, not the panel, so they go through the band helpers: on
        # the paper plate ink measured 1.72:1 against the night column and
        # the brass line 1.20 against the astronomical one.
        def _curve(hours: List[Optional[float]], width: float, dash: str = '',
                   opacity: str = '') -> None:
            seg: List[str] = []

            def flush() -> None:
                if len(seg) > 1:
                    p.append(_band_curve(' L'.join(seg), 'sky-stroke-ink', width,
                                         dash, opacity))
            for w, h in enumerate(hours):
                if h is None:
                    flush()
                    seg = []
                    continue
                seg.append('%.1f %.1f' % (XW(w + 0.5), Y(h)))
            flush()

        _curve(noon_h, 1, dash=' stroke-dasharray="3 4"', opacity='0.7')
        _curve(rise_h, 1.5, opacity='0.95')
        _curve(set_h, 1.5, opacity='0.95')
        wf_now = min(max((alm.time_ts - noon0) / (7 * 86400.0) + 0.5, 0.0), float(WEEKS))
        p.append(_band_tick(XW(wf_now), TOP - 8, XW(wf_now), TOP + PH,
                            'sky-stroke-brass', 1.5))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="todaylab">%s</text>'
                 % (XW(wf_now), TOP - 12, self._t('today')))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── the lunar month ──────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_EXTRAS)
    def lunation_svg(self, alm, palette: str = 'night') -> str:
        """The current lunation, previous new moon to next, as a strip of
        thirty phase discs with the principal phases dated and today's disc
        ringed in brass."""
        pal_name, _pal = _resolve_palette(palette)
        prev_new = _raw(alm.previous_new_moon, 'unix_epoch')
        next_new = _raw(alm.next_new_moon, 'unix_epoch')
        if prev_new is None or next_new is None or next_new <= prev_new:
            raise ValueError('lunation anchors unavailable')
        span = float(next_new - prev_new)
        N, M, W = 30, 40, 1000
        y_disc, r = 66, 13

        def X(ts: float) -> float:
            return M + W * (ts - prev_new) / span

        p = [_svg_open('viewBox="0 0 1080 152" role="img" aria-label="%s"'
                       % self._t('The lunar month'), pal_name)]
        today_i = int(round((alm.time_ts - prev_new) / span * (N - 1)))
        today_i = min(max(today_i, 0), N - 1)
        for i in range(N):
            ts = prev_new + span * i / (N - 1)
            a = alm(almanac_time=ts)
            x = M + W * i / (N - 1.0)
            p.append('<g>%s<title>%s</title></g>'
                     % (self._moon_disc(a, x, y_disc, r),
                        self._t('{date} — {pct}% illuminated', date=self._date(ts),
                                pct='%d' % a.moon_fullness)))
        aq = alm(almanac_time=prev_new + 3600)
        quarters = ((prev_new, self._t('new')),
                    (_raw(aq.next_first_quarter_moon, 'unix_epoch'), self._t('first quarter')),
                    (_raw(aq.next_full_moon, 'unix_epoch'), self._t('full')),
                    (_raw(aq.next_last_quarter_moon, 'unix_epoch'), self._t('last quarter')),
                    (next_new, self._t('new')))
        for ts_q, name in quarters:
            if ts_q is None or not prev_new <= ts_q <= next_new:
                continue
            x = X(ts_q)
            p.append('<line x1="%.1f" y1="86" x2="%.1f" y2="96" '
                     'class="sky-stroke-muted" stroke-width="1" opacity="0.7"/>'
                     % (x, x))
            p.append('<text x="%.1f" y="115" text-anchor="middle" class="rowlab">%s</text>'
                     % (x, name))
            p.append('<text x="%.1f" y="133" text-anchor="middle" class="mono gridlab">%s</text>'
                     % (x, self._date(ts_q)))
        x_t = M + W * today_i / (N - 1.0)
        p.append('<circle cx="%.1f" cy="%d" r="%.1f" fill="none" '
                 'class="sky-stroke-brass" stroke-width="1.5"/>'
                 % (x_t, y_disc, r + 4.5))
        p.append('<text x="%.1f" y="40" text-anchor="middle" class="todaylab">%s</text>'
                 % (x_t, self._t('today')))
        p.append('</svg>')
        return _svg_out(p, pal_name)

    # ── chips and table ──────────────────────────────────────────────────────
    @_panel_guard(needs=TIER_EXTRAS)
    def chips_html(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        body_color = pal['body']

        def dot_style(name: str) -> str:
            # The plate's value for this swatch, as CUSTOM PROPERTIES rather
            # than as `background` itself.  An HTML fragment cannot bring a
            # <style> with it the way an SVG can, so the color has to ride
            # inline -- but an inline `background` would outrank every rule a
            # consuming skin could write, short of !important, which is how
            # 2.4 first shipped these: themeable in the manual and immovable
            # in fact.  Setting only the variables leaves `background`
            # itself free, so sky.css's `.dot` rule reads them and any
            # consumer rule beats it on ordinary specificity.  The chip and
            # table rows carry data-body, so there is something to aim at.
            ring = pal.get('ring', {}).get(name)
            edge = ';--sky-dot-ring:%s' % ring if ring else ''
            return '--sky-dot:%s%s' % (body_color[name], edge)

        rows = []
        sun = self._body(alm, 'sun')
        tw = self._twilight(alm)
        rows.append(
            '<div class="chip" data-body="sun"><span class="dot" style="%s"></span>'
            '<div><div class="chipname">%s</div>'
            '<div class="chipline mono">%s</div>'
            '<div class="chipsub mono">%s</div></div></div>'
            % (dot_style('sun'), self._t('Daylight'),
               self._t('{duration} · sun {rise} → {set}',
                       duration=self._dur(sun['visible']),
                       rise=_t_hm(sun['rise']), set=_t_hm(sun['set'])),
               self._t('civil dusk {dusk} · astro dark {dark}',
                       dusk=_t_hm(tw['civil_dusk']), dark=_t_hm(tw['astro_dusk']))))
        for name in PLANETS:
            b = self._body(alm, name)
            if b['alt'] > 0:
                line = self._t('up now — alt {alt}° · az {az}°',
                               alt='%.0f' % b['alt'], az='%.0f' % b['az'])
            elif b['rise'] is not None:
                line = self._t('rises {time}', time=_t_hm(b['rise']))
            else:
                line = self._t('below the horizon')
            sub = self._t('mag {mag} · {dist} au · elong {elong}°',
                          mag='%+.1f' % b['mag'], dist='%.2f' % b['dist_au'],
                          elong='%.0f' % b['elong'])
            if b['constellation']:
                sub = '%s &#183; %s' % (self._t('in {constellation}',
                                                constellation=_esc(b['constellation'])), sub)
            extra = ''
            if name == 'jupiter':
                extra = ('<div class="chipsub mono">%s</div>'
                         % self._t('CML I {one}° · II {two}°',
                                   one='%.0f' % (math.degrees(alm.jupiter.cmlI) % 360.0),
                                   two='%.0f' % (math.degrees(alm.jupiter.cmlII) % 360.0)))
            elif name == 'saturn':
                extra = ('<div class="chipsub mono">%s</div>'
                         % self._t('ring tilt {tilt}°',
                                   tilt='%+.1f' % math.degrees(alm.saturn.earth_tilt)))
            rows.append(
                '<div class="chip" data-body="%s"><span class="dot" style="%s"></span>'
                '<div><div class="chipname">%s</div><div class="chipline mono">%s</div>'
                '<div class="chipsub mono">%s</div>%s</div></div>'
                % (_esc(name), dot_style(name), _esc(self._label(alm, name)),
                   line, sub, extra))
        # Configured comets with elements get a chip like any body: brass
        # dot, the same up-now/rises/below states, magnitude a dash when
        # the MPC row has no g/k.  One without elements is simply absent,
        # the dome convention.
        for name in self.comet_names():
            b = self._body(alm, name)
            if b['dist_au'] is None:
                continue
            if b['alt'] > 0:
                line = self._t('up now — alt {alt}° · az {az}°',
                               alt='%.0f' % b['alt'], az='%.0f' % b['az'])
            elif b['rise'] is not None:
                line = self._t('rises {time}', time=_t_hm(b['rise']))
            else:
                line = self._t('below the horizon')
            mag = '%+.1f' % b['mag'] if b['mag'] is not None else '&#8212;'
            sub = self._t('mag {mag} · {dist} au · elong {elong}°',
                          mag=mag, dist='%.2f' % b['dist_au'],
                          elong='%.0f' % b['elong'])
            if b['constellation']:
                sub = '%s &#183; %s' % (self._t('in {constellation}',
                                                constellation=_esc(b['constellation'])), sub)
            rows.append(
                '<div class="chip" data-body="%s"><span class="dot" style="--sky-dot:%s"></span>'
                '<div><div class="chipname">%s</div><div class="chipline mono">%s</div>'
                '<div class="chipsub mono">%s</div></div></div>'
                % (_esc(name), pal['brass'], _esc(self._label(alm, name)),
                   line, sub))
        return '\n'.join(rows)

    def _sat_when(self, alm, rise_ts: float, set_ts: Optional[float]) -> str:
        """The pass countdown, at the resolution a minutes-long event
        needs: 'overhead now' while the pass is in progress, minutes
        under an hour, hours under a day, then the countdown chips'
        day count.

        The sub-day branches are a resolution choice on elapsed time --
        'in 2 h' is what a go-watch reader wants, whichever side of
        midnight the pass falls on -- but the day count labels a row
        that also carries the pass DATE, so it is reckoned in calendar
        days like the countdown chips.  The floor of 1 covers the one
        hour a year when a fall-back DST day makes 24 elapsed hours land
        back on today's date."""
        now = alm.time_ts
        if set_ts is not None and rise_ts <= now < set_ts:
            return self._t('overhead now')
        delta = rise_ts - now
        if delta < 3600:
            return self._t('in {m} min', m=max(1, int(delta // 60)))
        if delta < 86400:
            return self._t('in {h} h', h=int(round(delta / 3600.0)))
        n = max(1, _days_until(now, rise_ts))
        if n == 1:
            return self._t('in {n} day', n=1)
        return self._t('in {n} days', n=n)

    @_panel_guard(needs=TIER_ENGINE)
    def satellites_html(self, alm, palette: str = 'night') -> str:
        """One row per configured satellite: its next visible pass -- the
        go-watch question -- in the planet chips' idiom.  A satellite with
        no qualifying pass in its elements' validity window says so
        honestly (HST from high latitudes is a permanent dash, and that is
        the truth), and one with no usable elements (an offline install, a
        stale cache) points at the log instead of guessing."""
        pal = _palette(palette)
        rows = []
        for name in self.satellite_names():
            d = self._sat_pass(alm, name)
            q = d['pass']
            sub = ''
            if q is not None:
                line = '%s %s · %s' % (self._date(q['rise']), _t_hm(q['rise']),
                                       self._sat_when(alm, q['rise'], q['set']))
                sub = self._t('appears {rise} · peaks {alt}° {culm} · disappears {set} · {m} min',
                              rise=_esc(q['rise_ord']), alt='%.0f' % q['max_alt'],
                              culm=_esc(q['culm_ord']), set=_esc(q['set_ord']),
                              m='%d' % round(q['duration'] / 60.0))
            elif d['usable']:
                line = self._t('no visible pass in the coming week')
            else:
                line = self._t('no usable orbital elements — see the weewxd log')
            rows.append('<div class="chip" data-body="%s">'
                        '<span class="dot" style="--sky-dot:%s"></span>'
                        '<div><div class="chipname">%s</div>'
                        '<div class="chipline mono">%s</div>%s</div></div>'
                        % (_esc(name), pal['brass'], _esc(self._label(alm, name)), line,
                           '<div class="chipsub mono">%s</div>' % sub if sub else ''))
        return '\n'.join(rows)

    @_panel_guard(needs=TIER_ENGINE)
    def moon_apsides_html(self, alm) -> str:
        """The lunation panel's apsis footer: the quiet next-perigee /
        next-apogee line, topped by a supermoon callout when the NEXT
        full moon is the next supermoon -- the rule itself lives in the
        engine's $almanac.next_supermoon tag (full moon within a day of
        perigee), read here rather than re-derived.  Anticipation only,
        like the satellite cards: the callout appears ahead of the event
        and leaves with it.  Colors come from the theme's CSS variables,
        not the palette, so the same markup serves both plates."""
        parts = []
        # _tag_raw, not _raw: next_supermoon and the moon's apsides are
        # engine tags, and an almanac that does not serve one raises on the
        # attribute read, outside _raw's reach.  The TIER_ENGINE floor keeps
        # the lesser almanacs out of here; this keeps the panel honest if
        # some future almanac serves only part of the set -- so the moon
        # hop goes through _tag_raw too, not just the tag after it.
        full = _tag_raw(alm, 'next_full_moon', 'unix_epoch')
        supermoon = _tag_raw(alm, 'next_supermoon', 'unix_epoch')
        if (full is not None and supermoon is not None
                and abs(supermoon - full) <= 60.0):
            parts.append('<p class="supermoon">%s</p>'
                         % self._t('Supermoon {date} — full moon within a day of perigee',
                                   date=self._date(full)))
        parts.append('<p class="apsis mono">%s &#183; %s</p>'
                     % (self._t('perigee {date}',
                                date=self._date_hm(_tag_raw(alm, 'moon.next_perigee', 'unix_epoch'))),
                        self._t('apogee {date}',
                                date=self._date_hm(_tag_raw(alm, 'moon.next_apogee', 'unix_epoch')))))
        return '\n'.join(parts)

    @_panel_guard(needs=TIER_EXTRAS)
    def table_html(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        body_color = pal['body']
        rows = []
        for name in CHART_BODIES:
            b = self._body(alm, name)
            if name == 'moon':
                dist = self._t('{dist} km', dist='{:,.0f}'.format(b['dist_au'] * 149597870.7))
            else:
                dist = self._t('{dist} au', dist='%.3f' % b['dist_au'])
            ring = pal.get('ring', {}).get(name)
            edge = ';--sky-dot-ring:%s' % ring if ring else ''
            rows.append('<tr data-body="%s"><td class="tname">'
                        '<span class="dot" style="--sky-dot:%s%s">'
                        '</span>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td>%+.1f&#176;</td><td>%.1f&#176;</td><td>%+.1f</td><td>%s</td></tr>'
                        % (_esc(name), body_color[name], edge,
                           _esc(self._label(alm, name)),
                           _t_hm(b['rise']), _t_hm(b['transit']), _t_hm(b['set']),
                           self._dur(b['visible']), b['alt'], b['az'], b['mag'], dist))
        # Configured comets with elements get a row like any body (brass
        # dot; a dash when the MPC row has no magnitude parameters); one
        # without elements is simply absent, the dome convention.
        for name in self.comet_names():
            b = self._body(alm, name)
            if b['dist_au'] is None:
                continue
            dist = self._t('{dist} au', dist='%.3f' % b['dist_au'])
            mag = '%+.1f' % b['mag'] if b['mag'] is not None else '&#8212;'
            rows.append('<tr data-body="%s"><td class="tname">'
                        '<span class="dot" style="--sky-dot:%s">'
                        '</span>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td>%+.1f&#176;</td><td>%.1f&#176;</td><td>%s</td><td>%s</td></tr>'
                        % (_esc(name), pal['brass'], _esc(self._label(alm, name)),
                           _t_hm(b['rise']), _t_hm(b['transit']), _t_hm(b['set']),
                           self._dur(b['visible']), b['alt'], b['az'], mag, dist))
        return ('<table><thead><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th>'
                '<th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th>'
                '</tr></thead><tbody>%s</tbody></table>'
                % (self._t('Body'), self._t('Rise'), self._t('Transit'), self._t('Set'),
                   self._t('Up for'), self._t('Altitude'), self._t('Azimuth'),
                   self._t('Mag'), self._t('Distance'), '\n'.join(rows)))


class SkyfieldSky(SearchList):
    """Exposes $sky_page to the Skyfield skin's templates."""

    def __init__(self, generator) -> None:
        SearchList.__init__(self, generator)

    def get_extension_list(self, timespan, db_lookup):
        # The report's skin_dict carries [Texts] (and [Labels]) for this
        # page's language -- each embedding report gets its own.
        return [{'sky_page': SkyPage(self.generator.skin_dict)}]
