"""Permanent audits: the manual and the code stay in lockstep.

Documentation drifts silently.  Every list that exists both in code and in
prose is a place where a release can quietly make the manual wrong, and
nothing notices until a user does.  These audits make each of those
failures loud, at the cost of one test run:

  * every almanac tag the source serves is in docs/tag-index.md;
  * every internal link and anchor between manual pages resolves;
  * the [Skyfield] options in docs/configuration.md are the ones the
    service actually accepts, and the Sky page's documented defaults are
    the ones skins/Skyfield/skin.conf actually sets;
  * every $sky_page panel method is documented on docs/panels.md;
  * docs/i18n-dictionary.md is skins/Skyfield/lang/en.conf, verbatim.

(docs/recipes.md's tag chains are evaluated against a real almanac by
TestManualRecipes in test_almanac.py, which needs the fixtures there.)

Everything here is static: ast for the source, text for the manual.  No
weewx, skyfield, ephemeris, ruby or network, so the audits run wherever
pytest does.

When one of these fails, the fix is usually the manual.  When it is
genuinely the test -- a name that is not user-visible, a method that is not
a panel -- add it to the exemption set NEXT TO ITS REASON.  An exemption
without a reason is how an audit quietly stops auditing.
"""

import ast
import os
import re
from typing import Any, Dict, Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield.py')
TAG_INDEX = os.path.join(REPO_ROOT, 'docs', 'tag-index.md')

# Functions whose ``attr`` comparisons name user-visible tags.
DISPATCH_FUNCTIONS = {'get_almanac_data', '_evaluate', '_satellite_attr',
                      '_comet_missing_attr'}

# Classes whose __init__ assigns the attributes a returned object exposes.
RESULT_CLASSES = {'SatellitePass', 'MeteorShowerInfo'}

# Module-level tables whose KEYS (dicts) or ELEMENTS (tuples/sets) are tags.
TAG_TABLES = {'SEASON_EVENTS', 'MOON_EVENTS', 'ECLIPSE_EVENTS',
              'EARTH_APSIS_ATTRS', 'APSIS_ATTRS', 'VALUE_HELPER_ANGLES',
              'FLOAT_ANGLES'}

# Names that are not tags: internal dict keys, sentinels, and the
# attributes Python itself asks for.  Each needs a reason to be here.
NOT_TAGS = {
    'mro', 'im_func', 'func_code',          # python internals, declined
    'culmination',                          # SatellitePass key, documented
                                            # as .culmination under next_pass
    'key',                                  # MeteorShowerInfo internal id
    'max_altitude', 'rise_azimuth', 'culmination_azimuth', 'set_azimuth',
    'duration',                             # ditto: pass sub-attributes,
                                            # documented under next_pass
    'peak', 'zhr', 'parent', 'radiant_ra', 'radiant_dec', 'radiant_alt',
    'radiant_az',                           # shower sub-attributes,
                                            # documented under
                                            # next_meteor_shower
}

# Tags served as callables rather than through attr dispatch.  These cannot
# be told apart from the binder's internal helpers automatically (both are
# plain defs), so they are named here; the landmark test guards the rest.
CALLABLE_TAGS = {
    'visible_change',   # binder method, $almanac.sun.visible_change(2)
    'separation',       # $almanac.separation(body1, body2)
}


def _module() -> ast.Module:
    with open(SOURCE, 'r') as f:
        return ast.parse(f.read(), filename=SOURCE)


def _string_elements(node: ast.AST) -> Set[str]:
    """The string constants of a tuple/list/set literal."""
    out: Set[str] = set()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                out.add(element.value)
    return out


def _tables(tree: ast.Module) -> Dict[str, Set[str]]:
    """The tag tables, by name.  Walks the whole tree, not just the module
    body: VALUE_HELPER_ANGLES and FLOAT_ANGLES are class attributes of
    SkyfieldAlmanacBinder, and scanning only top level silently loses every
    angle tag."""
    tables: Dict[str, Set[str]] = {}
    for node in ast.walk(tree):
        targets: list = []
        value: Any = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in TAG_TABLES:
                continue
            if isinstance(value, ast.Dict):
                keys: Set[str] = set()
                for key in value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
                tables[target.id] = keys
            else:
                tables[target.id] = _string_elements(value)
    return tables


def served_tags() -> Set[str]:
    """Every user-visible tag name the source serves."""
    tree = _module()
    tables = _tables(tree)
    tags: Set[str] = set()
    for names in tables.values():
        tags |= names

    # ECLIPSE_ATTRS is computed from ECLIPSE_EVENTS: the per-kind tags, a
    # _type companion for each, and the combined next_/previous_eclipse
    # family spelled out as a set literal.
    for name in tables.get('ECLIPSE_EVENTS', set()):
        tags.add(name)
        tags.add(name + '_type')
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'ECLIPSE_ATTRS'):
            for inner in ast.walk(node.value):
                tags |= _string_elements(inner)

    for node in ast.walk(tree):
        # attr == 'mag'  /  attr in ('rise', 'set', 'transit')
        if isinstance(node, ast.FunctionDef) and node.name in DISPATCH_FUNCTIONS:
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Compare):
                    continue
                if not (isinstance(inner.left, ast.Name) and inner.left.id == 'attr'):
                    continue
                for comparator in inner.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                        tags.add(comparator.value)
                    tags |= _string_elements(comparator)
                    # attr in SOME_TABLE
                    if isinstance(comparator, ast.Name) and comparator.id in tables:
                        tags |= tables[comparator.id]
        # self.rise = ... in SatellitePass / MeteorShowerInfo
        if isinstance(node, ast.ClassDef) and node.name in RESULT_CLASSES:
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Attribute)
                        and isinstance(inner.ctx, ast.Store)
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == 'self'):
                    tags.add(inner.attr)

    tags |= CALLABLE_TAGS
    return {tag for tag in tags
            if tag not in NOT_TAGS and not tag.startswith('_')}


def documented_tags() -> Set[str]:
    """Every tag named in a backticked cell of the manual's tag index."""
    with open(TAG_INDEX, 'r') as f:
        text = f.read()
    # `name`, `$almanac.name`, `.name`, `next_pass.rise` -- take the last
    # dotted segment's identifier so a chain documents its own leaf too.
    names: Set[str] = set()
    for code in re.findall(r'`([^`]+)`', text):
        code = code.strip().lstrip('$')
        for part in re.split(r'[^A-Za-z0-9_]+', code):
            if part:
                names.add(part)
    return names


class TestTagIndexCoverage:
    """docs/tag-index.md must mention every tag the code serves."""

    def test_every_served_tag_is_documented(self):
        missing = sorted(served_tags() - documented_tags())
        assert not missing, (
            'These tags are served by bin/user/wxskyfield.py but are not '
            'mentioned in docs/tag-index.md:\n  %s\n'
            'Document them (or, if one is genuinely not a user-visible tag, '
            'add it to NOT_TAGS in this test with the reason).'
            % '\n  '.join(missing))

    def test_extraction_still_finds_the_known_landmarks(self):
        """Guard the extractor itself: if a refactor moves the dispatch
        tables or renames the functions, the audit must fail loudly rather
        than quietly pass on an empty tag set."""
        tags = served_tags()
        assert len(tags) > 100, 'extractor found only %d tags' % len(tags)
        for landmark in ('sunrise', 'next_full_moon', 'next_solar_eclipse',
                         'equation_of_time', 'next_supermoon', 'mag',
                         'constellation', 'next_visible_pass', 'perihelion',
                         'next_meteor_shower', 'elements_epoch', 'hlongitude'):
            assert landmark in tags, 'extractor lost %r' % landmark


# ── the manual's internal links ─────────────────────────────────────────

DOCS_DIR = os.path.join(REPO_ROOT, 'docs')


def _slug(heading: str) -> str:
    """A heading's anchor, the way kramdown (GitHub Pages) generates it.

    This reimplements kramdown's rule rather than reading the ids out of a
    built site, so the audit runs anywhere pytest does -- a user checking
    out the repo has no ruby, jekyll or network.  The trade is that the
    rule could drift from kramdown; it was verified against a real
    GitHub Pages build of this manual (every id on all 16 rendered pages
    matched, the double-hyphen case included).  If a slugging edge case
    ever does bite -- kramdown also suffixes duplicate headings -- rebuild
    the site and diff these slugs against the emitted id="..." values
    rather than guessing at the rule.
    """
    text = heading.strip().lstrip('#').strip()
    text = re.sub(r'`([^`]*)`', r'\1', text)          # drop code ticks
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)   # links -> their text
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s_-]', '', text)
    # One hyphen per space, NOT per run of spaces: kramdown turns
    # "chart — `name`" into "chart--name", because removing the em dash
    # leaves the two spaces that surrounded it.  Verified against the
    # built site's own ids.
    return text.replace('\t', ' ').replace(' ', '-').strip('-')


def _page_anchors(path: str) -> Set[str]:
    anchors: Set[str] = set()
    with open(path, 'r') as f:
        in_code = False
        for line in f:
            if line.startswith('```'):
                in_code = not in_code
            elif not in_code and line.startswith('#'):
                anchors.add(_slug(line))
    return anchors


class TestSlugRule:
    """Pin kramdown's slugging by counterexample.

    The rule below is subtle in exactly one place, and prose did not stop
    me getting it wrong: an em dash surrounded by spaces leaves BOTH
    spaces behind when the punctuation is stripped, so the id carries two
    hyphens.  Collapsing runs of whitespace -- the obvious implementation
    -- silently produces a single hyphen and every anchor to such a
    heading reads as broken."""

    def test_em_dash_heading_yields_a_double_hyphen(self):
        assert _slug('## The next visible pass chart — `pass_chart_html`') == \
            'the-next-visible-pass-chart--pass_chart_html'

    def test_ordinary_headings(self):
        assert _slug('## The result cache') == 'the-result-cache'
        assert _slug('### The `[Skyfield]` section') == 'the-skyfield-section'
        assert _slug("## The Sky page's report stanza") == 'the-sky-pages-report-stanza'


class TestManualLinks:
    """Every internal link in the manual resolves.

    The pre-2.2 manual navigated by hand-typed link bars that silently
    drifted out of sync; moving prose between pages breaks anchors the
    same quiet way.  This audit is what makes that loud."""

    def test_internal_links_resolve(self):
        pages = sorted(f for f in os.listdir(DOCS_DIR) if f.endswith('.md'))
        anchors = {p: _page_anchors(os.path.join(DOCS_DIR, p)) for p in pages}
        broken = []
        for page in pages:
            with open(os.path.join(DOCS_DIR, page), 'r') as f:
                text = f.read()
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if target.startswith(('http://', 'https://', 'mailto:')):
                    continue
                file_part, _, anchor = target.partition('#')
                target_page = file_part or page
                if target_page not in anchors:
                    broken.append('%s -> %s (no such page)' % (page, target))
                elif anchor and anchor not in anchors[target_page]:
                    broken.append('%s -> %s (no such heading)' % (page, target))
        assert not broken, 'Broken internal links:\n  ' + '\n  '.join(broken)


# ── configuration, panels and the dictionary ────────────────────────────

SKY_SOURCE = os.path.join(REPO_ROOT, 'bin', 'user', 'wxskyfield_sky.py')
SKIN_CONF = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'skin.conf')
EN_CONF = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'lang', 'en.conf')
CONFIG_PAGE = os.path.join(DOCS_DIR, 'configuration.md')
PANELS_PAGE = os.path.join(DOCS_DIR, 'panels.md')
DICTIONARY_PAGE = os.path.join(DOCS_DIR, 'i18n-dictionary.md')

# Report options the manual documents that the bundled skin.conf does NOT
# declare, because they are WeeWX's own report keys rather than this skin's
# settings -- the installer writes them into weewx.conf.  Each needs a
# reason: this set is the only thing standing between the audit and a
# manual that documents an option nothing reads.
CORE_REPORT_KEYS = {
    'enable',         # WeeWX: whether to run the report at all
    'report_timing',  # WeeWX: the report's schedule
    'HTML_ROOT',      # WeeWX: where the report is written
}

# $sky_page members that are not panels and so are not documented on the
# panels page.  Each needs a reason.
NON_PANEL_MEMBERS = {
    'get_extension_list',   # the WeeWX search-list API itself
    'decorate',             # internal: wraps a render in error trapping
}
# `theme` and `palette` were on that list until 2.3, called internal.  They
# are not: they are the pair a skin embedding the panels calls to offer both
# plates, and exempting them is why the manual went several releases without
# a word about them while a consuming extension had to be told by hand.
# Anything genuinely internal belongs above, with the reason.


def _documented_table_rows(path: str, after: str, before: str) -> Dict[str, str]:
    """Rows of the first markdown table between two headings, as
    {first cell: second cell}, both stripped of backticks."""
    with open(path, 'r') as f:
        text = f.read()
    section = text[text.index(after):]
    if before in section:
        section = section[:section.index(before)]
    rows: Dict[str, str] = {}
    for line in section.split('\n'):
        if not line.startswith('|') or line.startswith('|---'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 2 or cells[0].lower() in ('option', 'tag', 'key'):
            continue
        # The manual writes subsections in config syntax ([[Satellites]]);
        # the code's key is the bare name.
        name = cells[0].strip('`').strip('*').strip('[]')
        rows[name] = cells[1].strip('`').strip('*')
    return rows


def _recognized_skyfield_options() -> Set[str]:
    """The [Skyfield] keys the service accepts, from its own check."""
    tree = _module()
    for node in ast.walk(tree):
        # for key in skyfield_config_dict: if key not in (...)
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == 'key'
                and any(isinstance(op, ast.NotIn) for op in node.ops)):
            names = _string_elements(node.comparators[0])
            if 'enable' in names:
                return names
    raise AssertionError('could not find the [Skyfield] option check in the source')


class TestConfigurationDocumented:
    """docs/configuration.md must match what the code actually reads."""

    def test_skyfield_section_options(self):
        code = _recognized_skyfield_options()
        documented = set(_documented_table_rows(
            CONFIG_PAGE, '## The `[Skyfield]` section', '## The Sky page'))
        assert code == documented, (
            'The [Skyfield] section documented in the manual does not match the '
            'options the service accepts.\n  only in code: %s\n  only in manual: %s'
            % (sorted(code - documented), sorted(documented - code)))

    def test_report_options_and_defaults(self):
        """Every option the bundled skin.conf sets, with its default,
        appears in the manual's report-stanza table with the same value."""
        skin: Dict[str, str] = {}
        with open(SKIN_CONF, 'r') as f:
            for line in f:
                if line.startswith('['):
                    break                      # top-level options only
                m = re.match(r'([a-z_]+)\s*=\s*(\S+)', line)
                if m:
                    skin[m.group(1)] = m.group(2)
        documented = _documented_table_rows(
            CONFIG_PAGE, "## The Sky page's report stanza", '## Translation keys')
        missing = sorted(set(skin) - set(documented))
        assert not missing, 'skin.conf options missing from the manual: %s' % missing
        # The direction that catches a manual promising something that does
        # nothing -- an option no code reads.  Users report those as bugs.
        invented = sorted(set(documented) - set(skin) - CORE_REPORT_KEYS)
        assert not invented, (
            'The manual documents report options that neither skin.conf declares '
            'nor WeeWX itself provides: %s\n(if one is a core WeeWX report key, '
            'add it to CORE_REPORT_KEYS with the reason.)' % invented)

        wrong = {k: (v, documented[k]) for k, v in skin.items()
                 if documented[k].lower() not in (v.lower(), '`%s`' % v.lower())}
        assert not wrong, (
            'The manual documents a different default than skin.conf sets '
            '(option: skin.conf vs manual): %s' % wrong)


class TestPanelsDocumented:
    """Every $sky_page panel method is documented on the panels page."""

    def test_every_panel_method_is_documented(self):
        with open(SKY_SOURCE, 'r') as f:
            members = set(re.findall(r'^    def ([a-z][a-z_0-9]*)', f.read(), re.M))
        panels = members - NON_PANEL_MEMBERS
        with open(PANELS_PAGE, 'r') as f:
            page = f.read()
        missing = sorted(m for m in panels if m not in page)
        assert not missing, (
            'These $sky_page methods are not mentioned on the panels page: %s\n'
            '(if one is internal rather than a panel, add it to NON_PANEL_MEMBERS '
            'with the reason.)' % missing)


class TestDictionaryPageMatchesSkin:
    """The manual's dictionary page is the skin's en.conf, verbatim.

    It is quoted in full so translators can read it without a checkout;
    quoting it means it can go stale, and this is what stops that."""

    def test_dictionary_matches_en_conf(self):
        with open(DICTIONARY_PAGE, 'r') as f:
            blocks = re.findall(r'```ini\n(.*?)```', f.read(), re.S)
        assert len(blocks) == 1, (
            'expected exactly one ini block on the dictionary page, found %d -- '
            'a second block would make this audit compare against a merge of '
            'both, which is how an audit silently stops auditing' % len(blocks))
        with open(EN_CONF, 'r') as f:
            conf = f.read()

        def meaningful(text):
            return [line.rstrip() for line in text.split('\n')
                    if line.strip() and not line.strip().startswith('#')]

        page_lines = meaningful('\n'.join(b.rstrip('\n') for b in blocks))
        conf_lines = meaningful(conf)
        assert page_lines == conf_lines, (
            'The dictionary page has drifted from skins/Skyfield/lang/en.conf.\n'
            '  only in en.conf: %s\n  only on the page: %s'
            % ([line for line in conf_lines if line not in page_lines][:5],
               [line for line in page_lines if line not in conf_lines][:5]))


# ── the pages' own furniture ────────────────────────────────────────────

# Matches the current wording and the pre-2.2 "The full ... manual (with
# search)" form alike, so the audit does not go red mid-rewording.
MANUAL_LINK = 'weewx-skyfield manual'
GITHUB_LINK = 'weewx-skyfield on GitHub'
ISSUE_LINK = 'Report an issue'

# The Home page carries the same destinations as just-the-docs buttons
# instead of the text line -- putting both on one screen would print the
# repository URL twice, and the manual link would point at the page the
# reader is already on.  It is exempt from the line rule and checked for
# the buttons instead, below; weewx-celestial's manual does the same.
BUTTON_HOME = 'index.md'
HOME_BUTTONS = (
    'View on GitHub',
    'Download weewx-skyfield.zip',
    'Report an issue',
)


class TestPageFurniture:
    """Every content page opens the same way.

    The link line is the in-body pointer to the manual and the project --
    it is what a reader of the raw markdown (in the release zip, or on
    github.com, where no sidebar exists) navigates by, and the only
    in-body backlink to the repository on most pages.  It is identical on
    every page until, silently, it is not: this class of drift is pure
    page furniture, and none of the other audits here can see it.

    The blank line between the link line and the `---` is load-bearing.
    A `---` directly beneath a line of text is setext syntax: kramdown
    reads the whole link line as an H2 instead of emitting a horizontal
    rule, which quietly turns the navigation furniture into a heading."""

    @staticmethod
    def _content_pages():
        for name in sorted(f for f in os.listdir(DOCS_DIR) if f.endswith('.md')):
            with open(os.path.join(DOCS_DIR, name), 'r') as f:
                text = f.read()
            # Redirect and nav-excluded stubs are deliberately bare: a
            # stub wants no chrome, only its pointer.
            if 'redirect_to:' in text or 'nav_exclude: true' in text:
                continue
            if name == BUTTON_HOME:
                continue
            yield name, text.split('\n')

    def test_every_content_page_has_the_link_line_and_rule(self):
        problems = []
        checked = 0
        for name, lines in self._content_pages():
            checked += 1
            where = next((i for i, line in enumerate(lines)
                          if MANUAL_LINK in line), None)
            if where is None:
                problems.append('%s: no manual link line' % name)
                continue
            # The line may be written across several source lines (each
            # destination on its own) or as one; find the rule that closes
            # it rather than assuming a fixed offset.
            rule = next((i for i in range(where, min(where + 8, len(lines)))
                         if lines[i].strip() == '---'), None)
            if rule is None:
                problems.append('%s: no "---" rule under the link line' % name)
                continue
            block = '\n'.join(lines[where:rule])
            for needed, what in ((GITHUB_LINK, 'the GitHub link'),
                                 (ISSUE_LINK, 'the issue link')):
                if needed not in block:
                    problems.append('%s: %s is missing from the link line'
                                    % (name, what))
            if lines[rule - 1].strip():
                problems.append('%s: no blank line before the rule -- a bare "---" '
                                'under text is a setext H2, not a rule' % name)
        assert not problems, 'Page furniture drift:\n  ' + '\n  '.join(problems)
        assert checked >= 15, 'only checked %d content pages' % checked

    def test_home_carries_the_buttons(self):
        """Home is exempt from the line rule, so it must earn that exemption:
        the destinations the line would have provided have to be present as
        buttons, or the exemption silently costs the page its only in-body
        link to the repository."""
        with open(os.path.join(DOCS_DIR, BUTTON_HOME), 'r') as f:
            home = f.read()
        missing = [b for b in HOME_BUTTONS if b not in home]
        assert not missing, 'Home is missing these buttons: %s' % missing
        assert '{: .btn' in home, 'Home\'s links are not rendered as buttons'
        assert MANUAL_LINK not in home, (
            'Home carries the manual link line as well as the buttons -- that '
            'is the duplication the exemption exists to avoid, and the link '
            'points at the page the reader is already on')


class TestThemeCreditSuppressed:
    """The theme must not advertise itself on the manual's pages.

    just-the-docs renders "This site uses ... a documentation theme for
    Jekyll", with a link to its own repository, in the sidebar and in the
    small-screen page footer -- on EVERY page.  It does this whenever the
    capture of _includes/nav_footer_custom.html comes out empty, so the
    override must produce non-empty output; an empty file changes nothing.

    Two traps, both learned the hard way:
      * overriding footer_custom.html instead removes site.footer_content
        (the copyright) and leaves the credit in place -- backwards;
      * an override that quotes the credit's wording in a comment still
        matches a grep for it, which reads as the fix having failed.
    """

    OVERRIDE = os.path.join(DOCS_DIR, '_includes', 'nav_footer_custom.html')

    def test_override_exists_and_is_not_empty(self):
        assert os.path.exists(self.OVERRIDE), (
            'docs/_includes/nav_footer_custom.html is missing -- without it '
            "the theme prints its own credit, and a link to its repository, "
            'on every page of the manual')
        with open(self.OVERRIDE, 'r') as f:
            body = f.read()
        assert body.strip(), (
            'the override is empty, which is exactly the condition that makes '
            'the theme print its credit -- the output must be non-empty')

    def test_the_copyright_include_is_not_overridden(self):
        """footer_custom.html renders site.footer_content.  Overriding it is
        the wrong fix and silently drops the copyright line."""
        wrong = os.path.join(DOCS_DIR, '_includes', 'footer_custom.html')
        assert not os.path.exists(wrong), (
            'docs/_includes/footer_custom.html overrides the include that '
            'renders the copyright (site.footer_content).  The theme credit '
            'is suppressed via nav_footer_custom.html instead.')


# ── what the installer actually writes ──────────────────────────────────

INSTALL_PY = os.path.join(REPO_ROOT, 'install.py')


def _installer_config() -> Dict[str, str]:
    """The flat key=value pairs install.py injects into weewx.conf.

    Nested sections are flattened to their leaf entries: what a reader
    needs to see in the manual is that `iss = 25544` is what lands in
    their config, not the shape of the python dict that put it there."""
    with open(INSTALL_PY, 'r') as f:
        tree = ast.parse(f.read(), filename=INSTALL_PY)

    # Module-level dicts the config block references as dict(NAME).
    named: Dict[str, Dict[str, str]] = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Dict)):
            pairs = {}
            for key, value in zip(node.value.keys, node.value.values):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    pairs[key.value] = value.value
            if pairs:
                named[node.targets[0].id] = pairs

    flat: Dict[str, str] = {}

    def walk(node: ast.AST) -> None:
        if not isinstance(node, ast.Dict):
            return
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                flat[key.value] = value.value
            elif isinstance(value, ast.Dict):
                walk(value)
            elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                  and value.func.id == 'dict' and value.args
                  and isinstance(value.args[0], ast.Name)):
                flat.update(named.get(value.args[0].id, {}))

    for element in ast.walk(tree):
        if isinstance(element, ast.keyword) and element.arg == 'config':
            walk(element.value)
    return flat


class TestInstallerDefaultsDocumented:
    """The manual says "the installer adds this ... with these defaults"
    and then prints a config block.  That is a falsifiable claim about
    another file, and nothing but a test keeps it true -- a default changed
    in install.py leaves the manual quietly lying about what a fresh
    install produces."""

    def test_every_installed_default_appears_in_the_manual(self):
        config = _installer_config()
        assert len(config) >= 8, (
            'only extracted %d entries from install.py -- the extractor has '
            'probably lost the config block' % len(config))
        with open(CONFIG_PAGE, 'r') as f:
            page = f.read()
        missing = []
        for key, value in sorted(config.items()):
            # The manual prints these as "key = value" inside its ini blocks.
            if not re.search(r'^\s*%s\s*=\s*%s\s*$' % (re.escape(key),
                                                       re.escape(value)),
                             page, re.M):
                missing.append('%s = %s' % (key, value))
        assert not missing, (
            'install.py writes these into weewx.conf, but the manual does not '
            'show them (or shows a different value):\n  %s' % '\n  '.join(missing))


class TestPagesUrlsResolve:
    """Absolute links to the published manual must use a form GitHub Pages
    actually serves.

    Jekyll builds `installation.html`, not `installation/index.html`, and
    GitHub Pages does NOT map a trailing-slash path onto the .html file.
    Measured against the live site:

        /installation.html  -> 200
        /installation       -> 200
        /installation/      -> 404

    The trailing-slash form is the natural thing to write and is silently
    dead, so every deep link into the manual -- from the README especially,
    which is the project's front page -- carries the .html suffix.  Only the
    site root may end in a slash."""

    SITE = 'https://chaunceygardiner.github.io/weewx-skyfield/'

    def _sources(self):
        yield 'README.md', os.path.join(REPO_ROOT, 'README.md')
        for name in sorted(os.listdir(DOCS_DIR)):
            if name.endswith('.md'):
                yield name, os.path.join(DOCS_DIR, name)

    def test_no_trailing_slash_deep_links(self):
        bad = []
        for label, path in self._sources():
            with open(path, 'r') as f:
                text = f.read()
            for url in re.findall(re.escape(self.SITE) + r'[^\s)\]"\'>]*', text):
                tail = url[len(self.SITE):]
                if not tail:
                    continue                      # the site root is fine
                if tail.endswith('/') or (('.' not in tail.split('#')[0])
                                          and not tail.startswith('#')):
                    bad.append('%s: %s' % (label, url))
        assert not bad, (
            'These links use a path GitHub Pages does not serve (a trailing '
            'slash 404s; jekyll builds <page>.html):\n  %s' % '\n  '.join(bad))

    def test_the_redirect_stub_targets_a_real_page(self):
        """redirect_to is prefixed with baseurl by the plugin, so it must be
        a site-absolute path -- and it needs the .html for the same reason."""
        with open(os.path.join(DOCS_DIR, 'known-skyfield-issues.md'), 'r') as f:
            text = f.read()
        target = re.search(r'^redirect_to:\s*(\S+)', text, re.M)
        assert target, 'the moved page lost its redirect_to'
        assert target.group(1).endswith('.html'), (
            'redirect_to %r has no .html suffix, so the redirect lands on a '
            '404' % target.group(1))
        page = target.group(1).lstrip('/').split('#')[0]
        assert os.path.exists(os.path.join(DOCS_DIR, page.replace('.html', '.md'))), (
            'redirect_to points at %s, which no manual page builds' % page)


class TestReadmeButtons:
    """The README's button row must not rot.

    GitHub markdown carries no styling, so the row that mirrors the
    manual's buttons is three committed SVGs referenced by relative path.
    A renamed or deleted asset shows as a broken image on the project's
    front page, and nothing else here would notice."""

    EXPECTED = {'assets/btn-manual.svg': 'Read the manual',
                'assets/btn-download.svg': 'Download weewx-skyfield.zip',
                'assets/btn-issue.svg': 'Report an issue'}

    def test_every_referenced_button_exists_and_is_labelled(self):
        with open(os.path.join(REPO_ROOT, 'README.md'), 'r') as f:
            readme = f.read()
        referenced = dict(re.findall(r'!\[([^\]]*)\]\((assets/[^)]+)\)', readme))
        referenced = {path: alt for alt, path in referenced.items()}
        assert referenced == self.EXPECTED, (
            'the README button row changed:\n  found: %s\n  expected: %s'
            % (sorted(referenced.items()), sorted(self.EXPECTED.items())))
        for path, label in sorted(self.EXPECTED.items()):
            full = os.path.join(REPO_ROOT, path)
            assert os.path.exists(full), '%s is referenced but missing' % path
            with open(full, 'r') as f:
                svg = f.read()
            assert 'aria-label="%s"' % label in svg, (
                '%s has no aria-label matching its README alt text -- screen '
                'readers and a broken-image fallback both rely on it' % path)
            assert 'textLength=' in svg, (
                '%s has no textLength: the SVG renders inside an <img>, so the '
                'font resolves against the viewer\'s system and an unpinned '
                'label overflows the pill' % path)

    def test_buttons_are_not_shipped_in_the_extension(self):
        """They are front-page furniture, like the screenshots -- not skin
        assets.  Shipping them would put them in every user's bin/user."""
        with open(os.path.join(REPO_ROOT, 'install.py'), 'r') as f:
            assert 'assets/' not in f.read(), (
                'install.py references assets/ -- the README buttons are '
                'repo-only furniture and should not be installed')


# ── numbers the manual quotes from the code ─────────────────────────────

# Thresholds that live as constants in the source and as PROSE in the
# manual, often on several pages each.  Change the constant and the manual
# lies -- silently, in four places at once, which is the worst kind.  Each
# entry is (constant, expected value, the phrase the manual uses).
QUOTED_CONSTANTS = [
    ('SAT_REFRESH_SECS',                  3 * 3600,   'three hours'),
    ('COMET_REFRESH_SECS',                2 * 86400,  'two days'),
    ('SAT_MAX_ELEMENT_AGE_SECS',          7 * 86400,  'seven days'),
    ('SAT_VISIBLE_MIN_CULMINATION_DEGREES', 10.0,     '10°'),
    ('_HORIZON_QUANTUM_DEGREES',          0.002,      '0.002 degrees'),
]


def _literal(node: ast.AST) -> Any:
    """Evaluate a constant expression.  The source spells these as
    arithmetic (3 * 3600, 7 * 86400) precisely so they read as what they
    mean, so literal_eval alone is not enough -- and eval is not worth the
    risk for two operators."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_literal(node.operand)
    if isinstance(node, ast.BinOp):
        left, right = _literal(node.left), _literal(node.right)
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Add):
            return left + right
    raise AssertionError('unsupported constant expression: %s' % ast.dump(node))


def _constant(name: str) -> Any:
    """A module-level constant's value, evaluated from the source."""
    tree = _module()
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            return _literal(node.value)
    raise AssertionError('constant %s not found in the source' % name)


class TestQuotedConstants:
    """The manual's numbers must match the code's constants.

    These are not tags or options -- they are thresholds the prose states
    in words ("about every three hours", "more than seven days older").
    Nothing else in this file can see them, and a reader has no way to
    tell that a sentence has gone stale."""

    def test_constants_still_have_the_documented_values(self):
        wrong = []
        for name, expected, phrase in QUOTED_CONSTANTS:
            actual = _constant(name)
            if actual != expected:
                pages = sorted(p for p in os.listdir(DOCS_DIR)
                               if p.endswith('.md')
                               and phrase in open(os.path.join(DOCS_DIR, p)).read())
                wrong.append('%s is now %r, but the manual still says %r in: %s'
                             % (name, actual, phrase, ', '.join(pages) or 'no page'))
        assert not wrong, (
            'The code changed and the manual did not:\n  ' + '\n  '.join(wrong))

    def test_the_manual_actually_states_them(self):
        """Guard the guard: if the prose is reworded, the check above would
        pass while silently protecting nothing."""
        unstated = []
        corpus = ''
        for name in sorted(os.listdir(DOCS_DIR)):
            if name.endswith('.md'):
                with open(os.path.join(DOCS_DIR, name), 'r') as f:
                    corpus += f.read()
        for name, _expected, phrase in QUOTED_CONSTANTS:
            if phrase not in corpus:
                unstated.append('%s: no page says %r any more' % (name, phrase))
        assert not unstated, (
            'The manual no longer states these, so the value check above is '
            'guarding nothing -- update QUOTED_CONSTANTS to the new wording:'
            '\n  ' + '\n  '.join(unstated))


# The download's size, as the README and the Installation page state it.
# Only the two BUNDLED files get a number: they are byte-frozen, so these
# can only go wrong if someone swaps the file -- which is exactly when a
# reader would be misled.  The zip total and the screenshots' share are
# deliberately unnumbered in the prose; both move every release with
# visual changes, and the total was wrong three times in a month (32 ->
# 43 -> 46 MB) before anyone noticed.  Sizes are decimal MB, the unit the
# releases page and a browser's download list report.
SIZED_FILES = [
    (os.path.join('bin', 'user', 'wxskyfield_de421.bsp'),
     17, 'DE421 ephemeris (17 MB)'),
    (os.path.join('bin', 'user', 'wxskyfield_stars.dat.gz'),
     15, 'Hipparcos star catalog (15 MB gzipped)'),
]

SIZED_FILE_PAGES = [os.path.join(REPO_ROOT, 'README.md'),
                    os.path.join(DOCS_DIR, 'installation.md')]


def _flowed(path: str) -> str:
    """A page's text with runs of whitespace collapsed, so a phrase still
    matches where the source wrapped it across two lines."""
    with open(path, 'r') as f:
        return ' '.join(f.read().split())


class TestBundledFileSizes:
    """The documented sizes of the bundled data files must be the real
    ones.  Nothing else in the suite reads these numbers, and a reader has
    no way to tell that a sentence has gone stale."""

    def test_documented_sizes_match_the_files(self):
        wrong = []
        for relpath, documented, phrase in SIZED_FILES:
            actual = os.path.getsize(os.path.join(REPO_ROOT, relpath))
            rounded = round(actual / 1000000)
            if rounded != documented:
                wrong.append(
                    '%s is %d bytes (%d MB), but the docs say %r'
                    % (relpath, actual, rounded, phrase))
        assert not wrong, (
            'A bundled file changed size and the docs did not:\n  '
            + '\n  '.join(wrong))

    def test_both_pages_actually_state_them(self):
        """Guard the guard: if the prose is reworded, the check above would
        pass while silently protecting nothing."""
        missing = []
        for path in SIZED_FILE_PAGES:
            text = _flowed(path)
            for _relpath, _documented, phrase in SIZED_FILES:
                if phrase not in text:
                    missing.append('%s no longer says %r'
                                   % (os.path.basename(path), phrase))
        assert not missing, (
            'The size check above is guarding nothing -- update SIZED_FILES '
            'to the new wording:\n  ' + '\n  '.join(missing))

    def test_no_page_states_a_total_download_size(self):
        """The zip total moves every release that changes a screenshot, so
        the prose must not carry one.  It was wrong three times in a month
        before this test existed."""
        stale = []
        for path in SIZED_FILE_PAGES:
            for sentence in _flowed(path).split('.'):
                if 'weewx-skyfield.zip' not in sentence and 'download' not in sentence:
                    continue
                for match in re.findall(r'(?:about|roughly|~)\s*\d+\s*MB', sentence):
                    stale.append('%s: %r' % (os.path.basename(path), match))
        assert not stale, (
            'A total download size is back in the prose -- it goes stale '
            'every release; name the bundled files instead:\n  '
            + '\n  '.join(stale))


I18N_PAGE = os.path.join(DOCS_DIR, 'i18n.md')
LANG_DIR = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'lang')

# The lead sentence spells the count in words, so the audit has to know
# them.  Eight is today's; the neighbors cover a language arriving or
# leaving without anyone having to remember this list exists.
COUNT_WORDS = {
    4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight',
    9: 'Nine', 10: 'Ten', 11: 'Eleven', 12: 'Twelve',
}


def _language_table_rows():
    """The Translating section's per-language rows, as
    [(language, lang file, status), ...]."""
    with open(I18N_PAGE, 'r') as f:
        text = f.read()
    section = text[text.index('## Translating'):]
    rows = []
    for line in section.split('\n'):
        if not line.startswith('|') or line.startswith('|---'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 3 or cells[0].lower() == 'language':
            continue
        rows.append((cells[0], cells[1].strip('`'), cells[2]))
    return rows


class TestLanguageTable:
    """The Translations page's language table must match the shipped skin.

    A translation arriving or leaving touches three things -- the lang
    directory, this table, and the count word in the sentence above it --
    and the two in prose are the ones nobody remembers.  This is also what
    makes an incoming native-speaker review a one-line edit that fails
    loudly in whichever repo forgets it."""

    def test_tabled_languages_are_the_shipped_ones(self):
        shipped = {n for n in os.listdir(LANG_DIR) if n.endswith('.conf')}
        shipped.discard('en.conf')      # the reference dictionary, not a
                                        # translation: deliberately untabled
        tabled = {os.path.basename(f) for _lang, f, _status in
                  _language_table_rows()}
        assert tabled == shipped, (
            'docs/i18n.md\'s language table and skins/Skyfield/lang/ '
            'disagree.\n  tabled but not shipped: %s\n  shipped but not '
            'tabled: %s' % (sorted(tabled - shipped) or 'none',
                            sorted(shipped - tabled) or 'none'))

    def test_english_is_not_tabled_as_a_translation(self):
        """en.conf is the reference dictionary.  Tabling it would make the
        count wrong and imply English needs a native-speaker review."""
        tabled = {os.path.basename(f) for _lang, f, _status in
                  _language_table_rows()}
        assert 'en.conf' not in tabled, (
            'en.conf is listed in the language table, but it is the '
            'reference dictionary rather than a translation')

    def test_every_row_states_reviewed_or_beta(self):
        # 'Partly reviewed' is weewx-celestial's status for a file whose
        # shared vocabulary was reviewed in THIS repo but whose own strings
        # were not; accepted here so the three manuals can share one audit.
        vague = [lang for lang, _f, status in _language_table_rows()
                 if not status.startswith(('Reviewed', 'Partly reviewed',
                                           'Beta'))]
        assert not vague, (
            'these rows state neither Reviewed nor Beta, so a reader cannot '
            'tell whether a native speaker has read the file: %s'
            % ', '.join(vague))

    def test_the_count_word_matches_the_table(self):
        rows = _language_table_rows()
        expected = COUNT_WORDS.get(len(rows))
        assert expected, (
            '%d languages ship -- add the count word to COUNT_WORDS'
            % len(rows))
        with open(I18N_PAGE, 'r') as f:
            text = f.read()
        claim = '**%s complete translations ship with the skin**' % expected
        assert claim in text, (
            'the table has %d languages, so the Translating section should '
            'lead with %r' % (len(rows), claim))
