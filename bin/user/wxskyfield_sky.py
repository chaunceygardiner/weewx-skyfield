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
        'conline': '#6C82C4',
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
        'conline': '#93A5C4',
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
        'conline': '#5F7BB8',
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
        'conline': '#93A5C4',
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

STAR_MAG_LIMIT = 2.6          # dome shows stars at least this bright (default)
STAR_LABEL_MAG = 1.1          # ... and labels these (default)
# The dome keeps constellation line vertices down to this altitude: a
# just-set star still anchors its segment (the dome's clipPath trims it at
# the rim), while the polar projection's blowup toward the antipode stays
# far away from the chart.
CON_ALT_FLOOR = -15.0

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


def _t_hm(ts: Optional[float]) -> str:
    return time.strftime('%H:%M', time.localtime(ts)) if ts else '&#8212;'


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
        val = (getattr(alm, 'texts', None) or {}).get(name)
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

    # ── shared data access (plain $almanac tags) ─────────────────────────────
    def _body(self, alm, name: str) -> Dict[str, Any]:
        key = (alm.time_ts, name)
        if key in self._memo:
            return self._memo[key]
        b = getattr(alm, name)
        d: Dict[str, Any] = {
            'name': name, 'az': b.az, 'alt': b.alt, 'mag': b.mag,
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

    def _stars(self, alm) -> List[Dict[str, Any]]:
        sky = _find_sky()
        if sky is None or not sky.stars:
            return []
        catalog = self._catalog_stars(alm, sky)
        if catalog is not None:
            return catalog
        seen, out = set(), []
        for name, hip in _wxskyfield().NAMED_STARS.items():
            if hip in seen or name not in sky.stars:
                continue
            mag = sky.stars[name][1]
            if mag is None or (mag > self._star_mag_limit and name != 'polaris'):
                continue
            seen.add(hip)
            b = getattr(alm, name)
            alt = b.alt
            if alt <= 0:
                continue
            out.append({'name': self._label(alm, name), 'named': True,
                        'az': b.az, 'alt': alt, 'mag': mag})
        return out

    def _catalog_stars(self, alm, sky) -> Optional[List[Dict[str, Any]]]:
        """The dome's stars from a full, user-installed hip_main.dat:
        every catalog star above the horizon at least star_mag_limit
        bright, dimmest first so the bright dots paint on top.  Stars
        with a NAMED_STARS name keep their translated label; the rest
        are anonymous dots whose tooltip names the Hipparcos number.
        None when only the bundled excerpt is installed -- the dome then
        falls back to the named stars."""
        amt = _find_almanac_type()
        if amt is None:
            return None
        field = amt.star_field(alm, self._star_mag_limit)
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
        texts = getattr(alm, 'texts', None)
        con_names = texts.get('Constellations') if isinstance(texts, dict) else None
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

    # ── template conveniences ─────────────────────────────────────────────────
    @_panel_guard(fallback=False)
    def sun_is_up(self, alm) -> bool:
        return bool(self._body(alm, 'sun')['alt'] > 0)

    @_panel_guard(fallback='dark')
    def theme(self, alm) -> str:
        """The page's resolved theme, 'dark' or 'light', from the report's
        theme option (dark | light | auto; default dark).  auto follows the
        sun at generation time: light while it is up, dark otherwise.  The
        page regenerates each report cycle, so the auto flip lags
        sunrise/sunset by at most one archive interval -- the palette is
        baked into the page; nothing shifts in the browser."""
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
            parts.append(self._t('Regenerated every report cycle'))
        return sep.join(parts).replace(
            'weewx-skyfield', '<a href="%s">weewx-skyfield</a>' % REPO_URL)

    @_panel_guard()
    def countdown_html(self, alm, palette: str = 'night') -> str:
        _palette(palette)

        def when_str(ts: float) -> str:
            n = max(0, int(math.ceil((ts - alm.time_ts) / 86400.0)))
            if n == 0:
                return self._t('today')
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
        return ('<svg width="%d" height="%d" viewBox="0 0 %d %d" aria-label="%s">%s</svg>'
                % (size, size, size, size, self._t('Moon phase'),
                   self._moon_disc(alm, c, c, c - 4, _palette(palette))))

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
        p = ['<svg viewBox="0 0 %d 706" role="img" aria-label="%s">'
             % (S, self._t('Sky dome chart'))]
        p.append('<defs><radialGradient id="skyg">%s</radialGradient>'
                 '<clipPath id="domec"><circle cx="%d" cy="%d" r="%d"/></clipPath></defs>'
                 % (''.join('<stop offset="%s" stop-color="%s"/>' % s
                            for s in pal['dome_stops']), cx, cy, R))
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
        c_n, c_e, c_s, c_w = self._cardinals(alm)
        for label, dx, dy, anch in ((c_n, 0, -R - 12, 'middle'), (c_s, 0, R + 22, 'middle'),
                                    (c_e, -R - 14, 5, 'end'), (c_w, R + 14, 5, 'start')):
            p.append('<text x="%d" y="%d" text-anchor="%s" class="mono cardinal" '
                     'style="font-size:%.1fpx">%s</text>'
                     % (cx + dx, cy + dy, anch, card_px, _esc(label)))
        p.append('<text x="%d" y="%d" text-anchor="middle" class="mono gridlab" '
                 'style="font-size:%.1fpx">30&#176;</text>'
                 % (int(cx + 6 + R / 3), cy - 6, grid_px))
        p.append('<text x="%d" y="%d" text-anchor="middle" class="mono gridlab" '
                 'style="font-size:%.1fpx">60&#176;</text>'
                 % (int(cx + 8 + R * 2 / 3), cy - 6, grid_px))
        con_labels: List[Tuple[float, float, str]] = []
        if self._constellation_lines:
            segs, con_labels = self._constellation_layer(alm, cx, cy, R)
            if segs:
                p.append('<g clip-path="url(#domec)" fill="none" stroke="%s" '
                         'stroke-width="1" stroke-linecap="round" opacity="%.2f">%s</g>'
                         % (pal['conline'], 0.40 if sun['alt'] > 0 else 0.55,
                            ''.join(segs)))
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
                     '<title>%s</title></circle>'
                     % (x, y, r, ink, star_op,
                        self._t('{name} — alt {alt}°, az {az}°, mag {mag}',
                                name=_esc(s['name']), alt='%.1f' % s['alt'],
                                az='%.1f' % s['az'], mag='%.2f' % s['mag'])))
            if s['named'] and s['mag'] <= self._star_label_mag:
                star_labels.append((x, y - 8, _esc(s['name'])))
        for name in PLANETS:
            b = self._body(alm, name)
            if b['alt'] <= 0:
                continue
            x, y = self._dome_xy(cx, cy, R, b['az'], b['alt'])
            label = self._label(alm, name)
            p.append('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="2">'
                     '<title>%s</title></circle>'
                     % (x, y, body_color[name], _ring(pal, name),
                        self._t('{name} — alt {alt}°, az {az}°, mag {mag}',
                                name=_esc(label), alt='%.1f' % b['alt'],
                                az='%.1f' % b['az'], mag='%.1f' % b['mag'])))
            _try_label(x, y, _esc(label), 'bodylab', 8, must=True)
        if sun['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, sun['az'], sun['alt'])
            for i in range(8):
                a = math.pi * i / 4
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>'
                         % (x + 11 * math.cos(a), y + 11 * math.sin(a),
                            x + 16 * math.cos(a), y + 16 * math.sin(a), body_color['sun']))
            p.append('<circle cx="%.1f" cy="%.1f" r="9" fill="%s" stroke="%s" stroke-width="1.5">'
                     '<title>%s</title></circle>'
                     % (x, y, body_color['sun'], _ring(pal, 'sun'),
                        self._t('{name} — alt {alt}°, az {az}°',
                                name=_esc(self._label(alm, 'sun')),
                                alt='%.1f' % sun['alt'], az='%.1f' % sun['az'])))
            _try_label(x, y, _esc(self._label(alm, 'sun')), 'bodylab', 19, must=True)
        moon = self._body(alm, 'moon')
        if moon['alt'] > 0:
            x, y = self._dome_xy(cx, cy, R, moon['az'], moon['alt'])
            p.append('<g>%s<title>%s</title></g>'
                     % (self._moon_disc(alm, x, y, 8, pal, ring=False),
                        self._t('{name} — alt {alt}°, az {az}°, {pct}% illuminated',
                                name=_esc(self._label(alm, 'moon')),
                                alt='%.1f' % moon['alt'], az='%.1f' % moon['az'],
                                pct='%d' % alm.moon_fullness)))
            _try_label(x, y, _esc(self._label(alm, 'moon')), 'bodylab', 12, must=True)
        for x, y, name in star_labels:
            _try_label(x, y, name, 'starlab', 6, must=False, opacity=star_op + 0.05)
        # Constellation names go last: background context that yields to
        # every body and star label (a collision simply drops the name --
        # its figure still shows).
        con_px = 10.0 * label_scale
        for x, y, name in con_labels:
            # Wider glyph estimate than the star labels': .conlab renders
            # uppercase with letter-spacing.
            est_w = 0.85 * con_px * len(name)
            box = (x - est_w / 2, y - con_px, x + est_w / 2, y + 3)
            if any(box[0] < o[2] and box[2] > o[0] and
                   box[1] < o[3] and box[3] > o[1] for o in placed):
                continue
            placed.append(box)
            deferred.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="conlab" '
                            'style="font-size:%.1fpx" opacity="%.2f">%s</text>'
                            % (x, y, con_px, star_op, _esc(name)))
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

        p = ['<svg viewBox="0 0 1080 %d" role="img" aria-label="%s">'
             % (H, self._t('Rise and set timeline'))]
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
            label = self._label(alm, b['name'])
            p.append('<circle cx="14" cy="%.1f" r="4" fill="%s"%s/>' % (cy, color, edge))
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
                p.append('<rect x="%.1f" y="%.1f" width="%.1f" height="10" rx="4" fill="%s"%s>'
                         '<title>%s</title></rect>'
                         % (xa, cy - 5, xz - xa, color, edge,
                            self._t('{name} above the horizon ({duration})',
                                    name=_esc(label), duration=self._dur(b['visible']))))
            if b['transit'] is not None and sod <= b['transit'] <= eod:
                xt = X(b['transit'])
                p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2">'
                         '<title>%s</title></line>'
                         % (xt, cy - 8, xt, cy + 8, ink,
                            self._t('{name} transit {time}', name=_esc(label),
                                    time=_t_hm(b['transit']))))
            p.append('<text x="%d" y="%.1f" class="mono timelab">%s</text>' % (X1 + 12, cy + 4, right))
        xn = X(alm.time_ts)
        p.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1.5" '
                 'class="nowpulse"/>' % (xn, TOP - 8, xn, TOP + plot_h, brass))
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono nowlab">%s</text>'
                 % (xn, TOP - 14, self._t('now {time}', time=_t_hm(alm.time_ts))))
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

        p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">'
             % (S, S, self._t('Solar system plan view'))]
        for a in SEMI_MAJOR_AU.values():
            p.append('<circle cx="%d" cy="%d" r="%.1f" fill="none" stroke="%s" '
                     'stroke-width="1" opacity="0.8"/>' % (cx, cx, orbit_r(a), pal['line']))
        p.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1" '
                 'stroke-dasharray="2 5" opacity="0.6"/>' % (cx + 44, cx, S - 12, cx, pal['muted']))
        p.append('<text x="%d" y="%d" text-anchor="end" class="mono gridlab">0&#176;</text>'
                 % (S - 8, cx - 8))
        sun_ring = pal.get('ring', {}).get('sun')
        p.append('<circle cx="%d" cy="%d" r="8" fill="%s"%s><title>%s</title></circle>'
                 % (cx, cx, pal['orrery_sun'],
                    ' stroke="%s" stroke-width="1.5"' % sun_ring if sun_ring else '',
                    _esc(self._label(alm, 'sun'))))
        hlongs = {name: self._body(alm, name)['hlong'] for name in PLANETS}
        hlongs['earth'] = alm.sun.hlong    # the sun tag reports Earth's, per XEphem
        labels: List[List[Any]] = []
        for name, a in SEMI_MAJOR_AU.items():
            h = math.radians(hlongs[name])
            r = orbit_r(a)
            x, y = cx + r * math.cos(h), cx - r * math.sin(h)
            disp = self._label(alm, name)
            title = self._t('{name} — heliocentric longitude {deg}°',
                            name=_esc(disp), deg='%.1f' % hlongs[name])
            if name == 'earth':
                p.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="%s" stroke-width="2">'
                         '<title>%s</title></circle>'
                         % (x, y, pal['earth_fill'], pal['earth_stroke'], title))
            else:
                p.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="%s" stroke-width="1.5">'
                         '<title>%s</title></circle>'
                         % (x, y, pal['body'][name], _ring(pal, name), title))
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

        p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">'
             % (S, S, self._t('Analemma'))]
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
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono gridlab">%s</text>'
                 % (X((az0 + az1) / 2), S - 18, self._t('azimuth')))
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

        # Months to label are picked by number — comparing strftime('%b')
        # output against English abbreviations loses every label on a
        # non-English OS locale.  The label text itself is strftime output,
        # so it renders in the station's locale like the panel dates do.
        month_seen: set = set()
        for q in pts:
            tm = time.localtime(q['ts'])
            first = tm.tm_mon not in month_seen
            month_seen.add(tm.tm_mon)
            p.append('<circle cx="%.1f" cy="%.1f" r="2" fill="%s">'
                     '<title>%s</title></circle>'
                     % (X(q['az']), Y(q['alt']), muted,
                        self._t('{date} — alt {alt}°, az {az}°', date=self._date(q['ts']),
                                alt='%.1f' % q['alt'], az='%.1f' % q['az'])))
            if first and tm.tm_mon in (1, 3, 6, 9, 11):
                if (abs(X(q['az']) - X(today['az'])) < 30
                        and abs(Y(q['alt']) - Y(today['alt'])) < 18):
                    continue
                lx, ly, anchor = _outward(q, 13)
                p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="mono gridlab">%s</text>'
                         % (lx, ly, anchor, time.strftime('%b', tm)))
        p.append('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="1.5">'
                 '<title>%s</title></circle>'
                 % (X(today['az']), Y(today['alt']), pal['brass'], pal['halo'],
                    self._t('This week — alt {alt}°, az {az}°',
                            alt='%.1f' % today['alt'], az='%.1f' % today['az'])))
        lx, ly, anchor = _outward(today, 17)
        p.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="todaylab">%s</text>'
                 % (lx, ly, anchor, self._t('today')))
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

        p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">'
             % (S, S, self._t('Sun path today'))]
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
        c_n, c_e, c_s, c_w = self._cardinals(alm)
        for az, label in ((0, c_n), (90, c_e), (180, c_s), (270, c_w), (360, c_n)):
            p.append('<text x="%.1f" y="%d" text-anchor="middle" class="mono cardinal" '
                     'style="font-size:12px">%s</text>' % (X(az), PY1 + 20, _esc(label)))

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
        sun_labels: List[Tuple[float, float]] = []
        for i, alt, az in sun_pts[:-1]:
            if i % 4 or alt < FLOOR:
                continue
            p.append('<circle cx="%.1f" cy="%.1f" r="1.9" fill="%s" opacity="0.9"/>'
                     % (X(az), Y(alt), ink))
            if i % 12 == 0 and alt > FLOOR + 4:
                sun_labels.append((X(az), Y(alt) - 7))
                p.append('<text x="%.1f" y="%.1f" text-anchor="middle" '
                         'class="mono gridlab">%02d</text>' % (X(az), Y(alt) - 7, i // 4))

        # ── times on the moon's curve ────────────────────────────────────────
        # The moon's 24-hour track is an open curve -- a lunar day outruns the
        # calendar day by ~50 minutes, so the track ends where it began minus
        # ~12 degrees of azimuth.  The two midnight endpoints get dots labeled
        # 00/24 when they clear the plot floor (near full moon that break sits
        # at the apex, where a user once reported it as a bug); rise, set and
        # transit are ticked and labeled with skin-formatted times.  Labels
        # dodge the sun's hour labels; the transit label yields to a nearby
        # endpoint label rather than crowd it.
        moon_ink = pal.get('ring', {}).get('moon', body_color['moon'])

        def _dodge(x: float, y: float, dy: float) -> float:
            for lx, ly in sun_labels:
                if abs(x - lx) < 26 and abs(y - ly) < 11:
                    return ly + dy
            return y

        ends = [(i, alt, az) for i, alt, az in (moon_pts[0], moon_pts[96])
                if alt >= FLOOR]
        for i, alt, az in ends:
            x, y = X(az), Y(alt)
            p.append('<g><title>%s</title>'
                     '<circle cx="%.1f" cy="%.1f" r="2.2" fill="%s"/>'
                     '<text x="%.1f" y="%.1f" text-anchor="%s" '
                     'class="mono moonlab">%s</text></g>'
                     % (self._t('Moon at {time} — the day’s track is open here: a lunar day runs about 50 minutes longer than a calendar day',
                                time='00:00' if i == 0 else '24:00'),
                        x, y, moon_ink,
                        x + (5 if i == 0 else -5), y - 5,
                        'start' if i == 0 else 'end', '00' if i == 0 else '24'))
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
                p.append('<g><title>%s</title>'
                         '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'stroke="%s" stroke-width="1.3"/>'
                         '<text x="%.1f" y="%.1f" text-anchor="middle" '
                         'class="mono moonlab">%s</text></g>'
                         % (self._t('Moon transit {time} — altitude {alt}°',
                                    time=str(vh), alt='%.1f' % alt),
                            x, y - 3, x, y - 8, moon_ink,
                            x, _dodge(x, y - 12, -12), vh))
            else:
                title = (self._t('Moonrise {time}', time=str(vh)) if kind == 'rise'
                         else self._t('Moonset {time}', time=str(vh)))
                p.append('<g><title>%s</title>'
                         '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'stroke="%s" stroke-width="1.3"/>'
                         '<text x="%.1f" y="%.1f" text-anchor="middle" '
                         'class="mono moonlab">%s%s</text></g>'
                         % (title, x, y - 4, x, y + 4, moon_ink,
                            x, _dodge(x, y + 15, 12), glyph, vh))
        moon = self._body(alm, 'moon')
        if moon['alt'] >= FLOOR:
            x, y = X(moon['az']), Y(moon['alt'])
            p.append('<g>%s<title>%s</title></g>'
                     % (self._moon_disc(alm, x, y, 7, pal, ring=False),
                        self._t('Moon now — alt {alt}°, az {az}°',
                                alt='%.1f' % moon['alt'], az='%.1f' % moon['az'])))
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
                     '<title>%s</title></circle>'
                     % (x, y, body_color['sun'], _ring(pal, 'sun'),
                        self._t('Sun now — alt {alt}°, az {az}°',
                                alt='%.1f' % sun['alt'], az='%.1f' % sun['az'])))
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

        p = ['<svg viewBox="0 0 1080 %d" role="img" aria-label="%s">'
             % (H, self._t('Day length through the year'))]
        for w, (ts, edges, rise, sset) in enumerate(cols):
            x = XW(w)
            for i, (h, shade) in enumerate(edges):
                h2 = edges[i + 1][0] if i + 1 < len(edges) else 24.0
                if h2 <= h:
                    continue
                rect = ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                        % (x, Y(h2), colw + 0.4, Y(h) - Y(h2), pal['twilight'][shade]))
                if shade == 'day' and rise is not None and sset is not None:
                    rect = rect[:-2] + ('><title>%s</title></rect>'
                                        % self._t('{date} — daylight {duration}',
                                                  date=self._date(ts),
                                                  duration=self._dur(max(0.0, sset - rise))))
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
        p.append('<text x="%.1f" y="%d" text-anchor="middle" class="todaylab">%s</text>'
                 % (XW(wf_now), TOP - 12, self._t('today')))
        p.append('</svg>')
        return ''.join(p)

    # ── the lunar month ──────────────────────────────────────────────────────
    @_panel_guard()
    def lunation_svg(self, alm, palette: str = 'night') -> str:
        """The current lunation, previous new moon to next, as a strip of
        thirty phase discs with the principal phases dated and today's disc
        ringed in brass."""
        pal = _palette(palette)
        prev_new = _raw(alm.previous_new_moon, 'unix_epoch')
        next_new = _raw(alm.next_new_moon, 'unix_epoch')
        if prev_new is None or next_new is None or next_new <= prev_new:
            raise ValueError('lunation anchors unavailable')
        span = float(next_new - prev_new)
        N, M, W = 30, 40, 1000
        y_disc, r = 66, 13

        def X(ts: float) -> float:
            return M + W * (ts - prev_new) / span

        p = ['<svg viewBox="0 0 1080 152" role="img" aria-label="%s">'
             % self._t('The lunar month')]
        today_i = int(round((alm.time_ts - prev_new) / span * (N - 1)))
        today_i = min(max(today_i, 0), N - 1)
        for i in range(N):
            ts = prev_new + span * i / (N - 1)
            a = alm(almanac_time=ts)
            x = M + W * i / (N - 1.0)
            p.append('<g>%s<title>%s</title></g>'
                     % (self._moon_disc(a, x, y_disc, r, pal),
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
            p.append('<line x1="%.1f" y1="86" x2="%.1f" y2="96" stroke="%s" '
                     'stroke-width="1" opacity="0.7"/>' % (x, x, pal['muted']))
            p.append('<text x="%.1f" y="115" text-anchor="middle" class="rowlab">%s</text>'
                     % (x, name))
            p.append('<text x="%.1f" y="133" text-anchor="middle" class="mono gridlab">%s</text>'
                     % (x, self._date(ts_q)))
        x_t = M + W * today_i / (N - 1.0)
        p.append('<circle cx="%.1f" cy="%d" r="%.1f" fill="none" stroke="%s" '
                 'stroke-width="1.5"/>' % (x_t, y_disc, r + 4.5, pal['brass']))
        p.append('<text x="%.1f" y="40" text-anchor="middle" class="todaylab">%s</text>'
                 % (x_t, self._t('today')))
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
                '<div class="chip"><span class="dot" style="%s"></span>'
                '<div><div class="chipname">%s</div><div class="chipline mono">%s</div>'
                '<div class="chipsub mono">%s</div>%s</div></div>'
                % (dot_style(name), _esc(self._label(alm, name)), line, sub, extra))
        return '\n'.join(rows)

    @_panel_guard()
    def table_html(self, alm, palette: str = 'night') -> str:
        pal = _palette(palette)
        body_color = pal['body']
        rows = []
        for name in ['sun', 'moon'] + PLANETS:
            b = self._body(alm, name)
            if name == 'moon':
                dist = self._t('{dist} km', dist='{:,.0f}'.format(b['dist_au'] * 149597870.7))
            else:
                dist = self._t('{dist} au', dist='%.3f' % b['dist_au'])
            ring = pal.get('ring', {}).get(name)
            edge = ';box-shadow:inset 0 0 0 1.5px %s' % ring if ring else ''
            rows.append('<tr><td class="tname"><span class="dot" style="background:%s%s">'
                        '</span>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                        '<td>%+.1f&#176;</td><td>%.1f&#176;</td><td>%+.1f</td><td>%s</td></tr>'
                        % (body_color[name], edge, _esc(self._label(alm, name)),
                           _t_hm(b['rise']), _t_hm(b['transit']), _t_hm(b['set']),
                           self._dur(b['visible']), b['alt'], b['az'], b['mag'], dist))
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
