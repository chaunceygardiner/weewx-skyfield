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
        sundial runs '-1m 56s' behind -- negative, below the zero line --
        where the Jun 18 grid sample would have mislabeled it '-1m 16s',
        40 seconds off."""
        svg = page.eot_svg(almanac)
        assert_balanced(svg)
        assert svg.count(' L') == 52          # the weekly curve
        assert '-1m 56s' in svg               # today's value, signed
        assert '-1m 16s' not in svg           # ...not the weekly sample's
        assert '+15m' in svg and '-15m' in svg

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

    def test_moon_apsides(self, almanac, page):
        html = page.moon_apsides_html(almanac)
        assert_balanced(html)
        # Jun 22 perigee, Jul 4 apogee (local time; both pinned in
        # test_almanac.py against Espenak's tables) -- and no supermoon:
        # June 2025's full moon (Jun 11) is nowhere near perigee.
        assert 'perigee' in html and 'apogee' in html
        assert 'Jun 22 21:44' in html and 'Jul 4 19:28' in html
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
        assert table.count('<tr>') == 14     # header + 9 bodies + 4 comets

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
            assert table.count('0h 00m') == 1
            assert re.search(r'14h \d\dm', table)   # the solstice sun, up ~14h46m

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
        assert '>today at %s<' % time.strftime('%H:%M', lt) in chip

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
        assert '>heute um %s<' % time.strftime('%H:%M', lt) in chip

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
        assert page._sat_when(almanac, TIME_TS + 3 * 3600, None) == 'in 3 h'
        assert page._sat_when(almanac, TIME_TS + 600, None) == 'in 10 min'
        assert page._sat_when(almanac, TIME_TS - 60, TIME_TS + 60) == 'overhead now'


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
        assert 'clip-path="url(#domec)"' in svg
        assert '<clipPath id="domec">' in svg
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
        assert 'Jun 22 03:11 · in 15 h' in html
        assert 'appears SSW · peaks 19° SE · disappears ENE · 10 min' in html
        # Tiangong crosses all week but never visibly: the honest dash.
        assert 'no visible pass in the coming week' in html

    def test_has_satellites(self, almanac, page):
        assert page.has_satellites() is True

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
        assert 'Sun Jun 22 · 03:11 → 03:21 · peak 19°' in html
        assert '<title>Iss pass — 03:11 → 03:21, peak 19°</title>' in html
        assert '>03:11</text>' in html and '>03:21</text>' in html
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
        ids must differ -- duplicate ids are invalid HTML."""
        dome = page.dome_svg(almanac)
        chart = page.pass_chart_html(almanac)
        assert 'id="skyg"' in dome and 'id="domec"' in dome
        assert 'id="skygp"' in chart and 'url(#domecp)' in chart
        assert 'id="skyg"' not in chart and 'id="domec"' not in chart

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
        assert '<title>Iss pass — 03:11 → 03:21, peak 19°</title>' in chart

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
                         r'<circle [^>]*fill="#0A0F22" stroke="#D3A94C"', svg)
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
                         r'<circle [^>]*fill="#D3A94C" stroke="#0A0F22"', svg)
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
    (yellow sun, silver moon, gray Mercury, pearly Venus, blue Earth);
    'classic-night'/'classic-light' preserve the pre-1.5 values."""

    RENDERERS = ('moon_svg', 'dome_svg', 'ribbons_svg', 'orrery_svg',
                 'analemma_svg', 'eot_svg', 'sunpath_svg', 'daylength_svg',
                 'lunation_svg', 'chips_html', 'table_html',
                 'countdown_html', 'header_sub')

    # The complete set of night-plate colors ever baked into markup.
    NIGHT_HEXES = ('#E9E4D4', '#8B93B8', '#D3A94C', '#2A3358', '#6E7DBA',
                   '#0A0F22', '#1E2745', '#DDD8C4', '#161F3D', '#1B2749',
                   '#2A3A63', '#0B1129', '#131B38', '#1A2547', '#233153',
                   '#2E3D5C', '#FFD75E', '#C9D0DA', '#C04F36', '#CE6750')

    def test_default_is_night(self, almanac, page):
        for name in self.RENDERERS:
            meth = getattr(page, name)
            assert meth(almanac) == meth(almanac, palette='night')

    def test_night_goldens(self, almanac, page):
        """Default output bakes the night-plate values — traditional body
        colors as of 1.5."""
        dome = page.dome_svg(almanac)
        for hexval in ('#161F3D', '#1B2749', '#2A3A63',     # dome gradient
                       '#6E7DBA', '#D3A94C', '#E9E4D4', '#0A0F22'):
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
        for hexval in ('#767E8A', '#97864A'):               # moon, venus bars
            assert hexval in ribbons
        assert '#BC7800' in page.orrery_svg(almanac, palette='light')
        assert 'box-shadow:inset 0 0 0 1.5px #BC7800' in \
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


def _luminance(hexval):
    """WCAG 2.x relative luminance of an #rrggbb string."""
    h = hexval.lstrip('#')
    out = 0.0
    for weight, i in ((0.2126, 0), (0.7152, 2), (0.0722, 4)):
        c = int(h[i:i + 2], 16) / 255.0
        out += weight * (c / 12.92 if c <= 0.03928
                         else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _composite(fg, bg, opacity):
    """The real color of a translucent mark: SVG opacity is alpha
    compositing, so what the eye gets is the blend.  Returned as a hex
    string so it can serve as the BACKGROUND of a further mark -- which is
    what a casing is (see _band_rule)."""
    f, b = fg.lstrip('#'), bg.lstrip('#')
    return '#' + ''.join(
        '%02X' % round(int(f[i:i + 2], 16) * opacity
                       + int(b[i:i + 2], 16) * (1 - opacity))
        for i in (0, 2, 4))


def _contrast(fg, bg, opacity=1.0):
    """WCAG contrast of fg over bg, fg first composited at `opacity` --
    SVG opacity is alpha compositing, so a translucent mark's real color
    is the blend, not the value in the palette."""
    fg = _composite(fg, bg, opacity)
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class TestSkyChartContrast:
    """Every mark on the two sky charts (the dome and the Next Visible Pass
    chart -- one _sky_chart, so one audit) must hold its floor against the
    dome gradient it is drawn on, on BOTH plates.

    This exists because the altitude rings and the meridian/horizon cross
    shipped through 2.1.3 at 1.07:1 -- they took `line`, the panel-border
    color, whose luminance is within a hair of the dome's own.  Nothing
    caught it: the rings were present, correct and invisible.  A golden-hex
    test cannot see that; only the ratio can.

    Floors are WCAG 2.x: 4.5 for text, 3.0 for graphics.  Two marks are
    deliberately exempt and carry their own floor -- see FIGURE_FLOOR."""

    SKIN_DIR = os.path.join(REPO_ROOT, 'skins', 'Skyfield')
    TEXT_FLOOR = 4.5
    MARK_FLOOR = 3.0
    # The rings and cross are chrome: they orient the eye and then get out
    # of the way, so they sit below the graphics floor on purpose.  The bar
    # is that they stay unambiguously visible -- an order of magnitude off
    # the 1.07 that made them disappear.
    CHROME_FLOOR = 1.9
    # The constellation FIGURES are the one mark left under its floor by
    # choice (night 1.87, light 1.47).  Mockups of the WCAG-compliant
    # version showed why: at the half scale the phone layout uses, lines
    # bright enough to pass turn the star field into a net over the sky
    # rather than figures within it.  Their LABELS were lifted instead --
    # a dozen marks, not five hundred segments.  This floor is "no worse
    # than 2.2 shipped", not a standard.
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
        for cls in ('skylab', 'starlab', 'conlab'):
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

    def test_text_marks_hold_45(self):
        """Star names, ring degrees and constellation names, composited at
        the opacities the chart actually renders them with -- read from the
        module, not restated here, so a change to either recomputes these
        ratios rather than making them fiction.

        SCOPE, deliberate: the dark-sky opacity.  While the sun is up the
        chart dims its star field to STAR_OPACITY_SUN_UP, which puts these
        same labels at 2.2-3.3 -- under the floor, on purpose, because
        those stars are not visible and their names are not there to be
        read.  Only .skylab, which never dims, holds 4.5 around the
        clock."""
        fills = self._chart_label_fills()
        dark = wxskyfield_sky.STAR_OPACITY_DARK
        for plate, idx in (('night', 0), ('light', 1)):
            pal = wxskyfield_sky.PALETTES[plate]
            for cls, opacity in (('skylab', 1.0),
                                 ('starlab', dark + wxskyfield_sky.STAR_LABEL_BUMP),
                                 ('conlab', dark)):
                fill = fills[cls][idx]
                for stop in self._dome_stops(pal):
                    got = _contrast(fill, stop, opacity)
                    assert got >= self.TEXT_FLOOR, (
                        '%s .%s %s on %s is %.2f, under %.1f'
                        % (plate, cls, fill, stop, got, self.TEXT_FLOOR))

    def test_body_dots_hold_3(self):
        """A body dot clears the graphics floor by its FILL or by its RING
        -- that is exactly what the palette's `ring` key is for, and the
        pale bodies on the paper plate (sun, venus) rely on it."""
        for plate in ('night', 'light'):
            pal = wxskyfield_sky.PALETTES[plate]
            for name, fill in pal['body'].items():
                ring = pal['ring'].get(name)
                for stop in self._dome_stops(pal):
                    best = _contrast(fill, stop)
                    if ring:
                        best = max(best, _contrast(ring, stop))
                    assert best >= self.MARK_FLOOR, (
                        '%s %s (fill %s, ring %s) is %.2f on %s, under %.1f'
                        % (plate, name, fill, ring, best, stop, self.MARK_FLOOR))

    def test_rings_and_cross_are_visible(self):
        """The 2.1.3 defect, pinned.  `grid` must never fall back to
        `line`: on both plates that value is ~1.1 against the dome."""
        for plate in ('night', 'light', 'classic-night', 'classic-light'):
            pal = wxskyfield_sky.PALETTES[plate]
            assert pal['grid'] != pal['line'], plate
            for opacity in (wxskyfield_sky.DOME_RING_OPACITY,
                            wxskyfield_sky.DOME_CROSS_OPACITY):
                for stop in self._dome_stops(pal):
                    got = _contrast(pal['grid'], stop, opacity)
                    assert got >= self.CHROME_FLOOR, (
                        '%s grid %s at %.2f is %.2f on %s, under %.1f'
                        % (plate, pal['grid'], opacity, got, stop,
                           self.CHROME_FLOOR))

    def test_constellation_figures_stay_recessive(self):
        """Two-sided on purpose: the figures must stay visible, and must
        NOT be lifted to the graphics floor without revisiting the half
        scale render that argued against it."""
        for plate in ('night', 'light'):
            pal = wxskyfield_sky.PALETTES[plate]
            for stop in self._dome_stops(pal):
                got = _contrast(pal['conline'],
                                stop, wxskyfield_sky.CONLINE_OPACITY_DARK)
                assert got >= self.FIGURE_FLOOR, (
                    '%s conline %s is %.2f on %s, under %.1f'
                    % (plate, pal['conline'], got, stop, self.FIGURE_FLOOR))

    def test_the_dome_draws_the_opacities_the_audit_reads(self, almanac, page):
        """The audit's ratios are composites at the module's opacities, so
        they mean nothing unless the dome really renders at them.  Checked
        in the rendered svg: the constant and the chart cannot drift apart
        without this failing, and no source grep is involved."""
        dome = page.dome_svg(almanac)
        assert ('stroke-dasharray="3 5" opacity="%s"'
                % wxskyfield_sky.DOME_RING_OPACITY) in dome
        assert dome.count('stroke-width="1" opacity="%s"'
                          % wxskyfield_sky.DOME_CROSS_OPACITY) == 2
        # Whichever star opacity the fixture instant calls for -- it is
        # local noon, so the dimmed one -- with the labels a shade above
        # it.  Derived rather than written down: the pair that matters is
        # (what the module says, what the chart drew), not the clock.
        star_op = (wxskyfield_sky.STAR_OPACITY_SUN_UP if page.sun_is_up(almanac)
                   else wxskyfield_sky.STAR_OPACITY_DARK)
        for cls, expected in (
                ('starlab', star_op + wxskyfield_sky.STAR_LABEL_BUMP),
                ('conlab', star_op)):
            drawn = [float(o) for o in re.findall(
                r'<text[^>]*class="%s"[^>]*opacity="([\d.]+)"' % cls, dome)]
            assert drawn, cls
            assert all(o == pytest.approx(expected) for o in drawn), (cls, drawn)


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
        """Walks PALETTES rather than a hardcoded roster, so a fifth plate
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
                for shade, band in pal['twilight'].items():
                    under = (_composite(pal['bandcase'], band,
                                        wxskyfield_sky.BAND_CASING_OPACITY)
                             if pal['bandcase'] else band)
                    got = _contrast(pal['bandgrid'], under, opacity)
                    assert got >= self.FLOOR, (
                        '%s %s rule on the %s band is %.2f, under %.1f'
                        % (plate, rank, shade, got, self.FLOOR))

    def test_the_night_plates_draw_no_casing(self):
        """The casing is the light plates' answer to a ramp they cannot
        straddle.  The night plates read against every one of their own
        bands with a single stroke, so they must not pay for a second
        element per gridline."""
        for plate in ('night', 'classic-night'):
            assert wxskyfield_sky.PALETTES[plate]['bandcase'] is None, plate

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
                assert 'stroke="%s"' % pal['line'] not in svg, (plate, renderer)

    def test_the_casing_is_wider_than_the_rule_it_carries(self):
        """A casing narrower than its rule would not be a casing.  Pins the
        geometry the ratios assume: one wide pale stroke, one thin rule
        centred on it, in that order -- painted after, the casing would
        bury what it is there to carry."""
        svg = wxskyfield_sky._band_rule(
            wxskyfield_sky.PALETTES['light'], 0, 0, 10, 0, 'primary')
        casing, rule = svg.split('/>')[0], svg.split('/>')[1]
        assert svg.count('<line') == 2
        assert 'stroke-width="%d"' % wxskyfield_sky.BAND_CASING_WIDTH in casing
        assert 'stroke-width="1"' in rule


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
        assert 'erscheint SSW · Höchststand 19° SO · verschwindet ONO · 10 min' in sats
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
