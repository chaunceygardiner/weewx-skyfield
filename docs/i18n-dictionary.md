---
title: The dictionary
layout: default
parent: Translations
nav_order: 1
description: Every translatable string in weewx-skyfield's Sky page and almanac — the [Texts] keys, the body names, the constellations and the meteor showers.
---

# The dictionary

[weewx-skyfield manual](https://chaunceygardiner.github.io/weewx-skyfield/) ·
[weewx-skyfield on GitHub](https://github.com/chaunceygardiner/weewx-skyfield) ·
[Report an issue](https://github.com/chaunceygardiner/weewx-skyfield/issues)

---

Every string the Sky page and the almanac can translate.  [Translations](i18n.md) explains
the mechanism and how to start a new language; this page is the reference list.

The complete reference dictionary, as shipped in 2.1 (`skins/Skyfield/lang/en.conf` in the
installed extension is always the authoritative copy for your version):

```ini
# skins/Skyfield/lang/en.conf
#
# English -- the Sky page's reference dictionary.  Every string the page
# renders is here, and nothing else: tests/test_sky_page.py fails if a key
# rendered by index.html.tmpl or wxskyfield_sky.py is missing from this
# file, or if this file carries a key nothing renders.
#
# Translations are gettext-style: the English string IS the key, and a
# report falls back to the English, one string at a time, for any key its
# language file does not carry -- a partial translation is fine.
# Composed strings keep their {named} placeholders; translators may
# reorder them but must not rename them.

[Labels]

    # Hemisphere abbreviations, for the latitude/longitude in the header
    hemispheres = N, S, E, W

[Units]

    [[Ordinates]]

        # Compass ordinal directions; the panels use N, E, S and W
        directions = N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW, N/A

[Almanac]

    # Moon phase names, for $almanac.moon_phase in the header
    moon_phases = New, Waxing crescent, First quarter, Waxing gibbous, Full, Waning gibbous, Last quarter, Waning crescent

    # Body display names, keyed by tag name: $almanac.<body>.label and
    # every panel label, chip, table row and tooltip.  Named stars may be
    # added the same way (e.g. polaris = ...).
    sun = Sun
    moon = Moon
    mercury = Mercury
    venus = Venus
    earth = Earth
    mars = Mars
    jupiter = Jupiter
    saturn = Saturn
    uranus = Uranus
    neptune = Neptune

    # Satellite display names, keyed by tag name -- the [Skyfield]
    # [[Satellites]] entries.  A satellite without one shows its tag
    # name title-cased.
    iss = ISS
    tiangong = Tiangong
    hst = HST

    # Comet display names, keyed by tag name -- the [Skyfield]
    # [[Comets]] entries.  A comet without one shows its tag name
    # title-cased.
    halley = Halley
    hale_bopp = Hale-Bopp

    # Meteor shower display names, keyed by the shower key --
    # $almanac.next_meteor_shower.label and the countdown chip.
    [[MeteorShowers]]
        quadrantids = Quadrantids
        lyrids = Lyrids
        eta_aquariids = Eta Aquariids
        delta_aquariids = Southern Delta Aquariids
        perseids = Perseids
        draconids = Draconids
        orionids = Orionids
        southern_taurids = Southern Taurids
        northern_taurids = Northern Taurids
        leonids = Leonids
        geminids = Geminids
        ursids = Ursids

    # Constellation display names, keyed by IAU abbreviation:
    # $almanac.<body>.constellation.label and the planet chips.  English
    # uses the Latin names, so this section doubles as the key reference;
    # $almanac.<body>.constellation always reports the Latin name.
    [[Constellations]]
        And = Andromeda
        Ant = Antlia
        Aps = Apus
        Aqr = Aquarius
        Aql = Aquila
        Ara = Ara
        Ari = Aries
        Aur = Auriga
        Boo = Boötes
        Cae = Caelum
        Cam = Camelopardalis
        Cnc = Cancer
        CVn = Canes Venatici
        CMa = Canis Major
        CMi = Canis Minor
        Cap = Capricornus
        Car = Carina
        Cas = Cassiopeia
        Cen = Centaurus
        Cep = Cepheus
        Cet = Cetus
        Cha = Chamaeleon
        Cir = Circinus
        Col = Columba
        Com = Coma Berenices
        CrA = Corona Australis
        CrB = Corona Borealis
        Crv = Corvus
        Crt = Crater
        Cru = Crux
        Cyg = Cygnus
        Del = Delphinus
        Dor = Dorado
        Dra = Draco
        Equ = Equuleus
        Eri = Eridanus
        For = Fornax
        Gem = Gemini
        Gru = Grus
        Her = Hercules
        Hor = Horologium
        Hya = Hydra
        Hyi = Hydrus
        Ind = Indus
        Lac = Lacerta
        Leo = Leo
        LMi = Leo Minor
        Lep = Lepus
        Lib = Libra
        Lup = Lupus
        Lyn = Lynx
        Lyr = Lyra
        Men = Mensa
        Mic = Microscopium
        Mon = Monoceros
        Mus = Musca
        Nor = Norma
        Oct = Octans
        Oph = Ophiuchus
        Ori = Orion
        Pav = Pavo
        Peg = Pegasus
        Per = Perseus
        Phe = Phoenix
        Pic = Pictor
        Psc = Pisces
        PsA = Piscis Austrinus
        Pup = Puppis
        Pyx = Pyxis
        Ret = Reticulum
        Sge = Sagitta
        Sgr = Sagittarius
        Sco = Scorpius
        Scl = Sculptor
        Sct = Scutum
        Ser = Serpens
        Sex = Sextans
        Tau = Taurus
        Tel = Telescopium
        Tri = Triangulum
        TrA = Triangulum Australe
        Tuc = Tucana
        UMa = Ursa Major
        UMi = Ursa Minor
        Vel = Vela
        Vir = Virgo
        Vol = Volans
        Vul = Vulpecula

[Texts]

    # ── page prose (index.html.tmpl) ─────────────────────────────────────
    "The Sky over {location}" = "The Sky over {location}"
    'The Sky <span class="over">over</span> {location}' = 'The Sky <span class="over">over</span> {location}'
    "{pct}% illuminated" = "{pct}% illuminated"
    "moonset {time}" = "moonset {time}"
    "The Sky Now · looking up" = "The Sky Now · looking up"
    "North at the top, east at the left — the sky-chart orientation, as if lying on your back looking up.  Altitude rings at 30° and 60°; the rim is the horizon." = "North at the top, east at the left — the sky-chart orientation, as if lying on your back looking up.  Altitude rings at 30° and 60°; the rim is the horizon."
    "The sun is up, so the plate shows the stars where they stand behind the daylight — Skyfield knows, even when you cannot see them." = "The sun is up, so the plate shows the stars where they stand behind the daylight — Skyfield knows, even when you cannot see them."
    "Dot size follows magnitude; the brighter the star, the larger the mark." = "Dot size follows magnitude; the brighter the star, the larger the mark."
    "Hover or tap any mark for its coordinates." = "Hover or tap any mark for its coordinates."
    "Rise & Set · today" = "Rise & Set · today"
    "Bars span each body's time above the horizon; the tick across each bar is the transit.  Background bands are tonight's darkness: civil, nautical and astronomical twilight — the USNO geometric definitions." = "Bars span each body's time above the horizon; the tick across each bar is the transit.  Background bands are tonight's darkness: civil, nautical and astronomical twilight — the USNO geometric definitions."
    "The Solar Year · daylight week by week" = "The Solar Year · daylight week by week"
    "Sunrise, sunset and solar noon (dashed) for every week of the year, over the same twilight bands as the timeline above — in local clock time, so the daylight-saving steps in spring and fall are real.  The brass line is today." = "Sunrise, sunset and solar noon (dashed) for every week of the year, over the same twilight bands as the timeline above — in local clock time, so the daylight-saving steps in spring and fall are real.  The brass line is today."
    "The Lunar Month · this lunation" = "The Lunar Month · this lunation"
    "New moon to new moon in thirty steps, the principal phases dated; the brass ring is today.  Hover or tap any disc for its date and illumination." = "New moon to new moon in thirty steps, the principal phases dated; the brass ring is today.  Hover or tap any disc for its date and illumination."
    "The Almanac Table" = "The Almanac Table"
    "Every value on this page is a WeeWX report tag served by weewx-skyfield — no PyEphem, and the page itself fetches nothing." = "Every value on this page is a WeeWX report tag served by weewx-skyfield — no PyEphem, and the page itself fetches nothing."
    "Sun & Planets · today" = "Sun & Planets · today"
    "Sun, Planets & Comets · today" = "Sun, Planets & Comets · today"
    "{name} perihelion" = "{name} perihelion"
    "Satellites · the next visible pass" = "Satellites · the next visible pass"
    "Each row is the satellite's next visible pass — visible means the satellite is sunlit while your sky is dark, peaking at least 10° up.  The soonest of these passes gets its own chart below.  Orbital elements refresh from CelesTrak every few hours." = "Each row is the satellite's next visible pass — visible means the satellite is sunlit while your sky is dark, peaking at least 10° up.  The soonest of these passes gets its own chart below.  Orbital elements refresh from CelesTrak every few hours."
    "The Next Visible Pass · the sky at its peak" = "The Next Visible Pass · the sky at its peak"
    "The whole sky as it will stand at the pass's highest point, on the date above — the dashed arc is the satellite's path, its rise and set times at the ends.  Only stars bright enough for a twilight sky are drawn: a visible pass happens while your sky is half dark." = "The whole sky as it will stand at the pass's highest point, on the date above — the dashed arc is the satellite's path, its rise and set times at the ends.  Only stars bright enough for a twilight sky are drawn: a visible pass happens while your sky is half dark."
    "The Sun’s Path · today" = "The Sun’s Path · today"
    "Altitude against azimuth from midnight to midnight, a dot every hour.  The dashed curve is the moon’s path, its rise, set and highest point marked with times; the 00 and 24 dots are the moon’s positions at the day’s two midnights — the curve is open between them because a lunar day runs about 50 minutes longer than a calendar day, and near full moon that break sits right at the top of the arc.  The bands below the horizon line are civil, nautical and astronomical twilight depth." = "Altitude against azimuth from midnight to midnight, a dot every hour.  The dashed curve is the moon’s path, its rise, set and highest point marked with times; the 00 and 24 dots are the moon’s positions at the day’s two midnights — the curve is open between them because a lunar day runs about 50 minutes longer than a calendar day, and near full moon that break sits right at the top of the arc.  The bands below the horizon line are civil, nautical and astronomical twilight depth."
    "The Solar System · today's positions" = "The Solar System · today's positions"
    "Heliocentric longitudes, viewed from above the north ecliptic pole; orbit spacing is logarithmic.  The dashed ray marks 0° (the direction of the vernal equinox)." = "Heliocentric longitudes, viewed from above the north ecliptic pole; orbit spacing is logarithmic.  The dashed ray marks 0° (the direction of the vernal equinox)."
    "Analemma · the sun at noon" = "Analemma · the sun at noon"
    "The Equation of Time · sundial vs clock" = "The Equation of Time · sundial vs clock"
    "Sundial time minus clock time at local standard noon, week by week — above the zero line the sundial runs ahead.  The curve's two bulges are Earth's tilt and its elliptical orbit, the same pair that draws the analemma's figure-eight; the brass point is today." = "Sundial time minus clock time at local standard noon, week by week — above the zero line the sundial runs ahead.  The curve's two bulges are Earth's tilt and its elliptical orbit, the same pair that draws the analemma's figure-eight; the brass point is today."
    "The sun's altitude and azimuth at local standard noon for every week of the year.  The figure-eight is the sum of Earth's tilt and its elliptical orbit; the brass point is today." = "The sun's altitude and azimuth at local standard noon for every week of the year.  The figure-eight is the sum of Earth's tilt and its elliptical orbit; the brass point is today."

    # ── panel strings (wxskyfield_sky.py) ────────────────────────────────
    "{h}h {m}m" = "{h}h {m}m"
    "Supermoon {date} — full moon within a day of perigee" = "Supermoon {date} — full moon within a day of perigee"
    "perigee {date}" = "perigee {date}"
    "apogee {date}" = "apogee {date}"
    "Computed with the station’s built-in almanac" = "Computed with the station’s built-in almanac"
    "weewx-skyfield is not active — see the weewxd log" = "weewx-skyfield is not active — see the weewxd log"
    "Regenerated every report cycle" = "Regenerated every report cycle"
    "Computed with weewx-skyfield" = "Computed with weewx-skyfield"
    "Skyfield and the JPL DE421 ephemeris" = "Skyfield and the JPL DE421 ephemeris"
    "IAU-CSN star names" = "IAU-CSN star names"
    "Hipparcos star data Credit: ESA" = "Hipparcos star data Credit: ESA"
    "Satellite elements: CelesTrak" = "Satellite elements: CelesTrak"
    "Comet elements: Minor Planet Center" = "Comet elements: Minor Planet Center"
    "Meteor shower data: IMO" = "Meteor shower data: IMO"
    "Constellation figures: Stellarium" = "Constellation figures: Stellarium"
    "star catalog unavailable — see the weewxd log" = "star catalog unavailable — see the weewxd log"
    "star catalog disabled" = "star catalog disabled"
    "today" = "today"
    "in {n} day" = "in {n} day"
    "in {n} days" = "in {n} days"
    "new moon" = "new moon"
    "full moon" = "full moon"
    "equinox" = "equinox"
    "solstice" = "solstice"
    "lunar eclipse" = "lunar eclipse"
    "solar eclipse" = "solar eclipse"
    "penumbral" = "penumbral"
    "partial" = "partial"
    "total" = "total"
    "annular" = "annular"
    "Moon phase" = "Moon phase"
    "Sky dome chart" = "Sky dome chart"
    "Pass sky chart" = "Pass sky chart"
    "{name} — alt {alt}°, az {az}°, mag {mag}" = "{name} — alt {alt}°, az {az}°, mag {mag}"
    "{name} — alt {alt}°, az {az}°" = "{name} — alt {alt}°, az {az}°"
    "{name} — alt {alt}°, az {az}° — in shadow" = "{name} — alt {alt}°, az {az}° — in shadow"
    "{name} — alt {alt}°, az {az}°, {pct}% illuminated" = "{name} — alt {alt}°, az {az}°, {pct}% illuminated"
    "Rise and set timeline" = "Rise and set timeline"
    "always up" = "always up"
    "never up" = "never up"
    "{name} above the horizon ({duration})" = "{name} above the horizon ({duration})"
    "{name} transit {time}" = "{name} transit {time}"
    "now {time}" = "now {time}"
    "Solar system plan view" = "Solar system plan view"
    "{name} — heliocentric longitude {deg}°" = "{name} — heliocentric longitude {deg}°"
    "{name} — heliocentric longitude {deg}°, {dist} au" = "{name} — heliocentric longitude {deg}°, {dist} au"
    "Analemma" = "Analemma"
    "Equation of time" = "Equation of time"
    "azimuth" = "azimuth"
    "{date} — alt {alt}°, az {az}°" = "{date} — alt {alt}°, az {az}°"
    "Sun path today" = "Sun path today"
    "Moon at {time} — the day’s track is open here: a lunar day runs about 50 minutes longer than a calendar day" = "Moon at {time} — the day’s track is open here: a lunar day runs about 50 minutes longer than a calendar day"
    "Moon transit {time} — altitude {alt}°" = "Moon transit {time} — altitude {alt}°"
    "Moonrise {time}" = "Moonrise {time}"
    "Moonset {time}" = "Moonset {time}"
    "Moon now — alt {alt}°, az {az}°" = "Moon now — alt {alt}°, az {az}°"
    "Sun now — alt {alt}°, az {az}°" = "Sun now — alt {alt}°, az {az}°"
    "Day length through the year" = "Day length through the year"
    "{date} — daylight {duration}" = "{date} — daylight {duration}"
    "The lunar month" = "The lunar month"
    "{date} — {pct}% illuminated" = "{date} — {pct}% illuminated"
    "new" = "new"
    "first quarter" = "first quarter"
    "full" = "full"
    "last quarter" = "last quarter"
    "Daylight" = "Daylight"
    "{duration} · sun {rise} → {set}" = "{duration} · sun {rise} → {set}"
    "civil dusk {dusk} · astro dark {dark}" = "civil dusk {dusk} · astro dark {dark}"
    "up now — alt {alt}° · az {az}°" = "up now — alt {alt}° · az {az}°"
    "rises {time}" = "rises {time}"
    "below the horizon" = "below the horizon"
    "mag {mag} · {dist} au · elong {elong}°" = "mag {mag} · {dist} au · elong {elong}°"
    "in {constellation}" = "in {constellation}"
    "CML I {one}° · II {two}°" = "CML I {one}° · II {two}°"
    "ring tilt {tilt}°" = "ring tilt {tilt}°"
    "{dist} km" = "{dist} km"
    "{dist} au" = "{dist} au"
    "overhead now" = "overhead now"
    "in {m} min" = "in {m} min"
    "in {h} h" = "in {h} h"
    "appears {rise} · peaks {alt}° {culm} · disappears {set} · {m} min" = "appears {rise} · peaks {alt}° {culm} · disappears {set} · {m} min"
    "no visible pass in the coming week" = "no visible pass in the coming week"
    "no usable orbital elements — see the weewxd log" = "no usable orbital elements — see the weewxd log"
    "{name} pass — {rise} → {set}, peak {alt}°" = "{name} pass — {rise} → {set}, peak {alt}°"
    "{date} · {rise} → {set} · peak {alt}°" = "{date} · {rise} → {set} · peak {alt}°"
    "Body" = "Body"
    "Rise" = "Rise"
    "Transit" = "Transit"
    "Set" = "Set"
    "Up for" = "Up for"
    "Altitude" = "Altitude"
    "Azimuth" = "Azimuth"
    "Mag" = "Mag"
    "Distance" = "Distance"

    # ── date formats (strftime) ──────────────────────────────────────────
    # A translation reorders day and month and adjusts punctuation; the
    # month and weekday NAMES (%b, %B, %A) come from strftime, i.e. the
    # weewxd process locale.
    "%b %-d" = "%b %-d"
    "%a %b %-d" = "%a %b %-d"
    "%b %-d %Y" = "%b %-d %Y"
    "%A, %B %-d %Y, %-H:%M %Z" = "%A, %B %-d %Y, %-H:%M %Z"
    "moon {pct}%" = "moon {pct}%"
    "{name} radiant — ZHR {zhr}, peak {date}" = "{name} radiant — ZHR {zhr}, peak {date}"
```
