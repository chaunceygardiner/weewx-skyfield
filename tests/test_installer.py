"""
test_installer.py

Copyright (C)2022-2026 by John A Kline (john@johnkline.com)
Distributed under the terms of the GNU Public License (GPLv3)

install.py's config stanza.  It is read on a fresh `weectl extension
install` and never again: weecfg merges it with conditional_merge, which
fills in absent keys only and never rewrites, so a wrong value here ships
silently and stays for the life of the station.

Two of those failures have their own guard below -- an option written live
whose value drifts from the default the code applies, and a commented-out
option that merges outside the section it documents.  The convention they
enforce (why the stanza is text, which options stay live, and why a
commented option needs a live key after it) is written up in CLAUDE.md.
"""

import ast
import importlib
import importlib.util
import io
import os
import re

import configobj

import weeutil.config
import weeutil.weeutil

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TEST_DIR)
INSTALL_PY = os.path.join(REPO_ROOT, 'install.py')
SOURCE = os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield.py')


def install_module():
    """install.py, loaded as a module.  Loading it needs weecfg.extension
    imported first: that module aliases itself as 'setup' in sys.modules
    for installers written against the pre-5.0 name, which is what
    install.py's own import resolves through."""
    importlib.import_module('weecfg.extension')      # registers the alias
    spec = importlib.util.spec_from_file_location('wxskyfield_install',
                                                  INSTALL_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installer_config():
    """The stanza the installer hands weectl, whichever form it is
    written in."""
    return install_module().WxSkyfieldInstaller()['config']


# A commented-out assignment: '#comet_downloads = true', never a prose
# comment, which always has a space after the '#'.
COMMENTED_OPTION_RE = re.compile(r'^(\s*)#(\w+)\s*=\s*(.+?)\s*$')
SECTION_RE = re.compile(r'^\s*(\[+)([^\]]+)\]+\s*$')


def commented_options():
    """install.py's commented-out assignments, as {section: {option:
    value}}.  Read out of CONFIG as text because a commented-out option is
    by definition absent from the parsed object."""
    found = {}
    section = None
    for line in install_module().CONFIG.splitlines():
        header = SECTION_RE.match(line)
        if header:
            section = header.group(2).strip()
            continue
        option = COMMENTED_OPTION_RE.match(line)
        if option:
            found.setdefault(section, {})[option.group(2)] = option.group(3)
    return found


def _get_defaults(path, keys):
    """The fallback in every `<something>.get('<key>', <constant>)` call in
    `path`, for the keys asked about.  A static read of the expression that
    actually governs when the option is absent from weewx.conf -- reaching
    it at run time would mean standing up the whole service."""
    with open(path, 'r') as f:
        tree = ast.parse(f.read(), filename=path)
    found = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get'
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in keys
                and isinstance(node.args[1], ast.Constant)):
            found[node.args[0].value] = node.args[1].value
    return found


class TestInstallerConfig:

    def test_live_options_are_the_ones_named_here(self):
        """What stays live, as a COMPLETE SET.

        `enable` is live because a user turning the extension off is not
        selecting a default, and [[Satellites]] / [[Comets]] because they
        are content the user edits, not tuning -- despite
        `get('Satellites') or DEFAULT_SATELLITES` giving them the shape of
        an option with a fallback.  The report stanza is live because
        weectl needs all three to run the report at all.

        Pinned as a complete set rather than by checking that today's
        commented-out options are absent: a named-absence check only
        guards the options that already exist, and a release that adds a
        new one live -- against a matching fallback in the code -- would be
        the very drift this scheme exists to prevent.  Adding a live key
        has to be a deliberate act that edits this test."""
        config = installer_config()
        assert sorted(config.keys()) == ['Skyfield', 'StdReport']

        skyfield = config['Skyfield']
        # .scalars is a section's non-section keys, so this is the whole
        # set, not a spot check.
        assert skyfield.scalars == ['enable']
        assert weeutil.weeutil.to_bool(skyfield['enable'])
        assert sorted(skyfield.sections) == ['Comets', 'Satellites']
        assert dict(skyfield['Satellites']) == {'iss': '25544',
                                                'tiangong': '48274'}
        assert dict(skyfield['Comets']) == {'halley': '1P',
                                            'hale_bopp': 'C/1995 O1'}

        report = config['StdReport']['SkyfieldReport']
        assert sorted(report.scalars) == ['HTML_ROOT', 'enable', 'skin']
        assert report['skin'] == 'Skyfield'
        assert weeutil.weeutil.to_bool(report['enable'])

    def test_html_root_is_a_bare_subdirectory(self):
        """weectl prepends the station's own [StdReport] HTML_ROOT at
        install time (weecfg/extension.py), so 'skyfield' becomes
        public_html/skyfield -- or whatever that station uses.  Writing
        'public_html/skyfield' here would install to
        public_html/public_html/skyfield."""
        report = installer_config()['StdReport']['SkyfieldReport']
        assert report['HTML_ROOT'] == 'skyfield'

    def test_default_sets_are_read_back_out_of_the_stanza(self):
        """DEFAULT_SATELLITES and DEFAULT_COMETS are the install-time
        first-fetch lists, used when the station's weewx.conf names none of
        its own -- configure() runs BEFORE the merge, so on a fresh install
        they are what gets fetched.  They are derived from CONFIG rather
        than written twice, which is what keeps the elements fetched at
        install equal to the tags the merged stanza then creates."""
        module = install_module()
        skyfield = module.WxSkyfieldInstaller()['config']['Skyfield']
        assert module.DEFAULT_SATELLITES == dict(skyfield['Satellites'])
        assert module.DEFAULT_COMETS == dict(skyfield['Comets'])
        assert module.DEFAULT_SATELLITES and module.DEFAULT_COMETS
        for pairs in (module.DEFAULT_SATELLITES, module.DEFAULT_COMETS):
            assert type(pairs) is dict
            for name, value in pairs.items():
                assert isinstance(name, str) and isinstance(value, str)

    def test_commented_options_match_the_value_that_governs(self):
        """The drift guard.  A commented-out option shows the user the
        value that will actually be used, so it must equal the fallback
        applied when the key is absent -- and once the installer stops
        writing it live, that fallback is the only thing that governs.

        WHICH SIDE MOVES WHEN THIS FAILS IS A JUDGEMENT, NOT A FORMALITY.
        Do not make it pass by editing the commented-out assignment to
        match the code.  While the option was written live, the installer's
        value is what every fresh install has actually been running and the
        code's fallback was never reached, so editing the assignment down
        to the fallback turns the test green while silently changing what
        new stations get.  Moving the fallback is usually what preserves
        behavior; moving the assignment is a deliberate change of default
        and belongs in changes.txt.  Existing stations are unaffected
        either way -- their weewx.conf already carries whatever the
        installer wrote, and an upgrade never rewrites it.

        Two fallbacks govern each of these, and both are checked: weewxd's
        (wxskyfield.py, every archive cycle from then on) and the
        installer's own (configure(), which runs before the merge and does
        the first fetch)."""
        commented = dict(commented_options()['Skyfield'])
        keys = {'satellite_downloads', 'comet_downloads'}
        runtime = _get_defaults(SOURCE, keys)
        install_time = _get_defaults(INSTALL_PY, keys)
        for key in sorted(keys):
            shown = weeutil.weeutil.to_bool(commented.pop(key))
            assert key in runtime, (
                '%s is commented out in the installer stanza, so nothing but '
                "wxskyfield.py's own fallback decides it -- and there is no "
                '.get(%r, <default>) there to find' % (key, key))
            assert shown == weeutil.weeutil.to_bool(runtime[key]), (
                'the stanza shows %s = %s but wxskyfield.py falls back to %s. '
                'Read this test before choosing which side to move.'
                % (key, shown, runtime[key]))
            assert key in install_time, (
                'install.py no longer reads a fallback for %s, so the first '
                'fetch and the stanza can no longer be compared' % key)
            assert shown == weeutil.weeutil.to_bool(install_time[key]), (
                'the stanza shows %s = %s but install.py fetches as though it '
                'were %s' % (key, shown, install_time[key]))
        assert commented == {}, (
            'commented out in [Skyfield] with nothing checking it against the '
            'value that governs: %s' % sorted(commented))

    def test_merged_stanza_keeps_comments_in_their_own_section(self):
        """The placement rule, checked through the real merge.  ConfigObj
        attaches a comment block to the NEXT key, so a commented-out option
        that is last in its section attaches to whatever comes next and is
        written at the PARENT's indentation, where it reads as an option of
        the parent rather than of the block it documents.  [Skyfield]
        therefore ends its scalars with a live key (enable).  This merges
        the stanza the way weectl does -- weeutil.config's
        conditional_merge, which transfers comments along with the keys it
        creates -- and checks that every commented-out assignment lands
        indented with the section it belongs to."""
        # A weewx.conf with no [Skyfield] yet.  Parsed from text rather
        # than built empty: ConfigObj takes its indent_type from what it
        # read, and a config that was never read indents nothing at all.
        merged = configobj.ConfigObj(io.StringIO(
            '[Station]\n    location = home\n'))
        weeutil.config.conditional_merge(merged, installer_config())
        out = io.BytesIO()
        merged.write(out)

        depth = 0
        seen = 0
        for line in out.getvalue().decode('utf-8').splitlines():
            header = SECTION_RE.match(line)
            if header:
                depth = len(header.group(1))
                continue
            option = COMMENTED_OPTION_RE.match(line)
            if option:
                seen += 1
                assert len(option.group(1)) == 4 * depth, (
                    'wrong indentation, so it merged outside its section: %r'
                    % line)
        # satellite_downloads and comet_downloads.
        assert seen == 2
