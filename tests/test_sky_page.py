"""
test_sky_page.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

Tests for the bundled Skyfield skin's search-list helper (wxskyfield_sky.py):
every panel must render well-formed markup from a real almanac, and the
Cheetah template and skin.conf must parse.
"""

import contextlib
import logging
import os
import re
import sys
import time

import pytest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TEST_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, 'bin', 'user'))

os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

import weewx.almanac
import weewx.units

import wxskyfield
import wxskyfield_sky

LATITUDE   = 37.4419
LONGITUDE  = -122.143
ALTITUDE_M = 9.0
TIME_TS    = 1750532400      # 2025-06-21 12:00:00 PDT
GAP_TS     = 1785178800      # 2026-07-27 12:00:00 PDT (moon transits ~midnight)

# The footer links the extension's name to the manual, in every language.
LINKED_NAME = ('<a href="%s">weewx-skyfield</a>'
               % wxskyfield_sky.REPO_URL)


@pytest.fixture(scope='module')
def sky():
    s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=True)
    assert s.is_valid()
    return s


@contextlib.contextmanager
def saved_almanacs():
    saved = list(weewx.almanac.almanacs)
    try:
        yield
    finally:
        weewx.almanac.almanacs[:] = saved


@pytest.fixture()
def almanac(sky):
    with saved_almanacs():
        assert wxskyfield.register_almanac(sky)
        yield weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                    formatter=weewx.units.get_default_formatter())


@pytest.fixture()
def page():
    return wxskyfield_sky.SkyPage()


def assert_balanced(markup: str):
    """Every panel must be non-empty, balanced markup with no leaked None."""
    assert markup
    assert 'None' not in markup
    for tag in ('svg', 'g', 'div', 'table', 'defs'):
        opens = len(re.findall(r'<%s[ >]' % tag, markup))
        closes = markup.count('</%s>' % tag)
        assert opens == closes, '%s: %d opened, %d closed' % (tag, opens, closes)
    # Self-closing-free sanity for the paired shape tags we emit with children.
    assert markup.count('<title>') == markup.count('</title>')


class TestPanels:
    def test_dome(self, almanac, page):
        svg = page.dome_svg(almanac)
        assert_balanced(svg)
        # On the 2025-06-21 test date/time the sun is up and Mars is up.
        assert '<title>Sun' in svg
        assert '<title>Mars' in svg
        # Stars render (dimmed by daylight, but present).
        assert 'starlab' in svg

    def test_dome_without_stars(self, page):
        """With the star catalog disabled the dome must still render."""
        starless = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False)
        with saved_almanacs():
            assert wxskyfield.register_almanac(starless)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = page.dome_svg(alm)
        assert_balanced(svg)
        assert 'starlab' not in svg

    def test_ribbons(self, almanac, page):
        svg = page.ribbons_svg(almanac)
        assert_balanced(svg)
        for body in ('Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter',
                     'Saturn', 'Uranus', 'Neptune'):
            assert '>%s</text>' % body in svg
        assert 'now ' in svg

    def test_orrery(self, almanac, page):
        svg = page.orrery_svg(almanac)
        assert_balanced(svg)
        assert '<title>Earth' in svg
        assert svg.count('<circle') >= 17    # 8 orbits + sun + 9 bodies

    def test_analemma(self, almanac, page):
        svg = page.analemma_svg(almanac)
        assert_balanced(svg)
        assert svg.count('<circle') >= 54    # 53 weekly points + today
        assert 'today' in svg
        assert '>Mar</text>' in svg and '>Nov</text>' in svg

    def test_analemma_month_labels_non_english_locale(self, almanac, page, monkeypatch):
        """Month labels are picked by month number and rendered with
        strftime, so a non-English OS locale keeps its labels -- in its
        own language.  Regression: through 1.11 the pick compared
        strftime('%b') output against 'Jan'/'Mar'/... and every label
        silently vanished on such stations."""
        real_strftime = time.strftime
        german = {1: 'Jan', 2: 'Feb', 3: 'Mär', 4: 'Apr', 5: 'Mai', 6: 'Jun',
                  7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Dez'}

        def strftime_de(fmt, tt=None):
            if tt is None:
                tt = time.localtime()
            if fmt == '%b':
                return german[tt.tm_mon]
            return real_strftime(fmt, tt)

        monkeypatch.setattr(time, 'strftime', strftime_de)
        svg = page.analemma_svg(almanac)
        assert_balanced(svg)
        assert '>Mär</text>' in svg
        assert '>Nov</text>' in svg

    def test_moon_svg(self, almanac, page):
        svg = page.moon_svg(almanac)
        assert_balanced(svg)
        assert '<path' in svg

    def test_sunpath(self, almanac, page):
        svg = page.sunpath_svg(almanac)
        assert_balanced(svg)
        # Test noon: the sun is high and the moon is up too.
        assert '<title>Sun now' in svg
        assert '<title>Moon now' in svg
        for cardinal in ('N', 'E', 'S', 'W'):
            assert '>%s</text>' % cardinal in svg

    def test_sunpath_moon_times(self, almanac, page):
        """Moonrise, moonset and the transit are ticked on the moon's curve,
        labeled with the report formatter's times.  On 2025-06-21 all three
        fall inside the plotted day, and the midnight endpoints hide below
        the plot floor, so no 00/24 open-track markers appear."""
        svg = page.sunpath_svg(almanac)
        assert_balanced(svg)
        assert '<title>Moonrise %s</title>' % almanac.moon.rise in svg
        assert '<title>Moonset %s</title>' % almanac.moon.set in svg
        assert '<title>Moon transit %s' % almanac.moon.transit in svg
        assert 'Moon at 00:00' not in svg
        assert 'Moon at 24:00' not in svg

    def test_sunpath_open_ends(self, sky, page):
        """Near full moon the moon transits about midnight, so the plotted
        24-hour track is visibly open at the apex (2026-07-27, the day a
        user reported the open track as a gap-shaped bug): the midnight
        endpoints get dots labeled 00/24 with the lunar-day tooltip, and
        the transit -- outside the plotted day -- is not labeled."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(GAP_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = page.sunpath_svg(alm)
        assert_balanced(svg)
        assert 'Moon at 00:00' in svg
        assert 'Moon at 24:00' in svg
        assert '>00</text>' in svg and '>24</text>' in svg
        assert 'lunar day' in svg
        assert 'Moon transit' not in svg
        assert '<title>Moonrise' in svg and '<title>Moonset' in svg

    def test_daylength(self, almanac, page):
        svg = page.daylength_svg(almanac)
        assert_balanced(svg)
        # A titled daylight rect for (nearly) every week of the year.
        assert svg.count('daylight ') >= 50
        assert 'today' in svg
        for mon in ('Jan', 'Jun', 'Dec'):
            assert '>%s</text>' % mon in svg

    def test_lunation(self, almanac, page):
        svg = page.lunation_svg(almanac)
        assert_balanced(svg)
        assert svg.count('% illuminated') == 30
        assert 'first quarter' in svg and 'full' in svg and 'last quarter' in svg
        assert svg.count('>new</text>') == 2      # both ends of the lunation
        assert 'today' in svg

    def test_chips_and_table(self, almanac, page):
        chips = page.chips_html(almanac)
        assert_balanced(chips)
        assert 'CML I' in chips and 'ring tilt' in chips
        assert 'in Leo' in chips                  # Mars's constellation, June 2025
        table = page.table_html(almanac)
        assert_balanced(table)
        assert table.count('<tr>') == 10     # header + 9 bodies

    def test_unit_group_overrides(self, sky):
        """A report's [Units] [[Groups]] preferences (e.g. a station-wide
        group_deltatime = hour, group_time = unix_epoch_ms) reach the
        almanac's ValueHelpers through the report converter, which
        converts at construction -- .raw is unformatted, not unconverted.
        Every panel must render identically to a default-units report.
        Field case: group_deltatime = hour fed hours into the panels'
        seconds arithmetic and every duration rendered as 0h 00m."""
        groups = dict(weewx.units.MetricUnits,
                      group_deltatime='hour', group_time='unix_epoch_ms')
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            formatter = weewx.units.get_default_formatter()
            plain = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                          altitude=ALTITUDE_M, formatter=formatter)
            overridden = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                               altitude=ALTITUDE_M, formatter=formatter,
                                               converter=weewx.units.Converter(groups))
            for method in ('header_sub', 'countdown_html', 'moon_svg', 'dome_svg',
                           'ribbons_svg', 'orrery_svg', 'analemma_svg', 'sunpath_svg',
                           'daylength_svg', 'lunation_svg', 'chips_html', 'table_html'):
                # A fresh SkyPage per render: the per-page memo is keyed on
                # the almanac's time, which both almanacs share.
                want = getattr(wxskyfield_sky.SkyPage(), method)(plain)
                got = getattr(wxskyfield_sky.SkyPage(), method)(overridden)
                assert got == want, method
            table = wxskyfield_sky.SkyPage().table_html(overridden)
            assert '0h 00m' not in table
            assert re.search(r'14h \d\dm', table)   # the solstice sun, up ~14h46m

    def test_header_bits(self, almanac, page):
        assert 'N' in page.header_sub(almanac)
        countdown = page.countdown_html(almanac)
        assert countdown.count('class="count"') == 5
        # The eclipse chip: the nearer of the next visible lunar/solar
        # eclipse (from Palo Alto in June 2025, the 2026-03-03 total
        # lunar), its date carrying the year since it can be years out.
        assert 'lunar eclipse' in countdown
        assert 'Mar 3 2026' in countdown
        assert 'total' in countdown
        assert page.sun_is_up(almanac) is True

    def test_star_lookup_in_installed_weewx(self, almanac, page, monkeypatch):
        """In an installed WeeWX, bin/user modules are importable only as
        the 'user' package (user.wxskyfield); a plain 'import wxskyfield'
        raises ModuleNotFoundError at report time.  Regression test: the
        helper must find the almanac module either way."""
        import types
        fake_user = types.ModuleType('user')
        fake_user.wxskyfield = wxskyfield
        monkeypatch.setitem(sys.modules, 'user', fake_user)
        monkeypatch.setitem(sys.modules, 'user.wxskyfield', wxskyfield)
        # Make the top-level name unimportable, as on a real install.  A
        # fresh fallback re-import would also break isinstance checks (a
        # second copy of the module has different class objects).
        monkeypatch.delitem(sys.modules, 'wxskyfield')
        monkeypatch.setattr(sys, 'path',
                            [p for p in sys.path
                             if not p.endswith(os.path.join('bin', 'user'))])
        assert wxskyfield_sky._find_sky() is not None
        svg = page.dome_svg(almanac)
        assert_balanced(svg)
        assert 'starlab' in svg

    def test_memo_reused_across_panels(self, almanac, page):
        page.ribbons_svg(almanac)
        n = len(page._memo)
        page.table_html(almanac)             # same bodies: no new evaluations
        assert len(page._memo) == n


class TestCatalogDome:
    """With a full hip_main.dat installed the dome plots every catalog
    star to star_mag_limit -- named or not -- while labels stay on named
    stars; without one it keeps the named-star chart."""

    @pytest.fixture()
    def full_almanac(self, tmp_path):
        from test_almanac import make_full_catalog_root
        s = wxskyfield.Sky(make_full_catalog_root(tmp_path), load_stars=True)
        assert s.is_valid()
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            yield weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())

    def test_unnamed_stars_plotted_never_labeled(self, full_almanac):
        page = wxskyfield_sky.SkyPage({'star_mag_limit': '5.0'})
        svg = page.dome_svg(full_almanac)
        assert_balanced(svg)
        # Gamma Cas (HIP 4427, mag 2.15, circumpolar here) has no
        # IAU-CSN/PyEphem name: a dot with a HIP tooltip, never a label.
        assert 'HIP 4427' in svg
        assert not re.search(r'<text[^>]*>HIP \d', svg)
        assert 'starlab' in svg              # named stars still label

    def test_default_limit_includes_gamma_cas(self, full_almanac, page):
        # 2.15 is brighter than the default 2.6 limit: the star Jacques
        # missed appears with no settings at all once the catalog is in.
        assert 'HIP 4427' in page.dome_svg(full_almanac)

    def test_raised_limit_adds_stars(self, full_almanac):
        few = wxskyfield_sky.SkyPage().dome_svg(full_almanac)
        many = wxskyfield_sky.SkyPage({'star_mag_limit': '5.0'}).dome_svg(full_almanac)
        assert many.count('<circle') > few.count('<circle')


class TestStarOptions:
    """star_mag_limit/star_label_mag skin options: parsed, clamped, and
    a bad value must fall back to the default, never blank the page."""

    def test_parsed(self):
        p = wxskyfield_sky.SkyPage({'star_mag_limit': '5.0', 'star_label_mag': '2.5'})
        assert p._star_mag_limit == 5.0
        assert p._star_label_mag == 2.5

    def test_defaults(self):
        p = wxskyfield_sky.SkyPage()
        assert p._star_mag_limit == wxskyfield_sky.STAR_MAG_LIMIT
        assert p._star_label_mag == wxskyfield_sky.STAR_LABEL_MAG

    def test_garbage_falls_back(self):
        p = wxskyfield_sky.SkyPage({'star_mag_limit': 'bright', 'star_label_mag': None})
        assert p._star_mag_limit == wxskyfield_sky.STAR_MAG_LIMIT
        assert p._star_label_mag == wxskyfield_sky.STAR_LABEL_MAG

    def test_clamped(self):
        p = wxskyfield_sky.SkyPage({'star_mag_limit': '99', 'star_label_mag': '-99'})
        assert p._star_mag_limit == 6.5
        assert p._star_label_mag == -2.0


class TestFooter:
    """footer_html must be true for what actually computed the page: the
    full Skyfield/DE421/Hipparcos credit only when the registered almanac's
    star catalog is live, a named failure otherwise (the footer doubles as
    a diagnostic -- the pre-1.10 static footer claimed Hipparcos data
    while a user's almanac had never registered at all)."""

    def test_full_credit_with_stars(self, almanac, page):
        html = page.footer_html()
        assert 'Computed with ' + LINKED_NAME in html
        assert 'Skyfield and the JPL DE421 ephemeris' in html
        assert 'IAU-CSN star names' in html
        assert 'Hipparcos star data Credit: ESA' in html
        assert 'Regenerated every report cycle' in html

    def test_stars_disabled(self, page):
        starless = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                                  load_stars=False)
        assert starless.is_valid()
        with saved_almanacs():
            assert wxskyfield.register_almanac(starless)
            html = page.footer_html()
        assert 'star catalog disabled' in html
        assert 'Hipparcos' not in html
        assert 'weewxd log' not in html          # disabled is not a failure

    def test_star_catalog_failure(self, page, tmp_path):
        """stars = true but wxskyfield_stars.dat unreadable: the engine
        stays valid (planets fine) and the footer names the failure."""
        os.symlink(os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp'),
                   os.path.join(str(tmp_path), 'wxskyfield_de421.bsp'))
        broken = wxskyfield.Sky(str(tmp_path), load_stars=True)
        assert broken.is_valid()
        assert not broken.stars and broken.stars_requested
        with saved_almanacs():
            assert wxskyfield.register_almanac(broken)
            html = page.footer_html()
        assert 'star catalog unavailable' in html
        assert 'see the weewxd log' in html
        assert 'Hipparcos' not in html

    def test_almanac_not_registered(self, page):
        """No registered Skyfield almanac (service failed or absent): the
        page renders off the built-in almanac and the footer says so."""
        with saved_almanacs():
            weewx.almanac.almanacs[:] = [
                a for a in weewx.almanac.almanacs
                if not isinstance(a, wxskyfield.SkyfieldAlmanacType)]
            assert wxskyfield_sky._find_sky() is None
            html = page.footer_html()
        assert 'built-in almanac' in html
        assert LINKED_NAME + ' is not active' in html
        assert 'DE421' not in html and 'Hipparcos' not in html


class TestPalettes:
    """Every render method takes palette=.  As of 1.5 the default 'night'
    and the 'light' plates bake the traditional astronomy body colors
    (yellow sun, silver moon, gray Mercury, pearly Venus, blue Earth);
    'classic-night'/'classic-light' preserve the pre-1.5 values."""

    RENDERERS = ('moon_svg', 'dome_svg', 'ribbons_svg', 'orrery_svg',
                 'analemma_svg', 'sunpath_svg', 'daylength_svg',
                 'lunation_svg', 'chips_html', 'table_html',
                 'countdown_html', 'header_sub')

    # The complete set of night-plate colors ever baked into markup.
    NIGHT_HEXES = ('#E9E4D4', '#8B93B8', '#D3A94C', '#2A3358', '#0A0F22',
                   '#1E2745', '#DDD8C4', '#161F3D', '#1B2749', '#2A3A63',
                   '#0B1129', '#131B38', '#1A2547', '#233153', '#2E3D5C',
                   '#FFD75E', '#C9D0DA', '#C04F36')

    def test_default_is_night(self, almanac, page):
        for name in self.RENDERERS:
            meth = getattr(page, name)
            assert meth(almanac) == meth(almanac, palette='night')

    def test_night_goldens(self, almanac, page):
        """Default output bakes the night-plate values — traditional body
        colors as of 1.5."""
        dome = page.dome_svg(almanac)
        for hexval in ('#161F3D', '#1B2749', '#2A3A63',     # dome gradient
                       '#2A3358', '#D3A94C', '#E9E4D4', '#0A0F22'):
            assert hexval in dome
        assert '#2E3D5C' in page.ribbons_svg(almanac)       # day twilight band
        moon = page.moon_svg(almanac)
        for hexval in ('#1E2745', '#DDD8C4', '#2A3358'):    # disc + ring
            assert hexval in moon
        assert '#FFD75E' in page.chips_html(almanac)        # sun identity dot

    def test_light_panels(self, almanac, page):
        """Every panel renders balanced with palette='light' and bakes no
        night-plate color."""
        for name in self.RENDERERS:
            markup = getattr(page, name)(almanac, palette='light')
            assert_balanced(markup)
            for hexval in self.NIGHT_HEXES:
                assert hexval not in markup, '%s leaked night %s' % (name, hexval)

    def test_light_values(self, almanac, page):
        dome = page.dome_svg(almanac, palette='light')
        for hexval in ('#ffffff', '#efece2',                # dome gradient
                       '#8a94a6', '#1d2c4e', '#c9cfd8'):    # rim, ink, line
            assert hexval in dome
        ribbons = page.ribbons_svg(almanac, palette='light')
        for hexval in ('#D7E6F5', '#B45309', '#FACC15'):    # day band, now, sun
            assert hexval in ribbons
        orrery = page.orrery_svg(almanac, palette='light')
        for hexval in ('#FACC15', '#2E7DBE', '#1B5C8F'):    # sun, earth + ring
            assert hexval in orrery
        moon = page.moon_svg(almanac, palette='light')
        for hexval in ('#26314F', '#F2ECD8', '#888888'):    # disc + ring
            assert hexval in moon
        assert '#B45309' in page.analemma_svg(almanac, palette='light')
        assert '#b23a24' in page.table_html(almanac, palette='light')   # mars

    def test_light_rings(self, almanac, page):
        """Pale bodies carry their ring color on the light plate: the sun's
        orrery dot, the moon and venus ribbon bars, and the chip/table dots
        (as an inset box-shadow).  The night plate defines no rings —
        nothing pale needs a lift on navy."""
        ribbons = page.ribbons_svg(almanac, palette='light')
        for hexval in ('#767E8A', '#9C8B4D'):               # moon, venus bars
            assert hexval in ribbons
        assert '#C77F00' in page.orrery_svg(almanac, palette='light')
        assert 'box-shadow:inset 0 0 0 1.5px #C77F00' in \
            page.chips_html(almanac, palette='light')
        assert 'box-shadow:inset 0 0 0 1.5px #767E8A' in \
            page.table_html(almanac, palette='light')
        assert 'box-shadow' not in page.chips_html(almanac)
        assert 'box-shadow' not in page.table_html(almanac)

    def test_classic_palettes_preserve_pre_15_colors(self, almanac, page):
        """'classic-night'/'classic-light' bake the pre-1.5 body colors for
        skins attached to the old look."""
        assert '#B98C31' in page.chips_html(almanac, palette='classic-night')
        assert '#7E92DA' in page.ribbons_svg(almanac, palette='classic-night')
        classic_ribbons = page.ribbons_svg(almanac, palette='classic-light')
        for hexval in ('#B8860B', '#4A5FB8'):               # old sun, old moon
            assert hexval in classic_ribbons
        orrery = page.orrery_svg(almanac, palette='classic-light')
        for hexval in ('#B8860B', '#2e6e8e'):               # old sun, old earth
            assert hexval in orrery
        for name in self.RENDERERS:
            assert_balanced(getattr(page, name)(almanac, palette='classic-light'))

    def test_unknown_palette_raises(self, almanac, page):
        for name in self.RENDERERS:
            with pytest.raises(ValueError, match='light, night'):
                getattr(page, name)(almanac, palette='sepia')


class TestTheme:
    """The report's theme option (skin.conf, overridable in the
    [StdReport] [[SkyfieldReport]] stanza): dark (default -- existing
    users see no change), light, or auto (light while the sun is up at
    generation time, dark otherwise).  Resolved once per page, baked in:
    no JavaScript, no prefers-color-scheme."""

    SKIN_DIR = os.path.join(REPO_ROOT, 'skins', 'Skyfield')

    def test_default_is_dark(self, almanac, page):
        assert page.theme(almanac) == 'dark'
        assert page.palette(almanac) == 'night'

    def test_light(self, almanac):
        page = wxskyfield_sky.SkyPage({'theme': 'light'})
        assert page.theme(almanac) == 'light'
        assert page.palette(almanac) == 'light'

    def test_case_insensitive(self, almanac):
        assert wxskyfield_sky.SkyPage({'theme': 'Light'}).theme(almanac) == 'light'

    def test_auto_follows_the_sun(self, sky):
        auto = wxskyfield_sky.SkyPage({'theme': 'auto'})
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            fmt = weewx.units.get_default_formatter()
            noon = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                         altitude=ALTITUDE_M, formatter=fmt)
            midnight = weewx.almanac.Almanac(TIME_TS + 12 * 3600, LATITUDE,
                                             LONGITUDE, altitude=ALTITUDE_M,
                                             formatter=fmt)
            assert auto.sun_is_up(noon)              # solstice noon
            assert not auto.sun_is_up(midnight)
            assert auto.theme(noon) == 'light'
            assert auto.palette(noon) == 'light'
            assert auto.theme(midnight) == 'dark'
            assert auto.palette(midnight) == 'night'

    def test_unknown_theme_raises(self, almanac):
        page = wxskyfield_sky.SkyPage({'theme': 'sepia'})
        with pytest.raises(ValueError, match='auto, dark, light'):
            page.theme(almanac)
        with pytest.raises(ValueError, match='auto, dark, light'):
            page.palette(almanac)

    def test_template_plumbs_the_theme(self):
        """The template stamps the theme class on the root element and hands
        the resolved palette to every panel call -- a call that forgets it
        would render night colors onto the light plate."""
        with open(os.path.join(self.SKIN_DIR, 'index.html.tmpl')) as f:
            text = f.read()
        assert 'class="theme-$theme"' in text
        assert '#set $theme = $sky_page.theme($almanac)' in text
        assert '#set $palette = $sky_page.palette($almanac)' in text
        for name, args in re.findall(r'\$sky_page\.(\w+)\(([^)]*)\)', text):
            if name in TestPalettes.RENDERERS:
                assert 'palette=$palette' in args, name

    def test_sky_css_light_covers_every_variable(self):
        """The :root.theme-light block must redefine every custom property
        the dark :root defines (a missed one leaks a night color onto the
        paper plate), and flip color-scheme."""
        with open(os.path.join(self.SKIN_DIR, 'sky.css')) as f:
            css = f.read()
        root = re.search(r':root\{(.*?)\}', css, re.S)
        light = re.search(r':root\.theme-light\{(.*?)\}', css, re.S)
        assert root is not None and light is not None
        dark_vars = set(re.findall(r'--([a-z]+):', root.group(1)))
        light_vars = set(re.findall(r'--([a-z]+):', light.group(1)))
        assert dark_vars and dark_vars == light_vars
        assert 'color-scheme: dark' in root.group(1)
        assert 'color-scheme: light' in light.group(1)


class TestPanelGuard:
    """A failure inside one $sky_page method must cost only that panel:
    the guard logs the error and renders the panel blank instead of
    killing the whole Sky page for the report cycle (which is how the
    wild skyfield event time fixed in 1.3 presented)."""

    @staticmethod
    def _break_bodies(monkeypatch):
        def boom(self, alm, name):
            raise ValueError("Python's datetime does not support negative years")
        monkeypatch.setattr(wxskyfield_sky.SkyPage, '_body', boom)

    def test_failed_panel_is_blank_and_logged(self, almanac, page, monkeypatch, caplog):
        self._break_bodies(monkeypatch)
        with caplog.at_level(logging.ERROR, logger='wxskyfield_sky'):
            for name in ('dome_svg', 'ribbons_svg', 'sunpath_svg',
                         'chips_html', 'table_html'):
                assert getattr(page, name)(almanac) == ''
                assert 'sky_page.%s failed' % name in caplog.text
        assert 'negative years' in caplog.text

    def test_sun_is_up_fails_closed(self, almanac, page, monkeypatch):
        self._break_bodies(monkeypatch)
        assert page.sun_is_up(almanac) is False

    def test_healthy_panels_unaffected(self, almanac, page, monkeypatch):
        """A panel that does not touch the broken helper still renders."""
        self._break_bodies(monkeypatch)
        assert_balanced(page.moon_svg(almanac))
        assert_balanced(page.lunation_svg(almanac))
        assert page.countdown_html(almanac).count('class="count"') == 5

    def test_usage_errors_still_raise(self, almanac, page, monkeypatch):
        """The guard is for runtime surprises only: a template-author error
        (unknown palette) must keep failing loudly, not blank the panel."""
        self._break_bodies(monkeypatch)
        with pytest.raises(ValueError, match='light, night'):
            page.dome_svg(almanac, palette='sepia')


class TestSkinFiles:
    SKIN_DIR = os.path.join(REPO_ROOT, 'skins', 'Skyfield')

    def test_template_compiles(self):
        Template = pytest.importorskip('Cheetah.Template').Template
        with open(os.path.join(self.SKIN_DIR, 'index.html.tmpl')) as f:
            source = f.read()
        # Compile parses all directives; placeholders resolve at run time.
        assert Template.compile(source=source) is not None

    def test_skin_conf_parses(self):
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.SKIN_DIR, 'skin.conf'))
        assert conf['CheetahGenerator']['search_list_extensions'] \
            == 'user.wxskyfield_sky.SkyfieldSky'
        assert conf['CheetahGenerator']['ToDate']['index']['template'] == 'index.html.tmpl'

    def test_version_lockstep(self):
        """The version lives in three places, kept identical: install.py,
        WXSKYFIELD_VERSION, and SKIN_VERSION in skin.conf.  (1.9.1 shipped
        with only install.py bumped -- this pins all three.)"""
        with open(os.path.join(REPO_ROOT, 'install.py')) as f:
            m = re.search(r'version\s*=\s*"([^"]+)"', f.read())
        assert m is not None
        assert m.group(1) == wxskyfield.WXSKYFIELD_VERSION
        with open(os.path.join(self.SKIN_DIR, 'skin.conf')) as f:
            m = re.search(r'^\s*SKIN_VERSION\s*=\s*(\S+)', f.read(), re.MULTILINE)
        assert m is not None
        assert m.group(1) == wxskyfield.WXSKYFIELD_VERSION

    def test_installer_lists_all_skin_files(self):
        with open(os.path.join(REPO_ROOT, 'install.py')) as f:
            installer = f.read()
        for name in os.listdir(self.SKIN_DIR):
            assert 'skins/Skyfield/%s' % name in installer
        assert 'bin/user/wxskyfield_sky.py' in installer
        # weectl prepends the station's [StdReport] HTML_ROOT to the
        # installer's HTML_ROOT (weecfg/extension.py), so the installer must
        # give a relative path ('skyfield'), never 'public_html/skyfield' --
        # that installs to public_html/public_html/skyfield.
        assert "'HTML_ROOT': 'skyfield'" in installer
        assert 'public_html' not in installer

    def test_installer_lists_lang_files(self):
        with open(os.path.join(REPO_ROOT, 'install.py')) as f:
            installer = f.read()
        lang_dir = os.path.join(self.SKIN_DIR, 'lang')
        assert os.listdir(lang_dir), 'lang dir missing or empty'
        for name in os.listdir(lang_dir):
            assert 'skins/Skyfield/lang/%s' % name in installer


class TestI18n:
    """The Sky page's translation plumbing (1.12).  [Texts] is
    gettext-style: the English string is the key, and a report falls back
    to it one string at a time, so a partial translation is fine.  Body
    display names come from the almanac's own texts (the [Almanac]
    section, the same source as $almanac.<body>.label), compass cardinals
    from the report formatter's [Units][[Ordinates]] directions, and the
    coordinate hemisphere letters from [Labels] hemispheres."""

    LANG_DIR = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'lang')

    @staticmethod
    def rendered_keys():
        """Every translation key the page can render, read from the two
        sources: self._t('...') calls in wxskyfield_sky.py (keys are
        single-line, single-quoted literals by convention) and
        $gettext("...") calls in the template."""
        with open(os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_sky.py'),
                  encoding='utf-8') as f:
            sle = re.findall(r"self\._t\(\s*'([^']*)'", f.read())
        with open(os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'index.html.tmpl'),
                  encoding='utf-8') as f:
            tmpl = re.findall(r'\$gettext\(\s*(?:"([^"]+)"|\'([^\']+)\')\s*\)', f.read())
        assert sle and tmpl
        return set(sle) | {a or b for a, b in tmpl}

    def test_en_conf_ships_exactly_what_renders(self):
        """Both directions: a rendered key missing from lang/en.conf fails,
        and an en.conf key nothing renders fails -- the English file is the
        reference dictionary for translators and embedding skins, and it
        must grow and shrink with the features that render it."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'en.conf'),
                                   encoding='utf-8', file_error=True)
        shipped = dict(conf['Texts'])
        rendered = self.rendered_keys()
        assert sorted(rendered - set(shipped)) == [], 'rendered but not in en.conf'
        assert sorted(set(shipped) - rendered) == [], 'in en.conf but never rendered'
        # English is the identity translation: every value equals its key
        # (so the file doubles as the untranslated reference).
        assert [k for k, v in shipped.items() if v != k] == []
        # Every English format string must itself format cleanly: _t falls
        # back to it when a translation's placeholders are broken.
        for k in rendered:
            k.format(**{name: 'x' for name in set(re.findall(r'\{(\w+)\}', k))})

    def test_en_conf_core_sections(self):
        """The lang file is self-contained: it carries the core-standard
        sections the panels read (hemispheres, ordinates, moon phases) and
        a display name for every body the page draws, earth included."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'en.conf'),
                                   encoding='utf-8', file_error=True)
        assert list(conf['Labels']['hemispheres']) == ['N', 'S', 'E', 'W']
        assert len(conf['Units']['Ordinates']['directions']) == 17
        assert len(conf['Almanac']['moon_phases']) == 8
        for body in ['sun', 'moon', 'earth'] + wxskyfield_sky.PLANETS:
            assert conf['Almanac'][body] == body.title()
        # English constellation names are the Latin ones -- the
        # [[Constellations]] section is the key reference for translators
        # and must mirror the engine's table exactly.
        assert dict(conf['Almanac']['Constellations']) == wxskyfield.CONSTELLATION_NAMES

    GERMAN_SKIN = {
        'Texts': {
            'today': 'heute',
            'now {time}': 'jetzt {time}',
            'Daylight': 'Tageslicht',
            'Body': 'Körper',
            'up now — alt {alt}° · az {az}°':
                'jetzt sichtbar — Höhe {alt}° · Azimut {az}°',
            'rises {time}': 'Aufgang {time}',
            'below the horizon': 'unter dem Horizont',
            'Computed with weewx-skyfield': 'Berechnet mit weewx-skyfield',
        },
        'Labels': {'hemispheres': ['Nord', 'Süd', 'Ost', 'West']},
    }

    def test_translated_rendering(self, sky):
        """Translations reach the panels through all four channels --
        [Texts], [Almanac] body names, formatter ordinates, [Labels]
        hemispheres -- and untranslated strings stay English."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            ordinates = ['N', 'NNO', 'NO', 'ONO', 'O', 'OSO', 'SO', 'SSO',
                         'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW', '-']
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.Formatter(ordinate_names=ordinates),
                texts={'moon': 'Mond'})
            page = wxskyfield_sky.SkyPage(self.GERMAN_SKIN)
            dome = page.dome_svg(alm)
            table = page.table_html(alm)
            chips = page.chips_html(alm)
            ribbons = page.ribbons_svg(alm)
            daylength = page.daylength_svg(alm)
            header = page.header_sub(alm)
            footer = page.footer_html()
        assert '>O</text>' in dome                    # east cardinal, Ordinates
        assert '</span>Mond</td>' in table            # body name, [Almanac]
        assert '<th>Körper</th>' in table        # header, [Texts]
        assert '<th>Rise</th>' in table               # untranslated: English
        assert 'Tageslicht' in chips
        assert 'jetzt sichtbar' in chips              # Mars is up at the fixture noon
        assert '>jetzt 12:00</text>' in ribbons
        assert '>heute</text>' in daylength
        assert 'Nord' in header and 'West' in header  # lat >= 0, lon < 0
        assert 'Berechnet mit ' + LINKED_NAME in footer  # the link survives translation
        assert 'IAU-CSN star names' in footer         # untranslated: English

    def test_star_name_translated(self, sky):
        """Named stars translate through [Almanac] like the planets, keyed
        by tag name; Polaris is circumpolar from the test latitude so it is
        always on the dome."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter(),
                                        texts={'polaris': 'Polarstern'})
            svg = wxskyfield_sky.SkyPage().dome_svg(alm)
        assert 'Polarstern' in svg

    def test_translation_is_escaped(self, almanac):
        """Translators control [Texts] values, so they are markup-escaped
        at injection -- quotes included, the strings land in attributes."""
        page = wxskyfield_sky.SkyPage({'Texts': {'today': 'to & day <b>"x"'}})
        svg = page.daylength_svg(almanac)
        assert_balanced(svg)
        assert 'to &amp; day &lt;b&gt;&quot;x&quot;' in svg
        assert '<b>' not in svg

    def test_broken_placeholder_falls_back_to_english(self, almanac):
        """A translation with a broken {placeholder} must not blank the
        panel: _t falls back to the English key, which always formats."""
        page = wxskyfield_sky.SkyPage({'Texts': {'now {time}': 'jetzt {tiem}'}})
        svg = page.ribbons_svg(almanac)
        assert_balanced(svg)
        assert '>now 12:00</text>' in svg
        assert 'tiem' not in svg

    def test_shipped_lang_files_are_consistent(self):
        """Every shipped lang file must parse, translate only keys en.conf
        ships (a stale key would silently never render), keep each value's
        placeholders exactly its key's set (a renamed one knocks the string
        back to English at run time), and carry the core sections."""
        configobj = pytest.importorskip('configobj')
        rendered = self.rendered_keys()
        names = sorted(os.listdir(self.LANG_DIR))
        assert 'en.conf' in names and 'de.conf' in names
        for name in names:
            conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, name),
                                       encoding='utf-8', file_error=True)
            for key, val in dict(conf['Texts']).items():
                assert key in rendered, (name, key)
                assert isinstance(val, str), (name, key)
                assert (set(re.findall(r'\{(\w+)\}', val))
                        == set(re.findall(r'\{(\w+)\}', key))), (name, key)
            assert len(conf['Labels']['hemispheres']) == 4, name
            assert len(conf['Units']['Ordinates']['directions']) == 17, name
            assert len(conf['Almanac']['moon_phases']) == 8, name
            for body in ['sun', 'moon', 'earth'] + wxskyfield_sky.PLANETS:
                assert conf['Almanac'][body], (name, body)
            # Constellation keys are the IAU abbreviations; a key outside
            # the engine's table would silently never be looked up.
            for abbr in conf['Almanac']['Constellations']:
                assert abbr in wxskyfield.CONSTELLATION_NAMES, (name, abbr)

    def test_de_conf_is_complete(self):
        """German is a full translation: every rendered key is covered, so
        a new feature's strings fail here until de.conf learns them (the
        vocabulary grows only with the feature that renders it)."""
        self.check_complete('de.conf')

    def test_fr_conf_is_complete(self):
        """French likewise ships complete."""
        self.check_complete('fr.conf')

    def test_nl_conf_is_complete(self):
        """Dutch likewise ships complete."""
        self.check_complete('nl.conf')

    def test_es_conf_is_complete(self):
        """Spanish likewise ships complete."""
        self.check_complete('es.conf')

    def test_da_conf_is_complete(self):
        """Danish likewise ships complete."""
        self.check_complete('da.conf')

    def check_complete(self, name):
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, name),
                                   encoding='utf-8', file_error=True)
        assert sorted(self.rendered_keys() - set(conf['Texts'])) == []
        # All 88 constellations, too.
        assert (sorted(set(wxskyfield.CONSTELLATION_NAMES)
                       - set(conf['Almanac']['Constellations'])) == [])

    def test_shipped_german_renders(self, sky):
        """The shipped de.conf, fed through the same channels the report
        engine uses, renders German panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'de.conf'),
                                   encoding='utf-8', file_error=True)
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.Formatter(
                    ordinate_names=list(conf['Units']['Ordinates']['directions'])),
                texts=dict(conf['Almanac']))
            page = wxskyfield_sky.SkyPage(
                {'Texts': dict(conf['Texts']),
                 'Labels': {'hemispheres': list(conf['Labels']['hemispheres'])}})
            dome = page.dome_svg(alm)
            table = page.table_html(alm)
            ribbons = page.ribbons_svg(alm)
            chips = page.chips_html(alm)
            footer = page.footer_html()
        for markup in (dome, table, ribbons, chips):
            assert_balanced(markup)
        assert '>O</text>' in dome                       # German east cardinal
        assert '>Mond</text>' in dome
        assert '<th>Körper</th>' in table
        assert '</span>Neptun</td>' in table             # not "Neptune"
        assert '<th>Aufgang</th>' in table and '<th>Untergang</th>' in table
        assert '>jetzt 12:00</text>' in ribbons
        # The chips' constellations carry the German names, through the
        # [[Constellations]] subsection: Mars stands in Leo on 2025-06-21.
        assert 'im Sternbild Löwe' in chips
        assert 'Berechnet mit ' + LINKED_NAME in footer
        assert 'IAU-CSN-Sternnamen' in footer
        # German moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])

    def test_shipped_french_renders(self, sky):
        """The shipped fr.conf, fed through the same channels the report
        engine uses, renders French panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'fr.conf'),
                                   encoding='utf-8', file_error=True)
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.Formatter(
                    ordinate_names=list(conf['Units']['Ordinates']['directions'])),
                texts=dict(conf['Almanac']))
            page = wxskyfield_sky.SkyPage(
                {'Texts': dict(conf['Texts']),
                 'Labels': {'hemispheres': list(conf['Labels']['hemispheres'])}})
            dome = page.dome_svg(alm)
            table = page.table_html(alm)
            ribbons = page.ribbons_svg(alm)
            chips = page.chips_html(alm)
            footer = page.footer_html()
        for markup in (dome, table, ribbons, chips):
            assert_balanced(markup)
        assert '>E</text>' in dome                       # French east cardinal
        assert '>Lune</text>' in dome
        assert '<th>Astre</th>' in table
        assert '</span>Mercure</td>' in table            # not "Mercury"
        assert '<th>Lever</th>' in table and '<th>Coucher</th>' in table
        assert '>maintenant 12:00</text>' in ribbons
        # The chips' constellations carry the French names, through the
        # [[Constellations]] subsection: Mars stands in Leo on 2025-06-21.
        assert 'constellation : Lion' in chips
        assert 'Calculé avec ' + LINKED_NAME in footer
        assert "Noms d'étoiles IAU-CSN" in footer
        # French moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])

    def test_shipped_dutch_renders(self, sky):
        """The shipped nl.conf, fed through the same channels the report
        engine uses, renders Dutch panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'nl.conf'),
                                   encoding='utf-8', file_error=True)
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.Formatter(
                    ordinate_names=list(conf['Units']['Ordinates']['directions'])),
                texts=dict(conf['Almanac']))
            page = wxskyfield_sky.SkyPage(
                {'Texts': dict(conf['Texts']),
                 'Labels': {'hemispheres': list(conf['Labels']['hemispheres'])}})
            dome = page.dome_svg(alm)
            table = page.table_html(alm)
            ribbons = page.ribbons_svg(alm)
            chips = page.chips_html(alm)
            footer = page.footer_html()
        for markup in (dome, table, ribbons, chips):
            assert_balanced(markup)
        assert '>O</text>' in dome                       # Dutch east cardinal
        assert '>Maan</text>' in dome
        assert '<th>Hemellichaam</th>' in table
        assert '</span>Mercurius</td>' in table          # not "Mercury"
        assert '<th>Opkomst</th>' in table and '<th>Ondergang</th>' in table
        assert '>nu 12:00</text>' in ribbons
        # The chips' constellations carry the Dutch names, through the
        # [[Constellations]] subsection: Mars stands in Leo on 2025-06-21.
        assert 'in het sterrenbeeld Leeuw' in chips
        assert 'Berekend met ' + LINKED_NAME in footer
        assert 'IAU-CSN-sternamen' in footer
        # Dutch moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])

    def test_shipped_spanish_renders(self, sky):
        """The shipped es.conf, fed through the same channels the report
        engine uses, renders Spanish panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'es.conf'),
                                   encoding='utf-8', file_error=True)
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.Formatter(
                    ordinate_names=list(conf['Units']['Ordinates']['directions'])),
                texts=dict(conf['Almanac']))
            page = wxskyfield_sky.SkyPage(
                {'Texts': dict(conf['Texts']),
                 'Labels': {'hemispheres': list(conf['Labels']['hemispheres'])}})
            dome = page.dome_svg(alm)
            table = page.table_html(alm)
            ribbons = page.ribbons_svg(alm)
            chips = page.chips_html(alm)
            footer = page.footer_html()
        for markup in (dome, table, ribbons, chips):
            assert_balanced(markup)
        assert '>E</text>' in dome                       # Spanish east cardinal
        assert '>Luna</text>' in dome
        assert '<th>Astro</th>' in table
        assert '</span>Mercurio</td>' in table           # not "Mercury"
        assert '<th>Salida</th>' in table and '<th>Puesta</th>' in table
        assert '>ahora 12:00</text>' in ribbons
        # The chips' constellations carry the Spanish names, through the
        # [[Constellations]] subsection: Saturn stands in Pisces on
        # 2025-06-21, and "Piscis" differs from the Latin fallback.
        assert 'constelación: Piscis' in chips
        assert 'Calculado con ' + LINKED_NAME in footer
        assert 'Nombres de estrellas IAU-CSN' in footer
        # Spanish moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])
