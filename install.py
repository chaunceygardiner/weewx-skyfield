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
import weewx
from setup import ExtensionInstaller

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
            version = "1.2",
            name = 'wxskyfield',
            description = "Replaces WeeWX's built-in almanac with a Skyfield based almanac for report generation.",
            author = "John A Kline",
            author_email = "john@johnkline.com",
            data_services = 'user.wxskyfield.WxSkyfield',
            config = {
                'Skyfield': {
                    'enable': 'true',
                    'stars' : 'true',
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
                    'bin/user/wxskyfield_stars.dat',
                    'bin/user/wxskyfield_de421.bsp',
                    ]),
                ('skins/Skyfield', [
                    'skins/Skyfield/skin.conf',
                    'skins/Skyfield/index.html.tmpl',
                    'skins/Skyfield/sky.css',
                    ]),
            ])
