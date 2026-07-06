"""
wxskyfield_sky.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

Search-list extension for the bundled Skyfield skin: renders the "Sky" page's
SVG panels (sky dome, rise/set ribbons, orrery, analemma, moon disc) and
HTML blocks server-side, from the same $almanac binder tags any template
could use.  The page is self-contained -- inline SVG, system fonts, no
JavaScript libraries and nothing fetched at run time.
"""

import math
import time

from typing import Any, Dict, List, Optional, Tuple

import weewx.almanac

from weewx.cheetahgenerator import SearchList

# ── palettes ─────────────────────────────────────────────────────────────────
# Every render method takes palette= naming an entry here.  'night' is the
# bundled Sky page's plate (see skins/Skyfield/sky.css); 'light' is the
# "paper atlas" plate for light-themed consuming skins.  Only baked SVG/HTML
# attributes come from the palette; typography stays class-based, styled by
# the consuming skin's CSS.  Keys: ink (star dots, curves, transit ticks),
# muted, brass (accents, now-markers), line (gridlines, orbit circles,
# altitude rings), halo (the stroke lifting body dots off the plate), body
# (identity colors, colorblind-validated against the plate surface),
# twilight (mid-tone enough that identity-colored ribbon bars stay readable
# on every band), the moon-disc fills/ring, the dome gradient stops and rim,
# and the orrery's sun and Earth.
PALETTES: Dict[str, Dict[str, Any]] = {
    'night': {
        'ink': '#E9E4D4', 'muted': '#8B93B8', 'brass': '#D3A94C',
        'line': '#2A3358', 'halo': '#0A0F22',
        'body': {'sun': '#B98C31', 'moon': '#7E92DA', 'mercury': '#AB763B',
                 'venus': '#D2B458', 'mars': '#C04F36', 'jupiter': '#D89A56',
                 'saturn': '#AC8F3E', 'uranus': '#35A8BE', 'neptune': '#5F85E6'},
        'twilight': {'night': '#0B1129', 'astro': '#131B38', 'naut': '#1A2547',
                     'civil': '#233153', 'day': '#2E3D5C'},
        'moon_dark': '#1E2745', 'moon_lit': '#DDD8C4', 'moon_ring': '#2A3358',
        'dome_stops': (('0%', '#161F3D'), ('72%', '#1B2749'), ('100%', '#2A3A63')),
        'dome_rim': '#D3A94C',
        'orrery_sun': '#D3A94C',
        'earth_fill': '#E9E4D4', 'earth_stroke': '#D3A94C',
    },
    'light': {
        'ink': '#1d2c4e', 'muted': '#5c6672', 'brass': '#B45309',
        'line': '#c9cfd8', 'halo': '#ffffff',
        'body': {'sun': '#B8860B', 'moon': '#4A5FB8', 'mercury': '#8a5a24',
                 'venus': '#a8862c', 'mars': '#b23a24', 'jupiter': '#b06f2e',
                 'saturn': '#8f7524', 'uranus': '#20808f', 'neptune': '#3a63c4',
                 'pluto': '#6a5f96'},
        'twilight': {'night': '#3A5175', 'astro': '#4A648C', 'naut': '#6C8FBF',
                     'civil': '#9FBCDE', 'day': '#D7E6F5'},
        'moon_dark': '#26314F', 'moon_lit': '#F2ECD8', 'moon_ring': '#888888',
        'dome_stops': (('0%', '#ffffff'), ('100%', '#efece2')),
        'dome_rim': '#8a94a6',
        'orrery_sun': '#B8860B',
        'earth_fill': '#2e6e8e', 'earth_stroke': '#ffffff',
    },
}


def _palette(name: str) -> Dict[str, Any]:
    if name not in PALETTES:
        raise ValueError('unknown palette %r; valid palettes: %s'
                         % (name, ', '.join(sorted(PALETTES))))
    return PALETTES[name]

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
    def sun_is_up(self, alm) -> bool:
        return bool(self._body(alm, 'sun')['alt'] > 0)

    def header_sub(self, alm, palette: str = 'night') -> str:
        _palette(palette)
        lat, lon = alm.lat, alm.lon
        return '%.2f&#176; %s &#183; %.2f&#176; %s &#183; %s' % (
            abs(lat), 'N' if lat >= 0 else 'S', abs(lon), 'E' if lon >= 0 else 'W',
            time.strftime('%A, %B %-d %Y, %-H:%M %Z', time.localtime(alm.time_ts)))

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

    def dome_svg(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        ink, line, halo, body_color = pal['ink'], pal['line'], pal['halo'], pal['body']
        S, cx, cy, R = 680, 340, 348, 296
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
            p.append('<text x="%d" y="%d" text-anchor="%s" class="mono cardinal">%s</text>'
                     % (cx + dx, cy + dy, anch, label))
        p.append('<text x="%d" y="%d" text-anchor="middle" class="mono gridlab">30&#176;</text>'
                 % (int(cx + 6 + R / 3), cy - 6))
        p.append('<text x="%d" y="%d" text-anchor="middle" class="mono gridlab">60&#176;</text>'
                 % (int(cx + 8 + R * 2 / 3), cy - 6))
        for s in self._stars(alm):
            x, y = self._dome_xy(cx, cy, R, s['az'], s['alt'])
            r = max(1.0, min(4.0, 3.2 - 0.62 * s['mag']))
            p.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" opacity="%.2f">'
                     '<title>%s &#8212; alt %.1f&#176;, az %.1f&#176;, mag %.2f</title></circle>'
                     % (x, y, r, ink, star_op, _esc(s['name']), s['alt'], s['az'], s['mag']))
            if s['mag'] <= STAR_LABEL_MAG:
                p.append('<text x="%.1f" y="%.1f" class="starlab" opacity="%.2f">%s</text>'
                         % (x + 6, y - 4, star_op + 0.05, _esc(s['name'])))
        for name in PLANETS:
            b = self._body(alm, name)
            if b['alt'] <= 0:
                continue
            x, y = self._dome_xy(cx, cy, R, b['az'], b['alt'])
            p.append('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="2">'
                     '<title>%s &#8212; alt %.1f&#176;, az %.1f&#176;, mag %.1f</title></circle>'
                     % (x, y, body_color[name], halo, _cap(name), b['alt'], b['az'], b['mag']))
            p.append('<text x="%.1f" y="%.1f" class="bodylab">%s</text>' % (x + 8, y + 4, _cap(name)))
        if sun['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, sun['az'], sun['alt'])
            for i in range(8):
                a = math.pi * i / 4
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>'
                         % (x + 11 * math.cos(a), y + 11 * math.sin(a),
                            x + 16 * math.cos(a), y + 16 * math.sin(a), body_color['sun']))
            p.append('<circle cx="%.1f" cy="%.1f" r="9" fill="%s" stroke="%s" stroke-width="1.5">'
                     '<title>Sun &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                     % (x, y, body_color['sun'], halo, sun['alt'], sun['az']))
            p.append('<text x="%.1f" y="%.1f" class="bodylab">Sun</text>' % (x + 19, y + 4))
        moon = self._body(alm, 'moon')
        if moon['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, moon['az'], moon['alt'])
            p.append('<g>%s<title>Moon &#8212; alt %.1f&#176;, az %.1f&#176;, %d%% illuminated</title></g>'
                     % (self._moon_disc(alm, x, y, 8, pal, ring=False),
                        moon['alt'], moon['az'], alm.moon_fullness))
            p.append('<text x="%.1f" y="%.1f" class="bodylab">Moon</text>' % (x + 12, y + 4))
        p.append('</svg>')
        return ''.join(p)

    # ── rise/set ribbons ─────────────────────────────────────────────────────
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
            p.append('<circle cx="14" cy="%.1f" r="4" fill="%s"/>' % (cy, color))
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
                p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="10" rx="4" fill="%s">'
                         '<title>%s above the horizon (%s)</title></rect>'
                         % (xa, cy - 5, xz - xa, color, _cap(b['name']), _dur_hm(b['visible'])))
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
        p.append('<text x="%d" y="%d" class="mono gridlab">0&#176;</text>' % (S - 26, cx - 6))
        p.append('<circle cx="%d" cy="%d" r="8" fill="%s"><title>Sun</title></circle>'
                 % (cx, cx, pal['orrery_sun']))
        hlongs = {name: self._body(alm, name)['hlong'] for name in PLANETS}
        hlongs['earth'] = alm.sun.hlong    # the sun tag reports Earth's, per XEphem
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
                         % (x, y, pal['body'][name], pal['halo'], _cap(name), hlongs[name]))
            # Label away from center, but flip near the right edge so a
            # body close to 0 degrees (Neptune, for years) is not clipped.
            anchor = 'start' if x >= cx else 'end'
            if anchor == 'start' and x > S - 64:
                anchor = 'end'
            p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="bodylab">%s</text>'
                     % (x + (8 if anchor == 'start' else -8), y + 4, anchor, _cap(name)))
        p.append('</svg>')
        return ''.join(p)

    # ── analemma ─────────────────────────────────────────────────────────────
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
        month_seen: set = set()
        for q in pts:
            mon = time.strftime('%b', time.localtime(q['ts']))
            first = mon not in month_seen
            month_seen.add(mon)
            p.append('<circle cx="%.1f" cy="%.1f" r="2" fill="%s">'
                     '<title>%s &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                     % (X(q['az']), Y(q['alt']), muted, _t_date(q['ts']), q['alt'], q['az']))
            if first and mon in ('Jan', 'Mar', 'Jun', 'Sep', 'Nov'):
                dx = 9 if q['az'] >= (az0 + az1) / 2 else -9
                p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="mono gridlab">%s</text>'
                         % (X(q['az']) + dx, Y(q['alt']) + 4, 'start' if dx > 0 else 'end', mon))
        today = min(pts, key=lambda q: abs(q['ts'] - alm.time_ts))
        p.append('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="1.5">'
                 '<title>This week &#8212; alt %.1f&#176;, az %.1f&#176;</title></circle>'
                 % (X(today['az']), Y(today['alt']), pal['brass'], pal['halo'],
                    today['alt'], today['az']))
        p.append('<text x="%.1f" y="%.1f" class="todaylab">today</text>'
                 % (X(today['az']) + 10, Y(today['alt']) + 4))
        p.append('</svg>')
        return ''.join(p)

    # ── chips and table ──────────────────────────────────────────────────────
    def chips_html(self, alm, palette: str = 'night') -> str:
        body_color = _palette(palette)['body']
        rows = []
        sun = self._body(alm, 'sun')
        tw = self._twilight(alm)
        rows.append(
            '<div class="chip"><span class="dot" style="background:%s"></span>'
            '<div><div class="chipname">Daylight</div>'
            '<div class="chipline mono">%s &#183; sun %s &#8594; %s</div>'
            '<div class="chipsub mono">civil dusk %s &#183; astro dark %s</div></div></div>'
            % (body_color['sun'], _dur_hm(sun['visible']), _t_hm(sun['rise']),
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
                '<div class="chip"><span class="dot" style="background:%s"></span>'
                '<div><div class="chipname">%s</div><div class="chipline mono">%s</div>'
                '<div class="chipsub mono">%s</div>%s</div></div>'
                % (body_color[name], _cap(name), line, sub, extra))
        return '\n'.join(rows)

    def table_html(self, alm, palette: str = 'night') -> str:
        body_color = _palette(palette)['body']
        rows = []
        for name in ['sun', 'moon'] + PLANETS:
            b = self._body(alm, name)
            if name == 'moon':
                dist = '{:,.0f} km'.format(b['dist_au'] * 149597870.7)
            else:
                dist = '%.3f au' % b['dist_au']
            rows.append('<tr><td class="tname"><span class="dot" style="background:%s">'
                        '</span>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td>%+.1f&#176;</td><td>%.1f&#176;</td><td>%+.1f</td><td>%s</td></tr>'
                        % (body_color[name], _cap(name), _t_hm(b['rise']), _t_hm(b['transit']),
                           _t_hm(b['set']), _dur_hm(b['visible']),
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
