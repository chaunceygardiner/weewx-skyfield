"""
wxskyfield.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

weewx-skyfield replaces WeeWX's built-in PyEphem/weeutil almanac with a
Skyfield based almanac (SkyfieldAlmanacType), so that report tags such as
$almanac.sunrise, $almanac(horizon=-6).sun(use_center=1).rise and
$almanac.rigel.mag are computed with Skyfield and JPL's ephemeris.
Requires WeeWX 5.2 or later (the first release with extensible almanacs).

The almanac engine originated in the weewx-celestial extension (which also
inserts celestial observations into loop packets); this extension carries
the almanac alone.
"""

import io
import logging
import math
import os
import re
import sys

from datetime import datetime
from datetime import timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import jplephem.daf
import jplephem.spk
import numpy

import skyfield
import skyfield.almanac
import skyfield.api
import skyfield.errors
import skyfield.framelib
import skyfield.jpllib
import skyfield.magnitudelib
import skyfield.timelib
import weeutil.weeutil
import weewx
import weewx.almanac
import weewx.units

from weeutil.weeutil import to_bool
from weewx.engine import StdEngine
from weewx.engine import StdService
from weewx.units import ValueHelper
from weewx.units import ValueTuple

# get a logger object
log = logging.getLogger(__name__)

WXSKYFIELD_VERSION = '1.6'

if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 9):
    raise weewx.UnsupportedFeature(
        "weewx-skyfield requires Python 3.9 or later, found %s.%s" % (sys.version_info[0], sys.version_info[1]))

# The WeeWX 5.2 requirement is enforced by register_almanac, which declines
# gracefully (with a log message) on anything older.

class WxSkyfield(StdService):
    """A service whose only job is to register the Skyfield almanac at
    engine startup (report tags are then computed with Skyfield)."""

    def __init__(self, engine: StdEngine, config_dict: Dict[str, Any]):
        super(WxSkyfield, self).__init__(engine, config_dict)
        log.info("Service version: %s" % WXSKYFIELD_VERSION)

        # Only continue if the plugin is enabled.
        skyfield_config_dict = config_dict.get('Skyfield', {})
        enable = to_bool(skyfield_config_dict.get('enable', True))
        if enable:
            log.info("WxSkyfield status: enabled...continuing.")
        else:
            log.info("WxSkyfield status: disabled...enable it in the Skyfield section of weewx.conf.")
            return

        stars = to_bool(skyfield_config_dict.get('stars', True))
        user_root = Sky.get_weewx_config_info(config_dict)

        log.info("stars    : %r" % stars)
        log.info("user_root: %s" % user_root)

        self.sky = Sky(user_root, load_stars=stars)
        if self.sky.is_valid():
            if register_almanac(self.sky):
                log.info('Skyfield almanac registered; reports will use Skyfield for almanac computations.')

# Named stars available as report almanac tags (e.g., $almanac.rigel.rise)
# unless disabled (stars = false in [Skyfield]).  Maps the tag name to the
# star's Hipparcos catalog number.  The names are the IAU Catalog of Star
# Names (the Working Group on Star Names' IAU-CSN list, 2022 edition; every
# entry with a Hipparcos number), plus PyEphem's star catalog names for
# backward compatibility (a few of which are legacy spellings of the same
# stars: albereo, alcaid, sirrah, etc.).  Multi-word names use underscores
# and diacritics are dropped, since a report tag must be an identifier
# ($almanac.barnards_star, $almanac.kaus_australis).  The stars themselves
# are read from wxskyfield_stars.dat, an excerpt of the Hipparcos Catalogue
# (ESA SP-1200, 1997) that ships with this extension.  Any other Hipparcos
# star can be addressed by number: $almanac.hip_57939.
NAMED_STARS: Dict[str, int] = {
    'acamar'           : 13847,
    'achernar'         : 7588,
    'achird'           : 3821,
    'acrab'            : 78820,
    'acrux'            : 60718,
    'acubens'          : 44066,
    'adara'            : 33579,
    'adhafera'         : 50335,
    'adhara'           : 33579,
    'adhil'            : 6411,
    'agena'            : 68702,
    'ain'              : 20889,
    'ainalrami'        : 92761,
    'aladfar'          : 94481,
    'alasia'           : 90004,
    'albaldah'         : 94141,
    'albali'           : 102618,
    'albereo'          : 95947,
    'albireo'          : 95947,
    'alcaid'           : 67301,
    'alchiba'          : 59199,
    'alcor'            : 65477,
    'alcyone'          : 17702,
    'aldebaran'        : 21421,
    'alderamin'        : 105199,
    'aldhanab'         : 108085,
    'aldhibah'         : 83895,
    'aldulfin'         : 101421,
    'alfirk'           : 106032,
    'algedi'           : 100064,
    'algenib'          : 1067,
    'algieba'          : 50583,
    'algol'            : 14576,
    'algorab'          : 60965,
    'alhena'           : 31681,
    'alioth'           : 62956,
    'aljanah'          : 102488,
    'alkaid'           : 67301,
    'alkalurops'       : 75411,
    'alkaphrah'        : 44471,
    'alkarab'          : 115623,
    'alkes'            : 53740,
    'almaaz'           : 23416,
    'almach'           : 9640,
    'alnair'           : 109268,
    'alnasl'           : 88635,
    'alnilam'          : 26311,
    'alnitak'          : 26727,
    'alniyat'          : 80112,
    'alphard'          : 46390,
    'alphecca'         : 76267,
    'alpheratz'        : 677,
    'alpherg'          : 7097,
    'alrakis'          : 83608,
    'alrescha'         : 9487,
    'alruba'           : 86782,
    'alsafi'           : 96100,
    'alsciaukat'       : 41075,
    'alsephina'        : 42913,
    'alshain'          : 98036,
    'alshat'           : 100310,
    'altair'           : 97649,
    'altais'           : 94376,
    'alterf'           : 46750,
    'aludra'           : 35904,
    'alula_australis'  : 55203,
    'alula_borealis'   : 55219,
    'alya'             : 92946,
    'alzirr'           : 32362,
    'amadioha'         : 29550,
    'ancha'            : 110003,
    'angetenar'        : 13288,
    'aniara'           : 57820,
    'ankaa'            : 2081,
    'anser'            : 95771,
    'antares'          : 80763,
    'arcalis'          : 72845,
    'arcturus'         : 69673,
    'arkab_posterior'  : 95294,
    'arkab_prior'      : 95241,
    'arneb'            : 25985,
    'ascella'          : 93506,
    'asellus_australis': 42911,
    'asellus_borealis' : 42806,
    'ashlesha'         : 43109,
    'aspidiske'        : 45556,
    'asterope'         : 17579,
    'athebyne'         : 80331,
    'atik'             : 17448,
    'atlas'            : 17847,
    'atria'            : 82273,
    'avior'            : 41037,
    'axolotl'          : 118319,
    'ayeyarwady'       : 13993,
    'azelfafage'       : 107136,
    'azha'             : 13701,
    'azmidi'           : 38170,
    'baekdu'           : 73136,
    'barnards_star'    : 87937,
    'baten_kaitos'     : 8645,
    'beemim'           : 20535,
    'beid'             : 19587,
    'belel'            : 95124,
    'belenos'          : 6643,
    'bellatrix'        : 25336,
    'betelgeuse'       : 27989,
    'bharani'          : 13209,
    'bibha'            : 48711,
    'biham'            : 109427,
    'bosona'           : 107251,
    'botein'           : 14838,
    'brachium'         : 73714,
    'bubup'            : 26380,
    'buna'             : 12191,
    'bunda'            : 106786,
    'canopus'          : 30438,
    'capella'          : 24608,
    'caph'             : 746,
    'castor'           : 36850,
    'castula'          : 4422,
    'cebalrai'         : 86742,
    'ceibo'            : 37284,
    'celaeno'          : 17489,
    'cervantes'        : 86796,
    'chalawan'         : 53721,
    'chamukuy'         : 20894,
    'chara'            : 61317,
    'chechia'          : 99894,
    'chertan'          : 54879,
    'citadelle'        : 1547,
    'citala'           : 33719,
    'cocibolca'        : 3479,
    'copernicus'       : 43587,
    'cor_caroli'       : 63125,
    'cujam'            : 80463,
    'cursa'            : 23875,
    'dabih'            : 100345,
    'dalim'            : 14879,
    'deneb'            : 102098,
    'deneb_algedi'     : 107556,
    'denebola'         : 57632,
    'diadem'           : 64241,
    'dingolay'         : 54158,
    'diphda'           : 3419,
    'dofida'           : 66047,
    'dschubba'         : 78401,
    'dubhe'            : 54061,
    'dziban'           : 86614,
    'ebla'             : 114322,
    'edasich'          : 75458,
    'electra'          : 17499,
    'elgafar'          : 70755,
    'elkurud'          : 29034,
    'elnath'           : 25428,
    'eltanin'          : 87833,
    'emiw'             : 5529,
    'enif'             : 107315,
    'errai'            : 116727,
    'etamin'           : 87833,
    'fafnir'           : 90344,
    'fang'             : 78265,
    'fawaris'          : 97165,
    'felis'            : 48615,
    'felixvarela'      : 2247,
    'flegetonte'       : 57370,
    'fomalhaut'        : 113368,
    'formalhaut'       : 113368,
    'formosa'          : 56508,
    'fulu'             : 2920,
    'fumalsamakah'     : 113889,
    'funi'             : 61177,
    'furud'            : 30122,
    'fuyue'            : 87261,
    'gacrux'           : 61084,
    'gakyid'           : 42446,
    'giausar'          : 56211,
    'gienah'           : 59803,
    'gienah_corvi'     : 59803,
    'ginan'            : 60260,
    'gomeisa'          : 36188,
    'grumium'          : 87585,
    'gudja'            : 77450,
    'gumala'           : 94645,
    'guniibuu'         : 84405,
    'hadar'            : 68702,
    'haedus'           : 23767,
    'hamal'            : 9884,
    'hassaleh'         : 23015,
    'hatysa'           : 26241,
    'helvetios'        : 113357,
    'heze'             : 66249,
    'hoggar'           : 21109,
    'homam'            : 112029,
    'hunahpu'          : 55174,
    'hunor'            : 80076,
    'iklil'            : 78104,
    'illyrian'         : 47087,
    'imai'             : 59747,
    'inquill'          : 84787,
    'intan'            : 15578,
    'intercrus'        : 46471,
    'itonda'           : 108375,
    'izar'             : 72105,
    'jabbah'           : 79374,
    'jishui'           : 37265,
    'kaffaljidhma'     : 12706,
    'kalausi'          : 47202,
    'kamuy'            : 79219,
    'kang'             : 69427,
    'karaka'           : 76351,
    'kaus_australis'   : 90185,
    'kaus_borealis'    : 90496,
    'kaus_media'       : 89931,
    'kaveh'            : 92895,
    'keid'             : 19849,
    'khambalia'        : 69974,
    'kitalpha'         : 104987,
    'kochab'           : 72607,
    'koeia'            : 12961,
    'kornephoros'      : 80816,
    'kraz'             : 61359,
    'kurhah'           : 108917,
    'la_superba'       : 62223,
    'larawag'          : 82396,
    'lesath'           : 85696,
    'libertas'         : 97938,
    'liesma'           : 66192,
    'lilii_borea'      : 13061,
    'lionrock'         : 110813,
    'lucilinburhuc'    : 30860,
    'lusitania'        : 30905,
    'maasym'           : 85693,
    'macondo'          : 52521,
    'mago'             : 24003,
    'mahasim'          : 28380,
    'mahsati'          : 82651,
    'maia'             : 17573,
    'marfik'           : 80883,
    'markab'           : 113963,
    'markeb'           : 45941,
    'marsic'           : 79043,
    'matar'            : 112158,
    'mebsuta'          : 32246,
    'megrez'           : 59774,
    'meissa'           : 26207,
    'mekbuda'          : 34088,
    'meleph'           : 42556,
    'menkalinan'       : 28360,
    'menkar'           : 14135,
    'menkent'          : 68933,
    'menkib'           : 18614,
    'merak'            : 53910,
    'merga'            : 72487,
    'meridiana'        : 94114,
    'merope'           : 17608,
    'mesarthim'        : 8832,
    'miaplacidus'      : 45238,
    'mimosa'           : 62434,
    'minchir'          : 42402,
    'minelauva'        : 63090,
    'minkar'           : 59316,
    'mintaka'          : 25930,
    'mira'             : 10826,
    'mirach'           : 5447,
    'miram'            : 13268,
    'mirfak'           : 15863,
    'mirzam'           : 30324,
    'misam'            : 14668,
    'mizar'            : 65378,
    'monch'            : 72339,
    'mothallah'        : 8796,
    'mouhoun'          : 22491,
    'muliphein'        : 34045,
    'muphrid'          : 67927,
    'muscida'          : 41704,
    'musica'           : 103527,
    'nahn'             : 44946,
    'naos'             : 39429,
    'nashira'          : 106985,
    'nasti'            : 40687,
    'natasha'          : 48235,
    'nekkar'           : 73555,
    'nembus'           : 7607,
    'nenque'           : 5054,
    'nervia'           : 32916,
    'nganurganity'     : 33856,
    'nihal'            : 25606,
    'nikawiy'          : 74961,
    'nosaxa'           : 31895,
    'nunki'            : 92855,
    'nusakan'          : 75695,
    'nushagak'         : 13192,
    'ogma'             : 80838,
    'okab'             : 93747,
    'paikauhale'       : 81266,
    'peacock'          : 100751,
    'phact'            : 26634,
    'phecda'           : 58001,
    'pherkad'          : 75097,
    'phoenicia'        : 99711,
    'piautos'          : 40881,
    'pincoya'          : 88414,
    'pipirima'         : 82545,
    'pleione'          : 17851,
    'poerava'          : 116084,
    'polaris'          : 11767,
    'polaris_australis': 104382,
    'polis'            : 89341,
    'pollux'           : 37826,
    'porrima'          : 61941,
    'praecipua'        : 53229,
    'prima_hyadum'     : 20205,
    'procyon'          : 37279,
    'propus'           : 29655,
    'proxima_centauri' : 70890,
    'ran'              : 16537,
    'rana'             : 17378,
    'rapeto'           : 83547,
    'rasalas'          : 48455,
    'rasalgethi'       : 84345,
    'rasalhague'       : 86032,
    'rastaban'         : 85670,
    'regulus'          : 49669,
    'revati'           : 5737,
    'rigel'            : 24436,
    'rigil_kentaurus'  : 71683,
    'rosaliadecastro'  : 81022,
    'rotanev'          : 101769,
    'ruchbah'          : 6686,
    'rukbat'           : 95347,
    'sabik'            : 84012,
    'saclateni'        : 23453,
    'sadachbia'        : 110395,
    'sadalbari'        : 112748,
    'sadalmelik'       : 109074,
    'sadalsuud'        : 106278,
    'sadr'             : 100453,
    'sagarmatha'       : 56572,
    'saiph'            : 27366,
    'salm'             : 115250,
    'samaya'           : 106824,
    'sargas'           : 86228,
    'sarin'            : 84379,
    'sceptrum'         : 21594,
    'scheat'           : 113881,
    'schedar'          : 3179,
    'secunda_hyadum'   : 20455,
    'segin'            : 8886,
    'seginus'          : 71075,
    'sham'             : 96757,
    'shama'            : 55664,
    'sharjah'          : 79431,
    'shaula'           : 85927,
    'sheliak'          : 92420,
    'sheratan'         : 8903,
    'sika'             : 95262,
    'sirius'           : 32349,
    'sirrah'           : 677,
    'situla'           : 111710,
    'skat'             : 113136,
    'solaris'          : 104780,
    'spica'            : 65474,
    'stribor'          : 43674,
    'sualocin'         : 101958,
    'subra'            : 47508,
    'suhail'           : 44816,
    'sulafat'          : 93194,
    'syrma'            : 69701,
    'tabit'            : 22449,
    'taiyangshou'      : 57399,
    'taiyi'            : 63076,
    'talitha'          : 44127,
    'tania_australis'  : 50801,
    'tania_borealis'   : 50372,
    'tapecue'          : 38041,
    'tarazed'          : 97278,
    'tarf'             : 40526,
    'taygeta'          : 17531,
    'tegmine'          : 40167,
    'tejat'            : 30343,
    'terebellum'       : 98066,
    'theemin'          : 21393,
    'thuban'           : 68756,
    'tiaki'            : 112122,
    'tianguan'         : 26451,
    'tianyi'           : 62423,
    'timir'            : 80687,
    'titawin'          : 7513,
    'toliman'          : 71681,
    'tonatiuh'         : 58952,
    'torcular'         : 8198,
    'tupa'             : 60644,
    'tupi'             : 17096,
    'tureis'           : 39757,
    'ukdah'            : 47431,
    'uklun'            : 57291,
    'unukalhai'        : 77070,
    'uruk'             : 96078,
    'vega'             : 91262,
    'veritate'         : 116076,
    'vindemiatrix'     : 63608,
    'wasat'            : 35550,
    'wazn'             : 27628,
    'wezen'            : 34444,
    'wurren'           : 5348,
    'xamidimura'       : 82514,
    'xihe'             : 91852,
    'xuange'           : 69732,
    'yed_posterior'    : 79882,
    'yed_prior'        : 79593,
    'yildun'           : 85822,
    'zaniah'           : 60129,
    'zaurak'           : 18543,
    'zavijava'         : 57757,
    'zhang'            : 48356,
    'zibal'            : 15197,
    'zosma'            : 54872,
    'zubenelgenubi'    : 72622,
    'zubenelhakrabi'   : 76333,
    'zubeneschamali'   : 74785,
}

# An excerpt of the Hipparcos Catalogue containing the stars in NAMED_STARS.
# It is installed alongside wxskyfield.py (like the ephemeris), and its data
# lines are unmodified hip_main.dat records, so a full hip_main.dat works in
# its place.
STAR_FILE = 'wxskyfield_stars.dat'
# The Hipparcos catalog's positions are for epoch J1991.25.  This is that
# epoch as a TT Julian date, matching skyfield.data.hipparcos.load_dataframe.
HIPPARCOS_EPOCH_JD = 1721045.0 + 1991.25 * 365.25

# Astronomical units per light year (IAU 2015 definitions).
AU_PER_LIGHT_YEAR = 63241.077

# Body name -> key in the DE421 ephemeris, for every body served by the
# almanac (earth, the observer, is loaded separately).
EPHEMERIS_KEYS: Dict[str, str] = {
    'sun'    : 'sun',
    'moon'   : 'moon',
    'mercury': 'mercury',
    'venus'  : 'venus',
    'mars'   : 'mars',
    'jupiter': 'jupiter barycenter',
    'saturn' : 'saturn barycenter',
    'uranus' : 'uranus barycenter',
    'neptune': 'neptune barycenter',
    'pluto'  : 'pluto barycenter',
}

# ── result cache ─────────────────────────────────────────────────────────────
# Report generation asks the same expensive questions over and over: every
# template mention of $almanac.moon.rise runs a fresh find_risings scan, a
# page's desktop and smartphone twins repeat each other's work, and the
# day-window verbs (rise/set/transit, searched from local midnight) return
# the same instant for every almanac time within the day.  Cache at the
# computation layer -- raw floats only, never ValueHelpers, which carry the
# calling skin's formatter.  Two pools: day-window search results survive
# across report cycles (their keys name the search window and location);
# instantaneous positions are keyed on the exact timestamp, collapsing
# repeats within a cycle -- and across cycles for time-traveled tags
# anchored to fixed instants (an analemma's weekly noons, a moon calendar's
# days).  On overflow a pool is simply cleared: correctness never depends
# on an entry being present.
_DAY_CACHE: Dict[Tuple, Any] = {}
_POS_CACHE: Dict[Tuple, Any] = {}
_DAY_CACHE_CAP = 4096
_POS_CACHE_CAP = 16384
_MISS = object()

# Rise/set cache keys quantize the effective horizon to this granularity.
# The horizon includes refraction scaled by the almanac's current
# temperature and pressure, which drift a few thousandths of a degree
# between report cycles; without quantization no day-window entry would
# ever be reused.  0.002 degrees of horizon moves a mid-latitude rise or
# set by well under a second (worst measured 0.64 s over a 15-hour replay
# of real sensor data), so a cached time disagrees with a fresh one by a
# displayed (truncated) minute only when the true time sits within that
# fraction of a second of the boundary.  (0.02 originally; its ~5 s of
# drift flipped displayed minutes on boundary-straddling times -- seen on
# the bambi5t/ella5t soak, 2026-07-08.)
_HORIZON_QUANTUM_DEGREES = 0.002


def _cached(cache: Dict[Tuple, Any], cap: int, key: Tuple,
            compute: Callable[[], Any]) -> Any:
    value = cache.get(key, _MISS)
    if value is _MISS:
        value = compute()
        if len(cache) >= cap:
            cache.clear()
        cache[key] = value
    return value


def stamps_within(times, flags, t0, t1) -> List[float]:
    """Timestamps of the flagged skyfield event times that lie inside the
    search window [t0, t1].  Skyfield's find_risings/find_settings can emit
    a numerically wild time (near Julian day zero, the "year -4713") when a
    body barely grazes the horizon; converting such a time to a datetime
    raises ValueError and, before this guard, cost a report cycle its page
    (seen once in production, 2026-07-06).  A time outside the window is by
    definition not this day's event, so it is dropped before conversion."""
    stamps: List[float] = []
    for t, flag in zip(times, flags):
        if not flag:
            continue
        if not (t0.tt - 0.1 <= t.tt <= t1.tt + 0.1):
            continue
        stamps.append(t.utc_datetime().timestamp())
    return stamps


def find_discrete_events(f, t0, t1, code_sets: Tuple[Tuple[int, ...], ...],
                         previous: bool = False) -> List[Optional[float]]:
    """One skyfield find_discrete scan over [t0, t1]; for each set of event
    codes, the timestamp of the first (or last, if previous) matching event,
    or None.  Used for moon phases and equinoxes/solstices."""
    times, events = skyfield.almanac.find_discrete(t0, t1, f)
    results: List[Optional[float]] = []
    for codes in code_sets:
        stamps = [t.utc_datetime().timestamp() for t, event in zip(times, events) if event in codes]
        results.append((stamps[-1] if previous else stamps[0]) if stamps else None)
    return results


def daylight_seconds(rise: Optional[float], set_: Optional[float],
                     sod_ts: float, eod_ts: float,
                     up_all_day: Callable[[], bool]) -> float:
    """How long a body is above the horizon on the day [sod_ts, eod_ts),
    given its first rise/set of that day.  Handles the polar cases; used by
    the almanac's 'visible'.  up_all_day is only consulted when the body
    never crossed the horizon."""
    if rise is not None and set_ is not None:
        if set_ >= rise:
            return set_ - rise
        # The body was up at the start of the day: it set first, then rose
        # again (e.g., the sun in polar regions, or the moon).
        return (set_ - sod_ts) + (eod_ts - rise)
    if rise is not None:
        # The body rose, but never set.
        return eod_ts - rise
    if set_ is not None:
        # The body set, but never rose.
        return set_ - sod_ts
    # The body neither rose nor set.  Since it never crossed the horizon, it
    # was either up all day or down all day.
    return 86400 if up_all_day() else 0


class InMemorySpiceKernel(skyfield.jpllib.SpiceKernel):
    """A SpiceKernel whose .bsp is read fully into memory (~16 MB for
    DE421) instead of memory-mapped by jplephem.  A mapped ephemeris kills
    the process with SIGBUS if the file is rewritten in place underneath
    it -- which is exactly what 'weectl extension install' over a live
    weewxd does.  Deliberately does not chain to SpiceKernel.__init__
    (that would reopen the path with mmap); it reproduces its assignments
    over an in-memory SPK, whose DAF falls back to plain reads when the
    file object cannot be mapped."""

    def __init__(self, path: str):
        with open(path, 'rb') as f:
            data: bytes = f.read()
        self.path = path
        self.filename = os.path.basename(path)
        self.spk = jplephem.spk.SPK(jplephem.daf.DAF(io.BytesIO(data)))
        self.segments = [skyfield.jpllib.SPICESegment(self, segment)
                         for segment in self.spk.segments]
        self.comments = self.spk.comments


class Sky():
    """The Skyfield engine: the timescale, the JPL ephemeris and the star
    catalog.  Its __init__ never raises: every failure logs and leaves
    valid=False, and the service then simply does nothing."""

    def __init__(self, user_root: str, load_stars: bool = False):
        log.info("Skyfield version: %d.%d." % (skyfield.VERSION[0], skyfield.VERSION[1]))

        self.valid    : bool = False
        self.user_root: str  = user_root

        # find_risings/find_settings arrived in Skyfield 1.47; on anything
        # older every rise/set tag would fail at report time, so decline
        # up front (e.g., Debian 12 packages Skyfield 1.45).
        if tuple(skyfield.VERSION[:2]) < (1, 47):
            log.error('init: weewx-skyfield requires Skyfield 1.47 or later, found %d.%d.'
                      '  The Skyfield almanac will not run.'
                      % (skyfield.VERSION[0], skyfield.VERSION[1]))
            return

        # The timescale is built once and reused; building it parses
        # skyfield's leap second and delta-T tables.
        try:
            self.ts: skyfield.timelib.Timescale = skyfield.api.load.timescale()
        except Exception as e:
            log.error('init: Could not build the skyfield timescale: %s.  The Skyfield almanac will not run.' % e)
            return

        # Load the JPL ephemeris DE421 (covers 1900-2050).  The file is
        # prefixed 'wxskyfield_' so that no other extension can claim (and,
        # on its uninstall, remove) it; skyfield itself does not care about
        # the name.  It is read fully into memory so that an extension
        # install rewriting the file under a running weewxd cannot SIGBUS
        # the process.
        try:
            planets_file: str = '%s/wxskyfield_de421.bsp' % user_root
            self.planets: skyfield.jpllib.SpiceKernel = InMemorySpiceKernel(planets_file)
        except Exception as e:
            log.error('init: Could not load %s: %s.  The Skyfield almanac will not run.' % (planets_file, e))
            return

        # Look up the bodies in the ephemeris.  EPHEMERIS_KEYS is the single
        # source of truth for which bodies are served and their DE421 keys;
        # earth (the observer) is not a target body and stays out of
        # self.orbs, whose keys drive the almanac's body dispatch.
        try:
            orb: str = 'earth'
            self.earth: skyfield.vectorlib.VectorSum = self.planets['earth']
            self.orbs: Dict[str, Any] = {}
            for orb, key in EPHEMERIS_KEYS.items():
                self.orbs[orb] = self.planets[key]
        except Exception as e:
            log.error('init: Could not find %s in ephermis file %s: %s.  The Skyfield almanac will not run.' % (orb, planets_file, e))
            return

        # The span the ephemeris covers (DE421: 1899-07-29 through
        # 2053-10-09), as unix timestamps.  Requests outside it are declined
        # (see covers) so the built-in almanac can serve them.
        try:
            self.start_ts: float = self.ts.tdb_jd(
                max(seg.start_jd for seg in self.planets.spk.segments)).utc_datetime().timestamp()
            self.end_ts: float = self.ts.tdb_jd(
                min(seg.end_jd for seg in self.planets.spk.segments)).utc_datetime().timestamp()
        except Exception as e:
            log.error('init: Could not determine the span of %s: %s.  The Skyfield almanac will not run.' % (planets_file, e))
            return

        # The same bodies as attributes, for readability.
        self.sun    : skyfield.vectorlib.VectorSum = self.orbs['sun']
        self.moon   : skyfield.vectorlib.VectorSum = self.orbs['moon']
        self.mercury: skyfield.vectorlib.VectorSum = self.orbs['mercury']
        self.venus  : skyfield.vectorlib.VectorSum = self.orbs['venus']
        self.mars   : skyfield.vectorlib.VectorSum = self.orbs['mars']
        self.jupiter: skyfield.vectorlib.VectorSum = self.orbs['jupiter']
        self.saturn : skyfield.vectorlib.VectorSum = self.orbs['saturn']
        self.uranus : skyfield.vectorlib.VectorSum = self.orbs['uranus']
        self.neptune: skyfield.vectorlib.VectorSum = self.orbs['neptune']
        self.pluto  : skyfield.vectorlib.VectorSum = self.orbs['pluto']

        # A map of star name to (skyfield.api.Star, magnitude), populated from
        # the Hipparcos catalog when stars are enabled.  hip_<number> entries
        # are added lazily by get_star_by_hip; misses are remembered so a bad
        # tag doesn't rescan the catalog on every report.
        self.stars: Dict[str, Tuple[Any, Optional[float]]] = {}
        self.load_stars: bool = load_stars
        self.hip_misses: set = set()
        if load_stars:
            try:
                self.stars = Sky.load_named_stars(user_root)
                log.info('Loaded %d named stars from the Hipparcos catalog.' % len(self.stars))
            except Exception as e:
                log.error('init: Could not load the Hipparcos star catalog: %s.  Star support disabled.' % e)
                self.load_stars = False

        self.valid = True

    def get_star_by_hip(self, hip: int) -> bool:
        """Load the star with the given Hipparcos number into self.stars
        under the name 'hip_<number>', serving $almanac.hip_57939 style tags
        for any star in the available catalog (the bundled excerpt, or all
        118,218 stars when a full hip_main.dat is installed).  Results,
        including misses, are cached.  Returns whether the star is available."""
        if not self.load_stars:
            return False
        name = 'hip_%d' % hip
        if name in self.stars:
            return True
        if hip in self.hip_misses:
            return False
        # Already loaded under one of its names?  Alias it; no catalog scan.
        for star_name, star_hip in NAMED_STARS.items():
            if star_hip == hip and star_name in self.stars:
                self.stars[name] = self.stars[star_name]
                return True
        try:
            by_hip = Sky.load_stars_by_hip(self.user_root, {hip})
        except Exception as e:
            # An unreadable catalog -- missing, permission-denied, or not
            # text at all (a corrupt or still-compressed hip_main.dat raises
            # UnicodeDecodeError) -- must degrade to a per-tag miss, never
            # propagate into report generation.
            log.error('get_star_by_hip: could not read the star catalog: %s' % e)
            self.hip_misses.add(hip)
            return False
        if hip not in by_hip:
            self.hip_misses.add(hip)
            return False
        self.stars[name] = by_hip[hip]
        return True

    @staticmethod
    def load_named_stars(user_root: str) -> Dict[str, Tuple[Any, Optional[float]]]:
        """Load the stars in NAMED_STARS from the Hipparcos catalog.  The
        bundled excerpt covers exactly these stars (with records identical
        to the full catalog's), so it is read even when a full hip_main.dat
        is installed: scanning 118,218 records at every startup would buy
        nothing."""
        by_hip = Sky.load_stars_by_hip(user_root, set(NAMED_STARS.values()),
                                       prefer_full_catalog=False)
        return {name: by_hip[hip] for name, hip in NAMED_STARS.items() if hip in by_hip}

    @staticmethod
    def load_stars_by_hip(user_root: str, wanted_hips: set,
                          prefer_full_catalog: bool = True) -> Dict[int, Tuple[Any, Optional[float]]]:
        """Load the requested Hipparcos numbers from the star catalog.  By
        default a full hip_main.dat, if present, is preferred, since it
        serves every Hipparcos star, not just the named ones; either file
        stands in for the other when only one is present."""
        first, second = 'hip_main.dat', STAR_FILE
        if not prefer_full_catalog:
            first, second = second, first
        path = '%s/%s' % (user_root, first)
        if not os.path.exists(path):
            path = '%s/%s' % (user_root, second)

        def parse_float(field: str) -> float:
            field = field.strip()
            return float(field) if field else 0.0

        by_hip: Dict[int, Tuple[Any, Optional[float]]] = {}
        with open(path) as f:
            for line in f:
                fields = line.split('|')
                try:
                    hip = int(fields[1])
                except (ValueError, IndexError):
                    continue
                if hip not in wanted_hips:
                    continue
                # A malformed record disables only this star, not the catalog.
                try:
                    if fields[8].strip() and fields[9].strip():
                        ra_degrees = float(fields[8])
                        dec_degrees = float(fields[9])
                    else:
                        # A few Hipparcos entries (e.g., HIP 55203, Alula
                        # Australis, a close binary) have no astrometric
                        # solution; fall back to the identification columns
                        # (right ascension h m s, declination sign-d m s).
                        h, m, s = fields[3].split()
                        ra_degrees = (int(h) + int(m) / 60.0 + float(s) / 3600.0) * 15.0
                        d, dm, ds = fields[4].split()
                        sign = -1.0 if d.startswith('-') else 1.0
                        dec_degrees = sign * (abs(int(d)) + int(dm) / 60.0 + float(ds) / 3600.0)
                    star = skyfield.api.Star(
                        ra_hours=ra_degrees / 15.0,
                        dec_degrees=dec_degrees,
                        ra_mas_per_year=parse_float(fields[12]),
                        dec_mas_per_year=parse_float(fields[13]),
                        parallax_mas=parse_float(fields[11]),
                        epoch=HIPPARCOS_EPOCH_JD)
                    magnitude = float(fields[5]) if fields[5].strip() else None
                except (ValueError, IndexError):
                    continue
                by_hip[hip] = (star, magnitude)
                if len(by_hip) == len(wanted_hips):
                    break
        return by_hip

    @staticmethod
    def get_weewx_config_info(config_dict: Dict[str, Any]) -> str:
        """The user directory: where the ephemeris and star catalog were
        installed."""
        weewx_root: str = config_dict.get('WEEWX_ROOT', '')
        user_root : str = config_dict.get('USER_ROOT', 'bin/user')
        if not user_root.startswith('/'):
            user_root = "%s/%s" % (weewx_root, user_root)
        return user_root

    def is_valid(self) -> bool:
        return self.valid

    def covers(self, time_ts: float) -> bool:
        """Whether the ephemeris covers time_ts, with enough margin for
        the two-day search windows used by rise/set and visible."""
        return self.start_ts + 2 * 86400 <= time_ts <= self.end_ts - 2 * 86400

    def distance_au(self, t: skyfield.timelib.Time, orb: skyfield.vectorlib.VectorSum,
                    origin: Optional[skyfield.vectorlib.VectorSum] = None) -> float:
        """Distance from origin (default: earth) to orb, in astronomical units."""
        position = (origin if origin is not None else self.earth).at(t).observe(orb)
        _, _, distance = position.radec()
        return distance.au

    def get_moon_phase(self, ts: skyfield.timelib.Timescale, pkt_datetime: datetime) -> Tuple[float, float]:
        t: skyfield.timelib.Time = ts.from_datetime(pkt_datetime)

        e = self.earth.at(t)
        s = e.observe(self.sun).apparent()
        m = e.observe(self.moon).apparent()

        _, slon, _ = s.frame_latlon(skyfield.framelib.ecliptic_frame)
        _, mlon, _ = m.frame_latlon(skyfield.framelib.ecliptic_frame)
        phase = (mlon.degrees - slon.degrees) % 360.0

        percent = 100.0 * m.fraction_illuminated(self.sun)

        return phase, percent

    def get_moon_phase_index(self, degrees: float) -> int:
        index: int = int(round((degrees / 360) * 8))
        if index == 8:
            index = 0
        return index

    def rise_set_radius_degrees(self, t: skyfield.timelib.Time, body_name: str, orb,
                                observer) -> float:
        """The body's apparent angular radius for rise/set purposes,
        computed for the date -- sun and moon only (a planet's
        sub-arcsecond radius does not meaningfully move its rise time)."""
        if body_name not in BODY_RADIUS_DEGREES:
            return 0.0
        distance_km = observer.at(t).observe(orb).apparent().distance().km
        return math.degrees(math.asin(BODY_RADIUS_KM[body_name] / distance_km))

#
# Skyfield report almanac.
#
# WeeWX 5.2 introduced extensible almanacs: weewx.almanac.almanacs is a
# prioritized list of AlmanacType objects and Almanac.__getattr__ tries
# each in turn until one does not raise weewx.UnknownType.  By registering
# SkyfieldAlmanacType at the head of that list, report tags such as
# $almanac.sunrise, $almanac.moon.transit and $almanac.next_full_moon are
# computed with Skyfield rather than the built-in PyEphem/weeutil almanac.
# Attributes Skyfield does not handle (e.g., stars when the catalog is
# disabled) fall through to the built-in almanac.
#

# The eight seasonal events reported by skyfield.almanac.seasons are
# 0=vernal equinox, 1=summer solstice, 2=autumnal equinox, 3=winter solstice.
SEASON_EVENTS: Dict[str, Tuple[bool, Tuple[int, ...]]] = {
    'previous_equinox'         : (True,  (0, 2)),
    'next_equinox'             : (False, (0, 2)),
    'previous_solstice'        : (True,  (1, 3)),
    'next_solstice'            : (False, (1, 3)),
    'previous_vernal_equinox'  : (True,  (0,)),
    'next_vernal_equinox'      : (False, (0,)),
    'previous_summer_solstice' : (True,  (1,)),
    'next_summer_solstice'     : (False, (1,)),
    'previous_autumnal_equinox': (True,  (2,)),
    'next_autumnal_equinox'    : (False, (2,)),
    'previous_winter_solstice' : (True,  (3,)),
    'next_winter_solstice'     : (False, (3,)),
}

# skyfield.almanac.moon_phases events are
# 0=new moon, 1=first quarter, 2=full moon, 3=last quarter.
MOON_EVENTS: Dict[str, Tuple[bool, Tuple[int, ...]]] = {
    'previous_new_moon'          : (True,  (0,)),
    'next_new_moon'              : (False, (0,)),
    'previous_first_quarter_moon': (True,  (1,)),
    'next_first_quarter_moon'    : (False, (1,)),
    'previous_full_moon'         : (True,  (2,)),
    'next_full_moon'             : (False, (2,)),
    'previous_last_quarter_moon' : (True,  (3,)),
    'next_last_quarter_moon'     : (False, (3,)),
}

# Mean apparent semidiameters, used when a custom horizon is combined with
# use_center=False (i.e., the upper limb, not the center, crosses the horizon).
BODY_RADIUS_DEGREES: Dict[str, float] = {'sun': 16.0 / 60.0, 'moon': 15.5 / 60.0}

# Skyfield's standard refraction angle at the horizon.
STANDARD_REFRACTION_DEGREES = -34.0 / 60.0

# Equatorial radii in kilometers, used for angular size ($almanac.sun.size,
# $almanac.moon.radius_size, etc.).
BODY_RADIUS_KM: Dict[str, float] = {
    'sun'    : 695700.0,
    'moon'   : 1738.1,
    'mercury': 2440.5,
    'venus'  : 6051.8,
    'mars'   : 3396.2,
    'jupiter': 71492.0,
    'saturn' : 60268.0,
    'uranus' : 25559.0,
    'neptune': 24764.0,
    'pluto'  : 1188.3,
}

# Tag form for addressing any Hipparcos star by number, e.g. $almanac.hip_57939.
HIP_TAG_RE = re.compile(r'hip_(\d+)$')

# Attributes that make no sense for a star (they involve the sun-body
# geometry of a solar system body).  For these, a star goes straight to the
# PyEphem fallback, which raises AttributeError just as PyEphem's own star
# objects do.  earth_distance/sun_distance are not in this set: unlike
# PyEphem, they ARE supported for stars with a measured parallax (e.g.,
# $almanac.proxima_centauri.earth_distance).
STAR_UNSUPPORTED = {'phase', 'moon_fullness',
                    'hlong', 'hlat', 'hlongitude', 'hlatitude'}

# Base class for almanac extensions.  WeeWX versions earlier than 5.2 do not
# have weewx.almanac.AlmanacType, in which case register_almanac declines to
# register (and this base is never exercised).
_AlmanacTypeBase: Any = getattr(weewx.almanac, 'AlmanacType', object)

class SkyfieldAlmanacType(_AlmanacTypeBase):
    """Almanac extension that computes report almanac tags with Skyfield."""

    def __init__(self, sky: Sky):
        self.sky = sky
        self.ts = sky.ts
        # Cache of observers, keyed by (lat, lon, altitude).
        self._observers: Dict[Tuple[float, float, float], Tuple[Any, Any]] = {}

    @property
    def hasExtras(self) -> bool:
        return True

    def location(self, almanac_obj) -> Tuple[Any, Any]:
        """Return (geographic_position, observer) for the almanac's location."""
        key = (almanac_obj.lat, almanac_obj.lon, almanac_obj.altitude)
        if key not in self._observers:
            geographic = skyfield.api.wgs84.latlon(almanac_obj.lat, almanac_obj.lon, elevation_m=almanac_obj.altitude)
            self._observers[key] = (geographic, self.sky.earth + geographic)
        return self._observers[key]

    def skyfield_time(self, time_ts: float) -> skyfield.timelib.Time:
        return self.ts.from_datetime(datetime.fromtimestamp(time_ts, timezone.utc))

    def time_value(self, almanac_obj, time_ts: Optional[float], context: str) -> ValueHelper:
        return ValueHelper(ValueTuple(time_ts, 'unix_epoch', 'group_time'),
                           context=context,
                           formatter=almanac_obj.formatter,
                           converter=almanac_obj.converter)

    def direction_value(self, almanac_obj, degrees: float) -> ValueHelper:
        return ValueHelper(ValueTuple(degrees, 'degree_compass', 'group_direction'),
                           context='ephem_day',
                           formatter=almanac_obj.formatter,
                           converter=almanac_obj.converter)

    def find_event(self, almanac_obj, f, codes: Tuple[int, ...], previous: bool, window_days: int,
                   cache_key: Optional[str] = None) -> ValueHelper:
        """Search for the next (or previous) discrete event of the given type(s).

        With a cache_key (the tag name, e.g. 'next_full_moon'), the found
        event is reused for any almanac time between the time it was
        computed for and the event itself: no event of that kind lies in
        between, or the search would have found it.  These events are
        geocentric, so location plays no part in the key."""
        time_ts = almanac_obj.time_ts
        if cache_key is not None:
            hit = _DAY_CACHE.get(('event', cache_key), _MISS)
            if hit is not _MISS:
                valid_from, valid_to, event_ts = hit
                if valid_from <= time_ts <= valid_to:
                    return self.time_value(almanac_obj, event_ts, 'ephem_year')
        if previous:
            t0 = self.skyfield_time(time_ts - window_days * 86400)
            t1 = self.skyfield_time(time_ts)
        else:
            t0 = self.skyfield_time(time_ts)
            t1 = self.skyfield_time(time_ts + window_days * 86400)
        try:
            event_ts = find_discrete_events(f, t0, t1, (codes,), previous)[0]
        except skyfield.errors.EphemerisRangeError:
            # The search window pokes past the ephemeris' span (the almanac's
            # time itself is inside it, or get_almanac_data would already
            # have declined).  Let the next almanac serve the tag.
            raise weewx.UnknownType('event search outside the ephemeris span')
        if cache_key is not None and event_ts is not None:
            if len(_DAY_CACHE) >= _DAY_CACHE_CAP:
                _DAY_CACHE.clear()
            if previous:
                _DAY_CACHE[('event', cache_key)] = (event_ts, time_ts, event_ts)
            else:
                _DAY_CACHE[('event', cache_key)] = (time_ts, event_ts, event_ts)
        return self.time_value(almanac_obj, event_ts, 'ephem_year')

    def get_almanac_data(self, almanac_obj, attr: str):
        if attr.startswith('__'):
            raise weewx.UnknownType(attr)

        # A time the ephemeris does not cover (DE421: 1899-2053) cannot be
        # computed; decline it so the next almanac (PyEphem or weeutil)
        # serves the tag, rather than EphemerisRangeError aborting report
        # generation.
        if not self.sky.covers(almanac_obj.time_ts):
            raise weewx.UnknownType(attr)

        if attr == 'sunrise':
            return almanac_obj.sun.rise
        elif attr == 'sunset':
            return almanac_obj.sun.set
        elif attr in ('moon_phase', 'moon_index', 'moon_fullness'):
            time_ts = almanac_obj.time_ts
            moon_phase_degrees, percent_illumination = _cached(
                _POS_CACHE, _POS_CACHE_CAP, ('moon_phase', time_ts),
                lambda: self.sky.get_moon_phase(
                    self.ts, datetime.fromtimestamp(time_ts, timezone.utc)))
            if attr == 'moon_fullness':
                return int(percent_illumination + 0.5)
            index = self.sky.get_moon_phase_index(moon_phase_degrees)
            if attr == 'moon_index':
                return index
            return almanac_obj.moon_phases[index]
        elif attr in SEASON_EVENTS:
            previous, codes = SEASON_EVENTS[attr]
            return self.find_event(almanac_obj, skyfield.almanac.seasons(self.sky.planets), codes,
                                   previous, 370, cache_key=attr)
        elif attr in MOON_EVENTS:
            previous, codes = MOON_EVENTS[attr]
            return self.find_event(almanac_obj, skyfield.almanac.moon_phases(self.sky.planets), codes,
                                   previous, 32, cache_key=attr)
        elif attr in ('sidereal_time', 'sidereal_angle'):
            geographic, _ = self.location(almanac_obj)
            degrees = geographic.lst_hours_at(self.skyfield_time(almanac_obj.time_ts)) * 15.0
            if attr == 'sidereal_time':
                return degrees
            return self.direction_value(almanac_obj, degrees)
        elif attr in self.sky.orbs or attr in self.sky.stars:
            return SkyfieldAlmanacBinder(self, almanac_obj, attr)

        # Any Hipparcos star by number: $almanac.hip_57939 (works for every
        # star in the available catalog; install a full hip_main.dat in the
        # user directory to go beyond the bundled named-star excerpt).
        hip_match = HIP_TAG_RE.match(attr)
        if hip_match:
            hip = int(hip_match.group(1))
            if self.sky.get_star_by_hip(hip):
                canonical = 'hip_%d' % hip
                if attr != canonical:
                    # Catalogs zero-pad HIP numbers (e.g. hip_032349); alias
                    # the tag as written to the canonical entry.
                    self.sky.stars[attr] = self.sky.stars[canonical]
                return SkyfieldAlmanacBinder(self, almanac_obj, attr)

        # Not something Skyfield handles (e.g., a star when the Hipparcos
        # catalog is not enabled).  Let the next almanac in
        # weewx.almanac.almanacs (PyEphem or weeutil) take a crack at it.
        raise weewx.UnknownType(attr)

    def separation(self, body1, body2):
        """Angular separation, in radians.  Accepts (longitude, latitude)
        tuples in radians (same contract as weewx.almanac.AlmanacType.separation),
        this almanac's own body binders (e.g.,
        $almanac.separation($almanac.mars, $almanac.venus)), or a mix of the
        two.  Each binder is observed at its own almanac's time.  Anything
        else (e.g., PyEphem Body objects) is deferred to the next almanac
        rather than crashed on."""
        try:
            if isinstance(body1, SkyfieldAlmanacBinder) and isinstance(body2, SkyfieldAlmanacBinder):
                p1 = self.sky.earth.at(self.skyfield_time(body1.almanac.time_ts)).observe(body1.target_body())
                p2 = self.sky.earth.at(self.skyfield_time(body2.almanac.time_ts)).observe(body2.target_body())
                return p1.separation_from(p2).radians
            coords1 = SkyfieldAlmanacType.separation_coordinates(body1)
            coords2 = SkyfieldAlmanacType.separation_coordinates(body2)
        except skyfield.errors.EphemerisRangeError:
            # A binder whose almanac time is outside the ephemeris' span.
            raise weewx.UnknownType('separation')
        if coords1 is None or coords2 is None:
            raise weewx.UnknownType('separation')
        # Meeus 17.1, delegated to the WeeWX base class (only reachable on
        # WeeWX 5.2+, where the base class exists).
        return super().separation(coords1, coords2)

    @staticmethod
    def separation_coordinates(body):
        """A separation argument as (longitude, latitude) in radians: a
        tuple as given, or a binder's apparent geocentric coordinates of
        date (at the binder's own almanac time).  None if unrecognized."""
        if isinstance(body, SkyfieldAlmanacBinder):
            ra_degrees, dec_degrees = body.geocentric_radec_degrees()
            return (math.radians(ra_degrees), math.radians(dec_degrees))
        if isinstance(body, (tuple, list)):
            return body
        return None


class SkyfieldAlmanacBinder:
    """Binds the observer properties held in Almanac with a heavenly body."""

    # Attributes that are returned as ValueHelpers.  Maps attribute name to
    # (computation, ValueTuple flavor), where flavor 'direction' means degrees in
    # degree_compass, and 'angle' means radians in group_angle.
    VALUE_HELPER_ANGLES: Dict[str, Tuple[str, str]] = {
        'azimuth'   : ('az',    'direction'),
        'altitude'  : ('alt',   'angle'),
        'topo_ra'   : ('ra',    'direction'),
        'topo_dec'  : ('dec',   'angle'),
        'astro_ra'  : ('a_ra',  'direction'),
        'astro_dec' : ('a_dec', 'angle'),
        'geo_ra'    : ('g_ra',  'direction'),
        'geo_dec'   : ('g_dec', 'angle'),
        'hlongitude': ('hlong', 'direction'),
        'hlatitude' : ('hlat',  'angle'),
        'elongation': ('elong', 'angle'),
    }

    # Attributes that are returned as plain floats in decimal degrees.
    FLOAT_ANGLES = ('az', 'alt', 'ra', 'dec', 'a_ra', 'a_dec', 'g_ra', 'g_dec', 'hlong', 'hlat', 'elong')

    def __init__(self, almanac_type: SkyfieldAlmanacType, almanac, heavenly_body: str):
        self.almanac_type = almanac_type
        self.almanac = almanac
        self.heavenly_body = heavenly_body
        self.is_star = heavenly_body not in almanac_type.sky.orbs
        self.use_center = False

    def __call__(self, use_center: bool = False):
        self.use_center = use_center
        return self

    def __str__(self):
        # A binder cannot be printed itself.  It always needs an attribute.
        raise AttributeError(self.heavenly_body)

    def target_body(self) -> Any:
        """The skyfield object observed: a planet vector or a Star."""
        sky = self.almanac_type.sky
        if self.is_star:
            return sky.stars[self.heavenly_body][0]
        return sky.orbs[self.heavenly_body]

    def start_of_day_ts(self) -> float:
        """Local midnight of the day containing the almanac's time."""
        return weeutil.weeutil.startOfDay(self.almanac.time_ts)

    def refraction_degrees(self) -> float:
        """Atmospheric refraction at the horizon (negative degrees) for the
        almanac's pressure/temperature, scaled from the standard 34' so that
        WeeWX's defaults (1010 mbar, 15C) give exactly the standard value.
        pressure=0, WeeWX's documented no-refraction idiom, gives 0."""
        return (STANDARD_REFRACTION_DEGREES * (self.almanac.pressure / 1010.0)
                * (288.0 / (273.0 + self.almanac.temperature)))

    def apparent_radius_degrees(self) -> float:
        """The body's apparent angular radius for rise/set purposes,
        evaluated at the start of the almanac's day (so a day's rise and
        set share one horizon)."""
        a = self.almanac
        sod_ts = self.start_of_day_ts()
        key = ('radius', self.heavenly_body, sod_ts, a.lat, a.lon, a.altitude)
        return _cached(_DAY_CACHE, _DAY_CACHE_CAP, key,
                       lambda: self._apparent_radius_degrees(sod_ts))

    def _apparent_radius_degrees(self, sod_ts: float) -> float:
        _, observer = self.almanac_type.location(self.almanac)
        t = self.almanac_type.skyfield_time(sod_ts)
        return self.almanac_type.sky.rise_set_radius_degrees(
            t, self.heavenly_body, self.target_body(), observer=observer)

    def horizon_degrees(self) -> float:
        """The effective horizon for rise/set (and for the all-day up/down
        judgments of visible and circumpolar/neverup, which must use the
        same value).  The default horizon includes refraction, scaled by
        the almanac's pressure/temperature (standard 34 arcminutes at
        standard conditions; pressure=0 turns it off), and the date's
        apparent body radius unless use_center is set.  One formula for
        all conditions: rise/set times vary continuously with pressure.
        A custom horizon is geometric (no refraction), per the USNO
        twilight definitions.  An explicit horizon=0 is indistinguishable
        from the default (WeeWX supplies 0.0 when no horizon is given) and
        gets the default treatment; the geometric crossing of the true
        horizon is available as pressure=0 with use_center=1."""
        if self.almanac.horizon == 0.0:
            refraction = self.refraction_degrees()
            if self.use_center:
                return refraction
            return refraction - self.apparent_radius_degrees()
        h: float = self.almanac.horizon
        if not self.use_center:
            h -= self.apparent_radius_degrees()
        return h

    def find_rise_set(self, rise: bool, start_ts: float, end_ts: float, previous: bool = False) -> Optional[float]:
        a = self.almanac
        horizon = self.horizon_degrees()
        key = ('rise' if rise else 'set', self.heavenly_body,
               start_ts, end_ts, previous, a.lat, a.lon, a.altitude,
               round(horizon / _HORIZON_QUANTUM_DEGREES))
        return _cached(_DAY_CACHE, _DAY_CACHE_CAP, key,
                       lambda: self._find_rise_set(rise, start_ts, end_ts, previous, horizon))

    def _find_rise_set(self, rise: bool, start_ts: float, end_ts: float,
                       previous: bool, horizon: float) -> Optional[float]:
        _, observer = self.almanac_type.location(self.almanac)
        orb = self.target_body()
        t0 = self.almanac_type.skyfield_time(start_ts)
        t1 = self.almanac_type.skyfield_time(end_ts)
        finder = skyfield.almanac.find_risings if rise else skyfield.almanac.find_settings
        times, crosses = finder(observer, orb, t0, t1, horizon_degrees=horizon)
        stamps = stamps_within(times, crosses, t0, t1)
        if not stamps:
            return None
        return stamps[-1] if previous else stamps[0]

    def find_transit(self, antitransit: bool, start_ts: float, end_ts: float, previous: bool = False) -> Optional[float]:
        a = self.almanac
        key = ('antitransit' if antitransit else 'transit', self.heavenly_body,
               start_ts, end_ts, previous, a.lat, a.lon, a.altitude)
        return _cached(_DAY_CACHE, _DAY_CACHE_CAP, key,
                       lambda: self._find_transit(antitransit, start_ts, end_ts, previous))

    def _find_transit(self, antitransit: bool, start_ts: float, end_ts: float,
                      previous: bool) -> Optional[float]:
        geographic, _ = self.almanac_type.location(self.almanac)
        orb = self.target_body()
        t0 = self.almanac_type.skyfield_time(start_ts)
        t1 = self.almanac_type.skyfield_time(end_ts)
        f = skyfield.almanac.meridian_transits(self.almanac_type.sky.planets, orb, geographic)
        times, events = skyfield.almanac.find_discrete(t0, t1, f)
        # meridian_transits reports 1 for an upper (meridian) transit and 0 for
        # a lower (antimeridian) transit.
        wanted = 0 if antitransit else 1
        stamps = stamps_within(times, [event == wanted for event in events], t0, t1)
        if not stamps:
            return None
        return stamps[-1] if previous else stamps[0]

    @property
    def visible(self) -> ValueHelper:
        """How long the body is above the horizon on the almanac's day."""
        sod_ts = self.start_of_day_ts()
        eod_ts = sod_ts + 86400
        rise = self.find_rise_set(True, sod_ts, eod_ts)
        set_ = self.find_rise_set(False, sod_ts, eod_ts)

        def up_all_day() -> bool:
            _, observer = self.almanac_type.location(self.almanac)
            orb = self.target_body()
            alt, _, _ = observer.at(self.almanac_type.skyfield_time(sod_ts)).observe(orb).apparent().altaz()
            return alt.degrees > self.horizon_degrees()

        visible = daylight_seconds(rise, set_, sod_ts, eod_ts, up_all_day)
        return ValueHelper(ValueTuple(visible, 'second', 'group_deltatime'),
                           context='day',
                           formatter=self.almanac.formatter,
                           converter=self.almanac.converter)

    def visible_change(self, days_ago: int = 1) -> ValueHelper:
        """Change in visibility of the heavenly body compared to 'days_ago'."""
        today_visible = self.visible
        # Anchor at local noon minus whole days: subtracting a flat 86400
        # from the almanac's time can land on the wrong calendar day across
        # a DST transition (e.g., 00:30 PDT on the spring-forward day minus
        # 86400 is 23:30 PST two calendar days back).
        then_almanac = self.almanac(
            almanac_time=self.start_of_day_ts() + 43200 - days_ago * 86400)
        then_visible = getattr(then_almanac, self.heavenly_body).visible
        diff_vt = today_visible.value_t - then_visible.value_t
        return ValueHelper(diff_vt,
                           context='hour',
                           formatter=self.almanac.formatter,
                           converter=self.almanac.converter)

    def geocentric_radec_degrees(self) -> Tuple[float, float]:
        """Apparent geocentric (right ascension, declination) of date, in
        decimal degrees.  One observation serves both angles (separation
        needs the pair; two compute_angle calls would observe twice)."""
        key = ('gradec', self.heavenly_body, self.almanac.time_ts)
        return _cached(_POS_CACHE, _POS_CACHE_CAP, key, self._geocentric_radec_degrees)

    def _geocentric_radec_degrees(self) -> Tuple[float, float]:
        sky = self.almanac_type.sky
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        ra, dec, _ = sky.earth.at(t).observe(self.target_body()).apparent().radec('date')
        return ra._degrees, dec.degrees

    def compute_angle(self, attr: str) -> float:
        """Compute the requested angle.  Returned in decimal degrees."""
        a = self.almanac
        # Temperature and pressure only matter for the refracted alt/az, but
        # keying on them unconditionally is merely a few extra cache misses.
        key = ('angle', self.heavenly_body, attr, a.time_ts,
               a.lat, a.lon, a.altitude, a.temperature, a.pressure)
        return _cached(_POS_CACHE, _POS_CACHE_CAP, key,
                       lambda: self._compute_angle(attr))

    def _compute_angle(self, attr: str) -> float:
        sky = self.almanac_type.sky
        orb = self.target_body()
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        if attr in ('az', 'alt'):
            _, observer = self.almanac_type.location(self.almanac)
            apparent = observer.at(t).observe(orb).apparent()
            alt, az, _ = apparent.altaz(temperature_C=self.almanac.temperature,
                                        pressure_mbar=self.almanac.pressure)
            return az.degrees if attr == 'az' else alt.degrees
        elif attr in ('ra', 'dec'):
            # Apparent topocentric right ascension/declination of date.
            _, observer = self.almanac_type.location(self.almanac)
            ra, dec, _ = observer.at(t).observe(orb).apparent().radec('date')
            return ra._degrees if attr == 'ra' else dec.degrees
        elif attr in ('a_ra', 'a_dec'):
            # Astrometric geocentric right ascension/declination (J2000).
            ra, dec, _ = sky.earth.at(t).observe(orb).radec()
            return ra._degrees if attr == 'a_ra' else dec.degrees
        elif attr in ('g_ra', 'g_dec'):
            # Apparent geocentric right ascension/declination of date.
            g_ra, g_dec = self.geocentric_radec_degrees()
            return g_ra if attr == 'g_ra' else g_dec
        elif attr in ('hlong', 'hlat'):
            # Heliocentric ecliptic longitude/latitude.  For the sun itself
            # these are undefined (it sits at the origin); report Earth's
            # heliocentric coordinates instead, per the XEphem convention.
            # For the moon this is its true heliocentric longitude, where
            # PyEphem reports the moon's GEOcentric ecliptic longitude.
            target = sky.earth if self.heavenly_body == 'sun' else orb
            lat, lon, _ = sky.sun.at(t).observe(target).frame_latlon(skyfield.framelib.ecliptic_frame)
            return lon.degrees if attr == 'hlong' else lat.degrees
        elif attr == 'elong':
            # Elongation (angular separation from the sun).
            e = sky.earth.at(t)
            return e.observe(orb).separation_from(e.observe(sky.sun)).degrees
        # Every key in FLOAT_ANGLES/VALUE_HELPER_ANGLES must have a branch
        # above; failing loudly here beats silently answering with the
        # wrong angle.
        raise ValueError('compute_angle: unknown angle %r' % attr)

    def magnitude(self) -> float:
        """Apparent visual magnitude of the body."""
        sky = self.almanac_type.sky
        name = self.heavenly_body
        if self.is_star:
            mag = sky.stars[name][1]
            if mag is None:
                raise AttributeError('mag')
            return mag
        a = self.almanac
        # The moon's magnitude is topocentric; keying every body on location
        # costs nothing.
        key = ('mag', name, a.time_ts, a.lat, a.lon, a.altitude)
        return _cached(_POS_CACHE, _POS_CACHE_CAP, key, self._magnitude)

    def _magnitude(self) -> float:
        sky = self.almanac_type.sky
        name = self.heavenly_body
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        if name == 'sun':
            # The sun's apparent magnitude is -26.74 at one astronomical unit.
            return -26.74 + 5.0 * math.log10(sky.distance_au(t, sky.sun))
        elif name == 'moon':
            # Allen's approximation, plus a correction for the moon's
            # topocentric distance (385000 km is the mean).
            _, observer = self.almanac_type.location(self.almanac)
            apparent = observer.at(t).observe(sky.moon).apparent()
            phase_angle = abs(apparent.phase_angle(sky.sun).degrees)
            return (-12.73 + 0.026 * phase_angle + 4e-9 * phase_angle ** 4
                    + 5.0 * math.log10(apparent.distance().km / 385000.0))
        elif name == 'pluto':
            # Meeus, Astronomical Algorithms: m = -1.00 + 5 log10(r * delta).
            return -1.0 + 5.0 * math.log10(sky.distance_au(t, sky.pluto, origin=sky.sun)
                                           * sky.distance_au(t, sky.pluto))
        else:
            return float(skyfield.magnitudelib.planetary_magnitude(
                sky.earth.at(t).observe(sky.orbs[name])))

    def angular_radius_radians(self) -> float:
        """Apparent (topocentric) angular radius of the body, in radians."""
        if self.is_star:
            return 0.0
        _, observer = self.almanac_type.location(self.almanac)
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        distance_km = observer.at(t).observe(self.target_body()).apparent().distance().km
        return math.asin(BODY_RADIUS_KM[self.heavenly_body] / distance_km)

    def circumpolar_neverup(self) -> Tuple[bool, bool]:
        """Whether the body stays above (circumpolar), or below (neverup),
        the horizon, judged from its current declination.  Uses the same
        effective horizon as find_rise_set (refraction and body radius
        included), so these can never contradict rise/set."""
        dec_degrees = self.compute_angle('dec')
        latitude = self.almanac.lat
        upper_culmination_alt = 90.0 - abs(latitude - dec_degrees)
        lower_culmination_alt = abs(latitude + dec_degrees) - 90.0
        threshold = self.horizon_degrees()
        return (lower_culmination_alt > threshold,
                upper_culmination_alt < threshold)

    def parallactic_angle(self) -> float:
        """Parallactic angle of the body in radians (a method, like PyEphem's,
        so that both $almanac.venus.parallactic_angle and an explicit call
        work in a template)."""
        _, observer = self.almanac_type.location(self.almanac)
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        ha, dec, _ = observer.at(t).observe(self.target_body()).apparent().hadec()
        latitude = math.radians(self.almanac.lat)
        return math.atan2(math.sin(ha.radians),
                          math.tan(latitude) * math.cos(dec.radians)
                          - math.sin(dec.radians) * math.cos(ha.radians))

    def moon_libration(self, attr: str) -> float:
        """Geocentric optical libration of the moon (libration_lat,
        libration_long) and selenographic colongitude of the sun (colong),
        in radians like PyEphem's, per Meeus, Astronomical Algorithms,
        chapter 53.  The physical libration (at most 0.04 degrees) is
        neglected."""
        sky = self.almanac_type.sky
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        T = (t.tt - 2451545.0) / 36525.0
        # Mean elements of the lunar orbit (Meeus ch. 47), in degrees:
        # F, the moon's argument of latitude, and omega, the longitude of
        # the ascending node.  I is the inclination of the mean lunar
        # equator to the ecliptic.
        F = 93.2720950 + 483202.0175233 * T - 0.0036539 * T ** 2 - T ** 3 / 3526000.0 + T ** 4 / 863310000.0
        omega = 125.0445479 - 1934.1362891 * T + 0.0020754 * T ** 2 + T ** 3 / 467441.0 - T ** 4 / 60616000.0
        inc = math.radians(1.54242)

        moon_lat, moon_lon, moon_dist = sky.earth.at(t).observe(sky.moon).apparent().frame_latlon(
            skyfield.framelib.ecliptic_frame)
        if attr == 'colong':
            # The colongitude derives from the selenographic position of
            # the sun: the same formulas, fed the sun's coordinates as seen
            # from the moon (Meeus 53.5).
            sun_lat, sun_lon, sun_dist = sky.earth.at(t).observe(sky.sun).apparent().frame_latlon(
                skyfield.framelib.ecliptic_frame)
            ratio = moon_dist.au / sun_dist.au
            lam = (sun_lon.degrees + 180.0
                   + math.degrees(ratio) * math.cos(moon_lat.radians)
                   * math.sin(math.radians(sun_lon.degrees - moon_lon.degrees)))
            beta = math.radians(ratio * moon_lat.degrees)
        else:
            lam = moon_lon.degrees
            beta = moon_lat.radians
        W = math.radians(lam - omega)
        if attr == 'libration_lat':
            return math.asin(-math.sin(W) * math.cos(beta) * math.sin(inc)
                             - math.sin(beta) * math.cos(inc))
        A = math.atan2(math.sin(W) * math.cos(beta) * math.cos(inc)
                       - math.sin(beta) * math.sin(inc),
                       math.cos(W) * math.cos(beta))
        l = math.degrees(A) - F
        if attr == 'libration_long':
            # Librations stay within +/-8 degrees; normalize to [-180, 180).
            return math.radians((l + 180.0) % 360.0 - 180.0)
        # Selenographic colongitude of the sun (the morning terminator).
        return math.radians((90.0 - l) % 360.0)

    def jupiter_cml(self, attr: str) -> float:
        """Central meridian longitude of Jupiter in System I (equatorial
        belts) or System II (temperate belts), in radians like PyEphem's.
        Computed rigorously: the sub-Earth longitude from the light-time
        corrected geometry and the IAU rotation elements (pole per the IAU
        Working Group on Cartographic Coordinates; System I/II rotation
        rates per the Explanatory Supplement).  Note: PyEphem's values
        differ from the IAU definition by about 0.8 degrees."""
        sky = self.almanac_type.sky
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        astrometric = sky.earth.at(t).observe(sky.jupiter)
        p = astrometric.position.au                # earth -> jupiter, ICRF
        d = (t.tdb - 2451545.0) - astrometric.light_time    # time at Jupiter
        T = d / 36525.0
        a0 = math.radians(268.056595 - 0.006499 * T)        # pole RA
        d0 = math.radians(64.495303 + 0.002413 * T)         # pole dec
        if attr == 'cmlI':
            W = 67.1 + 877.900 * d
        else:
            W = 43.3 + 870.270 * d
        z = numpy.array([math.cos(d0) * math.cos(a0),
                         math.cos(d0) * math.sin(a0),
                         math.sin(d0)])
        node = numpy.cross([0.0, 0.0, 1.0], z)     # ascending node of the equator
        node /= numpy.linalg.norm(node)
        y = numpy.cross(z, node)
        s = -p / numpy.linalg.norm(p)              # jupiter -> earth direction
        theta = math.degrees(math.atan2(numpy.dot(s, y), numpy.dot(s, node)))
        return math.radians((W - theta) % 360.0)

    def saturn_ring_tilt(self, attr: str) -> float:
        """Saturnicentric latitude of the Earth (earth_tilt) or of the Sun
        (sun_tilt) referred to the ring plane, in radians like PyEphem's
        (southern tilts negative), per Meeus, Astronomical Algorithms,
        chapter 45."""
        sky = self.almanac_type.sky
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        T = (t.tt - 2451545.0) / 36525.0
        # Inclination and node of the ring plane, ecliptic of date.
        i = math.radians(28.075216 - 0.012998 * T + 0.000004 * T ** 2)
        node = 169.508470 + 1.394681 * T + 0.000412 * T ** 2
        if attr == 'earth_tilt':
            lat, lon, _ = sky.earth.at(t).observe(sky.saturn).apparent().frame_latlon(
                skyfield.framelib.ecliptic_frame)
        else:
            lat, lon, _ = sky.sun.at(t).observe(sky.saturn).frame_latlon(
                skyfield.framelib.ecliptic_frame)
        return math.asin(math.sin(i) * math.cos(lat.radians) * math.sin(math.radians(lon.degrees - node))
                         - math.cos(i) * math.sin(lat.radians))

    def pyephem_fallback(self, attr: str):
        """Delegate an attribute Skyfield does not compute to the built-in
        PyEphem almanac, if PyEphem is installed."""
        if getattr(weewx.almanac, 'ephem', None) is not None:
            binder = weewx.almanac.AlmanacBinder(self.almanac, self.heavenly_body)
            binder.use_center = self.use_center
            return getattr(binder, attr)
        raise AttributeError("'%s' object has no attribute '%s'" % (self.heavenly_body.capitalize(), attr))

    def __getattr__(self, attr: str):
        """Get the requested observation, such as when the body will rise."""
        # Don't try any attributes that start with a double underscore, or any
        # of these special names: they are used by the Python language:
        if attr.startswith('__') or attr in ['mro', 'im_func', 'func_code']:
            raise AttributeError(attr)

        try:
            return self._evaluate(attr)
        except skyfield.errors.EphemerisRangeError:
            # A search window poking past the ephemeris' span (the almanac's
            # time itself is inside it, or SkyfieldAlmanacType would never
            # have handed out this binder).  PyEphem, if installed, can
            # still answer; without it, a per-tag error -- never an aborted
            # report.
            return self.pyephem_fallback(attr)

    def _evaluate(self, attr: str):
        # For a star, attributes involving sun-body geometry make no sense.
        # PyEphem's own star objects raise AttributeError for these, and the
        # fallback reproduces that behavior.
        if self.is_star and attr in STAR_UNSUPPORTED:
            return self.pyephem_fallback(attr)

        if attr in ('rise', 'set', 'transit'):
            # These verbs refer to the time the event occurs anytime in the
            # day, which is not necessarily the *next* one.  Look forward from
            # local midnight (two days, in case the event does not occur today).
            sod_ts = self.start_of_day_ts()
            if attr == 'transit':
                event_ts = self.find_transit(False, sod_ts, sod_ts + 2 * 86400)
            else:
                event_ts = self.find_rise_set(attr == 'rise', sod_ts, sod_ts + 2 * 86400)
            return self.almanac_type.time_value(self.almanac, event_ts, 'ephem_day')
        elif attr in ('next_rising', 'next_setting', 'previous_rising', 'previous_setting',
                      'next_transit', 'previous_transit', 'next_antitransit', 'previous_antitransit'):
            # These are relative to the time of the almanac.
            time_ts = self.almanac.time_ts
            previous = attr.startswith('previous_')
            if previous:
                start_ts, end_ts = time_ts - 2 * 86400, time_ts
            else:
                start_ts, end_ts = time_ts, time_ts + 2 * 86400
            if attr.endswith('transit'):
                event_ts = self.find_transit(attr.endswith('antitransit'), start_ts, end_ts, previous)
            else:
                event_ts = self.find_rise_set(attr.endswith('rising'), start_ts, end_ts, previous)
            return self.almanac_type.time_value(self.almanac, event_ts, 'ephem_day')
        elif attr in SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES:
            key, flavor = SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES[attr]
            degrees = self.compute_angle(key)
            if flavor == 'direction':
                return self.almanac_type.direction_value(self.almanac, degrees)
            return ValueHelper(ValueTuple(math.radians(degrees), 'radian', 'group_angle'),
                               context='ephem_day',
                               formatter=self.almanac.formatter,
                               converter=self.almanac.converter)
        elif attr in SkyfieldAlmanacBinder.FLOAT_ANGLES:
            return self.compute_angle(attr)
        elif attr == 'moon_fullness' and self.heavenly_body == 'moon':
            # Same computation as 'phase' (percent illuminated).
            return self.phase
        elif attr in ('earth_distance', 'sun_distance'):
            # Supported for planets, and for stars with a measured parallax
            # (a zero parallax puts the star on skyfield's gigaparsec sphere,
            # i.e., its distance is unknown).
            sky = self.almanac_type.sky
            if self.is_star and not sky.stars[self.heavenly_body][0].parallax_mas:
                return self.pyephem_fallback(attr)
            t = self.almanac_type.skyfield_time(self.almanac.time_ts)
            origin = sky.sun if attr == 'sun_distance' else None
            return sky.distance_au(t, self.target_body(), origin=origin)
        elif attr == 'mag':
            return self.magnitude()
        elif attr == 'phase':
            # Percent of the body's surface illuminated by the sun.  The sun
            # illuminates itself: 100, as PyEphem also reports (asking
            # skyfield for the sun's fraction_illuminated by the sun would
            # yield a meaningless ~50).
            if self.heavenly_body == 'sun':
                return 100.0
            sky = self.almanac_type.sky
            t = self.almanac_type.skyfield_time(self.almanac.time_ts)
            return 100.0 * sky.earth.at(t).observe(sky.orbs[self.heavenly_body]).apparent().fraction_illuminated(sky.sun)
        elif attr == 'size':
            # Apparent angular diameter in arcseconds.
            return math.degrees(2.0 * self.angular_radius_radians()) * 3600.0
        elif attr == 'radius':
            # Apparent angular radius in decimal degrees (the old-style name).
            return math.degrees(self.angular_radius_radians())
        elif attr == 'radius_size':
            # Apparent angular radius as a ValueHelper.
            return ValueHelper(ValueTuple(self.angular_radius_radians(), 'radian', 'group_angle'),
                               context='ephem_day',
                               formatter=self.almanac.formatter,
                               converter=self.almanac.converter)
        elif attr in ('circumpolar', 'neverup'):
            circumpolar, neverup = self.circumpolar_neverup()
            return circumpolar if attr == 'circumpolar' else neverup
        elif attr in ('libration_lat', 'libration_long', 'colong') and self.heavenly_body == 'moon':
            return self.moon_libration(attr)
        elif attr in ('cmlI', 'cmlII') and self.heavenly_body == 'jupiter':
            return self.jupiter_cml(attr)
        elif attr in ('earth_tilt', 'sun_tilt') and self.heavenly_body == 'saturn':
            return self.saturn_ring_tilt(attr)
        elif attr == 'name':
            return self.heavenly_body.replace('_', ' ').title()

        # Something Skyfield does not compute (e.g., the moon's subsolar
        # latitude).  Fall back to the built-in PyEphem almanac if PyEphem
        # is installed.
        return self.pyephem_fallback(attr)


def register_almanac(sky: Sky) -> bool:
    """Register the Skyfield almanac at the head of WeeWX's almanac list, so
    that reports use Skyfield.  Requires WeeWX 5.2 or later."""
    if not hasattr(weewx.almanac, 'almanacs') or not hasattr(weewx.almanac, 'AlmanacType'):
        log.info('This version of WeeWX (%s) does not support almanac extensions'
                 ' (WeeWX 5.2 or later is required).  Reports will not use Skyfield.' % weewx.__version__)
        return False
    # Remove any previously registered instance (e.g., after an engine restart),
    # then insert at the head of the list so Skyfield takes priority.  Match on
    # module as well as class name: the weewx-celestial and weewx-skyfield-almanac
    # extensions also name their almanac class SkyfieldAlmanacType and must not
    # be removed.
    weewx.almanac.almanacs[:] = [a for a in weewx.almanac.almanacs
                                 if not (type(a).__name__ == 'SkyfieldAlmanacType'
                                         and type(a).__module__ == __name__)]
    weewx.almanac.almanacs.insert(0, SkyfieldAlmanacType(sky))
    return True
