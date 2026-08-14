"""
test_almanac.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

Tests for the Skyfield report almanac (SkyfieldAlmanacType/SkyfieldAlmanacBinder).

Run with the WeeWX virtual environment's Python, from the root of this repo:
    /home/weewx/weewx-venv/bin/python -m pytest tests

The expected values below were computed with Skyfield 1.54 and JPL's de421
ephemeris for Palo Alto, CA on 2025-06-21 (summer solstice weekend), and were
sanity checked against PyEphem and published almanac data.  They serve as
regression values.
"""

import contextlib
import json
import logging
import os
import re
import shutil
import sys
import time

from typing import List

import pytest

import skyfield.api

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TEST_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, 'bin', 'user'))

# The expected values (and WeeWX's notion of "today's" rise/set) depend on
# the local timezone, so pin it.
os.environ['TZ'] = 'America/Los_Angeles'
time.tzset()

import weeutil.Moon
import weeutil.weeutil
import weewx
import weewx.almanac
import weewx.units

import wxskyfield

LATITUDE    = 37.4419
LONGITUDE   = -122.143
ALTITUDE_M  = 9.0
TIME_TS     = 1750532400      # 2025-06-21 12:00:00 PDT

# Tolerances
TIME_TOL    = 5.0             # seconds, for event regression values
ANGLE_TOL   = 0.05            # degrees
EPHEM_TOL   = 120.0           # seconds, when comparing against PyEphem

# The stars come from wxskyfield_stars.dat.gz, the complete Hipparcos
# catalog that ships with the extension.
CATALOG_PRESENT = os.path.exists(os.path.join(REPO_ROOT, 'bin', 'user', wxskyfield.STAR_FILE))
needs_catalog = pytest.mark.skipif(not CATALOG_PRESENT, reason='%s not present' % wxskyfield.STAR_FILE)

# Satellite element fixtures: real archived TLEs (CelesTrak's stations
# group as captured 2025-06-21, epochs 0.26/0.88 days before TIME_TS) for
# the ISS and Tiangong, committed as test data, plus a fabricated
# geostationary satellite parked over the far side of the Earth --
# deterministic never-rises.  SGP4 is pure math: canned TLE + TIME_TS +
# Palo Alto = deterministic, so pass times pin like sun -17.6239.
SAT_DATA_DIR = os.path.join(TEST_DIR, 'data')
ISS_NORAD, TIANGONG_NORAD, GEOSAT_NORAD = 25544, 48274, 90000
SATELLITES = {'iss': ISS_NORAD, 'tiangong': TIANGONG_NORAD}
ISS_EPOCH_TS = 1750510380.388


def read_tle(norad: int) -> str:
    with open(os.path.join(SAT_DATA_DIR, wxskyfield.SAT_FILE_FORMAT % norad)) as f:
        return f.read()


def raw(value_helper, unit):
    """A tag's value in the given unit, or None -- .raw honors any report
    unit-group override, so the unit is always pinned explicitly."""
    try:
        return value_helper.convert(unit).raw
    except Exception:
        return None


@pytest.fixture(scope='session')
def sky():
    s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                       load_stars=CATALOG_PRESENT,
                       satellites=dict(SATELLITES), sat_dir=SAT_DATA_DIR,
                       comets=dict(COMETS), comet_dir=SAT_DATA_DIR)
    assert s.is_valid()
    return s


@contextlib.contextmanager
def saved_almanacs():
    """Save and restore the global weewx.almanac.almanacs list."""
    saved = list(weewx.almanac.almanacs)
    try:
        yield
    finally:
        weewx.almanac.almanacs[:] = saved


def pyephem_observer(start_of_day: bool = False):
    """A PyEphem observer at the test station, at TIME_TS (or the local
    midnight starting its day).  Skips the calling test when PyEphem is
    not installed."""
    ephem = pytest.importorskip('ephem')
    observer = ephem.Observer()
    observer.lat = str(LATITUDE)
    observer.lon = str(LONGITUDE)
    observer.elevation = ALTITUDE_M
    date_ts = weeutil.weeutil.startOfDay(TIME_TS) if start_of_day else TIME_TS
    observer.date = weewx.almanac.timestamp_to_djd(date_ts)
    return observer


@pytest.fixture()
def almanac(sky):
    with saved_almanacs():
        assert wxskyfield.register_almanac(sky)
        yield weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                    formatter=weewx.units.get_default_formatter())


@pytest.fixture()
def skyfield_only_almanac(sky):
    """An Almanac as it would behave on a system without PyEphem: the
    Skyfield almanac is the only registered almanac, and the PyEphem
    fallback sees no ephem module."""
    saved_ephem = getattr(weewx.almanac, 'ephem', None)
    with saved_almanacs():
        assert wxskyfield.register_almanac(sky)
        weewx.almanac.almanacs[:] = [a for a in weewx.almanac.almanacs
                                     if type(a).__name__ == 'SkyfieldAlmanacType']
        if saved_ephem is not None:
            del weewx.almanac.ephem
        try:
            yield weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
        finally:
            if saved_ephem is not None:
                weewx.almanac.ephem = saved_ephem


class StubEngine:
    """Just enough of a WeeWX engine for the WxSkyfield service to start."""
    def __init__(self):
        self.bound = []

    def bind(self, event, callback):
        self.bound.append(event)


def make_config(**skyfield_options):
    config = {
        'WEEWX_ROOT': REPO_ROOT,
        'USER_ROOT': 'bin/user',
        'Skyfield': {'enable': 'true'},
    }
    config['Skyfield'].update(skyfield_options)
    return config


class TestService:
    def test_service_registers_almanac(self):
        with saved_almanacs():
            engine = StubEngine()
            wxskyfield.WxSkyfield(engine, make_config())
            assert type(weewx.almanac.almanacs[0]).__name__ == 'SkyfieldAlmanacType'
            # A pure almanac extension binds no loop/archive events.
            assert engine.bound == []

    def test_service_disabled(self):
        with saved_almanacs():
            engine = StubEngine()
            wxskyfield.WxSkyfield(engine, make_config(enable='false'))
            assert engine.bound == []
            assert all(type(a).__name__ != 'SkyfieldAlmanacType' for a in weewx.almanac.almanacs)

    @needs_catalog
    def test_service_stars_default_on(self):
        with saved_almanacs():
            engine = StubEngine()
            service = wxskyfield.WxSkyfield(engine, make_config())
            assert len(service.sky.stars) == len(set(wxskyfield.NAMED_STARS))

    @needs_catalog
    def test_removed_stars_option_warns_and_stars_still_load(self, caplog):
        """The stars option was removed in 2.0 (the full catalog always
        ships); an old config's stars = false must be called out with the
        removal hint -- and must not disable anything."""
        with saved_almanacs(), caplog.at_level(logging.WARNING, logger=wxskyfield.log.name):
            engine = StubEngine()
            service = wxskyfield.WxSkyfield(engine, make_config(stars='false'))
        assert 'unrecognized [Skyfield] option: stars' in caplog.text
        assert 'removed in 2.0' in caplog.text
        assert len(service.sky.stars) == len(set(wxskyfield.NAMED_STARS))

    def test_service_missing_enable_defaults_to_enabled(self):
        """A missing 'enable' key means enabled, per the README -- and must
        never crash the service constructor (and with it, engine startup)."""
        with saved_almanacs():
            config = make_config(stars='false')
            del config['Skyfield']['enable']
            wxskyfield.WxSkyfield(StubEngine(), config)
            assert type(weewx.almanac.almanacs[0]).__name__ == 'SkyfieldAlmanacType'

    def test_service_missing_section_defaults_to_enabled(self):
        """Same for a missing [Skyfield] section altogether."""
        with saved_almanacs():
            config = make_config()
            del config['Skyfield']
            wxskyfield.WxSkyfield(StubEngine(), config)
            assert type(weewx.almanac.almanacs[0]).__name__ == 'SkyfieldAlmanacType'

    def test_unrecognized_option_warns(self, caplog):
        """A key [Skyfield] does not read must be called out, not silently
        ignored -- a report option (star_mag_limit) landing there looks
        plausible next to stars = true and otherwise just does nothing."""
        with saved_almanacs(), caplog.at_level(logging.WARNING, logger=wxskyfield.log.name):
            wxskyfield.WxSkyfield(StubEngine(), make_config(star_mag_limit='5.0'))
        assert 'unrecognized [Skyfield] option: star_mag_limit' in caplog.text
        assert '[StdReport] [[SkyfieldReport]]' in caplog.text

    def test_unrecognized_option_warns_without_hint(self, caplog):
        with saved_almanacs(), caplog.at_level(logging.WARNING, logger=wxskyfield.log.name):
            wxskyfield.WxSkyfield(StubEngine(), make_config(star='true'))
        assert 'unrecognized [Skyfield] option: star' in caplog.text
        assert '[StdReport]' not in caplog.text

    def test_recognized_options_do_not_warn(self, caplog):
        with saved_almanacs(), caplog.at_level(logging.WARNING, logger=wxskyfield.log.name):
            wxskyfield.WxSkyfield(StubEngine(), make_config(satellite_downloads='true'))
        assert 'unrecognized' not in caplog.text

    def test_old_skyfield_declines(self, monkeypatch):
        """Skyfield earlier than 1.47 lacks find_risings/find_settings; the
        engine must decline up front (leaving the built-in almanac in
        place), not fail on every rise/set tag at report time."""
        monkeypatch.setattr(wxskyfield.skyfield, 'VERSION', (1, 45))
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False)
        assert not s.is_valid()


class TestTerminatePropagation:
    """weewxd stops by raising Terminate from its SIGTERM signal handler --
    inside whatever the main thread is executing at that instant.  This
    extension's main-thread exposure is Sky.__init__, which the service
    runs at engine startup; its broad exception handlers must hand
    Terminate back (a shutdown request, not a failure -- the one exemption
    from the never-raise contract), or weewx cannot shut down.  Almanac
    tags run on the report thread, which never receives signals."""

    class Terminate(Exception):
        """Stands in for weewxd's Terminate, which is recognized by name
        (weewxd runs as __main__, so the real class cannot be imported)."""

    def test_sky_init_lets_terminate_through(self, monkeypatch):
        def raise_terminate(*args, **kwargs):
            raise self.Terminate
        monkeypatch.setattr(wxskyfield.skyfield.api.load, 'timescale', raise_terminate)
        with pytest.raises(self.Terminate):
            wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False)

    def test_ordinary_exception_still_swallowed(self, monkeypatch):
        """The reraise guard must not change error handling for real
        failures: Sky.__init__ still logs and leaves valid=False."""
        def raise_valueerror(*args, **kwargs):
            raise ValueError('boom')
        monkeypatch.setattr(wxskyfield.skyfield.api.load, 'timescale', raise_valueerror)
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False)
        assert not s.is_valid()


class TestRegistration:
    def test_skyfield_registered_first(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            assert type(weewx.almanac.almanacs[0]).__name__ == 'SkyfieldAlmanacType'
            # Registering again must not create a duplicate.
            assert wxskyfield.register_almanac(sky)
            names = [type(a).__name__ for a in weewx.almanac.almanacs]
            assert names.count('SkyfieldAlmanacType') == 1
            assert names[0] == 'SkyfieldAlmanacType'

    def test_has_extras(self, almanac):
        assert almanac.hasExtras


class TestSunAndMoonEvents:
    def test_sunrise_sunset(self, almanac):
        assert almanac.sunrise.raw == pytest.approx(1750510081.9, abs=TIME_TOL)
        assert almanac.sunset.raw == pytest.approx(1750563177.8, abs=TIME_TOL)
        assert almanac.sun.rise.raw == almanac.sunrise.raw
        assert almanac.sun.set.raw == almanac.sunset.raw

    def test_sun_transit(self, almanac):
        assert almanac.sun.transit.raw == pytest.approx(1750536630.2, abs=TIME_TOL)

    def test_moon_rise_transit_set(self, almanac):
        assert almanac.moon.rise.raw == pytest.approx(1750497776.3, abs=TIME_TOL)
        assert almanac.moon.transit.raw == pytest.approx(1750523341.1, abs=TIME_TOL)
        assert almanac.moon.set.raw == pytest.approx(1750549654.3, abs=TIME_TOL)

    def test_twilight_horizons(self, almanac):
        civil = almanac(horizon=-6).sun(use_center=1).rise.raw
        nautical = almanac(horizon=-12).sun(use_center=1).rise.raw
        astronomical = almanac(horizon=-18).sun(use_center=1).rise.raw
        assert civil == pytest.approx(1750508213.5, abs=TIME_TOL)
        assert nautical == pytest.approx(1750505876.7, abs=TIME_TOL)
        assert astronomical == pytest.approx(1750503235.7, abs=TIME_TOL)
        # Dawn stages must be in order and before sunrise.
        assert astronomical < nautical < civil < almanac.sunrise.raw
        # The horizon override must not stick to the almanac.
        assert almanac.sun.rise.raw == pytest.approx(1750510081.9, abs=TIME_TOL)

    def test_next_and_previous_events(self, almanac):
        assert almanac.next_full_moon.raw == pytest.approx(1752179807.6, abs=TIME_TOL)
        assert almanac.next_new_moon.raw == pytest.approx(1750847497.1, abs=TIME_TOL)
        assert almanac.next_equinox.raw == pytest.approx(1758565160.5, abs=TIME_TOL)
        assert almanac.next_solstice.raw == pytest.approx(1766329385.1, abs=TIME_TOL)
        assert almanac.previous_solstice.raw == pytest.approx(1750473735.7, abs=TIME_TOL)
        # Sanity: previous < now < next.
        assert almanac.previous_full_moon.raw < TIME_TS < almanac.next_full_moon.raw
        assert almanac.previous_equinox.raw < TIME_TS < almanac.next_equinox.raw
        assert almanac.next_vernal_equinox.raw > almanac.next_autumnal_equinox.raw
        assert almanac.previous_winter_solstice.raw < TIME_TS

    def test_next_previous_risings(self, almanac):
        assert almanac.sun.previous_rising.raw == pytest.approx(1750510081.9, abs=TIME_TOL)
        assert almanac.sun.next_rising.raw == pytest.approx(1750596496.5, abs=TIME_TOL)
        assert almanac.sun.previous_rising.raw < TIME_TS < almanac.sun.next_rising.raw
        assert almanac.sun.previous_setting.raw < TIME_TS < almanac.sun.next_setting.raw

    def test_transits(self, almanac):
        assert almanac.sun.next_antitransit.raw == pytest.approx(1750579836.8, abs=TIME_TOL)
        assert almanac.sun.previous_transit.raw < TIME_TS < almanac.sun.next_transit.raw
        assert almanac.sun.previous_antitransit.raw < TIME_TS < almanac.sun.next_antitransit.raw


class TestPositions:
    def test_sun_position(self, almanac):
        assert almanac.sun.az == pytest.approx(127.847, abs=ANGLE_TOL)
        assert almanac.sun.alt == pytest.approx(69.409, abs=ANGLE_TOL)
        assert almanac.sun.ra == pytest.approx(90.707, abs=ANGLE_TOL)
        assert almanac.sun.dec == pytest.approx(23.436, abs=ANGLE_TOL)

    def test_moon_position(self, almanac):
        assert almanac.moon.az == pytest.approx(249.300, abs=ANGLE_TOL)
        assert almanac.moon.alt == pytest.approx(52.462, abs=ANGLE_TOL)

    def test_value_helper_angles(self, almanac):
        # These are ValueHelpers; .raw applies the default converter, which
        # renders angles in degrees.
        assert almanac.sun.azimuth.raw == pytest.approx(almanac.sun.az, abs=ANGLE_TOL)
        assert almanac.sun.altitude.raw == pytest.approx(almanac.sun.alt, abs=ANGLE_TOL)
        assert almanac.sun.topo_dec.raw == pytest.approx(almanac.sun.dec, abs=ANGLE_TOL)
        assert almanac.sun.topo_ra.raw == pytest.approx(almanac.sun.ra, abs=ANGLE_TOL)
        assert almanac.sun.hour_angle.raw == pytest.approx(almanac.sun.ha, abs=ANGLE_TOL)
        # And they can be formatted (as done in the Seasons skin).
        assert str(almanac.sun.azimuth.format("%.1f"))
        assert str(almanac.moon.altitude.format("%.1f"))
        assert str(almanac.sun.hour_angle.format("%.1f"))

    def test_value_helper_angles_honor_unit_overrides(self, almanac):
        """The ValueHelper family participates in the unit system: a report
        converter that prefers radians for group_angle gets radians from
        .raw -- hour_angle like altitude (the plain-float ha stays decimal
        degrees regardless).  The almanac fixture keeps the Skyfield
        almanac registered while this one is built with its own converter."""
        import math
        radians_converter = weewx.units.Converter({'group_angle': 'radian'})
        alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                    formatter=weewx.units.get_default_formatter(),
                                    converter=radians_converter)
        assert alm.sun.hour_angle.raw == pytest.approx(math.radians(alm.sun.ha), abs=1e-6)
        assert alm.sun.altitude.raw == pytest.approx(math.radians(alm.sun.alt), abs=1e-6)

    def test_compute_angle_unknown_key_raises(self, almanac):
        """A key not wired into compute_angle must fail loudly, not
        silently answer with the elongation."""
        with pytest.raises(ValueError):
            almanac.sun.compute_angle('bogus')

    def test_sidereal(self, almanac):
        assert almanac.sidereal_time == pytest.approx(73.083, abs=ANGLE_TOL)
        assert 0.0 <= almanac.sidereal_time < 360.0
        assert almanac.sidereal_angle.raw == pytest.approx(almanac.sidereal_time, abs=ANGLE_TOL)

    def test_solar_time(self, almanac):
        """Local apparent solar time as an angle, mirroring the sidereal
        pair: 180° is solar noon.  At 12:00 PDT on the solstice the sun
        is still 17.6° (an hour and change) east of the local meridian."""
        assert almanac.solar_time == pytest.approx(162.376, abs=ANGLE_TOL)
        assert 0.0 <= almanac.solar_time < 360.0
        assert almanac.solar_angle.raw == pytest.approx(almanac.solar_time, abs=ANGLE_TOL)

    def test_solar_noon_is_180_degrees(self, almanac):
        """Time-traveled to the sun's transit, apparent solar time reads
        180° -- solar noon, by definition."""
        noon = almanac(almanac_time=almanac.sun.transit.raw)
        assert noon.solar_time == pytest.approx(180.0, abs=0.02)

    def test_equation_of_time(self, almanac):
        """Apparent minus mean solar time -- the USNO sign convention --
        as a signed group_deltatime ValueHelper.  Values agree with Meeus
        ch. 28 within a few seconds; the yearly extremes land on the
        published +16m26s (early November) and -14m14s (mid-February)."""
        # Solstice 2025: the sundial runs about 1m55s behind the clock.
        assert almanac.equation_of_time.raw == pytest.approx(-115.4, abs=3.0)
        nov = almanac(almanac_time=1762200000)      # 2025-11-03 12:00 PST
        assert nov.equation_of_time.raw == pytest.approx(16.43 * 60.0, abs=15.0)
        feb = almanac(almanac_time=1739304000)      # 2025-02-11 12:00 PST
        assert feb.equation_of_time.raw == pytest.approx(-14.19 * 60.0, abs=15.0)

    def test_distances(self, almanac):
        assert almanac.sun.earth_distance == pytest.approx(1.01625, abs=0.001)
        assert almanac.mars.earth_distance == pytest.approx(1.85875, abs=0.001)
        assert almanac.mars.sun_distance == pytest.approx(1.64, abs=0.05)

    def test_distance_value_helpers(self, almanac):
        """distance/distance_from_sun are ValueHelper twins of the raw
        earth_distance/sun_distance floats: the same AU value, rendered
        with the AU label by default in every unit system, converting on
        ask.  distance is from Earth, mirroring the satellite surface,
        where .distance already means distance from the observer."""
        assert str(almanac.sun.distance) == '1.0163 AU'
        assert str(almanac.mars.distance) == '1.8588 AU'
        assert str(almanac.mars.distance_from_sun) == '1.6448 AU'
        assert almanac.sun.distance.raw == pytest.approx(almanac.sun.earth_distance, abs=1e-12)
        assert almanac.mars.distance.raw == pytest.approx(almanac.mars.earth_distance, abs=1e-12)
        assert almanac.mars.distance_from_sun.raw == pytest.approx(almanac.mars.sun_distance, abs=1e-12)
        # Conversions answer on ask, through WeeWX's unit machinery.
        assert almanac.moon.distance.km.raw == pytest.approx(
            almanac.moon.earth_distance * wxskyfield.KM_PER_AU, abs=1e-3)
        assert almanac.mars.distance.mile.raw == pytest.approx(
            almanac.mars.earth_distance * wxskyfield.KM_PER_AU / 1.609344, abs=1.0)
        # The sun is zero AU from itself -- served honestly, not an error.
        assert almanac.sun.distance_from_sun.raw == pytest.approx(0.0, abs=1e-9)

    def test_illumination_value_helper(self, almanac):
        """illumination is the ValueHelper twin of the raw phase percent
        (and of the moon's moon_fullness alias), in group_percent.  mag
        deliberately has no twin: a magnitude is unitless."""
        assert almanac.moon.illumination.raw == pytest.approx(almanac.moon.phase, abs=1e-12)
        assert almanac.moon.illumination.raw == pytest.approx(almanac.moon.moon_fullness, abs=1e-12)
        assert almanac.venus.illumination.raw == pytest.approx(almanac.venus.phase, abs=1e-12)
        assert almanac.sun.illumination.raw == 100.0
        vt = almanac.moon.illumination.value_t
        assert (vt.unit, vt.group) == ('percent', 'group_percent')
        # A star has no illumination, like phase.
        with pytest.raises(AttributeError):
            almanac.rigel.illumination

    def test_au_unit_registration(self):
        """register_units runs at module import -- before any service, so
        weewx-loopdata's field parsing can never beat it -- and wires the
        AU group into every unit system."""
        for group_dict in (weewx.units.USUnits, weewx.units.MetricUnits,
                           weewx.units.MetricWXUnits):
            assert group_dict['group_distance_astronomical'] == 'astronomical_unit'
        assert weewx.units.default_unit_label_dict['astronomical_unit'] == ' AU'
        assert weewx.units.default_unit_format_dict['astronomical_unit'] == '%.4f'
        assert weewx.units.conversionDict['astronomical_unit']['km'](1.0) == pytest.approx(
            wxskyfield.KM_PER_AU)
        assert weewx.units.conversionDict['km']['astronomical_unit'](wxskyfield.KM_PER_AU) == pytest.approx(1.0)
        assert weewx.units.conversionDict['astronomical_unit']['mile'](1.0) == pytest.approx(
            wxskyfield.KM_PER_AU / 1.609344)


class TestMoonPhase:
    def test_moon_phase(self, almanac):
        assert almanac.moon_phase == weeutil.Moon.moon_phases[7]  # waning crescent
        assert almanac.moon_index == 7
        assert isinstance(almanac.moon_index, int)

    def test_moon_fullness(self, almanac):
        assert almanac.moon_fullness == 18
        assert isinstance(almanac.moon_fullness, int)
        # The more precise binder value:
        assert almanac.moon.moon_fullness == pytest.approx(18.18, abs=0.1)


class TestMoonApsides:
    """Moon perigee/apogee times (new in 2.1) -- the supermoon machinery.
    The extremum is searched on the GEOMETRIC center-to-center distance,
    matching the published apsis tables; regression values verified
    against Espenak's 2025 geometric tables (perigee 2025-06-23 04:44
    UTC, apogee 2025-07-05 02:29 UTC, ...), all matched within a
    minute."""

    def test_apsis_times(self, almanac):
        assert almanac.moon.next_perigee.raw == pytest.approx(1750653855, abs=60)
        assert almanac.moon.previous_perigee.raw == pytest.approx(1748223227, abs=60)
        assert almanac.moon.next_apogee.raw == pytest.approx(1751682527, abs=60)
        assert almanac.moon.previous_apogee.raw == pytest.approx(1749293028, abs=60)

    def test_apsis_ordering(self, almanac):
        assert almanac.moon.previous_perigee.raw < TIME_TS < almanac.moon.next_perigee.raw
        assert almanac.moon.previous_apogee.raw < TIME_TS < almanac.moon.next_apogee.raw
        # Consecutive perigees are one anomalistic month (27.55 d) apart.
        assert (almanac.moon.next_perigee.raw - almanac.moon.previous_perigee.raw
                == pytest.approx(27.55 * 86400, abs=0.6 * 86400))

    def test_next_supermoon(self, almanac):
        """The engine's single copy of the supermoon rule: the next full
        moon within a day of perigee.  From the June 2025 fixture the
        June through October full moons all miss; the answer is the
        Nov 5 full moon, 9.1 hours from perigee -- and it is the same
        instant next_full_moon serves when time-traveled there."""
        sm = almanac.next_supermoon.raw
        assert sm == pytest.approx(1762348758, abs=60)
        assert sm == pytest.approx(
            almanac(almanac_time=sm - 86400).next_full_moon.raw, abs=60)
        p = almanac(almanac_time=sm - 2 * 86400).moon.next_perigee.raw
        assert abs(p - sm) <= wxskyfield.SUPERMOON_PERIGEE_GAP_S

    def test_perigee_is_distance_minimum(self, almanac):
        p = almanac.moon.next_perigee.raw
        def distance(ts):
            return almanac(almanac_time=ts).moon.distance.raw
        assert distance(p) < distance(p - 3 * 86400)
        assert distance(p) < distance(p + 3 * 86400)

    def test_apsides_moon_only(self, almanac):
        """No other served body orbits the observer: anything but the moon
        raises a clean per-tag AttributeError (PyEphem has no apsides, so
        the fallback cannot answer either)."""
        with pytest.raises(AttributeError):
            almanac.mars.next_perigee
        with pytest.raises(AttributeError):
            almanac.rigel.next_apogee

    def test_apsis_at_ephemeris_edge(self, sky, almanac):
        """Near the ephemeris edge the search window pokes past the span:
        the tag serves an honest N/A, and the no-event outcome lands in
        the event cache -- weewx-loopdata retries no-data event fields on
        every loop packet, and each retry must hit the cache, not a fresh
        extrema search."""
        edge = almanac(almanac_time=sky.end_ts - 3 * 86400)
        assert edge.moon.next_perigee.raw is None
        assert str(edge.moon.next_perigee).strip() == 'N/A'
        hit = wxskyfield._DAY_CACHE.get(('event', 'next_perigee'))
        assert hit is not None and hit[2] is None


class TestEarthApsides:
    """Earth's own perihelion/aphelion, served as top-level tags -- the
    same geometric-extremum machinery as the moon's apsides on the
    earth-sun distance.  All four regression values match the published
    USNO instants within a minute (2025 perihelion Jan 4 13:28 UT and
    2024 aphelion Jul 5 05:06 UT to the exact minute)."""

    def test_apsis_times(self, almanac):
        assert almanac.next_perihelion.raw == pytest.approx(1767460538, abs=120)
        assert almanac.previous_perihelion.raw == pytest.approx(1735997286, abs=120)
        assert almanac.next_aphelion.raw == pytest.approx(1751572482, abs=120)
        assert almanac.previous_aphelion.raw == pytest.approx(1720155962, abs=120)

    def test_ordering_and_spacing(self, almanac):
        assert almanac.previous_perihelion.raw < TIME_TS < almanac.next_perihelion.raw
        assert almanac.previous_aphelion.raw < TIME_TS < almanac.next_aphelion.raw
        # Consecutive perihelia average one anomalistic year apart, but
        # individual spacings jitter by more than a day: the moon swings
        # EARTH around the earth-moon barycenter, shifting each year's
        # distance minimum (2025 -> 2026 is 364.16 days).
        assert (almanac.next_perihelion.raw - almanac.previous_perihelion.raw
                == pytest.approx(365.26 * 86400, abs=2.0 * 86400))

    def test_perihelion_is_distance_minimum(self, almanac):
        p = almanac.next_perihelion.raw
        def distance(ts):
            return almanac(almanac_time=ts).sun.earth_distance
        assert distance(p) < distance(p - 10 * 86400)
        assert distance(p) < distance(p + 10 * 86400)


class TestVisible:
    def test_sun_visible(self, almanac):
        assert almanac.sun.visible.raw == pytest.approx(almanac.sunset.raw - almanac.sunrise.raw, abs=1.0)
        assert str(almanac.sun.visible.long_form())

    def test_sun_visible_change(self, almanac):
        # Within a day of the solstice, the day length changes just a few seconds.
        assert abs(almanac.sun.visible_change().raw) < 60.0

    def test_sun_visible_change_across_dst(self, almanac):
        # 2026-03-09 00:30 PDT: within the first hour after midnight on the
        # day after the spring-forward transition.  A flat time_ts - 86400
        # is 2026-03-07 23:30 PST -- the wrong calendar day -- so
        # visible_change must anchor its day arithmetic at local noon.
        just_after_midnight = time.mktime((2026, 3, 9, 0, 30, 0, 0, 0, -1))
        today = almanac(almanac_time=just_after_midnight)
        yesterday = almanac(almanac_time=time.mktime((2026, 3, 8, 12, 0, 0, 0, 0, -1)))
        expected = today.sun.visible.raw - yesterday.sun.visible.raw
        assert today.sun.visible_change().raw == pytest.approx(expected, abs=1.0)

    def test_polar_day(self, almanac):
        polar = almanac(lat=70.0, lon=25.0, altitude=0.0)
        assert polar.sun.rise.raw is None
        assert polar.sun.set.raw is None
        assert polar.sun.visible.raw == 86400

    def test_polar_night(self, sky):
        with saved_almanacs():
            wxskyfield.register_almanac(sky)
            # 2024-12-21 12:00:00 PST, above the arctic circle
            polar = weewx.almanac.Almanac(1734811200, 70.0, 25.0, altitude=0.0,
                                          formatter=weewx.units.get_default_formatter())
            assert polar.sun.visible.raw == 0
            assert polar.sun.rise.raw is None


class TestPlanets:
    def test_planet_rise_set(self, almanac):
        for planet in ('mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune', 'pluto'):
            binder = getattr(almanac, planet)
            assert binder.rise.raw is not None
            assert binder.set.raw is not None
            assert binder.transit.raw is not None
            assert -90.0 <= binder.alt <= 90.0
            assert 0.0 <= binder.az < 360.0


class TestFallback:
    def test_star_without_catalog_falls_back_to_pyephem(self):
        pytest.importorskip('ephem')
        # Without the Hipparcos catalog, stars fall through to PyEphem.
        starless_sky = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'))
        with saved_almanacs():
            assert wxskyfield.register_almanac(starless_sky)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert alm.rigel.rise.raw is not None

    def test_unknown_binder_attribute_falls_back(self, almanac):
        pytest.importorskip('ephem')
        # The moon's subsolar latitude is not computed by the Skyfield
        # almanac; PyEphem handles it.
        assert almanac.moon.subsolar_lat is not None

    def test_nonsense_body(self, almanac):
        pytest.importorskip('ephem')
        with pytest.raises(AttributeError):
            almanac.bar.rise

    def test_nonsense_attribute(self, almanac):
        with pytest.raises(AttributeError):
            almanac.sun.foo


class TestEphemerisRange:
    """Almanac times outside the ephemeris' span (DE421: 1899-2053) must
    fall through to the next almanac, never raise EphemerisRangeError into
    report generation."""

    OUT_OF_RANGE_TS = 4102444800.0    # 2100-01-01 00:00:00 UTC

    def test_covers(self, sky):
        assert sky.covers(TIME_TS)
        assert not sky.covers(self.OUT_OF_RANGE_TS)
        assert not sky.covers(-3000000000.0)    # 1874

    def test_out_of_range_falls_back_to_pyephem(self, almanac):
        pytest.importorskip('ephem')
        far = almanac(almanac_time=self.OUT_OF_RANGE_TS)
        assert far.sunrise.raw is not None
        assert str(far.sun.rise) != ''
        assert str(far.next_solstice) != ''

    def test_out_of_range_without_pyephem_is_per_tag(self, skyfield_only_almanac):
        far = skyfield_only_almanac(almanac_time=self.OUT_OF_RANGE_TS)
        with pytest.raises(AttributeError):
            far.sunrise


class TestPyEphemAgreement:
    """The Skyfield values should closely agree with PyEphem."""

    def test_sun_events_agree(self, almanac):
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer(start_of_day=True)
        sun = ephem.Sun()
        pyephem_rise = weewx.almanac.djd_to_timestamp(observer.next_rising(sun))
        pyephem_set = weewx.almanac.djd_to_timestamp(observer.next_setting(sun))
        assert almanac.sunrise.raw == pytest.approx(pyephem_rise, abs=EPHEM_TOL)
        assert almanac.sunset.raw == pytest.approx(pyephem_set, abs=EPHEM_TOL)


class TestConventions:
    """Behaviors where PyEphem and standard astronomical conventions differ,
    or where the two almanacs must interoperate (see 'Differences from
    PyEphem' in the README)."""

    def test_separation_tuple_form(self, almanac):
        """(longitude, latitude) tuples in radians -> radians, per the
        WeeWX 5.2 almanac API (Meeus 17.1)."""
        import math
        sep = almanac.separation((math.radians(10), math.radians(20)),
                                 (math.radians(30), math.radians(40)))
        assert sep == pytest.approx(0.45948598, abs=1e-6)

    def test_separation_body_form_defers_to_pyephem(self, almanac):
        """PyEphem Body arguments are not tuples; they must pass through to
        PyEphem rather than crash."""
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        mars = ephem.Mars(observer)
        venus = ephem.Venus(observer)
        assert almanac.separation(mars, venus) == pytest.approx(
            float(ephem.separation(mars, venus)), abs=1e-9)

    def test_separation_binder_form(self, skyfield_only_almanac):
        """$almanac.separation($almanac.mars, $almanac.venus) works with this
        almanac's own binders, natively (no PyEphem involved).  Cross-checked
        against the tuple form fed with geocentric coordinates of date."""
        import math
        alm = skyfield_only_almanac
        sep = alm.separation(alm.mars, alm.venus)
        tuple_sep = alm.separation(
            (math.radians(alm.mars.g_ra), math.radians(alm.mars.g_dec)),
            (math.radians(alm.venus.g_ra), math.radians(alm.venus.g_dec)))
        assert sep == pytest.approx(tuple_sep, abs=1e-3)

    def test_separation_mixed_form(self, skyfield_only_almanac):
        """A binder mixed with a coordinate tuple works natively: the
        binder contributes its apparent geocentric coordinates of date."""
        import math
        alm = skyfield_only_almanac
        venus_tuple = (math.radians(alm.venus.g_ra), math.radians(alm.venus.g_dec))
        mixed = alm.separation(alm.mars, venus_tuple)
        assert mixed == pytest.approx(alm.separation(alm.mars, alm.venus), abs=1e-3)

    def test_separation_honors_each_binders_time(self, skyfield_only_almanac):
        """Each binder is observed at its own almanac's time: the moon moves
        ~12 degrees/day, so yesterday's moon is far from today's."""
        import math
        alm = skyfield_only_almanac
        yesterday = alm(almanac_time=TIME_TS - 86400)
        same_day = alm.separation(alm.sun, alm.moon)
        cross_day = alm.separation(alm.sun, yesterday.moon)
        assert abs(math.degrees(cross_day - same_day)) > 5.0

    def test_separation_body_form_without_pyephem(self, skyfield_only_almanac):
        """Without PyEphem, a non-tuple argument finds no almanac that can
        handle it: WeeWX raises ValueError (rather than a crash mid-formula)."""
        class NotATuple:
            pass
        with pytest.raises(ValueError):
            skyfield_only_almanac.separation(NotATuple(), NotATuple())

    def test_hour_angle_convention(self, skyfield_only_almanac):
        """$almanac.<body>.ha is the local apparent hour angle in signed
        decimal degrees: 0 at transit, negative east of the meridian,
        positive west.  Fixed regression values for the standard fixture;
        at local noon the sun is shortly before its transit, so slightly
        negative."""
        alm = skyfield_only_almanac
        assert alm.sun.ha == pytest.approx(-17.6239, abs=0.01)
        assert alm.saturn.ha == pytest.approx(70.7862, abs=0.01)
        assert alm.rigel.ha == pytest.approx(-5.8527, abs=0.01)
        assert -180.0 <= alm.moon.ha < 180.0

    def test_hour_angle_agrees_with_pyephem(self, almanac):
        """Same angle as PyEphem's ha, modulo the wrapping convention
        (PyEphem usually wraps to [0, 2*pi))."""
        ephem = pytest.importorskip('ephem')
        import math
        observer = pyephem_observer()
        for name, body in [('sun', ephem.Sun()), ('moon', ephem.Moon()),
                           ('mars', ephem.Mars())]:
            body.compute(observer)
            diff = getattr(almanac, name).ha - math.degrees(body.ha)
            assert (diff + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=0.01)

    def test_hlon_is_pyephem_spelling_of_hlong(self, skyfield_only_almanac):
        """hlon (PyEphem's spelling) reports the same decimal degrees as
        hlong, the XEphem sun convention included."""
        alm = skyfield_only_almanac
        assert alm.mars.hlon == alm.mars.hlong
        assert alm.sun.hlon == alm.sun.hlong

    def test_sun_hlong_is_earths_heliocentric_longitude(self, almanac):
        """Heliocentric coordinates of the sun itself are undefined; Earth's
        are reported, per the XEphem convention (and never 0.0)."""
        ephem = pytest.importorskip('ephem')
        import math
        observer = pyephem_observer()
        sun = ephem.Sun(observer)
        assert almanac.sun.hlong == pytest.approx(math.degrees(sun.hlong), abs=0.05)

    def test_moon_hlong_is_truly_heliocentric(self, almanac):
        """The moon's hlongitude is its true heliocentric longitude, within
        ~0.15 degrees of Earth's (the moon is close to Earth as seen from the
        sun) -- NOT PyEphem's geocentric redefinition, which differs wildly."""
        ephem = pytest.importorskip('ephem')
        import math
        observer = pyephem_observer()
        moon = ephem.Moon(observer)
        assert almanac.moon.hlong == pytest.approx(almanac.sun.hlong, abs=0.2)
        assert abs(almanac.moon.hlong - math.degrees(moon.hlong)) > 90.0

    def test_pressure_zero_gives_geometric_rise(self, almanac):
        """WeeWX's documented pressure=0 idiom turns refraction off for
        rise/set.  Verified against PyEphem with pressure=0 (both compute
        the geometric upper-limb crossing)."""
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer(start_of_day=True)
        observer.pressure = 0
        sun = ephem.Sun()
        pyephem_rise = weewx.almanac.djd_to_timestamp(observer.next_rising(sun))
        no_refraction = almanac(pressure=0)
        assert no_refraction.sun.rise.raw == pytest.approx(pyephem_rise, abs=EPHEM_TOL)

    def test_pressure_scales_refraction(self, almanac):
        # Less refraction -> the sun appears later: default (1010 mbar)
        # rises earliest, low pressure later, no refraction latest.
        default_rise = almanac.sun.rise.raw
        low_pressure_rise = almanac(pressure=800).sun.rise.raw
        geometric_rise = almanac(pressure=0).sun.rise.raw
        assert default_rise < low_pressure_rise < geometric_rise

    def test_circumpolar_agrees_with_rise_set(self, almanac):
        """At 66.2N on the June solstice the sun's lower culmination is a few
        tenths of a degree below the geometric horizon but above the refracted
        one: rise/set find no crossing, and circumpolar must say True (it is
        judged against the same effective horizon as rise/set)."""
        polar = weewx.almanac.Almanac(TIME_TS, 66.2, LONGITUDE, altitude=ALTITUDE_M,
                                      formatter=weewx.units.get_default_formatter())
        assert polar.sun.rise.raw is None
        assert polar.sun.set.raw is None
        assert polar.sun.circumpolar
        assert not polar.sun.neverup


class TestNativePhysicalEphemeris:
    """Moon libration/colongitude, Jupiter central meridian longitudes and
    Saturn ring tilt, computed natively.  All return radians, like PyEphem's."""

    def test_libration_agrees_with_pyephem(self, almanac):
        import math
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        moon = ephem.Moon(observer)
        # Optical libration; the neglected physical libration is < 0.04 deg.
        assert math.degrees(almanac.moon.libration_lat) == pytest.approx(
            math.degrees(moon.libration_lat), abs=0.1)
        assert math.degrees(almanac.moon.libration_long) == pytest.approx(
            math.degrees(moon.libration_long), abs=0.1)
        assert math.degrees(almanac.moon.colong) == pytest.approx(
            math.degrees(moon.colong), abs=0.25)

    def test_colong_definition(self, almanac):
        """Anchor colong to its definition rather than to PyEphem: the
        selenographic colongitude of the sun is ~90 degrees at full moon
        (within the +/-8 degree libration/geometry envelope), and PyEphem
        agrees closely there (both implementations are best-conditioned
        near syzygy)."""
        import math
        ephem = pytest.importorskip('ephem')
        full = almanac(almanac_time=almanac.next_full_moon.raw)
        colong = math.degrees(full.moon.colong)
        assert colong == pytest.approx(90.0, abs=9.0)
        observer = ephem.Observer()
        observer.date = weewx.almanac.timestamp_to_djd(almanac.next_full_moon.raw)
        moon = ephem.Moon(observer)
        assert colong == pytest.approx(math.degrees(moon.colong) % 360.0, abs=0.1)

    def test_libration_range(self, almanac):
        import math
        # Librations never exceed about 8 degrees.
        assert abs(math.degrees(almanac.moon.libration_lat)) < 8.0
        assert abs(math.degrees(almanac.moon.libration_long)) < 8.5

    def test_subsolar_lat(self, skyfield_only_almanac):
        """The selenographic latitude of the subsolar point, from the same
        Meeus ch. 53 machinery as colong; radians carrying .degrees, like
        the librations.  It can never exceed the mean lunar equator's
        inclination to the ecliptic (1.54 deg) plus the sun's tiny ecliptic
        latitude as seen from the moon."""
        alm = skyfield_only_almanac
        # Regression value for the standard fixture (2025-06-21 12:00 PDT).
        assert alm.moon.subsolar_lat.degrees == pytest.approx(1.5171, abs=0.001)
        assert abs(alm.moon.subsolar_lat.degrees) < 1.6

    def test_subsolar_lat_agrees_with_pyephem(self, almanac):
        import math
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        moon = ephem.Moon(observer)
        assert math.degrees(almanac.moon.subsolar_lat) == pytest.approx(
            math.degrees(moon.subsolar_lat), abs=0.01)

    def test_moon_phase_is_raw_fraction(self, skyfield_only_almanac):
        """$almanac.moon.moon_phase is PyEphem's raw illuminated fraction,
        0..1 -- exactly phase/100 (the top-level $almanac.moon_phase, the
        phase NAME, is a different tag served by the almanac itself)."""
        alm = skyfield_only_almanac
        assert alm.moon.moon_phase == pytest.approx(alm.moon.phase / 100.0, abs=1e-12)
        assert 0.0 <= alm.moon.moon_phase <= 1.0

    def test_moon_phase_agrees_with_pyephem(self, almanac):
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        moon = ephem.Moon(observer)
        assert almanac.moon.moon_phase == pytest.approx(moon.moon_phase, abs=0.001)

    def test_jupiter_cml(self, almanac):
        """Pinned against the rigorous IAU rotation model (pole + System
        I/II rates), cross-checked with PyEphem.  PyEphem's own values sit
        about 0.8 degrees from the IAU definition, hence the tolerance."""
        import math
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        jupiter = ephem.Jupiter(observer)
        assert math.degrees(almanac.jupiter.cmlI) == pytest.approx(
            math.degrees(jupiter.cmlI), abs=1.2)
        assert math.degrees(almanac.jupiter.cmlII) == pytest.approx(
            math.degrees(jupiter.cmlII), abs=1.2)
        # Regression values (IAU rotation elements, 2025-06-21 12:00 PDT).
        assert math.degrees(almanac.jupiter.cmlI) == pytest.approx(162.19, abs=0.05)
        assert math.degrees(almanac.jupiter.cmlII) == pytest.approx(74.54, abs=0.05)

    def test_saturn_ring_tilt(self, almanac):
        import math
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        saturn = ephem.Saturn(observer)
        assert math.degrees(almanac.saturn.earth_tilt) == pytest.approx(
            math.degrees(saturn.earth_tilt), abs=0.05)
        assert math.degrees(almanac.saturn.sun_tilt) == pytest.approx(
            math.degrees(saturn.sun_tilt), abs=0.05)


class TestPhysicalAttributes:
    """Magnitude, illuminated fraction, angular size, circumpolar status and
    parallactic angle, all computed natively with Skyfield."""

    def test_magnitudes_pinned(self, almanac):
        assert almanac.venus.mag == pytest.approx(-4.20, abs=0.05)
        assert almanac.mars.mag == pytest.approx(1.44, abs=0.05)
        assert almanac.sun.mag == pytest.approx(-26.70, abs=0.05)
        assert almanac.moon.mag == pytest.approx(-8.42, abs=0.1)
        assert almanac.pluto.mag == pytest.approx(14.42, abs=0.1)

    def test_magnitudes_agree_with_pyephem(self, almanac):
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        # PyEphem's lunar magnitude model before 4.2 is crude (-10.9 at this
        # fixture's crescent, where 4.2 and Skyfield both say -8.4), so the
        # moon comparison is meaningful only against 4.2 or later.  Field
        # case: Debian bookworm's python3-ephem 4.1.x (issue #2 reporter).
        # The moon's own regression value stays pinned in
        # test_magnitudes_pinned regardless of PyEphem.
        ephem_version = tuple(int(part) for part in ephem.__version__.split('.')[:2])
        for planet in ('mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune',
                       'sun', 'moon', 'pluto'):
            if planet == 'moon' and ephem_version < (4, 2):
                continue
            body = getattr(ephem, planet.title())()
            body.compute(observer)
            # PyEphem uses older magnitude models, so agreement is loose.
            assert getattr(almanac, planet).mag == pytest.approx(body.mag, abs=0.6), planet

    def test_phase(self, almanac):
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        for planet in ('mercury', 'venus', 'mars', 'moon'):
            body = getattr(ephem, planet.title())()
            body.compute(observer)
            assert getattr(almanac, planet).phase == pytest.approx(body.phase, abs=0.1), planet
        # The sun is fully illuminated, by definition (and per PyEphem).
        assert almanac.sun.phase == 100.0

    def test_size_and_radius(self, almanac):
        ephem = pytest.importorskip('ephem')
        import math
        observer = pyephem_observer()
        for planet in ('sun', 'moon', 'venus', 'jupiter'):
            body = getattr(ephem, planet.title())()
            body.compute(observer)
            binder = getattr(almanac, planet)
            # size is the angular diameter in arcseconds.
            assert binder.size == pytest.approx(body.size, rel=0.02), planet
            # radius is the angular radius in decimal degrees (old-style name).
            assert binder.radius == pytest.approx(math.degrees(body.radius), rel=0.02), planet
            # radius_size is a ValueHelper; its raw value is converted to degrees.
            assert binder.radius_size.raw == pytest.approx(binder.radius, abs=1e-6), planet
        # size is self-consistent with radius.
        assert almanac.sun.size == pytest.approx(almanac.sun.radius * 2.0 * 3600.0, rel=1e-6)

    def test_parallactic_angle(self, almanac):
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer()
        for planet in ('venus', 'moon', 'mars'):
            body = getattr(ephem, planet.title())()
            body.compute(observer)
            assert getattr(almanac, planet).parallactic_angle() == pytest.approx(
                float(body.parallactic_angle()), abs=0.01), planet

    @pytest.mark.parametrize('body, attr', [
        ('moon', 'libration_lat'), ('moon', 'libration_long'), ('moon', 'colong'),
        ('jupiter', 'cmlI'), ('jupiter', 'cmlII'),
        ('saturn', 'earth_tilt'), ('saturn', 'sun_tilt'),
        ('venus', 'parallactic_angle'),
    ])
    def test_radians_tags_carry_degrees(self, almanac, body, attr):
        """Every PyEphem-shaped radians attribute is a Radians float: the
        value itself is unchanged (plain radians), and .degrees/.radians
        carry the same answer."""
        import math
        value = getattr(getattr(almanac, body), attr)
        assert isinstance(value, float)
        assert value.degrees == pytest.approx(math.degrees(value))
        assert value.radians == float(value)

    def test_separation_carries_degrees(self, almanac):
        import math
        sep = almanac.separation(almanac.mars, almanac.venus)
        assert sep.degrees == pytest.approx(math.degrees(sep))

    def test_parallactic_angle_forms(self, almanac):
        """The tag resolves to a callable value: the parens-free form, the
        legacy PyEphem-style explicit call, and the .degrees chain all agree
        -- as a plain getattr walk, the way loopdata evaluates almanac
        fields (no Cheetah autocall involved)."""
        value = almanac.venus.parallactic_angle
        assert isinstance(value, float)
        assert almanac.venus.parallactic_angle() == value
        assert almanac.venus.parallactic_angle.degrees == value.degrees

    def test_parallactic_angle_in_cheetah(self, almanac):
        """Rendered through Cheetah itself: autocall must not intercept
        .degrees, and the explicit-call template form must keep working."""
        Template = pytest.importorskip('Cheetah.Template').Template
        import math
        bare = str(Template('$almanac.moon.parallactic_angle.degrees',
                            searchList=[{'almanac': almanac}]))
        assert float(bare) == pytest.approx(
            math.degrees(almanac.moon.parallactic_angle))
        called = str(Template('$almanac.moon.parallactic_angle()',
                              searchList=[{'almanac': almanac}]))
        assert float(called) == pytest.approx(float(almanac.moon.parallactic_angle))

    def test_circumpolar_neverup(self, almanac):
        # From 37N, the sun neither stays up nor stays down.
        assert not almanac.sun.circumpolar
        assert not almanac.sun.neverup

    def test_name(self, almanac):
        assert almanac.sun.name == 'Sun'
        assert almanac.mars.name == 'Mars'


@needs_catalog
class TestStars:
    """Named stars, computed natively from the Hipparcos catalog."""

    def test_all_named_stars_loaded(self, sky):
        assert len(sky.stars) == len(set(wxskyfield.NAMED_STARS))
        for name in wxskyfield.NAMED_STARS:
            assert name in sky.stars

    def test_star_positions_and_magnitudes_match_pyephem(self, almanac, sky):
        """Verify the name -> HIP mapping: every star's position and magnitude
        must agree with PyEphem's own catalog."""
        ephem = pytest.importorskip('ephem')
        import math
        observer = pyephem_observer()
        # Compare with refraction off (pressure=0): for a star sitting on the
        # horizon (e.g., Canopus from 37N), the two libraries' refraction
        # models differ by up to a degree, which would mask a mapping error.
        observer.pressure = 0
        no_refraction = almanac(pressure=0)
        compared = 0
        for name in sky.stars:
            pyephem_name = name.replace('_', ' ').title()
            try:
                star = ephem.star(pyephem_name)
            except KeyError:
                # An IAU name beyond PyEphem's catalog: nothing to compare.
                continue
            compared += 1
            star.compute(observer)
            binder = getattr(no_refraction, name)
            az1, alt1 = math.radians(binder.az), math.radians(binder.alt)
            az2, alt2 = float(star.az), float(star.alt)
            separation = math.degrees(math.acos(min(1.0,
                math.sin(alt1) * math.sin(alt2)
                + math.cos(alt1) * math.cos(alt2) * math.cos(az1 - az2))))
            assert separation < 0.1, '%s is %f degrees from PyEphem position' % (name, separation)
            assert binder.mag == pytest.approx(star.mag, abs=1.5), name
        # Every PyEphem-known name must actually have been compared.
        assert compared >= 100

    def test_star_rise_set_transit(self, almanac):
        assert almanac.rigel.rise.raw is not None
        assert almanac.rigel.set.raw is not None
        assert almanac.rigel.rise.raw < almanac.rigel.transit.raw < almanac.rigel.set.raw + 86400
        assert str(almanac.rigel.visible.long_form())

    def test_star_rise_agrees_with_pyephem(self, almanac):
        ephem = pytest.importorskip('ephem')
        observer = pyephem_observer(start_of_day=True)
        star = ephem.star('Rigel')
        pyephem_rise = weewx.almanac.djd_to_timestamp(observer.next_rising(star))
        assert almanac.rigel.rise.raw == pytest.approx(pyephem_rise, abs=EPHEM_TOL)

    def test_star_circumpolar(self, almanac):
        # From 37N, Polaris never sets and Acrux (Southern Cross) never rises.
        assert almanac.polaris.circumpolar
        assert not almanac.polaris.neverup
        assert almanac.acrux.neverup
        assert almanac.polaris.rise.raw is None
        assert almanac.acrux.rise.raw is None
        assert almanac.polaris.visible.raw == 86400
        assert almanac.acrux.visible.raw == 0

    def test_star_multiword_name(self, almanac):
        assert almanac.kaus_australis.name == 'Kaus Australis'
        assert almanac.kaus_australis.rise.raw is not None

    def test_iau_star_names(self, almanac, sky):
        """The name table is the IAU Catalog of Star Names (every entry with
        a Hipparcos number) plus PyEphem's names as aliases."""
        assert len(wxskyfield.NAMED_STARS) >= 400
        # An IAU name PyEphem never had: Barnard's Star (HIP 87937), the
        # highest-proper-motion star in the sky.
        assert almanac.barnards_star.mag == pytest.approx(9.54, abs=0.1)
        assert 'Barnards Star' in almanac.barnards_star.name
        # PyEphem's legacy spellings still work, mapping to the same stars
        # as the IAU spellings.
        assert wxskyfield.NAMED_STARS['alcaid'] == wxskyfield.NAMED_STARS['alkaid']
        assert wxskyfield.NAMED_STARS['albereo'] == wxskyfield.NAMED_STARS['albireo']
        assert wxskyfield.NAMED_STARS['sirrah'] == wxskyfield.NAMED_STARS['alpheratz']
        # Alula Australis has no astrometric solution in hip_main.dat; its
        # position comes from the identification columns.
        assert sky.stars['alula_australis'][0].dec.degrees == pytest.approx(31.53, abs=0.01)

    def test_hip_number_tags(self, almanac, sky):
        """Any of the catalog's 118,218 stars can be addressed by number:
        $almanac.hip_57939.  Loaded lazily and cached; misses are cached
        too and fall through to the next almanac (AttributeError)."""
        # HIP 32349 is Sirius: the hip_ tag serves the same star as the name.
        assert almanac.hip_32349.mag == almanac.sirius.mag
        assert almanac.hip_32349.rise.raw == pytest.approx(almanac.sirius.rise.raw, abs=1.0)
        assert 'hip_32349' in sky.stars    # cached
        # A star far beyond the named ~400 works out of the box:
        # Groombridge 1830 (HIP 57939), mag 6.4.
        assert almanac.hip_57939.mag == pytest.approx(6.42, abs=0.1)
        # A number the catalog has never heard of is a cached miss.
        with pytest.raises(AttributeError):
            almanac.hip_999999.mag
        assert 999999 in sky.hip_misses

    def test_hip_tag_leading_zeros(self, almanac):
        """Catalogs zero-pad HIP numbers ('HIP 032349'); the zero-padded tag
        must serve the same star as the canonical one."""
        assert almanac.hip_032349.mag == almanac.hip_32349.mag == almanac.sirius.mag

    def test_hip_tag_reuses_loaded_star(self, almanac, sky):
        """A hip_ tag for a star already loaded under a name is aliased
        without rescanning the catalog."""
        rigel_hip = wxskyfield.NAMED_STARS['rigel']
        assert getattr(almanac, 'hip_%d' % rigel_hip).mag == almanac.rigel.mag
        assert sky.stars['hip_%d' % rigel_hip] is sky.stars['rigel']

    def test_missing_catalog_degrades_per_tag(self, tmp_path):
        """stars=true with an absent/unreadable catalog file must degrade to
        per-tag AttributeError, never leak OSError into report generation."""
        (tmp_path / 'wxskyfield_de421.bsp').symlink_to(
            os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp'))
        crippled = wxskyfield.Sky(str(tmp_path), load_stars=True)
        assert crippled.is_valid()
        assert crippled.stars == {}
        assert not crippled.load_stars    # disabled by the failed load
        with saved_almanacs():
            assert wxskyfield.register_almanac(crippled)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            with pytest.raises(AttributeError):
                alm.hip_32349.mag

    @needs_catalog
    def test_corrupt_catalog_after_startup_degrades_per_tag(self, tmp_path):
        """A catalog corrupted after startup (e.g. a broken reinstall
        rewriting the file) must degrade hip_<n> tags to per-tag misses,
        never leak a gzip error into report generation."""
        (tmp_path / 'wxskyfield_de421.bsp').symlink_to(
            os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp'))
        (tmp_path / wxskyfield.STAR_FILE).symlink_to(
            os.path.join(REPO_ROOT, 'bin', 'user', wxskyfield.STAR_FILE))
        s = wxskyfield.Sky(str(tmp_path), load_stars=True)
        assert s.is_valid() and s.load_stars
        # Garbage bytes wearing a gzip magic number replace the catalog.
        (tmp_path / wxskyfield.STAR_FILE).unlink()
        (tmp_path / wxskyfield.STAR_FILE).write_bytes(b'\x1f\x8b\x08\x00\xff\xfe garbage \xff')
        assert 12345 not in wxskyfield.NAMED_STARS.values()
        assert not s.get_star_by_hip(12345)
        assert 12345 in s.hip_misses    # the miss is cached

    def test_rigil_kentaurus_is_alpha_cen_a(self, almanac):
        """Rigil Kentaurus is the IAU name for Alpha Centauri A (HIP 71683,
        mag -0.01), not its close binary companion Alpha Cen B (HIP 71681,
        mag 1.35).  The pair is too close for the general 0.1-degree position
        audit to tell apart, so pin the identity here."""
        assert wxskyfield.NAMED_STARS['rigil_kentaurus'] == 71683
        assert almanac.rigil_kentaurus.mag == pytest.approx(-0.01, abs=0.05)

    def test_malformed_record_skips_only_that_star(self, tmp_path):
        """One bad catalog record must disable only that star, not the
        whole catalog."""
        import gzip
        good = None
        with gzip.open(os.path.join(REPO_ROOT, 'bin', 'user', wxskyfield.STAR_FILE),
                       'rt') as f:
            for line in f:
                if line.startswith('H|') and line.split('|')[1].strip() == '32349':
                    good = line
                    break
        assert good is not None
        vega_hip = wxskyfield.NAMED_STARS['vega']
        truncated = 'H|%12d| |18 36 56.34|+38 47 01.3\n' % vega_hip
        bad_mag = good.split('|')
        bad_mag[1] = '%12d' % wxskyfield.NAMED_STARS['rigel']
        bad_mag[5] = ' x.xx'
        with gzip.open(str(tmp_path / wxskyfield.STAR_FILE), 'wt') as f:
            f.write(good + truncated + '|'.join(bad_mag))
        stars = wxskyfield.Sky.load_named_stars(str(tmp_path))
        assert 'sirius' in stars
        assert 'vega' not in stars
        assert 'rigel' not in stars

    def test_star_unsupported_attributes(self, almanac):
        # A star has no phase (nor does PyEphem's).
        with pytest.raises(AttributeError):
            almanac.rigel.phase
        with pytest.raises(AttributeError):
            almanac.rigel.hlong
        with pytest.raises(AttributeError):
            almanac.rigel.hlon

    def test_star_earth_distance(self, almanac):
        """Unlike PyEphem, earth_distance and sun_distance work for stars
        with a parallax (in AU, like the planets).  Hipparcos puts Rigel at
        ~773 light years; at that distance the two differ by at most 1 AU."""
        assert almanac.rigel.earth_distance / wxskyfield.AU_PER_LIGHT_YEAR == pytest.approx(773.0, abs=5.0)
        assert abs(almanac.rigel.sun_distance - almanac.rigel.earth_distance) <= 1.0

    def test_star_distance_value_helpers(self, almanac):
        """The distance twins serve stars with a parallax, like the raw
        tags; a star whose catalog record has no measured parallax
        (alula_australis, HIP 55203) has no known distance -- an empty
        "N/A" ValueHelper, never the PyEphem fallback (whose star objects
        have no such attribute)."""
        assert almanac.rigel.distance.raw / wxskyfield.AU_PER_LIGHT_YEAR == pytest.approx(773.0, abs=5.0)
        assert almanac.rigel.distance.raw == pytest.approx(almanac.rigel.earth_distance, abs=1e-6)
        assert almanac.alula_australis.distance.raw is None
        # The formatter's NONE string ("   N/A" in WeeWX's defaults).
        assert str(almanac.alula_australis.distance).strip() == 'N/A'

    def test_proxima_centauri(self, almanac):
        """The one star beyond PyEphem's catalog: the nearest star, at 4.22
        light years (Hipparcos parallax 772.33 mas), mag 11.01."""
        assert wxskyfield.NAMED_STARS['proxima_centauri'] == 70890
        assert almanac.proxima_centauri.mag == pytest.approx(11.01, abs=0.05)
        ly = almanac.proxima_centauri.earth_distance / wxskyfield.AU_PER_LIGHT_YEAR
        assert ly == pytest.approx(4.223, abs=0.01)
        # From 37N, Proxima (dec -62.7) never rises.
        assert almanac.proxima_centauri.neverup


# Every category of tag the built-in PyEphem almanac supports, including
# direct PyEphem body attributes.  With PyEphem installed, all of these must
# evaluate: natively via Skyfield where possible, via the PyEphem fallback
# otherwise.
PYEPHEM_PARITY_EXPRESSIONS = [
    "almanac.moon_fullness", "almanac.moon.moon_fullness",
    "almanac.sunrise", "almanac.sunset", "almanac.moon_phase", "almanac.moon_index",
    "almanac.sun.rise", "almanac.sun.transit", "almanac.sun.set",
    "almanac.moon.rise", "almanac.moon.transit", "almanac.moon.set",
    "almanac.mars.rise", "almanac.mars.transit", "almanac.mars.set",
    "almanac.rigel.rise", "almanac.rigel.transit", "almanac.rigel.set",
    "almanac.sidereal_time", "almanac.sidereal_angle",
    "almanac.next_vernal_equinox", "almanac.next_autumnal_equinox",
    "almanac.next_summer_solstice", "almanac.previous_winter_solstice",
    "almanac.next_winter_solstice",
    "almanac.next_full_moon", "almanac.next_new_moon",
    "almanac.next_first_quarter_moon", "almanac.previous_last_quarter_moon",
    "almanac.sun.az", "almanac.sun.alt", "almanac.moon.az", "almanac.moon.alt",
    "almanac.sun.azimuth", "almanac.sun.altitude",
    "almanac.moon.azimuth", "almanac.moon.altitude",
    "almanac(horizon=-6).sun(use_center=1).rise",
    "almanac(pressure=0, horizon=-34.0/60.0).sun.previous_rising",
    "almanac.moon.next_setting", "almanac.sun.next_antitransit",
    "almanac.mars.sun_distance", "almanac.mars.earth_distance",
    "almanac.jupiter.cmlI", "almanac.jupiter.cmlII",
    "almanac.venus.mag", "almanac.venus.phase",
    "almanac.sun.size", "almanac.moon.radius_size",
    "almanac.moon.libration_lat", "almanac.moon.libration_long", "almanac.moon.colong",
    "almanac.moon.subsolar_lat", "almanac.moon.moon_phase",
    "almanac.saturn.earth_tilt",
    "almanac.mercury.elong", "almanac.mercury.elongation",
    "almanac.sun.hlong", "almanac.mars.hlongitude", "almanac.mars.hlatitude",
    "almanac.sun.ha", "almanac.mars.hlon",
    "almanac.sun.a_ra", "almanac.sun.a_dec", "almanac.sun.g_ra", "almanac.sun.g_dec",
    "almanac.sun.astro_ra", "almanac.sun.geo_dec",
    "almanac.sun.topo_ra", "almanac.sun.topo_dec", "almanac.sun.hour_angle",
    "almanac.sun.name", "almanac.venus.circumpolar", "almanac.venus.neverup",
    "almanac.sun.parallactic_angle()",
    "almanac.polaris.az", "almanac.polaris.alt",
    "almanac.separation((almanac.venus.a_ra, almanac.venus.a_dec), (almanac.mars.a_ra, almanac.mars.a_dec))",
    "almanac.sun.visible", "almanac.sun.visible_change()", "almanac.moon.visible",
]

# HIP 4427 (gamma Cassiopeiae, mag 2.15) is the brightest star with
# neither an IAU-CSN nor a PyEphem name, so it can only ever come from the
# catalog scan, never from NAMED_STARS -- the star whose absence prompted
# the catalog dome (1.18), and the canary for the full-catalog paths.
GAMMA_CAS_HIP = 4427

# Its real hip_main.dat record, for fabricating small stand-in catalogs.
GAMMA_CAS_RECORD = (
    'H|        4427| |00 56 42.50|+60 43 00.3| 2.15|1|H|014.17708808|+60.71674966| '
    '|   5.32|   25.65|   -3.82|  0.35|  0.38|  0.56|  0.42|  0.44|-0.24| 0.19| 0.04'
    '| 0.24| 0.06|-0.01| 0.08|-0.03| 0.18|-0.26|  0|-1.19|  4427| 2.112|0.002| 2.168'
    '|0.003| |-0.046|0.003|T|-.02|0.00|L| | 2.1379|0.0008|0.009|154| | 2.12| 2.16|  '
    '     |U|2| |00567+6043|I| 1| 1| | | |  |   |       |     |     |    |S| |P|  '
    '5394|B+59  144 |          |          |0.01|B0IV:evar   |X \n')


def make_catalog_root(tmp_path, records: str) -> str:
    """A user_root whose star catalog is a small fabricated gzip holding
    just the given hip_main.dat records; the ephemeris is symlinked from
    the repo."""
    import gzip
    os.symlink(os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp'),
               os.path.join(tmp_path, 'wxskyfield_de421.bsp'))
    with gzip.open(os.path.join(tmp_path, wxskyfield.STAR_FILE), 'wt') as f:
        f.write(records)
    return str(tmp_path)


@needs_catalog
class TestCatalogStarField:
    """star_field/catalog_stars: the dome plots every catalog star to a
    magnitude limit, positions computed in one vectorized observe that
    must agree with the binder's scalar path.  Pinned against the real
    shipped catalog -- since 2.0 the full 118,218 records ARE the bundled
    star file."""

    @staticmethod
    def almanac_type():
        return [a for a in weewx.almanac.almanacs
                if isinstance(a, wxskyfield.SkyfieldAlmanacType)][0]

    def test_shipped_catalog_is_complete(self):
        """The bundled file is the complete Hipparcos main catalog, and
        the magnitude scan finds the known populations (the same counts
        as the 1.18 field measurements against a user-installed
        hip_main.dat)."""
        import gzip
        n = 0
        with gzip.open(os.path.join(REPO_ROOT, 'bin', 'user',
                                    wxskyfield.STAR_FILE), 'rt') as f:
            for _line in f:
                n += 1
        assert n == 118218

    def test_star_counts_pinned(self, sky):
        assert len(sky.catalog_stars(2.6)[0]) == 102
        assert len(sky.catalog_stars(5.0)[0]) == 1627

    def test_field_matches_binder(self, almanac):
        field = {hip: (az, alt, mag) for hip, az, alt, mag
                 in self.almanac_type().star_field(almanac, 5.0)}
        # Gamma Cas is circumpolar at the test latitude, so it must be up.
        assert GAMMA_CAS_HIP in field
        for name, hip in (('rigel', 24436), ('polaris', 11767),
                          ('hip_%d' % GAMMA_CAS_HIP, GAMMA_CAS_HIP)):
            az, alt, mag = field[hip]
            b = getattr(almanac, name)
            assert abs(alt - b.alt) < 1e-6
            assert abs(az - b.az) < 1e-6
        for hip, (az, alt, mag) in field.items():
            assert alt > 0.0
            assert mag <= 5.0

    def test_limit_filters(self, almanac):
        field = self.almanac_type().star_field(almanac, 2.0)
        hips = {hip for hip, _az, _alt, _mag in field}
        # Rigel (0.18) passes a 2.0 limit; gamma Cas (2.15) must not.
        assert 24436 in hips
        assert GAMMA_CAS_HIP not in hips

    def test_empty_field(self, almanac):
        # Nothing is brighter than magnitude -2 (Sirius is -1.44).
        assert self.almanac_type().star_field(almanac, -2.0) == []

    def test_cached_per_limit(self, almanac):
        sky = self.almanac_type().sky
        assert sky.catalog_stars(5.0) is sky.catalog_stars(5.0)

    def test_malformed_record_skipped(self, tmp_path):
        root = make_catalog_root(
            tmp_path, GAMMA_CAS_RECORD + 'H|garbage|record\n')
        s = wxskyfield.Sky(root, load_stars=True)
        assert s.is_valid()
        hips, star, mags = s.catalog_stars(5.0)
        assert GAMMA_CAS_HIP in hips

    def test_corrupt_catalog_degrades(self, tmp_path):
        os.symlink(os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp'),
                   os.path.join(tmp_path, 'wxskyfield_de421.bsp'))
        with open(os.path.join(tmp_path, wxskyfield.STAR_FILE), 'wb') as f:
            f.write(b'\x1f\x8b\x00\x00not really gzip\xff\xfe')
        s = wxskyfield.Sky(str(tmp_path), load_stars=True)
        # The named-star load fails too, so star support is disabled and
        # catalog_stars must return None, not raise.
        assert s.is_valid()
        assert s.catalog_stars(2.6) is None


class TestConstellationLines:
    """The constellation line data and its vectorized vertex field:
    wxskyfield_lines.dat covers all 88 IAU constellations, the bundled
    excerpt carries a record for every line vertex, and
    constellation_field's positions must agree with the binder's scalar
    path (it feeds the Sky page's dome)."""

    @staticmethod
    def almanac_type():
        return [a for a in weewx.almanac.almanacs
                if isinstance(a, wxskyfield.SkyfieldAlmanacType)][0]

    def test_data_covers_every_constellation(self, sky):
        lines = sky.constellation_lines()
        assert ({abbr for abbr, _hips in lines}
                == set(wxskyfield.CONSTELLATION_NAMES))
        for _abbr, hips in lines:
            assert len(hips) >= 2

    def test_excerpt_covers_every_vertex(self, sky):
        wanted = {hip for _abbr, hips in sky.constellation_lines()
                  for hip in hips}
        hips, star = sky.constellation_stars()
        # Every vertex resolved from the bundled excerpt -- a gap here
        # means wxskyfield_lines.dat and wxskyfield_stars.dat were
        # regenerated out of step (tools/gen_constellations.py makes
        # them together).
        assert set(hips) == wanted

    def test_cached_for_engine_life(self, sky):
        assert sky.constellation_lines() is sky.constellation_lines()
        assert sky.constellation_stars() is sky.constellation_stars()

    def test_field_matches_binder(self, almanac):
        amt = self.almanac_type()
        field = amt.constellation_field(almanac)
        hips, _star = amt.sky.constellation_stars()
        # The whole field, below-horizon vertices included: the dome
        # clips setting figures at the rim instead of dropping them.
        assert set(field) == set(hips)
        assert min(alt for _az, alt in field.values()) < 0.0
        for name, hip in (('rigel', 24436), ('polaris', 11767)):
            az, alt = field[hip]
            b = getattr(almanac, name)
            assert abs(alt - b.alt) < 1e-6
            assert abs(az - b.az) < 1e-6

    def test_stars_disabled_disables_lines(self):
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                           load_stars=False)
        assert s.is_valid()
        assert s.constellation_lines() is None
        assert s.constellation_stars() is None

    def test_missing_lines_file_degrades(self, tmp_path):
        for f in ('wxskyfield_de421.bsp', wxskyfield.STAR_FILE):
            os.symlink(os.path.join(REPO_ROOT, 'bin', 'user', f),
                       os.path.join(tmp_path, f))
        s = wxskyfield.Sky(str(tmp_path), load_stars=True)
        assert s.is_valid()
        # No wxskyfield_lines.dat: the dome simply has no figures.
        assert s.constellation_lines() is None
        assert s.constellation_stars() is None


class TestBodyLabel:
    """$almanac.<body>.label -- the body's display name, translated by the
    skin's [Almanac] texts (key = the tag name, beside moon_phases; WeeWX
    pipes the section into every almanac), falling back to the English
    .name for bodies the skin does not translate."""

    def test_untranslated_falls_back_to_name(self, almanac):
        assert almanac.sun.label == 'Sun'
        assert almanac.moon.label == 'Moon'

    @needs_catalog
    def test_star_label(self, almanac):
        assert almanac.rigel.label == 'Rigel'
        assert almanac.proxima_centauri.label == 'Proxima Centauri'

    def test_translated(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter(),
                texts={'moon': 'Mond', 'sun': 'Sonne'})
            assert alm.moon.label == 'Mond'
            assert alm.sun.label == 'Sonne'
            # A body absent from the texts falls back to English.
            assert alm.jupiter.label == 'Jupiter'


class TestConstellations:
    """$almanac.<body>.constellation, computed from the observer's
    topocentric apparent place against skyfield's bundled IAU boundary
    map.  The value is a str subclass: the Latin name (so rendering,
    comparison and serialization see a plain string) carrying .name,
    .abbr and .label attributes; .constellation_abbr is the 1.9 legacy
    alias for .abbr.  Values verified against a star atlas for
    2025-06-21."""

    def test_planets(self, almanac):
        assert almanac.mars.constellation == 'Leo'
        assert almanac.mars.constellation_abbr == 'Leo'
        assert almanac.saturn.constellation == 'Pisces'
        assert almanac.saturn.constellation_abbr == 'Psc'
        assert almanac.jupiter.constellation == 'Gemini'

    def test_sun_and_moon(self, almanac):
        # The sun crosses the Taurus/Gemini boundary each June 21; by noon
        # PDT on 2025-06-21 it sits just inside Gemini.
        assert almanac.sun.constellation == 'Gemini'
        assert almanac.sun.constellation_abbr == 'Gem'
        assert almanac.moon.constellation == 'Aries'

    @needs_catalog
    def test_stars(self, almanac):
        assert almanac.rigel.constellation == 'Orion'
        assert almanac.polaris.constellation == 'Ursa Minor'
        assert almanac.polaris.constellation_abbr == 'UMi'
        assert almanac.antares.constellation == 'Scorpius'
        # Serpens, the one constellation in two pieces, maps to one name.
        assert almanac.unukalhai.constellation == 'Serpens'

    def test_is_a_string_with_attributes(self, almanac):
        """The tag IS the Latin-name string -- a template's equality
        comparison and loopdata's json serialization both see a str --
        with the other views as attributes."""
        c = almanac.saturn.constellation
        assert isinstance(c, str)
        assert c == 'Pisces'
        assert c.name == 'Pisces'
        assert c.abbr == 'Psc'
        assert c.label == 'Pisces'   # untranslated: Latin
        assert json.dumps(c) == '"Pisces"'

    def test_label_translated(self, sky):
        """The [Almanac] [[Constellations]] subsection, keyed by IAU
        abbreviation, translates .label; the value itself stays Latin
        regardless (loopdata consumers read it as data)."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter(),
                texts={'Constellations': {'Gem': 'Zwillinge'}})
            assert alm.sun.constellation.label == 'Zwillinge'
            assert alm.sun.constellation == 'Gemini'
            # An abbreviation absent from the subsection falls back to Latin.
            assert alm.mars.constellation.label == 'Leo'

    def test_label_survives_scalar_constellations_key(self, sky):
        """A malformed skin config (Constellations as a scalar, not a
        subsection) must not break the tag."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter(),
                texts={'Constellations': 'oops'})
            assert alm.mars.constellation.label == 'Leo'

    def test_abbreviation_table_is_complete(self):
        assert len(wxskyfield.CONSTELLATION_NAMES) == 88


class TestEclipses:
    """The eclipse tags report the nearest eclipse VISIBLE from the
    station (the eclipsed body above the horizon at maximum), with _type
    the kind as locally seen.  Dates and local types cross-checked
    against NASA's Five Millennium eclipse catalogs: from Palo Alto on
    2025-06-21, the previous lunar eclipse is the 2025-03-14 total
    (maximum 06:58:43 UTC), the next is 2026-03-03 (the 2025-09-07 total
    falls with the moon below Palo Alto's horizon and must be skipped);
    the previous solar eclipse is 2024-04-08 -- total along its path,
    PARTIAL as seen from Palo Alto -- and the next is the 2029-01-14
    partial."""

    def test_lunar(self, almanac):
        assert almanac.previous_lunar_eclipse.raw == pytest.approx(1741935525.5, abs=TIME_TOL)
        assert almanac.previous_lunar_eclipse_type == 'total'
        assert almanac.next_lunar_eclipse.raw == pytest.approx(1772537621.6, abs=TIME_TOL)
        assert almanac.next_lunar_eclipse_type == 'total'
        assert almanac.previous_lunar_eclipse.raw < TIME_TS < almanac.next_lunar_eclipse.raw
        # The tag is a ValueHelper, formattable like any other event tag.
        assert str(almanac.next_lunar_eclipse) != ''

    def test_solar(self, almanac):
        assert almanac.previous_solar_eclipse.raw == pytest.approx(1712599986.6, abs=TIME_TOL)
        assert almanac.previous_solar_eclipse_type == 'partial'
        assert almanac.next_solar_eclipse.raw == pytest.approx(1863102136.4, abs=TIME_TOL)
        assert almanac.next_solar_eclipse_type == 'partial'
        assert almanac.previous_solar_eclipse.raw < TIME_TS < almanac.next_solar_eclipse.raw

    def test_combined(self, almanac):
        """next_/previous_eclipse pick the sooner (later) of the two
        kinds, with _kind naming the winner -- the selection every skin
        showing "the next eclipse" would otherwise reimplement."""
        assert almanac.next_eclipse.raw == almanac.next_lunar_eclipse.raw
        assert almanac.next_eclipse_kind == 'lunar'
        assert almanac.next_eclipse_type == 'total'
        assert almanac.previous_eclipse.raw == almanac.previous_lunar_eclipse.raw
        assert almanac.previous_eclipse_kind == 'lunar'
        assert almanac.previous_eclipse_type == 'total'

    def test_combined_solar_wins(self, sky):
        """Time-traveled to New Year 2029, Palo Alto's next visible
        eclipse is the 2029-01-14 partial solar (its next visible lunar
        is not until 2031)."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            jan29 = weewx.almanac.Almanac(1861992000, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                          formatter=weewx.units.get_default_formatter())
            assert jan29.next_eclipse_kind == 'solar'
            assert jan29.next_eclipse_type == 'partial'
            assert jan29.next_eclipse.raw == pytest.approx(1863102136.4, abs=TIME_TOL)

    def test_visibility_is_local(self, sky):
        """From Sydney the same date answers differently: the 2025-09-07
        total lunar eclipse IS visible there (maximum 18:11:47 UTC), and
        the next solar eclipse is 2028-07-22, on whose path of totality
        Sydney famously sits."""
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            sydney = weewx.almanac.Almanac(TIME_TS, -33.87, 151.21, altitude=58,
                                           formatter=weewx.units.get_default_formatter())
            assert sydney.next_lunar_eclipse.raw == pytest.approx(1757268707.2, abs=TIME_TOL)
            assert sydney.next_lunar_eclipse_type == 'total'
            assert sydney.next_solar_eclipse.raw == pytest.approx(1847851293.2, abs=TIME_TOL)
            assert sydney.next_solar_eclipse_type == 'total'


# ── satellites ───────────────────────────────────────────────────────────────

class TestSatelliteConfig:
    """[Skyfield] [[Satellites]] parsing, the cache directory convention,
    and the sat_<norad> tag spelling."""

    def test_parse_satellites(self):
        parsed = wxskyfield.parse_satellites(
            {'Satellites': {'ISS': '25544', 'tiangong': '48274'}})
        assert parsed == {'iss': 25544, 'tiangong': 48274}

    def test_bad_norad_disables_only_that_entry(self, caplog):
        with caplog.at_level(logging.ERROR, logger=wxskyfield.log.name):
            parsed = wxskyfield.parse_satellites(
                {'Satellites': {'iss': '25544', 'hubble': 'HST'}})
        assert parsed == {'iss': 25544}
        assert 'hubble' in caplog.text and 'NORAD' in caplog.text

    def test_shadowing_names_refused(self, caplog):
        """A name that is already an almanac tag would silently never be
        served (body dispatch checks planets, stars and the number forms
        first), so it is refused loudly."""
        with caplog.at_level(logging.ERROR, logger=wxskyfield.log.name):
            parsed = wxskyfield.parse_satellites(
                {'Satellites': {'mars': '1', 'rigel': '2', 'hip_87937': '3',
                                'sat_25544': '4', 'sun': '5', 'earth': '6',
                                'iss': '25544'}})
        assert parsed == {'iss': 25544}
        assert caplog.text.count('already an almanac tag') == 6

    def test_missing_section_means_no_satellites(self):
        assert wxskyfield.parse_satellites({}) == {}
        assert wxskyfield.parse_satellites({'Satellites': {}}) == {}

    def test_sat_dir_under_sqlite_root(self):
        config = {'WEEWX_ROOT': '/home/weewx',
                  'DatabaseTypes': {'SQLite': {'SQLITE_ROOT': 'archive'}}}
        assert wxskyfield.get_sat_dir(config) == '/home/weewx/archive/wxskyfield'
        # An absolute SQLITE_ROOT wins the join, as in weewx's own manager.
        config['DatabaseTypes']['SQLite']['SQLITE_ROOT'] = '/var/lib/weewx'
        assert wxskyfield.get_sat_dir(config) == '/var/lib/weewx/wxskyfield'

    def test_sat_dir_mysql_fallback(self):
        """A MySQL-only station has no SQLITE_ROOT; the cache falls back
        to WEEWX_ROOT."""
        config = {'WEEWX_ROOT': '/home/weewx'}
        assert wxskyfield.get_sat_dir(config) == '/home/weewx/./wxskyfield'

    def test_sat_norad_spellings(self, sky):
        """sat_<norad> is only an alternate spelling for a LISTED
        satellite -- never a trigger to serve (and so fetch) an unlisted
        one, unlike hip_<n>, whose catalog is already on disk."""
        assert sky.sat_norad('iss') == ISS_NORAD
        assert sky.sat_norad('sat_25544') == ISS_NORAD
        assert sky.sat_norad('sat_20580') is None
        assert sky.sat_norad('mars') is None

    def test_tle_lines_named(self):
        name, l1, l2 = wxskyfield.tle_lines(read_tle(ISS_NORAD), ISS_NORAD)
        assert name == 'ISS (ZARYA)'
        assert l1.startswith('1 25544U') and l2.startswith('2 25544')

    def test_tle_lines_nameless(self):
        bare = '\n'.join(read_tle(ISS_NORAD).splitlines()[1:])
        name, _l1, _l2 = wxskyfield.tle_lines(bare, ISS_NORAD)
        assert name == 'NORAD 25544'

    def test_tle_lines_rejects_wrong_satellite(self):
        with pytest.raises(ValueError, match='48274, not 25544'):
            wxskyfield.tle_lines(read_tle(TIANGONG_NORAD), ISS_NORAD)

    def test_tle_lines_rejects_non_tle(self):
        # CelesTrak's miss answer, and a truncated download.
        with pytest.raises(ValueError):
            wxskyfield.tle_lines('No GP data found', ISS_NORAD)
        with pytest.raises(ValueError):
            wxskyfield.tle_lines(read_tle(ISS_NORAD).splitlines()[1], ISS_NORAD)


def read_comet_file() -> str:
    """The archived CometEls.txt excerpt: 1P, 10P, 220P, C/1947 X1-B,
    C/1995 O1 verbatim (captured 2026-08-08, epochs 20260808), plus one
    FABRICATED always-bright comet, C/9999 Z9: the orbit of P/1999 XN120
    (alt 72 degrees at TIME_TS from Palo Alto) with g forced to -9.0, so
    its magnitude is naked-eye bright regardless of geometry -- the dome's
    solid-marker state (geosat-90000 spirit)."""
    with open(os.path.join(SAT_DATA_DIR, wxskyfield.COMET_FILE)) as f:
        return f.read()


class TestCometParsing:
    """CometEls.txt row parsing, designation matching, and the [[Comets]]
    config section."""

    def test_designation_keys(self):
        for readable, key in (
                ('1P/Halley', '1P'),
                ('12P/Pons-Brooks', '12P'),
                ('220P/McNaught', '220P'),
                ('73P-B/Schwassmann-Wachmann', '73P-B'),
                ('C/1995 O1 (Hale-Bopp)', 'C/1995 O1'),
                ('C/1947 X1-B (Southern comet)', 'C/1947 X1-B'),
                ('C/2023 A3 (Tsuchinshan-ATLAS)', 'C/2023 A3')):
            assert wxskyfield.comet_designation_key(readable) == key

    def test_normalization_is_case_and_whitespace_only(self):
        assert wxskyfield.normalize_comet_designation('  c/2023   a3 ') == 'C/2023 A3'
        assert wxskyfield.normalize_comet_designation('12p') == '12P'

    def test_parse_rows_from_archive(self):
        rows = [wxskyfield.parse_comet_row(line)
                for line in read_comet_file().splitlines()]
        by_key = {row.designation_key: row for row in rows}
        halley = by_key['1P']
        assert halley.designation_full == '1P/Halley'
        assert halley.e == pytest.approx(0.968018)
        assert halley.q == pytest.approx(0.571147)
        assert (halley.peri_year, halley.peri_month) == (2061, 8)
        assert halley.g == pytest.approx(5.5)
        assert halley.k == pytest.approx(3.2)
        # The archive was captured 2026-08-08; every row carries that epoch.
        assert halley.epoch_ts == pytest.approx(1786147200.0)  # 2026-08-08 UTC
        assert 'C/1947 X1-B' in by_key          # the fragment survives intact
        assert by_key['C/9999 Z9'].g == pytest.approx(-9.0)

    def test_blank_magnitude_fields_parse_as_none(self):
        line = read_comet_file().splitlines()[0]
        blanked = line[:91] + '    ' + line[95:96] + '    ' + line[100:]
        row = wxskyfield.parse_comet_row(blanked)
        assert row.g is None and row.k is None

    def test_malformed_row_raises(self):
        with pytest.raises(ValueError):
            wxskyfield.parse_comet_row('garbage')
        line = read_comet_file().splitlines()[0]
        with pytest.raises(ValueError):
            wxskyfield.parse_comet_row(line[:30] + 'x.xxxxxxx' + line[39:])

    def test_parse_comets(self):
        parsed = wxskyfield.parse_comets(
            {'Comets': {'Halley': '1p', 'hale_bopp': 'C/1995  O1'}}, {})
        assert parsed == {'halley': '1P', 'hale_bopp': 'C/1995 O1'}

    def test_parse_comets_refuses_shadowing_names(self, caplog):
        """A name that is already an almanac tag -- including a configured
        satellite, which dispatches first -- would silently shadow the
        comet, so it is refused loudly."""
        with caplog.at_level(logging.ERROR, logger=wxskyfield.log.name):
            parsed = wxskyfield.parse_comets(
                {'Comets': {'mars': '1P', 'rigel': '2P', 'hip_87937': '3P',
                            'sat_25544': '4P', 'sun': '5P', 'earth': '6P',
                            'iss': '7P', 'halley': '1P', 'empty': '  '}},
                {'iss': ISS_NORAD})
        assert parsed == {'halley': '1P'}
        assert caplog.text.count('already an almanac tag') == 7
        assert 'empty' in caplog.text

    def test_missing_section_means_no_comets(self):
        assert wxskyfield.parse_comets({}, {}) == {}
        assert wxskyfield.parse_comets({'Comets': {}}, {}) == {}


COMETS = {'halley': '1P', 'hale_bopp': 'C/1995 O1', 'bright': 'C/9999 Z9',
          'mcnaught': '220P'}


@pytest.fixture(scope='module')
def comet_sky():
    s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                       comets=dict(COMETS), comet_dir=SAT_DATA_DIR)
    assert s.is_valid()
    return s


class TestCometElements:
    """Sky's comet element loading: lazy, mtime-invalidated, the honest
    no-elements states, and the Horizons-pinned Kepler path."""

    COMETS = COMETS

    def make_sky(self, comet_dir, comets=None):
        return wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                              comets=dict(comets or self.COMETS),
                              comet_dir=str(comet_dir))

    def test_elements_for_halley(self, comet_sky):
        elements = comet_sky.comet_elements('halley')
        assert elements is not None
        vector, row, mtime = elements
        assert row.designation_full == '1P/Halley'
        assert mtime == os.stat(comet_sky.comet_path()).st_mtime
        # The vector is memoized per designation until the file changes.
        again = comet_sky.comet_elements('halley')
        assert again is not None and again[0] is vector

    def test_horizons_pin(self, comet_sky):
        """Topocentric place of 1P and Hale-Bopp at TIME_TS from Palo Alto
        against JPL Horizons (queried 2026-08-08; elements epoch 20260808,
        so TIME_TS is 14 months of two-body propagation).  This is the
        regression pin for skyfield's PRIVATE _KeplerOrbit._from_periapsis:
        if a Skyfield upgrade moves or changes it, this fails loudly."""
        t = comet_sky.ts.utc(2025, 6, 21, 19)     # TIME_TS
        observer = comet_sky.earth + skyfield.api.wgs84.latlon(
            LATITUDE, LONGITUDE, elevation_m=ALTITUDE_M)
        pins = {
            # name: (astro RA deg, astro dec deg, az deg, alt deg, delta AU, r AU)
            'halley':    (123.15625, 3.52749, 113.785, 32.803, 35.9078, 35.1064),
            'hale_bopp': (346.47053, -84.88071, 186.567, -36.882, 49.2601, 49.6911),
        }
        for name, (p_ra, p_dec, p_az, p_alt, p_delta, p_r) in pins.items():
            elements = comet_sky.comet_elements(name)
            assert elements is not None
            vector = elements[0]
            ra, dec, _ = comet_sky.earth.at(t).observe(vector).radec()
            assert ra._degrees == pytest.approx(p_ra, abs=0.05)
            assert dec.degrees == pytest.approx(p_dec, abs=0.05)
            alt, az, delta = observer.at(t).observe(vector).apparent().altaz()
            assert az.degrees == pytest.approx(p_az, abs=0.05)
            assert alt.degrees == pytest.approx(p_alt, abs=0.05)
            assert delta.au == pytest.approx(p_delta, abs=0.01)
            _, _, r = comet_sky.sun.at(t).observe(vector).radec()
            assert r.au == pytest.approx(p_r, abs=0.01)

    def test_mtime_change_reparses(self, tmp_path):
        shutil.copy(os.path.join(SAT_DATA_DIR, wxskyfield.COMET_FILE),
                    str(tmp_path / wxskyfield.COMET_FILE))
        s = self.make_sky(tmp_path)
        elements = s.comet_elements('halley')
        assert elements is not None
        old_q = elements[1].q
        lines = read_comet_file().splitlines(keepends=True)
        lines[0] = lines[0][:30] + ' 1.571147' + lines[0][39:]
        with open(str(tmp_path / wxskyfield.COMET_FILE), 'w') as f:
            f.writelines(lines)
        os.utime(str(tmp_path / wxskyfield.COMET_FILE),
                 (time.time() + 10, time.time() + 10))
        refreshed = s.comet_elements('halley')
        assert refreshed is not None
        assert refreshed[1].q == pytest.approx(1.571147)
        assert refreshed[1].q != pytest.approx(old_q)

    def test_vanishing_row_serves_none(self, tmp_path):
        lines = [line for line in read_comet_file().splitlines(keepends=True)
                 if not line[102:158].startswith('1P/')]
        with open(str(tmp_path / wxskyfield.COMET_FILE), 'w') as f:
            f.writelines(lines)
        s = self.make_sky(tmp_path)
        assert s.comet_elements('halley') is None
        assert s.comet_elements('hale_bopp') is not None

    def test_malformed_row_disables_only_itself(self, tmp_path, caplog):
        lines = read_comet_file().splitlines(keepends=True)
        lines[0] = lines[0][:30] + 'x.xxxxxxx' + lines[0][39:]
        with open(str(tmp_path / wxskyfield.COMET_FILE), 'w') as f:
            f.writelines(lines)
        s = self.make_sky(tmp_path)
        with caplog.at_level(logging.ERROR, logger=wxskyfield.log.name):
            assert s.comet_elements('halley') is None
            assert s.comet_elements('hale_bopp') is not None
        assert '1P' in caplog.text

    def test_missing_file_serves_none(self, tmp_path):
        s = self.make_sky(tmp_path)
        assert s.comet_elements('halley') is None
        assert s.comet_elements('unconfigured') is None

    def test_note_comet_usable_once_per_crossing(self, tmp_path, caplog):
        s = self.make_sky(tmp_path)
        with caplog.at_level(logging.INFO, logger=wxskyfield.log.name):
            s.note_comet_usable('halley', False)
            s.note_comet_usable('halley', False)
            s.note_comet_usable('halley', True)
        assert caplog.text.count('will report N/A') == 1
        assert 'halley (1P)' in caplog.text
        assert caplog.text.count('has elements again') == 1


# Every attribute of the comet tag surface, with the value shape the
# no-elements state must serve for it: 'time'/'vh' -> empty ValueHelper
# (raw None), 'none' -> plain None, 'zero' -> 0.0.
COMET_SURFACE_SHAPES = [
    ('rise', 'time'), ('set', 'time'), ('transit', 'time'),
    ('next_rising', 'time'), ('next_setting', 'time'),
    ('previous_rising', 'time'), ('previous_setting', 'time'),
    ('next_transit', 'time'), ('previous_transit', 'time'),
    ('next_antitransit', 'time'), ('previous_antitransit', 'time'),
    ('perihelion', 'time'),
    ('azimuth', 'vh'), ('altitude', 'vh'), ('topo_ra', 'vh'), ('topo_dec', 'vh'),
    ('astro_ra', 'vh'), ('astro_dec', 'vh'), ('geo_ra', 'vh'), ('geo_dec', 'vh'),
    ('hour_angle', 'vh'), ('hlongitude', 'vh'), ('hlatitude', 'vh'),
    ('elongation', 'vh'), ('illumination', 'vh'),
    ('distance', 'vh'), ('distance_from_sun', 'vh'), ('visible', 'vh'),
    ('elements_epoch', 'vh'), ('elements_age', 'vh'),
    ('az', 'none'), ('alt', 'none'), ('ra', 'none'), ('dec', 'none'),
    ('a_ra', 'none'), ('a_dec', 'none'), ('g_ra', 'none'), ('g_dec', 'none'),
    ('ha', 'none'), ('hlong', 'none'), ('hlat', 'none'), ('hlon', 'none'),
    ('elong', 'none'), ('mag', 'none'), ('phase', 'none'), ('moon_phase', 'none'),
    ('earth_distance', 'none'), ('sun_distance', 'none'),
    ('circumpolar', 'none'), ('neverup', 'none'),
    ('constellation', 'none'), ('constellation_abbr', 'none'),
    ('size', 'zero'), ('radius', 'zero'),
]


class TestCometBinder:
    """The comet tag surface: the normal orb path on a sun+Kepler-orbit
    vector, pinned at TIME_TS; the honest no-elements state; the cache
    pin; and the no-PyEphem fence."""

    def test_halley_at_time_ts(self, almanac):
        """Pinned against the live evaluation verified against JPL
        Horizons (see TestCometElements.test_horizons_pin): Halley near
        aphelion, 35.9 AU out in Hydra, telescope-faint."""
        h = almanac.halley
        assert h.alt == pytest.approx(32.829, abs=0.05)
        assert h.az == pytest.approx(113.786, abs=0.05)
        assert h.a_ra == pytest.approx(123.155, abs=0.05)
        assert h.a_dec == pytest.approx(3.528, abs=0.05)
        assert h.mag == pytest.approx(25.64, abs=0.05)
        assert h.earth_distance == pytest.approx(35.9066, abs=0.01)
        assert h.sun_distance == pytest.approx(35.1052, abs=0.01)
        assert h.distance.raw == pytest.approx(h.earth_distance, abs=1e-9)
        assert h.distance_from_sun.raw == pytest.approx(h.sun_distance, abs=1e-9)
        assert h.elong == pytest.approx(37.44, abs=0.05)
        assert h.phase == pytest.approx(99.99, abs=0.05)
        assert str(h.constellation) == 'Hydra'
        assert not h.circumpolar and not h.neverup
        assert h.rise.raw == pytest.approx(1750522117, abs=60)
        assert h.visible.raw == pytest.approx(44695, abs=60)
        assert h.size == 0.0 and h.radius_size.raw == 0.0
        assert h.label == 'Halley'
        # elements_epoch is the archive's capture date (2026-08-08), in the
        # almanac's FUTURE at TIME_TS: the age diagnostic is honestly
        # negative, not clamped.
        assert almanac.halley.elements_epoch.raw == pytest.approx(1786147200, abs=86400)
        assert almanac.halley.elements_age.raw < 0

    def test_fabricated_bright_comet(self, almanac):
        assert almanac.bright.alt == pytest.approx(72.4, abs=0.1)
        assert almanac.bright.mag == pytest.approx(-3.21, abs=0.05)

    def test_perihelion(self, almanac):
        """The time of perihelion passage straight from the MPC row -- a
        TT date; future for Halley (2061), past for Hale-Bopp (1997),
        under a year ahead for 220P (2026-06-14): the countdown chip's
        three cases."""
        assert almanac.halley.perihelion.raw == pytest.approx(2890316269, abs=60)
        assert almanac.hale_bopp.perihelion.raw == pytest.approx(859596458, abs=60)
        assert almanac.mcnaught.perihelion.raw == pytest.approx(1781405334, abs=60)

    def test_separation_with_comet(self, almanac):
        sep = almanac.separation(almanac.halley, almanac.mars)
        assert float(sep) == pytest.approx(0.5612, abs=0.001)

    @pytest.mark.parametrize('attr,shape', COMET_SURFACE_SHAPES)
    def test_no_elements_serves_na(self, tmp_path, attr, shape):
        """A configured comet with no elements (missing file here; a
        vanished designation is the same state) serves the honest N/A
        shape for the ENTIRE surface -- never a wrong number, never a
        per-tag error."""
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                           comets={'halley': '1P'}, comet_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            value = getattr(alm.halley, attr)
            if shape in ('time', 'vh'):
                assert value.raw is None
                assert str(value).strip() in ('N/A', '')
            elif shape == 'none':
                assert value is None
            else:
                assert value == 0.0

    def test_no_elements_visible_change(self, tmp_path):
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                           comets={'halley': '1P'}, comet_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert alm.halley.visible_change().raw is None

    def test_element_refresh_invalidates_caches(self, tmp_path):
        """_DAY_CACHE survives across report cycles, and its keys once
        carried only the body NAME: a CometEls refresh would keep serving
        the old elements' rise time until the day rolled.  cache_name
        folds the file mtime in, so a refresh moves the answer at once."""
        shutil.copy(os.path.join(SAT_DATA_DIR, wxskyfield.COMET_FILE),
                    str(tmp_path / wxskyfield.COMET_FILE))
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                           comets={'halley': '1P'}, comet_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            first = alm.halley.rise.raw
            assert first is not None
            # Swing the ascending node 90 degrees: a different place in
            # the sky, a different rise time.
            lines = read_comet_file().splitlines(keepends=True)
            assert lines[0][102:158].startswith('1P/')
            lines[0] = lines[0][:61] + '149.3098' + lines[0][69:]
            with open(str(tmp_path / wxskyfield.COMET_FILE), 'w') as f:
                f.writelines(lines)
            os.utime(str(tmp_path / wxskyfield.COMET_FILE),
                     (time.time() + 10, time.time() + 10))
            second = alm.halley.rise.raw
            assert second is not None
            assert abs(second - first) > 60

    def test_pyephem_never_serves_a_comet(self, almanac):
        """The fence: attributes outside the comet surface raise a clean
        per-tag AttributeError even with PyEphem installed -- PyEphem has
        no comets, and a silent fall-through would answer with garbage
        (or another body entirely)."""
        for attr in ('next_pass', 'next_visible_pass', 'sunlit',
                     'moon_fullness', 'a_epoch', 'libration_lat'):
            with pytest.raises(AttributeError):
                getattr(almanac.halley, attr)

    def test_comet_surface_whole_without_pyephem(self, skyfield_only_almanac):
        assert skyfield_only_almanac.halley.mag == pytest.approx(25.64, abs=0.05)
        with pytest.raises(AttributeError):
            skyfield_only_almanac.halley.next_pass


class FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestSatelliteFetcher:
    """The element fetcher and the service's refresh scheduling.  No test
    here ever touches the network or sleeps: downloads are monkeypatched
    and staleness comes from synthetic mtimes."""

    def make_service(self, tmp_path, **skyfield_options):
        options = dict(Satellites={'iss': str(ISS_NORAD)})
        options.update(skyfield_options)
        config = make_config(**options)
        config['DatabaseTypes'] = {'SQLite': {'SQLITE_ROOT': str(tmp_path)}}
        with saved_almanacs():
            engine = StubEngine()
            service = wxskyfield.WxSkyfield(engine, config)
        return engine, service

    def test_fetch_writes_validated_payload(self, tmp_path, monkeypatch):
        payload = read_tle(ISS_NORAD)
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen['url'] = request.full_url
            seen['ua'] = request.get_header('User-agent')
            return FakeResponse(payload.encode('ascii'))

        monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen', fake_urlopen)
        path = str(tmp_path / 'wxskyfield_sat_25544.tle')
        wxskyfield.fetch_satellite_elements(ISS_NORAD, path)
        with open(path) as f:
            assert f.read() == payload
        assert not os.path.exists(path + '.tmp')
        # The wire format: bare gp.php?CATNR returns CSV; FORMAT=TLE is
        # required.  And the identifying User-Agent CelesTrak asks for.
        assert 'CATNR=25544' in seen['url'] and 'FORMAT=TLE' in seen['url']
        assert seen['ua'] == wxskyfield.SAT_USER_AGENT
        assert wxskyfield.WXSKYFIELD_VERSION in seen['ua']
        assert 'github.com/chaunceygardiner/weewx-skyfield' in seen['ua']

    def test_fetch_failure_keeps_old_file(self, tmp_path, monkeypatch):
        old = read_tle(ISS_NORAD)
        path = str(tmp_path / 'wxskyfield_sat_25544.tle')
        with open(path, 'w') as f:
            f.write(old)

        def fake_urlopen(request, timeout=None):
            raise OSError('network unreachable')

        monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen', fake_urlopen)
        with pytest.raises(OSError):
            wxskyfield.fetch_satellite_elements(ISS_NORAD, path)
        with open(path) as f:
            assert f.read() == old
        assert not os.path.exists(path + '.tmp')

    def test_fetch_corrupt_payload_keeps_old_file(self, tmp_path, monkeypatch):
        """The payload is validated BEFORE the write: a CSV answer (the
        FORMAT-less wire format), an HTML error page, or a miss answer
        must never replace working elements with garbage."""
        old = read_tle(ISS_NORAD)
        path = str(tmp_path / 'wxskyfield_sat_25544.tle')
        with open(path, 'w') as f:
            f.write(old)
        for payload in (b'OBJECT_NAME,OBJECT_ID,EPOCH\nISS (ZARYA),1998-067A,x\n',
                        b'No GP data found',
                        read_tle(TIANGONG_NORAD).encode('ascii')):
            monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen',
                                lambda request, timeout=None, p=payload: FakeResponse(p))
            with pytest.raises(ValueError):
                wxskyfield.fetch_satellite_elements(ISS_NORAD, path)
            with open(path) as f:
                assert f.read() == old
            assert not os.path.exists(path + '.tmp')

    def test_comet_fetch_writes_validated_payload(self, tmp_path, monkeypatch):
        payload = read_comet_file()
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen['url'] = request.full_url
            seen['ua'] = request.get_header('User-agent')
            return FakeResponse(payload.encode('ascii'))

        monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen', fake_urlopen)
        path = str(tmp_path / wxskyfield.COMET_FILE)
        wxskyfield.fetch_comet_elements(path)
        with open(path) as f:
            assert f.read() == payload
        assert not os.path.exists(path + '.tmp')
        assert seen['url'] == wxskyfield.COMET_URL
        assert seen['ua'] == wxskyfield.SAT_USER_AGENT

    def test_comet_fetch_failure_keeps_old_file(self, tmp_path, monkeypatch):
        old = read_comet_file()
        path = str(tmp_path / wxskyfield.COMET_FILE)
        with open(path, 'w') as f:
            f.write(old)

        def fake_urlopen(request, timeout=None):
            raise OSError('network unreachable')

        monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen', fake_urlopen)
        with pytest.raises(OSError):
            wxskyfield.fetch_comet_elements(path)
        with open(path) as f:
            assert f.read() == old
        assert not os.path.exists(path + '.tmp')

    def test_comet_fetch_corrupt_payload_keeps_old_file(self, tmp_path, monkeypatch):
        """Validated BEFORE the write: an HTML error page or empty answer
        must never replace a working CometEls file.  The validation asks
        only for one parseable row anywhere -- never the configured
        designations: a vanishing row is a tag-time concern."""
        old = read_comet_file()
        path = str(tmp_path / wxskyfield.COMET_FILE)
        with open(path, 'w') as f:
            f.write(old)
        for payload in (b'<html><body>503</body></html>', b''):
            monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen',
                                lambda request, timeout=None, p=payload: FakeResponse(p))
            with pytest.raises(ValueError):
                wxskyfield.fetch_comet_elements(path)
            with open(path) as f:
                assert f.read() == old
            assert not os.path.exists(path + '.tmp')

    def test_no_network_at_startup(self, tmp_path, monkeypatch):
        """Sky.__init__ (and the whole service constructor) never touches
        the network: elements load lazily at tag time, and the first
        fetch waits for the engine's STARTUP event, on a worker thread --
        the constructor only binds."""
        def boom(*args, **kwargs):
            raise AssertionError('network access at startup')

        monkeypatch.setattr(wxskyfield.urllib.request, 'urlopen', boom)
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           satellites=dict(SATELLITES), sat_dir=SAT_DATA_DIR)
        assert s.is_valid()
        assert s.satellite_elements(ISS_NORAD) is not None
        self.make_service(tmp_path)

    def test_service_binds_startup_and_archive_events(self, tmp_path):
        """STARTUP is what makes a just-added satellite live within
        seconds of a restart instead of one archive interval in -- a
        satellite configured and restarted into showed N/A tags for
        minutes before this binding existed."""
        engine, _service = self.make_service(tmp_path)
        assert engine.bound == [weewx.STARTUP, weewx.NEW_ARCHIVE_RECORD]

    def test_downloads_off_binds_nothing(self, tmp_path):
        """satellite_downloads = false is user-supplied-file mode: the
        tags still serve whatever TLEs the user maintains in the cache
        directory; the service just never fetches."""
        engine, service = self.make_service(tmp_path, satellite_downloads='false')
        assert engine.bound == []
        assert service.sky.satellites == {'iss': ISS_NORAD}

    def test_no_satellites_binds_nothing(self, tmp_path):
        engine, _service = self.make_service(tmp_path, Satellites={})
        assert engine.bound == []

    def test_stale_satellites_age_driven(self, tmp_path):
        """Missing file: maximally stale, due at the first archive cycle
        (offline install, or a satellite added to the config later).
        Fresh mtime: not due.  Older than the cadence: due -- age-driven,
        not schedule-driven, so a weewxd started after a long stop
        refreshes immediately."""
        _engine, service = self.make_service(tmp_path)
        now = time.time()
        assert service.stale_satellites(now) == [ISS_NORAD]
        path = service.sky.sat_path(ISS_NORAD)
        os.makedirs(service.sky.sat_dir, exist_ok=True)
        with open(path, 'w') as f:
            f.write(read_tle(ISS_NORAD))
        os.utime(path, (now, now))
        assert service.stale_satellites(now) == []
        os.utime(path, (now - wxskyfield.SAT_REFRESH_SECS - 1,
                        now - wxskyfield.SAT_REFRESH_SECS - 1))
        assert service.stale_satellites(now) == [ISS_NORAD]
        # A satellite inside its failure backoff window is skipped.
        service._sat_retry_ts[ISS_NORAD] = now + 60
        assert service.stale_satellites(now) == []

    def test_backoff_doubles_and_caps(self, tmp_path, monkeypatch):
        """On failure, retry SOONER than the normal cadence -- five
        minutes, doubling per consecutive failure, capped at the three-
        hour cadence -- so a recovered network refreshes quickly and
        CelesTrak is never hammered.  Success resets the backoff."""
        _engine, service = self.make_service(tmp_path)

        def failing(norad, path):
            raise OSError('offline')

        monkeypatch.setattr(wxskyfield, 'fetch_satellite_elements', failing)
        delays = []
        for _ in range(8):
            before = time.time()
            service._fetch_worker([ISS_NORAD])
            delays.append(service._sat_retry_ts[ISS_NORAD] - before)
        assert delays[0] == pytest.approx(wxskyfield.SAT_RETRY_BASE_SECS, abs=5)
        assert delays[1] == pytest.approx(2 * wxskyfield.SAT_RETRY_BASE_SECS, abs=5)
        assert max(delays) <= wxskyfield.SAT_REFRESH_SECS + 5
        assert delays[-1] == pytest.approx(wxskyfield.SAT_REFRESH_SECS, abs=5)

        def succeeding(norad, path):
            with open(path, 'w') as f:
                f.write(read_tle(norad))

        monkeypatch.setattr(wxskyfield, 'fetch_satellite_elements', succeeding)
        service._fetch_worker([ISS_NORAD])
        assert ISS_NORAD not in service._sat_retry_ts
        assert ISS_NORAD not in service._sat_retry_delay
        assert os.path.exists(service.sky.sat_path(ISS_NORAD))

    def test_refresh_fetches_stale_on_worker_thread(self, tmp_path, monkeypatch):
        """The one callback serves both bindings: at STARTUP the cache is
        missing or stale and this is the immediate fetch; at every
        NEW_ARCHIVE_RECORD it is the three-hour cadence."""
        _engine, service = self.make_service(tmp_path)
        fetched = []
        monkeypatch.setattr(wxskyfield, 'fetch_satellite_elements',
                            lambda norad, path: fetched.append(norad))
        service.refresh_satellite_elements(None)
        assert service._sat_thread is not None
        service._sat_thread.join(10)
        assert not service._sat_thread.is_alive()
        assert fetched == [ISS_NORAD]

    def test_refresh_skips_fresh_elements(self, tmp_path, monkeypatch):
        """A normal restart with fresh cache files spawns no thread and
        fetches nothing -- the STARTUP binding never hammers CelesTrak."""
        _engine, service = self.make_service(tmp_path)
        path = service.sky.sat_path(ISS_NORAD)
        os.makedirs(service.sky.sat_dir, exist_ok=True)
        with open(path, 'w') as f:
            f.write(read_tle(ISS_NORAD))
        monkeypatch.setattr(wxskyfield, 'fetch_satellite_elements',
                            lambda norad, p: pytest.fail('fetched fresh elements'))
        service.refresh_satellite_elements(None)
        assert service._sat_thread is None


class TestMeteorShowers:
    """The IMO major-shower table, the solar-longitude peak solver, and
    the two tags.  Peaks are COMPUTED from the sun's apparent ecliptic
    longitude of date, so the pins are ephemeris facts, not calendar
    lookups."""

    def test_solar_longitude_anchor(self, almanac):
        """lambda = 180 must land on skyfield's own September equinox to
        the second: the solver speaks equinox-of-date solar longitude,
        the convention meteor astronomy states peaks in."""
        atype = weewx.almanac.almanacs[0]
        eq = almanac.next_equinox.raw
        lam = atype.find_sun_longitude(180.0, eq - 5 * 86400, eq + 5 * 86400)
        assert lam == pytest.approx(eq, abs=1.0)

    def test_next_at_fixture(self, almanac):
        s = almanac.next_meteor_shower
        assert s.name == 'Southern Delta Aquariids'
        assert s.key == 'delta_aquariids'
        # lambda 126.9 in 2025: July 29, 18:44 UT.
        assert s.peak.raw == pytest.approx(1753814687, abs=120)
        assert s.zhr == 25 and s.parent == '96P/Machholz'
        assert isinstance(s.radiant_alt, float) and isinstance(s.radiant_az, float)
        # No [[MeteorShowers]] table on this almanac: label falls back
        # to the stable English name.
        assert s.label == 'Southern Delta Aquariids'

    def test_perseids_peak(self, almanac):
        """lambda 140.0 in 2025 lands August 12, 11:01 UT -- the
        ephemeris truth of the IMO anchor."""
        aug = almanac(almanac_time=1754980000)      # 2025-08-11 22:06 PDT
        s = aug.next_meteor_shower
        assert s.name == 'Perseids'
        assert s.key == 'perseids'
        assert s.peak.raw == pytest.approx(1754996504, abs=120)
        assert s.zhr == 100 and s.parent == '109P/Swift-Tuttle'

    def test_active_showers(self, almanac):
        # June 21 (lambda ~90): quiet -- no major shower is active.
        assert almanac.active_meteor_showers == ()
        # Perseids week: the Perseids and the Southern Delta Aquariids
        # are both active, each carrying its own apparition's peak (the
        # Aquariids' already two weeks past -- still active, honestly).
        aug = almanac(almanac_time=1754980000)
        showers = {s.name: s for s in aug.active_meteor_showers}
        assert 'Perseids' in showers and 'Southern Delta Aquariids' in showers
        assert showers['Southern Delta Aquariids'].peak.raw < 1754980000
        for s in showers.values():
            assert s.peak.raw is not None

    def test_table_is_sane(self):
        """Twelve majors; every activity window holds its peak, nothing
        spans the March-equinox wrap, keys are unique and tag-safe."""
        assert len(wxskyfield.METEOR_SHOWERS) == 12
        keys = [s.key for s in wxskyfield.METEOR_SHOWERS]
        assert len(set(keys)) == 12
        for s in wxskyfield.METEOR_SHOWERS:
            assert s.start_lambda < s.peak_lambda < s.end_lambda
            assert 0.0 <= s.start_lambda and s.end_lambda <= 360.0
            assert 0 < s.zhr <= 200 and s.parent


class TestCometFetcher:
    """The comet element fetch scheduling: one file, scalar backoff, the
    same STARTUP + NEW_ARCHIVE_RECORD shape as the satellite refresher.
    Never touches the network."""

    def make_service(self, tmp_path, **skyfield_options):
        options = dict(Satellites={}, Comets={'halley': '1P'})
        options.update(skyfield_options)
        config = make_config(**options)
        config['DatabaseTypes'] = {'SQLite': {'SQLITE_ROOT': str(tmp_path)}}
        with saved_almanacs():
            engine = StubEngine()
            service = wxskyfield.WxSkyfield(engine, config)
        return engine, service

    def test_service_binds_startup_and_archive_events(self, tmp_path):
        engine, service = self.make_service(tmp_path)
        assert engine.bound == [weewx.STARTUP, weewx.NEW_ARCHIVE_RECORD]
        assert service.sky.comets == {'halley': '1P'}

    def test_downloads_off_binds_nothing(self, tmp_path):
        """comet_downloads = false is user-maintained-file mode: the tags
        still serve whatever CometEls file sits in the cache directory;
        the service just never fetches."""
        engine, service = self.make_service(tmp_path, comet_downloads='false')
        assert engine.bound == []
        assert service.sky.comets == {'halley': '1P'}

    def test_no_comets_binds_nothing(self, tmp_path):
        engine, _service = self.make_service(tmp_path, Comets={})
        assert engine.bound == []

    def test_comets_and_satellites_bind_independently(self, tmp_path):
        engine, _service = self.make_service(
            tmp_path, Satellites={'iss': str(ISS_NORAD)})
        assert engine.bound == [weewx.STARTUP, weewx.NEW_ARCHIVE_RECORD] * 2

    def test_comet_stale_age_driven(self, tmp_path):
        _engine, service = self.make_service(tmp_path)
        now = time.time()
        assert service.comet_stale(now)          # no file: maximally stale
        assert service.sky.comet_dir is not None
        os.makedirs(service.sky.comet_dir, exist_ok=True)
        path = service.sky.comet_path()
        with open(path, 'w') as f:
            f.write(read_comet_file())
        os.utime(path, (now, now))
        assert not service.comet_stale(now)
        os.utime(path, (now - wxskyfield.COMET_REFRESH_SECS - 1,
                        now - wxskyfield.COMET_REFRESH_SECS - 1))
        assert service.comet_stale(now)
        # Inside the failure backoff window: never due.
        service._comet_retry_ts = now + 60
        assert not service.comet_stale(now)

    def test_comet_backoff_doubles_and_caps(self, tmp_path, monkeypatch):
        _engine, service = self.make_service(tmp_path)

        def failing(path):
            raise OSError('offline')

        monkeypatch.setattr(wxskyfield, 'fetch_comet_elements', failing)
        delays = []
        for _ in range(12):
            before = time.time()
            service._comet_fetch_worker()
            delays.append(service._comet_retry_ts - before)
        assert delays[0] == pytest.approx(wxskyfield.COMET_RETRY_BASE_SECS, abs=5)
        assert delays[1] == pytest.approx(2 * wxskyfield.COMET_RETRY_BASE_SECS, abs=5)
        assert max(delays) <= wxskyfield.COMET_REFRESH_SECS + 5
        assert delays[-1] == pytest.approx(wxskyfield.COMET_REFRESH_SECS, abs=5)

        def succeeding(path):
            with open(path, 'w') as f:
                f.write(read_comet_file())

        monkeypatch.setattr(wxskyfield, 'fetch_comet_elements', succeeding)
        service._comet_fetch_worker()
        assert service._comet_retry_ts == 0.0
        assert os.path.exists(service.sky.comet_path())

    def test_refresh_fetches_on_worker_thread(self, tmp_path, monkeypatch):
        _engine, service = self.make_service(tmp_path)
        fetched = []
        monkeypatch.setattr(wxskyfield, 'fetch_comet_elements',
                            lambda path: fetched.append(path))
        service.refresh_comet_elements(None)
        assert service._comet_thread is not None
        service._comet_thread.join(10)
        assert fetched == [service.sky.comet_path()]
        # A fresh file is not refetched.
        with open(service.sky.comet_path(), 'w') as f:
            f.write(read_comet_file())
        service.refresh_comet_elements(None)
        if service._comet_thread is not None:
            service._comet_thread.join(10)
        assert fetched == [service.sky.comet_path()]


class TestSatellitePositions:
    """Topocentric satellite tags at the standard fixture.  SGP4 is pure
    math, so these pin like every other regression value."""

    def test_position_pins(self, almanac):
        iss = almanac.iss
        assert iss.alt == pytest.approx(-17.7318, abs=ANGLE_TOL)
        assert iss.az == pytest.approx(309.1526, abs=ANGLE_TOL)
        assert iss.ra == pytest.approx(303.6499, abs=ANGLE_TOL)
        assert iss.dec == pytest.approx(16.9973, abs=ANGLE_TOL)
        assert raw(iss.distance, 'km') == pytest.approx(5004.9, abs=1.0)
        assert iss.sunlit is True

    def test_value_helper_forms(self, almanac):
        assert raw(almanac.iss.altitude, 'degree_angle') == pytest.approx(-17.7318, abs=ANGLE_TOL)
        assert raw(almanac.iss.azimuth, 'degree_compass') == pytest.approx(309.1526, abs=ANGLE_TOL)
        assert raw(almanac.iss.topo_ra, 'degree_compass') == pytest.approx(303.6499, abs=ANGLE_TOL)
        assert raw(almanac.iss.topo_dec, 'degree_angle') == pytest.approx(16.9973, abs=ANGLE_TOL)
        assert almanac.iss.azimuth.ordinal_compass() == 'NW'

    def test_tiangong_pins(self, almanac):
        tg = almanac.tiangong
        assert tg.alt == pytest.approx(-78.9339, abs=ANGLE_TOL)
        assert tg.az == pytest.approx(254.9652, abs=ANGLE_TOL)
        assert raw(tg.distance, 'km') == pytest.approx(12911.4, abs=1.0)
        assert tg.sunlit is False

    def test_sat_number_is_alternate_spelling(self, almanac):
        assert almanac.sat_25544.alt == almanac.iss.alt
        assert raw(almanac.sat_25544.next_pass.rise, 'unix_epoch') \
            == raw(almanac.iss.next_pass.rise, 'unix_epoch')

    def test_unlisted_sat_number_raises(self, almanac):
        # The config list IS the fetch list: sat_<n> never serves an
        # unlisted satellite (unlike hip_<n>, whose catalog is on disk).
        with pytest.raises(AttributeError):
            almanac.sat_20580.alt

    def test_unsupported_attributes_raise(self, almanac):
        """A satellite's tag surface is its own: no magnitude (models are
        hand-wavy; sunlit + max_altitude are the honest answer), no
        planet verbs, no PyEphem fallback."""
        for attr in ('mag', 'visible', 'constellation', 'phase',
                     'earth_distance', 'moon_fullness', 'a_epoch'):
            with pytest.raises(AttributeError):
                getattr(almanac.iss, attr)

    def test_name_and_label(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter(),
                                        texts={'iss': 'ISS'})
            assert alm.iss.label == 'ISS'
            assert alm.tiangong.label == 'Tiangong'
            assert alm.iss.name == 'Iss'

    def test_separation_takes_coordinate_path(self, almanac):
        """A satellite binder cannot take separation's exact-vector path
        (skyfield only observe()s from the barycenter); the coordinate
        path must serve it instead of raising ValueError."""
        sep = almanac.separation(almanac.iss, almanac.mars)
        assert 0.0 <= sep.degrees <= 180.0
        sep2 = almanac.separation(almanac.mars, almanac.iss)
        assert sep2.degrees == pytest.approx(sep.degrees, abs=0.01)


class TestSatellitePasses:
    """The next_pass family, per the settled semantics: geometric horizon
    (default 0, the almanac's horizon argument), the 7-day element-
    validity search window, whole-pass visibility sampling against a -6
    degree dark sky, and the 10-degree go-watch bar for the visible
    variant."""

    def test_next_pass_pins(self, almanac):
        p = almanac.iss.next_pass
        assert raw(p.rise, 'unix_epoch') == pytest.approx(1750532794.085, abs=1.0)
        assert raw(p.culmination, 'unix_epoch') == pytest.approx(1750533111.680, abs=1.0)
        assert raw(p.set, 'unix_epoch') == pytest.approx(1750533427.069, abs=1.0)
        assert raw(p.max_altitude, 'degree_angle') == pytest.approx(35.54, abs=ANGLE_TOL)
        assert raw(p.duration, 'second') == pytest.approx(633.0, abs=2.0)
        # A midday pass: geometrically fine, invisible (the sky is bright).
        assert p.visible is False
        assert p.rise_azimuth.ordinal_compass() == 'WNW'
        assert p.culmination_azimuth.ordinal_compass() == 'SW'
        assert p.set_azimuth.ordinal_compass() == 'SSE'

    def test_next_visible_pass_pins(self, almanac):
        """The next VISIBLE pass skips ahead to the next morning's dark-
        sky pass (03:11 local): sunlit satellite, observer past civil
        dusk, culmination over the 10-degree bar."""
        v = almanac.iss.next_visible_pass
        assert raw(v.rise, 'unix_epoch') == pytest.approx(1750587085.008, abs=1.0)
        assert raw(v.max_altitude, 'degree_angle') == pytest.approx(19.34, abs=ANGLE_TOL)
        assert raw(v.duration, 'second') == pytest.approx(592.0, abs=2.0)
        assert v.visible is True
        assert v.rise_azimuth.ordinal_compass() == 'SSW'
        assert v.culmination_azimuth.ordinal_compass() == 'SE'
        assert v.set_azimuth.ordinal_compass() == 'ENE'
        # It is a later pass than the unfiltered next_pass.
        assert raw(v.rise, 'unix_epoch') > raw(almanac.iss.next_pass.set, 'unix_epoch')

    def test_horizon_override(self, almanac):
        """$almanac(horizon=10) reuses the existing horizon argument; the
        pass shrinks to its above-10-degrees core."""
        p10 = almanac(horizon=10).iss.next_pass
        assert raw(p10.rise, 'unix_epoch') == pytest.approx(1750532925.215, abs=1.0)
        assert raw(p10.rise, 'unix_epoch') > raw(almanac.iss.next_pass.rise, 'unix_epoch')
        assert raw(p10.set, 'unix_epoch') < raw(almanac.iss.next_pass.set, 'unix_epoch')

    def test_in_progress_pass_is_next(self, sky, almanac):
        """rise <= now < set: the current pass IS next_pass -- the
        countdown rolls into 'overhead now, sets in three minutes'."""
        culmination_ts = raw(almanac.iss.next_pass.culmination, 'unix_epoch')
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            mid = weewx.almanac.Almanac(int(culmination_ts), LATITUDE, LONGITUDE,
                                        altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            p = mid.iss.next_pass
            assert raw(p.rise, 'unix_epoch') == pytest.approx(1750532794.085, abs=1.0)
            assert raw(p.rise, 'unix_epoch') < mid.time_ts < raw(p.set, 'unix_epoch')
            assert mid.iss.alt == pytest.approx(35.56, abs=ANGLE_TOL)

    def test_rise_transit_set_are_next_occurrence(self, almanac):
        """For a satellite these are the NEXT events from the almanac's
        time (transit meaning culmination), not the planets' anytime-
        today verbs: passes are minutes long and 'today's' is rarely the
        interesting one."""
        p = almanac.iss.next_pass
        assert raw(almanac.iss.rise, 'unix_epoch') == raw(p.rise, 'unix_epoch')
        assert raw(almanac.iss.transit, 'unix_epoch') == raw(p.culmination, 'unix_epoch')
        assert raw(almanac.iss.set, 'unix_epoch') == raw(p.set, 'unix_epoch')

    def test_whole_window_pass_stats(self, sky, almanac):
        """The pass list spans the element-validity window (a day before
        the epoch through the 7-day cutoff), every pass ordered, with the
        fixture's known census: visibility sampled over the WHOLE pass
        (rise, every culmination, set) and the 10-degree bar applied only
        by the visible variant."""
        binder = almanac.iss
        sat, epoch_ts = sky.satellite_elements(ISS_NORAD)
        passes = binder._sat_passes(sat, epoch_ts)
        assert len(passes) == 59
        assert sum(1 for p in passes if p['visible']) == 17
        assert sum(1 for p in passes
                   if p['visible'] and p['max_altitude'] >= 10.0) == 16
        for p in passes:
            assert epoch_ts - 86400 <= p['rise']
            assert p['set'] <= epoch_ts + wxskyfield.SAT_MAX_ELEMENT_AGE_SECS
            assert p['rise'] < p['culmination'] < p['set']

    def test_tiangong_honest_na(self, almanac):
        """Tiangong crosses Palo Alto's sky all week (a plain next_pass
        exists) but never sunlit-in-a-dark-sky above 10 degrees: the
        visible variant answers N/A, honestly, not with the least-bad
        pass."""
        p = almanac.tiangong.next_pass
        assert raw(p.rise, 'unix_epoch') == pytest.approx(1750534664.550, abs=1.0)
        assert raw(p.max_altitude, 'degree_angle') == pytest.approx(37.25, abs=ANGLE_TOL)
        v = almanac.tiangong.next_visible_pass
        assert raw(v.rise, 'unix_epoch') is None
        assert v.visible is None
        assert 'N/A' in str(v.rise)
        assert 'N/A' in str(v.max_altitude)

    def test_geostationary_never_rises(self):
        """The fabricated far-side geostationary satellite: find_events
        yields nothing, so every pass tag is N/A while the position tags
        stay live -- deterministic never-rises."""
        geo_sky = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'),
                                 load_stars=False,
                                 satellites={'geosat': GEOSAT_NORAD},
                                 sat_dir=SAT_DATA_DIR)
        assert geo_sky.is_valid()
        with saved_almanacs():
            assert wxskyfield.register_almanac(geo_sky)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert alm.geosat.alt < -50.0
            assert raw(alm.geosat.rise, 'unix_epoch') is None
            assert raw(alm.geosat.transit, 'unix_epoch') is None
            assert raw(alm.geosat.next_pass.rise, 'unix_epoch') is None
            assert alm.geosat.next_pass.visible is None

    def test_loopdata_chain_walk(self, almanac):
        """loopdata walks tag chains with plain getattr -- no Cheetah
        autocall -- so every pass attribute must be an already-computed
        value, never a method (the parallactic_angle lesson, baked in on
        day one)."""
        binder = getattr(almanac, 'iss')
        p = getattr(binder, 'next_pass')
        for attr in ('rise', 'culmination', 'set', 'max_altitude',
                     'rise_azimuth', 'culmination_azimuth', 'set_azimuth',
                     'duration'):
            value = getattr(p, attr)
            assert not callable(value), attr
            assert isinstance(value, weewx.units.ValueHelper), attr
        assert getattr(p, 'visible') is False


class TestSatelliteStale:
    """The unified no-usable-elements state: missing, unparseable, or
    epoch beyond the seven-day cutoff (measured against the almanac's
    time, never the file's mtime) all collapse to N/A -- never a silently
    wrong pass time.  Only the element diagnostics stay live: they are
    how a user sees WHY."""

    def test_element_diagnostics(self, almanac):
        assert raw(almanac.iss.elements_epoch, 'unix_epoch') \
            == pytest.approx(ISS_EPOCH_TS, abs=1.0)
        assert raw(almanac.iss.elements_age, 'second') \
            == pytest.approx(TIME_TS - ISS_EPOCH_TS, abs=1.0)

    def test_stale_elements_collapse_to_na(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            stale = weewx.almanac.Almanac(TIME_TS + 8 * 86400, LATITUDE, LONGITUDE,
                                          altitude=ALTITUDE_M,
                                          formatter=weewx.units.get_default_formatter())
            assert stale.iss.alt is None
            assert stale.iss.az is None
            assert stale.iss.sunlit is None
            assert raw(stale.iss.distance, 'km') is None
            assert raw(stale.iss.rise, 'unix_epoch') is None
            p = stale.iss.next_pass
            assert raw(p.rise, 'unix_epoch') is None
            assert p.visible is None
            assert 'N/A' in str(p.rise)
            # The diagnostics ignore the cutoff -- they explain the N/As.
            assert raw(stale.iss.elements_epoch, 'unix_epoch') \
                == pytest.approx(ISS_EPOCH_TS, abs=1.0)
            assert raw(stale.iss.elements_age, 'second') \
                == pytest.approx(8 * 86400 + (TIME_TS - ISS_EPOCH_TS), abs=1.0)

    def test_cutoff_warns_once_per_crossing(self, caplog):
        """The cutoff crossing logs ONE warning per satellite (not one
        per tag evaluation), and recovery logs once too."""
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           satellites=dict(SATELLITES), sat_dir=SAT_DATA_DIR)
        with saved_almanacs(), caplog.at_level(logging.INFO, logger=wxskyfield.log.name):
            assert wxskyfield.register_almanac(s)
            fresh = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                          formatter=weewx.units.get_default_formatter())
            assert fresh.iss.alt is not None
            stale = weewx.almanac.Almanac(TIME_TS + 8 * 86400, LATITUDE, LONGITUDE,
                                          altitude=ALTITUDE_M,
                                          formatter=weewx.units.get_default_formatter())
            assert stale.iss.alt is None
            assert stale.iss.sunlit is None
            assert raw(stale.iss.distance, 'km') is None
            assert caplog.text.count('no usable elements') == 1
            assert fresh.iss.az is not None
            assert caplog.text.count('usable elements again') == 1

    def test_corrupt_cache_costs_only_that_satellite(self, tmp_path, caplog):
        cache = tmp_path / 'wxskyfield'
        cache.mkdir()
        (cache / ('wxskyfield_sat_%d.tle' % ISS_NORAD)).write_text('garbage\n')
        (cache / ('wxskyfield_sat_%d.tle' % TIANGONG_NORAD)).write_text(
            read_tle(TIANGONG_NORAD))
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           satellites=dict(SATELLITES), sat_dir=str(cache))
        with saved_almanacs(), caplog.at_level(logging.ERROR, logger=wxskyfield.log.name):
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert alm.iss.alt is None
            assert alm.tiangong.alt == pytest.approx(-78.9339, abs=ANGLE_TOL)
        assert 'satellite_elements' in caplog.text

    def test_configured_but_no_file(self, tmp_path):
        """A satellite added to the config before any fetch: every tag
        N/A (including the diagnostics -- there is nothing to date), and
        nothing raises."""
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           satellites={'iss': ISS_NORAD}, sat_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert alm.iss.alt is None
            assert raw(alm.iss.next_pass.rise, 'unix_epoch') is None
            assert raw(alm.iss.elements_epoch, 'unix_epoch') is None
            assert raw(alm.iss.elements_age, 'second') is None

    def test_cache_reloads_on_mtime_change(self, tmp_path):
        """The element cache is keyed on the file's mtime: a fetch (or a
        user replacing a file by hand) is picked up at the next tag
        evaluation, per tag, without a restart."""
        path = tmp_path / ('wxskyfield_sat_%d.tle' % ISS_NORAD)
        path.write_text('garbage\n')
        s = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=False,
                           satellites={'iss': ISS_NORAD}, sat_dir=str(tmp_path))
        with saved_almanacs():
            assert wxskyfield.register_almanac(s)
            alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                        formatter=weewx.units.get_default_formatter())
            assert alm.iss.alt is None
            path.write_text(read_tle(ISS_NORAD))
            future = time.time() + 10
            os.utime(str(path), (future, future))
            assert alm.iss.alt == pytest.approx(-17.7318, abs=ANGLE_TOL)


class TestPyEphemSatelliteSanity:
    """A one-time independent check of the satellite observer plumbing --
    NOT a parity commitment (loose tolerance, no runtime dependency):
    PyEphem's readtle on the same TLE, time and place must agree to a
    fraction of a degree, catching the self-consistent-wrong-pin class of
    error that regression pins cannot."""

    def test_readtle_altaz_agrees(self, almanac):
        ephem = pytest.importorskip('ephem')
        import math
        lines = read_tle(ISS_NORAD).splitlines()
        sat = ephem.readtle(lines[0], lines[1], lines[2])
        observer = pyephem_observer()
        observer.pressure = 0
        sat.compute(observer)
        assert math.degrees(sat.alt) == pytest.approx(almanac.iss.alt, abs=0.2)
        assert math.degrees(sat.az) == pytest.approx(almanac.iss.az, abs=0.2)


# These raise AttributeError on the built-in almanac too (PyEphem limitations);
# the Skyfield almanac must fail the same way rather than crash differently.
PYEPHEM_PARITY_ATTRIBUTE_ERRORS = [
    "almanac.venus.cmlI",
    "almanac.sun.foo",
    "almanac.moon.sublatitude",
    "almanac.moon.sublongitude",
    "almanac.io.rise",
]


class TestPyEphemParityAudit:
    """With PyEphem installed, everything the built-in almanac can do must
    still work with the Skyfield almanac registered."""

    @pytest.fixture(autouse=True)
    def _require_ephem(self):
        pytest.importorskip('ephem')

    @pytest.mark.parametrize('expression', PYEPHEM_PARITY_EXPRESSIONS)
    def test_expression_evaluates(self, almanac, expression):
        value = eval(expression)
        assert value is not None
        assert str(value) != ''

    @pytest.mark.parametrize('expression', PYEPHEM_PARITY_ATTRIBUTE_ERRORS)
    def test_expression_raises_attribute_error(self, almanac, expression):
        with pytest.raises(AttributeError):
            eval(expression)


# Everything that must work on a system with no PyEphem at all (a
# Skyfield-only installation).
SKYFIELD_ONLY_EXPRESSIONS = [
    "almanac.hasExtras",
    "almanac.moon_fullness", "almanac.moon.moon_fullness",
    "almanac.sunrise", "almanac.sunset", "almanac.moon_phase", "almanac.moon_index",
    "almanac.sun.rise", "almanac.sun.transit", "almanac.sun.set",
    "almanac.moon.rise", "almanac.moon.transit", "almanac.moon.set",
    "almanac.mars.rise", "almanac.mars.transit", "almanac.mars.set",
    "almanac.sidereal_time", "almanac.sidereal_angle",
    "almanac.next_vernal_equinox", "almanac.next_autumnal_equinox",
    "almanac.next_summer_solstice", "almanac.previous_winter_solstice",
    "almanac.next_winter_solstice", "almanac.next_equinox", "almanac.next_solstice",
    "almanac.next_full_moon", "almanac.next_new_moon",
    "almanac.next_first_quarter_moon", "almanac.previous_last_quarter_moon",
    "almanac.sun.az", "almanac.sun.alt", "almanac.moon.az", "almanac.moon.alt",
    "almanac.sun.azimuth", "almanac.sun.altitude",
    "almanac.moon.azimuth", "almanac.moon.altitude",
    "almanac.sun.topo_ra", "almanac.sun.topo_dec",
    "almanac.sun.astro_ra", "almanac.sun.geo_dec",
    "almanac(horizon=-6).sun(use_center=1).rise",
    "almanac(pressure=0, horizon=-34.0/60.0).sun.previous_rising",
    "almanac.moon.next_setting", "almanac.sun.next_antitransit",
    "almanac.mars.sun_distance", "almanac.mars.earth_distance",
    "almanac.mars.distance", "almanac.mars.distance_from_sun",
    "almanac.moon.distance.km",
    "almanac.moon.next_perigee", "almanac.moon.previous_perigee",
    "almanac.moon.next_apogee", "almanac.moon.previous_apogee",
    "almanac.next_supermoon",
    "almanac.next_perihelion", "almanac.previous_perihelion",
    "almanac.next_aphelion", "almanac.previous_aphelion",
    "almanac.solar_time", "almanac.solar_angle", "almanac.equation_of_time",
    "almanac.next_meteor_shower.name", "almanac.next_meteor_shower.label",
    "almanac.next_meteor_shower.peak", "almanac.next_meteor_shower.zhr",
    "almanac.next_meteor_shower.parent", "almanac.next_meteor_shower.radiant_ra",
    "almanac.next_meteor_shower.radiant_alt", "almanac.next_meteor_shower.radiant_az",
    "almanac.active_meteor_showers",
    "almanac.moon.libration_lat", "almanac.moon.libration_long", "almanac.moon.colong",
    "almanac.jupiter.cmlI", "almanac.jupiter.cmlII",
    "almanac.saturn.earth_tilt", "almanac.saturn.sun_tilt",
    "almanac.separation(almanac.mars, almanac.venus)",
    "almanac.sun.phase",
    "almanac.mercury.mag", "almanac.venus.mag", "almanac.mars.mag",
    "almanac.jupiter.mag", "almanac.saturn.mag", "almanac.uranus.mag",
    "almanac.neptune.mag", "almanac.sun.mag", "almanac.moon.mag", "almanac.pluto.mag",
    "almanac.venus.phase", "almanac.mars.phase",
    "almanac.moon.illumination", "almanac.venus.illumination", "almanac.sun.illumination",
    "almanac.sun.size", "almanac.moon.size", "almanac.moon.radius", "almanac.moon.radius_size",
    "almanac.sun.circumpolar", "almanac.sun.neverup",
    "almanac.venus.parallactic_angle()", "almanac.venus.parallactic_angle",
    "almanac.venus.parallactic_angle.degrees",
    "almanac.moon.libration_lat.degrees", "almanac.moon.colong.degrees",
    "almanac.moon.subsolar_lat.degrees", "almanac.moon.moon_phase",
    "almanac.jupiter.cmlI.degrees", "almanac.saturn.sun_tilt.degrees",
    "almanac.separation(almanac.mars, almanac.venus).degrees",
    "almanac.sun.name",
    "almanac.mercury.elong", "almanac.mercury.elongation",
    "almanac.sun.hlong", "almanac.mars.hlongitude", "almanac.mars.hlatitude",
    "almanac.sun.ha", "almanac.mars.hlon", "almanac.sun.hour_angle",
    "almanac.separation((0.1, 0.2), (0.3, 0.4))",
    "almanac.sun.visible", "almanac.sun.visible_change()", "almanac.moon.visible",
    "almanac.sun.constellation", "almanac.sun.constellation_abbr",
    "almanac.moon.constellation", "almanac.mars.constellation_abbr",
    "almanac.sun.constellation.label", "almanac.sun.constellation.abbr",
    "almanac.sun.label", "almanac.moon.label",
    "almanac.next_lunar_eclipse", "almanac.next_lunar_eclipse_type",
    "almanac.previous_lunar_eclipse", "almanac.previous_lunar_eclipse_type",
    "almanac.next_solar_eclipse", "almanac.next_solar_eclipse_type",
    "almanac.previous_solar_eclipse", "almanac.previous_solar_eclipse_type",
    "almanac.next_eclipse", "almanac.next_eclipse_type", "almanac.next_eclipse_kind",
    "almanac.previous_eclipse", "almanac.previous_eclipse_type", "almanac.previous_eclipse_kind",
    # Satellites are Skyfield-native: the built-in almanac never served
    # them, so the whole surface must be whole without PyEphem.
    "almanac.iss.alt", "almanac.iss.az", "almanac.iss.ra", "almanac.iss.dec",
    "almanac.iss.altitude", "almanac.iss.azimuth",
    "almanac.iss.topo_ra", "almanac.iss.topo_dec",
    "almanac.iss.azimuth.ordinal_compass()",
    "almanac.iss.distance", "almanac.iss.sunlit",
    "almanac.iss.rise", "almanac.iss.transit", "almanac.iss.set",
    "almanac.iss.next_pass.rise", "almanac.iss.next_pass.culmination",
    "almanac.iss.next_pass.set", "almanac.iss.next_pass.max_altitude",
    "almanac.iss.next_pass.rise_azimuth.ordinal_compass()",
    "almanac.iss.next_pass.culmination_azimuth", "almanac.iss.next_pass.set_azimuth",
    "almanac.iss.next_pass.duration",
    "almanac.iss.next_visible_pass.rise", "almanac.iss.next_visible_pass.visible",
    "almanac(horizon=10).iss.next_pass.rise",
    "almanac.iss.elements_epoch", "almanac.iss.elements_age",
    "almanac.sat_25544.alt", "almanac.iss.name", "almanac.iss.label",
    "almanac.tiangong.next_pass.rise",
    "almanac.separation(almanac.iss, almanac.mars)",
    # Comets are Skyfield-native too: the built-in almanac never served
    # them, so the whole surface must be whole without PyEphem.
    "almanac.halley.rise", "almanac.halley.set", "almanac.halley.transit",
    "almanac.halley.az", "almanac.halley.alt", "almanac.halley.ra", "almanac.halley.dec",
    "almanac.halley.azimuth", "almanac.halley.altitude",
    "almanac.halley.next_rising", "almanac.halley.previous_setting",
    "almanac.halley.mag", "almanac.halley.earth_distance", "almanac.halley.sun_distance",
    "almanac.halley.distance", "almanac.halley.distance_from_sun",
    "almanac.halley.elong", "almanac.halley.elongation",
    "almanac.halley.visible", "almanac.halley.phase", "almanac.halley.illumination",
    "almanac.halley.circumpolar", "almanac.halley.neverup",
    "almanac.halley.constellation", "almanac.halley.constellation.label",
    "almanac.halley.elements_epoch", "almanac.halley.elements_age",
    "almanac.halley.perihelion",
    "almanac.halley.name", "almanac.halley.label",
    "almanac.hale_bopp.a_ra", "almanac.bright.mag",
    "almanac.separation(almanac.halley, almanac.mars)",
]

SKYFIELD_ONLY_STAR_EXPRESSIONS = [
    "almanac.rigel.rise", "almanac.rigel.set", "almanac.rigel.transit",
    "almanac.rigel.az", "almanac.rigel.alt", "almanac.rigel.mag",
    "almanac.rigel.ha", "almanac.sirius.hour_angle",
    "almanac.polaris.circumpolar", "almanac.sirius.azimuth",
    "almanac.vega.next_rising", "almanac.rigel.visible",
    "almanac.rigel.earth_distance", "almanac.rigel.sun_distance",
    "almanac.rigel.distance", "almanac.rigel.distance_from_sun",
    "almanac.proxima_centauri.earth_distance", "almanac.barnards_star.mag",
    "almanac.hip_32349.mag",
    "almanac.rigel.constellation", "almanac.rigel.constellation_abbr",
    "almanac.rigel.constellation.label", "almanac.rigel.label",
    "almanac.rigel.parallactic_angle.degrees",
]


class TestSkyfieldOnlyAudit:
    """Everything a Skyfield-only installation (no PyEphem) must support."""

    def test_has_extras(self, skyfield_only_almanac):
        assert skyfield_only_almanac.hasExtras

    @pytest.mark.parametrize('expression', SKYFIELD_ONLY_EXPRESSIONS)
    def test_expression_evaluates(self, skyfield_only_almanac, expression):
        value = eval(expression, {'almanac': skyfield_only_almanac})
        assert value is not None
        assert str(value) != ''

    @needs_catalog
    @pytest.mark.parametrize('expression', SKYFIELD_ONLY_STAR_EXPRESSIONS)
    def test_star_expression_evaluates(self, skyfield_only_almanac, expression):
        value = eval(expression, {'almanac': skyfield_only_almanac})
        assert value is not None
        assert str(value) != ''

    def test_pyephem_only_attributes_raise(self, skyfield_only_almanac):
        # Without PyEphem, its exclusive attributes raise AttributeError
        # (a per-tag error in a report, not a crash).  a_epoch -- the epoch
        # stamp of PyEphem's astrometric coordinates -- is a deliberate
        # fallthrough, as is its deprecated rise_time family.
        with pytest.raises(AttributeError):
            skyfield_only_almanac.moon.a_epoch


# Every almanac tag used by WeeWX's Seasons skin, as template-shaped
# expressions.  A single list, evaluated both with and without PyEphem
# installed, so the two configurations can never drift apart.
SEASONS_SKIN_EXPRESSIONS = [
    "almanac.hasExtras",
    "almanac(horizon=-6).sun(use_center=1).rise",
    "almanac(horizon=-6).sun(use_center=1).set",
    "almanac.moon.altitude", 'almanac.moon.altitude.format("%.1f")',
    "almanac.moon.azimuth", 'almanac.moon.azimuth.format("%.1f")',
    "almanac.moon_fullness", "almanac.moon_phase",
    "almanac.moon.rise", "almanac.moon.set", "almanac.moon.transit",
    'almanac.moon.topo_dec.format("%.1f")', 'almanac.moon.topo_ra.format("%.1f")',
    "almanac.next_equinox", "almanac.next_equinox.raw",
    "almanac.next_full_moon", "almanac.next_full_moon.raw",
    "almanac.next_new_moon", "almanac.next_new_moon.raw",
    "almanac.next_solstice", "almanac.next_solstice.raw",
    "almanac.sun.alt", "almanac.sun.altitude",
    "almanac.sun.azimuth", 'almanac.sun.azimuth.format("%.1f")',
    "almanac.sunrise", 'almanac.sun.rise.format(None_string="none")', "almanac.sun.rise.raw",
    "almanac.sunset", 'almanac.sun.set.format(None_string="none")', "almanac.sun.set.raw",
    'almanac.sun.topo_dec.format("%.1f")', 'almanac.sun.topo_ra.format("%.1f")',
    "almanac.sun.transit",
    "almanac.sun.visible_change()", "almanac.sun.visible.long_form()",
]


class TestSeasonsSkinTags:
    """Every almanac tag used by WeeWX's Seasons skin must evaluate, both
    with PyEphem installed and without."""

    @pytest.mark.parametrize('expression', SEASONS_SKIN_EXPRESSIONS)
    def test_with_pyephem_installed(self, almanac, expression):
        value = eval(expression)
        assert value is not None and str(value) != '', expression

    @pytest.mark.parametrize('expression', SEASONS_SKIN_EXPRESSIONS)
    def test_without_pyephem(self, skyfield_only_almanac, expression):
        value = eval(expression, {'almanac': skyfield_only_almanac})
        assert value is not None and str(value) != '', expression


def test_stamps_within_drops_wild_times():
    """Skyfield's find_risings/find_settings can emit a numerically wild
    time (near Julian day zero, the "year -4713") when a body barely grazes
    the horizon; converting it to a datetime raises ValueError and, before
    the stamps_within guard, cost a report cycle its page (production,
    2026-07-06).  Times outside the search window are dropped unconverted."""
    ts = skyfield.api.load.timescale(builtin=True)
    t0 = ts.utc(2026, 7, 6)
    t1 = ts.utc(2026, 7, 8)
    good = ts.utc(2026, 7, 6, 12)
    wild = ts.tt_jd(0.0)
    # The wild time is exactly the crash the guard prevents.
    with pytest.raises(ValueError):
        wild.utc_datetime()
    stamps = wxskyfield.stamps_within([good, wild], [True, True], t0, t1)
    assert stamps == [good.utc_datetime().timestamp()]
    # Unflagged events are dropped regardless.
    assert wxskyfield.stamps_within([good], [False], t0, t1) == []
    # An event just outside the window is not this day's event.
    outside = ts.utc(2026, 7, 12)
    assert wxskyfield.stamps_within([outside], [True], t0, t1) == []


class TestInMemoryEphemeris:
    """The engine reads the .bsp fully into RAM (InMemorySpiceKernel).
    'weectl extension install' over a live weewxd rewrites the ephemeris in
    place; a memory-mapped kernel dies with SIGBUS when that happens, so
    replacing or truncating the file under a loaded kernel must not disturb
    its computations."""

    def test_kernel_matches_mmap_and_survives_truncation(self, sky, tmp_path):
        src = os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp')
        copy = str(tmp_path / 'wxskyfield_de421.bsp')
        shutil.copyfile(src, copy)
        t = sky.ts.utc(2025, 6, 21, 19)

        # Same answers as skyfield's own (mmap) loader on the pristine file.
        reference = skyfield.api.load_file(src)
        ref_ra, ref_dec, _ = reference['earth'].at(t).observe(reference['mars']).radec()
        kernel = wxskyfield.InMemorySpiceKernel(copy)
        ra, dec, _ = kernel['earth'].at(t).observe(kernel['mars']).radec()
        assert ra.radians == ref_ra.radians
        assert dec.radians == ref_dec.radians

        # Truncate the backing file to zero bytes underneath the kernel --
        # the in-place rewrite window that used to SIGBUS weewxd.
        open(copy, 'wb').close()
        ra2, dec2, _ = kernel['earth'].at(t).observe(kernel['mars']).radec()
        assert ra2.radians == ra.radians
        assert dec2.radians == dec.radians

    def test_engine_uses_in_memory_kernel(self, sky):
        assert isinstance(sky.planets, wxskyfield.InMemorySpiceKernel)

    def test_kernel_has_every_spicekernel_attribute(self):
        """Field failure on Debian's Skyfield 1.53: SpiceKernel.__init__'s
        attribute set changes between Skyfield releases (1.53 sets codes
        and _vector_functions, 1.54 sets neither), and reproducing the
        assignments by hand left the in-memory kernel missing whatever the
        installed release added -- 'InMemorySpiceKernel' object has no
        attribute 'codes', and the whole almanac declined at startup.  The
        kernel now runs the real __init__, so whatever attributes the
        installed Skyfield's own loader ends up with, ours must too."""
        src = os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_de421.bsp')
        reference = skyfield.api.load_file(src)
        kernel = wxskyfield.InMemorySpiceKernel(src)
        missing = set(vars(reference)) - set(vars(kernel))
        assert not missing
        # The name-decode path the 1.53 failure died in.
        assert kernel.decode('earth') == 399
        assert 399 in kernel.codes
        # The SPK factory swap must have been restored.
        assert skyfield.jpllib.SPK is wxskyfield.jplephem.spk.SPK


# ── the manual's recipes ────────────────────────────────────────────────

def _recipe_expressions() -> List[str]:
    """Every $almanac... chain in docs/recipes.md, as evaluable Python.

    The recipes page tells readers its snippets are checked against a real
    almanac; this is that check.  Cheetah control flow and the snippets'
    local variables ($pass, $comet) are skipped -- what is verified is that
    every chain rooted at $almanac resolves and produces a value."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'docs', 'recipes.md')
    with open(path, 'r') as f:
        text = f.read()
    found = []
    for raw in re.findall(r'\$almanac[A-Za-z0-9_.()=\-,"%\' ]*', text):
        # A chain ends at the first space outside parentheses -- inside
        # them a space is legitimate ("%B %e, %Y"), outside it is prose.
        depth, cut = 0, len(raw)
        for i, ch in enumerate(raw):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ' ' and depth == 0:
                cut = i
                break
        expr = raw[:cut].rstrip('.,;:%')
        if expr.count('(') != expr.count(')') or expr == '$almanac':
            continue
        found.append(expr[1:])          # drop the leading $
    return sorted(set(found))


class TestManualRecipes:
    """docs/recipes.md promises its tag chains evaluate.  Keep that true."""

    def test_found_the_recipes(self):
        exprs = _recipe_expressions()
        assert len(exprs) > 15, 'only found %d chains -- did recipes.md move?' % len(exprs)

    @pytest.mark.parametrize('expression', _recipe_expressions())
    def test_recipe_chain_evaluates(self, almanac, expression):
        value = eval(expression, {'almanac': almanac})
        assert value is not None
        if isinstance(value, wxskyfield.SkyfieldAlmanacBinder):
            # A bare body binder ($almanac.halley, assigned to a snippet's
            # local and then asked for attributes) is a legitimate
            # intermediate.  It deliberately refuses to render by itself.
            return
        # A ValueHelper with no value is a legitimate answer (N/A); what
        # must not happen is an exception or an empty rendering of a tag
        # that should have one.
        str(value)


class _TextsIsAHeavenlyBody:
    """A stand-in almanac type reproducing what WeeWX's PyEphem almanac
    does with an unrecognized attribute: treat it as the name of a
    heavenly body and hand back a binder.  Registered LAST, so it only
    answers what every real almanac has already declined."""

    class Binder:
        def __getattr__(self, attr):
            raise AttributeError(attr)

    def get_almanac_data(self, almanac_obj, attr):
        return _TextsIsAHeavenlyBody.Binder()


@contextlib.contextmanager
def weewx_52_almanac(sky):
    """An Almanac as WeeWX 5.2 and earlier build one: no .texts.

    5.2 is this extension's stated floor and its Almanac.__init__ has no
    texts parameter, so the attribute is simply absent.  The suite runs on
    5.3+, where it is always set, so the test removes it -- and appends
    the catch-all above, which is the half that makes this a real
    reproduction: on 5.2 the missing attribute does NOT raise.  It falls
    through Almanac.__getattr__ to PyEphem's "must be a heavenly body"
    branch, which returns a truthy binder, so `getattr(alm, 'texts',
    None) or {}` keeps the binder and blows up on .get one step later.
    A fake that merely lacks the attribute passes against that broken
    code and proves nothing.
    """
    with saved_almanacs():
        assert wxskyfield.register_almanac(sky)
        weewx.almanac.almanacs.append(_TextsIsAHeavenlyBody())
        alm = weewx.almanac.Almanac(
            TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
            formatter=weewx.units.get_default_formatter())
        del alm.__dict__['texts']
        assert 'texts' not in alm.__dict__
        # The premise: the lookup yields a truthy non-dict, not None.
        probe = getattr(alm, 'texts', None)
        assert probe is not None and not isinstance(probe, dict) and bool(probe)
        yield alm


class TestWeeWX52NoTexts:
    """Label translation reads the report's [Almanac] section off
    Almanac.texts, which arrived in WeeWX 5.3.  This extension supports
    5.2, where every label must quietly stay Latin/English -- and, above
    all, no tag may raise."""

    def test_body_label(self, sky):
        with weewx_52_almanac(sky) as alm:
            assert alm.moon.label == 'Moon'
            assert alm.jupiter.label == 'Jupiter'

    def test_constellation_label(self, sky):
        with weewx_52_almanac(sky) as alm:
            c = alm.sun.constellation
            assert c == 'Gemini'
            assert c.label == 'Gemini'
            assert c.abbr == 'Gem'

    def test_meteor_shower_label(self, sky):
        with weewx_52_almanac(sky) as alm:
            shower = alm.next_meteor_shower
            assert shower.label == shower.name

    def test_moon_phase_still_works(self, sky):
        """moon_phases predates texts, so the phase name is unaffected."""
        with weewx_52_almanac(sky) as alm:
            assert str(alm.moon_phase) in weeutil.Moon.moon_phases

    def test_almanac_texts_helper(self, sky):
        with weewx_52_almanac(sky) as alm:
            assert wxskyfield.almanac_texts(alm) == {}

    def test_helper_reads_the_section_on_53(self, sky):
        with saved_almanacs():
            assert wxskyfield.register_almanac(sky)
            alm = weewx.almanac.Almanac(
                TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                formatter=weewx.units.get_default_formatter(),
                texts={'moon': 'Mond'})
            assert wxskyfield.almanac_texts(alm) == {'moon': 'Mond'}

    def test_helper_absorbs_a_malformed_section(self, sky):
        class Scalar:
            def __init__(self):
                self.texts = 'oops'
        assert wxskyfield.almanac_texts(Scalar()) == {}

    def test_helper_absorbs_a_dictless_almanac(self):
        """A foreign almanac using __slots__ has no __dict__ at all."""
        class Slotted:
            __slots__ = ()
        assert wxskyfield.almanac_texts(Slotted()) == {}

    def test_helper_never_hands_back_its_own_default(self):
        """The empty-case return must not be a shared mutable a caller
        could scribble on."""
        class Slotted:
            __slots__ = ()
        d = wxskyfield.almanac_texts(Slotted())
        d['moon'] = 'scribble'
        assert wxskyfield.almanac_texts(Slotted()) == {}
