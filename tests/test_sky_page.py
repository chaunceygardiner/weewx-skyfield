"""
test_sky_page.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

Tests for the bundled Skyfield skin's search-list helper (wxskyfield_sky.py):
every panel must render well-formed markup from a real almanac, and the
Cheetah template and skin.conf must parse.
"""

import contextlib
import inspect
import logging
import os
import re
import subprocess
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

sys.path.insert(0, TEST_DIR)
import contrast

LATITUDE   = 37.4419
LONGITUDE  = -122.143
ALTITUDE_M = 9.0
TIME_TS    = 1750532400      # 2025-06-21 12:00:00 PDT
GAP_TS     = 1785178800      # 2026-07-27 12:00:00 PDT (moon transits ~midnight)
PASS_TS    = 1750533112      # culmination of the ISS's (invisible) noon pass
SHADOW_TS  = 1750503830      # ISS 29° up pre-dawn 2025-06-21, in Earth's shadow

# Satellite element fixtures, shared with test_almanac.py: the ISS and
# Tiangong TLEs as captured 2025-06-21, so the page's satellite panel and
# dome arc pin deterministically.
SAT_DATA_DIR = os.path.join(TEST_DIR, 'data')
SATELLITES = {'iss': 25544, 'tiangong': 48274}

# Comet fixtures, shared with test_almanac.py: real archived rows plus the
# fabricated always-bright C/9999 Z9 (above the horizon at TIME_TS with
# g forced to -9.0), so the dome pins both marker states -- halley is up
# but telescope-faint (hollow), bright is up and naked-eye (solid), and
# hale_bopp is below the horizon (absent).
COMETS = {'halley': '1P', 'hale_bopp': 'C/1995 O1', 'bright': 'C/9999 Z9',
          'mcnaught': '220P'}

# The footer links the extension's name to the manual, in every language.
LINKED_NAME = ('<a href="%s">weewx-skyfield</a>'
               % wxskyfield_sky.REPO_URL)


@pytest.fixture(scope='module')
def sky():
    s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=True,
                       satellites=dict(SATELLITES), sat_dir=SAT_DATA_DIR,
                       comets=dict(COMETS), comet_dir=SAT_DATA_DIR)
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

    def test_dome_comet_markers(self, almanac, page):
        """Configured comets always plot when risen, always labeled --
        the config list is the filter.  The solid/hollow diamond states:
        the fabricated bright comet (mag -3) is the solid brass mark, the
        genuinely faint Halley (mag ~26) the hollow present-but-not-
        naked-eye ring (data-bright mirrors the satellites' data-sunlit
        hook), and below-the-horizon Hale-Bopp is absent."""
        svg = page.dome_svg(almanac)
        assert_balanced(svg)
        assert 'data-body="bright" data-bright="1"' in svg
        assert 'data-body="halley" data-bright="0"' in svg
        assert 'data-body="hale_bopp"' not in svg
        # Each risen comet carries its three anti-sunward tail rays.
        assert svg.count('comet-tail') == 6
        # The tooltip carries the magnitude; the label is the display name.
        assert 'mag 25.6' in svg
        assert '>Halley</text>' in svg

    def test_dome_comet_without_elements_absent(self, page, tmp_path):
        """A configured comet with no elements serves alt None: no marker,
        no label, no error -- the dome simply omits it."""
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           comets={'halley': '1P'}, comet_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = page.dome_svg(alm)
        assert_balanced(svg)
        assert 'data-body="halley"' not in svg

    def test_comet_names_contract(self, almanac, page):
        """PUBLIC CONTRACT, like satellite_names: embedding skins
        enumerate the comets through this, in config order."""
        assert page.comet_names() == ['halley', 'hale_bopp', 'bright', 'mcnaught']

    def test_comets_in_table_chips_ribbons(self, almanac, page):
        """A configured comet with elements rides every roster panel: a
        table row, a rail chip and a ribbon bar, brass-marked, with the
        same up-now/rises/below states as the planets.  The elementless
        case is simply absent (tested per-panel below and via the dome)."""
        table = page.table_html(almanac)
        assert_balanced(table)
        assert 'Halley' in table and 'Mcnaught' in table
        assert '35.907 au' in table          # Halley's distance column
        chips = page.chips_html(almanac)
        assert_balanced(chips)
        assert 'Halley' in chips
        # Halley is up at TIME_TS; 220P is below the horizon.
        halley_chip = chips[chips.index('Halley'):chips.index('Hale Bopp')]
        assert 'up now' in halley_chip
        assert 'in Hydra' in halley_chip
        ribbons = page.ribbons_svg(almanac)
        assert_balanced(ribbons)
        assert '>Halley</text>' in ribbons and '>Mcnaught</text>' in ribbons

    def test_comet_perihelion_countdown(self, almanac, page):
        """The countdown row shows a comet's perihelion only when it lies
        ahead within a year: 220P (2026-06-14, ~358 days out) shows;
        Halley's 2061 date and Hale-Bopp's 1997 date stay quiet."""
        html = page.countdown_html(almanac)
        assert_balanced(html)
        assert 'Mcnaught perihelion' in html
        assert 'Halley' not in html and 'Hale Bopp' not in html

    def test_meteor_radiant_on_dome(self, almanac, page):
        """Perseids week, late evening: the Perseids and Delta Aquariids
        radiants stand above the horizon, each a rayed mark carrying ZHR
        and peak date in its tooltip.  At the June fixture instant no
        major shower is active and the dome carries no radiant."""
        assert 'radiant' not in page.dome_svg(almanac)
        aug = almanac(almanac_time=1754980000)      # 2025-08-11 22:06 PDT
        svg = wxskyfield_sky.SkyPage().dome_svg(aug)
        assert_balanced(svg)
        assert 'data-body="perseids"' in svg
        assert 'data-body="delta_aquariids"' in svg
        assert 'ZHR 100' in svg
        assert '>Perseids</text>' in svg

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

    def test_ribbons_time_column_fits(self, almanac, page):
        """The right-hand rise → set column widens for 12-hour times
        instead of running off the 1080 viewBox, and a 24-hour language
        keeps the layout it always had (text at x=964)."""
        def columns(svg):
            return [(int(x), len(re.sub(r'&#?\w+;', 'x', text)))
                    for x, text in re.findall(
                        r'<text x="(\d+)" y="[\d.]+" class="mono timelab">([^<]*)</text>', svg)]
        cols = columns(page.ribbons_svg(almanac))
        assert cols and any(' PM' in t or ' AM' in t for t in re.findall(
            r'class="mono timelab">([^<]*)<', page.ribbons_svg(almanac)))
        assert all(x + 6.82 * n <= 1080 - 8 for x, n in cols), cols
        cols24 = columns(wxskyfield_sky.SkyPage(
            {'Texts': {'%-I:%M %p': '%H:%M'}}).ribbons_svg(almanac))
        assert {x for x, _n in cols24} == {964}

    def test_orrery(self, almanac, page):
        svg = page.orrery_svg(almanac)
        assert_balanced(svg)
        assert '<title>Earth' in svg
        assert svg.count('<circle') >= 17    # 8 orbits + sun + 9 bodies

    def test_orrery_comets(self, almanac, page):
        """Every configured comet with elements is a diamond at its
        CURRENT sun distance and heliocentric longitude -- marker only,
        no orbit ring (eccentric orbits do not draw as circles) -- with
        the true distance in the tooltip and the dome's solid/hollow
        naked-eye rule.  Unlike the dome, below-the-horizon comets plot
        too: the orrery is a plan view, not the observer's sky."""
        svg = page.orrery_svg(almanac)
        # Halley at 35.1 AU: hollow, pinned just outside Neptune's ring.
        assert ', 35.1 au' in svg
        assert '>Halley</text>' in svg
        # All four fixture comets have elements, so all four plot --
        # hale_bopp and 220P included (below the dome's horizon, on the
        # orrery regardless), as the four diamond paths.
        assert svg.count('<path d="M') == 4
        assert '>Hale Bopp</text>' in svg and '>Bright</text>' in svg
        assert '>Mcnaught</text>' in svg
        # Each diamond carries its three tail rays, pointing radially
        # outward -- anti-sunward on a sun-centered plan view.
        assert svg.count('comet-tail') == 12
        # Ring count is unchanged: comets add no orbit circles.
        assert svg.count('fill="none"') == 8

    def test_orrery_comet_without_elements_absent(self, page, tmp_path):
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           comets={'halley': '1P'}, comet_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = page.orrery_svg(alm)
        assert_balanced(svg)
        assert '<path d="M' not in svg and 'Halley' not in svg

    def test_eot_chart(self, almanac, page):
        """53 weekly samples of the equation of time at the analemma's own
        instants (local standard noon); the fixed ±18-minute frame; the
        USNO sign.  The brass point is TODAY's own standard-noon value,
        not the nearest weekly sample: at the June-solstice test time the
        sundial runs '-1 m 56 s' behind -- negative, below the zero line --
        where the Jun 18 grid sample would have mislabeled it '-1 m 16 s',
        40 seconds off."""
        svg = page.eot_svg(almanac)
        assert_balanced(svg)
        assert svg.count(' L') == 52          # the weekly curve
        assert '-1\u00a0m 56\u00a0s' in svg             # today's value, signed
        assert '-1\u00a0m 16\u00a0s' not in svg         # ...not the weekly sample's
        assert '>+15\u00a0m<' in svg and '>-15\u00a0m<' in svg

    def test_analemma(self, almanac, page):
        svg = page.analemma_svg(almanac)
        assert_balanced(svg)
        assert svg.count('<circle') >= 54    # 53 weekly points + today's own noon
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
        labeled with the page's clock times, the format every other panel
        uses -- not the skin's ephem_day ('16:47:33'), which they read
        through 2.6.  On 2025-06-21 all three fall inside the plotted day,
        and the midnight endpoints hide below the plot floor, so no 00/24
        open-track markers appear."""
        svg = page.sunpath_svg(almanac)
        assert_balanced(svg)

        def hm(vh):
            return page._hm(wxskyfield_sky._raw(vh, 'unix_epoch'))
        assert '<title>Moonrise %s</title>' % hm(almanac.moon.rise) in svg
        assert '<title>Moonset %s</title>' % hm(almanac.moon.set) in svg
        assert '<title>Moon transit %s' % hm(almanac.moon.transit) in svg
        assert '>4:47 PM<' in svg or '&#8600;4:47 PM<' in svg
        assert ':33<' not in svg                    # no seconds
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

    def test_moon_apsides(self, almanac, page):
        html = page.moon_apsides_html(almanac)
        assert_balanced(html)
        # Jun 22 perigee, Jul 4 apogee (local time; both pinned in
        # test_almanac.py against Espenak's tables) -- and no supermoon:
        # June 2025's full moon (Jun 11) is nowhere near perigee.
        assert 'perigee' in html and 'apogee' in html
        assert 'Jun 22, 9:44 PM' in html and 'Jul 4, 7:28 PM' in html
        assert 'supermoon' not in html

    def test_supermoon_callout(self, almanac, page):
        """2025-11-05 is the year's closest supermoon: full moon 05:19
        PST, perigee 14:27 PST, nine hours apart.  Seen from Oct 25 the
        callout is up, dated to the full moon."""
        alm = weewx.almanac.Almanac(1761418800,     # 2025-10-25 12:00 PDT
                                    LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                    formatter=weewx.units.get_default_formatter())
        html = page.moon_apsides_html(alm)
        assert_balanced(html)
        assert 'class="supermoon"' in html
        assert 'Supermoon Nov 5' in html
        # The quiet apsis line still rides below the callout.
        assert 'class="apsis mono"' in html

    def test_chips_and_table(self, almanac, page):
        chips = page.chips_html(almanac)
        assert_balanced(chips)
        assert 'CML I' in chips and 'ring tilt' in chips
        assert 'in Leo' in chips                  # Mars's constellation, June 2025
        table = page.table_html(almanac)
        assert_balanced(table)
        # Body and comet rows carry data-body (2.4); the header row does not.
        assert table.count('<tr') == 14      # header + 9 bodies + 4 comets
        assert table.count('<tr data-body=') == 13

    def test_unit_group_overrides(self, sky):
        """A report's [Units] [[Groups]] preferences (e.g. a station-wide
        group_deltatime = hour, group_time = unix_epoch_ms) reach the
        almanac's ValueHelpers through the report converter, which
        converts at construction -- .raw is unformatted, not unconverted.
        Every panel must render identically to a default-units report.
        Field case: group_deltatime = hour fed hours into the panels'
        seconds arithmetic and every duration rendered as 0 h 0 m."""
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
                           'ribbons_svg', 'orrery_svg', 'analemma_svg', 'eot_svg',
                           'sunpath_svg',
                           'daylength_svg', 'lunation_svg', 'chips_html', 'table_html',
                           'satellites_html'):
                # A fresh SkyPage per render: the per-page memo is keyed on
                # the almanac's time, which both almanacs share.
                want = getattr(wxskyfield_sky.SkyPage(), method)(plain)
                got = getattr(wxskyfield_sky.SkyPage(), method)(overridden)
                assert got == want, method
            table = wxskyfield_sky.SkyPage().table_html(overridden)
            # Exactly one zero duration: Hale-Bopp's honest neverup (dec
            # -85 from 37N).  The units-override bug this pins against
            # zeroed EVERY row.
            assert table.count('>0\u00a0h 0\u00a0m<') == 1
            assert re.search('>14\u00a0h \\d+\u00a0m<', table)   # the solstice sun, up ~14 h 46 m

    def test_header_bits(self, almanac, page):
        assert 'N' in page.header_sub(almanac)
        countdown = page.countdown_html(almanac)
        # 5 event chips, the always-on next-meteor-shower chip, plus two
        # comet perihelia inside the one-year window (220P, and the
        # fabricated bright comet's donor orbit).
        assert countdown.count('class="count"') == 8
        # The shower chip: next from June 21 is the Southern Delta
        # Aquariids, with the moon's peak-night interference judgment.
        assert 'Southern Delta Aquariids' in countdown
        assert 'moon ' in countdown
        # The eclipse chip: the nearer of the next visible lunar/solar
        # eclipse (from Palo Alto in June 2025, the 2026-03-03 total
        # lunar), its date carrying the year since it can be years out.
        assert 'lunar eclipse' in countdown
        assert 'Mar 3, 2026' in countdown
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


class TestCountdownDayCount:
    """A countdown chip's detail line must agree with the calendar date
    on the line above it.  Jacques Terrettaz reported the 2026-08-12
    partial solar eclipse reading "in 1 day" beside that morning's own
    date (issue #6): the count was ceil() over elapsed seconds, which
    rounds any event later today up to one day.  Rounding down instead
    just moves the disagreement to the other side of midnight, so the
    count is differenced between the two LOCAL DATES -- the boundaries
    below are exactly the two cases ceil() and floor() each get wrong."""

    def _chip(self, html: str, key: str) -> str:
        m = re.search(r'<div class="count"><span class="k">%s</span>(.*?)</div>'
                      % re.escape(key), html)
        assert m, 'no %s chip in %s' % (key, html)
        return m.group(1)

    def test_days_until_boundaries(self):
        # Aug 12 2026 08:00 local, the morning Jacques rendered the page.
        # No DST transition in this window, so the offsets are exact.
        now = time.mktime((2026, 8, 12, 8, 0, 0, 0, 0, -1))
        assert wxskyfield_sky._days_until(now, now + 13 * 3600) == 0   # 21:00 today
        assert wxskyfield_sky._days_until(now, now + 17 * 3600) == 1   # 01:00 tomorrow
        assert wxskyfield_sky._days_until(now, now + 40 * 3600) == 2   # 00:00 in two days
        assert wxskyfield_sky._days_until(now, now - 3600) == 0        # clamped, never negative

    def test_dst_day_is_still_one_day(self):
        """A clock shift does not add or remove a calendar day: 23 elapsed
        hours across the spring-forward Sunday are still one day, and 25
        across the fall-back Sunday are still one day."""
        spring = time.mktime((2026, 3, 7, 12, 0, 0, 0, 0, -1))     # day before
        assert wxskyfield_sky._days_until(spring, spring + 23 * 3600) == 1
        fall = time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1))
        assert wxskyfield_sky._days_until(fall, fall + 25 * 3600) == 1

    def test_event_later_today_reads_today(self, almanac):
        """Jacques's case, end to end: bound to 00:30 on the full moon's
        own morning, the chip's date is today's and its detail line must
        say so -- and carry the clock time, which on the day itself is the
        one fact the chip does not already show."""
        ts = wxskyfield_sky._raw(almanac.next_full_moon, 'unix_epoch')
        lt = time.localtime(ts)
        morning = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 30, 0, 0, 0, -1))
        assert morning < ts, 'fixture full moon must fall later on its own day'
        chip = self._chip(
            wxskyfield_sky.SkyPage().countdown_html(almanac(almanac_time=morning)),
            'full moon')
        assert time.strftime('%b %-d', lt) in chip
        assert '>today at %s<' % time.strftime('%-I:%M %p', lt) in chip

    def test_today_phrase_is_one_translatable_key(self):
        """The today line is a single phrase with a {time} placeholder, not
        'today' + 'at' + the clock composed in Python: word order is the
        translator's to choose, and a bare 'at' is a fragment no one can
        translate in isolation (it would collide with 'at the top', 'at
        noon', 'at least 10 degrees up').  Every bundled language must
        carry the key, and each translation must keep the placeholder --
        one that drops it silently loses the time."""
        for code in ('en', 'de', 'fr', 'es', 'da', 'nl', 'it', 'no', 'sv'):
            path = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'lang',
                                '%s.conf' % code)
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            m = re.search(r'^\s*"today at \{time\}" = "(.*)"\s*$', text, re.M)
            assert m, '%s.conf is missing the "today at {time}" key' % code
            assert '{time}' in m.group(1), \
                '%s.conf drops the {time} placeholder: %r' % (code, m.group(1))
            assert '"at" =' not in text, \
                '%s.conf has a bare "at" key -- translate whole phrases' % code

    def test_today_phrase_translates(self, almanac):
        """The chip honors a [Texts] override, placeholder and all."""
        ts = wxskyfield_sky._raw(almanac.next_full_moon, 'unix_epoch')
        lt = time.localtime(ts)
        morning = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 30, 0, 0, 0, -1))
        page = wxskyfield_sky.SkyPage(
            {'Texts': {'today at {time}': 'heute um {time}'}})
        chip = self._chip(page.countdown_html(almanac(almanac_time=morning)),
                          'full moon')
        assert '>heute um %s<' % time.strftime('%-I:%M %p', lt) in chip

    def test_clock_times_follow_the_language(self, almanac):
        """English prints clock times 12-hour; a language that translates
        the clock key prints its own form, 24-hour for every bundled one."""
        ts = wxskyfield_sky._raw(almanac.next_full_moon, 'unix_epoch')
        lt = time.localtime(ts)
        morning = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 30, 0, 0, 0, -1))
        page = wxskyfield_sky.SkyPage({'Texts': {'%-I:%M %p': '%H:%M'}})
        chip = self._chip(page.countdown_html(almanac(almanac_time=morning)),
                          'full moon')
        assert '>today at %s<' % time.strftime('%H:%M', lt) in chip

    def test_clock_format_without_am_pm_reads_24_hour(self, monkeypatch):
        """A locale whose AM/PM designators are empty (most of continental
        Europe) would print a bare '8:45 ': the 12-hour format falls back
        to 24-hour there, and is left alone where %p prints."""
        monkeypatch.setattr(wxskyfield_sky.locale, 'nl_langinfo', lambda _item: '')
        assert wxskyfield_sky._clock_format('%-I:%M %p') == '%H:%M'
        assert (wxskyfield_sky._clock_format('%A, %B %-d, %Y, %-I:%M %p %Z')
                == '%A, %B %-d, %Y, %H:%M %Z')
        assert wxskyfield_sky._clock_format('%H:%M') == '%H:%M'
        monkeypatch.setattr(wxskyfield_sky.locale, 'nl_langinfo', lambda _item: 'AM')
        assert wxskyfield_sky._clock_format('%-I:%M %p') == '%-I:%M %p'

    def test_bundled_languages_keep_24_hour_clocks(self):
        """Only English reads 12-hour: every other bundled language must
        translate the clock key, or it would silently inherit AM/PM."""
        for code in ('de', 'fr', 'es', 'da', 'nl', 'it', 'no', 'sv'):
            path = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'lang',
                                '%s.conf' % code)
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            assert re.search(r'^\s*"%-I:%M %p" = "%H:%M"\s*$', text, re.M), code
            m = re.search(r'^\s*"%A, %B %-d, %Y, %-I:%M %p %Z" = "(.*)"\s*$', text, re.M)
            assert m and '%p' not in m.group(1), code

    def test_event_after_midnight_reads_one_day(self, almanac):
        """The mirror case, which rounding down gets wrong: bound to 23:30
        the evening before, the same full moon is hours away but lands on
        tomorrow's date, and the chip must say tomorrow."""
        ts = wxskyfield_sky._raw(almanac.next_full_moon, 'unix_epoch')
        lt = time.localtime(ts)
        eve = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 30, 0, 0, 0, -1)) - 3600
        chip = self._chip(
            wxskyfield_sky.SkyPage().countdown_html(almanac(almanac_time=eve)),
            'full moon')
        assert time.strftime('%b %-d', lt) in chip
        assert '>in 1 day<' in chip

    def test_satellite_pass_day_count(self, almanac, page):
        """The pass row carries a date too, so its day count is calendar
        days as well: a pass 30 hours out falls tomorrow, not in two days.
        Below a day the row keeps its finer elapsed-time resolution."""
        assert page._sat_when(almanac, TIME_TS + 30 * 3600, None) == 'in 1 day'
        assert page._sat_when(almanac, TIME_TS + 50 * 3600, None) == 'in 2 days'
        assert page._sat_when(almanac, TIME_TS + 3 * 3600, None) == 'in 3\u00a0h'
        assert page._sat_when(almanac, TIME_TS + 600, None) == 'in 10\u00a0m'
        assert page._sat_when(almanac, TIME_TS - 60, TIME_TS + 60) == 'overhead now'
        # Every rung floors, at the rung boundaries themselves: one second
        # under a day is 'in 23 h', never the 'in 24 h' that rounding gave
        # (a countdown the day rung never prints).
        assert page._sat_when(almanac, TIME_TS + 86399, None) == 'in 23\u00a0h'
        assert page._sat_when(almanac, TIME_TS + 86400, None) == 'in 1 day'
        assert page._sat_when(almanac, TIME_TS + 3599, None) == 'in 59\u00a0m'
        assert page._sat_when(almanac, TIME_TS + 3600, None) == 'in 1\u00a0h'
        assert page._sat_when(almanac, TIME_TS + 5400, None) == 'in 1\u00a0h'


class TestCatalogDome:
    """The dome plots every catalog star to star_mag_limit -- named or
    not -- while labels stay on named stars.  Since 2.0 the complete
    Hipparcos catalog ships with the extension, so this is the dome
    everyone gets."""

    def test_unnamed_stars_plotted_never_labeled(self, almanac, page):
        svg = page.dome_svg(almanac)
        assert_balanced(svg)
        # Gamma Cas (HIP 4427, mag 2.15, circumpolar here) has no
        # IAU-CSN/PyEphem name: a dot with a HIP tooltip, never a label
        # -- at the DEFAULT settings, the star Jacques missed is simply
        # there.
        assert 'HIP 4427' in svg
        assert not re.search(r'<text[^>]*>HIP \d', svg)
        assert 'starlab' in svg              # named stars still label

    def test_lowered_limit_restores_sparse_chart(self, almanac):
        few = wxskyfield_sky.SkyPage({'star_mag_limit': '2.6'}).dome_svg(almanac)
        many = wxskyfield_sky.SkyPage().dome_svg(almanac)
        # The pre-2.0 defaults remain the escape hatch to the sparse look.
        assert many.count('<circle') > few.count('<circle')


class TestConstellationDome:
    """The dome's constellation figures (1.19): clipped stick figures
    under the stars, a centroid label on each substantially-risen
    constellation, and the constellation_lines option."""

    def test_lines_and_labels_render(self, almanac, page):
        svg = page.dome_svg(almanac)
        assert_balanced(svg)
        assert svg.count('<polyline') > 50
        # The figures clip at the horizon rim, planetarium-style.
        assert 'clip-path="url(#domec-night)"' in svg
        assert '<clipPath id="domec-night">' in svg
        # Ursa Minor is circumpolar at the test latitude: always up,
        # always labeled (its centroid sits in the dome's quiet middle).
        assert '>Ursa Minor</text>' in svg
        assert 'class="conlab"' in svg

    def test_off_restores_plain_dome(self, almanac):
        svg = wxskyfield_sky.SkyPage(
            {'constellation_lines': 'false'}).dome_svg(almanac)
        assert_balanced(svg)
        assert '<polyline' not in svg
        assert 'conlab' not in svg
        assert 'starlab' in svg              # the stars are untouched

    def test_option_parsing(self):
        assert wxskyfield_sky.SkyPage()._constellation_lines
        assert not wxskyfield_sky.SkyPage(
            {'constellation_lines': 'false'})._constellation_lines
        assert not wxskyfield_sky.SkyPage(
            {'constellation_lines': 'Off'})._constellation_lines
        # A malformed value must never change the page's look: still on.
        assert wxskyfield_sky.SkyPage(
            {'constellation_lines': 'maybe'})._constellation_lines

    def test_labels_translate(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter(),
                texts={'Constellations': {'UMi': 'Kleiner Bär'}})
            # The sparse pre-2.0 star settings: this test is about the
            # translation plumbing, and at the dense defaults Ursa
            # Major's label legitimately yields to a star label.
            svg = wxskyfield_sky.SkyPage({'star_mag_limit': '2.6',
                                          'star_label_mag': '1.1'}).dome_svg(alm)
        # UMi reads its [Almanac] [[Constellations]] translation; an
        # untranslated constellation keeps its Latin name.
        assert '>Kleiner Bär</text>' in svg
        assert '>Ursa Major</text>' in svg

    def test_without_stars_no_lines(self, page):
        starless = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                                  load_stars=False)
        with saved_almanacs():
            assert wxskyfield.register_almanac(starless)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = page.dome_svg(alm)
        assert_balanced(svg)
        assert '<polyline' not in svg


class TestSatellitePanel:
    """The satellite rail panel and the Next Visible Pass chart (2.0): the
    anticipation half of the satellite feature.  One row per configured
    satellite giving its next VISIBLE pass; the soonest of those passes
    charted on its own single-epoch sky (the sky at the pass's
    culmination -- the dome draws no future arc); and a dome position
    marker only when a satellite is above the horizon at generation
    time."""

    def test_rows_give_next_visible_pass(self, almanac, page):
        html = page.satellites_html(almanac)
        assert_balanced(html)
        assert html.count('class="chip"') == 2
        # The ISS: the next morning's dark-sky pass, 15 hours out from
        # the fixture noon.  (ISS spelling needs the [Almanac] texts a
        # real report supplies; bare almanacs title-case the tag name.)
        assert 'Iss' in html
        assert 'Jun 22, 3:11 AM · in 15\u00a0h' in html
        assert 'appears SSW · peaks 19° SE · disappears ENE · 10\u00a0m' in html
        # Tiangong crosses all week but never visibly: the honest dash.
        assert 'no visible pass in the coming week' in html

    def test_has_satellites(self, almanac, page):
        assert page.has_satellites() is True

    def test_can_draw_public(self, almanac, page):
        """can_draw() is PUBLIC contract: an embedding skin gates the
        panels it places beside the dome on it (weewx-celestial 9.0), so
        a page without a dome need not draw one to learn whether it
        could.  True with the Skyfield almanac registered, False with
        none -- the tier where dome_svg comes back empty -- and never a
        raise."""
        assert page.can_draw() is True
        with saved_almanacs():
            weewx.almanac.almanacs[:] = []
            assert page.can_draw() is False

    def test_satellite_names_public(self, almanac, page):
        """satellite_names() is PUBLIC contract: embedding skins enumerate
        the configured satellites through it (weewx-celestial 8.0 builds
        its roster and live layer from the list), config order preserved."""
        assert page.satellite_names() == ['iss', 'tiangong']

    def test_no_satellites_hides_everything(self, page):
        """A station with no [[Satellites]]: the template guard hides the
        section, and the dome draws no arc and no marker."""
        plain = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                               load_stars=False)
        with saved_almanacs():
            assert wxskyfield.register_almanac(plain)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert page.has_satellites() is False
            assert page.satellite_names() == []
            assert page.satellites_html(alm) == ''
            assert page.pass_chart_html(alm) == ''
            svg = page.dome_svg(alm)
        assert 'satlab' not in svg

    def test_pass_chart_draws_soonest_visible_pass(self, almanac, page):
        """The Next Visible Pass chart: the sky at the pass's culmination with
        the arc across it (clipped, tooltipped, rise and set times at
        the ends -- the 1.10 moon-curve idiom), a dated head line
        (2025-06-22 is a Sunday), and the chart-epoch satellite loop
        putting the ISS's own dot at the peak of its arc.  That dot is
        the HOLLOW ring: this morning pass rises in Earth's shadow and
        exits it at 03:17, just after culmination -- the chart honestly
        shows the pass flaring into view mid-sky, not at the horizon."""
        html = page.pass_chart_html(almanac)
        assert_balanced(html)
        assert '<span class="passname">Iss</span>' in html
        assert 'Sun, Jun 22 · 3:11 AM → 3:21 AM · peak 19°' in html
        assert '<title>Iss pass — 3:11 AM → 3:21 AM, peak 19°</title>' in html
        assert '>3:11 AM</text>' in html and '>3:21 AM</text>' in html
        assert '<g class="dome-body" data-body="iss" data-sunlit="0">' in html
        assert 'alt 19.4°, az 130.2° — in shadow' in html
        assert 'class="satlab"' in html

    def test_dome_shows_only_the_current_sky(self, almanac, page):
        """The dome draws no future arc as of the pass chart's arrival:
        an undated future track on the now-sky read as tonight's, and
        mixed epochs on one chart drew a sky that will never exist.  No
        track group, no arc tooltip, and no marker while the ISS is
        below the horizon at the fixture noon."""
        svg = page.dome_svg(almanac)
        assert_balanced(svg)
        assert 'dome-track' not in svg
        assert 'Iss pass' not in svg
        assert 'Iss — alt' not in svg

    def test_pass_chart_ids_distinct_from_dome(self, almanac, page):
        """Both charts share one page, so their SVG gradient/clipPath
        ids must differ -- duplicate ids are invalid HTML, and worse than
        invalid: an id is global to the document and the FIRST element
        wins every url(#id), so a chart whose id collides paints with
        another chart's gradient."""
        dome = page.dome_svg(almanac)
        chart = page.pass_chart_html(almanac)
        assert 'id="skyg-night"' in dome and 'id="domec-night"' in dome
        assert 'id="skygp-night"' in chart and 'url(#domecp-night)' in chart
        assert 'id="skyg-night"' not in chart
        assert 'id="domec-night"' not in chart

    def test_two_plates_of_one_chart_do_not_share_a_gradient(self, almanac, page):
        """The collision the ids are really guarding against, and the one
        2.4's first cut had: a night dome and a light dome on the same
        page.  Both said id="skyg", so the light dome's sky resolved to
        the night gradient and drew navy under light-plate stars --
        verified in a browser before this test was written.  Two charts of
        the SAME plate may share an id, because they define identical
        gradients; two plates must not."""
        night = page.dome_svg(almanac)
        light = page.dome_svg(almanac, palette='light')
        for kind in ('skyg', 'domec'):
            night_id = 'id="%s-night"' % kind
            light_id = 'id="%s-light"' % kind
            assert night_id in night and light_id in light, kind
            assert night_id not in light and light_id not in night, kind
        # ... and the reference on each disc points at its own plate.
        assert 'url(#skyg-night)' in night and 'url(#skyg-light)' in light

    def test_pass_chart_twilight_cutoffs(self, almanac, page):
        """The chart plots a twilight sky (PASS_STAR_MAG_LIMIT, not the
        dome's option): far fewer stars than the dome's mag-5.0 field."""
        assert wxskyfield_sky.PASS_STAR_MAG_LIMIT < wxskyfield_sky.STAR_MAG_LIMIT
        chart = page.pass_chart_html(almanac)
        dome = page.dome_svg(almanac)
        assert 0 < chart.count('<circle') < dome.count('<circle')

    def test_dome_body_hooks(self, almanac, page):
        """Every dome mark and its label carry data-body="<tag>" -- the
        consumer contract weewx-celestial's live dome uses to reposition
        marks between report cycles (the <title> text is translated and
        cannot serve as a selector).  The pass arc's group names its
        satellite the same way -- on the pass chart, the arc's home."""
        svg = page.dome_svg(almanac)
        assert '<g class="dome-body" data-body="sun">' in svg
        assert re.search(r'<text[^>]*class="bodylab"[^>]*data-body="sun"', svg)
        chart = page.pass_chart_html(almanac)
        assert '<g class="dome-track" data-body="iss" ' in chart
        assert re.search(r'<text[^>]*class="satlab"[^>]*data-body="iss"', chart)

    def test_pass_track_carries_its_own_window(self, almanac, page):
        """2.3.2: the pass arc's group states the pass's OWN rise and set
        as epoch seconds (data-rise/data-set) -- the chart saying when the
        pass it depicts begins and ends, as the dome fragment declares its
        epoch.  weewx-celestial's live sweep judges the chart against this
        instead of the loop feed's next_visible_pass, which rolls to the
        following pass moments after this one sets and left the mark
        parked at the culmination under a finished-pass header (celestial
        8.3.3).  Pinned to the almanac's own numbers, integers, in
        rise-before-set order, on the same element as data-body."""
        chart = page.pass_chart_html(almanac)
        m = re.search(r'<g class="dome-track" data-body="iss" '
                      r'data-rise="(\d+)" data-set="(\d+)" ', chart)
        assert m, 'the track has no data-rise/data-set'
        rise, sset = int(m.group(1)), int(m.group(2))
        nvp = almanac.iss.next_visible_pass
        assert rise == int(round(nvp.rise.raw))
        assert sset == int(round(nvp.set.raw))
        assert rise < sset

    def test_dome_marker_only_when_overhead(self, sky):
        """At mid-pass the dome gets a position marker (the dome's 'sky
        at time T' contract); the pass chart meanwhile still shows the
        next VISIBLE pass, which this noon pass is not."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(PASS_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            mid_page = wxskyfield_sky.SkyPage()
            svg = mid_page.dome_svg(alm)
            chart = mid_page.pass_chart_html(alm)
        assert_balanced(svg)
        assert re.search(r'<title>Iss — alt 35\.\d°, az 22\d\.\d°</title>', svg)
        assert '<g class="dome-body" data-body="iss" data-sunlit="1">' in svg
        assert '<title>Iss pass — 3:11 AM → 3:21 AM, peak 19°</title>' in chart

    def test_shadowed_satellite_is_hollow(self, sky):
        """Pre-dawn the ISS crosses 29° up inside Earth's shadow: the
        marker inverts to the hollow ring -- brass stroke, halo fill, same
        footprint -- the tooltip says so, and data-sunlit="0" carries the
        state for weewx-celestial's live dome.  (The sunlit noon marker
        in test_dome_marker_only_when_overhead pins the solid form.)"""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(SHADOW_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = wxskyfield_sky.SkyPage().dome_svg(alm)
        assert_balanced(svg)
        assert re.search(r'<g class="dome-body" data-body="iss" data-sunlit="0">'
                         r'<circle [^>]*class="sky-fill-halo sky-stroke-brass"', svg)
        assert re.search(r'<title>Iss — alt 29\.\d°, az 16\d\.\d° — in shadow</title>',
                         svg)

    def test_sunlit_satellite_is_solid(self, sky):
        """The noon marker keeps the solid brass dot -- fill and stroke
        the exact inverse of the shadowed ring's."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(PASS_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            svg = wxskyfield_sky.SkyPage().dome_svg(alm)
        assert re.search(r'<g class="dome-body" data-body="iss" data-sunlit="1">'
                         r'<circle [^>]*class="sky-fill-brass sky-stroke-halo"', svg)
        assert 'in shadow' not in svg

    def test_stale_elements_point_at_log(self, sky):
        """Eight days past the fixture the elements are beyond the 7-day
        cutoff: every row says so (instead of a silently wrong pass), the
        dome drops its marker, and the pass chart is the empty state."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(TIME_TS + 8 * 86400, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            stale_page = wxskyfield_sky.SkyPage()
            html = stale_page.satellites_html(alm)
            svg = stale_page.dome_svg(alm)
            assert stale_page.pass_chart_html(alm) == ''
        assert_balanced(html)
        assert html.count('no usable orbital elements — see the weewxd log') == 2
        # No SATELLITE marker or label; the comet marks (which share the
        # satlab class) legitimately remain.
        assert 'data-body="iss"' not in svg
        assert 'data-body="tiangong"' not in svg

    def test_geostationary_only_no_track(self):
        """A configuration whose only satellite never rises: an honest
        no-pass row and no pass chart -- the page must not invent a
        pass."""
        geo_sky = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                                 load_stars=False,
                                 satellites={'geosat': 90000},
                                 sat_dir=SAT_DATA_DIR)
        with saved_almanacs():
            assert wxskyfield.register_almanac(geo_sky)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            geo_page = wxskyfield_sky.SkyPage()
            html = geo_page.satellites_html(alm)
            svg = geo_page.dome_svg(alm)
            assert geo_page.pass_chart_html(alm) == ''
        assert html.count('class="chip"') == 1
        assert 'no visible pass in the coming week' in html
        assert 'satlab' not in svg


class TestLabelLayers:
    """A sky chart can carry its labels laid out at more than one scale,
    for a page that serves a phone and a desktop layout from one URL: the
    marks drawn once, one `<g class="dome-labels" data-label-scale=...>`
    per scale, and the chart's own <style> picking the layer by media
    query.  Asked for by weewx-celestial 9.3, which had been fetching a
    second fragment set per scale to get the same effect.  The browser
    half of this
    (which layer actually DISPLAYS at a given viewport width) is claim 8
    of verify_sky_classes.py."""

    GROUP = re.compile(r'<g class="dome-labels" data-label-scale="([^"]*)">(.*?)</g>')
    TEXT = re.compile(r'<text[^>]*>.*?</text>')
    Q = '(max-width: 600px)'

    def _groups(self, markup):
        return {scale: body for scale, body in self.GROUP.findall(markup)}

    @staticmethod
    def _marks(markup):
        """The chart with its label groups, its style and the layer
        attributes removed: what the layers must share."""
        markup = re.sub(r'<g class="dome-labels"[^>]*>.*?</g>', '', markup)
        markup = re.sub(r'<style>.*?</style>', '', markup)
        return re.sub(r' data-label-(layers|media)="[^"]*"', '', markup)

    @staticmethod
    def _media_key(markup):
        keys = set(re.findall(r'<svg [^>]*data-label-media="([0-9a-f]{8})"', markup))
        assert len(keys) == 1, keys
        return keys.pop()

    def test_base_layer_is_always_wrapped(self, almanac, page):
        """One code path: with no extra layers the chart still carries its
        one layer in the group, every <text> inside it -- the cardinals,
        ring figures and pass times that used to sit beside their marks
        included -- and no media rule."""
        for meth in ('dome_svg', 'pass_chart_html'):
            markup = getattr(page, meth)(almanac)
            groups = self._groups(markup)
            assert list(groups) == ['1']
            assert 'data-label-layers="1"' in markup
            assert 'data-label-media' not in markup
            assert '@media' not in markup
            assert set(self.TEXT.findall(markup)) == set(self.TEXT.findall(groups['1']))
            assert '>N</text>' in groups['1'] and '30&#176;' in groups['1']
        assert 'class="mono nowlab"' in self._groups(page.pass_chart_html(almanac))['1']
        assert list(self._groups(page.dome_svg(almanac, label_scale=2.20))) == ['2.2']

    def test_each_layer_is_that_scale_s_own_layout(self, almanac, page):
        """The property the design rests on: a layer is EXACTLY what a
        plain render at that scale lays out (its own collision list, so
        bigger names and fewer of them fit), the marks are drawn once, and
        every layer's body and satellite names carry data-body."""
        for meth in ('dome_svg', 'pass_chart_html'):
            m = getattr(page, meth)
            layered = m(almanac, label_scale=0.8, label_layers=[(2.2, self.Q)])
            groups = self._groups(layered)
            assert list(groups) == ['0.8', '2.2']            # base first
            assert 'data-label-layers="0.8 2.2"' in layered
            for scale in ('0.8', '2.2'):
                assert groups[scale] == self._groups(m(almanac, label_scale=float(scale)))[scale]
            assert self._marks(layered) == self._marks(m(almanac, label_scale=0.8))
            assert 'font-size:11.2px' in groups['0.8']        # a cardinal, 14 * 0.8
            assert 'font-size:30.8px' in groups['2.2']
            assert (0 < groups['2.2'].count('class="starlab"')
                    < groups['0.8'].count('class="starlab"'))
            for scale in groups:
                assert re.search(r'<text[^>]*class="(bodylab|satlab)"[^>]*data-body=',
                                 groups[scale]), (meth, scale)
            assert_balanced(layered)

    def test_rules_pick_the_layer(self, almanac, page):
        """Each extra layer hidden; under its query the base hidden and it
        shown.  In the chart's own <style>, after the paint defaults, at
        plain specificity (a consumer's `.dome-labels{display:block}`
        must not show both layers), and scoped to the plate."""
        svg = page.dome_svg(almanac, label_scale=0.8, label_layers=[(2.2, self.Q)])
        key = self._media_key(svg)

        def sel(scale):
            return ('svg.sky-night[data-label-layers="0.8 2.2"][data-label-media="%s"] '
                    '.dome-labels[data-label-scale="%s"]' % (key, scale))
        assert (sel('2.2') + '{display:none}@media (max-width: 600px){'
                + sel('0.8') + '{display:none}' + sel('2.2') + '{display:inline}}') in svg
        assert svg.count('@media') == 1
        style = re.search(r'<style>(.*?)</style>', svg).group(1)
        assert style.startswith(':where(') and style.endswith('{display:inline}}')
        assert ':where(svg.sky-night) .dome-labels' not in svg
        light = page.dome_svg(almanac, palette='light', label_scale=0.8,
                              label_layers=[(2.2, self.Q)])
        assert ('svg.sky-light[data-label-layers="0.8 2.2"][data-label-media="%s"]'
                % self._media_key(light)) in light
        assert 'sky-night' not in light
        two = page.dome_svg(almanac, label_layers=[(1.6, '(max-width: 900px)'),
                                                   (2.2, self.Q)])
        assert list(self._groups(two)) == ['1', '1.6', '2.2']
        assert two.count('@media') == 2

    SCOPE = re.compile(r'svg\.sky-night\[data-label-layers="([^"]*)"\]'
                       r'\[data-label-media="([0-9a-f]{8})"\]')

    def test_rules_are_scoped_to_the_layer_set(self, almanac, page):
        """The plate alone is not enough scope: a layered dome beside an
        unlayered chart on the same plate, both at 0.8, would otherwise
        hide the other chart's only labels on the phone.  The rules name
        the layer set, and a chart with a different set cannot match."""
        layered = page.dome_svg(almanac, label_scale=0.8, label_layers=[(2.2, self.Q)])
        plain = page.pass_chart_html(almanac, label_scale=0.8)
        scopes = self.SCOPE.findall(layered)
        assert scopes and set(scopes) == {('0.8 2.2', self._media_key(layered))}
        assert 'data-label-layers="0.8"' in plain
        assert 'data-label-layers="0.8 2.2"' not in plain
        assert 'data-label-media' not in plain
        assert '@media' not in plain

    def test_rules_are_scoped_to_the_queries(self, almanac, page):
        """Same plate, same scales, different queries -- a width query on
        the dome, a portrait query on the pass chart -- must not switch
        each other's labels: every <style> reaches the whole page, so the
        key has to cover the queries as well as the scales.  Found by the
        2.5 code review.  The browser half is claim 8b of
        verify_sky_classes.py.  Charts with the same queries share a key,
        and their rules are then identical, which is harmless."""
        wide = page.dome_svg(almanac, label_scale=0.8, label_layers=[(2.2, self.Q)])
        tall = page.pass_chart_html(almanac, label_scale=0.8,
                                    label_layers=[(2.2, '(orientation: portrait)')])
        wide_key, tall_key = self._media_key(wide), self._media_key(tall)
        assert wide_key != tall_key
        assert {k for _s, k in self.SCOPE.findall(wide)} == {wide_key}
        assert {k for _s, k in self.SCOPE.findall(tall)} == {tall_key}
        same = page.pass_chart_html(almanac, label_scale=0.8, label_layers=[(2.2, self.Q)])
        assert self._media_key(same) == wide_key
        rules = re.compile(r'svg\.sky-night\[data-label-layers[^{]*\{display:none\}@media.*?\}\}')
        assert rules.findall(same) == rules.findall(wide)
        # Two extra layers: the key follows the query ORDER, which pairs
        # each query with its scale.
        ab = page.dome_svg(almanac, label_layers=[(1.6, '(max-width: 900px)'), (2.2, self.Q)])
        ba = page.dome_svg(almanac, label_layers=[(1.6, self.Q), (2.2, '(max-width: 900px)')])
        assert self._media_key(ab) != self._media_key(ba)

    def test_pass_head_takes_no_part(self, almanac, page):
        """The dated head line is HTML outside the SVG, sized by the page's
        CSS: layers leave it byte-identical."""
        plain = page.pass_chart_html(almanac)
        layered = page.pass_chart_html(almanac, label_layers=[(2.2, self.Q)])
        assert plain.startswith('<div class="passhead">')
        assert plain[:plain.index('<svg')] == layered[:layered.index('<svg')]

    def test_query_is_held_to_the_whitelist(self, almanac, page):
        """The query is written inside <style> inside inline SVG, where the
        HTML parser treats `<` and `&` as markup: the range syntax and
        anything that could close the block are refused, loudly and
        naming what is allowed; a bad query on a chart with no pass to
        draw is still refused."""
        for bad in ('(width < 600px)', '(max-width: 600px)} svg{display:none', '',
                    '   ', 'a&b', None, 600,
                    # Unbalanced: an unclosed ( would swallow every later
                    # rule in the block, a stray ) is never a valid query.
                    '(max-width: 600px', 'max-width: 600px)', ')(max-width: 600px('):
            with pytest.raises(wxskyfield_sky.SkyPageUsageError) as e:
                page.dome_svg(almanac, label_layers=[(2.2, bad)])
            msg = str(e.value)
            assert msg.startswith('label_layers media query %r is not usable' % (bad,))
            assert "for example '(max-width: 600px)'" in msg
        for ok in ('screen and (max-width: 600px)', '(orientation: portrait)',
                   '(min-width: 400px) and (max-width: 600px)',
                   'not print', '(max-width: 37.5em)', '  (max-width: 600px) '):
            svg = page.dome_svg(almanac, label_layers=[(2.2, ok)])
            assert '@media %s{' % ok.strip() in svg
        with pytest.raises(wxskyfield_sky.SkyPageUsageError):
            page.pass_chart_html(almanac, label_layers=[(2.2, 'a&b')])

    def test_scales_are_checked(self, almanac, page):
        """A scale is a positive finite number, distinct from every other
        layer's as formatted; a layer is a pair.  Text that reads as a
        number is fine -- skin.conf values arrive as text."""
        for bad in ([(0, self.Q)], [(-1, self.Q)], [(float('nan'), self.Q)],
                    [(float('inf'), self.Q)], [('big', self.Q)], [(None, self.Q)],
                    [(1.0, self.Q)],                        # repeats the base
                    [(2.2, self.Q), (2.2, '(max-width: 400px)')],
                    [(2.2, self.Q), (2.2000001, '(max-width: 400px)')],   # same as formatted
                    'nonsense', 7, [2.2], [(2.2,)], [(2.2, self.Q, 'extra')]):
            with pytest.raises(wxskyfield_sky.SkyPageUsageError):
                page.dome_svg(almanac, label_layers=bad)
        for bad_scale in (0, -2, 'x', None, float('nan')):
            with pytest.raises(wxskyfield_sky.SkyPageUsageError):
                page.dome_svg(almanac, label_scale=bad_scale)
        with pytest.raises(wxskyfield_sky.SkyPageUsageError) as e:
            page.dome_svg(almanac, label_layers=[(1, self.Q)])
        assert str(e.value) == ('label_layers scale 1 repeats a scale the chart already '
                                'draws; each layer needs its own')
        svg = page.dome_svg(almanac, label_scale='0.8', label_layers=[('2.2', self.Q)])
        assert list(self._groups(svg)) == ['0.8', '2.2']
        assert page.dome_svg(almanac, label_layers=[]) == page.dome_svg(almanac)
        assert page.dome_svg(almanac, label_layers=((2.2, self.Q),)) == \
            page.dome_svg(almanac, label_layers=[(2.2, self.Q)])


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
        assert 'Constellation figures: Stellarium' in html
        # Comets are configured in the fixture, so the MPC is credited.
        assert 'Comet elements: Minor Planet Center' in html
        assert 'Regenerated every report cycle' in html

    def test_no_mpc_credit_without_comets(self, page):
        """No configured comets, no MPC line -- the footer stays true for
        what actually computed the page."""
        cometless = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                                   load_stars=False)
        with saved_almanacs():
            assert wxskyfield.register_almanac(cometless)
            html = page.footer_html()
        assert 'Minor Planet Center' not in html

    def test_no_stellarium_credit_when_lines_off(self, almanac):
        """constellation_lines = false draws no figures, so the footer
        must not credit Stellarium; everything else is unchanged."""
        html = wxskyfield_sky.SkyPage({'constellation_lines': 'false'}).footer_html()
        assert 'Hipparcos star data Credit: ESA' in html
        assert 'Stellarium' not in html

    def test_no_stellarium_credit_when_lines_file_missing(self, page, tmp_path):
        """A live star catalog but an unreadable wxskyfield_lines.dat: no
        figures are drawn, so no Stellarium credit -- but the star credits
        stay (the catalog is fine)."""
        for name in ('wxskyfield_de421.bsp', wxskyfield.STAR_FILE):
            os.symlink(os.path.join(REPO_ROOT, 'bin', 'user', name),
                       os.path.join(str(tmp_path), name))
        lineless = wxskyfield.Sky(str(tmp_path), load_stars=True)
        assert lineless.is_valid() and lineless.stars
        assert lineless.constellation_lines() is None
        with saved_almanacs():
            assert wxskyfield.register_almanac(lineless)
            html = page.footer_html()
        assert 'Hipparcos star data Credit: ESA' in html
        assert 'Stellarium' not in html

    def test_stars_disabled(self, page):
        starless = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                                  load_stars=False)
        assert starless.is_valid()
        with saved_almanacs():
            assert wxskyfield.register_almanac(starless)
            html = page.footer_html()
        assert 'star catalog disabled' in html
        assert 'Hipparcos' not in html
        assert 'Stellarium' not in html          # no catalog, no figures
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
    (yellow sun, silver moon, gray Mercury, pearly Venus, blue Earth).  As
    of 2.3 'classic-night'/'classic-light' are aliases of those two rather
    than plates of their own."""

    RENDERERS = ('moon_svg', 'dome_svg', 'ribbons_svg', 'orrery_svg',
                 'analemma_svg', 'eot_svg', 'sunpath_svg', 'daylength_svg',
                 'lunation_svg', 'chips_html', 'table_html',
                 'countdown_html', 'header_sub')

    # The complete set of night-plate colors ever baked into markup.
    NIGHT_HEXES = ('#E9E4D4', '#8B93B8', '#C0C5D9', '#E0C27F', '#2A3358', '#6E7DBA',
                   '#0A0F22', '#1E2745', '#DDD8C4', '#161F3D', '#1B2749',
                   '#2A3A63', '#0B1129', '#131B38', '#1A2547', '#233153',
                   '#2E3D5C', '#FFD75E', '#C9D0DA', '#C04F36', '#D06C56')

    def test_default_is_night(self, almanac, page):
        for name in self.RENDERERS:
            meth = getattr(page, name)
            assert meth(almanac) == meth(almanac, palette='night')

    def test_night_goldens(self, almanac, page):
        """Default output bakes the night-plate values — traditional body
        colors as of 1.5."""
        dome = page.dome_svg(almanac)
        for hexval in ('#161F3D', '#1B2749', '#2A3A63',     # dome gradient
                       '#6E7DBA', '#E0C27F', '#E9E4D4', '#0A0F22'):
            assert hexval in dome
        # The rings and cross take `grid`, never the panel-border `line`:
        # on the dome gradient that value is 1.07:1, invisible (2.2).
        assert '#2A3358' not in dome
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
                       '#8a94a6', '#1d2c4e', '#7A899F'):    # rim, ink, grid
            assert hexval in dome
        assert '#c9cfd8' not in dome
        ribbons = page.ribbons_svg(almanac, palette='light')
        for hexval in ('#D7E6F5', '#A44A08', '#FACC15'):    # day band, now, sun
            assert hexval in ribbons
        orrery = page.orrery_svg(almanac, palette='light')
        for hexval in ('#FACC15', '#2E7DBE', '#1B5C8F'):    # sun, earth + ring
            assert hexval in orrery
        moon = page.moon_svg(almanac, palette='light')
        for hexval in ('#26314F', '#F2ECD8', '#868686'):    # disc + ring
            assert hexval in moon
        assert '#A44A08' in page.analemma_svg(almanac, palette='light')
        assert '#b23a24' in page.table_html(almanac, palette='light')   # mars

    def test_light_rings(self, almanac, page):
        """Pale bodies carry their ring color on the light plate: the sun's
        orrery dot, the moon and venus ribbon bars, and the chip/table dots
        (as an inset box-shadow, drawn by sky.css from --sky-dot-ring since
        2.4).  The night plate defines no rings — nothing pale needs a lift
        on navy — and sets no ring variable, so the shadow falls back to
        transparent."""
        ribbons = page.ribbons_svg(almanac, palette='light')
        for hexval in ('#767E8A', '#97864A'):               # moon, venus bars
            assert hexval in ribbons
        assert '#BC7800' in page.orrery_svg(almanac, palette='light')
        assert '--sky-dot-ring:#BC7800' in \
            page.chips_html(almanac, palette='light')
        assert '--sky-dot-ring:#767E8A' in \
            page.table_html(almanac, palette='light')
        assert '--sky-dot-ring' not in page.chips_html(almanac)
        assert '--sky-dot-ring' not in page.table_html(almanac)

    def test_a_plate_colors_exactly_the_drawn_bodies(self):
        """A plate gives a color to every body the panels paint, and to no
        others.

        The contrast audits below walk the PALETTE rather than the panels,
        so a color for a body nothing draws is a ratio measured on a mark
        that does not exist.  The light plate carried a `pluto` from 1.5 to
        2.4 -- picked up when the traditional-colors pass enumerated the
        ALMANAC's bodies -- and 2.3's change log duly reported having fixed
        its contrast against the twilight bands, where no Pluto has ever
        been drawn.  ($almanac.pluto is served in full; the charts plot the
        classical planets, and PLANETS has read Mercury through Neptune
        since v1.0.)  Rings are a per-body override and cannot name a body
        the plate has no color for."""
        drawn = set(wxskyfield_sky.CHART_BODIES)
        for plate, pal in wxskyfield_sky.PALETTES.items():
            assert set(pal['body']) == drawn, (
                '%s colors %s' % (plate, sorted(set(pal['body']) ^ drawn)))
            assert set(pal['ring']) <= drawn, plate

    def test_the_classic_names_still_render(self, almanac, page):
        """As of 2.3 'classic-night' and 'classic-light' are ALIASES of the
        two current plates, not plates of their own -- the pre-1.5 body
        colors they froze lasted a very short time and nothing was ever attached
        to them, while keeping them meant arguing every contrast fix twice,
        the second time on a plate whose premise was that it could not move.

        The names keep working on purpose: a skin still passing one must go
        on rendering rather than start raising at report time.  Two-sided,
        because both halves can break independently -- the name resolves,
        and it resolves to the CURRENT colors."""
        for classic, current in wxskyfield_sky.PALETTE_ALIASES.items():
            for name in self.RENDERERS:
                got = getattr(page, name)(almanac, palette=classic)
                assert got == getattr(page, name)(almanac, palette=current)
                assert_balanced(got)
        # The pre-1.5 values are gone from the module, not merely unreachable.
        for old in ('#B98C31', '#7E92DA', '#B8860B', '#4A5FB8', '#2e6e8e'):
            assert old not in str(wxskyfield_sky.PALETTES), old

    def test_a_classic_theme_option_warns_and_renders(self, almanac, caplog):
        """The other surface the dropped names can arrive on: the report's
        own theme option, which takes dark/light/auto rather than palette
        names.  A classic value there was never legal and used to fail the
        page outright; from 2.3 it warns and draws the plate that replaced
        it, so a station that set one gets a working page and a log line
        telling it what to change."""
        for value, expected in wxskyfield_sky.THEME_ALIASES.items():
            wxskyfield_sky._warned_palettes.clear()
            page = wxskyfield_sky.SkyPage({'theme': value})
            with caplog.at_level(logging.WARNING):
                caplog.clear()
                assert page.theme(almanac) == expected
                assert page.palette(almanac) == (
                    'light' if expected == 'light' else 'night')
            msgs = [r.getMessage() for r in caplog.records if value in r.getMessage()]
            assert len(msgs) == 1, msgs
            assert 'theme = %s' % expected in msgs[0]
        wxskyfield_sky._warned_palettes.clear()

    def test_the_two_surfaces_warn_independently(self, almanac, caplog):
        """A station can hit both surfaces with the same spelling -- a
        template passing palette='classic-night' on a report whose theme
        option says the same.  Through 2.3's first cut one set keyed by the
        bare name meant it heard about only whichever fired first, fixed
        that one, and never learned about the other."""
        wxskyfield_sky._warned_palettes.clear()
        try:
            page = wxskyfield_sky.SkyPage({'theme': 'classic-night'})
            with caplog.at_level(logging.WARNING):
                caplog.clear()
                page.ribbons_svg(almanac, palette='classic-night')
                assert page.theme(almanac) == 'dark'
            msgs = [r.getMessage() for r in caplog.records]
            assert sum(m.startswith('palette') for m in msgs) == 1, msgs
            assert sum(m.startswith('theme') for m in msgs) == 1, msgs
        finally:
            wxskyfield_sky._warned_palettes.clear()

    def test_a_classic_name_warns_once(self, almanac, page, caplog):
        """The rendering is silent about the substitution; the LOG is not --
        a skin still asking for a dropped name should be told, or the
        substitution is invisible until someone wonders why their colors
        moved.  Once per name per process, though: the page resolves its
        palette a dozen times per cycle and this must not fill the log."""
        wxskyfield_sky._warned_palettes.clear()
        try:
            with caplog.at_level(logging.WARNING):
                for _ in range(3):
                    page.ribbons_svg(almanac, palette='classic-night')
                page.dome_svg(almanac, palette='classic-night')
            warnings = [r for r in caplog.records
                        if 'classic-night' in r.getMessage()]
            assert len(warnings) == 1, [r.getMessage() for r in warnings]
            assert "'night'" in warnings[0].getMessage()
        finally:
            wxskyfield_sky._warned_palettes.clear()

    def test_unknown_palette_raises(self, almanac, page):
        for name in self.RENDERERS:
            with pytest.raises(ValueError, match='light, night'):
                getattr(page, name)(almanac, palette='sepia')


def _composite(fg, bg, opacity):
    """The real color of a translucent mark: SVG opacity is alpha
    compositing, so what the eye gets is the blend.  Returned as a hex
    string so it can serve as the BACKGROUND of a further mark -- which is
    what a casing is (see _band_rule)."""
    return '#%02X%02X%02X' % tuple(
        int(round(v)) for v in contrast.flatten(contrast.parse(fg)[:3] + (opacity,), bg))


def _measure(fg, bg, opacity=1.0):
    """(WCAG 2 ratio, APCA |Lc|) of fg over bg, fg first composited at
    `opacity` -- SVG opacity is alpha compositing, so a translucent mark's
    real color is the blend, not the value in the palette.  The arithmetic
    is tests/contrast.py's, the same copy its command line uses."""
    ground = contrast.flatten(bg)
    seen = contrast.flatten(contrast.parse(fg)[:3] + (opacity,), ground + (1.0,))
    return contrast.wcag(seen, ground), abs(contrast.apca(seen, ground))


def _contrast(fg, bg, opacity=1.0):
    """The WCAG 2 half of _measure alone, for the proofs that an audit can
    trip, which are written against that ratio."""
    return _measure(fg, bg, opacity)[0]


# The contrast standard, the same bars in every one of the author's
# extensions.  Every piece of text clears TEXT_BARS, with no relief for
# size or weight; a non-text mark that must be seen clears MARK_BARS.
# Opacity is part of the color and is applied before scoring.  Each is
# (WCAG 2 ratio, APCA |Lc|) and both halves must hold: through 2.5 the
# dome's star names passed the ratio at 4.59 and read Lc 46.
TEXT_BARS = (4.5, 60.0)
MARK_BARS = (3.0, 30.0)

# A mark allowed to miss MARK_BARS is a NAMED EXCEPTION, keyed by
# (plate, mark), with its reason.  _hold_mark enforces both directions: a
# listed mark must still miss -- one that starts clearing the bar comes out
# of this table rather than staying on to excuse a later regression -- and
# an unlisted one must clear.  A listed mark still holds the visibility
# floor its audit states.
_CHROME = ('chrome: the dome rings, the cross through the zenith and the '
           'band gridlines orient the eye and then get out of the way, so '
           'they sit below the graphics bar on purpose')
_FIGURES = ('background context: mockups of constellation lines bright '
            'enough to pass showed the star field turned into a net at the '
            'half scale the phone layout uses; their names carry them')
MARK_EXCEPTIONS = {
    ('night', 'dome rings'): _CHROME,
    ('night', 'dome cross'): _CHROME,
    ('light', 'dome rings'): _CHROME,
    ('light', 'dome cross'): _CHROME,
    ('night', 'band gridlines primary'): _CHROME,
    ('night', 'band gridlines secondary'): _CHROME,
    ('night', 'constellation figures'): _FIGURES,
    ('light', 'constellation figures'): _FIGURES,
}


def _clears(got, bars):
    return got[0] >= bars[0] and got[1] >= bars[1]


def _hold_mark(plate, mark, measured, floor):
    """Grade one mark against MARK_BARS, honoring MARK_EXCEPTIONS.
    measured: every (ratio, |Lc|) the mark takes, one per ground."""
    worst = (min(m[0] for m in measured), min(m[1] for m in measured))
    if (plate, mark) in MARK_EXCEPTIONS:
        assert not all(_clears(m, MARK_BARS) for m in measured), (
            '%s %s now clears %.1f / Lc %.0f everywhere (worst %.2f / Lc %.1f): '
            'remove its named exception'
            % (plate, mark, MARK_BARS[0], MARK_BARS[1], worst[0], worst[1]))
        assert worst[0] >= floor, ('%s %s is %.2f, under its visibility floor %.1f'
                                   % (plate, mark, worst[0], floor))
    else:
        assert all(_clears(m, MARK_BARS) for m in measured), (
            '%s %s is %.2f / Lc %.1f at worst, under %.1f / Lc %.0f'
            % (plate, mark, worst[0], worst[1], MARK_BARS[0], MARK_BARS[1]))


class TestContrastArithmetic:
    """The one copy of the contrast math, pinned at the points every
    extension sharing it pins, so a drifted constant fails here first."""

    def test_apca_oracle(self):
        assert contrast.apca((0, 0, 0), (255, 255, 255)) == pytest.approx(106.04, abs=0.005)
        assert contrast.apca((255, 255, 255), (0, 0, 0)) == pytest.approx(-107.88, abs=0.005)

    def test_wcag_oracle(self):
        assert contrast.wcag((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)

    def test_opacity_is_part_of_the_color(self):
        """The 2.5 night constellation name as the chart drew it with the
        sun up: #9DABD7 at 0.55 over the dome's rim.  Opaque it passed the
        ratio; composited it misses both bars by far."""
        assert _clears(_measure('#9DABD7', '#2A3A63'), (4.5, 0))
        got = _measure('#9DABD7', '#2A3A63', 0.55)
        assert got[0] == pytest.approx(2.56, abs=0.02)
        assert got[1] == pytest.approx(23.1, abs=0.2)
        assert not _clears(got, TEXT_BARS)

    def test_named_exceptions_say_why(self):
        for key, reason in MARK_EXCEPTIONS.items():
            assert key[0] in wxskyfield_sky.PALETTES, key
            assert len(reason) > 40, key

    def test_named_exceptions_name_graded_marks(self):
        """Every exception names a mark an audit still grades.  An entry
        that stops applying -- a gridline rank renamed, its mark graded
        under the new name -- would otherwise stay in the table, excusing
        nothing, which is how a stale exemption survives.  The gridline
        names come from BAND_RULE_OPACITY itself, the renamable part."""
        graded = {'dome rings', 'dome cross', 'constellation figures'}
        graded |= {'band gridlines %s' % rank
                   for rank in wxskyfield_sky.BAND_RULE_OPACITY}
        stale = sorted(key for key in MARK_EXCEPTIONS if key[1] not in graded)
        assert not stale, stale


class TestPageTextContrast:
    """The page's own text tokens against the grounds the page paints under
    them -- the body (--night) and every section (--vault) -- in both
    themes, read from the shipped sky.css so an edit there can fail it.
    Through 2.5 nothing graded these, and the night --muted read Lc 43.5 on
    a section, --brass Lc 57.6."""

    def test_text_tokens_clear_the_text_bars(self):
        with open(os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'sky.css')) as f:
            css = re.sub(r'/\*.*?\*/', ' ', f.read(), flags=re.S)
        for theme, pattern in (('dark', r':root\{(.*?)\}'),
                               ('light', r':root\.theme-light\{(.*?)\}')):
            block = re.search(pattern, css, re.S).group(1)
            tok = dict(re.findall(r'--([a-z]+):\s*(#[0-9A-Fa-f]{6})', block))
            for text in ('ink', 'muted', 'brass'):
                for ground in ('night', 'vault'):
                    got = _measure(tok[text], tok[ground])
                    assert _clears(got, TEXT_BARS), (
                        '%s --%s %s on --%s %s is %.2f / Lc %.1f'
                        % (theme, text, tok[text], ground, tok[ground], got[0], got[1]))


class TestClassContract:
    """The role classes and their zero-specificity defaults (2.4).

    Every graphical mark names its ROLE in a class and the SVG carries the
    requested plate's values for the roles it used, so a consuming skin can
    repaint any mark -- which is what a per-viewer light/dark switch needs,
    the SVG being written once per report cycle and flipped hours later.

    These are markup checks, and markup is only half the claim: whether the
    defaults actually WIN or LOSE against a consumer's rule is a CSS
    resolution question no source assertion can see.  That half lives in
    tests/verify_sky_classes.py, which reads computed styles out of a real
    browser -- test_the_browser_contract_holds runs it."""

    SVG_RENDERERS = ('moon_svg', 'dome_svg', 'ribbons_svg', 'orrery_svg',
                     'analemma_svg', 'eot_svg', 'sunpath_svg',
                     'daylength_svg', 'lunation_svg')

    def _classes_on_marks(self, svg):
        """Every sky- role class used in a class ATTRIBUTE (never the style
        block's own selectors), and the root plate class dropped."""
        out = set()
        for attr in re.findall(r'class="([^"]*)"', svg):
            out |= {c for c in attr.split()
                    if c.startswith('sky-') and c not in ('sky-night', 'sky-light')}
        return out

    def test_every_panel_carries_its_plate_class(self, almanac, page):
        """The defaults are scoped to this class on the <svg> itself.  Miss
        it and the panel renders unpainted -- and two panels of different
        plates on one page would repaint each other, a <style> inside
        inline SVG being document-wide in an HTML page."""
        for plate in ('night', 'light'):
            for name in self.SVG_RENDERERS:
                svg = getattr(page, name)(almanac, palette=plate)
                assert 'class="sky sky-%s"' % plate in svg, (plate, name)

    def test_the_style_block_defines_every_class_a_mark_uses(self, almanac, page):
        """A class on a mark with no default beside it renders unpainted --
        black, or nothing at all.  This is the check that catches a typo in
        a role name, which is otherwise invisible until someone looks at
        the page: `sky-fill-trace-moon` was written on the moon track's
        endpoint dots before the class existed."""
        for plate in ('night', 'light'):
            for name in self.SVG_RENDERERS:
                svg = getattr(page, name)(almanac, palette=plate)
                for cls in self._classes_on_marks(svg):
                    assert ':where(.%s){' % cls in svg, (
                        '%s %s: %s has no default' % (plate, name, cls))

    def test_the_style_block_defines_nothing_a_mark_does_not_use(
            self, almanac, page):
        """The other direction: the block is driven by the markup, so a
        panel carries its own roles -- and each of those roles in the other
        paint channel, for the swap below -- and not the whole palette."""
        for name in self.SVG_RENDERERS:
            svg = getattr(page, name)(almanac)
            used = self._classes_on_marks(svg)
            want = set(used)
            for cls in used:
                partner = wxskyfield_sky._partner(cls)
                if partner in wxskyfield_sky._sky_classes(
                        wxskyfield_sky.PALETTES['night']):
                    want.add(partner)
            defined = set(re.findall(r':where\(\.(sky-[a-z0-9-]+)\)\{', svg))
            assert defined == want, (name, sorted(defined ^ want))

    def test_a_swapped_mark_still_has_a_default(self, almanac, page):
        """The guarantee the documented flip technique stands on.

        A mark whose two states are one another's inverse -- a sunlit
        satellite is `sky-fill-brass sky-stroke-halo`, a shadowed one the
        same pair exchanged -- lets a live consumer invert it by exchanging
        the suffixes, without naming a color.  That only works if the
        partner class has a rule.  Emitting only what the chart happened to
        draw broke it: a chart whose satellite was sunlit never filled with
        halo, so the swapped mark asked for `sky-fill-halo`, found nothing,
        and fell back to the SVG initial -- black for a fill.  Caught by a
        consumer's code review, in the technique this repo recommends."""
        for plate in ('night', 'light'):
            for name in self.SVG_RENDERERS:
                svg = getattr(page, name)(almanac, palette=plate)
                for cls in self._classes_on_marks(svg):
                    partner = wxskyfield_sky._partner(cls)
                    if partner is None or partner not in wxskyfield_sky._sky_classes(
                            wxskyfield_sky.PALETTES[plate]):
                        continue
                    assert ':where(.%s){' % partner in svg, (
                        '%s %s: swapping %s asks for %s, which has no default'
                        % (plate, name, cls, partner))

    def test_no_mark_takes_two_roles_in_one_channel(self, almanac, page):
        """Two fill roles (or two stroke roles) on one mark leaves the
        winner to the order the defaults happen to be written in, which is
        alphabetical and means nothing.  The ribbons bar shipped that way
        for an afternoon: it carried the body's rim AND the plate's
        bandedge, and the rim won because 'r' sorts after 'b'."""
        for plate in ('night', 'light'):
            for name in self.SVG_RENDERERS:
                svg = getattr(page, name)(almanac, palette=plate)
                for attr in re.findall(r'class="([^"]*)"', svg):
                    roles = [c for c in attr.split() if c.startswith('sky-')]
                    fills = [c for c in roles if c.startswith('sky-fill-')]
                    strokes = [c for c in roles if c.startswith('sky-stroke-')]
                    assert len(fills) <= 1, (plate, name, attr)
                    assert len(strokes) <= 1, (plate, name, attr)

    def test_no_svg_panel_bakes_a_color(self, almanac, page):
        """The point of the exercise: outside the style block, no mark
        carries a color a stylesheet cannot reach.  (The chip and table
        swatches are HTML rather than SVG and stay baked, by agreement with
        the consuming skin that themes them.)"""
        for plate in ('night', 'light'):
            for name in self.SVG_RENDERERS:
                svg = getattr(page, name)(almanac, palette=plate)
                marks = re.sub(r'<style>.*?</style>', '', svg, flags=re.S)
                for attr in ('fill', 'stroke', 'stop-color'):
                    assert '%s="#' % attr not in marks, (
                        '%s %s bakes a %s' % (plate, name, attr))

    def test_an_alias_scopes_to_the_plate_it_resolves_to(self, almanac, page):
        """A skin still passing 'classic-night' must get a working panel,
        not one whose defaults name a plate class the root does not carry.
        The name has to resolve BEFORE it reaches the markup."""
        wxskyfield_sky._warned_palettes.clear()
        try:
            for classic, current in wxskyfield_sky.PALETTE_ALIASES.items():
                svg = page.dome_svg(almanac, palette=classic)
                assert 'class="sky sky-%s"' % current in svg, classic
                assert ':where(svg.sky-%s)' % current in svg, classic
        finally:
            wxskyfield_sky._warned_palettes.clear()

    def test_both_plates_paint_their_casing(self, almanac, page):
        """The structural half of 2.4: the casing is an ELEMENT on both
        plates, because markup a plate declines to write is markup a reader
        who flips to the other plate can never get back.  Both plates now
        give it a value too: the night plate's is its night band's own
        color, which covers the sun's arc under the sun-path hour numbers
        (ink over that arc read 1.17:1)."""
        svg = page.ribbons_svg(almanac)
        assert 'class="sky-fill-bandcase"' in svg
        assert (':where(.sky-fill-bandcase){fill:%s}'
                % wxskyfield_sky.PALETTES['night']['twilight']['night']) in svg
        light = page.ribbons_svg(almanac, palette='light')
        assert ':where(.sky-fill-bandcase){fill:#ffffff}' in light

    def test_the_two_plates_shape_the_dome_gradient_alike(self):
        """A stop's OFFSET is an attribute, not a CSS property, so it
        cannot follow a reader's theme switch.  Two plates with different
        offsets would leave a flipped page drawing the other plate's
        geometry, so both ramp through the same three."""
        offsets = [tuple(o for o, _c in pal['dome_stops'])
                   for pal in wxskyfield_sky.PALETTES.values()]
        assert len(set(offsets)) == 1, offsets

    def test_the_browser_contract_holds(self):
        """Which rule wins is not a question the markup can answer.  Runs
        the real thing in Chromium: an untouched panel draws its plate, a
        one-class consumer rule beats our default, two plates on one page
        do not repaint each other, a night panel flips to light, and the
        casing the night plate declines can be handed a color."""
        script = os.path.join(TEST_DIR, 'verify_sky_classes.py')
        if not os.path.exists(os.path.join(REPO_ROOT, 'tools', 'pwenv',
                                           'bin', 'python')):
            pytest.skip('no browser environment (tools/pwenv)')
        proc = subprocess.run([sys.executable, script], capture_output=True,
                              text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr


class TestSkyChartContrast:
    """Every mark on the two sky charts (the dome and the Next Visible Pass
    chart -- one _sky_chart, so one audit) must hold its bars against the
    dome gradient it is drawn on, on BOTH plates.

    This exists because the altitude rings and the cross through the zenith
    (the meridian and the prime vertical -- the horizon is the rim, and is
    drawn separately) shipped through 2.1.3 at 1.07:1 -- they took `line`,
    the panel-border
    color, whose luminance is within a hair of the dome's own.  Nothing
    caught it: the rings were present, correct and invisible.  A golden-hex
    test cannot see that; only the ratio can.

    Text clears TEXT_BARS, marks MARK_BARS.  The chrome and the
    constellation figures are named exceptions (MARK_EXCEPTIONS), each held
    to a visibility floor of its own below."""

    SKIN_DIR = os.path.join(REPO_ROOT, 'skins', 'Skyfield')
    # The rings and cross are chrome: they orient the eye and then get out
    # of the way.  The floor is that they stay unambiguously visible -- an
    # order of magnitude off the 1.07 that made them disappear.
    CHROME_FLOOR = 1.9
    # The constellation FIGURES are left under the mark bars by choice
    # (night 1.87, light 1.47).  Mockups of the compliant version showed
    # why: at the half scale the phone layout uses, lines bright enough to
    # pass turn the star field into a net over the sky rather than figures
    # within it.  Their LABELS were lifted instead -- a dozen marks, not
    # five hundred segments.  This floor is "no worse than 2.2 shipped",
    # not a standard.
    FIGURE_FLOOR = 1.4

    def _dome_stops(self, pal):
        """Every stop of the dome gradient.  Which one is hardest to hold a
        mark against depends on the mark's own luminance, so rather than
        reason about it the audit tests all of them."""
        return [c for _offset, c in pal['dome_stops']]

    def _chart_label_fills(self):
        """The chart's text colors live in sky.css, not the palette, so
        read them from the shipped file -- a CSS edit must be able to fail
        this audit.  .skylab is the sky charts' scoped opt-in out of the
        panel-surface .gridlab gray.  Returns {class: (night, light)}."""
        with open(os.path.join(self.SKIN_DIR, 'sky.css')) as f:
            css = f.read()
        # Comments out, FIRST.  The rule split below reads everything up
        # to a '{' as the selector, so a comment written above a rule
        # becomes part of that rule's selector -- the lookup then misses,
        # fill_of returns None, and a light override grades silently as the
        # dark value it falls back to.  A comment explaining why a color was
        # chosen is exactly what sits above these rules (2.4).
        css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
        root = re.search(r':root\{(.*?)\}', css, re.S).group(1)
        light_root = re.search(r':root\.theme-light\{(.*?)\}', css, re.S).group(1)

        def var(block, name):
            return re.search(r'--%s:\s*(#[0-9A-Fa-f]{6})' % name, block).group(1)

        # Selector -> declarations, matched EXACTLY.  Reading the first
        # `.cls{` in the file would grade a scoped rule as the base one the
        # day someone reorders the stylesheet, and requiring `fill` to be a
        # rule's last declaration would silently fall back to the dark value
        # the day a light override gains a second property.  Neither failure
        # announces itself, so parse instead of pattern-matching.
        rules = [(' '.join(sel.split()), body)
                 for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)]

        def fill_of(selector):
            bodies = [b for sel, b in rules if sel == selector]
            assert len(bodies) < 2, 'two rules for %s -- which wins?' % selector
            if not bodies:
                return None
            m = re.search(r'(?:^|;)\s*fill:\s*([^;]+)', bodies[0])
            return m.group(1).strip() if m else None

        out = {}
        # satlab and nowlab are brass and sit INSIDE the dome -- a satellite
        # name beside its marker, a pass's rise and set times nudged in from
        # the rim.  They were not graded until 2.4, and the paper plate's
        # brass measured 4.44 against the gradient's middle and 4.25 against
        # its rim.  Grading three of the chart's label classes and calling
        # it the chart's audit is how that shipped.
        for cls in ('skylab', 'starlab', 'conlab', 'satlab', 'nowlab'):
            dark = fill_of('.%s' % cls)
            assert dark, cls
            light = fill_of(':root.theme-light .%s' % cls) or dark
            resolved = []
            for value, block in ((dark, root), (light, light_root)):
                value = value.strip()
                v = re.match(r'var\(--([a-z]+)\)', value)
                resolved.append(var(block, v.group(1)) if v else value)
            out[cls] = tuple(resolved)
        return out

    def test_text_marks_clear_the_text_bars(self):
        """Star names, ring degrees, constellation names, satellite names
        and pass times, against every stop of the gradient.

        As of 2.4 satlab and nowlab are graded too -- brass text, inside
        the dome, ungraded until a consuming skin measured it at 4.25
        against the paper plate's rim.

        Through 2.5 this audit graded the ratio alone, and graded star and
        constellation names only at the dark-sky opacity: while the sun was
        up the chart dimmed them with the star field, to Lc 23 on the night
        plate.  Names are now drawn at full strength at every hour
        (test_the_dome_draws_the_opacities_the_audit_reads pins it), so
        there is no opacity to composite and no hour this can miss."""
        fills = self._chart_label_fills()
        for plate, idx in (('night', 0), ('light', 1)):
            pal = wxskyfield_sky.PALETTES[plate]
            for cls in sorted(fills):
                fill = fills[cls][idx]
                for stop in self._dome_stops(pal):
                    got = _measure(fill, stop)
                    assert _clears(got, TEXT_BARS), (
                        '%s .%s %s on %s is %.2f / Lc %.1f, under %.1f / Lc %.0f'
                        % (plate, cls, fill, stop, got[0], got[1],
                           TEXT_BARS[0], TEXT_BARS[1]))

    def test_body_dots_clear_the_mark_bars(self):
        """A body dot clears the bars by its FILL or by its RING -- that is
        exactly what the palette's `ring` key is for, and the pale bodies on
        the paper plate (sun, venus) rely on it.  Night Mars read Lc 29.2 on
        the dome's rim through 2.5."""
        for plate in ('night', 'light'):
            pal = wxskyfield_sky.PALETTES[plate]
            for name, fill in pal['body'].items():
                ring = pal['ring'].get(name)
                for stop in self._dome_stops(pal):
                    got = _measure(fill, stop)
                    ok = _clears(got, MARK_BARS) or (
                        ring is not None and _clears(_measure(ring, stop), MARK_BARS))
                    assert ok, ('%s %s (fill %s, ring %s) on %s: fill %.2f / Lc %.1f'
                                % (plate, name, fill, ring, stop, got[0], got[1]))

    def test_rings_and_cross_are_visible(self):
        """The 2.1.3 defect, pinned.  `grid` must never fall back to
        `line`: on both plates that value is ~1.1 against the dome."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            assert pal['grid'] != pal['line'], plate
            for mark, opacity in (('dome rings', wxskyfield_sky.DOME_RING_OPACITY),
                                  ('dome cross', wxskyfield_sky.DOME_CROSS_OPACITY)):
                _hold_mark(plate, mark,
                           [_measure(pal['grid'], stop, opacity)
                            for stop in self._dome_stops(pal)],
                           self.CHROME_FLOOR)

    def test_constellation_figures_stay_recessive(self):
        """Two-sided on purpose: the figures must stay visible, and must
        NOT be lifted to the mark bars without revisiting the half-scale
        render that argued against it -- their named exception fails the
        day they clear."""
        for plate in ('night', 'light'):
            pal = wxskyfield_sky.PALETTES[plate]
            _hold_mark(plate, 'constellation figures',
                       [_measure(pal['conline'], stop,
                                 wxskyfield_sky.CONLINE_OPACITY_DARK)
                        for stop in self._dome_stops(pal)],
                       self.FIGURE_FLOOR)

    def test_the_dome_draws_the_opacities_the_audit_reads(self, almanac, page):
        """The audit's numbers are composites at the module's opacities, so
        they mean nothing unless the dome really renders at them.  Checked
        in the rendered svg: the constant and the chart cannot drift apart
        without this failing, and no source grep is involved."""
        dome = page.dome_svg(almanac)
        assert ('stroke-dasharray="3 5" opacity="%s"'
                % wxskyfield_sky.DOME_RING_OPACITY) in dome
        assert dome.count('stroke-width="1" opacity="%s"'
                          % wxskyfield_sky.DOME_CROSS_OPACITY) == 2
        # The fixture instant is local noon, the hour the chart used to dim
        # star and constellation names along with the star field.  The
        # MARKS still dim; the names must not, on any element or on the
        # layer that holds them -- the text bars are scored at full
        # strength, and an opacity anywhere above a label makes that fiction.
        assert page.sun_is_up(almanac)
        assert re.search(r'<circle[^>]*class="sky-fill-ink" opacity="%.2f"'
                         % wxskyfield_sky.STAR_OPACITY_SUN_UP, dome)
        for cls in ('starlab', 'conlab'):
            texts = re.findall(r'<text[^>]*class="%s"[^>]*>' % cls, dome)
            assert texts, cls
            assert not [t for t in texts if 'opacity' in t], (cls, texts[:3])
        assert not re.search(r'<g class="dome-labels"[^>]*opacity', dome)


class TestLabelKeepouts:
    """Labels step clear of body marks where there is room.  A planet's
    name over the noon sun measured 1.09:1 and a pass's set time over the
    moon's dark disc 2.18: each label cleared its bars against the sky and
    read against a disc instead.  _sky_chart hands _place_labels every body
    mark as a box, and the layout counts those boxes as already placed.  A
    label that must be drawn and finds no room in five steps is still
    drawn -- the fixtures below are not that crowded."""

    KEEP = [(100.0, 90.0, 160.0, 110.0)]
    DAY_TS = 1750536000          # 2025-06-21 13:00 PDT: Jupiter beside the sun

    @staticmethod
    def _texts(svg):
        return [(float(x), float(y), t) for x, y, t in re.findall(
            r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*>([^<]*)</text>', svg)]

    def test_a_body_name_steps_off_a_mark(self):
        out = wxskyfield_sky.SkyPage._place_labels(
            [('mark', 100.0, 100.0, 'Jupiter', 'bodylab', 8, True, None)],
            1.0, 680, self.KEEP)
        (_x, y, text), = self._texts(out)
        assert text == 'Jupiter'
        assert y - 11.0 >= 110.0, y

    def test_an_optional_name_yields_to_a_mark(self):
        for req in (('mark', 100.0, 100.0, 'Mizar', 'starlab', 6, False, None),
                    ('con', 130.0, 100.0, 'LYRA')):
            out = wxskyfield_sky.SkyPage._place_labels([req], 1.0, 680, self.KEEP)
            assert self._texts(out) == [], req

    def test_a_pass_time_steps_inward_off_a_mark(self):
        """Four steps of 10 clear the box, so the label is placed by the
        clear check, not by running out of tries (five)."""
        out = wxskyfield_sky.SkyPage._place_labels(
            [('time', 100.0, 100.0, '03:21', 1.0, 0.0)], 1.0, 680,
            [(80.0, 85.0, 115.0, 110.0)])
        (x, y, text), = self._texts(out)
        assert text == '03:21'
        assert x == pytest.approx(140.0), x
        assert y == pytest.approx(103.0)

    def test_with_nothing_in_the_way_nothing_moves(self):
        out = wxskyfield_sky.SkyPage._place_labels(
            [('time', 100.0, 100.0, '03:21', 1.0, 0.0),
             ('mark', 300.0, 300.0, 'Mars', 'bodylab', 8, True, None)], 1.0, 680)
        texts = self._texts(out)
        assert (100.0, 103.0, '03:21') in texts, texts
        assert (308.0, 304.0, 'Mars') in texts, texts

    @staticmethod
    def _marks(svg):
        """{body: box} for every body mark, sized by everything the mark
        draws -- the sun's rays as well as its disc, a comet's diamond, a
        radiant's rays -- read out of the rendered SVG.  A comet's tail is
        left out: it trails away from the mark and is not kept clear."""
        marks = {}
        for body, inner in re.findall(
                r'<g class="dome-body[^"]*" data-body="([^"]+)"[^>]*>(.*?)</g>', svg):
            xs, ys = [], []
            for cx, cy, r in re.findall(
                    r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)"', inner):
                cx, cy, r = float(cx), float(cy), float(r)
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
            for line in re.findall(r'<line [^>]*>', inner):
                if 'comet-tail' in line:
                    continue
                for axis, vals in (('x', xs), ('y', ys)):
                    vals += [float(v) for v in re.findall(
                        r' %s[12]="([-\d.]+)"' % axis, line)]
            for d in re.findall(r'<path d="(M[-\d. L]+Z)"', inner):
                pts = [float(v) for v in re.findall(r'-?[\d.]+', d)]
                xs += pts[0::2]
                ys += pts[1::2]
            if xs:
                marks[body] = (min(xs), min(ys), max(xs), max(ys))
        return marks

    def _overlaps(self, svg):
        """Every label box, estimated as the layout estimates it, that
        touches another body's mark in the chart's first label layer."""
        marks = sorted(self._marks(svg).items())
        assert marks
        layer = svg.split('<g class="dome-labels"')[1].split('</g>')[0]
        boxes = []
        for x, y, anchor, cls, px, body, text in re.findall(
                r'<text x="([-\d.]+)" y="([-\d.]+)" text-anchor="(\w+)" '
                r'class="(bodylab|satlab)" style="font-size:([\d.]+)px" '
                r'data-body="([^"]+)">([^<]*)</text>', layer):
            x, y, px = float(x), float(y), float(px)
            w = 0.62 * px * len(text)
            x0 = x if anchor == 'start' else x - w
            boxes.append((body, text, (x0, y - px, x0 + w, y + 2)))
        for x, y, px, text in re.findall(
                r'<text x="([-\d.]+)" y="([-\d.]+)" text-anchor="middle" '
                r'class="mono nowlab" style="font-size:([\d.]+)px">([^<]*)</text>', layer):
            x, y, px = float(x), float(y) - 3, float(px)
            boxes.append((None, text, (x - 2 * px, y - px, x + 2 * px, y + 5)))
        assert boxes
        hits = []
        for body, text, b in boxes:
            for mbody, m in marks:
                if mbody != body and b[0] < m[2] and b[2] > m[0] and b[1] < m[3] and b[3] > m[1]:
                    hits.append('%s over %s' % (text, mbody))
        return hits

    def test_every_drawn_mark_is_kept_clear(self, sky, monkeypatch):
        """The keep-out boxes the chart hands the layout must cover each
        mark as DRAWN -- the sun's rays, a comet's diamond -- not a smaller
        idea of it.  Checked directly rather than through where labels
        happen to fall: at the fixture instants no label sits on the sun's
        rays, so shrinking the sun's keep-out to its disc would pass the
        end-to-end test below and fail only here."""
        seen = []
        real = wxskyfield_sky.SkyPage._place_labels

        def spy(labels, scale, S, keep=None):
            seen.append(list(keep or []))
            return real(labels, scale, S, keep)
        monkeypatch.setattr(wxskyfield_sky.SkyPage, '_place_labels', staticmethod(spy))
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            day = weewx.almanac.Almanac(self.DAY_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            dome = wxskyfield_sky.SkyPage().dome_svg(day)
        keep = seen[0]
        marks = self._marks(dome)
        assert {'sun', 'moon', 'halley'} <= set(marks), sorted(marks)
        for body, m in sorted(marks.items()):
            assert any(k[0] <= m[0] and k[1] <= m[1] and k[2] >= m[2] and k[3] >= m[3]
                       for k in keep), (body, m)

    def test_the_charts_seed_every_body_mark(self, sky):
        """End to end: at 13:00 on the fixture day, when Jupiter stands
        beside the sun, and on the pass chart, no body name or pass time is
        laid over another body's mark."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            fmt = weewx.units.get_default_formatter()
            day = weewx.almanac.Almanac(self.DAY_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M, formatter=fmt)
            noon = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                         altitude=ALTITUDE_M, formatter=fmt)
            page = wxskyfield_sky.SkyPage()
            for plate in ('night', 'light'):
                dome = page.dome_svg(day, palette=plate)
                assert 'Jupiter' in dome
                # The sun's box must be its rays, not just its disc.
                sun = self._marks(dome)['sun']
                assert sun[2] - sun[0] > 30.0, sun
                assert self._overlaps(dome) == [], plate
                chart = page.pass_chart_html(noon, palette=plate)
                assert 'nowlab' in chart
                assert self._overlaps(chart) == [], plate


class TestBandLabelContrast:
    """Every LABEL that lands on the twilight bands, measured against the
    ground it actually lands on -- read out of the rendered SVG rather than
    from a list of the classes someone remembered.

    This is the audit that was missing, and the gap was not subtle: the
    chart draws nine label classes and TestSkyChartContrast graded three of
    them, all on the dome.  Two failures shipped behind that.  The moon's
    times on the sun path took the moon's dot RIM color, right for a 1px
    edge on a pale disc and 2.09:1 as 10px text on the civil band; and the
    hour numbers that follow the arc down through the bands took the
    panel-surface gray, 1.03 on the paper plate's astronomical band and
    3.59 on the NIGHT plate's day band.  Both were found by a consuming
    skin, not here (2.4).

    Reading the ground from the markup is the whole point.  A label's
    ground depends on where the sun happens to put it, which is a function
    of the date and the latitude -- so this renders at two of them, and
    would have caught either defect at either one."""

    BARS = TEXT_BARS
    PANELS = ('sunpath_svg', 'ribbons_svg', 'daylength_svg')
    # Palo Alto, and inside the Arctic Circle where the arc lies along the
    # bands rather than crossing them.  Two is a compromise: each sun-path
    # render evaluates the almanac 97 times.
    PLACES = ((LATITUDE, LONGITUDE), (69.6492, 18.9553))

    def _fills(self):
        """{class: (night fill, light fill)} for every class sky.css gives
        a fill to, with var() resolved and comments stripped."""
        with open(os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'sky.css')) as f:
            css = re.sub(r'/\*.*?\*/', ' ', f.read(), flags=re.S)
        root = re.search(r':root\{(.*?)\}', css, re.S).group(1)
        light_root = re.search(r':root\.theme-light\{(.*?)\}', css, re.S).group(1)

        def resolve(value, block):
            v = re.match(r'var\(--([a-z]+)\)', value.strip())
            if not v:
                return value.strip()
            return re.search(r'--%s:\s*(#[0-9A-Fa-f]{6})' % v.group(1),
                             block, re.I).group(1)

        rules = []
        for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            m = re.search(r'(?:^|;)\s*fill:\s*([^;]+)', body)
            if m:
                rules.append((' '.join(sel.split()), m.group(1)))
        return rules, root, light_root, resolve

    def _winning(self, classes, plate, rules, root, light_root, resolve):
        """The fill the ELEMENT gets, not the one a single class would.

        The dome's ring labels carry `mono gridlab skylab` and the band
        hour labels `mono gridlab bandlab`; grading a class at a time
        reports the value the cascade threw away."""
        best = None
        for order, (sel, value) in enumerate(rules):
            for cls in classes:
                if sel == '.%s' % cls:
                    rank = 1
                elif plate == 'light' and sel == ':root.theme-light .%s' % cls:
                    rank = 2
                else:
                    continue
                if best is None or (rank, order) >= best[0]:
                    best = ((rank, order), value)
        if best is None:
            return None
        return resolve(best[1], light_root if plate == 'light' else root)

    def test_every_label_over_a_band_clears_the_text_bars(self, sky):
        rules, root, light_root, resolve = self._fills()
        worst = []
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            for lat, lon in self.PLACES:
                alm = weewx.almanac.Almanac(
                    TIME_TS, lat, lon, altitude=ALTITUDE_M,
                    formatter=weewx.units.get_default_formatter())
                for plate in ('night', 'light'):
                    pal = wxskyfield_sky.PALETTES[plate]
                    for panel in self.PANELS:
                        svg = getattr(wxskyfield_sky.SkyPage(), panel)(
                            alm, palette=plate)
                        bands = [(float(m.group(1)), float(m.group(2)),
                                  float(m.group(3)), float(m.group(4)), m.group(5))
                                 for m in re.finditer(
                                     r'<rect x="([\d.]+)" y="([\d.]+)" '
                                     r'width="([\d.]+)" height="([\d.]+)" '
                                     r'class="sky-fill-tw-(\w+)"', svg)]
                        texts = re.findall(
                            r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*'
                            r'class="([^"]*)"[^>]*>', svg)
                        cased = {(round(float(x), 1), round(float(y), 1))
                                 for x, y, cls in texts
                                 if 'sky-fill-bandcase' in cls}
                        for x, y, classes in texts:
                            if 'sky-fill-bandcase' in classes:
                                continue          # the casing is not a label
                            x, y = float(x), float(y)
                            names = [c for c in classes.split()
                                     if c != 'mono' and not c.startswith('sky-')]
                            fill = self._winning(names, plate, rules, root,
                                                 light_root, resolve)
                            on = [(n, pal['twilight'][n])
                                  for bx, by, w, h, n in bands
                                  if bx <= x <= bx + w and by <= y <= by + h]
                            if fill is None or not on:
                                continue
                            # A label with a casing reads against the
                            # casing, which is the point of having one --
                            # and on a plate that declines one, against the
                            # band, which is why the night plate's labels
                            # have to clear the bands by color alone.
                            if (round(x, 1), round(y, 1)) in cased and pal['bandcase']:
                                on = [('its casing', pal['bandcase'])]
                            for where, bg in on:
                                got = _measure(fill, bg)
                                if not _clears(got, self.BARS):
                                    worst.append(
                                        '%s %s lat %.1f: %s (%s) on %s (%s) is '
                                        '%.2f / Lc %.1f' % (plate, panel, lat, classes,
                                                            fill, where, bg, got[0], got[1]))
        assert not worst, '\n'.join([''] + sorted(set(worst)))

    def test_the_audit_reads_labels_and_bands(self, sky):
        """A scanner that matched nothing would pass for ever.  Both halves
        have to be found: the bands, and text sitting on them."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter())
            svg = wxskyfield_sky.SkyPage().sunpath_svg(alm, palette='light')
        bands = re.findall(r'class="sky-fill-tw-(\w+)"', svg)
        assert len(set(bands)) >= 4, sorted(set(bands))
        assert 'bandlab' in svg
        assert 'sky-fill-bandcase sky-stroke-bandcase' in svg


class TestPanelGridContrast:
    """The three panels that plot over TWILIGHT BANDS -- ribbons, sun path
    and day length -- draw their gridlines on a third surface again: not the
    panel (`line`), not the dome gradient (`grid`), but the bands.  Through
    2.1.3 all five sites took `line` and measured 1.02-1.15:1 on the night
    plate -- the dome's own defect, on three more panels, found by a review
    of the 2.2 dome fix.  They take `bandgrid` from 2.2.

    The floor is the sky charts' CHROME_FLOOR, not the graphics floor: these
    are the same class of mark as the dome's rings, and the same bar applies
    -- orient the eye, then get out of the way, but never disappear."""

    FLOOR = TestSkyChartContrast.CHROME_FLOOR

    # The three renderers that plot over the bands.  Every gridline in them
    # goes through _band_rule, which takes a RANK rather than a number, so
    # the weights a panel may draw are exactly BAND_RULE_OPACITY's values
    # and this audit measures all of them: a new panel cannot invent a
    # third weight without adding it here first.
    RENDERERS = ('ribbons_svg', 'sunpath_svg', 'daylength_svg')

    def test_every_plate_holds_the_chrome_floor(self):
        """Walks PALETTES rather than a hardcoded roster, so a third plate
        is covered the day it is added, and branches on what the plate
        DECLARES rather than on its name.

        A plate with no casing is measured against the bands themselves.  A
        plate with one is measured against the casing -- because that is
        what its rule actually sits on -- with the casing first composited
        over each band, since a casing over a pale band barely lightens it
        and the band still sets the answer.  The light ramp is why the
        casing exists: #3A5175 to #D7E6F5 is a wider luminance span than
        any single stroke color can straddle, the best candidate swept
        bottoming out at 1.72.

        Every band, not just the worst: which shades a panel paints depends
        on the day and the latitude."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            for rank, opacity in wxskyfield_sky.BAND_RULE_OPACITY.items():
                measured = []
                for band in pal['twilight'].values():
                    under = (_composite(pal['bandcase'], band,
                                        wxskyfield_sky.BAND_CASING_OPACITY)
                             if pal['bandcase'] else band)
                    measured.append(_measure(pal['bandgrid'], under, opacity))
                # Chrome on the night plate, a named exception there; the
                # paper plate's cased rules clear the mark bars outright.
                _hold_mark(plate, 'band gridlines %s' % rank, measured, self.FLOOR)

    def test_the_night_casing_is_its_darkest_band(self):
        """The night plate's casing exists for its LABELS, which read against
        the bands by color but not against the sun's arc drawn on them.  It
        is the night band's own color, so over that band it cannot be seen,
        and over the lighter bands it only deepens the ground under a mark."""
        night = wxskyfield_sky.PALETTES['night']
        assert night['bandcase'] == night['twilight']['night']

    def test_every_palette_carries_the_same_keys(self):
        """_band_rule reads `bandgrid` and `bandcase` by subscript, so a
        plate that omits one raises inside a guarded renderer and blanks
        three panels at report time.  Key parity is the cheap way to make
        that a test failure instead."""
        rosters = {plate: frozenset(pal)
                   for plate, pal in wxskyfield_sky.PALETTES.items()}
        reference = rosters['night']
        for plate, keys in rosters.items():
            assert keys == reference, (
                '%s differs: missing %s, extra %s'
                % (plate, sorted(reference - keys), sorted(keys - reference)))

    def test_no_band_gridline_takes_the_panel_color(self, almanac, page):
        """The 2.1.3 defect itself: these rules drawn in `line`, the
        panel-border color, on a surface that is not the panel.

        Checked in the RENDERED svg, not in the source -- the color is
        caught however it arrives, and a reflow of the call sites cannot
        make the guard pass by accident."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            for renderer in self.RENDERERS:
                svg = getattr(page, renderer)(almanac, palette=plate)
                assert pal['bandgrid'] in svg, (plate, renderer)
                # `line` is the PANEL-surface color and has no business on
                # a mark drawn over the bands -- as of 2.4 that is a class
                # these panels must not carry, rather than a hex they must
                # not bake.
                assert 'sky-stroke-line' not in svg, (plate, renderer)
                assert 'sky-fill-line' not in svg, (plate, renderer)

    def test_the_casing_is_wider_than_the_rule_it_carries(self):
        """A casing narrower than its rule would not be a casing.  Pins the
        geometry the ratios assume: one wide pale stroke, one thin rule
        centered on it, in that order -- painted after, the casing would
        bury what it is there to carry."""
        svg = wxskyfield_sky._band_rule(0, 0, 10, 0, 'primary')
        casing, rule = svg.split('/>')[0], svg.split('/>')[1]
        assert svg.count('<line') == 2
        assert 'stroke-width="%d"' % wxskyfield_sky.BAND_CASING_WIDTH in casing
        assert 'stroke-width="1"' in rule


class TestBandMarkContrast:
    """The DATA marks on the same twilight bands -- a body's above-horizon
    bar, its transit tick, the "now" line -- as opposed to the gridlines
    TestPanelGridContrast measures.

    This is the half 2.2 left behind, and it was the worse half: the
    gridlines were invisible on the NIGHT plate, where the bars were merely
    dim, but on the paper plate the bars themselves measured 1.01:1 (Mars
    on the astro band) and 1.04 (Mercury on night), with the
    transit ticks at 1.72 and the "now" line at 1.20.  (2.3's own account
    of this added "1.06 (Pluto)" -- a ratio for a body no panel draws; see
    test_a_plate_colors_exactly_the_drawn_bodies.)  Nothing caught it
    because `test_body_dots_hold_3` measures body colors against the DOME
    GRADIENT -- the surface those colors were chosen for -- and no audit
    knew the same colors were also being painted over a twilight ramp.

    The floor is the graphics floor, not the chrome floor these panels'
    gridlines get: a body's bar is the information the panel exists to
    carry, not chrome that may recede.

    Why this cannot be fixed with a color, and what carries it instead, is
    in _band_bar's docstring."""

    BARS = MARK_BARS

    @staticmethod
    def _under(pal, band, curve=False):
        """What a mark on this band actually sits on: the band itself where
        the plate declares no casing, else the casing composited over the
        band -- a near-solid casing over a pale band barely moves it, so
        the band still sets the answer at that end of the ramp."""
        if not pal['bandcase']:
            return band
        return _composite(pal['bandcase'], band,
                          wxskyfield_sky.BAND_CURVE_CASING_OPACITY if curve
                          else wxskyfield_sky.BAND_MARK_CASING_OPACITY)

    def test_every_body_mark_reads_on_every_band(self):
        """A body mark clears the floor by its own fill or by the layer its
        plate puts around it -- one of the two, on every band, on every
        plate.

        Read the guarantee precisely, because an earlier docstring here
        claimed the opposite of what the assertion does: `bandedge` does
        not depend on the body, so once a plate declares one this passes
        for ANY fill, including a fill identical to the band.  That is not
        a hole, it is the design -- the whole point of an outline is that a
        body color can then be chosen for identity alone -- but it means
        this test constrains the PLATE, not the palette's body colors.
        What would fail: a plate that stops declaring the layers, or
        declares ones that do not clear the floor.  `test_a_bare_identity
        _color_fails_this_audit` pins the other direction."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            for name, fill in pal['body'].items():
                for shade, band in pal['twilight'].items():
                    under = self._under(pal, band)
                    got = _measure(fill, under)
                    ok = _clears(got, self.BARS) or bool(
                        pal['bandedge']
                        and _clears(_measure(pal['bandedge'], under), self.BARS))
                    assert ok, (
                        '%s %s bar (fill %s, edge %s) is %.2f / Lc %.1f on the %s'
                        ' band' % (plate, name, fill, pal['bandedge'],
                                   got[0], got[1], shade))

    def test_the_line_marks_read_on_every_band(self):
        """The marks drawn as lines and curves over the bands -- transit
        ticks and the "now" line on the ribbons, the sun and moon arcs and
        the horizon line on the sun path, the rise/set/noon traces and the
        today line on the solar year -- carry no outline, since an outline
        on a 1.5px stroke is just a wider stroke.  Each must clear the
        floor against whatever its plate puts under it.

        `_under` composites the casing, so this measurement is only true of
        renderers that actually paint one: through 2.3's first cut it
        reported 10.03 for `ink` while `sunpath_svg` and `daylength_svg`
        drew the same color bare at 1.72.  That is why
        `test_every_band_crossing_panel_paints_its_casing` walks the
        renderers -- these ratios mean nothing without it."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            marks = [('ink', pal['ink']), ('brass', pal['brass'])]
            marks += [('arc %s' % b, wxskyfield_sky._ring_or_body(pal, b))
                      for b in ('sun', 'moon')]
            for name, color in marks:
                for shade, band in pal['twilight'].items():
                    got = _measure(color, self._under(pal, band, curve=True))
                    assert _clears(got, self.BARS), (
                        '%s %s mark %s is %.2f / Lc %.1f on the %s band'
                        % (plate, name, color, got[0], got[1], shade))

    def test_every_band_crossing_panel_paints_its_casing(self, almanac, page):
        """The ratios above assume a casing under every data mark that
        crosses the bands.  All three panels that plot on that surface must
        therefore paint one -- checked in the rendered SVG, per renderer,
        because 2.3 first shipped the mechanism in `ribbons_svg` alone and
        the audit could not tell.

        As of 2.4 the casing ELEMENT is written on both plates and the
        plate's value arrives as a class default, so both halves are
        checked: the mark carries the casing class, and the plate's own
        value (or `none`, which is how the night plate goes on paying
        nothing for a casing it does not need) is what that class resolves
        to in this SVG.  The element cannot be conditional any more --
        markup a plate declines to write is markup a reader who flips to
        the other plate can never get back."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            want = pal['bandcase'] or 'none'
            for renderer in ('ribbons_svg', 'sunpath_svg', 'daylength_svg'):
                svg = getattr(page, renderer)(almanac, palette=plate)
                assert ('sky-stroke-bandcase' in svg
                        or 'sky-fill-bandcase' in svg), (
                    '%s %s draws no casing mark' % (plate, renderer))
                for cls, prop in (('sky-stroke-bandcase', 'stroke'),
                                  ('sky-fill-bandcase', 'fill')):
                    if cls in svg:
                        assert ':where(.%s){%s:%s}' % (cls, prop, want) in svg, (
                            '%s %s: %s does not resolve to %s'
                            % (plate, renderer, cls, want))

    def test_the_ribbons_panel_draws_the_layers_the_audit_reads(
            self, almanac, page):
        """The ratios above are computed from palette keys and the casing
        opacity; they mean nothing unless the panel really paints those
        layers.  Checked in the rendered SVG, not in the source."""
        for plate, pal in wxskyfield_sky.PALETTES.items():
            svg = page.ribbons_svg(almanac, palette=plate)
            # The outline on the bar, and the casing beneath it: each is a
            # class on the mark and a default resolving to the plate's own
            # value -- `none` on the plate that declines the layer.
            assert 'sky-stroke-bandedge" stroke-width="1"' in svg, plate
            assert ':where(.sky-stroke-bandedge){stroke:%s}' % pal['bandedge'] in svg, plate
            assert ('class="sky-fill-bandcase" opacity="%s"'
                    % wxskyfield_sky.BAND_MARK_CASING_OPACITY) in svg, plate
            assert (':where(.sky-fill-bandcase){fill:%s}'
                    % (pal['bandcase'] or 'none')) in svg, plate

    def test_a_bare_identity_color_fails_this_audit(self):
        """Proof the audit trips, by measuring the code as it shipped
        through 2.2: no casing, no outline, the fill alone.  Without this,
        an audit that passes says nothing about whether it could ever
        fail."""
        pal = dict(wxskyfield_sky.PALETTES['light'],
                   bandcase=None, bandedge=None)
        worst = min(_contrast(f, b) for f in pal['body'].values()
                    for b in pal['twilight'].values())
        assert worst < 1.1, worst

    def test_the_casing_stands_outside_the_bar_it_carries(self):
        """Geometry the ratios assume: the casing is painted first and
        stands proud of the bar on every side.  A casing painted after, or
        inset, would bury the mark it exists to carry.  The <title> stays
        on the bar -- the casing must not become a second hover target."""
        svg = wxskyfield_sky._band_bar(
            100, 50, 200, 10, 4, 'sky-fill-body-mars',
            inner='<title>x</title>')
        casing, bar = svg.split('<rect ')[1], svg.split('<rect ')[2]
        pad = wxskyfield_sky.BAND_MARK_CASING_PAD
        num = wxskyfield_sky._num
        assert svg.count('<rect ') == 2
        assert 'x="%s" y="%s"' % (num(100 - pad), num(50 - pad)) in casing
        assert ('width="%s" height="%s"'
                % (num(200 + 2 * pad), num(10 + 2 * pad))) in casing
        assert '<title>' not in casing.split('/>')[0]
        assert '<title>x</title>' in bar


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
        assert page.countdown_html(almanac).count('class="count"') == 8

    def test_usage_errors_still_raise(self, almanac, page, monkeypatch):
        """The guard is for runtime surprises only: a template-author error
        (unknown palette) must keep failing loudly, not blank the panel."""
        self._break_bodies(monkeypatch)
        with pytest.raises(ValueError, match='light, night'):
            page.dome_svg(almanac, palette='sepia')


# Every public $sky_page method that takes an almanac, assigned to the rung
# of the tier ladder (wxskyfield_sky.TIER_*) it needs to draw on.  A
# partition, pinned by TestAlmanacTiers, so a panel added later cannot skip
# the tier question -- which is exactly how the first cut of this went
# wrong: it modeled two tiers, put PyEphem's eleven panels on the basic
# tier, and every one of them threw there.
ENGINE_PANELS = ('dome_svg', 'eot_svg', 'moon_apsides_html',
                 'pass_chart_html', 'satellites_html')
EXTRAS_PANELS = ('analemma_svg', 'chips_html', 'countdown_html',
                 'daylength_svg', 'lunation_svg', 'moon_svg', 'moonset_html',
                 'orrery_svg', 'ribbons_svg', 'sun_is_up', 'sunpath_svg',
                 'table_html')
BASIC_PANELS = ('header_sub', 'palette', 'theme')
# Of those, the ones that answer with markup assert_balanced can judge.
EXTRAS_MARKUP = tuple(n for n in EXTRAS_PANELS if n != 'sun_is_up')


@contextlib.contextmanager
def _tier(*almanac_types):
    """Serve $almanac from exactly these almanac types, with the warn-once
    state cleared going in and coming out."""
    with saved_almanacs():
        weewx.almanac.almanacs[:] = [t() for t in almanac_types]
        wxskyfield_sky._warned_tiers.clear()
        try:
            yield weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
        finally:
            wxskyfield_sky._warned_tiers.clear()


@pytest.fixture()
def extras_almanac():
    """The PyEphem tier: no Skyfield almanac, but an almanac with hasExtras.

    A legitimate configuration, and the one that found the original bug: the
    almanac service and the $sky_page search-list extension install and
    configure separately, so a skin can name $sky_page on a station that
    never enabled [Skyfield]."""
    pytest.importorskip('ephem')
    with _tier(weewx.almanac.PyEphemAlmanacType) as alm:
        assert alm.hasExtras, 'fixture did not build the extras tier'
        yield alm


@pytest.fixture()
def basic_almanac():
    """The tier WeeWX falls back to when PyEphem is not installed: its own
    weeutil almanac, which serves sunrise, sunset and the moon's phase and
    raises for everything else.

    Built explicitly rather than by deleting PyEphem, so this tier is
    exercised on every machine -- including the ones where PyEphem happens
    to be installed, which is every machine this suite has ever run on.
    That is why the tier went unmodeled: a fixture that only removes the
    Skyfield almanac can never see it."""
    with _tier(weewx.almanac.WeeutilAlmanacType) as alm:
        assert not alm.hasExtras, 'fixture did not build the basic tier'
        yield alm


class TestAlmanacTiers:
    """The page on the two tiers below the Skyfield almanac.

    can_draw() has promised since 2.3.4 that the engine-dependent panels
    come back empty below it, but nothing rendered a panel there to check
    it, and they only got there by throwing: the dome's meteor-shower guard
    caught the attribute read and not the iteration over it, so every dome
    on the page blanked with a TypeError while the report still exited 0.
    Every panel now states the tier it needs and declines below it."""

    def test_can_draw_is_false_below_the_engine(self, extras_almanac, page):
        assert page.can_draw() is False

    def test_can_draw_is_false_on_the_basic_tier(self, basic_almanac, page):
        assert page.can_draw() is False

    def test_engine_panels_decline_on_extras(self, extras_almanac, page):
        """Empty, exactly as can_draw() False advertises.

        dome_svg is here BY CHOICE, not because it cannot draw: on this
        tier its body would produce about 5 KB of working chart -- sun,
        moon and the seven planets placed correctly, no stars and no
        constellation figures.  It is declined so that can_draw(), a
        published contract since 2.3.4 that weewx-celestial 9.0 gates on,
        keeps meaning "these five come back empty"; see _panel_guard for
        the full argument.  Do not 'fix' this by moving dome_svg to
        EXTRAS_PANELS without changing that contract and telling the
        consumers -- the other four genuinely have nothing to draw here."""
        for name in ENGINE_PANELS:
            assert getattr(page, name)(extras_almanac) == '', name

    def test_the_dome_declines_rather_than_fails_on_extras(self, extras_almanac, page):
        """The other half of that claim, pinned so the reason stays true:
        the dome is empty on this tier because the gate declined, not
        because the body raised.  If it ever starts throwing here again,
        the docstring above stops being an accurate account of why the
        panel is blank."""
        assert wxskyfield_sky.SkyPage.dome_svg.__wrapped__(page, extras_almanac)

    def test_extras_panels_still_render_on_extras(self, extras_almanac, page):
        """That tier is degraded, not dead: the sun and moon plates, the
        orrery, the tables and the rest draw from PyEphem -- which is what
        footer_html's built-in-almanac credit has always said."""
        for name in EXTRAS_MARKUP:
            assert_balanced(getattr(page, name)(extras_almanac))

    def test_extras_panels_decline_on_basic(self, basic_almanac, page):
        """WeeWX's own almanac serves sunrise, sunset and moon phase and
        raises for everything else, so these decline rather than throw.
        Ten of them threw an AttributeError per page per report cycle
        before the basic tier was modeled at all -- the same noise the
        dome had been making, moved onto its neighbors."""
        for name in EXTRAS_MARKUP:
            assert getattr(page, name)(basic_almanac) == '', name
        assert page.sun_is_up(basic_almanac) is False

    def test_basic_panels_render_on_every_tier(self, basic_almanac, page):
        """The header, the footer and the theme need no almanac data, so
        they draw even here -- the page is never wholly blank."""
        assert_balanced(page.header_sub(basic_almanac))
        assert_balanced(page.footer_html())
        assert page.theme(basic_almanac) in ('dark', 'light')
        assert page.palette(basic_almanac) in ('night', 'light')

    @pytest.mark.parametrize('tier', ['extras', 'basic'])
    def test_nothing_is_reported_as_a_failure(self, tier, page, caplog, request):
        """The whole point, on BOTH tiers: not one ERROR.  A panel that
        cannot draw is a configuration, not a failure, and the log line an
        operator finally reads must mean something is broken."""
        alm = request.getfixturevalue('%s_almanac' % tier)
        with caplog.at_level(logging.ERROR, logger='wxskyfield_sky'):
            caplog.clear()
            for name in ENGINE_PANELS + EXTRAS_PANELS + BASIC_PANELS:
                getattr(page, name)(alm)
            page.footer_html()
        assert [r.getMessage() for r in caplog.records
                if r.levelno >= logging.ERROR] == []

    @pytest.mark.parametrize('tier,phrase', [
        ('extras', 'Skyfield almanac is not registered'),
        ('basic', 'own sunrise/sunset formulas')])
    def test_the_warning_is_said_once_per_process(self, tier, phrase, caplog, request):
        """Once, however many panels ask and however many pages a report run
        builds: sixteen domes across sixteen pages every archive interval is
        what made the old TypeErrors unreadable, and a WARNING repeated at
        that rate would be no better.  It names what went missing and what to
        do, because the footer's 'see the weewxd log' points the operator at
        exactly this line."""
        alm = request.getfixturevalue('%s_almanac' % tier)
        with caplog.at_level(logging.WARNING, logger='wxskyfield_sky'):
            caplog.clear()
            for _page_of_the_report in range(3):
                p = wxskyfield_sky.SkyPage()
                for name in ENGINE_PANELS + EXTRAS_PANELS:
                    getattr(p, name)(alm)
        warnings = [r.getMessage() for r in caplog.records if phrase in r.getMessage()]
        assert len(warnings) == 1, warnings
        assert 'data_services' in warnings[0]
        assert 'can_draw()' in warnings[0]

    def test_every_panel_is_assigned_a_tier(self):
        """No panel may skip the tier question.  Add a render method that
        takes an almanac and it must be listed above, on the rung it needs;
        the decorator must then carry the matching `needs=`."""
        classified = ENGINE_PANELS + EXTRAS_PANELS + BASIC_PANELS
        # A partition, not just a cover: a name on two rungs would make the
        # set comparison below pass while claiming two different tiers.
        assert len(set(classified)) == len(classified)
        found = set()
        for name, fn in vars(wxskyfield_sky.SkyPage).items():
            if name.startswith('_') or not callable(fn):
                continue
            params = inspect.signature(fn).parameters
            required = [p for p in list(params)[1:]
                        if params[p].default is inspect.Parameter.empty]
            if required == ['alm']:
                found.add(name)
        assert found == set(classified)

    @pytest.mark.parametrize('panels,floor', [
        (ENGINE_PANELS, wxskyfield_sky.TIER_ENGINE),
        (EXTRAS_PANELS, wxskyfield_sky.TIER_EXTRAS)])
    def test_panels_carry_their_floor(self, panels, floor, caplog):
        """The lists above are a claim about the decorator, not just names.

        Asserting the empty answer alone would not prove it -- an ungated
        panel throws its way to the same empty answer through the panel
        guard, which is precisely the bug.  The proof is that nothing is
        logged as a failure with no almanac to read at all, where the body
        would raise on its first tag."""
        for name in panels:
            with _tier():
                assert wxskyfield_sky._almanac_tier(None) < floor
                with caplog.at_level(logging.ERROR, logger='wxskyfield_sky'):
                    caplog.clear()
                    out = getattr(wxskyfield_sky.SkyPage(), name)(None)
                assert out == '' or out is False, name
                assert [r.getMessage() for r in caplog.records
                        if r.levelno >= logging.ERROR] == [], name

    def test_the_almanac_may_arrive_as_a_keyword(self, almanac, page):
        """A template is free to write alm=$almanac.  The gate reads the
        almanac to decide the tier, so reading only the positional would
        drop every gated panel to the basic tier on a station that can
        draw them -- silently, since declining looks the same as an empty
        answer."""
        assert page.can_draw() is True
        for name in ENGINE_PANELS[:1] + EXTRAS_PANELS[:1]:
            assert getattr(page, name)(alm=almanac) != '', name

    def test_a_raising_gate_still_costs_only_its_panel(self, page, monkeypatch, caplog):
        """The gate runs inside the panel guard, not ahead of it.  It has
        to import the almanac module to identify the registered type, and
        a gate that raised past the guard would take the whole page down
        for the report cycle -- the one failure the guard exists to
        contain."""
        def boom(alm):
            raise ImportError("No module named 'user.wxskyfield'")
        monkeypatch.setattr(wxskyfield_sky, '_almanac_tier', boom)
        with caplog.at_level(logging.ERROR, logger='wxskyfield_sky'):
            for name in ENGINE_PANELS:
                assert getattr(page, name)(None) == '', name
                assert 'sky_page.%s failed' % name in caplog.text


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
        assert re.search(r'^\s*HTML_ROOT = skyfield\s*$', installer, re.M)
        assert 'public_html' not in installer

    def test_template_guards_satellite_section(self):
        """A station with no [[Satellites]] must not render an empty
        section: the template wraps the panel in the has_satellites
        guard."""
        with open(os.path.join(self.SKIN_DIR, 'index.html.tmpl')) as f:
            source = f.read()
        assert '#if $sky_page.has_satellites()' in source
        assert 'satellites_html' in source

    def test_every_section_is_ordered_on_narrow_screens(self):
        """Below the breakpoint the two tracks dissolve and the sections
        reorder into one column by `order`.  A section missing from that
        list keeps the default order:0 and jumps to the TOP of the page,
        ahead of the dome -- which is how .sec-eot shipped in 2.1
        (issue #5).  So: every sec-* class the template uses must appear
        in the media query, and the numbers must be a gapless 1..N."""
        with open(os.path.join(self.SKIN_DIR, 'index.html.tmpl')) as f:
            used = set(re.findall(r'<section class="(sec-[a-z]+)"', f.read()))
        with open(os.path.join(self.SKIN_DIR, 'sky.css')) as f:
            css = f.read()
        query = css[css.index('@media (max-width: 1159px){'):]
        query = query[:query.index('\n}')]
        ordered = dict((m, int(n)) for m, n
                       in re.findall(r'\.(sec-[a-z]+)\{order:(\d+)\}', query))
        assert used, 'no sections found in the template'
        assert used == set(ordered), (
            'sections missing an order (they would sort to the top): %s'
            % sorted(used - set(ordered)))
        assert sorted(ordered.values()) == list(range(1, len(used) + 1))

    def test_tap_tooltip_script_wired(self):
        """sky.js turns the SVG <title> hover tooltips into tap-to-show
        chips -- without it every tooltip is dead on a touch screen (no
        hover on an iPad).  The template must load it, the CopyGenerator
        must copy it beside sky.css, and the chip's .skytip rule must
        exist in sky.css."""
        with open(os.path.join(self.SKIN_DIR, 'index.html.tmpl')) as f:
            assert '<script src="sky.js" defer></script>' in f.read()
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.SKIN_DIR, 'skin.conf'))
        assert conf['CopyGenerator']['copy_once'] == ['sky.css', 'sky.js']
        with open(os.path.join(self.SKIN_DIR, 'sky.css')) as f:
            assert '.skytip' in f.read()
        with open(os.path.join(self.SKIN_DIR, 'sky.js')) as f:
            js = f.read()
        assert "getElementsByTagName('title')" in js

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
        # The default satellites (and the documented hst example) carry
        # display names, so ISS never renders as "Iss".
        for sat, label in (('iss', 'ISS'), ('tiangong', 'Tiangong'), ('hst', 'HST')):
            assert conf['Almanac'][sat] == label
        # The default comets carry display names too -- Hale-Bopp keeps
        # its hyphen instead of the fallback's "Hale Bopp".
        for comet, label in (('halley', 'Halley'), ('hale_bopp', 'Hale-Bopp')):
            assert conf['Almanac'][comet] == label
        # English constellation names are the Latin ones -- the
        # [[Constellations]] section is the key reference for translators
        # and must mirror the engine's table exactly.
        assert dict(conf['Almanac']['Constellations']) == wxskyfield.CONSTELLATION_NAMES
        # The meteor-shower table mirrors the engine's, key for key --
        # the reference for translators, like the constellations.
        assert dict(conf['Almanac']['MeteorShowers']) == {
            s.key: s.name for s in wxskyfield.METEOR_SHOWERS}

    GERMAN_SKIN = {
        'Texts': {
            'today': 'heute',
            'now {time}': 'jetzt {time}',
            '%-I:%M %p': '%H:%M',
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
        assert '>now 12:00 PM</text>' in svg
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
            for sat in ('iss', 'tiangong', 'hst'):
                assert conf['Almanac'][sat], (name, sat)
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

    def test_it_conf_is_complete(self):
        """Italian likewise ships complete."""
        self.check_complete('it.conf')

    def test_no_conf_is_complete(self):
        """Norwegian likewise ships complete."""
        self.check_complete('no.conf')

    def test_sv_conf_is_complete(self):
        """Swedish likewise ships complete."""
        self.check_complete('sv.conf')

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
            sats = page.satellites_html(alm)
            footer = page.footer_html()
        for markup in (dome, table, ribbons, chips, sats):
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
        # The satellite rows: the ISS label from [Almanac], the pass line
        # translated, the compass ordinals from [[Ordinates]] (SE -> SO).
        assert '>ISS</div>' in sats
        assert 'erscheint SSW · Höchststand 19° SO · verschwindet ONO · 10\u00a0min' in sats
        assert 'kein sichtbarer Überflug in der kommenden Woche' in sats
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

    def test_shipped_italian_renders(self, sky):
        """The shipped it.conf, fed through the same channels the report
        engine uses, renders Italian panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'it.conf'),
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
        assert '>E</text>' in dome                       # Italian east cardinal
        assert '>Luna</text>' in dome
        assert '<th>Astro</th>' in table
        assert '</span>Nettuno</td>' in table            # not "Neptune"
        assert '<th>Levata</th>' in table and '<th>Tramonto</th>' in table
        assert '>adesso 12:00</text>' in ribbons
        # The chips' constellations carry the Italian names, through the
        # [[Constellations]] subsection: Mars stands in Leo on 2025-06-21.
        assert 'costellazione: Leone' in chips
        assert 'Calcolato con ' + LINKED_NAME in footer
        assert 'Nomi di stelle IAU-CSN' in footer
        # Italian moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])

    def test_shipped_norwegian_renders(self, sky):
        """The shipped no.conf, fed through the same channels the report
        engine uses, renders Norwegian panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'no.conf'),
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
        assert '>Ø</text>' in dome                       # Norwegian east cardinal
        assert '>Månen</text>' in dome
        assert '<th>Himmellegeme</th>' in table
        assert '</span>Merkur</td>' in table             # not "Mercury"
        assert '<th>Oppgang</th>' in table and '<th>Nedgang</th>' in table
        assert '>nå 12:00</text>' in ribbons
        # The chips' constellations carry the Norwegian names, through the
        # [[Constellations]] subsection: Mars stands in Leo on 2025-06-21.
        assert 'i stjernebildet Løven' in chips
        assert 'Beregnet med ' + LINKED_NAME in footer
        assert 'IAU-CSN-stjernenavn' in footer
        # Norwegian moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])

    def test_shipped_swedish_renders(self, sky):
        """The shipped sv.conf, fed through the same channels the report
        engine uses, renders Swedish panels."""
        configobj = pytest.importorskip('configobj')
        conf = configobj.ConfigObj(os.path.join(self.LANG_DIR, 'sv.conf'),
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
        assert '>O</text>' in dome                       # Swedish east cardinal (ost)
        assert '>Månen</text>' in dome
        assert '<th>Himlakropp</th>' in table
        assert '</span>Merkurius</td>' in table          # not "Mercury"
        assert '<th>Uppgång</th>' in table and '<th>Nedgång</th>' in table
        assert '>nu 12:00</text>' in ribbons
        # The chips' constellations carry the Swedish names, through the
        # [[Constellations]] subsection: Mars stands in Leo on 2025-06-21.
        assert 'i stjärnbilden Lejonet' in chips
        assert 'Beräknat med ' + LINKED_NAME in footer
        assert 'IAU-CSN-stjärnnamn' in footer
        # Swedish moon phase names flow through the same texts dict.
        assert str(alm.moon_phase) in list(conf['Almanac']['moon_phases'])


class TestWeeWX52NoTexts:
    """The Sky page reads body and constellation names off Almanac.texts,
    which WeeWX gained in 5.3.  On 5.2 -- still this extension's floor --
    the page must render whole, with those names in English/Latin.

    The stand-in almanac type below is the reproduction's essential half:
    on 5.2 the missing attribute does not raise, it falls through to
    PyEphem's "unrecognized attribute must be a heavenly body" branch and
    yields a truthy binder, defeating a `getattr(...) or {}` guard.
    """

    class _Binder:
        def __getattr__(self, attr):
            raise AttributeError(attr)

    class _TextsIsAHeavenlyBody:
        def get_almanac_data(self, almanac_obj, attr):
            return TestWeeWX52NoTexts._Binder()

    @contextlib.contextmanager
    def weewx_52_almanac(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            weewx.almanac.almanacs.append(self._TextsIsAHeavenlyBody())
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter())
            del alm.__dict__['texts']
            probe = getattr(alm, 'texts', None)
            assert probe is not None and not isinstance(probe, dict) and bool(probe)
            yield alm

    def test_panels_render(self, sky):
        """Every panel that reads a body or constellation name."""
        with self.weewx_52_almanac(sky) as alm:
            page = wxskyfield_sky.SkyPage({})
            dome = page.dome_svg(alm)
            table = page.table_html(alm)
            chips = page.chips_html(alm)
            ribbons = page.ribbons_svg(alm)
        assert 'Moon' in table and 'Jupiter' in table
        assert dome and chips and ribbons

    def test_label_helper(self, sky):
        with self.weewx_52_almanac(sky) as alm:
            assert wxskyfield_sky.SkyPage._label(alm, 'moon') == 'Moon'
            assert wxskyfield_sky.SkyPage._label(alm, 'proxima_centauri') == 'Proxima Centauri'
