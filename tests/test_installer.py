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
enforce: the stanza is text rather than a dict so ConfigObj carries its
comments into the user's file; an option the code can answer for itself is
written commented out so its fallback goes on governing; and a commented
option needs a live key after it in the same section, because ConfigObj
attaches a comment block to the NEXT key.
"""

import ast
import importlib
import importlib.util
import io
import os
import re
import time
import urllib.error

import configobj
import pytest

import weeutil.config
import weeutil.printer
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


def _get_module_constants(path, names):
    """The module-level constants named, read statically.  ast.literal_eval
    will not do: these are written as arithmetic (3 * 3600), which reads
    better than the seconds -- so the literal expression is unparsed and
    evaluated with no builtins and no names in scope."""
    with open(path, 'r') as f:
        tree = ast.parse(f.read(), filename=path)
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                found[target.id] = eval(ast.unparse(node.value),
                                        {'__builtins__': {}}, {})
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

    def test_refresh_clocks_match_the_extension(self):
        """The installer skips a download whose cached file is younger
        than the extension's own refresh interval -- the file weewxd would
        not refetch either.  install.py cannot import wxskyfield, so it
        carries its own copy of the two clocks; this is what keeps them
        equal.  If wxskyfield.py's cadence changes, change install.py's to
        match: a stale copy here would make an install fetch what weewxd
        considers current, or skip what it considers stale."""
        module = install_module()
        names = {'SAT_REFRESH_SECS', 'COMET_REFRESH_SECS'}
        runtime = _get_module_constants(SOURCE, names)
        assert sorted(runtime) == sorted(names), (
            'wxskyfield.py no longer defines %s at module level'
            % sorted(names - set(runtime)))
        assert module.SAT_REFRESH_SECS == runtime['SAT_REFRESH_SECS']
        assert module.COMET_REFRESH_SECS == runtime['COMET_REFRESH_SECS']

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


# ---------------------------------------------------------------------------
# The install-time first fetch.
#
# An install is normally quick, so the seconds spent downloading orbital
# elements read as a hang unless the installer says what it is waiting for.
# The behaviors pinned below: the heads-up arrives BEFORE the download rather
# than after it, a cached file that is still current is not fetched at all
# (the usual case on an upgrade, where weewxd has been keeping it fresh), and
# a NORAD number CelesTrak does not know is reported as something to fix
# rather than as something weewxd will retry -- because it will retry it, for
# ever, and fail.
# ---------------------------------------------------------------------------


def satellite_payload(catnr, name='TESTSAT'):
    """A two-line element set the installer's validation accepts: it looks
    only for a line 1 carrying the catalog number asked for."""
    return ('%s\n'
            '1 %05d U 98067A   25172.50000000  .00016717  00000-0  10270-3 0  9007\n'
            '2 %05d  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n'
            % (name, catnr, catnr))


def no_such_satellite_error(url):
    """What CelesTrak answers for a catalog number it has no current
    elements for: HTTP 404 carrying 'No GP data found'.  Verified against
    the live service -- a mistyped NORAD number never reaches the
    installer's own validation of the payload, which is why the 404 has to
    be read as the same fact."""
    return urllib.error.HTTPError(url, 404, 'Not Found', {},
                                  io.BytesIO(b'No GP data found'))


# One MPC CometEls.txt row: the installer accepts a file with at least one
# line long enough to be a record whose perihelion-distance column parses.
COMET_PAYLOAD = '%s0.5859780%s\n' % (' ' * 30, ' ' * 70)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload.encode('ascii')

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeEngine:
    """The parts of weecfg's ExtensionEngine that configure() touches."""

    def __init__(self, tmp_path, skyfield=None, dry_run=False):
        self.config_dict = {
            'WEEWX_ROOT': str(tmp_path),
            'DatabaseTypes': {'SQLite': {'SQLITE_ROOT': 'archive'}},
        }
        if skyfield is not None:
            self.config_dict['Skyfield'] = skyfield
        self.dry_run = dry_run
        self.printer = weeutil.printer.Printer(fd=io.StringIO())

    @property
    def output(self):
        return self.printer.fd.getvalue()

    @property
    def cache_dir(self):
        return os.path.join(self.config_dict['WEEWX_ROOT'], 'archive',
                            'wxskyfield')


@pytest.fixture
def engine_factory(tmp_path):
    """A FakeEngine whose archive directory exists, since that is what the
    real cache directory is created beside."""
    os.makedirs(os.path.join(str(tmp_path), 'archive'), exist_ok=True)

    def make(skyfield=None, dry_run=False):
        return FakeEngine(tmp_path, skyfield=skyfield, dry_run=dry_run)
    return make


@pytest.fixture
def installer():
    return install_module().WxSkyfieldInstaller()


@pytest.fixture
def fake_urlopen(monkeypatch):
    """Replaces urllib.request.urlopen for the installer's fetches.  The
    calls are recorded, along with everything printed at the moment each
    one was made -- which is how the heads-up is shown to arrive before
    the download and not after it."""
    module = install_module()
    calls = []

    class Downloads:
        def __init__(self):
            self.answers = {}
            self.raises = {}
            self.calls = calls
            # Called with the key the moment the download starts, before
            # anything is returned: how a test sees what had already been
            # printed when the installer began to wait.
            self.observer = None

        def _key(self, url):
            if 'CATNR=' in url:
                return int(url.split('CATNR=')[1].split('&')[0])
            return 'comets'

        def __call__(self, request, timeout=None):
            key = self._key(request.full_url)
            calls.append(key)
            if self.observer:
                self.observer(key)
            if key in self.raises:
                raise self.raises[key]
            return FakeResponse(self.answers[key])

    downloads = Downloads()
    monkeypatch.setattr(module.urllib.request, 'urlopen', downloads)
    return downloads


def write_cache(engine, name, age_secs):
    """A cached element file of the given age."""
    os.makedirs(engine.cache_dir, exist_ok=True)
    path = os.path.join(engine.cache_dir, name)
    with open(path, 'w') as f:
        f.write('cached\n')
    when = time.time() - age_secs
    os.utime(path, (when, when))
    return path


class TestInstallTimeFetch:

    def test_current_files_are_not_fetched_at_all(self, engine_factory,
                                                  installer, fake_urlopen):
        """The usual upgrade: weewxd has been refreshing these all along,
        so the install finds every cache younger than the interval weewxd
        itself uses and touches the network not at all."""
        engine = engine_factory()
        module = install_module()
        for norad in module.DEFAULT_SATELLITES.values():
            write_cache(engine, 'wxskyfield_sat_%s.tle' % norad, 60)
        write_cache(engine, 'wxskyfield_comets.txt', 3600)

        installer.configure(engine)

        assert fake_urlopen.calls == []
        assert 'are current; not fetching' in engine.output
        assert 'Comet elements in' in engine.output
        assert 'Fetching' not in engine.output

    def test_stale_files_are_fetched(self, engine_factory, installer,
                                     fake_urlopen):
        """Past the refresh interval, the install fetches as it always
        did.  A station that has been down a week gets fresh elements."""
        engine = engine_factory()
        module = install_module()
        for norad in module.DEFAULT_SATELLITES.values():
            write_cache(engine, 'wxskyfield_sat_%s.tle' % norad,
                        module.SAT_REFRESH_SECS + 60)
            fake_urlopen.answers[int(norad)] = satellite_payload(int(norad))
        write_cache(engine, 'wxskyfield_comets.txt',
                    module.COMET_REFRESH_SECS + 60)
        fake_urlopen.answers['comets'] = COMET_PAYLOAD

        installer.configure(engine)

        assert sorted(str(c) for c in fake_urlopen.calls) == sorted(
            [str(int(n)) for n in module.DEFAULT_SATELLITES.values()]
            + ['comets'])
        assert 'Fetched satellite elements for' in engine.output
        assert 'Fetched comet elements into' in engine.output

    def test_the_heads_up_precedes_the_download(self, engine_factory,
                                                installer, fake_urlopen):
        """The point of the whole exercise: what the installer is waiting
        for is on screen BEFORE it waits, so a slow network does not read
        as a hang.  Checked by capturing the output as it stood at the
        moment each download was made, not at the end."""
        engine = engine_factory(skyfield={'Satellites': {'iss': 25544},
                                          'Comets': {'halley': '1P'}})
        fake_urlopen.answers[25544] = satellite_payload(25544)
        fake_urlopen.answers['comets'] = COMET_PAYLOAD
        seen = {}
        fake_urlopen.observer = lambda key: seen.__setitem__(key,
                                                             engine.output)

        installer.configure(engine)

        assert 'Fetching satellite orbital elements for iss' in seen[25544]
        assert 'Fetching comet orbital elements' in seen['comets']

    def test_a_mistyped_norad_says_what_to_fix(self, engine_factory,
                                               installer, fake_urlopen):
        """CelesTrak answered and had nothing: no retry can help, so the
        message must not promise one.  And the bad entry must not cost the
        rest of the list -- it is listed first here on purpose."""
        engine = engine_factory(skyfield={
            'comet_downloads': 'false',
            'Satellites': {'oops': 99999, 'iss': 25544}})
        fake_urlopen.raises[99999] = no_such_satellite_error(
            install_module().CELESTRAK_URL % 99999)
        fake_urlopen.answers[25544] = satellite_payload(25544)

        installer.configure(engine)

        assert 'CelesTrak has no current elements for oops (99999)' in engine.output
        assert 'check the NORAD number' in engine.output
        assert 'weewxd will fetch' not in engine.output
        assert 'Fetched satellite elements for iss' in engine.output
        assert os.path.exists(os.path.join(engine.cache_dir,
                                           'wxskyfield_sat_25544.tle'))

    def test_an_unparseable_answer_is_transient(self, engine_factory,
                                                installer, fake_urlopen):
        """A 200 carrying no element set is NOT the no-such-satellite
        fact: CelesTrak says that with a 404.  It is a captive portal, an
        intercepting proxy or an error page answering instead -- causes a
        retry does fix, so blaming the catalog number would send the user
        after a number that is correct."""
        engine = engine_factory(skyfield={'comet_downloads': 'false',
                                          'Satellites': {'iss': 25544}})
        fake_urlopen.answers[25544] = '<html>Sign in to continue</html>\n'

        installer.configure(engine)

        assert 'Could not fetch elements for iss now' in engine.output
        assert 'weewxd will fetch them itself' in engine.output
        assert 'check the NORAD number' not in engine.output

    def test_a_server_error_is_not_a_bad_norad(self, engine_factory,
                                               installer, fake_urlopen):
        """CelesTrak answers 503 when it is shedding load, which says
        nothing about the catalog number -- it must read as transient."""
        engine = engine_factory(skyfield={'comet_downloads': 'false',
                                          'Satellites': {'iss': 25544}})
        fake_urlopen.raises[25544] = urllib.error.HTTPError(
            install_module().CELESTRAK_URL % 25544, 503,
            'Service Unavailable', {}, io.BytesIO(b''))

        installer.configure(engine)

        assert 'weewxd will fetch them itself' in engine.output
        assert 'check the NORAD number' not in engine.output

    def test_a_norad_that_is_not_a_number_is_named(self, engine_factory,
                                                   installer, fake_urlopen):
        """It cannot even be asked for, so it is skipped -- but out loud,
        for the same reason as the 404: a typo noticed at install is a typo
        not puzzled over later."""
        engine = engine_factory(skyfield={'comet_downloads': 'false',
                                          'Satellites': {'oops': '2554a',
                                                         'iss': 25544}})
        fake_urlopen.answers[25544] = satellite_payload(25544)

        installer.configure(engine)

        assert 'Skipping satellite oops' in engine.output
        assert 'not a NORAD catalog number' in engine.output
        assert 'Fetched satellite elements for iss' in engine.output

    def test_a_transient_failure_still_promises_the_retry(self, engine_factory,
                                                          installer,
                                                          fake_urlopen):
        """A timeout is exactly what weewxd's own 3-hourly fetch is for,
        so here the reassurance is true -- and again, one satellite's
        failure does not skip the next."""
        engine = engine_factory(skyfield={
            'comet_downloads': 'false',
            'Satellites': {'oops': 99999, 'iss': 25544}})
        fake_urlopen.raises[99999] = OSError('timed out')
        fake_urlopen.answers[25544] = satellite_payload(25544)

        installer.configure(engine)

        assert 'Could not fetch elements for oops now' in engine.output
        assert 'weewxd will fetch them itself' in engine.output
        assert 'check the NORAD number' not in engine.output
        assert 'Fetched satellite elements for iss' in engine.output

    def test_dry_run_reports_what_it_would_do(self, engine_factory, installer,
                                              fake_urlopen):
        """--dry-run names the satellites it would fetch and skips the
        ones it would not: the freshness check runs first, so the report
        matches the install that would follow."""
        engine = engine_factory(skyfield={
            'Satellites': {'iss': 25544, 'tiangong': 48274},
            'Comets': {'halley': '1P'}}, dry_run=True)
        write_cache(engine, 'wxskyfield_sat_25544.tle', 60)
        write_cache(engine, 'wxskyfield_comets.txt', 3600)

        installer.configure(engine)

        assert fake_urlopen.calls == []
        assert 'Satellite elements for iss' in engine.output
        assert 'Would fetch satellite elements for tiangong' in engine.output
        assert 'Would fetch comet elements' not in engine.output

    def test_downloads_off_fetches_nothing(self, engine_factory, installer,
                                           fake_urlopen):
        """The isolated-network station: no announcement either, since
        there is no wait to explain."""
        engine = engine_factory(skyfield={'satellite_downloads': 'false',
                                          'comet_downloads': 'false'})
        installer.configure(engine)
        assert fake_urlopen.calls == []
        assert engine.output == ''
