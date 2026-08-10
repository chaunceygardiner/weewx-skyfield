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
import urllib.request

import weewx
from setup import ExtensionInstaller

# The default satellite set: naked-eye space stations whose inclinations
# make them visible from essentially all inhabited latitudes.  This map is
# both the injected [Skyfield] [[Satellites]] config and the install-time
# first-fetch list; weewxd keeps the elements fresh afterwards.
DEFAULT_SATELLITES = {
    'iss'     : '25544',
    'tiangong': '48274',
}

# The default comets: the two names everybody knows.  Halley tells the
# it-returns story (telescope-faint until the 2061 apparition -- the
# dome marks it with the honest hollow ring); Hale-Bopp the
# it-left-forever story (the 1997 great comet, now ~49 AU out and
# receding, dec -85 so it never rises from northern stations -- a
# table-and-orrery resident whose distance creeps outward year over
# year).  Both entries are the pattern users copy when the next
# naked-eye comet makes the news.
DEFAULT_COMETS = {
    'halley': '1P',
    'hale_bopp': 'C/1995 O1',
}

CELESTRAK_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=%s&FORMAT=TLE'
COMET_URL = 'https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt'

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
            version = "2.1",
            name = 'wxskyfield',
            description = "Replaces WeeWX's built-in almanac with a Skyfield based almanac for report generation.",
            author = "John A Kline",
            author_email = "john@johnkline.com",
            data_services = 'user.wxskyfield.WxSkyfield',
            config = {
                'Skyfield': {
                    'enable': 'true',
                    # Fetch satellite orbital elements from CelesTrak, at
                    # install and then 3-hourly from weewxd.  Set false on
                    # an isolated network; [[Satellites]] still works if
                    # you maintain the element files yourself (see the
                    # README).
                    'satellite_downloads': 'true',
                    'Satellites': dict(DEFAULT_SATELLITES),
                    # Fetch comet orbital elements (one MPC CometEls.txt
                    # for all configured comets), at install and then
                    # every couple of days from weewxd.  Same isolated-
                    # network story as the satellites.
                    'comet_downloads': 'true',
                    'Comets': dict(DEFAULT_COMETS),
                },
                'StdReport': {
                    'SkyfieldReport': {
                        'skin': 'Skyfield',
                        'enable': 'true',
                        'HTML_ROOT': 'skyfield',
                    },
                },
            },
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
        install uses the defaults above.  Every failure degrades
        gracefully -- weewxd fetches on its own schedule -- and the
        install itself never fails here.  Never modifies the
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
        if engine.dry_run:
            engine.printer.out('Would fetch satellite elements into %s.' % sat_dir)
            return
        os.makedirs(sat_dir, exist_ok=True)
        fetched = []
        for name, norad in satellites.items():
            try:
                catnr = int(str(norad))
            except ValueError:
                continue
            path = os.path.join(sat_dir, 'wxskyfield_sat_%d.tle' % catnr)
            request = urllib.request.Request(
                CELESTRAK_URL % catnr,
                headers={'User-Agent': 'weewx-skyfield/%s (+https://github.com/'
                                       'chaunceygardiner/weewx-skyfield)' % self['version']})
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read().decode('ascii', 'replace')
            lines = [line for line in payload.splitlines() if line.strip()]
            if not any(line.startswith('1 %05d' % catnr) for line in lines):
                raise ValueError('no TLE for %s (%s) in the CelesTrak answer' % (name, catnr))
            tmp_path = '%s.tmp' % path
            with open(tmp_path, 'w') as f:
                f.write(payload)
            os.replace(tmp_path, path)
            fetched.append(str(name))
        if fetched:
            engine.printer.out('Fetched satellite elements for %s into %s.'
                               % (', '.join(fetched), sat_dir))

    def _fetch_comet_elements(self, engine):
        skyfield_dict = engine.config_dict.get('Skyfield', {})
        downloads = str(skyfield_dict.get('comet_downloads', 'true')).lower()
        if downloads in ('false', 'no', '0'):
            return
        if not (skyfield_dict.get('Comets') or DEFAULT_COMETS):
            return
        _, cache_dir = self._cache_dir(engine)
        path = os.path.join(cache_dir, 'wxskyfield_comets.txt')
        if engine.dry_run:
            engine.printer.out('Would fetch comet elements into %s.' % path)
            return
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
