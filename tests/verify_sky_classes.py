#!/usr/bin/env python
"""Prove the $sky_page class contract in a real browser.

The panels' role classes and their zero-specificity defaults are a CSS
mechanism, and every way they can go wrong is a CSS resolution question:
which rule wins, and what a <style> inside inline SVG is scoped to.  No
assertion on the markup can see any of that -- the source can be perfectly
correct and the page still draw navy stars on a light theme -- so this
loads the real fragments into Chromium and reads computed styles back.

Nine claims, each of which was a live risk when it was added:

  1. A consumer that does nothing gets the palette it asked for.
  2. The WEAKEST possible consumer rule -- :where(.sky-fill-ink), which
     scores zero -- still beats our default.  `svg :where(...)` would have
     scored (0,0,1) and quietly won instead.
  3. Two panels of different palettes on one page keep their own colors.
     A <style> in inline SVG is NOT scoped to that SVG in an HTML
     document: without the per-plate root class, the second block would
     repaint the first panel.
  4. A theme rule repaints a night-rendered panel -- the switch this whole
     mechanism exists for.
  5. The band casing is an ELEMENT on both plates, painting each plate's
     own value, so a reader flipping themes can be given the other's.
  6. The chip and table swatches, which are HTML and carry their color
     inline, can still be repainted by an ordinary consumer rule -- they
     set --sky-dot rather than `background`, and sky.css reads it.
  7. Exchanging a mark's two role suffixes -- the documented way for a live
     consumer to invert a mark without naming a color -- exchanges the two
     paints, rather than dropping one to the SVG initial because the partner
     class had no default.
  8. A chart with label layers DISPLAYS exactly one of them, chosen by the
     viewport width, on both charts; and a consumer's one-class display
     reset does not show both, because the layer rules are the one thing
     in the style block that is not zero-specificity.  8b: two charts on
     one page with the same plate and scales but different queries each
     follow their own query, not the other's.
  9. Every line BETWEEN rows or sections -- the rosters' rows, the table's
     rows, the header's rule and the footer's -- scores on the night plate
     (APCA) what it scores on paper, each against the ground it actually
     sits on, and the paper lines are still the paper design.  Through
     2.7.1 the night ones were the box-outline color, Lc 0 on both grounds.

Run it with the WeeWX venv python (it renders the panels); it re-invokes
itself under tools/pwenv for the browser half, and does nothing where no
browser environment is installed:

    /home/weewx/weewx-venv/bin/python tests/verify_sky_classes.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PWENV = os.path.join(REPO_ROOT, 'tools', 'pwenv', 'bin', 'python')

LATITUDE, LONGITUDE, ALTITUDE_M = 37.4419, -122.143, 9.0
TIME_TS = 1750532400                  # 2025-06-21 12:00:00 PDT, as the suite uses


# ── half one: render the fragments (needs WeeWX, Skyfield, the ephemeris) ────
def render(out_dir):
    sys.path.insert(0, os.path.join(REPO_ROOT, 'bin', 'user'))
    os.environ['TZ'] = 'America/Los_Angeles'
    time.tzset()
    import weewx.almanac
    import weewx.units
    import wxskyfield
    import wxskyfield_sky

    # Satellites and comets from the suite's own fixtures: their markers
    # are the marks with two states (sunlit/shadowed, naked-eye/faint), and
    # so the only ones the flip technique in claim 7 applies to.
    data_dir = os.path.join(REPO_ROOT, 'tests', 'data')
    sky = wxskyfield.Sky(os.path.join(REPO_ROOT, 'bin', 'user'), load_stars=True,
                         satellites={'iss': 25544, 'tiangong': 48274},
                         sat_dir=data_dir,
                         comets={'halley': '1P', 'bright': 'C/9999 Z9'},
                         comet_dir=data_dir)
    assert sky.is_valid(), 'the Skyfield engine did not load'
    assert wxskyfield.register_almanac(sky)
    alm = weewx.almanac.Almanac(TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
                                formatter=weewx.units.get_default_formatter())
    page = wxskyfield_sky.SkyPage()
    frags = {'dome_night': page.dome_svg(alm),
             'dome_light': page.dome_svg(alm, palette='light'),
             'ribbons_night': page.ribbons_svg(alm),
             'ribbons_light': page.ribbons_svg(alm, palette='light'),
             'chips_night': page.chips_html(alm),
             # Claim 9: the page's dividers in their real containers.
             'satellites_night': page.satellites_html(alm),
             'table_night': page.table_html(alm),
             'footer': page.footer_html(),
             # The pass chart is the SINGLE-STATE case, and so the one the
             # partner defaults exist for: its satellite is sunlit at
             # culmination (that is what makes the pass visible), so
             # nothing on that chart ever fills with halo.  A dome that
             # happens to draw both a solid and a hollow marker defines
             # both channels by accident and proves nothing.
             'pass_night': page.pass_chart_html(alm),
             'pass_light': page.pass_chart_html(alm, palette='light'),
             # Claim 8: two layers, the phone's under a width query.
             'dome_layered': page.dome_svg(
                 alm, label_scale=0.8, label_layers=[(2.2, '(max-width: 600px)')]),
             'pass_layered': page.pass_chart_html(
                 alm, label_scale=0.8, label_layers=[(2.2, '(max-width: 600px)')]),
             # Claim 8b: same plate, same scales, a different query.
             'pass_portrait': page.pass_chart_html(
                 alm, label_scale=0.8, label_layers=[(2.2, '(orientation: portrait)')])}
    pal = wxskyfield_sky.PALETTES
    want = {'night_ink': pal['night']['ink'], 'light_ink': pal['light']['ink'],
            'light_bandcase': pal['light']['bandcase'],
            'night_bandcase': pal['night']['bandcase'],
            'night_mars': pal['night']['body']['mars'],
            'light_mars': pal['light']['body']['mars']}
    css_path = os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'sky.css')
    with open(css_path) as f:
        skin_css = f.read()
    with open(os.path.join(out_dir, 'fragments.json'), 'w') as f:
        json.dump({'frags': frags, 'want': want, 'skin_css': skin_css}, f)


# ── half two: read computed styles back out of a browser ────────────────────
def _hex_to_rgb(h):
    h = h.lstrip('#')
    return 'rgb(%d, %d, %d)' % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def check(work_dir):
    from playwright.sync_api import sync_playwright
    with open(os.path.join(work_dir, 'fragments.json')) as f:
        data = json.load(f)
    frags, want = data['frags'], data['want']
    night_ink = _hex_to_rgb(want['night_ink'])
    light_ink = _hex_to_rgb(want['light_ink'])
    failures = []

    def expect(label, got, wanted):
        if got != wanted:
            failures.append('%s: got %s, wanted %s' % (label, got, wanted))

    def page_html(body, extra_css=''):
        return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<style>%s</style></head><body>%s</body></html>'
                % (extra_css, body))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        def fill_of(selector):
            return page.eval_on_selector(
                selector, 'el => getComputedStyle(el).fill')

        def stroke_of(selector):
            return page.eval_on_selector(
                selector, 'el => getComputedStyle(el).stroke')

        # 1. A consumer that does nothing gets the palette it asked for.
        page.set_content(page_html(frags['dome_night']))
        expect('1. untouched night star', fill_of('.sky-fill-ink'), night_ink)
        page.set_content(page_html(frags['dome_light']))
        expect('1. untouched light star', fill_of('.sky-fill-ink'), light_ink)

        # 2. Our default must not outrank the consumer.  Both halves of it
        #    are wrapped in :where(), so it scores zero -- any rule naming
        #    one class (0,1,0) beats it wherever that rule sits, which is
        #    what every real consumer writes.  `svg :where(.sky-fill-ink)`
        #    would have scored (0,0,1) and silently won those.
        #
        #    The honest edge, pinned here rather than papered over: a
        #    consumer rule that ALSO scores zero ties with ours, and a tie
        #    is broken by document order.  Our <style> rides inside the
        #    SVG, in the body, so a zero-specificity rule in <head> loses
        #    and the same rule after the fragment wins.
        page.set_content(page_html(frags['dome_night'],
                                   extra_css='.sky-fill-ink{fill:#123456}'))
        expect('2. one-class consumer rule in <head>',
               fill_of('.sky-fill-ink'), 'rgb(18, 52, 86)')
        page.set_content(frags['dome_night']
                         + '<style>:where(.sky-fill-ink){fill:#654321}</style>')
        expect('2. zero-specificity rule after the fragment',
               fill_of('.sky-fill-ink'), 'rgb(101, 67, 33)')
        page.set_content(page_html(
            frags['dome_night'],
            extra_css=':where(.sky-fill-ink){fill:#654321}'))
        expect('2. zero-specificity rule in <head> ties and loses',
               fill_of('.sky-fill-ink'), night_ink)

        # 3. Two plates on one page do not repaint each other.  This is the
        #    one that fails without the per-plate root class, because a
        #    <style> inside inline SVG applies to the whole document.
        page.set_content(page_html(frags['dome_night'] + frags['dome_light']))
        expect('3. night dome beside a light one',
               fill_of('svg.sky-night .sky-fill-ink'), night_ink)
        expect('3. light dome beside a night one',
               fill_of('svg.sky-light .sky-fill-ink'), light_ink)

        # 4. The switch itself: a theme rule repaints a NIGHT-rendered
        #    panel, which is what a per-viewer light/dark control does long
        #    after the page was written.
        page.set_content(page_html(
            '<div class="theme-light">%s</div>' % frags['dome_night'],
            extra_css='.theme-light .sky-fill-ink{fill:%s}' % want['light_ink']))
        expect('4. night panel flipped to light', fill_of('.sky-fill-ink'),
               light_ink)

        # 5. The casing is present on both plates and paints each plate's
        #    own value, and a consumer can hand the night one the light
        #    plate's value.
        page.set_content(page_html(frags['ribbons_night']))
        expect('5. night casing paints the night band',
               fill_of('.sky-fill-bandcase'), _hex_to_rgb(want['night_bandcase']))
        page.set_content(page_html(frags['ribbons_light']))
        expect('5. light casing paints', fill_of('.sky-fill-bandcase'),
               _hex_to_rgb(want['light_bandcase']))
        page.set_content(page_html(
            frags['ribbons_night'],
            extra_css='.sky-fill-bandcase{fill:%s}' % want['light_bandcase']))
        expect('5. night casing repainted by a consumer',
               fill_of('.sky-fill-bandcase'),
               _hex_to_rgb(want['light_bandcase']))
        # ... and the same for the stroked casing on the gridlines.
        page.set_content(page_html(frags['ribbons_night']))
        expect('5. night rule casing paints the night band',
               stroke_of('.sky-stroke-bandcase'), _hex_to_rgb(want['night_bandcase']))

        # 6. The chip and table swatches are HTML and cannot carry a
        #    <style> of their own, so their color rides inline -- but as
        #    the custom property --sky-dot, never as `background` itself.
        #    That is the whole difference between themeable and not: an
        #    inline `background` outranks every rule a skin could write.
        #    Checked with the shipped stylesheet, which is what reads the
        #    variable.
        skin = data['skin_css']

        def bg_of(selector):
            return page.eval_on_selector(
                selector, 'el => getComputedStyle(el).backgroundColor')

        page.set_content(page_html(frags['chips_night'], extra_css=skin))
        expect('6. untouched swatch takes the plate color',
               bg_of('[data-body="mars"] .dot'), _hex_to_rgb(want['night_mars']))
        page.set_content(page_html(
            frags['chips_night'],
            extra_css=skin + '\n[data-body="mars"] .dot{background:%s}'
                             % want['light_mars']))
        expect('6. a consumer rule repaints the swatch',
               bg_of('[data-body="mars"] .dot'), _hex_to_rgb(want['light_mars']))

        # 7. The documented flip technique actually paints.  A mark whose
        #    two states are one another's inverse is flipped by exchanging
        #    its two role suffixes; that works only if the partner class has
        #    a default, which is why the style block emits both channels of
        #    every role it uses.  Without that the swapped mark falls back to
        #    the SVG initial -- black for a fill -- so a hollow white ring on
        #    the light plate becomes a solid black disc, silently.
        for plate, frag in (('night', frags['pass_night']),
                            ('light', frags['pass_light'])):
            page.set_content(page_html(frag))
            swapped =                 page.evaluate('''
                () => {
                  // A mark that HAS two states: a satellite marker
                  // (data-sunlit) or a comet's (data-bright).  Those are
                  // the marks the flip technique is for -- a planet dot's
                  // fill and stroke are different roles (body and ring),
                  // not an inverse pair, and exchanging them means nothing.
                  const el = document.querySelector(
                      'svg.sky [data-sunlit] circle, svg.sky [data-bright] path');
                  if (el === null) { return null; }
                  const before = {fill: getComputedStyle(el).fill,
                                  stroke: getComputedStyle(el).stroke,
                                  cls: el.getAttribute('class')};
                  el.setAttribute('class', before.cls.split(/\\s+/).map(
                      t => t.startsWith('sky-fill-')
                             ? 'sky-stroke-' + t.slice('sky-fill-'.length)
                             : t.startsWith('sky-stroke-')
                             ? 'sky-fill-' + t.slice('sky-stroke-'.length)
                             : t).join(' '));
                  return {before: before,
                          after: {fill: getComputedStyle(el).fill,
                                  stroke: getComputedStyle(el).stroke}};
                }''')
            if swapped is None:
                failures.append('7. %s: no two-channel mark to swap' % plate)
                continue
            expect('7. %s swapped fill takes the original stroke' % plate,
                   swapped['after']['fill'], swapped['before']['stroke'])
            expect('7. %s swapped stroke takes the original fill' % plate,
                   swapped['after']['stroke'], swapped['before']['fill'])
            # black and 'none' are the two ways a missing default shows up.
            for side in ('fill', 'stroke'):
                if swapped['after'][side] in ('rgb(0, 0, 0)', 'none'):
                    failures.append(
                        '7. %s swapped %s fell back to the SVG initial (%s)'
                        ' -- the partner class has no default'
                        % (plate, side, swapped['after'][side]))

        # 8. Label layers: the browser picks exactly one by its viewport.
        #    Which layer shows is a media-query and specificity question
        #    the markup cannot answer; the base and phone groups are both
        #    in the document, and only computed `display` says which one
        #    a reader sees.  Then the specificity claim: a consumer's
        #    `.dome-labels{display:block}` -- a one-class reset, which
        #    beats every :where() default in the block -- must NOT show
        #    both layers, because the layer rules are written at plain
        #    specificity for exactly this reason.
        def displays():
            return page.evaluate("""
                () => Object.fromEntries(
                  [...document.querySelectorAll('g.dome-labels')].map(
                    g => [g.getAttribute('data-label-scale'),
                          getComputedStyle(g).display]))""")

        for name in ('dome_layered', 'pass_layered'):
            for width, shown, hidden in ((1200, '0.8', '2.2'), (500, '2.2', '0.8')):
                page.set_viewport_size({'width': width, 'height': 900})
                page.set_content(page_html(frags[name]))
                got = displays()
                expect('8. %s at %dpx shows layer %s' % (name, width, shown),
                       got.get(shown), 'inline')
                expect('8. %s at %dpx hides layer %s' % (name, width, hidden),
                       got.get(hidden), 'none')
                page.set_content(page_html(frags[name],
                                           extra_css='.dome-labels{display:block}'))
                expect('8. %s at %dpx, consumer reset, still hides layer %s'
                       % (name, width, hidden), displays().get(hidden), 'none')
        # 8b. Each chart obeys its own query.  Every <style> on a page
        #     reaches every element, so a key that named the plate and the
        #     scales but not the queries let the dome's width rule switch
        #     the pass chart and the pass chart's portrait rule switch the
        #     dome.  A wide portrait viewport trips only the pass chart's
        #     query; a narrow landscape one only the dome's.
        def per_chart():
            return page.evaluate("""
                () => [...document.querySelectorAll('svg.sky')].map(svg =>
                  Object.fromEntries(
                    [...svg.querySelectorAll('g.dome-labels')].map(
                      g => [g.getAttribute('data-label-scale'),
                            getComputedStyle(g).display])))""")

        for width, height, dome_shows, pass_shows in ((800, 1200, '0.8', '2.2'),
                                                      (500, 300, '2.2', '0.8')):
            page.set_viewport_size({'width': width, 'height': height})
            page.set_content(page_html(frags['dome_layered'] + frags['pass_portrait']))
            charts = per_chart()
            if len(charts) != 2:
                failures.append('8b. expected two charts, found %d' % len(charts))
                continue
            for label, got, shows in (('dome (width query)', charts[0], dome_shows),
                                      ('pass chart (portrait query)', charts[1], pass_shows)):
                hides = '2.2' if shows == '0.8' else '0.8'
                expect('8b. %dx%d %s shows layer %s' % (width, height, label, shows),
                       got.get(shows), 'inline')
                expect('8b. %dx%d %s hides layer %s' % (width, height, label, hides),
                       got.get(hides), 'none')
        page.set_viewport_size({'width': 1280, 'height': 720})

        # 9. Dividers.  A line between rows is not held to a bar; it is
        #    held to its paper twin, scored against the ground under it,
        #    which only the cascade knows -- so the ground is the nearest
        #    ancestor that paints a background, read back from the browser
        #    like the line itself.  The shell is the template's own
        #    nesting: the header and footer on the page, the rosters and
        #    the table in a section card.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import contrast
        shell = ('<head><meta charset="utf-8">'
                 '<style>' + skin + '</style></head><body><div class="page">'
                 '<header><h1>Sky</h1></header><div class="main"><div class="primary">'
                 '<section class="sec-chips"><div class="chips">' + frags['chips_night']
                 + '</div></section><section class="sec-satellites"><div class="chips">'
                 + frags['satellites_night'] + '</div></section>'
                 '<section class="sec-table"><div class="tablewrap">' + frags['table_night']
                 + '</div></section></div></div><footer>' + frags['footer']
                 + '</footer></div></body></html>')
        lines = (('planet roster row', '.sec-chips .chip', 'Bottom'),
                 ('satellite roster row', '.sec-satellites .chip', 'Bottom'),
                 ('table row', 'tbody td', 'Bottom'),
                 ('header rule', 'header', 'Bottom'),
                 ('footer rule', 'footer', 'Top'))
        scored = {}
        for theme in ('', 'theme-light'):
            page.set_content('<!DOCTYPE html><html class="%s">' % theme + shell)
            for label, selector, side in lines:
                got = page.eval_on_selector(selector, '''(el, side) => {
                    const cs = getComputedStyle(el);
                    let g = el.parentElement;
                    while (g && getComputedStyle(g).backgroundColor
                                  === 'rgba(0, 0, 0, 0)') { g = g.parentElement; }
                    return {line: cs['border' + side + 'Color'],
                            style: cs['border' + side + 'Style'],
                            width: cs['border' + side + 'Width'],
                            ground: g ? getComputedStyle(g).backgroundColor : null};
                }''', side)
                plate = 'light' if theme else 'night'
                if got['style'] != 'solid' or got['width'] != '1px' or got['ground'] is None:
                    failures.append('9. %s %s: not a drawn line on a painted ground: %s'
                                    % (plate, label, got))
                    continue
                under = contrast.flatten(got['ground'])
                over = contrast.flatten(got['line'], under + (1.0,))
                scored[(label, plate)] = (got['line'], abs(contrast.apca(over, under)))
        for label, _selector, _side in lines:
            if (label, 'night') not in scored or (label, 'light') not in scored:
                continue
            (night_line, night_lc), (light_line, light_lc) = (
                scored[(label, 'night')], scored[(label, 'light')])
            expect('9. %s on paper is the paper design' % label,
                   light_line, _hex_to_rgb('#C9CFD8'))
            if abs(night_lc - light_lc) > .5:
                failures.append('9. %s: night %s Lc %.1f, paper %s Lc %.1f'
                                % (label, night_line, night_lc, light_line, light_lc))

        browser.close()

    for line in failures:
        print('FAIL  %s' % line)
    print('%d checks failed' % len(failures))
    return 1 if failures else 0


def main():
    if '--browser-half' in sys.argv:
        return check(sys.argv[sys.argv.index('--browser-half') + 1])
    if not os.path.exists(PWENV):
        print('SKIP: no browser environment at %s' % PWENV)
        return 0
    with tempfile.TemporaryDirectory(prefix='skyclasses-') as work:
        render(work)
        return subprocess.call([PWENV, os.path.abspath(__file__),
                                '--browser-half', work])


if __name__ == '__main__':
    sys.exit(main())
