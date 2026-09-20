#!/usr/bin/env python
"""Prove the narrow frame in a real browser.

The narrow frame exists for one reason: a label on a phone has to be big
enough to read.  "Big enough" is a measurement on the GLASS, and nothing in
the markup can make it -- a label's size in user units says nothing until
the browser has resolved the stylesheet, applied the viewBox transform and
laid the glyphs out.  A drawing can be perfectly correct in source and
still print 3.3px type, which is exactly the defect this frame was built to
fix.  So this loads the real page into Chromium at real phone widths and
measures what a reader would actually see.

Seven claims, each a live risk while the frame was being written:

  1. Every label in every narrow drawing clears 11px on the glass at both
     320 and 390 CSS px, with the bundled stylesheet's own padding.  11 is
     the floor the site's phone pages hold to; 12 is the target.
  2. No label's ink leaves its drawing.  The narrow frame's gutters, heads
     and feet were cut for phone type from estimated glyph widths, and an
     estimate that is too tight does not warn -- it silently clips a digit
     off the left of a time, or an ascender off the top of a cardinal.
     (It did, at first: three dome cardinals and two hour labels.)
  3. The narrow drawings' own type rules BEAT the stylesheet.  Every
     consuming stylesheet already carries `.gridlab{font-size:10px}` and
     friends for the wide drawings, so a rule of zero specificity -- which
     is what the palette defaults next door are -- would lose, and the
     narrow chart would draw 10px type in gutters cut for 15.
  4. The premise: at those same widths the WIDE drawings do not clear 11px.
     If they did there would be no frame to justify, and a measurement that
     cannot see the defect cannot prove the fix either.
  5. The page shows exactly one frame at a time -- the narrow one at phone
     width, the wide one above the breakpoint -- so no reader gets both and
     nobody gets neither.
  6. EVERY SHIPPED TRANSLATION fits.  The narrow frame's gutters and
     clamps are cut for the strings they hold, and the strings are
     translated: "+10 m" is "+10 min" in German and Dutch, "new" is
     "Neumond" and "nieuwe maan", and a gutter measured against English
     clips all three.  Four of those were real, and none of them was
     visible in English.  So every bundled language is drawn and measured
     -- at the narrower width, which is the harder one for size, and
     overflow is in the drawing's own units and so width-independent.
  7. No id appears twice on that page.  An id is global to the HTML
     document and the first element wins every url(#id) on it, so the two
     frames' gradients and clip paths have to be named apart -- they had
     the same names at first, and the narrow dome's constellation figures
     were trimmed at the WIDE dome's rim.  The browser is the only place
     this resolves, and the page carrying both frames is the ordinary
     case, not a corner.

Run it with the WeeWX venv python (it renders the panels); it re-invokes
itself under tools/pwenv for the browser half, and does nothing where no
browser environment is installed:

    /home/weewx/weewx-venv/bin/python tests/verify_narrow_frame.py
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

# The floor a label must clear on the glass, and the phone widths it must
# clear it at.  320 is the narrowest screen still worth serving (an SE in
# portrait); 390 is the common modern one.
FLOOR_PX = 11.0
WIDTHS = (320, 390)
# Where the stylesheet switches frames.
BREAKPOINT = 600

PANELS = ('dome_svg', 'pass_chart_html', 'ribbons_svg', 'sunpath_svg',
          'daylength_svg', 'lunation_svg', 'orrery_svg', 'analemma_svg',
          'eot_svg')
SKIN = os.path.join(REPO_ROOT, 'skins', 'Skyfield')


def _skin_dict(lang):
    """What the report engine hands a localized report: the WeeWX
    defaults, the skin's own skin.conf, then lang/<lang>.conf over both.
    No locale is set -- the C library only supplies month and weekday
    NAMES, which are three letters in every bundled language, while every
    string a gutter is cut for comes from [Texts] and [Almanac], which
    this does load."""
    import configobj
    import weewx.defaults
    from weeutil.config import deep_copy, merge_config
    sd = deep_copy(weewx.defaults.defaults)
    for path in (os.path.join(SKIN, 'skin.conf'),
                 os.path.join(SKIN, 'lang', lang + '.conf')):
        merge_config(sd, configobj.ConfigObj(path, encoding='utf-8',
                                             file_error=True))
    return sd


# ── half one: render both frames (needs WeeWX, Skyfield, the ephemeris) ─────
def render(out_dir):
    sys.path.insert(0, os.path.join(REPO_ROOT, 'bin', 'user'))
    os.environ['TZ'] = 'America/Los_Angeles'
    time.tzset()
    import weewx.almanac
    import weewx.units
    import wxskyfield
    import wxskyfield_sky

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
    # Both plates: the night plate is the default and the light one is what
    # a day-lit page draws, and they differ in what casings a label wears
    # -- a cased label is TWO text elements, both of which have to clear
    # the floor and stay inside the drawing.
    frames = {}
    for palette in ('night', 'light'):
        for narrow in (True, False):
            frames['%s_%s' % (palette, 'narrow' if narrow else 'wide')] = {
                name: getattr(page, name)(alm, palette=palette, narrow=narrow)
                for name in PANELS}
    # Claim 6: the narrow drawings in every language this skin ships.
    # The almanac is handed each language's [Almanac] so body names
    # translate too, and the page its [Texts] so every label does.  Cheap:
    # the almanac work behind all of them is memoized on the one SkyPage
    # -- only the markup is built again, per language.
    langs = {}
    for path in sorted(os.listdir(os.path.join(SKIN, 'lang'))):
        if not path.endswith('.conf'):
            continue
        lang = path[:-5]
        sd = _skin_dict(lang)
        l_alm = weewx.almanac.Almanac(
            TIME_TS, LATITUDE, LONGITUDE, altitude=ALTITUDE_M,
            formatter=weewx.units.Formatter.fromSkinDict(sd),
            texts=sd.get('Almanac', {}))
        l_page = wxskyfield_sky.SkyPage(sd)
        langs[lang] = {name: getattr(l_page, name)(l_alm, narrow=True)
                       for name in PANELS}
    with open(os.path.join(REPO_ROOT, 'skins', 'Skyfield', 'sky.css')) as f:
        skin_css = f.read()
    with open(os.path.join(out_dir, 'frames.json'), 'w') as f:
        json.dump({'frames': frames, 'langs': langs, 'skin_css': skin_css}, f)


# ── half two: measure what the reader sees ──────────────────────────────────
# Every <text> in every SVG, with its font size multiplied by the SVG's own
# screen transform -- the size on the glass -- and its ink box against the
# drawing's own viewBox.
MEASURE = """() => {
  const out = [];
  for (const svg of document.querySelectorAll('svg')) {
    if (!svg.getClientRects().length) continue;      // the hidden frame
    const m = svg.getScreenCTM();
    if (!m) continue;
    const vb = svg.viewBox.baseVal;
    const holder = svg.closest('section');
    for (const t of svg.querySelectorAll('text')) {
      let bb;
      try { bb = t.getBBox(); } catch (e) { continue; }
      out.push({panel: holder ? holder.getAttribute('data-panel') : '?',
                cls: t.getAttribute('class') || '',
                px: parseFloat(getComputedStyle(t).fontSize) * Math.abs(m.a),
                text: t.textContent,
                out: (bb.x < -0.5 || bb.x + bb.width > vb.width + 0.5 ||
                      bb.y < -0.5 || bb.y + bb.height > vb.height + 0.5),
                box: [bb.x, bb.y, bb.width, bb.height],
                vb: [vb.width, vb.height]});
    }
  }
  return out;
}"""

# Every id on the page, so duplicates can be counted.
IDS = """() => [...document.querySelectorAll('[id]')].map(e => e.id)"""

# Which frames are on show, by the wrapper class each SVG sits in.
SHOWN = """() => {
  const seen = {desk: 0, phone: 0};
  for (const div of document.querySelectorAll('.sky-desk, .sky-phone'))
    if (div.getClientRects().length)
      seen[div.className === 'sky-desk' ? 'desk' : 'phone'] += 1;
  return seen;
}"""


def _page_html(panels, skin_css, theme):
    """The page as the skin builds it: both frames in their wrappers, the
    skin's own stylesheet, the skin's own section padding.  The padding is
    load-bearing -- it is what stands between a 320px screen and the ~270px
    the narrow frame needs -- so measuring fragments on a bare page would
    measure a page nobody is served."""
    body = []
    for name in PANELS:
        body.append('<section class="sec-x" data-panel="%s">'
                    '<h2 class="eyebrow">%s</h2>'
                    '<div class="sky-desk">%s</div>'
                    '<div class="sky-phone">%s</div></section>'
                    % (name, name, panels['wide'][name], panels['narrow'][name]))
    return ('<!DOCTYPE html><html lang="en"%s><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Frames</title><style>%s</style></head><body><div class="page">'
            '%s</div></body></html>'
            % ('' if theme == 'night' else ' class="theme-light"',
               skin_css, ''.join(body)))


def check(work_dir):
    from playwright.sync_api import sync_playwright
    with open(os.path.join(work_dir, 'frames.json')) as f:
        data = json.load(f)
    frames, langs, skin_css = data['frames'], data['langs'], data['skin_css']
    failures = []

    def fail(line):
        failures.append(line)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for theme in ('night', 'light'):
            panels = {'wide': frames['%s_wide' % theme],
                      'narrow': frames['%s_narrow' % theme]}
            page.set_content(_page_html(panels, skin_css, theme))
            for width in WIDTHS:
                page.set_viewport_size({'width': width, 'height': 900})
                rows = page.evaluate(MEASURE)
                if not rows:
                    fail('%s %dpx: nothing measured at all' % (theme, width))
                    continue
                # 1. every label clears the floor
                small = [r for r in rows if r['px'] < FLOOR_PX]
                if small:
                    worst = min(small, key=lambda r: r['px'])
                    fail('1. %s %dpx: %d label(s) under %.0fpx, worst %s %r at %.1fpx'
                         % (theme, width, len(small), FLOOR_PX, worst['panel'],
                            worst['text'][:24], worst['px']))
                # 2. nothing is clipped
                spill = [r for r in rows if r['out']]
                if spill:
                    r = spill[0]
                    fail('2. %s %dpx: %d label(s) leave the drawing, e.g. %s %r '
                         'box %s of %s'
                         % (theme, width, len(spill), r['panel'],
                            r['text'][:24], r['box'], r['vb']))
                # 5. exactly one frame is on show
                shown = page.evaluate(SHOWN)
                if shown['phone'] != len(PANELS) or shown['desk'] != 0:
                    fail('5. %s %dpx: %d narrow and %d wide drawings shown, '
                         'want %d and 0' % (theme, width, shown['phone'],
                                            shown['desk'], len(PANELS)))
            # 6. no id twice on a page that carries both frames
            ids = page.evaluate(IDS)
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                fail('7. %s: %d id(s) appear more than once on a page '
                     'carrying both frames: %s' % (theme, len(dupes), dupes))
            # 3. the narrow type rules beat the stylesheet's own class rules.
            # sky.css sets .gridlab to 10px; a narrow chart that did not
            # out-specify it would answer 10 here.
            page.set_viewport_size({'width': WIDTHS[-1], 'height': 900})
            got = page.evaluate("""() => {
              const t = document.querySelector('.sky-phone text.gridlab, '
                                             + '.sky-phone text.mono.gridlab');
              return t ? parseFloat(getComputedStyle(t).fontSize) : null;
            }""")
            if got != 15.0:
                fail('3. %s: a narrow chart\'s gridlab resolves to %r user units, '
                     'want 15 -- the stylesheet won' % (theme, got))
            # 4. the premise: the wide drawings really are too small here,
            # and are what the reader gets above the breakpoint.
            page.set_viewport_size({'width': BREAKPOINT + 200, 'height': 900})
            shown = page.evaluate(SHOWN)
            if shown['desk'] != len(PANELS) or shown['phone'] != 0:
                fail('5. %s %dpx: %d wide and %d narrow drawings shown, want %d '
                     'and 0' % (theme, BREAKPOINT + 200, shown['desk'],
                                shown['phone'], len(PANELS)))
            page.set_viewport_size({'width': WIDTHS[0], 'height': 900})
            page.add_style_tag(content='.sky-desk{display:block}'
                                       '.sky-phone{display:none}')
            wide_rows = page.evaluate(MEASURE)
            under = [r for r in wide_rows if r['px'] < FLOOR_PX]
            if not under:
                fail('4. %s: the WIDE drawings cleared %.0fpx at %dpx wide, so '
                     'this measurement cannot see the defect the narrow frame '
                     'fixes' % (theme, FLOOR_PX, WIDTHS[0]))
        # 6. every shipped translation, at the narrower width
        page.set_viewport_size({'width': WIDTHS[0], 'height': 900})
        for lang in sorted(langs):
            page.set_content(_page_html({'wide': langs[lang],
                                         'narrow': langs[lang]},
                                        skin_css, 'night'))
            rows = page.evaluate(MEASURE)
            if not rows:
                fail('6. %s: nothing measured' % lang)
                continue
            small = [r for r in rows if r['px'] < FLOOR_PX]
            if small:
                worst = min(small, key=lambda r: r['px'])
                fail('6. %s at %dpx: %d label(s) under %.0fpx, worst %s %r '
                     'at %.1fpx' % (lang, WIDTHS[0], len(small), FLOOR_PX,
                                    worst['panel'], worst['text'][:24],
                                    worst['px']))
            spill = [r for r in rows if r['out']]
            if spill:
                r = spill[0]
                fail('6. %s: %d label(s) leave the drawing, e.g. %s %r box %s '
                     'of %s -- a gutter cut for the English string'
                     % (lang, len(spill), r['panel'], r['text'][:24],
                        [round(v, 1) for v in r['box']], r['vb']))
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
    with tempfile.TemporaryDirectory(prefix='skynarrow-') as work:
        render(work)
        return subprocess.call([PWENV, os.path.abspath(__file__),
                                '--browser-half', work])


if __name__ == '__main__':
    sys.exit(main())
