"""Shared utilities for the Mattermost integration."""

import re
from urllib.parse import quote

# Een `@` die geen mention mag worden. Een backslash ervoor helpt niet:
# Mattermost zoekt mentions in de tekst ná het parsen van de markdown, en
# daar is `\@channel` alweer `@channel` (`parseEscapeCharacter` in de
# server, en daarna `getExplicitMentions`). Een woordverbinder (U+2060)
# direct na de `@` werkt wel: de mention-parser knipt de tekst op elk
# teken dat geen letter, cijfer of een van `.-_:@` is, en dan staan er
# een losse `@` en een los woord. In de webapp is hij onzichtbaar.
GEEN_MENTION = "@⁠"

# Characters that have special meaning in Mattermost markdown.
#
# De backslash zelf hoort erbij: anders wordt `\[` in de bron na het
# escapen `\\[`, en dat is een letterlijke backslash gevolgd door een
# echte `[`, het begin van een link.
_MM_ESCAPE_CHARS = str.maketrans(
    {
        "\\": "\\\\",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "@": GEEN_MENTION,
        "~": "\\~",
        "*": "\\*",
        "_": "\\_",
        "`": "\\`",
        "#": "\\#",
        "|": "\\|",
    }
)


# Dezelfde tekens, zonder de haakjes. Haakjes hebben in Mattermost alleen
# betekenis direct ná een `]` — dus in linktekst. In gewone prozatekst
# leveren ze niets op behalve zichtbare backslashes, en die stonden in
# productie in een samenvatting: "Meerdere fracties \(D66, VVD\) stellen".
#
# Een aparte tabel en niet de bestaande aanpassen, omdat de strikte vorm
# nog nodig is voor tekst die tússen `[` en `]` belandt.
_MM_ESCAPE_PROZA = str.maketrans(
    {
        "\\": "\\\\",
        "[": "\\[",
        "]": "\\]",
        "@": GEEN_MENTION,
        "~": "\\~",
        "*": "\\*",
        "_": "\\_",
        "`": "\\`",
        "#": "\\#",
        "|": "\\|",
    }
)


def escape_mattermost_prose(text: str) -> str:
    """Escape voor lopende tekst, waar haakjes gewoon haakjes zijn.

    Voor linktekst (alles wat tussen `[` en `]` komt) hoort
    `escape_mattermost_md`, want daar maakt een haakje wél verschil.
    """
    return text.translate(_MM_ESCAPE_PROZA)


def escape_mattermost_md(text: str) -> str:
    """Escape Mattermost markdown special characters in user-controlled text."""
    return text.translate(_MM_ESCAPE_CHARS)


def zonder_mentions(text: str) -> str:
    """Platte tekst (een titel met link, een voettekst, een `fallback`).

    Daar is geen markdown, dus escapen levert alleen zichtbare
    backslashes op. Mentions worden er wel in gezocht.
    """
    return text.replace("@", GEEN_MENTION)


# Wat een markdownlink kan afsluiten of openbreken: haakjes en blokhaken,
# punthaken, een backslash (escape binnen de URL) en witruimte (daarna
# kan een linktitel beginnen).
_URL_GEVAARLIJK = re.compile(r"[\s()<>\[\]\\]")


def markdown_url(url: str) -> str:
    """Een URL die veilig tussen de haakjes van `[tekst](url)` past.

    Percent-encoding van precies de tekens die de link anders afsluiten:
    `https://x/a)[Inloggen](https://kwaad` blijft zo één link naar x.
    """
    return _URL_GEVAARLIJK.sub(lambda m: quote(m.group(), safe=""), url)
