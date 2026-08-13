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

import gzip
import io
import logging
import math
import os
import re
import sys
import threading
import time
import urllib.request

from datetime import datetime
from datetime import timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import jplephem.daf
import jplephem.spk
import numpy

import skyfield
import skyfield.almanac
import skyfield.api
import skyfield.eclipselib
import skyfield.errors
import skyfield.framelib
import skyfield.jpllib
import skyfield.constants
import skyfield.data.spice
import skyfield.keplerlib
import skyfield.magnitudelib
import skyfield.searchlib
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

WXSKYFIELD_VERSION = '2.1.3'

if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 9):
    raise weewx.UnsupportedFeature(
        "weewx-skyfield requires Python 3.9 or later, found %s.%s" % (sys.version_info[0], sys.version_info[1]))

def reraise_if_terminate(e: BaseException) -> None:
    """weewxd stops by raising Terminate from its SIGTERM signal handler --
    inside whatever the main thread is executing at that instant.  This
    extension's main-thread exposure is Sky.__init__, which the service runs
    at engine startup; every broad exception handler there must call this
    first and hand the exception back, or weewx cannot shut down.  (Almanac
    tags are evaluated during report generation, on a child thread that
    never receives signals.)  weewxd runs as __main__, so its Terminate
    class cannot be imported here and is recognized by name."""
    if type(e).__name__ == 'Terminate':
        raise e


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
        # [Skyfield] has exactly three options and two subsections.
        # Anything else here is a mistake -- most likely a report option
        # that belongs under [StdReport] [[SkyfieldReport]] -- and would
        # otherwise be silently ignored.
        for key in skyfield_config_dict:
            if key not in ('enable', 'satellite_downloads', 'Satellites',
                           'comet_downloads', 'Comets'):
                if key == 'stars':
                    hint = (' (removed in 2.0: the complete Hipparcos catalog now'
                            ' ships with the extension and stars are always available)')
                elif key in ('star_mag_limit', 'star_label_mag',
                             'constellation_lines', 'theme', 'lang'):
                    hint = ' (a report option: put it under [StdReport] [[SkyfieldReport]])'
                else:
                    hint = ''
                log.warning('Ignoring unrecognized [Skyfield] option: %s%s' % (key, hint))
        enable = to_bool(skyfield_config_dict.get('enable', True))
        if enable:
            log.info("WxSkyfield status: enabled...continuing.")
        else:
            log.info("WxSkyfield status: disabled...enable it in the Skyfield section of weewx.conf.")
            return

        user_root = Sky.get_weewx_config_info(config_dict)
        log.info("user_root: %s" % user_root)

        satellites = parse_satellites(skyfield_config_dict)
        sat_dir = get_sat_dir(config_dict) if satellites else None
        self.sat_downloads = to_bool(skyfield_config_dict.get('satellite_downloads', True))
        if satellites:
            log.info('satellites: %s (elements cached in %s; downloads %s)'
                     % (', '.join('%s=%d' % (n, c) for n, c in satellites.items()),
                        sat_dir, 'on' if self.sat_downloads else 'off'))

        comets = parse_comets(skyfield_config_dict, satellites)
        comet_dir = get_sat_dir(config_dict) if comets else None
        self.comet_downloads = to_bool(skyfield_config_dict.get('comet_downloads', True))
        if comets:
            log.info('comets: %s (elements cached in %s; downloads %s)'
                     % (', '.join('%s=%s' % (n, d) for n, d in comets.items()),
                        comet_dir, 'on' if self.comet_downloads else 'off'))

        self.sky = Sky(user_root, load_stars=True,
                       satellites=satellites, sat_dir=sat_dir,
                       comets=comets, comet_dir=comet_dir)
        if self.sky.is_valid():
            if register_almanac(self.sky):
                log.info('Skyfield almanac registered; reports will use Skyfield for almanac computations.')
            # Keeping the satellite elements fresh is the service's only
            # recurring job (a pure almanac needs no events at all): at
            # the engine's STARTUP event and then each archive record,
            # stale cache files are refreshed on a worker thread.  The
            # STARTUP check is what makes a satellite just added to the
            # config live within seconds of a restart instead of one
            # archive interval in; the constructor itself still spawns
            # nothing, and the main thread never touches the network.
            self._sat_thread: Optional[threading.Thread] = None
            self._sat_retry_ts: Dict[int, float] = {}
            self._sat_retry_delay: Dict[int, float] = {}
            if satellites and self.sat_downloads:
                self.bind(weewx.STARTUP, self.refresh_satellite_elements)
                self.bind(weewx.NEW_ARCHIVE_RECORD, self.refresh_satellite_elements)
            # The comet elements get the same treatment, as a parallel
            # trio rather than a generalization (one file, so the backoff
            # state is a pair of scalars, and the tested satellite path
            # stays untouched).
            self._comet_thread: Optional[threading.Thread] = None
            self._comet_retry_ts = 0.0
            self._comet_retry_delay = float(COMET_RETRY_BASE_SECS)
            if comets and self.comet_downloads:
                self.bind(weewx.STARTUP, self.refresh_comet_elements)
                self.bind(weewx.NEW_ARCHIVE_RECORD, self.refresh_comet_elements)

    def refresh_satellite_elements(self, event) -> None:
        """Refresh any stale satellite elements, on a worker thread so a
        slow CelesTrak can never delay startup or the archive cycle.
        Bound to STARTUP -- a just-added satellite gets its elements
        right away, not one archive interval in -- and to every
        NEW_ARCHIVE_RECORD.  Never raises."""
        try:
            if self._sat_thread is not None and self._sat_thread.is_alive():
                return
            due = self.stale_satellites(time.time())
            if not due:
                return
            self._sat_thread = threading.Thread(target=self._fetch_worker,
                                                args=(due,), daemon=True,
                                                name='wxskyfield-tle')
            self._sat_thread.start()
        except Exception as e:
            log.error('refresh_satellite_elements: could not start the element fetch: %s' % e)

    def stale_satellites(self, now: float) -> List[int]:
        """The NORAD numbers whose cache files are due for a fetch: file
        mtime older than the refresh cadence, or no file at all (a
        satellite added to the config later, or an install that was
        offline) -- maximally stale, fetched at the first archive cycle.
        A number inside its failure backoff window is skipped.  Checks
        are age-driven, not schedule-driven, so a weewxd started after a
        long stop refreshes immediately."""
        due: List[int] = []
        for norad in sorted(set(self.sky.satellites.values())):
            if now < self._sat_retry_ts.get(norad, 0.0):
                continue
            try:
                mtime = os.stat(self.sky.sat_path(norad)).st_mtime
            except OSError:
                mtime = None
            if mtime is None or now - mtime >= SAT_REFRESH_SECS:
                due.append(norad)
        return due

    def _fetch_worker(self, norads: List[int]) -> None:
        """Fetch each due element set.  A failure keeps the old file (the
        fetcher is atomic) and backs off: retry in five minutes, doubling
        per consecutive failure up to the normal three-hour cadence, so a
        recovered network refreshes quickly without hammering CelesTrak.
        In-memory backoff state resetting on restart (to try-now) is
        correct.  Never raises -- and never touches the engine: weewxd's
        shutdown does not wait for daemon threads."""
        for norad in norads:
            try:
                assert self.sky.sat_dir is not None
                os.makedirs(self.sky.sat_dir, exist_ok=True)
                fetch_satellite_elements(norad, self.sky.sat_path(norad))
                self._sat_retry_ts.pop(norad, None)
                self._sat_retry_delay.pop(norad, None)
                log.info('Fetched satellite elements for %d.' % norad)
            except Exception as e:
                delay = min(self._sat_retry_delay.get(norad, SAT_RETRY_BASE_SECS),
                            float(SAT_REFRESH_SECS))
                self._sat_retry_ts[norad] = time.time() + delay
                self._sat_retry_delay[norad] = delay * 2
                log.warning('Could not fetch satellite elements for %d (%s);'
                            ' keeping the cached elements, next try in %d minutes.'
                            % (norad, e, delay // 60))

    def refresh_comet_elements(self, event) -> None:
        """Refresh the CometEls cache file when stale, on a worker thread
        so a slow MPC can never delay startup or the archive cycle.
        Bound to STARTUP and NEW_ARCHIVE_RECORD like the satellite
        refresher; the cadence is days, not hours -- two-body comet
        elements stay serviceable for months.  Never raises."""
        try:
            if self._comet_thread is not None and self._comet_thread.is_alive():
                return
            if not self.comet_stale(time.time()):
                return
            self._comet_thread = threading.Thread(target=self._comet_fetch_worker,
                                                  daemon=True,
                                                  name='wxskyfield-comets')
            self._comet_thread.start()
        except Exception as e:
            log.error('refresh_comet_elements: could not start the element fetch: %s' % e)

    def comet_stale(self, now: float) -> bool:
        """Whether the CometEls cache file is due for a fetch: mtime older
        than the refresh cadence, or no file at all -- maximally stale.
        Inside the failure backoff window, never due.  Age-driven, not
        schedule-driven, like stale_satellites."""
        if now < self._comet_retry_ts:
            return False
        try:
            mtime = os.stat(self.sky.comet_path()).st_mtime
        except OSError:
            return True
        return now - mtime >= COMET_REFRESH_SECS

    def _comet_fetch_worker(self) -> None:
        """Fetch the CometEls file.  A failure keeps the old file (the
        fetcher is atomic) and backs off: retry in five minutes, doubling
        per consecutive failure up to the normal cadence.  Never raises,
        never touches the engine."""
        try:
            assert self.sky.comet_dir is not None
            os.makedirs(self.sky.comet_dir, exist_ok=True)
            fetch_comet_elements(self.sky.comet_path())
            self._comet_retry_ts = 0.0
            self._comet_retry_delay = float(COMET_RETRY_BASE_SECS)
            log.info('Fetched comet elements into %s.' % self.sky.comet_path())
        except Exception as e:
            delay = min(self._comet_retry_delay, float(COMET_REFRESH_SECS))
            self._comet_retry_ts = time.time() + delay
            self._comet_retry_delay = delay * 2
            log.warning('Could not fetch comet elements (%s); keeping the'
                        ' cached elements, next try in %d minutes.'
                        % (e, delay // 60))

# Named stars available as report almanac tags (e.g., $almanac.rigel.rise)
# unless disabled (stars = false in [Skyfield]).  Maps the tag name to the
# star's Hipparcos catalog number.  The names are the IAU Catalog of Star
# Names (the Working Group on Star Names' IAU-CSN list, 2022 edition; every
# entry with a Hipparcos number), plus PyEphem's star catalog names for
# backward compatibility (a few of which are legacy spellings of the same
# stars: albereo, alcaid, sirrah, etc.).  Multi-word names use underscores
# and diacritics are dropped, since a report tag must be an identifier
# ($almanac.barnards_star, $almanac.kaus_australis).  The stars themselves
# are read from wxskyfield_stars.dat.gz, the complete Hipparcos Catalogue
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

# The complete Hipparcos Catalogue -- all 118,218 records of hip_main.dat,
# gzipped and unmodified -- installed alongside wxskyfield.py (like the
# ephemeris).  Through 1.19 this was a ~400-star excerpt and the full
# catalog was a user-supplied download; as of 2.0 everyone has the whole
# sky.  The scan is sequential and rare (once per need, cached for the
# life of the engine), so the file is read straight through gzip.
STAR_FILE = 'wxskyfield_stars.dat.gz'
# The constellation line figures drawn by the Sky page's dome: per line one
# polyline -- the IAU constellation abbreviation, then the Hipparcos numbers
# of its vertices in draw order.  Distilled from the Stellarium project's
# "modern" sky culture (CC BY-SA 4.0); the excerpt above carries a record
# for every vertex.
LINES_FILE = 'wxskyfield_lines.dat'
# The Hipparcos catalog's positions are for epoch J1991.25.  This is that
# epoch as a TT Julian date, matching skyfield.data.hipparcos.load_dataframe.
HIPPARCOS_EPOCH_JD = 1721045.0 + 1991.25 * 365.25

REPO_URL = 'https://github.com/chaunceygardiner/weewx-skyfield'

# ── satellites ───────────────────────────────────────────────────────────────
# [Skyfield] [[Satellites]] maps tag names to NORAD catalog numbers
# (iss = 25544); that one list drives both the report tags
# ($almanac.iss.next_pass.rise) and the fetch list.  Orbital elements (TLEs)
# are fetched per satellite from CelesTrak and cached as plain files,
# wxskyfield_sat_<norad>.tle, in SAT_DIR_NAME under the station's SQLITE_ROOT
# -- TLEs are already a file format Skyfield reads directly, staleness is
# mtime, and `cat` works when debugging.  The service refreshes them on a
# worker thread at STARTUP and each NEW_ARCHIVE_RECORD (weewxd's only
# network access in this extension -- satellite_downloads = false turns it
# off, leaving the files for the user to maintain).
CELESTRAK_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=%d&FORMAT=TLE'
SAT_DIR_NAME = 'wxskyfield'
SAT_FILE_FORMAT = 'wxskyfield_sat_%d.tle'
# CelesTrak identifies polite clients by software, so abuse reports can
# reach the author; the repo URL does that.  Deliberately no per-machine
# identifier: hostnames are often personal.
SAT_USER_AGENT = 'weewx-skyfield/%s (+%s)' % (WXSKYFIELD_VERSION, REPO_URL)
# Refresh cadence.  CelesTrak regenerates element sets about every two
# hours; three is polite, and each install's archive-cycle phase spreads
# the fleet's fetches.  A failed fetch retries sooner -- the next archive
# cycle, doubling from five minutes up to this same cadence -- so a
# recovered network refreshes quickly and CelesTrak is never hammered.
SAT_REFRESH_SECS = 3 * 3600
SAT_RETRY_BASE_SECS = 300
# Elements whose epoch is older than this cannot be trusted for pass
# times: plain SGP4 drift is only seconds at a week, but a reboost or
# maneuver accumulates minutes of error per week after it -- missed-pass
# territory.  Age is measured from the TLE epoch, never the file mtime (a
# "successful" fetch of stale data must not reset the clock).  Past the
# cutoff every satellite tag reports the unified no-usable-elements state:
# empty ValueHelpers ("N/A"), None for the plain-value tags.
SAT_MAX_ELEMENT_AGE_SECS = 7 * 86400
# A pass is visible when the satellite is sunlit while the observer is in
# at least civil twilight (sun below -6 degrees geometric, the
# Heavens-Above convention), sampled at rise, culmination and set --
# whole-pass sampling catches the mid-pass fade-out into Earth's shadow.
# next_visible_pass additionally requires a culmination of at least 10
# degrees (a go-watch recommendation, not a bare fact like next_pass).
SAT_DARK_SUN_ALT_DEGREES = -6.0
SAT_VISIBLE_MIN_CULMINATION_DEGREES = 10.0

# Tag form addressing a LISTED satellite by number, e.g. $almanac.sat_25544.
# Unlike hip_<number> (whose whole catalog is on disk), this is only an
# alternate spelling for a satellite already in [[Satellites]] -- it never
# triggers a fetch of an unlisted one.
SAT_TAG_RE = re.compile(r'sat_(\d+)$')

# ── comets ───────────────────────────────────────────────────────────────────
# One MPC CometEls.txt file (~160 KB, every comet with a current orbit -- 953
# rows in August 2026) serves ALL configured comets, cached beside the
# satellite TLEs under get_sat_dir.  [Skyfield] [[Comets]] maps tag names to
# MPC designations (halley = 1P, hale_bopp = C/1995 O1); the friendly name is
# the config KEY, and the value is matched against the file's readable
# designation column after case/whitespace normalization ONLY -- no fuzzy
# names, no packed designations, fragments named explicitly (C/1947 X1-B).
COMET_URL = 'https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt'
COMET_FILE = 'wxskyfield_comets.txt'

# MPC recomputes the file continuously, but unlike satellite TLEs (useless
# after days) two-body comet elements stay serviceable for months: refresh on
# the scale of days, not hours -- and there is no usability gate at all, only
# the elements_epoch/elements_age diagnostics.
COMET_REFRESH_SECS = 2 * 86400
COMET_RETRY_BASE_SECS = 300

# Periodic-comet readable designations start "12P/", "220P/", "73P-B/" (and
# D for defunct, I for interstellar); everything else is the "C/1995 O1
# (Hale-Bopp)" shape whose parenthesized name is decoration.
COMET_PERIODIC_RE = re.compile(r'\d+[PDI]\b')


class CometRow(NamedTuple):
    """The orbital elements of one CometEls.txt row."""
    designation_key: str        # normalized match key, e.g. 'C/1995 O1'
    designation_full: str       # the readable column verbatim (stripped)
    q: float                    # perihelion distance, AU
    e: float                    # eccentricity
    incl: float                 # inclination, degrees
    node: float                 # longitude of the ascending node, degrees
    argp: float                 # argument of perihelion, degrees
    peri_year: int              # time of perihelion passage (TT)
    peri_month: int
    peri_day: float
    g: Optional[float]          # absolute total magnitude (blank in some rows)
    k: Optional[float]          # magnitude slope parameter
    epoch_ts: Optional[float]   # perturbed-epoch column, or None when blank


def normalize_comet_designation(text: Any) -> str:
    """Case and whitespace normalization -- the ONLY liberty taken when
    matching a [[Comets]] value against the file's designation column."""
    return ' '.join(str(text).split()).upper()


def comet_designation_key(readable: str) -> str:
    """Reduce the readable designation column to the designation itself:
    '12P/Pons-Brooks' -> '12P', 'C/1995 O1 (Hale-Bopp)' -> 'C/1995 O1',
    fragments intact ('73P-B/Schwassmann-Wachmann' -> '73P-B')."""
    text = readable.strip()
    if COMET_PERIODIC_RE.match(text):
        text = text.split('/', 1)[0]
    else:
        text = re.sub(r'\s*\(.*\)\s*$', '', text)
    return normalize_comet_designation(text)


def parse_comet_row(line: str) -> CometRow:
    """Parse one CometEls.txt row (the 80-column orbital elements plus the
    readable designation; format per
    https://www.minorplanetcenter.net/iau/info/CometOrbitFormat.html).
    Raises ValueError on a malformed row -- the caller disables only that
    comet, hip_main-parser spirit."""
    designation_full = line[102:158].strip()
    if not designation_full:
        raise ValueError('no designation')

    def opt_float(field: str) -> Optional[float]:
        field = field.strip()
        return float(field) if field else None

    epoch_field = line[81:89].strip()
    epoch_ts: Optional[float] = None
    if len(epoch_field) == 8 and epoch_field.isdigit():
        try:
            epoch_ts = datetime(int(epoch_field[:4]), int(epoch_field[4:6]),
                                int(epoch_field[6:8]), tzinfo=timezone.utc).timestamp()
        except ValueError:
            epoch_ts = None
    return CometRow(
        designation_key=comet_designation_key(designation_full),
        designation_full=designation_full,
        q=float(line[30:39]),
        e=float(line[41:49]),
        incl=float(line[71:79]),
        node=float(line[61:69]),
        argp=float(line[51:59]),
        peri_year=int(line[14:18]),
        peri_month=int(line[19:21]),
        peri_day=float(line[22:29]),
        g=opt_float(line[91:95]),
        k=opt_float(line[96:100]),
        epoch_ts=epoch_ts,
    )


def parse_comets(skyfield_config_dict: Dict[str, Any],
                 satellites: Dict[str, int]) -> Dict[str, str]:
    """The [Skyfield] [[Comets]] section as {tag name: normalized
    designation}.  Mirrors parse_satellites: a bad entry disables only
    itself, and a name that is already an almanac tag -- a body, a star,
    the hip_/sat_ spellings, or a configured satellite (satellites
    dispatch first, so a duplicate would silently shadow the comet) -- is
    refused with an error naming it."""
    comets: Dict[str, str] = {}
    for name, value in (skyfield_config_dict.get('Comets', {}) or {}).items():
        tag = str(name).lower()
        designation = normalize_comet_designation(value)
        if not designation:
            log.error('Ignoring [Skyfield] [[Comets]] entry %s = %r: empty'
                      ' designation.' % (name, value))
            continue
        if (tag in EPHEMERIS_KEYS or tag in NAMED_STARS or HIP_TAG_RE.match(tag)
                or SAT_TAG_RE.match(tag) or tag in ('sun', 'earth')
                or tag in satellites):
            log.error('Ignoring [Skyfield] [[Comets]] entry %s: the name is'
                      ' already an almanac tag.' % name)
            continue
        comets[tag] = designation
    return comets


def fetch_comet_elements(path: str, timeout: float = 30.0) -> None:
    """Download CometEls.txt from the MPC into path.  Validates before any
    write -- the payload must contain at least one parseable comet row,
    never the CONFIGURED designations (a vanishing row is a tag-time
    concern, not a download failure).  The write is atomic (temp file +
    os.replace), so report threads never see a partial file; raises on any
    failure, leaving the previous file in place -- callers own backoff."""
    request = urllib.request.Request(COMET_URL,
                                     headers={'User-Agent': SAT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode('ascii', 'replace')
    for line in payload.splitlines():
        try:
            parse_comet_row(line)
            break
        except ValueError:
            continue
    else:
        raise ValueError('no parseable comet rows in the downloaded file')
    tmp_path = '%s.tmp' % path
    with open(tmp_path, 'w') as f:
        f.write(payload)
    os.replace(tmp_path, path)


# ── meteor showers ───────────────────────────────────────────────────────────
# The dozen MAJOR annual showers of the IMO working list.  Each peak is
# anchored to the SUN'S ECLIPTIC LONGITUDE, the way meteor astronomy
# states it -- the Perseids peak when the sun reaches 140.0 degrees,
# whatever the calendar says -- so each year's peak instant is COMPUTED
# from the ephemeris, never looked up, and the table needs no annual
# maintenance.  Radiants are the peak-date positions (J2000); ZHR is the
# nominal zenithal hourly rate; the activity window is in solar
# longitude too (none of the twelve spans the March-equinox wrap).
# A closed, named set like the constellations: display names translate
# through [Almanac] [[MeteorShowers]], keyed by the snake_case key,
# while .name stays stable English data.
class MeteorShower(NamedTuple):
    key: str
    name: str
    peak_lambda: float      # solar longitude of the peak, degrees
    start_lambda: float     # activity window, solar longitudes
    end_lambda: float
    radiant_ra: float       # radiant at peak, degrees, J2000
    radiant_dec: float
    zhr: int
    parent: str             # the parent body whose debris it is


METEOR_SHOWERS: Tuple[MeteorShower, ...] = (
    MeteorShower('quadrantids', 'Quadrantids', 283.16, 276.5, 291.0,
                 230.0, 48.5, 110, '(196256) 2003 EH1'),
    MeteorShower('lyrids', 'Lyrids', 32.32, 24.4, 40.0,
                 271.0, 33.5, 18, 'C/1861 G1 (Thatcher)'),
    MeteorShower('eta_aquariids', 'Eta Aquariids', 45.5, 29.0, 68.0,
                 338.0, -1.0, 50, '1P/Halley'),
    MeteorShower('delta_aquariids', 'Southern Delta Aquariids', 126.9, 109.0, 150.0,
                 340.0, -16.0, 25, '96P/Machholz'),
    MeteorShower('perseids', 'Perseids', 140.0, 114.5, 151.4,
                 48.0, 58.0, 100, '109P/Swift-Tuttle'),
    MeteorShower('draconids', 'Draconids', 195.4, 193.0, 197.0,
                 262.0, 54.0, 10, '21P/Giacobini-Zinner'),
    MeteorShower('orionids', 'Orionids', 208.0, 189.0, 225.0,
                 95.0, 15.5, 20, '1P/Halley'),
    MeteorShower('southern_taurids', 'Southern Taurids', 223.0, 167.0, 238.0,
                 52.0, 15.0, 5, '2P/Encke'),
    MeteorShower('northern_taurids', 'Northern Taurids', 230.0, 206.0, 258.0,
                 58.0, 22.0, 5, '2P/Encke'),
    MeteorShower('leonids', 'Leonids', 235.27, 224.0, 248.0,
                 152.0, 21.8, 15, '55P/Tempel-Tuttle'),
    MeteorShower('geminids', 'Geminids', 262.2, 252.0, 265.5,
                 112.0, 32.5, 150, '(3200) Phaethon'),
    MeteorShower('ursids', 'Ursids', 270.7, 265.0, 274.5,
                 217.0, 75.8, 10, '8P/Tuttle'),
)


class _SunLongitudeCrossed:
    """Whether the sun's longitude has passed target (within a half-turn),
    shaped for skyfield's find_discrete (a vectorized callable carrying
    step_days): flips False -> True as the longitude ascends through the
    target -- the shower-peak crossing."""

    step_days = 30.0

    def __init__(self, almanac_type: Any, target: float):
        self.almanac_type = almanac_type
        self.target = target

    def __call__(self, t: skyfield.timelib.Time) -> Any:
        return (self.almanac_type.sun_longitude_degrees(t) - self.target) % 360.0 < 180.0


_NO_TEXTS: Dict[str, Any] = {}


def almanac_texts(almanac_obj: Any) -> Dict[str, Any]:
    """The report's [Almanac] section (moon phase names, body names,
    constellation names), or {} on a WeeWX that has none.

    WeeWX 5.3 gave Almanac a .texts instance attribute carrying the whole
    section; through 5.2 -- the version this extension still supports --
    there is no such attribute, and label translation simply does not
    happen there.

    Read through __dict__ deliberately, NOT getattr: on 5.2 the attribute
    lookup does not fail, so a getattr default never fires.  It falls
    through Almanac.__getattr__, which walks weewx.almanac.almanacs (ours
    declines 'texts' with UnknownType, correctly) until PyEphem's
    catch-all treats any unrecognized name as a heavenly body and returns
    a truthy AlmanacBinder for a body called "texts" -- which then raises
    AttributeError one attribute later, on .get.  Without PyEphem the
    lookup raises instead.  __dict__.get bypasses __getattr__ entirely and
    is plainly None before 5.3.  The isinstance also absorbs a malformed
    [Almanac] section, and the __dict__ default a __slots__ object -- the
    Sky page's labels are contracted to survive a foreign almanac.
    """
    texts = getattr(almanac_obj, '__dict__', _NO_TEXTS).get('texts')
    return texts if isinstance(texts, dict) else {}


class MeteorShowerInfo:
    """One shower as $almanac.next_meteor_shower (and each item of
    $almanac.active_meteor_showers) serves it: plain pre-computed
    attributes, never methods, so loopdata's plain-getattr chains walk it.
    name is stable English data; label is the report's [Almanac]
    [[MeteorShowers]] translation, falling back to the name."""

    def __init__(self, almanac_type: 'SkyfieldAlmanacType', almanac_obj,
                 shower: MeteorShower, peak_ts: Optional[float]):
        self.key = shower.key
        self.name = shower.name
        labels = almanac_texts(almanac_obj).get('MeteorShowers')
        self.label = (labels.get(shower.key, shower.name)
                      if isinstance(labels, dict) else shower.name)
        self.peak = almanac_type.time_value(almanac_obj, peak_ts, 'ephem_year')
        self.zhr = shower.zhr
        self.parent = shower.parent
        self.radiant_ra = shower.radiant_ra
        self.radiant_dec = shower.radiant_dec
        alt, az = almanac_type.radiant_altaz(almanac_obj, shower.radiant_ra,
                                             shower.radiant_dec)
        self.radiant_alt = alt
        self.radiant_az = az


# Astronomical units per light year (IAU 2015 definitions).
AU_PER_LIGHT_YEAR = 63241.077

# Kilometers per astronomical unit (IAU 2012 definition of the au).
KM_PER_AU = 149597870.7


def register_units() -> None:
    """Register the astronomical-unit plumbing with WeeWX's unit system.

    The distance/distance_from_sun ValueHelper twins report in
    group_distance_astronomical, whose display unit is the astronomical
    unit in EVERY unit system -- interplanetary distances read naturally
    in AU, not in ten-digit kilometers -- with conversions registered so
    $almanac.mars.distance.km and .mile answer on ask (and skins can
    override the group's unit wholesale via [Units] [[Groups]]).

    Runs at module import, not service startup: weewx-loopdata parses
    almanac fields against the unit system at its own service start, and
    service ordering in weewx.conf must not decide whether the group
    exists yet.  Re-registration (the module imports both as
    user.wxskyfield and wxskyfield under the test suite) is harmless:
    every write is an idempotent dict assignment.
    """
    for group_dict in (weewx.units.USUnits, weewx.units.MetricUnits,
                       weewx.units.MetricWXUnits):
        group_dict['group_distance_astronomical'] = 'astronomical_unit'
    # WeeWX 5.5 ships these conversions itself; this extension runs on 5.2+,
    # so register them unconditionally (same IAU factor, harmless overwrite).
    weewx.units.conversionDict.setdefault('astronomical_unit', {}).update({
        'km'   : lambda x: x * KM_PER_AU,
        'meter': lambda x: x * KM_PER_AU * 1000.0,
        'mile' : lambda x: x * KM_PER_AU / 1.609344,
    })
    weewx.units.conversionDict['km']['astronomical_unit'] = lambda x: x / KM_PER_AU
    weewx.units.conversionDict['meter']['astronomical_unit'] = lambda x: x / (KM_PER_AU * 1000.0)
    weewx.units.conversionDict['mile']['astronomical_unit'] = lambda x: x * 1.609344 / KM_PER_AU
    # Four decimals keeps the moon (0.0024 AU) meaningful without turning
    # Mars (1.8588 AU) into noise.
    weewx.units.default_unit_format_dict['astronomical_unit'] = '%.4f'
    weewx.units.default_unit_label_dict['astronomical_unit'] = ' AU'


register_units()

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


# The moon's perigee/apogee search window: one anomalistic month (27.55
# days, perigee to perigee) plus margin, so the window always brackets one
# extremum of each kind.  step_days samples the distance curve every three
# days -- far finer than the ~13.8-day half-period of the oscillation, so
# skyfield.searchlib cannot skip an extremum.
APSIS_WINDOW_DAYS = 28.5
APSIS_STEP_DAYS = 3.0
# A full moon within a day of perigee is a supermoon -- the popular
# definition.  THE engine's single copy of the rule: the Sky page's
# lunation callout and the live pages' countdowns all read
# $almanac.next_supermoon rather than re-deriving it.
SUPERMOON_PERIGEE_GAP_S = 86400.0


class MoonDistanceAU:
    """The GEOMETRIC center-to-center earth-moon distance in AU as a
    function of time, shaped for skyfield.searchlib (a vectorized callable
    carrying step_days).  Geometric deliberately: the published apsis
    tables (Meeus; Espenak) are geometric, and this reproduces them to the
    minute, where the light-time-corrected observe() distance puts the
    extremum about eight minutes off the accepted definition."""

    step_days = APSIS_STEP_DAYS

    def __init__(self, sky: 'Sky'):
        self.moon_from_earth = sky.moon - sky.earth

    def __call__(self, t: skyfield.timelib.Time):
        return self.moon_from_earth.at(t).distance().au


# Earth's own apsides: one extremum of each kind per anomalistic year
# (365.26 days), so the window is a year plus margin; the 30-day step
# samples the annual oscillation far finer than its ~183-day half-period.
EARTH_APSIS_WINDOW_DAYS = 370.0
EARTH_APSIS_STEP_DAYS = 30.0


class EarthSunDistanceAU:
    """The GEOMETRIC center-to-center earth-sun distance in AU, shaped
    for skyfield.searchlib like MoonDistanceAU -- the same geometric
    convention the published perihelion/aphelion tables use."""

    step_days = EARTH_APSIS_STEP_DAYS

    def __init__(self, sky: 'Sky'):
        self.earth_from_sun = sky.earth - sky.sun

    def __call__(self, t: skyfield.timelib.Time):
        return self.earth_from_sun.at(t).distance().au


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


def tle_lines(text: str, norad: int) -> Tuple[str, str, str]:
    """(name, line1, line2) of the two-line element set for the given
    satellite in text -- the wire format CelesTrak's CATNR query returns
    and the cache files hold: an optional name line, then the '1 '/'2 '
    element lines.  Raises ValueError when the text is not a TLE for
    this catalog number (e.g. CelesTrak's "No GP data found" answer, a
    truncated download, or a corrupt cache file)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if line.startswith('1 ') and i + 1 < len(lines) and lines[i + 1].startswith('2 '):
            try:
                catnr = int(line[2:7])
            except ValueError:
                break
            if catnr != norad:
                raise ValueError('TLE is for catalog number %d, not %d' % (catnr, norad))
            name = lines[i - 1] if i > 0 else 'NORAD %d' % norad
            return name, line, lines[i + 1]
    raise ValueError('no two-line element set found')


def fetch_satellite_elements(norad: int, path: str, timeout: float = 15.0) -> None:
    """Fetch the current TLE for the given NORAD catalog number from
    CelesTrak into path.  The write is atomic (temp file, then rename)
    and the payload is validated first, so the previous file survives
    any failure -- serving slightly old elements always beats serving
    none.  Raises on any failure; callers own the backoff."""
    request = urllib.request.Request(CELESTRAK_URL % norad,
                                     headers={'User-Agent': SAT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode('ascii', 'replace')
    tle_lines(payload, norad)
    tmp_path = '%s.tmp' % path
    with open(tmp_path, 'w') as f:
        f.write(payload)
    os.replace(tmp_path, path)


def get_sat_dir(config_dict: Dict[str, Any]) -> str:
    """The satellite element cache directory: SAT_DIR_NAME under the
    station's SQLITE_ROOT (the conventional home for a WeeWX extension's
    runtime-writable data; weewx's own manager joins WEEWX_ROOT the same
    way, an absolute SQLITE_ROOT winning the join).  A MySQL-only
    configuration has no SQLITE_ROOT and falls back to WEEWX_ROOT."""
    weewx_root: str = config_dict.get('WEEWX_ROOT', '')
    sqlite_root: str = (config_dict.get('DatabaseTypes', {})
                        .get('SQLite', {}).get('SQLITE_ROOT', ''))
    return os.path.join(weewx_root, sqlite_root or '.', SAT_DIR_NAME)


def parse_satellites(skyfield_config_dict: Dict[str, Any]) -> Dict[str, int]:
    """The [Skyfield] [[Satellites]] section as a tag-name -> NORAD number
    map.  A bad entry disables only itself, loudly; a name that would
    shadow an existing tag (a planet, a named star, or the hip_/sat_
    number forms) is refused -- body dispatch checks those first, so the
    satellite would silently never be served."""
    satellites: Dict[str, int] = {}
    for name, value in (skyfield_config_dict.get('Satellites', {}) or {}).items():
        tag = str(name).lower()
        try:
            norad = int(str(value))
        except ValueError:
            log.error('Ignoring [Skyfield] [[Satellites]] entry %s = %r: the value'
                      ' must be the satellite\'s NORAD catalog number.' % (name, value))
            continue
        if tag in EPHEMERIS_KEYS or tag in NAMED_STARS or HIP_TAG_RE.match(tag) \
                or SAT_TAG_RE.match(tag) or tag in ('sun', 'earth'):
            log.error('Ignoring [Skyfield] [[Satellites]] entry %s: the name is'
                      ' already an almanac tag.' % name)
            continue
        satellites[tag] = norad
    return satellites


class InMemorySpiceKernel(skyfield.jpllib.SpiceKernel):
    """A SpiceKernel whose .bsp is read fully into memory (~16 MB for
    DE421) instead of memory-mapped by jplephem.  A mapped ephemeris kills
    the process with SIGBUS if the file is rewritten in place underneath
    it -- which is exactly what 'weectl extension install' over a live
    weewxd does.  SpiceKernel.__init__ is reused verbatim; for the length
    of that one call, the module-level SPK name it consults is swapped for
    a stand-in whose open() builds the SPK over the already-read bytes
    (jplephem's DAF falls back to plain reads when the file object cannot
    be mapped).  Reproducing the parent's assignments here instead is a
    trap: the set changes between Skyfield releases (1.53's __init__ sets
    codes and _vector_functions, 1.54's sets neither) and a missing one
    surfaces only at almanac time as an AttributeError -- field case,
    "'InMemorySpiceKernel' object has no attribute 'codes'" on Debian's
    Skyfield 1.53, which silently cost the user the whole almanac.  The
    swap is safe: __init__ runs once, on the main thread, at engine
    startup, before any report thread exists."""

    def __init__(self, path: str):
        with open(path, 'rb') as f:
            data: bytes = f.read()

        class _SPKFromBytes:
            @staticmethod
            def open(_path: str) -> Any:
                return jplephem.spk.SPK(jplephem.daf.DAF(io.BytesIO(data)))

        saved = skyfield.jpllib.SPK
        skyfield.jpllib.SPK = _SPKFromBytes
        try:
            super().__init__(path)
        finally:
            skyfield.jpllib.SPK = saved


class Sky():
    """The Skyfield engine: the timescale, the JPL ephemeris and the star
    catalog.  Its __init__ never raises: every failure logs and leaves
    valid=False, and the service then simply does nothing.  The one
    exemption is weewxd's Terminate, a shutdown request rather than a
    failure: __init__ runs on the main thread, where a SIGTERM during
    startup surfaces as Terminate inside whatever is executing, so every
    handler here re-raises it (reraise_if_terminate) instead of logging
    it away -- otherwise weewx cannot stop."""

    def __init__(self, user_root: str, load_stars: bool = False,
                 satellites: Optional[Dict[str, int]] = None,
                 sat_dir: Optional[str] = None,
                 comets: Optional[Dict[str, str]] = None,
                 comet_dir: Optional[str] = None):
        log.info("Skyfield version: %d.%d." % (skyfield.VERSION[0], skyfield.VERSION[1]))

        self.valid    : bool = False
        self.user_root: str  = user_root
        # The configured satellites (tag name -> NORAD number) and their
        # element cache directory.  Nothing is read here -- elements load
        # lazily at tag time (satellite_elements), and no network is ever
        # touched at startup: the service's archive-cycle worker owns the
        # fetching.
        self.satellites: Dict[str, int] = satellites or {}
        self.sat_dir: Optional[str] = sat_dir
        # Parsed elements keyed by NORAD number, tagged with the cache
        # file's mtime so a refreshed file is picked up on the next tag
        # evaluation; and the last usable/unusable state per satellite,
        # so the age-cutoff warning fires once at each crossing rather
        # than on every tag.
        self._sat_cache: Dict[int, Tuple[Optional[float], Optional[Tuple[Any, float]]]] = {}
        self._sat_usable: Dict[int, bool] = {}
        # The configured comets (tag name -> normalized MPC designation),
        # same lazy contract as the satellites: nothing is read here.  The
        # one cached CometEls file is parsed on first use and re-parsed
        # when its mtime changes; Kepler vectors are memoized per
        # designation and cleared on reparse.
        self.comets: Dict[str, str] = comets or {}
        self.comet_dir: Optional[str] = comet_dir
        self._comet_file: Tuple[Optional[float], Dict[str, CometRow]] = (None, {})
        self._comet_vectors: Dict[str, Any] = {}
        self._comet_usable: Dict[str, bool] = {}
        # Skyfield's constellation boundary map, loaded lazily on first
        # use by constellation_abbr_at (None: not yet tried; False: tried
        # and failed, don't retry).
        self._constellation_map: Any = None

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
            reraise_if_terminate(e)
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
            reraise_if_terminate(e)
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
            reraise_if_terminate(e)
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
            reraise_if_terminate(e)
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
        # What was asked for, as distinct from what happened: load_stars is
        # cleared when the catalog fails to load, stars_requested is not --
        # the difference is "disabled" vs "broken" (the Sky page footer
        # reports it).
        self.stars_requested: bool = load_stars
        self.load_stars: bool = load_stars
        self.hip_misses: set = set()
        # catalog_stars results, keyed by magnitude limit.
        self._catalog_fields: Dict[float, Optional[Tuple[List[int], Any, List[float]]]] = {}
        # The constellation line figures and the single array-valued Star
        # carrying every line vertex, loaded lazily by the Sky page's dome
        # (None: not yet tried; False: tried and failed, don't retry).
        self._constellation_lines: Any = None
        self._constellation_stars: Any = None
        if load_stars:
            try:
                self.stars = Sky.load_named_stars(user_root)
                log.info('Loaded %d named stars from the Hipparcos catalog.' % len(self.stars))
            except Exception as e:
                reraise_if_terminate(e)
                log.error('init: Could not load the Hipparcos star catalog: %s.  Star support disabled.' % e)
                self.load_stars = False

        self.valid = True

    def get_star_by_hip(self, hip: int) -> bool:
        """Load the star with the given Hipparcos number into self.stars
        under the name 'hip_<number>', serving $almanac.hip_57939 style tags
        for any of the catalog's 118,218 stars.  Results, including misses,
        are cached.  Returns whether the star is available."""
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
            # An unreadable catalog -- missing, permission-denied, or
            # corrupt (bad gzip data raises mid-read) -- must degrade to a
            # per-tag miss, never propagate into report generation.
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
        """Load the stars in NAMED_STARS from the Hipparcos catalog (an
        early-exit scan: the last named HIP sits well before the end of
        the catalog, and the whole read costs a few hundred ms, once, at
        engine startup)."""
        by_hip = Sky.load_stars_by_hip(user_root, set(NAMED_STARS.values()))
        return {name: by_hip[hip] for name, hip in NAMED_STARS.items() if hip in by_hip}

    @staticmethod
    def load_stars_by_hip(user_root: str, wanted_hips: set) -> Dict[int, Tuple[Any, Optional[float]]]:
        """Load the requested Hipparcos numbers from the star catalog.
        The scan stops as soon as every requested star has been seen."""
        by_hip: Dict[int, Tuple[Any, Optional[float]]] = {}
        with gzip.open('%s/%s' % (user_root, STAR_FILE), 'rt') as f:
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
                    ra_hours, dec_degrees, pm_ra, pm_dec, plx, magnitude = \
                        Sky._star_astrometry(fields)
                except (ValueError, IndexError):
                    continue
                star = skyfield.api.Star(
                    ra_hours=ra_hours,
                    dec_degrees=dec_degrees,
                    ra_mas_per_year=pm_ra,
                    dec_mas_per_year=pm_dec,
                    parallax_mas=plx,
                    epoch=HIPPARCOS_EPOCH_JD)
                by_hip[hip] = (star, magnitude)
                if len(by_hip) == len(wanted_hips):
                    break
        return by_hip

    @staticmethod
    def _star_astrometry(fields: List[str]) -> Tuple[float, float, float, float, float, Optional[float]]:
        """(ra_hours, dec_degrees, ra_mas_per_year, dec_mas_per_year,
        parallax_mas, magnitude) from one hip_main.dat record, already
        split on '|'.  Raises ValueError or IndexError on a malformed
        record; the caller decides how much that disables."""
        def parse_float(field: str) -> float:
            field = field.strip()
            return float(field) if field else 0.0

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
        magnitude = float(fields[5]) if fields[5].strip() else None
        return (ra_degrees / 15.0, dec_degrees, parse_float(fields[12]),
                parse_float(fields[13]), parse_float(fields[11]), magnitude)

    def catalog_stars(self, mag_limit: float) -> Optional[Tuple[List[int], Any, List[float]]]:
        """Every catalog star at least mag_limit bright: (hip numbers, ONE
        Star carrying all their coordinates as arrays, magnitudes) -- or
        None when stars are disabled or the catalog cannot be read.  The
        Sky page's dome uses this to plot the whole visible sky; the
        single array-valued Star makes the per-render cost one vectorized
        observe instead of thousands of scalar ones.  The scan reads all
        118,218 records, so results are cached for the life of the
        engine; an extension install replacing the file under a running
        weewxd is served from this cache, by design."""
        if not self.load_stars:
            return None
        key = round(mag_limit, 3)
        if key in self._catalog_fields:
            return self._catalog_fields[key]
        path = '%s/%s' % (self.user_root, STAR_FILE)
        hips: List[int] = []
        mags: List[float] = []
        ra_h: List[float] = []
        dec_d: List[float] = []
        pm_ra: List[float] = []
        pm_dec: List[float] = []
        plx: List[float] = []
        try:
            with gzip.open(path, 'rt') as f:
                for line in f:
                    fields = line.split('|')
                    # Test magnitude before the full astrometric parse:
                    # nearly every record fails this test.
                    try:
                        hip = int(fields[1])
                        mag = float(fields[5]) if fields[5].strip() else None
                    except (ValueError, IndexError):
                        continue
                    if mag is None or mag > mag_limit:
                        continue
                    # A malformed record disables only this star.
                    try:
                        r, d, pr, pd, px, _ = Sky._star_astrometry(fields)
                    except (ValueError, IndexError):
                        continue
                    hips.append(hip)
                    mags.append(mag)
                    ra_h.append(r)
                    dec_d.append(d)
                    pm_ra.append(pr)
                    pm_dec.append(pd)
                    plx.append(px)
        except Exception as e:
            # An unreadable catalog (missing, permission-denied, or
            # corrupt: bad gzip data raises mid-read) must degrade to the
            # named-star dome, never into report generation.  Cached:
            # retrying every report cycle would log the same error forever.
            log.error('catalog_stars: could not read the star catalog: %s' % e)
            self._catalog_fields[key] = None
            return None
        field: Optional[Tuple[List[int], Any, List[float]]]
        if hips:
            star = skyfield.api.Star(
                ra_hours=numpy.array(ra_h),
                dec_degrees=numpy.array(dec_d),
                ra_mas_per_year=numpy.array(pm_ra),
                dec_mas_per_year=numpy.array(pm_dec),
                parallax_mas=numpy.array(plx),
                epoch=HIPPARCOS_EPOCH_JD)
            field = (hips, star, mags)
            log.info('Loaded %d stars to magnitude %.2f from the full Hipparcos catalog.'
                     % (len(hips), mag_limit))
        else:
            field = ([], None, [])
        self._catalog_fields[key] = field
        return field

    def constellation_lines(self) -> Optional[List[Tuple[str, List[int]]]]:
        """The constellation line figures of wxskyfield_lines.dat, one
        (IAU abbreviation, vertex Hipparcos numbers) tuple per polyline
        -- or None when stars are disabled or the file cannot be read.
        The Sky page's dome draws these; loaded once, on first use."""
        if not self.load_stars or self._constellation_lines is False:
            return None
        if self._constellation_lines is not None:
            return self._constellation_lines
        lines: List[Tuple[str, List[int]]] = []
        try:
            with open('%s/%s' % (self.user_root, LINES_FILE)) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 3 or parts[0].startswith('#'):
                        continue
                    try:
                        hips = [int(p) for p in parts[1:]]
                    except ValueError:
                        # A malformed polyline disables only itself.
                        continue
                    lines.append((parts[0], hips))
        except Exception as e:
            log.error('constellation_lines: could not read %s: %s' % (LINES_FILE, e))
            self._constellation_lines = False
            return None
        self._constellation_lines = lines
        return lines

    def constellation_stars(self) -> Optional[Tuple[List[int], Any]]:
        """Every distinct constellation line vertex as (its Hipparcos
        numbers, ONE Star carrying all their coordinates as arrays) --
        or None when the lines or the star catalog are unavailable.  A
        vertex missing from the catalog drops only the segments that
        touch it.  Cached for the life of the engine."""
        if self._constellation_stars is False:
            return None
        if self._constellation_stars is not None:
            return self._constellation_stars
        polylines = self.constellation_lines()
        if polylines is None:
            return None
        wanted = {hip for _abbr, hips in polylines for hip in hips}
        try:
            by_hip = Sky.load_stars_by_hip(self.user_root, wanted)
        except Exception as e:
            log.error('constellation_stars: could not read the star catalog: %s' % e)
            self._constellation_stars = False
            return None
        if not by_hip:
            self._constellation_stars = False
            return None
        hips = sorted(by_hip)
        star = skyfield.api.Star(
            ra_hours=numpy.array([by_hip[h][0].ra.hours for h in hips]),
            dec_degrees=numpy.array([by_hip[h][0].dec.degrees for h in hips]),
            ra_mas_per_year=numpy.array([by_hip[h][0].ra_mas_per_year for h in hips]),
            dec_mas_per_year=numpy.array([by_hip[h][0].dec_mas_per_year for h in hips]),
            parallax_mas=numpy.array([by_hip[h][0].parallax_mas for h in hips]),
            epoch=HIPPARCOS_EPOCH_JD)
        self._constellation_stars = (hips, star)
        return self._constellation_stars

    def sat_norad(self, name: str) -> Optional[int]:
        """The NORAD number a body name refers to: a configured
        [[Satellites]] tag name, or the sat_<number> spelling of a LISTED
        satellite (never a trigger to serve an unlisted one).  None when
        the name is not a satellite."""
        norad = self.satellites.get(name)
        if norad is not None:
            return norad
        match = SAT_TAG_RE.match(name)
        if match:
            norad = int(match.group(1))
            if norad in self.satellites.values():
                return norad
        return None

    def sat_path(self, norad: int) -> str:
        return os.path.join(self.sat_dir or '.', SAT_FILE_FORMAT % norad)

    def satellite_elements(self, norad: int) -> Optional[Tuple[Any, float]]:
        """The satellite's orbital elements from its cache file, as
        (skyfield EarthSatellite, TLE epoch timestamp) -- or None when
        the file is missing or not a usable TLE.  Results are cached
        against the file's mtime, so the fetch worker replacing the file
        is picked up on the next tag evaluation, and a missing or
        corrupt file is not re-read (or re-logged) every tag.  Never
        raises: a broken cache file costs only this satellite."""
        try:
            mtime: Optional[float] = os.stat(self.sat_path(norad)).st_mtime
        except OSError:
            mtime = None
        cached = self._sat_cache.get(norad)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        elements: Optional[Tuple[Any, float]] = None
        if mtime is not None:
            try:
                with open(self.sat_path(norad)) as f:
                    name, line1, line2 = tle_lines(f.read(), norad)
                sat = skyfield.api.EarthSatellite(line1, line2, name, self.ts)
                elements = (sat, sat.epoch.utc_datetime().timestamp())
            except Exception as e:
                log.error('satellite_elements: could not load %s: %s'
                          % (self.sat_path(norad), e))
        self._sat_cache[norad] = (mtime, elements)
        return elements

    def note_sat_usable(self, norad: int, usable: bool) -> None:
        """Track each satellite's usable/unusable state so the age-cutoff
        crossing (and the recovery) is logged once, not per tag."""
        previous = self._sat_usable.get(norad)
        if previous == usable:
            return
        self._sat_usable[norad] = usable
        if not usable:
            log.warning('Satellite %d has no usable elements (missing, unreadable,'
                        ' or epoch older than %d days); its tags will report N/A.'
                        % (norad, SAT_MAX_ELEMENT_AGE_SECS // 86400))
        elif previous is not None:
            log.info('Satellite %d has usable elements again.' % norad)

    def comet_path(self) -> str:
        return os.path.join(self.comet_dir or '.', COMET_FILE)

    def comet_elements(self, name: str) -> Optional[Tuple[Any, CometRow, float]]:
        """The configured comet's (vector, elements row, file mtime), or
        None when the cached CometEls file is missing, unreadable, or no
        longer carries the designation -- MPC drops faded comets, so a
        configured comet CAN vanish from a fresh download; the binder
        serves the honest no-elements state, never an error.  Lazy and
        mtime-invalidated like satellite_elements; only CONFIGURED
        designations are parsed (six rows, not 953), and a malformed
        matching row logs and disables only that comet."""
        designation = self.comets.get(name)
        if designation is None:
            return None
        try:
            mtime = os.stat(self.comet_path()).st_mtime
        except OSError:
            return None
        if self._comet_file[0] != mtime:
            wanted = set(self.comets.values())
            rows: Dict[str, CometRow] = {}
            try:
                with open(self.comet_path()) as f:
                    for line in f:
                        key = comet_designation_key(line[102:158])
                        if key in wanted and key not in rows:
                            try:
                                rows[key] = parse_comet_row(line)
                            except ValueError as e:
                                log.error('comet_elements: could not parse the'
                                          ' %s row in %s: %s'
                                          % (key, self.comet_path(), e))
            except OSError as e:
                log.error('comet_elements: could not read %s: %s'
                          % (self.comet_path(), e))
                rows = {}
            self._comet_file = (mtime, rows)
            self._comet_vectors.clear()
        row = self._comet_file[1].get(designation)
        if row is None:
            return None
        vector = self._comet_vectors.get(designation)
        if vector is None:
            vector = self._comet_vector(row)
            self._comet_vectors[designation] = vector
        return vector, row, mtime

    def _comet_vector(self, row: CometRow) -> Any:
        """sun + the comet's Kepler orbit: skyfield.data.mpc.comet_orbit
        reproduced verbatim, minus pandas (that module imports pandas at
        module level, and pandas is deliberately not a dependency).
        _KeplerOrbit._from_periapsis is private Skyfield API -- the
        JPL-Horizons regression test pins its behavior, so a future
        Skyfield change fails loudly in the suite, not in the field."""
        if row.e == 1.0:
            p = row.q * 2.0
        else:
            a = row.q / (1.0 - row.e)
            p = a * (1.0 - row.e * row.e)
        orbit = skyfield.keplerlib._KeplerOrbit._from_periapsis(
            p, row.e, row.incl, row.node, row.argp,
            self.ts.tt(row.peri_year, row.peri_month, row.peri_day),
            skyfield.constants.GM_SUN_Pitjeva_2005_km3_s2, 10,
            row.designation_full)
        orbit._rotation = skyfield.data.spice.inertial_frames['ECLIPJ2000'].T
        return self.sun + orbit

    def note_comet_usable(self, name: str, usable: bool) -> None:
        """Track each comet's has-elements state so the vanishing-row
        crossing (and the recovery) is logged once, not per tag."""
        previous = self._comet_usable.get(name)
        if previous == usable:
            return
        self._comet_usable[name] = usable
        if not usable:
            log.warning('Comet %s (%s) has no elements in the cached CometEls'
                        ' file (file missing or unreadable, or the designation'
                        ' is gone from it); its tags will report N/A.'
                        % (name, self.comets.get(name)))
        elif previous is not None:
            log.info('Comet %s (%s) has elements again.'
                     % (name, self.comets.get(name)))

    @staticmethod
    def get_weewx_config_info(config_dict: Dict[str, Any]) -> str:
        """The user directory: where the ephemeris and star catalog were
        installed."""
        weewx_root: str = config_dict.get('WEEWX_ROOT', '')
        user_root : str = config_dict.get('USER_ROOT', 'bin/user')
        if not user_root.startswith('/'):
            user_root = "%s/%s" % (weewx_root, user_root)
        return user_root

    def constellation_abbr_at(self, position) -> Optional[str]:
        """The IAU abbreviation of the constellation containing the given
        skyfield position.  The boundary map ships inside the skyfield
        package (no download) and is loaded lazily on first use; None when
        it cannot be loaded, in which case the constellation tags fall
        through to the next almanac.  Runs on the report thread only, so
        no Terminate guard is needed."""
        if self._constellation_map is None:
            try:
                self._constellation_map = skyfield.api.load_constellation_map()
            except Exception as e:
                log.error('constellation_abbr_at: could not load the constellation map: %s' % e)
                self._constellation_map = False
        if self._constellation_map is False:
            return None
        return str(self._constellation_map(position))

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

# Eclipse tags: attribute -> (solar, previous).  Each reports the instant
# of maximum eclipse of the nearest eclipse VISIBLE from the station: the
# eclipsed body must be above the horizon at maximum.  Each has a
# companion _type tag ('penumbral'/'partial'/'total' for lunar;
# 'partial'/'annular'/'total', the type as seen from the station, for
# solar -- a station inside only the penumbra of a total solar eclipse
# sees, and reports, 'partial').
ECLIPSE_EVENTS: Dict[str, Tuple[bool, bool]] = {
    'next_lunar_eclipse'     : (False, False),
    'previous_lunar_eclipse' : (False, True),
    'next_solar_eclipse'     : (True,  False),
    'previous_solar_eclipse' : (True,  True),
}

# skyfield.eclipselib.lunar_eclipses event codes 0/1/2.
LUNAR_ECLIPSE_KINDS = ('penumbral', 'partial', 'total')

# Every eclipse tag: the per-kind tags with their _type companions, plus
# the combined next_/previous_eclipse -- the sooner (later) of the two
# kinds -- whose extra _kind companion says which kind won ('lunar' or
# 'solar').  The combined tags exist so a skin needs no selection logic
# of its own (the Sky page's eclipse chip uses them).
ECLIPSE_ATTRS = (frozenset(ECLIPSE_EVENTS)
                 | {name + '_type' for name in ECLIPSE_EVENTS}
                 | {'next_eclipse', 'next_eclipse_type', 'next_eclipse_kind',
                    'previous_eclipse', 'previous_eclipse_type', 'previous_eclipse_kind'})

# How far a single eclipse-search scan extends.  The next eclipse visible
# from a given station is usually months away, occasionally a few years
# (solar); scanning in chunks keeps the common case cheap while still
# reaching the edge of the ephemeris when it has to.
_ECLIPSE_CHUNK_DAYS = 400

class Constellation(str):
    """The constellation a body stands in, as $almanac.<body>.constellation
    returns it: a plain str holding the Latin name -- so templates that
    render or compare the 1.9 tag ($almanac.mars.constellation == 'Leo'),
    and loopdata fields that serialize it, see exactly what they always
    have -- that also carries the other views of the same answer as
    attributes: .name the Latin name again, .abbr the IAU abbreviation,
    and .label the report's translated display name."""
    name: str
    abbr: str
    label: str

    def __new__(cls, latin: str, abbr: str, label: str) -> 'Constellation':
        self = super().__new__(cls, latin)
        self.name = latin
        self.abbr = abbr
        self.label = label
        return self


class Radians(float):
    """A PyEphem-shaped angle as the almanac returns it: a plain float in
    radians -- templates and loopdata fields consuming the value numerically
    see exactly what they always have -- that also carries the same answer
    in decimal degrees as .degrees (and, for symmetry with Skyfield's own
    angle objects, .radians)."""

    @property
    def degrees(self) -> float:
        return math.degrees(self)

    @property
    def radians(self) -> float:
        return float(self)


class CallableRadians(Radians):
    """Radians that may also be called, with no arguments, yielding itself.
    $almanac.<body>.parallactic_angle was a bound method through 1.14
    (PyEphem's is a method), so the explicit-call form
    $almanac.venus.parallactic_angle() is in the wild and must keep working
    now that the tag resolves to the value itself -- which it must, so that
    .degrees works for consumers that walk attribute chains without
    Cheetah's autocall (loopdata almanac fields, plain Python)."""

    def __call__(self) -> 'CallableRadians':
        return self


# IAU constellation abbreviation -> nominative name, for
# $almanac.<body>.constellation.  Skyfield's bundled boundary map answers
# with the abbreviation ($almanac.<body>.constellation_abbr).
CONSTELLATION_NAMES: Dict[str, str] = {
    'And': 'Andromeda',       'Ant': 'Antlia',           'Aps': 'Apus',
    'Aqr': 'Aquarius',        'Aql': 'Aquila',           'Ara': 'Ara',
    'Ari': 'Aries',           'Aur': 'Auriga',           'Boo': 'Boötes',
    'Cae': 'Caelum',          'Cam': 'Camelopardalis',   'Cnc': 'Cancer',
    'CVn': 'Canes Venatici',  'CMa': 'Canis Major',      'CMi': 'Canis Minor',
    'Cap': 'Capricornus',     'Car': 'Carina',           'Cas': 'Cassiopeia',
    'Cen': 'Centaurus',       'Cep': 'Cepheus',          'Cet': 'Cetus',
    'Cha': 'Chamaeleon',      'Cir': 'Circinus',         'Col': 'Columba',
    'Com': 'Coma Berenices',  'CrA': 'Corona Australis', 'CrB': 'Corona Borealis',
    'Crv': 'Corvus',          'Crt': 'Crater',           'Cru': 'Crux',
    'Cyg': 'Cygnus',          'Del': 'Delphinus',        'Dor': 'Dorado',
    'Dra': 'Draco',           'Equ': 'Equuleus',         'Eri': 'Eridanus',
    'For': 'Fornax',          'Gem': 'Gemini',           'Gru': 'Grus',
    'Her': 'Hercules',        'Hor': 'Horologium',       'Hya': 'Hydra',
    'Hyi': 'Hydrus',          'Ind': 'Indus',            'Lac': 'Lacerta',
    'Leo': 'Leo',             'LMi': 'Leo Minor',        'Lep': 'Lepus',
    'Lib': 'Libra',           'Lup': 'Lupus',            'Lyn': 'Lynx',
    'Lyr': 'Lyra',            'Men': 'Mensa',            'Mic': 'Microscopium',
    'Mon': 'Monoceros',       'Mus': 'Musca',            'Nor': 'Norma',
    'Oct': 'Octans',          'Oph': 'Ophiuchus',        'Ori': 'Orion',
    'Pav': 'Pavo',            'Peg': 'Pegasus',          'Per': 'Perseus',
    'Phe': 'Phoenix',         'Pic': 'Pictor',           'Psc': 'Pisces',
    'PsA': 'Piscis Austrinus', 'Pup': 'Puppis',          'Pyx': 'Pyxis',
    'Ret': 'Reticulum',       'Sge': 'Sagitta',          'Sgr': 'Sagittarius',
    'Sco': 'Scorpius',        'Scl': 'Sculptor',         'Sct': 'Scutum',
    'Ser': 'Serpens',         'Sex': 'Sextans',          'Tau': 'Taurus',
    'Tel': 'Telescopium',     'Tri': 'Triangulum',       'TrA': 'Triangulum Australe',
    'Tuc': 'Tucana',          'UMa': 'Ursa Major',       'UMi': 'Ursa Minor',
    'Vel': 'Vela',            'Vir': 'Virgo',            'Vol': 'Volans',
    'Vul': 'Vulpecula',
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
STAR_UNSUPPORTED = {'phase', 'moon_fullness', 'illumination',
                    'hlong', 'hlat', 'hlon', 'hlongitude', 'hlatitude'}

# Moon apsis tags: attribute -> (apogee, previous).  The next_/previous_
# spelling is load-bearing for weewx-loopdata, which event-tiers almanac
# fields by that prefix; an unprefixed spelling would rerun the extrema
# search on every loop packet.
APSIS_ATTRS: Dict[str, Tuple[bool, bool]] = {
    'next_perigee'    : (False, False),
    'previous_perigee': (False, True),
    'next_apogee'     : (True, False),
    'previous_apogee' : (True, True),
}

# Earth's own apsides, served as top-level almanac tags (like
# next_solstice): attribute -> (farthest, previous).  No clash with the
# comets' per-body .perihelion attribute -- different namespace.  The
# next_/previous_ spelling is load-bearing for weewx-loopdata, as above.
EARTH_APSIS_ATTRS: Dict[str, Tuple[bool, bool]] = {
    'next_perihelion'    : (False, False),
    'previous_perihelion': (False, True),
    'next_aphelion'      : (True, False),
    'previous_aphelion'  : (True, True),
}

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

    def star_field(self, almanac_obj, mag_limit: float) -> Optional[List[Tuple[int, float, float, float]]]:
        """Every catalog star at least mag_limit bright and above the
        horizon, as (hip, azimuth degrees, altitude degrees, magnitude)
        tuples -- or None when the catalog is disabled or unreadable (the
        Sky page's dome then falls back to the named stars).  Alt/az are
        computed exactly as the binder's .alt/.az -- apparent, refracted
        with the almanac's temperature and pressure -- in one vectorized
        observe covering the whole field."""
        field = self.sky.catalog_stars(mag_limit)
        if field is None:
            return None
        hips, star, mags = field
        if not hips:
            return []
        _, observer = self.location(almanac_obj)
        t = self.skyfield_time(almanac_obj.time_ts)
        alt, az, _ = observer.at(t).observe(star).apparent().altaz(
            temperature_C=almanac_obj.temperature,
            pressure_mbar=almanac_obj.pressure)
        alt_d, az_d = alt.degrees, az.degrees
        return [(hips[i], az_d[i], alt_d[i], mags[i])
                for i in range(len(hips)) if alt_d[i] > 0.0]

    def constellation_field(self, almanac_obj) -> Optional[Dict[int, Tuple[float, float]]]:
        """Apparent (azimuth, altitude) degrees for every constellation
        line vertex, keyed by Hipparcos number -- below-horizon vertices
        included, which the dome needs to clip a setting figure at the
        rim instead of amputating it at its last risen star.  Computed
        exactly as the binder's .az/.alt (refracted with the almanac's
        temperature and pressure) in one vectorized observe; None when
        the line data or the star catalog is unavailable."""
        field = self.sky.constellation_stars()
        if field is None:
            return None
        hips, star = field
        _, observer = self.location(almanac_obj)
        t = self.skyfield_time(almanac_obj.time_ts)
        alt, az, _ = observer.at(t).observe(star).apparent().altaz(
            temperature_C=almanac_obj.temperature,
            pressure_mbar=almanac_obj.pressure)
        alt_d, az_d = alt.degrees, az.degrees
        return {hips[i]: (az_d[i], alt_d[i]) for i in range(len(hips))}

    def time_value(self, almanac_obj, time_ts: Optional[float], context: str) -> ValueHelper:
        return ValueHelper(ValueTuple(time_ts, 'unix_epoch', 'group_time'),
                           context=context,
                           formatter=almanac_obj.formatter,
                           converter=almanac_obj.converter)

    def direction_value(self, almanac_obj, degrees: Optional[float]) -> ValueHelper:
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

    def find_apsis(self, almanac_obj, apogee: bool, previous: bool,
                   cache_key: str, f: Any, window_days: float) -> ValueHelper:
        """Time of the nearest apsis -- an extremum of the given distance
        function f (the moon's perigee/apogee, Earth's own
        perihelion/aphelion), found with skyfield.searchlib -- after (or
        before) the almanac's time, within window_days of it.
        Geocentric, so location plays no part in the cache key; cached
        like find_event, valid from the time it was computed for through
        the event itself.  Unlike find_event, the no-event outcome is
        cached too: it is only reachable when the search window pokes
        past the ephemeris span (every window here is wider than
        covers()'s two-day margin), and weewx-loopdata deliberately
        never caches a no-data event field -- every loop packet retries
        it, and each retry must hit this cache, not a fresh search."""
        time_ts = almanac_obj.time_ts
        hit = _DAY_CACHE.get(('event', cache_key), _MISS)
        if hit is not _MISS:
            valid_from, valid_to, event_ts = hit
            if valid_from <= time_ts <= valid_to:
                return self.time_value(almanac_obj, event_ts, 'ephem_year')
        window_s = window_days * 86400
        start_ts = time_ts - window_s if previous else time_ts
        end_ts = time_ts if previous else time_ts + window_s
        find = (skyfield.searchlib.find_maxima if apogee
                else skyfield.searchlib.find_minima)
        event_ts = None
        try:
            times, _ = find(self.skyfield_time(start_ts),
                            self.skyfield_time(end_ts),
                            f)
            stamps = [t.utc_datetime().timestamp() for t in times]
            if previous:
                stamps = [s for s in stamps if s <= time_ts]
                event_ts = stamps[-1] if stamps else None
            else:
                stamps = [s for s in stamps if s >= time_ts]
                event_ts = stamps[0] if stamps else None
        except skyfield.errors.EphemerisRangeError:
            event_ts = None
        if len(_DAY_CACHE) >= _DAY_CACHE_CAP:
            _DAY_CACHE.clear()
        if previous:
            _DAY_CACHE[('event', cache_key)] = (
                start_ts if event_ts is None else event_ts, time_ts, event_ts)
        else:
            _DAY_CACHE[('event', cache_key)] = (
                time_ts, end_ts if event_ts is None else event_ts, event_ts)
        return self.time_value(almanac_obj, event_ts, 'ephem_year')

    def next_supermoon_ts(self, almanac_obj) -> Optional[float]:
        """The instant of the next supermoon: the next full moon falling
        within SUPERMOON_PERIGEE_GAP_S of perigee.  Searches forward full
        moon by full moon (one or two qualify per year; the bound of 30
        lunations is a safety rail, never reached in practice), judging
        each against its nearest perigee -- the same geometric-distance
        extremum the apsis tags use.  Cached like the other events, and
        the no-answer outcome (the search running past the ephemeris
        edge) is cached too, the apsis-tag precedent for loopdata's
        every-packet no-data retries."""
        time_ts = almanac_obj.time_ts
        hit = _DAY_CACHE.get(('event', 'next_supermoon'), _MISS)
        if hit is not _MISS:
            valid_from, valid_to, event_ts = hit
            if valid_from <= time_ts <= valid_to:
                return event_ts
        f = skyfield.almanac.moon_phases(self.sky.planets)
        found: Optional[float] = None
        searched_to = time_ts
        try:
            t = time_ts
            for _ in range(30):
                full = find_discrete_events(f, self.skyfield_time(t),
                                            self.skyfield_time(t + 35 * 86400),
                                            ((2,),))[0]
                if full is None:
                    break
                searched_to = full
                times, _values = skyfield.searchlib.find_minima(
                    self.skyfield_time(full - 16 * 86400),
                    self.skyfield_time(full + 16 * 86400),
                    MoonDistanceAU(self.sky))
                stamps = [pt.utc_datetime().timestamp() for pt in times]
                if stamps and min(abs(p - full) for p in stamps) <= SUPERMOON_PERIGEE_GAP_S:
                    found = full
                    break
                t = full + 86400.0
        except skyfield.errors.EphemerisRangeError:
            found = None
        if len(_DAY_CACHE) >= _DAY_CACHE_CAP:
            _DAY_CACHE.clear()
        _DAY_CACHE[('event', 'next_supermoon')] = (
            time_ts, found if found is not None else searched_to, found)
        return found

    def sun_longitude_degrees(self, t: skyfield.timelib.Time) -> Any:
        """The sun's apparent geocentric ecliptic longitude in degrees --
        the solar longitude meteor astronomy anchors shower peaks to.
        Vectorized: t may be a Time array (the crossing search needs it)."""
        _, lon, _ = (self.sky.earth.at(t).observe(self.sky.sun).apparent()
                     .frame_latlon(skyfield.framelib.ecliptic_frame))
        return lon.degrees % 360.0

    def find_sun_longitude(self, target: float, t0_ts: float, t1_ts: float) -> Optional[float]:
        """The instant within [t0_ts, t1_ts] when the sun's longitude
        ascends through target, or None if the window misses it."""
        times, values = skyfield.almanac.find_discrete(
            self.skyfield_time(t0_ts), self.skyfield_time(t1_ts),
            _SunLongitudeCrossed(self, target))
        stamps = [t.utc_datetime().timestamp()
                  for t, v in zip(times, values) if v]
        return stamps[0] if stamps else None

    def radiant_altaz(self, almanac_obj,
                      ra_degrees: float, dec_degrees: float) -> Tuple[float, float]:
        """Refracted topocentric (alt, az) of a fixed J2000 direction --
        a shower radiant -- at the almanac's time, through the same
        machinery the stars use."""
        _, observer = self.location(almanac_obj)
        t = self.skyfield_time(almanac_obj.time_ts)
        star = skyfield.api.Star(ra_hours=ra_degrees / 15.0,
                                 dec_degrees=dec_degrees)
        alt, az, _ = observer.at(t).observe(star).apparent().altaz(
            temperature_C=almanac_obj.temperature,
            pressure_mbar=almanac_obj.pressure)
        return alt.degrees, az.degrees

    def shower_peak_ts(self, shower: MeteorShower, near_ts: float,
                       window_days: float) -> Optional[float]:
        """The instant of the shower's peak within +/- window_days of
        near_ts, through the event cache (geocentric: location-free).
        One crossing per year, so any window under ~150 days brackets at
        most one."""
        key = ('event', 'meteor_peak', shower.key)
        hit = _DAY_CACHE.get(key, _MISS)
        if hit is not _MISS:
            valid_from, valid_to, peak_ts = hit
            if valid_from <= near_ts <= valid_to:
                return peak_ts
        peak_ts = self.find_sun_longitude(shower.peak_lambda,
                                          near_ts - window_days * 86400,
                                          near_ts + window_days * 86400)
        if peak_ts is not None:
            if len(_DAY_CACHE) >= _DAY_CACHE_CAP:
                _DAY_CACHE.clear()
            _DAY_CACHE[key] = (peak_ts - window_days * 86400,
                               peak_ts + window_days * 86400, peak_ts)
        return peak_ts

    def next_meteor_shower_info(self, almanac_obj) -> MeteorShowerInfo:
        """$almanac.next_meteor_shower: the shower whose peak lies next
        ahead.  Ordering costs one observe -- the next peak is simply the
        next peak_lambda ahead of today's solar longitude -- and only
        that shower's crossing is solved precisely (cached; a fresh Info
        is built per call so .label follows each report's language and
        the radiant's alt/az the almanac's time)."""
        time_ts = almanac_obj.time_ts
        lam = float(self.sun_longitude_degrees(self.skyfield_time(time_ts)))
        shower = min(METEOR_SHOWERS,
                     key=lambda s: (s.peak_lambda - lam) % 360.0)
        ahead_days = ((shower.peak_lambda - lam) % 360.0) / 360.0 * 365.2422
        peak_ts = self.shower_peak_ts(shower, time_ts + ahead_days * 86400, 6.0)
        return MeteorShowerInfo(self, almanac_obj, shower, peak_ts)

    def active_meteor_showers_info(self, almanac_obj) -> Tuple[MeteorShowerInfo, ...]:
        """$almanac.active_meteor_showers: every shower whose activity
        window contains today's solar longitude, each carrying its own
        apparition's peak (which may already lie days in the past --
        honest: an active shower past maximum is still active)."""
        time_ts = almanac_obj.time_ts
        lam = float(self.sun_longitude_degrees(self.skyfield_time(time_ts)))
        active = []
        for shower in METEOR_SHOWERS:
            if shower.start_lambda <= lam <= shower.end_lambda:
                peak_ts = self.shower_peak_ts(shower, time_ts, 75.0)
                active.append(MeteorShowerInfo(self, almanac_obj, shower, peak_ts))
        return tuple(active)

    def eclipse_event(self, almanac_obj, attr: str):
        """Serve any name in ECLIPSE_ATTRS: the per-kind tags
        (next_lunar_eclipse, ... plus _type), and the combined
        next_/previous_eclipse (plus _type and _kind), which report the
        sooner (later) of the two kinds so a skin needs no selection
        logic of its own."""
        base, suffix = attr, ''
        for s in ('_type', '_kind'):
            if attr.endswith(s):
                base, suffix = attr[:-len(s)], s
        if base in ECLIPSE_EVENTS:
            solar, previous = ECLIPSE_EVENTS[base]
            found = self.eclipse_lookup(almanac_obj, solar, previous)
            kind = 'solar' if solar else 'lunar'
        else:
            # next_eclipse / previous_eclipse: the sooner (later) of the
            # two kinds.  One kind having none left in the ephemeris'
            # span does not spoil the other.
            previous = (base == 'previous_eclipse')
            best: Optional[Tuple[Tuple[float, str], str]] = None
            for solar in (False, True):
                try:
                    candidate = self.eclipse_lookup(almanac_obj, solar, previous)
                except weewx.UnknownType:
                    continue
                if (best is None
                        or (candidate[0] > best[0][0] if previous
                            else candidate[0] < best[0][0])):
                    best = (candidate, 'solar' if solar else 'lunar')
            if best is None:
                raise weewx.UnknownType(attr)
            found, kind = best
        if suffix == '_type':
            return found[1]
        if suffix == '_kind':
            return kind
        return self.time_value(almanac_obj, found[0], 'ephem_year')

    def eclipse_lookup(self, almanac_obj, solar: bool, previous: bool) -> Tuple[float, str]:
        """(time of maximum, locally seen type) of the nearest eclipse of
        one kind visible from the station, through the cache.  Like
        find_event, a found eclipse is valid for any almanac time between
        the time searched from and the eclipse itself; unlike the
        seasonal events an eclipse is local (the visibility test runs at
        the station), so the cache key carries the location.  Raises
        weewx.UnknownType when no visible eclipse lies within the
        ephemeris' span."""
        a = almanac_obj
        time_ts = a.time_ts
        key = ('eclipse', solar, previous, a.lat, a.lon, a.altitude)
        hit = _DAY_CACHE.get(key, _MISS)
        if hit is not _MISS:
            valid_from, valid_to, found = hit
            if valid_from <= time_ts <= valid_to:
                return found
        try:
            found = (self.find_solar_eclipse(a, previous) if solar
                     else self.find_lunar_eclipse(a, previous))
        except skyfield.errors.EphemerisRangeError:
            # A search window poking past the ephemeris' span.
            raise weewx.UnknownType('eclipse')
        if found is None:
            # No visible eclipse inside the ephemeris' span.
            raise weewx.UnknownType('eclipse')
        if len(_DAY_CACHE) >= _DAY_CACHE_CAP:
            _DAY_CACHE.clear()
        if previous:
            _DAY_CACHE[key] = (found[0], time_ts, found)
        else:
            _DAY_CACHE[key] = (time_ts, found[0], found)
        return found

    def eclipse_windows(self, time_ts: float, previous: bool) -> List[Tuple[float, float]]:
        """Consecutive search windows from time_ts to the edge of the
        ephemeris, in _ECLIPSE_CHUNK_DAYS steps: the nearest visible
        eclipse is usually in the first chunk, so scanning the whole
        remaining span up front would be wasted work."""
        sky = self.sky
        floor_ts = sky.start_ts + 86400
        ceil_ts = sky.end_ts - 86400
        windows: List[Tuple[float, float]] = []
        if previous:
            hi = time_ts
            while hi > floor_ts:
                lo = max(floor_ts, hi - _ECLIPSE_CHUNK_DAYS * 86400)
                windows.append((lo, hi))
                hi = lo
        else:
            lo = time_ts
            while lo < ceil_ts:
                hi = min(ceil_ts, lo + _ECLIPSE_CHUNK_DAYS * 86400)
                windows.append((lo, hi))
                lo = hi
        return windows

    def altitude_degrees(self, almanac_obj, orb, time_ts: float) -> float:
        """Geometric altitude of the body's center at the station, in
        degrees, used for the is-the-eclipse-visible judgments."""
        _, observer = self.location(almanac_obj)
        alt, _, _ = observer.at(self.skyfield_time(time_ts)).observe(orb).apparent().altaz()
        return alt.degrees

    def find_lunar_eclipse(self, almanac_obj, previous: bool) -> Optional[Tuple[float, str]]:
        """Maximum of the nearest lunar eclipse visible from the station
        (the moon above the horizon at maximum), searched chunk by chunk
        to the edge of the ephemeris.  skyfield's eclipselib supplies the
        eclipses; only the visibility test is local."""
        sky = self.sky
        for start_ts, end_ts in self.eclipse_windows(almanac_obj.time_ts, previous):
            times, kinds, _ = skyfield.eclipselib.lunar_eclipses(
                self.skyfield_time(start_ts), self.skyfield_time(end_ts), sky.planets)
            stamps = [(t.utc_datetime().timestamp(), int(kind))
                      for t, kind in zip(times, kinds)]
            for event_ts, kind in (reversed(stamps) if previous else stamps):
                if self.altitude_degrees(almanac_obj, sky.moon, event_ts) > 0.0:
                    return event_ts, LUNAR_ECLIPSE_KINDS[kind]
        return None

    def find_solar_eclipse(self, almanac_obj, previous: bool) -> Optional[Tuple[float, str]]:
        """Maximum of the nearest solar eclipse visible from the station.
        A solar eclipse is local by nature, so every new moon is tested
        for a sun-moon overlap as seen from the station: a partial
        eclipse counts exactly when the station lies inside the penumbra,
        and the _type is the local type (a station that catches only the
        penumbra of a total eclipse sees, and reports, 'partial')."""
        for start_ts, end_ts in self.eclipse_windows(almanac_obj.time_ts, previous):
            new_moons = self.new_moons(start_ts, end_ts)
            for nm_ts in (reversed(new_moons) if previous else new_moons):
                found = self.local_solar_eclipse(almanac_obj, nm_ts)
                if found is not None:
                    return found
        return None

    def new_moons(self, start_ts: float, end_ts: float) -> List[float]:
        """Timestamps of the new moons in [start_ts, end_ts]."""
        times, events = skyfield.almanac.find_discrete(
            self.skyfield_time(start_ts), self.skyfield_time(end_ts),
            skyfield.almanac.moon_phases(self.sky.planets))
        return [t.utc_datetime().timestamp() for t, e in zip(times, events) if e == 0]

    def local_solar_eclipse(self, almanac_obj, nm_ts: float) -> Optional[Tuple[float, str]]:
        """Whether the new moon at nm_ts eclipses the sun as seen from
        the station: (time of maximum, local type), or None.  Maximum is
        the minimum topocentric sun-moon separation -- a coarse scan of
        the five hours either side of the new moon (partial phases span
        at most about three hours either side of maximum, and topocentric
        parallax shifts maximum from the geocentric new moon by at most
        about an hour), refined to ~5 seconds -- compared against the
        apparent radii of the two discs.  The maximum must occur with the
        sun above the horizon to count as visible."""
        _, observer = self.location(almanac_obj)
        sky = self.sky

        def observe(t) -> Tuple[Any, Any, Any]:
            o = observer.at(t)
            sun = o.observe(sky.sun).apparent()
            moon = o.observe(sky.moon).apparent()
            return sun, moon, sun.separation_from(moon).degrees

        coarse = self.ts.linspace(self.skyfield_time(nm_ts - 5 * 3600),
                                  self.skyfield_time(nm_ts + 5 * 3600), 101)
        _, _, sep = observe(coarse)
        i = int(numpy.argmin(sep))
        fine = self.ts.linspace(coarse[max(i - 1, 0)],
                                coarse[min(i + 1, len(coarse) - 1)], 145)
        sun, moon, sep = observe(fine)
        j = int(numpy.argmin(sep))
        sep_min = float(sep[j])
        r_sun = math.degrees(math.asin(BODY_RADIUS_KM['sun'] / sun.distance().km[j]))
        r_moon = math.degrees(math.asin(BODY_RADIUS_KM['moon'] / moon.distance().km[j]))
        if sep_min >= r_sun + r_moon:
            # The discs never overlap: no eclipse at this station.
            return None
        max_ts = fine[j].utc_datetime().timestamp()
        if self.altitude_degrees(almanac_obj, sky.sun, max_ts) <= 0.0:
            # The eclipsed sun is below the horizon.
            return None
        if r_moon >= r_sun and sep_min <= r_moon - r_sun:
            kind = 'total'
        elif r_moon < r_sun and sep_min <= r_sun - r_moon:
            kind = 'annular'
        else:
            kind = 'partial'
        return max_ts, kind

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
        elif attr in ECLIPSE_ATTRS:
            return self.eclipse_event(almanac_obj, attr)
        elif attr in ('sidereal_time', 'sidereal_angle'):
            geographic, _ = self.location(almanac_obj)
            degrees = geographic.lst_hours_at(self.skyfield_time(almanac_obj.time_ts)) * 15.0
            if attr == 'sidereal_time':
                return degrees
            return self.direction_value(almanac_obj, degrees)
        elif attr in EARTH_APSIS_ATTRS:
            # Earth's own perihelion (early January) and aphelion (early
            # July) -- the closest-sun-in-northern-winter classic.
            farthest, previous = EARTH_APSIS_ATTRS[attr]
            return self.find_apsis(almanac_obj, farthest, previous, attr,
                                   EarthSunDistanceAU(self.sky),
                                   EARTH_APSIS_WINDOW_DAYS)
        elif attr == 'next_supermoon':
            return self.time_value(almanac_obj, self.next_supermoon_ts(almanac_obj),
                                   'ephem_year')
        elif attr == 'next_meteor_shower':
            return self.next_meteor_shower_info(almanac_obj)
        elif attr == 'active_meteor_showers':
            return self.active_meteor_showers_info(almanac_obj)
        elif attr in ('solar_time', 'solar_angle', 'equation_of_time'):
            # Local apparent solar time -- what a sundial reads -- from the
            # sun's local apparent hour angle, the same machinery behind the
            # ha tag; and the equation of time, apparent MINUS mean solar
            # time per the USNO sign convention (positive with the sundial
            # ahead of the clock: ~+16 min in early November).
            # solar_time/solar_angle mirror the sidereal pair: decimal
            # degrees, 0-360, 180 at solar noon.
            ha = SkyfieldAlmanacBinder(self, almanac_obj, 'sun').compute_angle('ha')
            if attr == 'equation_of_time':
                apparent_hours = ha / 15.0 + 12.0
                mean_hours = ((almanac_obj.time_ts % 86400) / 3600.0
                              + almanac_obj.lon / 15.0)
                eot_hours = (apparent_hours - mean_hours + 12.0) % 24.0 - 12.0
                return ValueHelper(ValueTuple(eot_hours * 3600.0, 'second', 'group_deltatime'),
                                   context='ephem_day',
                                   formatter=almanac_obj.formatter,
                                   converter=almanac_obj.converter)
            degrees = (ha + 180.0) % 360.0
            if attr == 'solar_time':
                return degrees
            return self.direction_value(almanac_obj, degrees)
        elif attr in self.sky.orbs or attr in self.sky.stars:
            return SkyfieldAlmanacBinder(self, almanac_obj, attr)
        # A configured satellite, by its [[Satellites]] tag name or its
        # sat_<norad> spelling ($almanac.iss, $almanac.sat_25544).
        elif self.sky.sat_norad(attr) is not None:
            return SkyfieldAlmanacBinder(self, almanac_obj, attr)
        # A configured comet, by its [[Comets]] tag name.  No numeric
        # alternate spelling: comets have no NORAD-style number worth one.
        elif attr in self.sky.comets:
            return SkyfieldAlmanacBinder(self, almanac_obj, attr)

        # Any Hipparcos star by number: $almanac.hip_57939 (works for every
        # one of the catalog's 118,218 stars).
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
        """Angular separation, in radians (a Radians float, so .degrees is
        also available).  Accepts (longitude, latitude)
        tuples in radians (same contract as weewx.almanac.AlmanacType.separation),
        this almanac's own body binders (e.g.,
        $almanac.separation($almanac.mars, $almanac.venus)), or a mix of the
        two.  Each binder is observed at its own almanac's time.  Anything
        else (e.g., PyEphem Body objects) is deferred to the next almanac
        rather than crashed on."""
        try:
            if (isinstance(body1, SkyfieldAlmanacBinder) and isinstance(body2, SkyfieldAlmanacBinder)
                    and not body1.is_satellite and not body2.is_satellite):
                # A satellite binder cannot take this exact-vector path:
                # an EarthSatellite is Earth-centered, and skyfield only
                # observe()s from the barycenter.  Satellites fall through
                # to the coordinate path below, whose geocentric radec has
                # a satellite branch.
                p1 = self.sky.earth.at(self.skyfield_time(body1.almanac.time_ts)).observe(body1.target_body())
                p2 = self.sky.earth.at(self.skyfield_time(body2.almanac.time_ts)).observe(body2.target_body())
                return Radians(p1.separation_from(p2).radians)
            coords1 = SkyfieldAlmanacType.separation_coordinates(body1)
            coords2 = SkyfieldAlmanacType.separation_coordinates(body2)
        except skyfield.errors.EphemerisRangeError:
            # A binder whose almanac time is outside the ephemeris' span.
            raise weewx.UnknownType('separation')
        if coords1 is None or coords2 is None:
            raise weewx.UnknownType('separation')
        # Meeus 17.1, delegated to the WeeWX base class (only reachable on
        # WeeWX 5.2+, where the base class exists).
        return Radians(super().separation(coords1, coords2))

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


class SatellitePass:
    """One satellite pass, as $almanac.<sat>.next_pass and
    .next_visible_pass report it.  Every attribute is a plain,
    already-computed value -- rise, culmination and set as time
    ValueHelpers, max_altitude a group_angle ValueHelper, the three
    azimuths degree_compass ValueHelpers (so .ordinal_compass comes
    free), duration a group_deltatime ValueHelper, visible a bool --
    never a method: consumers that walk attribute chains with plain
    getattr (loopdata almanac fields) must resolve them without
    Cheetah's autocall.  With no qualifying pass, or no usable elements,
    every ValueHelper is empty ("N/A") and visible is None."""

    def __init__(self, binder: 'SkyfieldAlmanacBinder',
                 data: Optional[Dict[str, Any]]):
        almanac_type, a = binder.almanac_type, binder.almanac
        d: Dict[str, Any] = data or {}
        self.rise = almanac_type.time_value(a, d.get('rise'), 'ephem_day')
        self.culmination = almanac_type.time_value(a, d.get('culmination'), 'ephem_day')
        self.set = almanac_type.time_value(a, d.get('set'), 'ephem_day')
        max_altitude = d.get('max_altitude')
        self.max_altitude = ValueHelper(
            ValueTuple(math.radians(max_altitude) if max_altitude is not None else None,
                       'radian', 'group_angle'),
            context='ephem_day', formatter=a.formatter, converter=a.converter)
        self.rise_azimuth = almanac_type.direction_value(a, d.get('rise_azimuth'))
        self.culmination_azimuth = almanac_type.direction_value(a, d.get('culmination_azimuth'))
        self.set_azimuth = almanac_type.direction_value(a, d.get('set_azimuth'))
        self.duration = ValueHelper(
            ValueTuple(d['set'] - d['rise'] if d else None, 'second', 'group_deltatime'),
            context='hour', formatter=a.formatter, converter=a.converter)
        self.visible: Optional[bool] = d.get('visible') if d else None


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
        'hour_angle': ('ha',    'angle'),
        'hlongitude': ('hlong', 'direction'),
        'hlatitude' : ('hlat',  'angle'),
        'elongation': ('elong', 'angle'),
    }

    # Attributes that are returned as plain floats in decimal degrees.
    # hlon is PyEphem's spelling of hlong; ha is the hour angle.
    FLOAT_ANGLES = ('az', 'alt', 'ra', 'dec', 'a_ra', 'a_dec', 'g_ra', 'g_dec',
                    'ha', 'hlong', 'hlat', 'hlon', 'elong')

    def __init__(self, almanac_type: SkyfieldAlmanacType, almanac, heavenly_body: str):
        self.almanac_type = almanac_type
        self.almanac = almanac
        self.heavenly_body = heavenly_body
        self.norad: Optional[int] = almanac_type.sky.sat_norad(heavenly_body)
        self.is_satellite = self.norad is not None
        # A comet must be recognized BEFORE the is_star fall-through:
        # is_star is simply "nothing else", and an unrecognized comet
        # would KeyError into the star catalog.
        self.is_comet = (not self.is_satellite
                         and heavenly_body in almanac_type.sky.comets)
        self.is_star = (not self.is_satellite and not self.is_comet
                        and heavenly_body not in almanac_type.sky.orbs)
        self.use_center = False

    def __call__(self, use_center: bool = False):
        self.use_center = use_center
        return self

    def __str__(self):
        # A binder cannot be printed itself.  It always needs an attribute.
        raise AttributeError(self.heavenly_body)

    def target_body(self) -> Any:
        """The skyfield object observed: a planet vector, a Star, a comet's
        sun-plus-Kepler-orbit vector, or an EarthSatellite (a satellite or
        comet without elements raises like a missing attribute -- callers
        landing here for one, e.g. separation, have no N/A convention to
        fall back on; comet TAG evaluation never lands here elementless,
        the _evaluate gate serves the N/A state first)."""
        sky = self.almanac_type.sky
        if self.is_satellite:
            assert self.norad is not None
            elements = sky.satellite_elements(self.norad)
            if elements is None:
                raise AttributeError(self.heavenly_body)
            return elements[0]
        if self.is_comet:
            comet = sky.comet_elements(self.heavenly_body)
            if comet is None:
                raise AttributeError(self.heavenly_body)
            return comet[0]
        if self.is_star:
            return sky.stars[self.heavenly_body][0]
        return sky.orbs[self.heavenly_body]

    @property
    def cache_name(self) -> str:
        """The body's identity in _DAY_CACHE/_POS_CACHE keys.  For every
        body but a comet this is the name itself.  A comet's elements
        change whenever the cached CometEls file is refreshed -- and
        _DAY_CACHE survives across report cycles -- so the file's mtime
        is folded in: a refresh invalidates the cached rise/set times
        instead of serving old-element answers until the day rolls (the
        satellite pass cache's epoch precedent).  Mtime rather than the
        row's perturbed epoch, deliberately: the epoch column can be
        blank -- most likely for the freshly-discovered comets users
        actually configure -- and a refresh can revise the orbit without
        moving the epoch."""
        if not self.is_comet:
            return self.heavenly_body
        comet = self.almanac_type.sky.comet_elements(self.heavenly_body)
        mtime = comet[2] if comet is not None else 0.0
        return '%s@%d' % (self.heavenly_body, int(mtime))

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
        key = ('radius', self.cache_name, sod_ts, a.lat, a.lon, a.altitude)
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
        key = ('rise' if rise else 'set', self.cache_name,
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
        key = ('antitransit' if antitransit else 'transit', self.cache_name,
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
        if self.is_satellite:
            # Not part of a satellite's tag surface (that is the pass
            # family).  A property shadows __getattr__, so decline here;
            # the raise routes the lookup through __getattr__, whose
            # satellite branch raises the same clean AttributeError as
            # any other unsupported satellite attribute.
            raise AttributeError('visible')
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
        if today_visible.value_t[0] is None or then_visible.value_t[0] is None:
            # Either day has no answer (a comet without elements): an
            # honest empty ValueHelper, not a TypeError from None math.
            return ValueHelper(ValueTuple(None, 'second', 'group_deltatime'),
                               context='hour',
                               formatter=self.almanac.formatter,
                               converter=self.almanac.converter)
        diff_vt = today_visible.value_t - then_visible.value_t
        return ValueHelper(diff_vt,
                           context='hour',
                           formatter=self.almanac.formatter,
                           converter=self.almanac.converter)

    def geocentric_radec_degrees(self) -> Tuple[float, float]:
        """Apparent geocentric (right ascension, declination) of date, in
        decimal degrees.  One observation serves both angles (separation
        needs the pair; two compute_angle calls would observe twice)."""
        key = ('gradec', self.cache_name, self.almanac.time_ts)
        return _cached(_POS_CACHE, _POS_CACHE_CAP, key, self._geocentric_radec_degrees)

    def _geocentric_radec_degrees(self) -> Tuple[float, float]:
        sky = self.almanac_type.sky
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        if self.is_satellite:
            # An EarthSatellite is already a geocentric vector; there is
            # no light-time iteration to observe() through.
            ra, dec, _ = self.target_body().at(t).radec('date')
            return ra._degrees, dec.degrees
        ra, dec, _ = sky.earth.at(t).observe(self.target_body()).apparent().radec('date')
        return ra._degrees, dec.degrees

    def compute_angle(self, attr: str) -> float:
        """Compute the requested angle.  Returned in decimal degrees."""
        a = self.almanac
        # Temperature and pressure only matter for the refracted alt/az, but
        # keying on them unconditionally is merely a few extra cache misses.
        key = ('angle', self.cache_name, attr, a.time_ts,
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
        elif attr == 'ha':
            # Local apparent hour angle, signed: 0 at transit, negative east
            # of the meridian (rising toward transit), positive west -- the
            # standard convention.  PyEphem's ha is the same angle in radians,
            # usually wrapped to [0, 2*pi).
            _, observer = self.almanac_type.location(self.almanac)
            ha, _, _ = observer.at(t).observe(orb).apparent().hadec()
            return ha._degrees
        elif attr in ('hlong', 'hlat', 'hlon'):
            # Heliocentric ecliptic longitude/latitude.  For the sun itself
            # these are undefined (it sits at the origin); report Earth's
            # heliocentric coordinates instead, per the XEphem convention.
            # For the moon this is its true heliocentric longitude, where
            # PyEphem reports the moon's GEOcentric ecliptic longitude.
            # hlon is PyEphem's own spelling of hlong.
            target = sky.earth if self.heavenly_body == 'sun' else orb
            lat, lon, _ = sky.sun.at(t).observe(target).frame_latlon(skyfield.framelib.ecliptic_frame)
            return lat.degrees if attr == 'hlat' else lon.degrees
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
        key = ('mag', self.cache_name, a.time_ts, a.lat, a.lon, a.altitude)
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
        elif self.is_comet:
            # The MPC total-magnitude formula, m = g + 5 log10(delta)
            # + 2.5 k log10(r), from the row's g/k parameters.  Comets
            # notoriously deviate from it -- outbursts, disintegrations --
            # so the docs carry the caveat.  A row without g/k serves no
            # magnitude at all, like a catalog star without one.
            comet = sky.comet_elements(name)
            if comet is None:
                raise AttributeError('mag')
            vector, row, _ = comet
            if row.g is None or row.k is None:
                raise AttributeError('mag')
            delta = sky.distance_au(t, vector)
            r = sky.distance_au(t, vector, origin=sky.sun)
            return row.g + 5.0 * math.log10(delta) + 2.5 * row.k * math.log10(r)
        else:
            return float(skyfield.magnitudelib.planetary_magnitude(
                sky.earth.at(t).observe(sky.orbs[name])))

    def angular_radius_radians(self) -> float:
        """Apparent (topocentric) angular radius of the body, in radians.
        Stars and comets are point sources: 0.0, before any observation
        (a comet must not need elements to answer .size)."""
        if self.is_star or self.is_comet:
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

    def constellation_lookup(self) -> Optional[str]:
        """IAU abbreviation of the constellation the body stands in, as
        the observer sees it (topocentric apparent place -- for the moon,
        parallax can matter near a boundary).  Works for stars too.  NOT
        named constellation_abbr: a real attribute would shadow the tag
        (__getattr__ only runs for names not otherwise found, so the tag
        would evaluate to the bound method)."""
        a = self.almanac
        key = ('constellation', self.cache_name, a.time_ts, a.lat, a.lon, a.altitude)
        return _cached(_POS_CACHE, _POS_CACHE_CAP, key, self._constellation_lookup)

    def _constellation_lookup(self) -> Optional[str]:
        _, observer = self.almanac_type.location(self.almanac)
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        position = observer.at(t).observe(self.target_body()).apparent()
        return self.almanac_type.sky.constellation_abbr_at(position)

    def _parallactic_angle(self) -> float:
        """Parallactic angle of the body in radians.  Dispatched by _evaluate
        as a CallableRadians -- NOT a real method named after the tag (a real
        attribute would shadow __getattr__, and the tag must resolve to the
        value itself so .degrees works without Cheetah's autocall); the
        callable value keeps the explicit PyEphem-style call
        $almanac.venus.parallactic_angle() working."""
        _, observer = self.almanac_type.location(self.almanac)
        t = self.almanac_type.skyfield_time(self.almanac.time_ts)
        ha, dec, _ = observer.at(t).observe(self.target_body()).apparent().hadec()
        latitude = math.radians(self.almanac.lat)
        return math.atan2(math.sin(ha.radians),
                          math.tan(latitude) * math.cos(dec.radians)
                          - math.sin(dec.radians) * math.cos(ha.radians))

    def moon_libration(self, attr: str) -> float:
        """Geocentric optical libration of the moon (libration_lat,
        libration_long) and the selenographic position of the sun -- its
        colongitude (colong) and latitude (subsolar_lat) -- in radians
        like PyEphem's, per Meeus, Astronomical Algorithms, chapter 53.
        The physical libration (at most 0.04 degrees) is neglected."""
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
        if attr in ('colong', 'subsolar_lat'):
            # These derive from the selenographic position of the sun: the
            # same formulas, fed the sun's coordinates as seen from the
            # moon (Meeus 53.5).
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
        if attr in ('libration_lat', 'subsolar_lat'):
            # The latitude formula: the moon's coordinates give the
            # libration in latitude, the sun's give its subsolar latitude.
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

    def _comet_missing_attr(self, attr: str):
        """The no-elements comet surface: every tag the orb path would
        serve, shaped honestly -- empty "N/A" ValueHelpers, None for the
        plain-value tags, zero for the point-source sizes -- never a wrong
        number and never a per-tag error.  Anything OUTSIDE the served
        surface raises AttributeError, exactly as it would with elements
        (the pyephem_fallback fence).  Must stay in lockstep with the orb
        surface: the parametrized no-elements test enumerates it."""
        a = self.almanac
        if attr in ('rise', 'set', 'transit', 'perihelion',
                    'next_rising', 'next_setting',
                    'previous_rising', 'previous_setting',
                    'next_transit', 'previous_transit',
                    'next_antitransit', 'previous_antitransit'):
            return self.almanac_type.time_value(a, None, 'ephem_day')
        if attr in SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES:
            _, flavor = SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES[attr]
            if flavor == 'direction':
                return self.almanac_type.direction_value(a, None)
            return ValueHelper(ValueTuple(None, 'radian', 'group_angle'),
                               context='ephem_day',
                               formatter=a.formatter, converter=a.converter)
        if attr in SkyfieldAlmanacBinder.FLOAT_ANGLES:
            return None
        if attr in ('mag', 'phase', 'moon_phase', 'earth_distance', 'sun_distance',
                    'circumpolar', 'neverup', 'constellation', 'constellation_abbr'):
            return None
        if attr == 'illumination':
            return ValueHelper(ValueTuple(None, 'percent', 'group_percent'),
                               context='ephem_day',
                               formatter=a.formatter, converter=a.converter)
        if attr in ('distance', 'distance_from_sun'):
            return ValueHelper(ValueTuple(None, 'astronomical_unit', 'group_distance_astronomical'),
                               context='ephem_day',
                               formatter=a.formatter, converter=a.converter)
        if attr == 'visible':
            return ValueHelper(ValueTuple(None, 'second', 'group_deltatime'),
                               context='day',
                               formatter=a.formatter, converter=a.converter)
        if attr in ('size', 'radius'):
            # A comet is a point source with or without elements.
            return 0.0
        if attr == 'radius_size':
            return ValueHelper(ValueTuple(0.0, 'radian', 'group_angle'),
                               context='ephem_day',
                               formatter=a.formatter, converter=a.converter)
        raise AttributeError("'%s' object has no attribute '%s'"
                             % (self.heavenly_body.capitalize(), attr))

    def pyephem_fallback(self, attr: str):
        """Delegate an attribute Skyfield does not compute to the built-in
        PyEphem almanac, if PyEphem is installed.  Comets NEVER fall
        through -- PyEphem has no comets, and this is the one choke point
        every route passes (the _evaluate tail, __getattr__'s
        EphemerisRangeError handler, the constellation-failure path): a
        clean per-tag AttributeError instead, the satellite convention."""
        if self.is_comet:
            raise AttributeError("'%s' object has no attribute '%s'"
                                 % (self.heavenly_body.capitalize(), attr))
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
        # A satellite's tag surface is its own -- positions, sunlit, the
        # pass family, the element diagnostics -- and nothing else applies:
        # there is no PyEphem fallback to defer to (the built-in almanac
        # never served satellites), so anything unrecognized raises cleanly.
        if self.is_satellite and attr not in ('name', 'label'):
            return self._satellite_attr(attr)

        # A comet takes the normal orb path below -- the whole planet-style
        # surface comes free from its sun+Kepler-orbit vector -- but its
        # elements can honestly not exist (cache file missing, or MPC
        # dropped the designation from a fresh download).  The gate serves
        # the element diagnostics always, and collapses everything else to
        # the N/A state when there are no elements; wrong numbers and
        # per-tag errors are both unacceptable there.
        if self.is_comet and attr not in ('name', 'label'):
            sky = self.almanac_type.sky
            comet = sky.comet_elements(self.heavenly_body)
            if attr in ('elements_epoch', 'elements_age'):
                epoch_ts = comet[1].epoch_ts if comet is not None else None
                if attr == 'elements_epoch':
                    return self.almanac_type.time_value(self.almanac, epoch_ts, 'ephem_year')
                age = (self.almanac.time_ts - epoch_ts) if epoch_ts is not None else None
                return ValueHelper(ValueTuple(age, 'second', 'group_deltatime'),
                                   context='hour',
                                   formatter=self.almanac.formatter,
                                   converter=self.almanac.converter)
            sky.note_comet_usable(self.heavenly_body, comet is not None)
            if comet is None:
                return self._comet_missing_attr(attr)

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
        elif attr == 'illumination':
            # ValueHelper twin of the raw phase percent (and of the moon's
            # moon_fullness alias): the same value in group_percent,
            # honoring the report's percent formatting.  mag deliberately
            # has no twin: a magnitude is unitless, there is nothing to
            # convert or label.
            return ValueHelper(ValueTuple(self.phase, 'percent', 'group_percent'),
                               context='ephem_day',
                               formatter=self.almanac.formatter,
                               converter=self.almanac.converter)
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
        elif attr in ('distance', 'distance_from_sun'):
            # ValueHelper twins of the raw earth_distance/sun_distance
            # floats: the same AU value, served in
            # group_distance_astronomical so it formats as "1.8588 AU" in
            # every unit system and converts on ask
            # ($almanac.mars.distance.km).  distance is from Earth,
            # mirroring the satellite surface, where .distance already
            # means distance from the observer.  A star without a measured
            # parallax has no known distance: an empty "N/A" ValueHelper,
            # never the PyEphem fallback (whose star objects have no such
            # attribute).
            sky = self.almanac_type.sky
            au: Optional[float]
            if self.is_star and not sky.stars[self.heavenly_body][0].parallax_mas:
                au = None
            else:
                t = self.almanac_type.skyfield_time(self.almanac.time_ts)
                origin = sky.sun if attr == 'distance_from_sun' else None
                au = sky.distance_au(t, self.target_body(), origin=origin)
            return ValueHelper(ValueTuple(au, 'astronomical_unit', 'group_distance_astronomical'),
                               context='ephem_day',
                               formatter=self.almanac.formatter,
                               converter=self.almanac.converter)
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
            return 100.0 * sky.earth.at(t).observe(self.target_body()).apparent().fraction_illuminated(sky.sun)
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
        elif attr == 'parallactic_angle':
            return CallableRadians(self._parallactic_angle())
        elif attr == 'perihelion' and self.is_comet:
            # The comet's time of perihelion passage, straight from the
            # MPC row (a TT date).  The row references the current orbit
            # solution's perihelion, which may lie in the past --
            # Hale-Bopp's says 1997 -- so consumers judge upcoming-ness
            # themselves (the Sky page's countdown chip shows it only
            # when it lies ahead within a year).
            comet = self.almanac_type.sky.comet_elements(self.heavenly_body)
            if comet is None:
                # The gate normally serves N/A first; this covers the
                # race of the cache file vanishing mid-evaluation.
                return self.almanac_type.time_value(self.almanac, None, 'ephem_year')
            row = comet[1]
            t = self.almanac_type.sky.ts.tt(row.peri_year, row.peri_month, row.peri_day)
            return self.almanac_type.time_value(
                self.almanac, t.utc_datetime().timestamp(), 'ephem_year')
        elif attr in APSIS_ATTRS and self.heavenly_body == 'moon':
            # Moon perigee/apogee times (the supermoon machinery).  Moon
            # only: no other served body orbits the observer.  For any
            # other body the name falls through to the PyEphem fallback,
            # which raises AttributeError -- PyEphem has no apsides.
            apogee, previous = APSIS_ATTRS[attr]
            return self.almanac_type.find_apsis(
                self.almanac, apogee, previous, attr,
                MoonDistanceAU(self.almanac_type.sky), APSIS_WINDOW_DAYS)
        elif attr in ('libration_lat', 'libration_long', 'colong',
                      'subsolar_lat') and self.heavenly_body == 'moon':
            return Radians(self.moon_libration(attr))
        elif attr == 'moon_phase' and self.heavenly_body == 'moon':
            # PyEphem's raw illuminated fraction, 0..1 (phase is percent).
            return self.phase / 100.0
        elif attr in ('cmlI', 'cmlII') and self.heavenly_body == 'jupiter':
            return Radians(self.jupiter_cml(attr))
        elif attr in ('earth_tilt', 'sun_tilt') and self.heavenly_body == 'saturn':
            return Radians(self.saturn_ring_tilt(attr))
        elif attr in ('constellation', 'constellation_abbr'):
            abbr = self.constellation_lookup()
            if abbr is None:
                return self.pyephem_fallback(attr)
            if attr == 'constellation_abbr':
                # Legacy alias (1.9) for .constellation.abbr.
                return abbr
            latin = CONSTELLATION_NAMES.get(abbr, abbr)
            # .label is the localized display name.  Skins translate
            # constellations in an [Almanac] [[Constellations]] subsection
            # keyed by the IAU abbreviation (Psc = Fische); the value
            # itself stays the Latin str so consumers reading the tag as
            # data (loopdata fields, template comparisons) never see it
            # shift with a report's language.
            labels = almanac_texts(self.almanac).get('Constellations')
            label = labels.get(abbr, latin) if isinstance(labels, dict) else latin
            return Constellation(latin, abbr, label)
        elif attr == 'name':
            return self.heavenly_body.replace('_', ' ').title()
        elif attr == 'label':
            # Localized display name.  Skins translate body names in their
            # [Almanac] section, keyed by the tag name (moon = Mond, beside
            # moon_phases); WeeWX pipes that section into every almanac as
            # .texts.  Untranslated bodies fall back to the English .name,
            # mirroring $obs.label's fall-through.
            return almanac_texts(self.almanac).get(
                self.heavenly_body, self.heavenly_body.replace('_', ' ').title())

        # Something Skyfield does not compute (e.g., a_epoch, or PyEphem's
        # deprecated rise_time family).  Fall back to the built-in PyEphem
        # almanac if PyEphem is installed.
        return self.pyephem_fallback(attr)

    # ── satellites ───────────────────────────────────────────────────────

    def _satellite_attr(self, attr: str):
        """Serve a satellite tag.  Missing, unparseable, or too-old
        elements (epoch beyond the seven-day cutoff, measured against the
        almanac's time) all collapse to one no-usable-elements state:
        empty ValueHelpers ("N/A"), None for the plain-value tags -- never
        a silently wrong pass time.  Only the element diagnostics
        (elements_epoch, elements_age) ignore the cutoff: they are how a
        user sees WHY everything else reads N/A."""
        almanac_type = self.almanac_type
        a = self.almanac
        sky = almanac_type.sky
        assert self.norad is not None
        elements = sky.satellite_elements(self.norad)
        epoch_ts = elements[1] if elements is not None else None
        if attr == 'elements_epoch':
            return almanac_type.time_value(a, epoch_ts, 'ephem_year')
        if attr == 'elements_age':
            age = a.time_ts - epoch_ts if epoch_ts is not None else None
            return ValueHelper(ValueTuple(age, 'second', 'group_deltatime'),
                               context='hour', formatter=a.formatter,
                               converter=a.converter)
        usable = (epoch_ts is not None
                  and a.time_ts - epoch_ts <= SAT_MAX_ELEMENT_AGE_SECS)
        sky.note_sat_usable(self.norad, usable)
        if not usable:
            elements = None

        if attr in ('next_pass', 'next_visible_pass'):
            data = None
            if elements is not None:
                passes = self._sat_passes(elements[0], elements[1])
                data = self._next_sat_pass(passes, visible_only=(attr == 'next_visible_pass'))
            return SatellitePass(self, data)
        if attr in ('rise', 'transit', 'set'):
            # For a satellite these are the NEXT occurrence from the
            # almanac's time (transit meaning culmination), not the
            # planets' anytime-today verbs: passes are minutes long and
            # "today's" is rarely the interesting one.
            event_ts = None
            if elements is not None:
                event_key = {'rise': 'rise', 'transit': 'culmination', 'set': 'set'}[attr]
                passes = self._sat_passes(elements[0], elements[1])
                event_ts = next((p[event_key] for p in passes
                                 if p[event_key] > a.time_ts), None)
            return almanac_type.time_value(a, event_ts, 'ephem_day')
        if attr == 'sunlit':
            if elements is None:
                return None
            return self._sat_position(elements[0], elements[1])['sunlit']
        if attr == 'distance':
            # Slant range, observer to satellite.
            distance_km = (self._sat_position(elements[0], elements[1])['distance_km']
                           if elements is not None else None)
            return ValueHelper(ValueTuple(distance_km, 'km', 'group_distance'),
                               context='ephem_day', formatter=a.formatter,
                               converter=a.converter)
        if (attr in SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES
                and SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES[attr][0]
                in ('az', 'alt', 'ra', 'dec')):
            angle_key, flavor = SkyfieldAlmanacBinder.VALUE_HELPER_ANGLES[attr]
            degrees = (self._sat_position(elements[0], elements[1])[angle_key]
                       if elements is not None else None)
            if flavor == 'direction':
                return almanac_type.direction_value(a, degrees)
            return ValueHelper(ValueTuple(
                math.radians(degrees) if degrees is not None else None,
                'radian', 'group_angle'),
                context='ephem_day', formatter=a.formatter, converter=a.converter)
        if attr in ('az', 'alt', 'ra', 'dec'):
            if elements is None:
                return None
            return self._sat_position(elements[0], elements[1])[attr]
        raise AttributeError("'%s' object has no attribute '%s'"
                             % (self.heavenly_body.capitalize(), attr))

    def _sat_position(self, sat: Any, epoch_ts: float) -> Dict[str, Any]:
        """The satellite's topocentric numbers at the almanac's time, in
        one cached computation: apparent alt/az (refracted with the
        almanac's temperature and pressure, like every body's .alt/.az),
        topocentric right ascension/declination of date, slant range, and
        whether the satellite is sunlit.  An EarthSatellite is differenced
        from the observer (Skyfield's satellite form; there is no
        light-time iteration to observe() through)."""
        a = self.almanac
        key = ('sat_pos', self.norad, round(epoch_ts), a.time_ts,
               a.lat, a.lon, a.altitude, a.temperature, a.pressure)
        return _cached(_POS_CACHE, _POS_CACHE_CAP, key,
                       lambda: self._compute_sat_position(sat))

    def _compute_sat_position(self, sat: Any) -> Dict[str, Any]:
        sky = self.almanac_type.sky
        a = self.almanac
        geographic, _ = self.almanac_type.location(a)
        t = self.almanac_type.skyfield_time(a.time_ts)
        topocentric = (sat - geographic).at(t)
        alt, az, distance = topocentric.altaz(temperature_C=a.temperature,
                                              pressure_mbar=a.pressure)
        ra, dec, _ = topocentric.radec('date')
        return {'alt': alt.degrees, 'az': az.degrees,
                'ra': ra._degrees, 'dec': dec.degrees,
                'distance_km': distance.km,
                'sunlit': bool(sat.at(t).is_sunlit(sky.planets))}

    def _sat_passes(self, sat: Any, epoch_ts: float) -> List[Dict[str, Any]]:
        """Every pass in the elements' validity window -- a day before the
        TLE epoch through the seven-day age cutoff; never searching times
        the elements cannot be trusted for -- computed once per element
        set, location and horizon, and cached (the seven-day SGP4 sweep
        is milliseconds, but loopdata asks every loop packet).  The
        horizon is GEOMETRIC (default 0, overridable via the existing
        $almanac(horizon=10) argument): refraction is irrelevant to
        satellite watching, per the USNO-over-PyEphem policy."""
        a = self.almanac
        horizon = float(a.horizon)
        key = ('sat_passes', self.norad, round(epoch_ts), a.lat, a.lon,
               a.altitude, round(horizon / _HORIZON_QUANTUM_DEGREES))
        return _cached(_DAY_CACHE, _DAY_CACHE_CAP, key,
                       lambda: self._compute_sat_passes(sat, epoch_ts, horizon))

    def _compute_sat_passes(self, sat: Any, epoch_ts: float,
                            horizon: float) -> List[Dict[str, Any]]:
        almanac_type = self.almanac_type
        sky = almanac_type.sky
        geographic, observer = almanac_type.location(self.almanac)
        t0 = almanac_type.skyfield_time(epoch_ts - 86400)
        t1 = almanac_type.skyfield_time(epoch_ts + SAT_MAX_ELEMENT_AGE_SECS)
        times, events = sat.find_events(geographic, t0, t1,
                                        altitude_degrees=horizon)
        stamps = [t.utc_datetime().timestamp() for t in times]
        # Group the event stream into rise -> culmination(s) -> set.  A
        # pass already in progress at the window's edge (no rise event) is
        # dropped: the window starts a day before the epoch, so no
        # queryable pass is lost.  A satellite that never crosses the
        # horizon (geostationary, or HST from high latitudes with a high
        # horizon argument) yields no events and an empty list.
        raw: List[Tuple[float, List[float], float]] = []
        rise_ts: Optional[float] = None
        culm_ts: List[float] = []
        for stamp, event in zip(stamps, events):
            if event == 0:
                rise_ts, culm_ts = stamp, []
            elif event == 1:
                culm_ts.append(stamp)
            elif rise_ts is not None and culm_ts:
                raw.append((rise_ts, culm_ts, stamp))
                rise_ts, culm_ts = None, []
        if not raw:
            return []
        # One vectorized sweep answers every per-event question: geometric
        # altitude and azimuth, whether the satellite is sunlit, and how
        # dark the observer's sky is (sun below -6 degrees geometric,
        # civil twilight, the Heavens-Above convention).  A pass is
        # visible when ANY of its sampled instants qualifies -- sampling
        # the whole pass catches the mid-pass fade into Earth's shadow
        # that a culmination-only test misclassifies.
        all_stamps = [s for rise, culms, set_ in raw
                      for s in [rise] + culms + [set_]]
        t_all = sky.ts.from_datetimes(
            [datetime.fromtimestamp(s, timezone.utc) for s in all_stamps])
        alt, az, _ = (sat - geographic).at(t_all).altaz()
        sunlit = sat.at(t_all).is_sunlit(sky.planets)
        sun_alt, _, _ = observer.at(t_all).observe(sky.sun).apparent().altaz()
        alt_d, az_d, sun_d = alt.degrees, az.degrees, sun_alt.degrees
        passes: List[Dict[str, Any]] = []
        base = 0
        for rise, culms, set_ in raw:
            idx = list(range(base, base + len(culms) + 2))
            base += len(idx)
            # The culmination: the highest, when find_events reports more
            # than one for a single pass.
            c = max(idx[1:-1], key=lambda k: alt_d[k])
            passes.append({
                'rise': rise, 'culmination': all_stamps[c], 'set': set_,
                'max_altitude': float(alt_d[c]),
                'rise_azimuth': float(az_d[idx[0]]),
                'culmination_azimuth': float(az_d[c]),
                'set_azimuth': float(az_d[idx[-1]]),
                'visible': any(bool(sunlit[k]) and sun_d[k] < SAT_DARK_SUN_ALT_DEGREES
                               for k in idx),
            })
        return passes

    def _next_sat_pass(self, passes: List[Dict[str, Any]],
                       visible_only: bool) -> Optional[Dict[str, Any]]:
        """The next pass from the almanac's time.  A pass in progress IS
        the next pass (rise <= now < set: the countdown rolls into
        "overhead now, sets in three minutes").  The visible variant adds
        the go-watch bar: a qualifying visibility sample and a
        culmination of at least 10 degrees; plain next_pass is the
        unfiltered fact."""
        time_ts = self.almanac.time_ts
        for p in passes:
            if p['set'] <= time_ts:
                continue
            if visible_only and not (
                    p['visible'] and
                    p['max_altitude'] >= SAT_VISIBLE_MIN_CULMINATION_DEGREES):
                continue
            return p
        return None


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
