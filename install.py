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

import sys
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

    # Fetch satellite orbital elements from CelesTrak: weewxd fetches them
    # at startup and then every three hours.  Set false on an isolated
    # network; [[Satellites]] still works if you maintain the element
    # files yourself (see the README).
    #satellite_downloads = true

    # Fetch comet orbital elements (one MPC CometEls.txt for all the
    # comets below): weewxd fetches it at startup and then every couple
    # of days.  Same isolated-network story as the satellites.
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

# The oldest Skyfield the extension runs on: wxskyfield.py's
# SKYFIELD_MIN_VERSION, which says why, written a second time because
# install.py cannot import the module it installs; tests/test_installer.py
# keeps the two equal.
SKYFIELD_MIN_VERSION = (1, 47)
UPGRADING_URL = ('https://chaunceygardiner.github.io/weewx-skyfield/'
                 'installation.html#upgrading-skyfield')


def skyfield_requirement():
    """Why this station's Skyfield will not do, or None when it will."""
    try:
        import skyfield
        found = tuple(skyfield.VERSION[:2])
    except ImportError:
        return ('weewx-skyfield requires Skyfield %d.%d or later, which is not '
                'installed.  Install it first: %s' % (SKYFIELD_MIN_VERSION + (UPGRADING_URL,)))
    if found < SKYFIELD_MIN_VERSION:
        return ('weewx-skyfield requires Skyfield %d.%d or later, found %d.%d.  '
                'Upgrade it first: %s' % (SKYFIELD_MIN_VERSION + found + (UPGRADING_URL,)))
    return None


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

    # Below it the almanac declines at startup; checked here so an install
    # stops before it leaves weewxd with no almanac at all.
    message = skyfield_requirement()
    if message:
        sys.exit(message)

    return WxSkyfieldInstaller()


class WxSkyfieldInstaller(ExtensionInstaller):
    """Installs the files and merges the stanza; nothing else.  The
    satellite and comet orbital elements are fetched by weewxd itself,
    which asks for whatever is missing or stale within seconds of
    starting, so the installer has no download to make and no cache file
    to create or chown."""

    def __init__(self):
        super(WxSkyfieldInstaller, self).__init__(
            version = "2.12",
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
