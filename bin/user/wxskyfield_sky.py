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

import functools
import logging
import math
import time

from typing import Any, Callable, Dict, List, Optional, Tuple

import weewx.almanac

from weewx.cheetahgenerator import SearchList

log = logging.getLogger(__name__)

# ── palettes ─────────────────────────────────────────────────────────────────
# Every render method takes palette= naming an entry here.  'night' is the
# bundled Sky page's plate (see skins/Skyfield/sky.css); 'light' is the
# "paper atlas" plate for light-themed consuming skins.  Only baked SVG/HTML
# attributes come from the palette; typography stays class-based, styled by
# the consuming skin's CSS.  Keys: ink (star dots, curves, transit ticks),
# muted, brass (accents, now-markers), line (gridlines, orbit circles,
# altitude rings), halo (the stroke lifting body dots off the plate), body
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
# navy), and Neptune stays a readable mid-blue on the night plate.  The
# pre-1.5 colors survive as 'classic-night' / 'classic-light'.
PALETTES: Dict[str, Dict[str, Any]] = {
    'night': {
        'ink': '#E9E4D4', 'muted': '#8B93B8', 'brass': '#D3A94C',
        'line': '#2A3358', 'halo': '#0A0F22',
        'body': {'sun': '#FFD75E', 'moon': '#C9D0DA', 'mercury': '#9CA0AC',
                 'venus': '#F0E3BE', 'mars': '#C04F36', 'jupiter': '#D89A56',
                 'saturn': '#AC8F3E', 'uranus': '#35A8BE', 'neptune': '#5F85E6'},
        'ring': {},
        'twilight': {'night': '#0B1129', 'astro': '#131B38', 'naut': '#1A2547',
                     'civil': '#233153', 'day': '#2E3D5C'},
        'moon_dark': '#1E2745', 'moon_lit': '#DDD8C4', 'moon_ring': '#2A3358',
        'dome_stops': (('0%', '#161F3D'), ('72%', '#1B2749'), ('100%', '#2A3A63')),
        'dome_rim': '#D3A94C',
        'orrery_sun': '#FFD75E',
        'earth_fill': '#4FA3E3', 'earth_stroke': '#E9E4D4',
    },
    'light': {
        'ink': '#1d2c4e', 'muted': '#5c6672', 'brass': '#B45309',
        'line': '#c9cfd8', 'halo': '#ffffff',
        'body': {'sun': '#FACC15', 'moon': '#D6DAE0', 'mercury': '#52525B',
                 'venus': '#F0E4BE', 'mars': '#b23a24', 'jupiter': '#b06f2e',
                 'saturn': '#8f7524', 'uranus': '#20808f', 'neptune': '#3a63c4',
                 'pluto': '#6a5f96'},
        'ring': {'sun': '#C77F00', 'moon': '#767E8A', 'venus': '#9C8B4D'},
        'twilight': {'night': '#3A5175', 'astro': '#4A648C', 'naut': '#6C8FBF',
                     'civil': '#9FBCDE', 'day': '#D7E6F5'},
        'moon_dark': '#26314F', 'moon_lit': '#F2ECD8', 'moon_ring': '#888888',
        'dome_stops': (('0%', '#ffffff'), ('100%', '#efece2')),
        'dome_rim': '#8a94a6',
        'orrery_sun': '#FACC15',
        'earth_fill': '#2E7DBE', 'earth_stroke': '#1B5C8F',
    },
    # The pre-1.5 palettes, kept for skins attached to the old colors.
    'classic-night': {
        'ink': '#E9E4D4', 'muted': '#8B93B8', 'brass': '#D3A94C',
        'line': '#2A3358', 'halo': '#0A0F22',
        'body': {'sun': '#B98C31', 'moon': '#7E92DA', 'mercury': '#AB763B',
                 'venus': '#D2B458', 'mars': '#C04F36', 'jupiter': '#D89A56',
                 'saturn': '#AC8F3E', 'uranus': '#35A8BE', 'neptune': '#5F85E6'},
        'ring': {},
        'twilight': {'night': '#0B1129', 'astro': '#131B38', 'naut': '#1A2547',
                     'civil': '#233153', 'day': '#2E3D5C'},
        'moon_dark': '#1E2745', 'moon_lit': '#DDD8C4', 'moon_ring': '#2A3358',
        'dome_stops': (('0%', '#161F3D'), ('72%', '#1B2749'), ('100%', '#2A3A63')),
        'dome_rim': '#D3A94C',
        'orrery_sun': '#D3A94C',
        'earth_fill': '#E9E4D4', 'earth_stroke': '#D3A94C',
    },
    'classic-light': {
        'ink': '#1d2c4e', 'muted': '#5c6672', 'brass': '#B45309',
        'line': '#c9cfd8', 'halo': '#ffffff',
        'body': {'sun': '#B8860B', 'moon': '#4A5FB8', 'mercury': '#8a5a24',
                 'venus': '#a8862c', 'mars': '#b23a24', 'jupiter': '#b06f2e',
                 'saturn': '#8f7524', 'uranus': '#20808f', 'neptune': '#3a63c4',
                 'pluto': '#6a5f96'},
        'ring': {},
        'twilight': {'night': '#3A5175', 'astro': '#4A648C', 'naut': '#6C8FBF',
                     'civil': '#9FBCDE', 'day': '#D7E6F5'},
        'moon_dark': '#26314F', 'moon_lit': '#F2ECD8', 'moon_ring': '#888888',
        'dome_stops': (('0%', '#ffffff'), ('100%', '#efece2')),
        'dome_rim': '#8a94a6',
        'orrery_sun': '#B8860B',
        'earth_fill': '#2e6e8e', 'earth_stroke': '#ffffff',
    },
}


def _ring(pal: Dict[str, Any], name: str) -> str:
    """The stroke for a body's mark: its ring color if the palette gives it
    one (pale bodies on the light plate), else the plate's uniform halo."""
    return pal.get('ring', {}).get(name, pal['halo'])


class SkyPageUsageError(ValueError):
    """A template-author error (e.g. an unknown palette name).  Re-raised
    through the panel guard: it should fail loudly at development time,
    not blank a panel."""


def _palette(name: str) -> Dict[str, Any]:
    if name not in PALETTES:
        raise SkyPageUsageError('unknown palette %r; valid palettes: %s'
                                % (name, ', '.join(sorted(PALETTES))))
    return PALETTES[name]


def _panel_guard(fallback: Any = '') -> Callable:
    """Wrap a $sky_page render method so a failure costs only its own panel:
    the error is logged and the panel renders as `fallback`.  Without this,
    one raising tag takes out the whole Sky page for that report cycle --
    exactly how the (since-guarded) wild skyfield event time fixed in 1.3
    presented.  SkyPageUsageError passes through unchanged."""
    def decorate(method: Callable) -> Callable:
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            try:
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
SEMI_MAJOR_AU = {'mercury': 0.387, 'venus': 0.723, 'earth': 1.0, 'mars': 1.524,
                 'jupiter': 5.203, 'saturn': 9.537, 'uranus': 19.19, 'neptune': 30.07}

STAR_MAG_LIMIT = 2.6          # dome shows stars at least this bright
STAR_LABEL_MAG = 1.1          # ... and labels these


def _raw(value_helper) -> Optional[float]:
    try:
        return value_helper.raw
    except Exception:
        return None


def _t_hm(ts: Optional[float]) -> str:
    return time.strftime('%H:%M', time.localtime(ts)) if ts else '&#8212;'


def _t_date(ts: float) -> str:
    return time.strftime('%b %-d', time.localtime(ts))


def _dur_hm(seconds: Optional[float]) -> str:
    if seconds is None:
        return '&#8212;'
    return '%dh %02dm' % (int(seconds // 3600), int(seconds % 3600 // 60))


def _esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _cap(name: str) -> str:
    return name.capitalize()


def _wxskyfield():
    """The almanac module.  In an installed WeeWX, bin/user modules are
    importable only as the 'user' package (user.wxskyfield); the test
    suite imports them top-level.  Try the installed form first."""
    try:
        import user.wxskyfield as m
    except ImportError:
        import wxskyfield as m
    return m


def _find_sky():
    """The Sky engine of the registered Skyfield almanac (for the star
    catalog and its magnitudes), or None."""
    for a in getattr(weewx.almanac, 'almanacs', []):
        if isinstance(a, _wxskyfield().SkyfieldAlmanacType):
            return a.sky
    return None


class SkyPage:
    """The template-facing helper: each method returns a finished SVG or
    HTML fragment for one panel of the Sky page."""

    def __init__(self) -> None:
        # Per-page memo of body evaluations: rise/set searches are the
        # expensive tags and three panels need them.
        self._memo: Dict[Tuple[float, str], Dict[str, Any]] = {}

    # ── shared data access (plain $almanac tags) ─────────────────────────────
    def _body(self, alm, name: str) -> Dict[str, Any]:
        key = (alm.time_ts, name)
        if key in self._memo:
            return self._memo[key]
        b = getattr(alm, name)
        d: Dict[str, Any] = {
            'name': name, 'az': b.az, 'alt': b.alt, 'mag': b.mag,
            'rise': _raw(b.rise), 'set': _raw(b.set), 'transit': _raw(b.transit),
            'visible': _raw(b.visible),
            'circumpolar': bool(b.circumpolar), 'neverup': bool(b.neverup),
            'dist_au': b.earth_distance,
        }
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
            tw[label + '_dawn'] = _raw(a.sun(use_center=1).rise)
            tw[label + '_dusk'] = _raw(a.sun(use_center=1).set)
        self._memo[key] = tw
        return tw

    def _stars(self, alm) -> List[Dict[str, Any]]:
        sky = _find_sky()
        if sky is None or not sky.stars:
            return []
        seen, out = set(), []
        for name, hip in _wxskyfield().NAMED_STARS.items():
            if hip in seen or name not in sky.stars:
                continue
            mag = sky.stars[name][1]
            if mag is None or (mag > STAR_MAG_LIMIT and name != 'polaris'):
                continue
            seen.add(hip)
            b = getattr(alm, name)
            alt = b.alt
            if alt <= 0:
                continue
            out.append({'name': name.replace('_', ' ').title(),
                        'az': b.az, 'alt': alt, 'mag': mag})
        return out

    # ── template conveniences ─────────────────────────────────────────────────
    @_panel_guard(fallback=False)
    def sun_is_up(self, alm) -> bool:
        return bool(self._body(alm, 'sun')['alt'] > 0)

    @_panel_guard()
    def header_sub(self, alm, palette: str = 'night') -> str:
        _palette(palette)
        lat, lon = alm.lat, alm.lon
        return '%.2f&#176; %s &#183; %.2f&#176; %s &#183; %s' % (
            abs(lat), 'N' if lat >= 0 else 'S', abs(lon), 'E' if lon >= 0 else 'W',
            time.strftime('%A, %B %-d %Y, %-H:%M %Z', time.localtime(alm.time_ts)))

    @_panel_guard()
    def countdown_html(self, alm, palette: str = 'night') -> str:
        _palette(palette)
        chips = []
        for label, vh in (('new moon', alm.next_new_moon),
                          ('full moon', alm.next_full_moon),
                          ('equinox', alm.next_equinox),
                          ('solstice', alm.next_solstice)):
            ts = _raw(vh)
            if ts is None:
                continue
            n = max(0, int(math.ceil((ts - alm.time_ts) / 86400.0)))
            when = 'today' if n == 0 else ('in %d day%s' % (n, '' if n == 1 else 's'))
            chips.append('<div class="count"><span class="k">%s</span>'
                         '<span class="v mono">%s</span><span class="d">%s</span></div>'
                         % (label, _t_date(ts), when))
        return '\n'.join(chips)

    # ── moon disc ─────────────────────────────────────────────────────────────
    def _moon_disc(self, alm, cx: float, cy: float, R: float,
                   pal: Dict[str, Any], ring: bool = True) -> str:
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
        out = ['<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>' % (cx, cy, R, pal['moon_dark']),
               '<path d="%s" fill="%s"/>' % (path, pal['moon_lit'])]
        if ring:
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" '
                       'stroke="%s" stroke-width="1"/>' % (cx, cy, R, pal['moon_ring']))
        return ''.join(out)

    @_panel_guard()
    def moon_svg(self, alm, size: int = 76, palette: str = 'night') -> str:
        c = size / 2.0
        return ('<svg width="%d" height="%d" viewBox="0 0 %d %d" aria-label="Moon phase">%s</svg>'
                % (size, size, size, size, self._moon_disc(alm, c, c, c - 4, _palette(palette))))

    # ── sky dome ─────────────────────────────────────────────────────────────
    @staticmethod
    def _dome_xy(cx: float, cy: float, R: float, az: float, alt: float) -> Tuple[float, float]:
        r = R * (90.0 - alt) / 90.0
        a = math.radians(az)
        return cx - r * math.sin(a), cy - r * math.cos(a)

    @_panel_guard()
    def dome_svg(self, alm, palette: str = 'night', label_scale: float = 1.0) -> str:
        """label_scale grows every dome label (stars, bodies, cardinals, ring
        degrees) by that factor -- font sizes are emitted inline so the
        collision layout always matches the rendered size.  Useful for skins
        whose pages are scaled down (fixed-canvas smartphone layouts)."""
        pal = _palette(palette)
        ink, line, body_color = pal['ink'], pal['line'], pal['body']
        S, cx, cy, R = 680, 340, 348, 296
        star_px = 10.0 * label_scale
        body_px = 11.0 * label_scale
        card_px = 14.0 * label_scale
        grid_px = 10.0 * label_scale
        sun = self._body(alm, 'sun')
        star_op = 0.55 if sun['alt'] > 0 else 0.95
        p = ['<svg viewBox="0 0 %d 706" role="img" aria-label="Sky dome chart">' % S]
        p.append('<defs><radialGradient id="skyg">%s</radialGradient></defs>'
                 % ''.join('<stop offset="%s" stop-color="%s"/>' % s
                           for s in pal['dome_stops']))
        p.append('<circle cx="%d" cy="%d" r="%d" fill="url(#skyg)"/>' % (cx, cy, R))
        for alt in (30, 60):
            p.append('<circle cx="%d" cy="%d" r="%.1f" fill="none" stroke="%s" '
                     'stroke-width="1" stroke-dasharray="3 5" opacity="0.7"/>'
                     % (cx, cy, R * (90 - alt) / 90.0, line))
        p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1" opacity="0.5"/>'
                 % (cx - R, cy, cx + R, cy, line))
        p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1" opacity="0.5"/>'
                 % (cx, cy - R, cx, cy + R, line))
        p.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-width="1.5"/>'
                 % (cx, cy, R, pal['dome_rim']))
        for label, dx, dy, anch in (('N', 0, -R - 12, 'middle'), ('S', 0, R + 22, 'middle'),
                                    ('E', -R - 14, 5, 'end'), ('W', R + 14, 5, 'start')):
            p.append('<text x="%d" y="%d" text-anchor="%s" class="mono cardinal" '
                     'style="font-size:%.1fpx">%s</text>'
                     % (cx + dx, cy + dy, anch, card_px, label))
        p.append('<text x="%d" y="%d" text-anchor="middle" class="mono gridlab" '
                 'style="font-size:%.1fpx">30&#176;</text>'
                 % (int(cx + 6 + R / 3), cy - 6, grid_px))
        p.append('<text x="%d" y="%d" text-anchor="middle" class="mono gridlab" '
                 'style="font-size:%.1fpx">60&#176;</text>'
                 % (int(cx + 8 + R * 2 / 3), cy - 6, grid_px))
        # Labels are placed after every mark is drawn: body labels first (each
        # nudged vertically until it clears the ones already placed), then
        # star labels, which are simply dropped on a collision -- their dots
        # keep the hover title.  Bunched-up bodies (planets crowd the ecliptic)
        # otherwise print over each other.
        # Seed the collision list with the fixed chrome labels (cardinals and
        # ring degrees) so body labels dodge them too.
        placed: List[Tuple[float, float, float, float]] = []
        for fx, fy, fw in ((cx, cy - R - 12, card_px), (cx, cy + R + 22, card_px),
                           (cx - R - 14, cy + 5, card_px), (cx + R + 14, cy + 5, card_px),
                           (cx + 6 + R / 3.0, cy - 6, 2.0 * grid_px),
                           (cx + 8 + R * 2 / 3.0, cy - 6, 2.0 * grid_px)):
            placed.append((fx - fw, fy - card_px, fx + fw, fy + 4))
        deferred: List[str] = []

        def _try_label(x: float, y: float, text: str, cls: str, gap: float,
                       must: bool, opacity: Optional[float] = None) -> None:
            px = body_px if cls == 'bodylab' else star_px
            est_w = 0.62 * px * len(text)
            row_h = px + 3.0
            anchor = 'start'
            lx = x + gap
            if lx + est_w > S - 4:
                anchor = 'end'
                lx = x - gap
            ly = min(max(y + 4, row_h), 700.0)
            for _tries in range(5):
                x0 = lx if anchor == 'start' else lx - est_w
                box = (x0, ly - px, x0 + est_w, ly + 2)
                if not any(box[0] < o[2] and box[2] > o[0] and
                           box[1] < o[3] and box[3] > o[1] for o in placed):
                    break
                if not must:
                    return
                ly = min(ly + row_h, 700.0)
            placed.append((box[0], box[1], box[2], box[3]))
            op = '' if opacity is None else ' opacity="%.2f"' % opacity
            deferred.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="%s" '
                            'style="font-size:%.1fpx"%s>%s</text>'
                            % (lx, ly, anchor, cls, px, op, text))

        star_labels: List[Tuple[float, float, str]] = []
        for s in self._stars(alm):
            x, y = self._dome_xy(cx, cy, R, s['az'], s['alt'])
            r = max(1.0, min(4.0, 3.2 - 0.62 * s['mag']))
            p.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" opacity="%.2f">'
                     '<title>%s &#8212; alt %.1f&#176;, az %.1f&#176;, mag %.2f</title></circle>'
                     % (x, y, r, ink, star_op, _esc(s['name']), s['alt'], s['az'], s['mag']))
            if s['mag'] <= STAR_LABEL_MAG:
                star_labels.append((x, y - 8, _esc(s['name'])))
        for name in PLANETS:
            b = self._body(alm, name)
            if b['alt'] <= 0:
                continue
            x, y = self._dome_xy(cx, cy, R, b['az'], b['alt'])
            p.append('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="2">'
                     '<title>%s &#8212; alt %.1f&#176;, az %.1f&#176;, mag %.1f</title></circle>'
                     % (x, y, body_color[name], _ring(pal, name), _cap(name),
                        b['alt'], b['az'], b['mag']))
            _try_label(x, y, _cap(name), 'bodylab', 8, must=True)
        if sun['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, sun['az'], sun['alt'])
            for i in range(8):
                a = math.pi * i / 4
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>'
                         % (x + 11 * math.cos(a), y + 11 * math.sin(a),
                            x + 16 * math.cos(a), y + 16 * math.sin(a), body_color['sun']))
            p.append('<circle cx="%.1f" cy="%.1f" r="9" fill="%s" stroke="%s" stroke-width="1.5">'
                     '<title>Sun &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                     % (x, y, body_color['sun'], _ring(pal, 'sun'), sun['alt'], sun['az']))
            _try_label(x, y, 'Sun', 'bodylab', 19, must=True)
        moon = self._body(alm, 'moon')
        if moon['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, moon['az'], moon['alt'])
            p.append('<g>%s<title>Moon &#8212; alt %.1f&#176;, az %.1f&#176;, %d%% illuminated</title></g>'
                     % (self._moon_disc(alm, x, y, 8, pal, ring=False),
                        moon['alt'], moon['az'], alm.moon_fullness))
            _try_label(x, y, 'Moon', 'bodylab', 12, must=True)
        for x, y, name in star_labels:
            _try_label(x, y, name, 'starlab', 6, must=False, opacity=star_op + 0.05)
        p.extend(deferred)
        p.append('</svg>')
        return ''.join(p)

    # ── rise/set ribbons ─────────────────────────────────────────────────────
    @_panel_guard()
    def ribbons_svg(self, alm, palette: str = 'night') -> str:
        import weeutil.weeutil
        pal = _palette(palette)
        ink, line, brass, body_color = pal['ink'], pal['line'], pal['brass'], pal['body']
        sod = weeutil.weeutil.startOfDay(alm.time_ts)
        eod = sod + 86400
        X0, X1, ROW, TOP = 118, 952, 30, 34
        bodies = [self._body(alm, n) for n in ['sun', 'moon'] + PLANETS]
        H = TOP + ROW * len(bodies) + 34
        plot_h = ROW * len(bodies)

        def X(ts: float) -> float:
            return X0 + (X1 - X0) * (min(max(ts, sod), eod) - sod) / 86400.0

        p = ['<svg viewBox="0 0 1080 %d" role="img" aria-label="Rise and set timeline">' % H]
        tw = self._twilight(alm)
        sun = bodies[0]
        edges = [(sod, 'night'), (tw['astro_dawn'], 'astro'), (tw['nautical_dawn'], 'naut'),
                 (tw['civil_dawn'], 'civil'), (sun['rise'], 'day'), (sun['set'], 'civil'),
                 (tw['civil_dusk'], 'naut'), (tw['nautical_dusk'], 'astro'),
                 (tw['astro_dusk'], 'night')]
        edges = [(ts, shade) for ts, shade in edges if ts is not None]
        for i, (ts, shade) in enumerate(edges):
            end = edges[i + 1][0] if i + 1 < len(edges) else eod
            p.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="%s"/>'
                     % (X(ts), TOP, max(0.0, X(end) - X(ts)), plot_h, pal['twilight'][shade]))
        for h in range(0, 25, 3):
            x = X0 + (X1 - X0) * h / 24.0
            p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                     'stroke-width="1" opacity="0.35"/>' % (x, TOP, x, TOP + plot_h, line))
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%02d</text>'
                     % (x, TOP + plot_h + 18, h % 24))
        for i, b in enumerate(bodies):
            y = TOP + i * ROW
            cy = y + ROW / 2.0
            color = body_color[b['name']]
            # Pale bodies (palette 'ring' entries) get a 1px edge on their
            # legend dot, bars and transit tick so they hold up on the pale
            # daytime band; saturated bodies stay stroke-free as before.
            ring = pal.get('ring', {}).get(b['name'])
            edge = ' stroke="%s" stroke-width="1"' % ring if ring else ''
            p.append('<circle cx="14" cy="%.1f" r="4" fill="%s"%s/>' % (cy, color, edge))
            p.append('<text x="26" y="%.1f" class="rowlab">%s</text>' % (cy + 4, _cap(b['name'])))
            segs: List[Tuple[float, float]] = []
            if b['circumpolar']:
                segs, right = [(sod, eod)], 'always up'
            elif b['neverup']:
                right = 'never up'
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
                p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="10" rx="4" fill="%s"%s>'
                         '<title>%s above the horizon (%s)</title></rect>'
                         % (xa, cy - 5, xz - xa, color, edge,
                            _cap(b['name']), _dur_hm(b['visible'])))
            if b['transit'] is not None and sod <= b['transit'] <= eod:
                xt = X(b['transit'])
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2">'
                         '<title>%s transit %s</title></line>'
                         % (xt, cy - 8, xt, cy + 8, ink, _cap(b['name']), _t_hm(b['transit'])))
            p.append('<text x="%d" y="%.1f" class="mono timelab">%s</text>' % (X1 + 12, cy + 4, right))
        xn = X(alm.time_ts)
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1.5" '
                 'class="nowpulse"/>' % (xn, TOP - 8, xn, TOP + plot_h, brass))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono nowlab">now %s</text>'
                 % (xn, TOP - 14, _t_hm(alm.time_ts)))
        p.append('</svg>')
        return ''.join(p)

    # ── orrery ───────────────────────────────────────────────────────────────
    @_panel_guard()
    def orrery_svg(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        S, cx = 480, 240
        lo, hi = math.log(0.387), math.log(30.07)

        def orbit_r(a: float) -> float:
            return 44 + 176 * (math.log(a) - lo) / (hi - lo)

        p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Solar system plan view">' % (S, S)]
        for a in SEMI_MAJOR_AU.values():
            p.append('<circle cx="%d" cy="%d" r="%.1f" fill="none" stroke="%s" '
                     'stroke-width="1" opacity="0.8"/>' % (cx, cx, orbit_r(a), pal['line']))
        p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1" '
                 'stroke-dasharray="2 5" opacity="0.6"/>' % (cx + 44, cx, S - 12, cx, pal['muted']))
        p.append('<text x="%d" y="%d" text-anchor="end" class="mono gridlab">0&#176;</text>'
                 % (S - 8, cx - 8))
        sun_ring = pal.get('ring', {}).get('sun')
        p.append('<circle cx="%d" cy="%d" r="8" fill="%s"%s><title>Sun</title></circle>'
                 % (cx, cx, pal['orrery_sun'],
                    ' stroke="%s" stroke-width="1.5"' % sun_ring if sun_ring else ''))
        hlongs = {name: self._body(alm, name)['hlong'] for name in PLANETS}
        hlongs['earth'] = alm.sun.hlong    # the sun tag reports Earth's, per XEphem
        labels: List[List[Any]] = []
        for name, a in SEMI_MAJOR_AU.items():
            h = math.radians(hlongs[name])
            r = orbit_r(a)
            x, y = cx + r * math.cos(h), cx - r * math.sin(h)
            if name == 'earth':
                p.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="%s" stroke-width="2">'
                         '<title>Earth &#8212; heliocentric longitude %.1f&#176;</title></circle>'
                         % (x, y, pal['earth_fill'], pal['earth_stroke'], hlongs[name]))
            else:
                p.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="%s" stroke-width="1.5">'
                         '<title>%s &#8212; heliocentric longitude %.1f&#176;</title></circle>'
                         % (x, y, pal['body'][name], _ring(pal, name), _cap(name), hlongs[name]))
            # Label away from center, flipped when its estimated width would
            # leave the viewBox (a body near 0 degrees sits at the right rim
            # for years at a time), then clamped vertically.
            est_w = 8 + 7.0 * len(name)
            anchor = 'start' if x >= cx else 'end'
            if anchor == 'start' and x + est_w > S - 6:
                anchor = 'end'
            elif anchor == 'end' and x - est_w < 6:
                anchor = 'start'
            lx = x + (8 if anchor == 'start' else -8)
            ly = min(max(y + 4, 14.0), S - 8.0)
            x0 = lx if anchor == 'start' else lx - est_w
            labels.append([lx, ly, anchor, _cap(name), x0, x0 + est_w])
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
        return ''.join(p)

    # ── analemma ─────────────────────────────────────────────────────────────
    @_panel_guard()
    def analemma_svg(self, alm, palette: str = 'night') -> str:
        import calendar
        pal = _palette(palette)
        ink, muted, line = pal['ink'], pal['muted'], pal['line']
        year = time.localtime(alm.time_ts).tm_year
        # Local standard (not DST) noon, each week of the year.
        noon0 = calendar.timegm((year, 1, 1, 12, 0, 0)) + time.timezone
        pts = []
        for week in range(53):
            ts = noon0 + week * 7 * 86400
            a = alm(almanac_time=ts)
            pts.append({'ts': ts, 'alt': a.sun.alt, 'az': a.sun.az})
        S = 480
        azs, alts = [q['az'] for q in pts], [q['alt'] for q in pts]
        az0, az1 = min(azs) - 4, max(azs) + 4
        al0 = math.floor(min(alts) / 10.0) * 10 - 4
        al1 = math.ceil(max(alts) / 10.0) * 10 + 4

        def X(az: float) -> float:
            return 54 + (S - 78) * (az - az0) / (az1 - az0)

        def Y(al: float) -> float:
            return 20 + (S - 74) * (al1 - al) / (al1 - al0)

        p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Analemma">' % (S, S)]
        for al in range(int(al0) + 4, int(al1), 10):
            p.append('<line x1="54" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
                     'stroke-width="1" opacity="0.55"/>' % (Y(al), S - 24, Y(al), line))
            p.append('<text x="48" y="%.1f" text-anchor="end" class="mono gridlab">%d&#176;</text>'
                     % (Y(al) + 4, al))
        for az in range(int(az0) + 4, int(az1), 10):
            p.append('<line x1="%.1f" y1="20" x2="%.1f" y2="%d" stroke="%s" '
                     'stroke-width="1" opacity="0.35"/>' % (X(az), X(az), S - 54, line))
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%d&#176;</text>'
                     % (X(az), S - 36, az))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">azimuth</text>'
                 % (X((az0 + az1) / 2), S - 18))
        path = ' '.join('%s%.1f %.1f' % ('M' if i == 0 else 'L', X(q['az']), Y(q['alt']))
                        for i, q in enumerate(pts)) + ' Z'
        p.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.5" opacity="0.9"/>'
                 % (path, ink))
        # Labels sit radially outward from the figure's centroid, clear of the
        # curve at the lobes (Jun at the top, Dec/Jan at the bottom) and of
        # the axis labels; the today label owns its spot -- a month label
        # falling on it is skipped.
        today = min(pts, key=lambda q: abs(q['ts'] - alm.time_ts))
        az_c = sum(q['az'] for q in pts) / len(pts)
        al_c = sum(q['alt'] for q in pts) / len(pts)

        def _outward(q, dist: float) -> Tuple[float, float, str]:
            dx, dy = X(q['az']) - X(az_c), Y(q['alt']) - Y(al_c)
            n = math.hypot(dx, dy) or 1.0
            lx = X(q['az']) + dist * dx / n
            ly = min(max(Y(q['alt']) + dist * dy / n + 3, 14.0), S - 60.0)
            return lx, ly, ('start' if dx >= 0 else 'end')

        month_seen: set = set()
        for q in pts:
            mon = time.strftime('%b', time.localtime(q['ts']))
            first = mon not in month_seen
            month_seen.add(mon)
            p.append('<circle cx="%.1f" cy="%.1f" r="2" fill="%s">'
                     '<title>%s &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                     % (X(q['az']), Y(q['alt']), muted, _t_date(q['ts']), q['alt'], q['az']))
            if first and mon in ('Jan', 'Mar', 'Jun', 'Sep', 'Nov'):
                if (abs(X(q['az']) - X(today['az'])) < 30
                        and abs(Y(q['alt']) - Y(today['alt'])) < 18):
                    continue
                lx, ly, anchor = _outward(q, 13)
                p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="mono gridlab">%s</text>'
                         % (lx, ly, anchor, mon))
        p.append('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="1.5">'
                 '<title>This week &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                 % (X(today['az']), Y(today['alt']), pal['brass'], pal['halo'],
                    today['alt'], today['az']))
        lx, ly, anchor = _outward(today, 17)
        p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="todaylab">today</text>'
                 % (lx, ly, anchor))
        p.append('</svg>')
        return ''.join(p)

    # ── sun path ─────────────────────────────────────────────────────────────
    @_panel_guard()
    def sunpath_svg(self, alm, palette: str = 'night') -> str:
        """The sun's altitude/azimuth arc across today, midnight to midnight,
        over twilight-depth bands below the horizon; the moon's path dashed.
        The azimuth axis is the fixed full circle (N through E, S, W back to
        N) so the arc's seasonal swing reads at a glance and a circumpolar
        sun needs no special casing."""
        import weeutil.weeutil
        pal = _palette(palette)
        ink, line, body_color = pal['ink'], pal['line'], pal['body']
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

        p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Sun path today">' % (S, S)]
        # Day above the horizon, then the twilight depths below it.
        bands = [(top, 0.0, 'day'), (0.0, -6.0, 'civil'), (-6.0, -12.0, 'naut'),
                 (-12.0, -18.0, 'astro'), (-18.0, FLOOR, 'night')]
        for hi, lo, shade in bands:
            hi, lo = min(hi, top), max(lo, FLOOR)
            if hi <= lo:
                continue
            p.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" fill="%s"/>'
                     % (PX0, Y(hi), PX1 - PX0, Y(lo) - Y(hi), pal['twilight'][shade]))
        for alt in (30, 60, 90):
            if alt >= top:
                continue
            p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
                     'stroke-width="1" opacity="0.4"/>' % (PX0, Y(alt), PX1, Y(alt), line))
            p.append('<text x="%d" y="%.1f" text-anchor="end" class="mono gridlab">%d&#176;</text>'
                     % (PX0 - 6, Y(alt) + 4, alt))
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
                 'stroke-width="1" opacity="0.8"/>' % (PX0, Y(0), PX1, Y(0), ink))
        p.append('<text x="%d" y="%.1f" text-anchor="end" class="mono gridlab">0&#176;</text>'
                 % (PX0 - 6, Y(0) + 4, ))
        for az in range(45, 360, 45):
            p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                     'stroke-width="1" opacity="0.25"/>' % (X(az), PY0, X(az), PY1, line))
        for az, label in ((0, 'N'), (90, 'E'), (180, 'S'), (270, 'W'), (360, 'N')):
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono cardinal" '
                     'style="font-size:12px">%s</text>' % (X(az), PY1 + 20, label))

        def _paths(pts: List[Tuple[int, float, float]], style: str) -> None:
            seg: List[str] = []
            prev_az: Optional[float] = None
            for _i, alt, az in pts:
                if alt < FLOOR or (prev_az is not None and abs(az - prev_az) > 180):
                    if len(seg) > 1:
                        p.append('<path d="M%s" fill="none" %s/>' % (' L'.join(seg), style))
                    seg = []
                    prev_az = None
                if alt >= FLOOR:
                    seg.append('%.1f %.1f' % (X(az), Y(alt)))
                    prev_az = az
            if len(seg) > 1:
                p.append('<path d="M%s" fill="none" %s/>' % (' L'.join(seg), style))

        _paths(moon_pts, 'stroke="%s" stroke-width="1.3" stroke-dasharray="4 4" '
               'opacity="0.85"' % body_color['moon'])
        _paths(sun_pts, 'stroke="%s" stroke-width="2.2" opacity="0.95"' % body_color['sun'])
        for i, alt, az in sun_pts[:-1]:
            if i % 4 or alt < FLOOR:
                continue
            p.append('<circle cx="%.1f" cy="%.1f" r="1.9" fill="%s" opacity="0.9"/>'
                     % (X(az), Y(alt), ink))
            if i % 12 == 0 and alt > FLOOR + 4:
                p.append('<text x="%.1f" y="%.1f" text-anchor="middle" '
                         'class="mono gridlab">%02d</text>' % (X(az), Y(alt) - 7, i // 4))
        moon = self._body(alm, 'moon')
        if moon['alt'] >= FLOOR:
            x, y = X(moon['az']), Y(moon['alt'])
            p.append('<g>%s<title>Moon now &#8212; alt %.1f&#176;, az %.1f&#176;</title></g>'
                     % (self._moon_disc(alm, x, y, 7, pal, ring=False),
                        moon['alt'], moon['az']))
        sun = self._body(alm, 'sun')
        if sun['alt'] >= FLOOR:
            x, y = X(sun['az']), Y(sun['alt'])
            for k in range(8):
                a = math.pi * k / 4
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'stroke="%s" stroke-width="1.5"/>'
                         % (x + 9 * math.cos(a), y + 9 * math.sin(a),
                            x + 13 * math.cos(a), y + 13 * math.sin(a), body_color['sun']))
            p.append('<circle cx="%.1f" cy="%.1f" r="7" fill="%s" stroke="%s" stroke-width="1.5">'
                     '<title>Sun now &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                     % (x, y, body_color['sun'], _ring(pal, 'sun'), sun['alt'], sun['az']))
        p.append('</svg>')
        return ''.join(p)

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

    @_panel_guard()
    def daylength_svg(self, alm, palette: str = 'night') -> str:
        """Sunrise, sunset and the twilight depths for every week of the
        year, columns of local CLOCK time -- the DST steps are real and
        deliberate.  The solid curves are sunrise and sunset, the dashed
        curve is solar noon (the transit), the brass line is today."""
        import calendar
        pal = _palette(palette)
        ink, line, brass = pal['ink'], pal['line'], pal['brass']
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
            rise, sset = _raw(a.sun.rise), _raw(a.sun.set)
            noon = _raw(a.sun.transit)
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

        p = ['<svg viewBox="0 0 1080 %d" role="img" aria-label="Day length through the year">'
             % H]
        for w, (ts, edges, rise, sset) in enumerate(cols):
            x = XW(w)
            for i, (h, shade) in enumerate(edges):
                h2 = edges[i + 1][0] if i + 1 < len(edges) else 24.0
                if h2 <= h:
                    continue
                rect = ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                        % (x, Y(h2), colw + 0.4, Y(h) - Y(h2), pal['twilight'][shade]))
                if shade == 'day' and rise is not None and sset is not None:
                    rect = rect[:-2] + ('><title>%s &#8212; daylight %s</title></rect>'
                                        % (_t_date(ts), _dur_hm(max(0.0, sset - rise))))
                p.append(rect)
        for h in range(0, 25, 3):
            p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
                     'stroke-width="1" opacity="0.3"/>' % (X0, Y(h), X1, Y(h), line))
            p.append('<text x="%d" y="%.1f" text-anchor="end" class="mono gridlab">%02d</text>'
                     % (X0 - 8, Y(h) + 4, h % 24))
        for mon in range(1, 13):
            ts_m = calendar.timegm((year, mon, 1, 12, 0, 0)) + time.timezone
            wf = (ts_m - noon0) / (7 * 86400.0)
            if wf > 0.2:
                p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                         'stroke-width="1" opacity="0.25"/>'
                         % (XW(wf), TOP, XW(wf), TOP + PH, line))
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%s</text>'
                     % (min(XW(wf + 2.2), X1 - 10.0), TOP + PH + 20,
                        time.strftime('%b', time.localtime(ts_m))))

        def _curve(hours: List[Optional[float]], style: str) -> None:
            seg: List[str] = []
            for w, h in enumerate(hours):
                if h is None:
                    if len(seg) > 1:
                        p.append('<path d="M%s" fill="none" %s/>' % (' L'.join(seg), style))
                    seg = []
                    continue
                seg.append('%.1f %.1f' % (XW(w + 0.5), Y(h)))
            if len(seg) > 1:
                p.append('<path d="M%s" fill="none" %s/>' % (' L'.join(seg), style))

        _curve(noon_h, 'stroke="%s" stroke-width="1" stroke-dasharray="3 4" opacity="0.7"' % ink)
        _curve(rise_h, 'stroke="%s" stroke-width="1.5" opacity="0.95"' % ink)
        _curve(set_h, 'stroke="%s" stroke-width="1.5" opacity="0.95"' % ink)
        wf_now = min(max((alm.time_ts - noon0) / (7 * 86400.0) + 0.5, 0.0), float(WEEKS))
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1.5"/>'
                 % (XW(wf_now), TOP - 8, XW(wf_now), TOP + PH, brass))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="todaylab">today</text>'
                 % (XW(wf_now), TOP - 12))
        p.append('</svg>')
        return ''.join(p)

    # ── the lunar month ──────────────────────────────────────────────────────
    @_panel_guard()
    def lunation_svg(self, alm, palette: str = 'night') -> str:
        """The current lunation, previous new moon to next, as a strip of
        thirty phase discs with the principal phases dated and today's disc
        ringed in brass."""
        pal = _palette(palette)
        prev_new = _raw(alm.previous_new_moon)
        next_new = _raw(alm.next_new_moon)
        if prev_new is None or next_new is None or next_new <= prev_new:
            raise ValueError('lunation anchors unavailable')
        span = float(next_new - prev_new)
        N, M, W = 30, 40, 1000
        y_disc, r = 66, 13

        def X(ts: float) -> float:
            return M + W * (ts - prev_new) / span

        p = ['<svg viewBox="0 0 1080 152" role="img" aria-label="The lunar month">']
        today_i = int(round((alm.time_ts - prev_new) / span * (N - 1)))
        today_i = min(max(today_i, 0), N - 1)
        for i in range(N):
            ts = prev_new + span * i / (N - 1)
            a = alm(almanac_time=ts)
            x = M + W * i / (N - 1.0)
            p.append('<g>%s<title>%s &#8212; %d%% illuminated</title></g>'
                     % (self._moon_disc(a, x, y_disc, r, pal), _t_date(ts), a.moon_fullness))
        aq = alm(almanac_time=prev_new + 3600)
        quarters = ((prev_new, 'new'),
                    (_raw(aq.next_first_quarter_moon), 'first quarter'),
                    (_raw(aq.next_full_moon), 'full'),
                    (_raw(aq.next_last_quarter_moon), 'last quarter'),
                    (next_new, 'new'))
        for ts_q, name in quarters:
            if ts_q is None or not prev_new <= ts_q <= next_new:
                continue
            x = X(ts_q)
            p.append('<line x1="%.1f" y1="86" x2="%.1f" y2="96" stroke="%s" '
                     'stroke-width="1" opacity="0.7"/>' % (x, x, pal['muted']))
            p.append('<text x="%.1f" y="115" text-anchor="middle" class="rowlab">%s</text>'
                     % (x, name))
            p.append('<text x="%.1f" y="133" text-anchor="middle" class="mono gridlab">%s</text>'
                     % (x, _t_date(ts_q)))
        x_t = M + W * today_i / (N - 1.0)
        p.append('<circle cx="%.1f" cy="%d" r="%.1f" fill="none" stroke="%s" '
                 'stroke-width="1.5"/>' % (x_t, y_disc, r + 4.5, pal['brass']))
        p.append('<text x="%.1f" y="40" text-anchor="middle" class="todaylab">today</text>'
                 % x_t)
        p.append('</svg>')
        return ''.join(p)

    # ── chips and table ──────────────────────────────────────────────────────
    @_panel_guard()
    def chips_html(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        body_color = pal['body']

        def dot_style(name: str) -> str:
            # An inset ring (no layout change) for pale bodies, mirroring the
            # chart marks; skins size and shape .dot themselves.
            ring = pal.get('ring', {}).get(name)
            edge = ';box-shadow:inset 0 0 0 1.5px %s' % ring if ring else ''
            return 'background:%s%s' % (body_color[name], edge)

        rows = []
        sun = self._body(alm, 'sun')
        tw = self._twilight(alm)
        rows.append(
            '<div class="chip"><span class="dot" style="%s"></span>'
            '<div><div class="chipname">Daylight</div>'
            '<div class="chipline mono">%s &#183; sun %s &#8594; %s</div>'
            '<div class="chipsub mono">civil dusk %s &#183; astro dark %s</div></div></div>'
            % (dot_style('sun'), _dur_hm(sun['visible']), _t_hm(sun['rise']),
               _t_hm(sun['set']), _t_hm(tw['civil_dusk']), _t_hm(tw['astro_dusk'])))
        for name in PLANETS:
            b = self._body(alm, name)
            if b['alt'] > 0:
                line = 'up now &#8212; alt %.0f&#176; &#183; az %.0f&#176;' % (b['alt'], b['az'])
            elif b['rise'] is not None:
                line = 'rises %s' % _t_hm(b['rise'])
            else:
                line = 'below the horizon'
            sub = ('mag %+.1f &#183; %.2f au &#183; elong %.0f&#176;'
                   % (b['mag'], b['dist_au'], b['elong']))
            extra = ''
            if name == 'jupiter':
                extra = ('<div class="chipsub mono">CML I %.0f&#176; &#183; II %.0f&#176;</div>'
                         % (math.degrees(alm.jupiter.cmlI) % 360.0,
                            math.degrees(alm.jupiter.cmlII) % 360.0))
            elif name == 'saturn':
                extra = ('<div class="chipsub mono">ring tilt %+.1f&#176;</div>'
                         % math.degrees(alm.saturn.earth_tilt))
            rows.append(
                '<div class="chip"><span class="dot" style="%s"></span>'
                '<div><div class="chipname">%s</div><div class="chipline mono">%s</div>'
                '<div class="chipsub mono">%s</div>%s</div></div>'
                % (dot_style(name), _cap(name), line, sub, extra))
        return '\n'.join(rows)

    @_panel_guard()
    def table_html(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        body_color = pal['body']
        rows = []
        for name in ['sun', 'moon'] + PLANETS:
            b = self._body(alm, name)
            if name == 'moon':
                dist = '{:,.0f} km'.format(b['dist_au'] * 149597870.7)
            else:
                dist = '%.3f au' % b['dist_au']
            ring = pal.get('ring', {}).get(name)
            edge = ';box-shadow:inset 0 0 0 1.5px %s' % ring if ring else ''
            rows.append('<tr><td class="tname"><span class="dot" style="background:%s%s">'
                        '</span>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td>%+.1f&#176;</td><td>%.1f&#176;</td><td>%+.1f</td><td>%s</td></tr>'
                        % (body_color[name], edge, _cap(name), _t_hm(b['rise']),
                           _t_hm(b['transit']), _t_hm(b['set']), _dur_hm(b['visible']),
                           b['alt'], b['az'], b['mag'], dist))
        return ('<table><thead><tr><th>Body</th><th>Rise</th><th>Transit</th><th>Set</th>'
                '<th>Up for</th><th>Altitude</th><th>Azimuth</th><th>Mag</th><th>Distance</th>'
                '</tr></thead><tbody>%s</tbody></table>' % '\n'.join(rows))


class SkyfieldSky(SearchList):
    """Exposes $sky_page to the Skyfield skin's templates."""

    def __init__(self, generator) -> None:
        SearchList.__init__(self, generator)

    def get_extension_list(self, timespan, db_lookup):
        return [{'sky_page': SkyPage()}]
