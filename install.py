# Copyright 2022-2026 by John A Kline <john@johnkline.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os
import sys
import time
import urllib.error
import urllib.request
from io import StringIO

import configobj

import weewx
from setup import ExtensionInstaller

# The stanza a fresh install writes into weewx.conf, as text rather than a
# dict so that ConfigObj carries its comments into the user's file.  An
# option that only selects a default is written commented out, so that the
# extension's own fallback -- and a better one in some later release -- goes
# on governing; weectl fills in absent keys only and never rewrites a value
# that is already there, so a value written live here would pin the station
# to it for ever.
CONFIG = """
[Skyfield]
    # This section configures weewx-skyfield, the Skyfield almanac
    # engine.  See the README for details.
    #
    # An option shown commented out is one the extension supplies itself.
    # Leave it commented and the extension's own value governs, including
    # a better one a later release might bring.  Uncomment it to pin this
    # station to the value written here.

    # Fetch satellite orbital elements from CelesTrak, at install and
    # then 3-hourly from weewxd.  Set false on an isolated network;
    # [[Satellites]] still works if you maintain the element files
    # yourself (see the README).
    #satellite_downloads = true

    # Fetch comet orbital elements (one MPC CometEls.txt for all the
    # comets below), at install and then every couple of days from
    # weewxd.  Same isolated-network story as the satellites.
    #comet_downloads = true

    # Set false to leave the extension installed but idle: reports go
    # back to WeeWX's built-in almanac.
    enable = true

    # The satellites to track: tag name = NORAD catalog number.  This one
    # list drives both the tags ($almanac.iss.next_pass) and the fetch
    # list.  The two shipped are the naked-eye space stations, whose
    # inclinations make them visible from essentially all inhabited
    # latitudes.
    [[Satellites]]
        iss = 25544
        tiangong = 48274

    # The comets to track: tag name = MPC designation.  The two shipped
    # tell the two comet stories.  Halley returns (telescope-faint until
    # the 2061 apparition -- the dome marks it with the honest hollow
    # ring); Hale-Bopp left forever (the 1997 great comet, now ~49 AU out
    # and receding, dec -85 so it never rises from northern stations -- a
    # table-and-orrery resident whose distance creeps outward year over
    # year).  Both are the pattern to copy when the next naked-eye comet
    # makes the news: tsuchinshan_atlas = C/2023 A3.
    [[Comets]]
        halley = 1P
        hale_bopp = C/1995 O1

[StdReport]
    [[SkyfieldReport]]
        # The Sky page, a showcase of what the almanac computes,
        # generated once an archive interval.  Its files land in a
        # subdirectory of your HTML_ROOT.  Everything about how the page
        # looks is a skin.conf option that can be overridden here; see
        # the manual's Configuration page.
        HTML_ROOT = skyfield
        enable = true
        skin = Skyfield
"""

INSTALLER_CONFIG = configobj.ConfigObj(StringIO(CONFIG))

# The default satellite and comet sets, read back out of the stanza above
# so there is one copy of each: they are both what a fresh install writes
# and the install-time first-fetch list, used here when the station's
# weewx.conf does not name its own (configure() runs BEFORE the merge).
# weewxd keeps the elements fresh afterwards.
DEFAULT_SATELLITES = dict(INSTALLER_CONFIG['Skyfield']['Satellites'])
DEFAULT_COMETS = dict(INSTALLER_CONFIG['Skyfield']['Comets'])

CELESTRAK_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=%s&FORMAT=TLE'
COMET_URL = 'https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt'

# How long a cached element file stays current.  These are wxskyfield.py's
# own refresh clocks (SAT_REFRESH_SECS, COMET_REFRESH_SECS) written a
# second time: install.py cannot import the module it is installing, so
# tests/test_installer.py keeps the two copies equal.  A file younger than
# its clock is one weewxd would not refetch either, so the install does
# not either -- which is what lets an upgrade over a running station skip
# the network entirely, since weewxd has been keeping these fresh all
# along.
SAT_REFRESH_SECS = 3 * 3600
COMET_REFRESH_SECS = 2 * 86400


class NoSuchSatellite(ValueError):
    """CelesTrak's 404 "No GP data found": it has no current elements for
    the catalog number asked about -- what a mistyped NORAD number looks
    like, and a decayed object too.  Its own class because a retry cannot
    fix it: unlike a timeout or a DNS failure, it must not be reported as
    something weewxd will sort out later.  Nothing else earns this class;
    an answer that merely fails to parse is somebody else's error page and
    is reported as transient."""


def is_current(path, max_age_secs):
    """True if path exists and is younger than max_age_secs.  A missing
    file, or one whose mtime cannot be read, is not current."""
    try:
        return time.time() - os.path.getmtime(path) < max_age_secs
    except OSError:
        return False


def loader():
    if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 9):
        sys.exit("weewx-skyfield requires Python 3.9 or later, found %s.%s" % (
            sys.version_info[0], sys.version_info[1]))

    # Almanac extensions (weewx.almanac.almanacs) arrived in WeeWX 5.2; on
    # anything older this extension would do nothing at all.  A version
    # component that is not a plain integer (e.g., a dev build) is given the
    # benefit of the doubt.
    parts = weewx.__version__.split('.')
    try:
        major_minor = (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        major_minor = None
    if major_minor is not None and major_minor < (5, 2):
        sys.exit("weewx-skyfield requires WeeWX 5.2 or later, found %s" % weewx.__version__)

    return WxSkyfieldInstaller()

class WxSkyfieldInstaller(ExtensionInstaller):
    def __init__(self):
        super(WxSkyfieldInstaller, self).__init__(
            version = "2.3.5",
            name = 'wxskyfield',
            description = "Replaces WeeWX's built-in almanac with a Skyfield based almanac for report generation.",
            author = "John A Kline",
            author_email = "john@johnkline.com",
            data_services = 'user.wxskyfield.WxSkyfield',
            config = INSTALLER_CONFIG,
            files = [
                ('bin/user', [
                    'bin/user/wxskyfield.py',
                    'bin/user/wxskyfield_sky.py',
                    'bin/user/wxskyfield_stars.dat.gz',
                    'bin/user/wxskyfield_lines.dat',
                    'bin/user/wxskyfield_de421.bsp',
                    ]),
                ('skins/Skyfield', [
                    'skins/Skyfield/skin.conf',
                    'skins/Skyfield/index.html.tmpl',
                    'skins/Skyfield/sky.css',
                    'skins/Skyfield/sky.js',
                    ]),
                ('skins/Skyfield/lang', [
                    'skins/Skyfield/lang/en.conf',
                    'skins/Skyfield/lang/de.conf',
                    'skins/Skyfield/lang/fr.conf',
                    'skins/Skyfield/lang/nl.conf',
                    'skins/Skyfield/lang/es.conf',
                    'skins/Skyfield/lang/da.conf',
                    'skins/Skyfield/lang/it.conf',
                    'skins/Skyfield/lang/no.conf',
                    'skins/Skyfield/lang/sv.conf',
                    ]),
            ])

    def configure(self, engine):
        """Fetch the first copy of the satellite and comet orbital
        elements, so their tags work from weewxd's first report cycle.
        Runs before this installer's config is merged, so an upgrade
        honors the station's existing [Skyfield] settings and a fresh
        install uses the defaults above.  Elements the station already
        has and that are still current are not refetched, so an upgrade
        over a running station -- whose caches weewxd has been keeping
        fresh -- usually touches the network not at all.  Every failure
        degrades gracefully -- weewxd fetches on its own schedule -- and
        the install itself never fails here.  Never modifies the
        configuration (always returns False)."""
        try:
            self._fetch_satellite_elements(engine)
        except Exception as e:
            engine.printer.out('Could not fetch satellite elements now (%s); '
                               'weewxd will fetch them itself.' % e)
        try:
            self._fetch_comet_elements(engine)
        except Exception as e:
            engine.printer.out('Could not fetch comet elements now (%s); '
                               'weewxd will fetch them itself.' % e)
        try:
            self._fix_cache_ownership(engine)
        except Exception:
            pass
        return False

    def _announce(self, engine, msg):
        """Say what is about to be downloaded, BEFORE the wait it
        explains.  An install is normally quick, so a silent minute on a
        slow network reads as a hang.  Flushed by hand: Printer.out is a
        bare print(), and a stdout redirected to a log is block-buffered,
        which would hold the heads-up back until after the download it was
        supposed to announce."""
        engine.printer.out(msg)
        try:
            engine.printer.fd.flush()
        except (AttributeError, ValueError):
            pass

    def _cache_dir(self, engine):
        """(base_dir, cache_dir) for the element caches.  The cache lives
        beside the sqlite archive: the conventional home for an
        extension's runtime-writable data (an absolute SQLITE_ROOT wins
        the join, exactly as weewx's own manager resolves it).
        MySQL-only stations have no SQLITE_ROOT and fall back to
        WEEWX_ROOT."""
        weewx_root = engine.config_dict.get('WEEWX_ROOT', '')
        sqlite_root = (engine.config_dict.get('DatabaseTypes', {})
                       .get('SQLite', {}).get('SQLITE_ROOT', ''))
        base_dir = os.path.join(weewx_root, sqlite_root or '.')
        return base_dir, os.path.join(base_dir, 'wxskyfield')

    def _fetch_satellite_elements(self, engine):
        skyfield_dict = engine.config_dict.get('Skyfield', {})
        downloads = str(skyfield_dict.get('satellite_downloads', 'true')).lower()
        if downloads in ('false', 'no', '0'):
            return
        satellites = skyfield_dict.get('Satellites') or DEFAULT_SATELLITES
        _, sat_dir = self._cache_dir(engine)
        current = []
        wanted = []
        for name, norad in satellites.items():
            try:
                catnr = int(str(norad))
            except ValueError:
                # Say so rather than skipping in silence: the whole point
                # of the messages here is that a typo in [[Satellites]]
                # gets noticed at install rather than puzzled over later.
                engine.printer.out('Skipping satellite %s: %r is not a NORAD '
                                   'catalog number.' % (name, str(norad)))
                continue
            path = os.path.join(sat_dir, 'wxskyfield_sat_%d.tle' % catnr)
            if is_current(path, SAT_REFRESH_SECS):
                current.append(str(name))
            else:
                wanted.append((str(name), catnr, path))
        if current:
            engine.printer.out('Satellite elements for %s in %s are current; '
                               'not fetching.' % (', '.join(current), sat_dir))
        if not wanted:
            return
        names = ', '.join(name for name, _, _ in wanted)
        if engine.dry_run:
            engine.printer.out('Would fetch satellite elements for %s into %s.'
                               % (names, sat_dir))
            return
        self._announce(engine, 'Fetching satellite orbital elements for %s '
                               'from CelesTrak...' % names)
        os.makedirs(sat_dir, exist_ok=True)
        fetched = []
        for name, catnr, path in wanted:
            try:
                self._fetch_one_satellite(name, catnr, path)
            except NoSuchSatellite as e:
                # CelesTrak's 404: it has nothing for this number, so the
                # next try will fail the same way.  Say what to fix rather
                # than promising weewxd will sort it out.
                engine.printer.out('%s -- check the NORAD number in '
                                   '[Skyfield] [[Satellites]].' % e)
            except Exception as e:
                # Timeout, DNS, a CelesTrak outage, an answer that is not
                # elements at all: transient, and weewxd retries.  Caught
                # per satellite so one failure does not skip the rest of
                # the list.
                engine.printer.out('Could not fetch elements for %s now (%s); '
                                   'weewxd will fetch them itself.' % (name, e))
            else:
                fetched.append(name)
        if fetched:
            engine.printer.out('Fetched satellite elements for %s into %s.'
                               % (', '.join(fetched), sat_dir))

    def _fetch_one_satellite(self, name, catnr, path):
        """One satellite's TLE, written atomically.  Raises
        NoSuchSatellite only for CelesTrak's 404, the one failure a retry
        cannot fix; everything else raises whatever it raised, to be
        reported as transient."""
        request = urllib.request.Request(
            CELESTRAK_URL % catnr,
            headers={'User-Agent': 'weewx-skyfield/%s (+https://github.com/'
                                   'chaunceygardiner/weewx-skyfield)' % self['version']})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read().decode('ascii', 'replace')
        except urllib.error.HTTPError as e:
            # A catalog number CelesTrak has no current elements for gets
            # 404 "No GP data found" -- what a mistyped NORAD number looks
            # like, and a decayed object too.  Every other status is
            # CelesTrak having a bad moment (503 is common), which is
            # exactly what retrying is for.
            if e.code == 404:
                raise NoSuchSatellite('CelesTrak has no current elements for '
                                      '%s (%d)' % (name, catnr))
            raise
        lines = [line for line in payload.splitlines() if line.strip()]
        if not any(line.startswith('1 %05d' % catnr) for line in lines):
            # NOT NoSuchSatellite: CelesTrak says that with a 404, caught
            # above, so a 200 carrying no element set is something else
            # answering -- a captive portal, an intercepting proxy, an
            # HTML error page.  Blaming the catalog number there would
            # send the user after a correct number and tell them a retry
            # cannot help, when a retry is exactly what fixes it.
            raise ValueError('the answer carried no elements for catalog '
                             'number %d' % catnr)
        tmp_path = '%s.tmp' % path
        with open(tmp_path, 'w') as f:
            f.write(payload)
        os.replace(tmp_path, path)

    def _fetch_comet_elements(self, engine):
        skyfield_dict = engine.config_dict.get('Skyfield', {})
        downloads = str(skyfield_dict.get('comet_downloads', 'true')).lower()
        if downloads in ('false', 'no', '0'):
            return
        if not (skyfield_dict.get('Comets') or DEFAULT_COMETS):
            return
        _, cache_dir = self._cache_dir(engine)
        path = os.path.join(cache_dir, 'wxskyfield_comets.txt')
        if is_current(path, COMET_REFRESH_SECS):
            engine.printer.out('Comet elements in %s are current; not '
                               'fetching.' % path)
            return
        if engine.dry_run:
            engine.printer.out('Would fetch comet elements into %s.' % path)
            return
        self._announce(engine, 'Fetching comet orbital elements from the '
                               'Minor Planet Center (one file covering every '
                               'comet, so this is the slow one)...')
        os.makedirs(cache_dir, exist_ok=True)
        request = urllib.request.Request(
            COMET_URL,
            headers={'User-Agent': 'weewx-skyfield/%s (+https://github.com/'
                                   'chaunceygardiner/weewx-skyfield)' % self['version']})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode('ascii', 'replace')
        # Light validation (the installer cannot import wxskyfield): at
        # least one fixed-width row whose perihelion-distance column is a
        # number.  Never require specific designations.
        def plausible(line):
            try:
                float(line[30:39])
                return len(line) > 102
            except (ValueError, IndexError):
                return False
        if not any(plausible(line) for line in payload.splitlines()):
            raise ValueError('no comet rows in the MPC answer')
        tmp_path = '%s.tmp' % path
        with open(tmp_path, 'w') as f:
            f.write(payload)
        os.replace(tmp_path, path)
        engine.printer.out('Fetched comet elements into %s.' % path)

    def _fix_cache_ownership(self, engine):
        """weectl install often runs as root while weewxd runs
        unprivileged; root-owned cache files would silently break every
        later refresh.  Mirror the ownership of the archive directory
        itself -- whoever owns the database owns the elements -- and stay
        quiet if chown is not ours to do (pip installs run unprivileged
        already).  Runs after BOTH fetches, whichever of them were
        enabled."""
        base_dir, cache_dir = self._cache_dir(engine)
        if engine.dry_run or not os.path.isdir(cache_dir):
            return
        try:
            stat = os.stat(base_dir)
            os.chown(cache_dir, stat.st_uid, stat.st_gid)
            for entry in os.listdir(cache_dir):
                os.chown(os.path.join(cache_dir, entry), stat.st_uid, stat.st_gid)
        except OSError:
            pass
