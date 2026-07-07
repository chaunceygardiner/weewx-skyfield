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

    def test_moon_svg(self, almanac, page):
        svg = page.moon_svg(almanac)
        assert_balanced(svg)
        assert '<path' in svg

    def test_chips_and_table(self, almanac, page):
        chips = page.chips_html(almanac)
        assert_balanced(chips)
        assert 'CML I' in chips and 'ring tilt' in chips
        table = page.table_html(almanac)
        assert_balanced(table)
        assert table.count('<tr>') == 10     # header + 9 bodies

    def test_header_bits(self, almanac, page):
        assert 'N' in page.header_sub(almanac)
        countdown = page.countdown_html(almanac)
        assert countdown.count('class="count"') == 4
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


class TestPalettes:
    """Every render method takes palette= ('night'/'light'); the default
    'night' output must be unchanged from before the kwarg existed."""

    RENDERERS = ('moon_svg', 'dome_svg', 'ribbons_svg', 'orrery_svg',
                 'analemma_svg', 'chips_html', 'table_html',
                 'countdown_html', 'header_sub')

    # The complete set of night-plate colors ever baked into markup.
    NIGHT_HEXES = ('#E9E4D4', '#8B93B8', '#D3A94C', '#2A3358', '#0A0F22',
                   '#1E2745', '#DDD8C4', '#161F3D', '#1B2749', '#2A3A63',
                   '#0B1129', '#131B38', '#1A2547', '#233153', '#2E3D5C',
                   '#B98C31', '#7E92DA', '#C04F36')

    def test_default_is_night(self, almanac, page):
        for name in self.RENDERERS:
            meth = getattr(page, name)
            assert meth(almanac) == meth(almanac, palette='night')

    def test_night_goldens(self, almanac, page):
        """Default output still bakes the original night-plate values, so
        the shipped Sky page and existing users see identical markup."""
        dome = page.dome_svg(almanac)
        for hexval in ('#161F3D', '#1B2749', '#2A3A63',     # dome gradient
                       '#2A3358', '#D3A94C', '#E9E4D4', '#0A0F22'):
            assert hexval in dome
        assert '#2E3D5C' in page.ribbons_svg(almanac)       # day twilight band
        moon = page.moon_svg(almanac)
        for hexval in ('#1E2745', '#DDD8C4', '#2A3358'):    # disc + ring
            assert hexval in moon
        assert '#B98C31' in page.chips_html(almanac)        # sun identity dot

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
        for hexval in ('#D7E6F5', '#B45309', '#B8860B'):    # day band, now, sun
            assert hexval in ribbons
        orrery = page.orrery_svg(almanac, palette='light')
        for hexval in ('#B8860B', '#2e6e8e', '#ffffff'):    # sun, earth, halo
            assert hexval in orrery
        moon = page.moon_svg(almanac, palette='light')
        for hexval in ('#26314F', '#F2ECD8', '#888888'):    # disc + ring
            assert hexval in moon
        assert '#B45309' in page.analemma_svg(almanac, palette='light')
        assert '#b23a24' in page.table_html(almanac, palette='light')   # mars

    def test_unknown_palette_raises(self, almanac, page):
        for name in self.RENDERERS:
            with pytest.raises(ValueError, match='light, night'):
                getattr(page, name)(almanac, palette='sepia')


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
            for name in ('dome_svg', 'ribbons_svg', 'chips_html', 'table_html'):
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
        assert page.countdown_html(almanac).count('class="count"') == 4

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
