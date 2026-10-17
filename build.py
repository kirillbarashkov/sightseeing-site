#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Site builder for the Sightseeing site -- two tabs, one build.

Reads notes tagged #public from two Obsidian projects and produces a static
site in ./site_build:

    index.html              -- TAB 1: grid of place cards
    places/<slug>.html      -- one detail page per place
    lenochka.html           -- TAB 2: "Леночка приезжает" (days in Moscow)
    lenochka/den-NN.html    -- one page per day
    lenochka/<slug>.html    -- one page per venue / hotel / restaurant
    assets/style.css        -- base design system (shared chrome + tab 1)
    assets/trip.css         -- warm editorial theme for tab 2
    .nojekyll               -- stop GitHub Pages from running Jekyll

Usage:  python build.py
"""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")

try:
    import markdown as md
except ImportError:
    sys.exit("Missing dependency: pip install markdown")


VAULT_PLACES = Path(r"D:\DataBases\mstr_obs_git\02-Projects\02-Sightseeing\Places")
VAULT_TRIP = Path(r"D:\DataBases\mstr_obs_git\02-Projects\05-Lenochka-coming")
TRIP_DAYS = VAULT_TRIP / "Days"
TRIP_PLACES = VAULT_TRIP / "Places"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site_build"

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

PRIORITY_CLASS = {
    "must visit": "prio-high",
    "nice to have": "prio-low",
}

MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

WEEKDAYS = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]

# Venue categories that count as "события" in the trip hero.
EVENT_CATEGORIES = {"концерт", "театр", "круиз", "спектакль"}
HOTEL_CATEGORIES = {"отель", "гостиница"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def slugify(name: str) -> str:
    """Transliterate a Cyrillic note title into a URL-safe ASCII slug."""
    chunks = []
    for ch in name.lower():
        if ch in TRANSLIT:
            chunks.append(TRANSLIT[ch])
        elif ch.isascii() and ch.isalnum():
            chunks.append(ch)
        else:
            chunks.append("-")
    slug = re.sub(r"-+", "-", "".join(chunks)).strip("-")
    return slug or "place"


def clean(value):
    """Return an escaped string, or None for empty/placeholder values."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return html.escape(text)


def raw(value) -> str:
    """Return a plain stripped string, or '' when empty."""
    if value is None:
        return ""
    return str(value).strip()


class NoteError(Exception):
    """Raised when a note is malformed. Aborts the build."""


def read_note(path: Path):
    """Parse one note. Returns a dict for #public notes, else None.

    Raises NoteError when the frontmatter is not valid YAML, so a broken note
    stops the build instead of silently vanishing from the published site.
    """
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise NoteError("YAML error in %s: %s" % (path.name, exc)) from None

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    tags = [str(t).strip().lstrip("#") for t in tags]
    if "public" not in tags:
        return None

    return {
        "stem": path.stem,
        "meta": meta,
        "body": parts[2],
        "tags": tags,
    }


CALLOUT_ICONS = {
    "info": "\u2139\ufe0f",
    "note": "\U0001f4dd",
    "tip": "\U0001f4a1",
    "hint": "\U0001f4a1",
    "warning": "\u26a0\ufe0f",
    "caution": "\u26a0\ufe0f",
    "danger": "\u26d4",
    "important": "\u2757",
    "success": "\u2705",
    "quote": "\U0001f4ac",
}


def _callout(match):
    icon = CALLOUT_ICONS.get(match.group(1).lower(), "\U0001f4a1")
    title = match.group(2).strip()
    label = icon + (" " + title if title else "")
    return "> **" + label + "**"


def _mask_autolinks(markup: str) -> str:
    """Replace anchors whose text is the raw URL with a short human label."""
    def repl(match):
        url = match.group(1)
        if match.group(2) != url:
            return match.group(0)
        rest = re.sub(r"^https?://", "", url)
        host, _, path = rest.partition("/")
        segments = [seg for seg in path.split("/") if seg]
        label = host + ("/\u2026/" + segments[-1] if segments else "")
        if len(label) > 46:
            label = label[:43].rstrip("/") + "\u2026"
        return '<a href="' + url + '">' + html.escape(label) + "</a>"

    return re.sub(r'<a href="([^"]+)">([^<]+)</a>', repl, markup)


WIKI_LINKS = {}   # note stem / title -> slug, rebuilt per section
LINK_PREFIX = ""  # relative prefix for wiki-link targets on the current page

WIKI_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def set_prefix(value: str) -> None:
    """Set the relative prefix used for wiki-link targets ('' or 'lenochka/')."""
    global LINK_PREFIX
    LINK_PREFIX = value


def _link_target(match):
    """[[Note]] / [[Note|Alias]] -> (label, slug or None)."""
    target = match.group(1).strip()
    alias = match.group(2)
    label = (alias or target).strip()
    return label, WIKI_LINKS.get(target)


def _wiki_link(match):
    """Obsidian wiki-link -> anchor to the published page.

    Links to notes that are not published degrade to plain text, so the site
    never shows literal double brackets or a dead link.
    """
    label, slug = _link_target(match)
    if slug is None:
        return label
    return '<a href="' + LINK_PREFIX + slug + '.html">' + html.escape(label) + "</a>"


def linkify(text: str) -> str:
    """Escape plain text but keep [[wiki-links]] as real anchors."""
    out = []
    pos = 0
    for match in WIKI_RE.finditer(text):
        out.append(html.escape(text[pos:match.start()]))
        label, slug = _link_target(match)
        if slug is None:
            out.append(html.escape(label))
        else:
            out.append(
                '<a href="' + LINK_PREFIX + slug + '.html">' + html.escape(label) + "</a>"
            )
        pos = match.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def to_html(body: str) -> str:
    """Markdown body -> HTML, with Obsidian checkboxes and callouts handled."""
    # drop the note's own leading H1 -- the page already renders the title
    body = re.sub(r"^\s*#\s+[^\n]*\n?", "", body, count=1)
    # Obsidian wiki-links -> real anchors (or plain text when not published)
    body = WIKI_RE.sub(_wiki_link, body)
    # Obsidian callouts: "> [!info] Title" -> "> **INFO Title**"
    body = re.sub(r"^>\s*\[!(\w+)\]\s*(.*)$", _callout, body, flags=re.M)
    # strip empty template fields like "- Транспорт: "
    body = re.sub(r"^\s*[-*]\s+[^\n:]+:\s*$", "", body, flags=re.M)
    body = re.sub(r"^(\s*)- \[ \]", lambda m: m.group(1) + "- \u2610", body, flags=re.M)
    body = re.sub(r"^(\s*)- \[[xX]\]", lambda m: m.group(1) + "- \u2611", body, flags=re.M)
    markup = md.markdown(body, extensions=["extra", "sane_lists", "nl2br"])
    return _mask_autolinks(markup)


def excerpt(body: str, limit: int = 160) -> str:
    """First meaningful line of the note, as plain text for a card.

    Skips the leading H1, Obsidian callouts/blockquotes, headings and
    checklist items so cards never show markup like "[!info]".
    """
    candidates = []
    for line_text in body.splitlines():
        line = line_text.strip()
        if not line:
            continue
        if line.startswith(">"):        # callouts and quotes
            continue
        if line.startswith("#"):        # headings
            continue
        if line.startswith("|"):        # tables
            continue
        candidates.append(line)

    text = ""
    # prefer the explicit description bullet
    for line in candidates:
        if re.match(r"^\s*[-*]\s+\*\*Что это", line, flags=re.I):
            text = line
            break
    if not text:
        for line in candidates:
            if re.match(r"^\s*[-*]\s*\[[ xX]?\]", line):   # checklist
                continue
            text = line
            break

    text = re.sub(r"^\s*[-*]\s*", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)           # bold markers
    text = re.sub(r"^\s*[^:]{1,30}:\s*", "", text)         # leading "Label:"
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", text)      # links
    text = re.sub(r"<(.+?)>", r"\1", text)                 # autolinks
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "\u2026"
    return html.escape(text)


def plural_word(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def plural(n: int) -> str:
    return plural_word(n, "место", "места", "мест")


def as_date(value):
    """YAML date / string -> date, or None."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def ru_date(day: dt.date) -> str:
    return str(day.day) + " " + MONTHS_GEN[day.month - 1]


def maps_url(address: str) -> str:
    return "https://yandex.ru/maps/?text=" + quote(address)


# --------------------------------------------------------------------------- #
# styling -- base (shared chrome + tab 1, Vercel-flavoured)
# --------------------------------------------------------------------------- #

STYLE = """
:root {
  --ink: #171717;
  --muted: #4d4d4d;
  --faint: #808080;
  --line: rgba(0, 0, 0, 0.08);
  --surface: #ffffff;
  --canvas: #ffffff;
  --wash: #fafafa;
  --accent-bg: #ebf5ff;
  --accent-fg: #0068d6;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 80px 24px 120px;
  background: var(--canvas);
  color: var(--ink);
  font-family: 'Geist', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 960px; margin: 0 auto; }

/* ---------- top navigation (both tabs) ---------- */
.topnav {
  display: flex;
  align-items: center;
  gap: 26px;
  margin: 0 0 56px;
  padding-bottom: 15px;
  box-shadow: 0 1px 0 0 var(--line);
}
.topnav-brand {
  margin-right: auto;
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
  text-decoration: none;
  white-space: nowrap;
}
.topnav-link {
  position: relative;
  padding: 2px 0;
  font-size: 14px;
  color: var(--muted);
  text-decoration: none;
  white-space: nowrap;
}
.topnav-link:hover { color: var(--ink); }
.topnav-link.active { color: var(--ink); }
.topnav-link.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -7px;
  height: 1.5px;
  background: var(--accent-fg);
}

/* ---------- header ---------- */
.masthead { margin-bottom: 72px; }
.masthead h1 {
  margin: 0 0 12px;
  font-size: 48px;
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -2.4px;
}
.masthead p { margin: 0; color: var(--faint); font-size: 18px; }
.masthead .count {
  display: inline-block;
  margin-top: 20px;
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--faint);
}

/* ---------- card ---------- */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 24px;
}
.card {
  display: block;
  padding: 24px;
  border-radius: 8px;
  background: var(--surface);
  color: inherit;
  text-decoration: none;
  box-shadow: var(--line) 0 0 0 1px, rgba(0,0,0,0.04) 0 2px 2px,
              var(--wash) 0 0 0 1px;
  transition: box-shadow .2s ease, transform .2s ease;
}
.card:hover {
  box-shadow: rgba(0,0,0,0.14) 0 0 0 1px, rgba(0,0,0,0.06) 0 6px 10px;
  transform: translateY(-1px);
}
.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.card h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.6px;
  line-height: 1.3;
}
.card .excerpt {
  margin: 0 0 18px;
  color: var(--muted);
  font-size: 14px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card .meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--faint);
}

/* ---------- badges ---------- */
.badge {
  flex: none;
  padding: 3px 10px;
  border-radius: 9999px;
  background: var(--accent-bg);
  color: var(--accent-fg);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.badge-quiet {
  background: var(--wash);
  color: var(--muted);
  box-shadow: var(--line) 0 0 0 1px;
}
.prio-high { color: #0a72ef; }
.prio-low  { color: var(--faint); }

/* ---------- detail page ---------- */
.back {
  display: inline-block;
  margin-bottom: 32px;
  color: var(--faint);
  font-size: 14px;
  text-decoration: none;
}
.back:hover { color: var(--ink); }
.detail h1 {
  margin: 0 0 14px;
  font-size: 40px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -2px;
}
.detail .badges { display: flex; gap: 8px; margin-bottom: 20px; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 40px; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 14px;
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  box-shadow: var(--line) 0 0 0 1px, rgba(0,0,0,0.04) 0 1px 1px;
  transition: box-shadow .18s ease, transform .18s ease;
}
.chip:hover {
  box-shadow: rgba(0,0,0,0.14) 0 0 0 1px, rgba(0,0,0,0.06) 0 4px 8px;
  transform: translateY(-1px);
}
.chip svg { flex: none; color: var(--faint); }
.chip:hover svg { color: var(--accent-fg); }
.specs {
  margin: 0 0 48px;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.specs > div {
  padding: 12px 16px;
  border-radius: 8px;
  background: var(--wash);
  box-shadow: var(--line) 0 0 0 1px;
}
.specs dt {
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--faint);
  margin-bottom: 4px;
}
.specs dd { margin: 0; font-size: 15px; }
.specs dd a { color: var(--accent-fg); text-decoration: none; }
.specs dd a:hover { text-decoration: underline; }

/* ---------- prose ---------- */
.prose h2 {
  margin: 48px 0 16px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.96px;
  padding-bottom: 10px;
  box-shadow: 0 1px 0 0 var(--line);
}
.prose h3 { margin: 32px 0 12px; font-size: 18px; font-weight: 600; }
.prose p, .prose li { color: var(--muted); }
.prose ul { padding-left: 22px; }
.prose li { margin: 6px 0; }
.prose a { color: var(--accent-fg); }
.prose code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--wash);
  box-shadow: var(--line) 0 0 0 1px;
  font-family: 'Geist Mono', ui-monospace, monospace;
  font-size: 0.9em;
}
.prose blockquote {
  margin: 24px 0;
  padding: 4px 0 4px 20px;
  border-left: 2px solid var(--line);
  color: var(--faint);
}
.prose table { border-collapse: collapse; width: 100%; margin: 24px 0; font-size: 14px; }
.prose th, .prose td { padding: 10px 12px; text-align: left; box-shadow: var(--line) 0 0 0 1px; }
.prose th { font-weight: 600; background: var(--wash); }
.prose hr { margin: 48px 0; border: 0; box-shadow: 0 1px 0 0 var(--line); }

/* ---------- footer ---------- */
.foot {
  margin-top: 96px;
  padding-top: 24px;
  box-shadow: 0 -1px 0 0 var(--line);
  font-size: 13px;
  color: var(--faint);
}

@media (max-width: 640px) {
  body { padding: 48px 18px 80px; }
  .masthead h1 { font-size: 34px; letter-spacing: -1.6px; }
  .detail h1 { font-size: 30px; letter-spacing: -1.2px; }
  .masthead { margin-bottom: 48px; }
  .topnav { gap: 16px; margin-bottom: 36px; }
  .topnav-brand { display: none; }
}
""".strip()


# --------------------------------------------------------------------------- #
# styling -- tab 2: warm paper, with night blocks for the evening
# --------------------------------------------------------------------------- #

TRIP_STYLE = """
/* Tab 2: ivory paper + terracotta; graphite night reserved for the evenings. */
body.trip {
  --ink: #241f1c;
  --muted: #6b5f57;
  --faint: #7d6f66;
  --faint-strong: #74675e;
  --line: rgba(36, 31, 28, 0.12);
  --surface: #ffffff;
  --canvas: #fbf8f3;
  --wash: #f5efe7;
  --accent-bg: #f4e7e0;
  --accent-fg: #9c4a32;
  --night: #14161a;
  --night-ink: #f4efe7;
  --night-muted: #b9afa2;
  --gold: #c9a96a;
  background: var(--canvas);
  color: var(--ink);
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  padding: 64px 24px 110px;
}
body.trip .wrap { max-width: 880px; }
body.trip .topnav { margin-bottom: 44px; }
body.trip .back { margin-bottom: 28px; }
body.trip .foot { margin-top: 64px; }

/* ---------- hero ---------- */
.trip-hero { margin: 0 0 40px; padding-bottom: 38px; box-shadow: 0 1px 0 0 var(--line); }
.eyebrow {
  margin-bottom: 18px;
  font-size: 10.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent-fg);
}
.trip-hero h1 {
  margin: 0 0 18px;
  font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif;
  font-weight: 400;
  font-size: 64px;
  line-height: 1.02;
  letter-spacing: -0.02em;
}
.trip-hero h1 em { font-style: italic; color: var(--accent-fg); }
.trip-hero .lead {
  margin: 0;
  max-width: 600px;
  font-size: 16px;
  line-height: 1.62;
  color: var(--muted);
}
.trip-facts { display: flex; flex-wrap: wrap; gap: 34px; margin-top: 30px; }
.trip-facts div { display: flex; flex-direction: column; gap: 2px; }
.trip-facts b {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 27px;
  font-weight: 400;
  line-height: 1.1;
}
.trip-facts span {
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

/* ---------- letter ---------- */
.trip-letter {
  margin: 0 0 40px;
  padding: 30px 34px 28px;
  border-radius: 12px;
  background: var(--surface);
  box-shadow: inset 0 0 0 1px var(--line), 0 1px 0 rgba(36, 31, 28, 0.04);
}
.trip-letter .letter-body {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 19px;
  line-height: 1.72;
  color: var(--ink);
}
.trip-letter .letter-body p { margin: 0 0 14px; }
.trip-letter .letter-body p:last-child { margin-bottom: 0; }
.trip-letter .letter-body a { color: var(--accent-fg); }
.trip-letter .sign {
  margin-top: 20px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-style: italic;
  font-size: 18px;
  color: var(--muted);
}
.day-mood {
  margin: -4px 0 24px;
  max-width: 560px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-style: italic;
  font-size: 20px;
  line-height: 1.45;
  color: var(--muted);
}

/* ---------- day cards ---------- */
.days-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 18px;
}
.day-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 22px 22px 18px;
  border-radius: 10px;
  background: var(--surface);
  color: inherit;
  text-decoration: none;
  box-shadow: inset 0 0 0 1px var(--line), 0 1px 0 rgba(36, 31, 28, 0.04);
  transition: box-shadow .2s ease, transform .2s ease;
}
/* full-card link sits above the card, real links sit above the link */
.day-hit { position: absolute; inset: 0; z-index: 1; border-radius: inherit; }
.day-card .steps a, .day-card .excerpt a { position: relative; z-index: 2; }
.day-hit:focus-visible { outline: 2px solid var(--accent-fg); outline-offset: 3px; }
.day-card:hover {
  box-shadow: inset 0 0 0 1px var(--line), 0 12px 26px rgba(36, 31, 28, 0.11);
  transform: translateY(-2px);
}
.day-card .num {
  margin-bottom: 10px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--accent-fg);
}
.day-card h2 {
  margin: 0 0 8px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-weight: 400;
  font-size: 27px;
  line-height: 1.14;
  letter-spacing: -0.01em;
}
.day-card .excerpt {
  margin: 0 0 16px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-style: italic;
  font-size: 16px;
  line-height: 1.45;
  color: var(--muted);
}

/* ---------- slot lists ---------- */
.steps {
  list-style: none;
  margin: auto 0 0;
  padding: 14px 0 0;
  box-shadow: 0 -1px 0 0 var(--line);
}
.steps li.row { display: flex; gap: 12px; padding: 4px 0; font-size: 13px; color: var(--muted); }
.steps time {
  flex: none;
  min-width: 54px;
  padding-top: 2px;
  font-size: 11.5px;
  letter-spacing: 0.03em;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
}
.steps li.evening {
  display: block;
  margin: 10px -12px -4px;
  padding: 12px 14px;
  border-radius: 9px;
  background: var(--night);
}
.steps li.evening .row { display: flex; gap: 12px; padding: 3px 0; font-size: 13px; }
.steps li.evening time { color: var(--gold); }
.steps li.evening .row span { color: var(--night-ink); }
.steps li.evening .row span a { color: var(--gold); text-decoration: none; }
.steps li.alone {
  display: block;
  margin: 10px -12px -4px;
  padding: 12px 14px;
  border-radius: 9px;
  background: var(--wash);
  box-shadow: inset 0 0 0 1px var(--line);
}
.steps li.alone .row { display: flex; gap: 12px; padding: 3px 0; font-size: 13px; }
.steps li.alone time { color: var(--faint); }
.steps li.alone .row span {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-style: italic;
  font-size: 15px;
  color: var(--muted);
}
.steps li.alone .row span a { color: var(--accent-fg); text-decoration: none; }

/* ---------- day page ---------- */
.day-page .eyebrow { margin-bottom: 14px; }
.day-page h1 {
  margin: 0 0 14px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-weight: 400;
  font-size: 46px;
  line-height: 1.08;
  letter-spacing: -0.02em;
}
.day-page .badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 28px; }
.day-page .badges .badge a { color: inherit; text-decoration: none; }
.day-page .badges .badge a:hover { text-decoration: underline; }
.timeline { list-style: none; margin: 0 0 40px; padding: 0; }
.timeline li {
  display: flex;
  gap: 18px;
  padding: 15px 0;
  box-shadow: 0 1px 0 0 var(--line);
}
.timeline time {
  flex: none;
  width: 66px;
  padding-top: 2px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 17px;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
}
.timeline .what { font-size: 15.5px; line-height: 1.55; }
.timeline .what a { color: var(--accent-fg); text-decoration: none; }
.timeline .what a:hover { text-decoration: underline; }

.evening-block {
  margin: 0 0 40px;
  padding: 20px 24px 22px;
  border-radius: 12px;
  background: var(--night);
  color: var(--night-muted);
}
.evening-block h2 {
  margin: 0 0 12px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 13px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--gold);
}
.evening-block .row { display: flex; gap: 18px; padding: 7px 0; }
.evening-block time {
  flex: none;
  width: 66px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 17px;
  color: var(--gold);
  font-variant-numeric: tabular-nums;
}
.evening-block .row span { font-size: 15.5px; line-height: 1.5; color: var(--night-ink); }
.evening-block .row span a { color: var(--gold); text-decoration: none; }
.evening-block .row span a:hover { text-decoration: underline; }

.alone-block {
  margin: 0 0 40px;
  padding: 20px 24px 22px;
  border-radius: 12px;
  background: var(--wash);
  box-shadow: inset 0 0 0 1px var(--line);
  color: var(--muted);
}
.alone-block h2 {
  margin: 0 0 12px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 13px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--faint-strong);
}
.alone-block .row { display: flex; gap: 18px; padding: 7px 0; }
.alone-block time {
  flex: none;
  width: 66px;
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 17px;
  color: var(--faint-strong);
  font-variant-numeric: tabular-nums;
}
.alone-block .row span {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-style: italic;
  font-size: 18px;
  line-height: 1.5;
  color: var(--muted);
}
.alone-block .row span a { color: var(--accent-fg); text-decoration: none; }

.day-page .specs { margin-bottom: 40px; }
.day-page .specs > div { background: var(--surface); }
.day-page .prose { margin-bottom: 8px; }
.day-page .prose h2 {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-weight: 500;
  font-size: 26px;
  letter-spacing: -0.01em;
}
.day-nav {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-top: 44px;
  padding-top: 20px;
  box-shadow: 0 -1px 0 0 var(--line);
  font-size: 14px;
}
.day-nav a { color: var(--faint); text-decoration: none; }
.day-nav a:hover { color: var(--ink); }
.day-nav .next { margin-left: auto; text-align: right; }

@media (max-width: 640px) {
  body.trip { padding: 40px 18px 80px; }
  .trip-hero h1 { font-size: 40px; }
  .day-page h1 { font-size: 32px; }
  .timeline time, .evening-block time { width: 52px; font-size: 15px; }
  .timeline li, .evening-block .row { gap: 12px; }
}
""".strip()


# --------------------------------------------------------------------------- #
# document shell
# --------------------------------------------------------------------------- #

FONTS_GEIST = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Geist:wght@300;400;500;600&family=Geist+Mono:wght@400;500'
    '&display=swap" rel="stylesheet">'
)

FONTS_TRIP = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;1,400'
    '&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">'
)

NAV_ITEMS = (
    ("index.html", "Классные места", "places"),
    ("lenochka.html", "Леночка приезжает", "trip"),
)


def nav_html(depth: int, active: str) -> str:
    """Two-tab navigation shared by both sections."""
    prefix = "../" * depth
    links = []
    for href, label, key in NAV_ITEMS:
        cls = "topnav-link active" if key == active else "topnav-link"
        links.append('<a class="' + cls + '" href="' + prefix + href + '">' + label + "</a>")
    return (
        '<nav class="topnav">'
        '<a class="topnav-brand" href="' + prefix + 'index.html">Sightseeing</a>'
        + "".join(links) +
        "</nav>"
    )


def page(title: str, body: str, depth: int = 0, active: str = "places",
         css=("style.css",), fonts: str = FONTS_GEIST, body_class: str = "") -> str:
    """Wrap content in the shared document shell (nav + section styling)."""
    prefix = "../" * depth
    styles = "".join(
        '<link rel="stylesheet" href="' + prefix + "assets/" + name + '">'
        for name in css
    )
    cls = ' class="' + body_class + '"' if body_class else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>" + html.escape(title) + "</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        + fonts + "\n"
        + styles + "\n"
        "</head>\n<body" + cls + ">\n<div class=\"wrap\">\n"
        + nav_html(depth, active) + "\n"
        + body +
        "\n</div>\n</body>\n</html>\n"
    )


ICON_MAP = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>'
    '<circle cx="12" cy="10" r="3"/></svg>'
)

ICON_LINK = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
    '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
)

ICON_TICKET = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M3 9V7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a3 3 0 0 0 0 6v2'
    'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a3 3 0 0 0 0-6z"/>'
    '<line x1="13" y1="5" x2="13" y2="19"/></svg>'
)

CHIP_FIELDS = (
    ("site", "Сайт", ICON_LINK),
    ("maps", "Карта", ICON_MAP),
    ("tickets", "Билеты", ICON_TICKET),
)


def link_chips(meta) -> str:
    """Masked, clickable link pills -- never a raw URL on the page."""
    links = meta.get("links") or {}
    if not isinstance(links, dict):
        return ""
    chips = []
    for key, label, icon in CHIP_FIELDS:
        value = clean(links.get(key))
        if not value:
            continue
        chips.append(
            '<a class="chip" href="' + value + '" target="_blank" rel="noopener">'
            + icon + "<span>" + label + "</span></a>"
        )
    if not chips:
        return ""
    return '<div class="actions">' + "".join(chips) + "</div>"


def spec_rows(meta, fields) -> str:
    """Objective facts, as a flat grid of cards.

    Unknown values are omitted rather than shown as a placeholder -- an empty
    cell carries no information and only makes the page look unfinished.
    """
    cells = []
    for label, key in fields:
        value = clean(meta.get(key))
        if value is None:
            continue
        cells.append("<div><dt>" + label + "</dt><dd>" + value + "</dd></div>")
    if not cells:
        return ""
    return '<dl class="specs">' + "".join(cells) + "</dl>"


# --------------------------------------------------------------------------- #
# tab 1 -- places
# --------------------------------------------------------------------------- #

FACT_FIELDS = (
    ("Локация", "location"),
    ("Перелёт", "flight_cost"),
    ("Сезон", "best_season"),
    ("Стоимость", "estimated_cost"),
)


def card_html(place) -> str:
    meta = place["meta"]
    title = clean(meta.get("title")) or html.escape(place["stem"])
    category = clean(meta.get("category"))
    location = clean(meta.get("location"))
    priority = clean(meta.get("priority"))
    season = clean(meta.get("best_season"))
    text = excerpt(place["body"])

    bits = []
    if location:
        bits.append("<span>" + location + "</span>")
    if season:
        bits.append("<span>" + season + "</span>")
    if priority:
        cls = PRIORITY_CLASS.get(str(meta.get("priority", "")).lower(), "")
        bits.append('<span class="' + cls + '">' + priority + "</span>")

    badge = ('<span class="badge">' + category + "</span>") if category else ""
    para = ('<p class="excerpt">' + text + "</p>") if text else '<p class="excerpt"></p>'

    return (
        '<a class="card" href="places/' + place["slug"] + '.html">'
        '<div class="card-top"><h2>' + title + "</h2>" + badge + "</div>"
        + para +
        '<div class="meta">' + "".join(bits) + "</div>"
        "</a>"
    )


def detail_page(place) -> str:
    meta = place["meta"]
    title = clean(meta.get("title")) or html.escape(place["stem"])
    category = clean(meta.get("category"))
    priority = clean(meta.get("priority"))

    badges = ""
    status = clean(meta.get("status"))
    if status:
        badges += '<span class="badge badge-quiet">' + status + "</span>"
    if category:
        badges += '<span class="badge">' + category + "</span>"
    if priority:
        badges += '<span class="badge badge-quiet">' + priority + "</span>"

    body = (
        '<a class="back" href="../index.html">\u2190 Все места</a>'
        '<article class="detail">'
        "<h1>" + title + "</h1>"
        '<div class="badges">' + badges + "</div>"
        + link_chips(meta)
        + spec_rows(meta, FACT_FIELDS) +
        '<div class="prose">' + to_html(place["body"]) + "</div>"
        "</article>"
    )
    return page(title + " \u2014 Классные места", body, depth=1, active="places")


# --------------------------------------------------------------------------- #
# tab 2 -- the trip
# --------------------------------------------------------------------------- #

TRIP_FACT_FIELDS = (
    ("Во сколько", "time"),
    ("Адрес", "address"),
    ("Стоимость", "cost"),
    ("Бронь", "booking"),
)

TRIP_LEAD = (
    "Восемь дней, из которых я убрал всё лишнее — дорогу, суету и вопросы "
    "«а что дальше». Останутся город, три вечера и время, которое можно "
    "провести не спеша."
)


def load_slots(day, label) -> list:
    """Validate and normalise the 'slots' timeline of a day note."""
    items = day["meta"].get("slots") or []
    if not isinstance(items, list):
        raise NoteError("'slots' must be a list in " + label)
    out = []
    for item in items:
        if not isinstance(item, dict) or not raw(item.get("what")):
            raise NoteError("every slot needs a 'what' in " + label)
        period = raw(item.get("period") or "day").lower()
        if period not in ("day", "evening", "alone"):
            raise NoteError(
                "slot period must be day|evening|alone in " + label
                + " (got '" + period + "')"
            )
        out.append({
            "time": raw(item.get("time")),
            "what": raw(item.get("what")),
            "period": period,
        })
    return out


def group_slots(slots):
    """Split a timeline into day part, our evenings, and evenings without me."""
    day = [s for s in slots if s["period"] == "day"]
    evening = [s for s in slots if s["period"] == "evening"]
    alone = [s for s in slots if s["period"] == "alone"]
    return day, evening, alone


def slot_row(slot, tag_name: str = "li", cls: str = "") -> str:
    when = clean(slot["time"]) or "&nbsp;"
    attr = ' class="' + cls + '"' if cls else ""
    return (
        "<" + tag_name + attr + "><time>" + when + "</time>"
        '<span class="what">' + linkify(slot["what"]) + "</span></" + tag_name + ">"
    )


def evening_row(slot) -> str:
    when = clean(slot["time"]) or "&nbsp;"
    return (
        '<div class="row"><time>' + when + "</time>"
        '<span class="what">' + linkify(slot["what"]) + "</span></div>"
    )


def day_label(day) -> str:
    return (
        "День " + "%02d" % day["num"] + " \u00b7 "
        + day["weekday"].lower() + ", " + ru_date(day["date"])
    )


def day_card(day) -> str:
    text = (clean(day["meta"].get("mood")) or clean(day["meta"].get("lead"))
            or excerpt(day["body"], 120))
    para = ('<p class="excerpt">' + text + "</p>") if text else ""
    day_slots, evening, alone = group_slots(day["slots"])

    # The card is a div with a full-size overlay anchor: a real <a> wrapping the
    # whole card would make the inner wiki-links nested anchors, which the HTML
    # parser "fixes" by cloning the card anchor (the page then renders garbage).
    steps = "".join(slot_row(s, "li", "row") for s in day_slots)
    if evening:
        steps += '<li class="evening">' + "".join(evening_row(s) for s in evening) + "</li>"
    if alone:
        steps += '<li class="alone">' + "".join(evening_row(s) for s in alone) + "</li>"

    return (
        '<div class="day-card">'
        '<a class="day-hit" href="' + LINK_PREFIX + day["slug"] + '.html"'
        ' aria-label="' + html.escape(day_label(day)) + '"></a>'
        '<div class="num">' + day_label(day) + "</div>"
        "<h2>" + (clean(day["meta"].get("title")) or html.escape(day["stem"])) + "</h2>"
        + para +
        '<ul class="steps">' + steps + "</ul>"
        "</div>"
    )


def trip_hero(days, venues, lead: str = "") -> str:
    first, last = days[0]["date"], days[-1]["date"]
    if (first.year, first.month) == (last.year, last.month):
        span = ru_date(first) + " \u2014 " + ru_date(last) + " " + str(last.year)
    else:
        span = (ru_date(first) + " " + str(first.year) + " \u2014 "
                + ru_date(last) + " " + str(last.year))

    events = [v for v in venues if raw(v["meta"].get("category")).lower() in EVENT_CATEGORIES]
    hotels = [v for v in venues if raw(v["meta"].get("category")).lower() in HOTEL_CATEGORIES]

    facts = (
        "<div><b>" + str(len(days)) + "</b><span>"
        + plural_word(len(days), "день вместе", "дня вместе", "дней вместе") + "</span></div>"
        "<div><b>" + str(len(events)) + "</b><span>"
        + plural_word(len(events), "вечер в городе", "вечера в городе", "вечеров в городе")
        + "</span></div>"
        "<div><b>" + str(len(hotels)) + "</b><span>"
        + plural_word(len(hotels), "адрес в Москве", "адреса в Москве", "адресов в Москве")
        + "</span></div>"
    )

    text = lead or TRIP_LEAD
    return (
        '<header class="trip-hero">'
        '<div class="eyebrow">' + span + " \u00b7 Москва</div>"
        "<h1>Леночка <em>приезжает</em></h1>"
        '<p class="lead">' + linkify(text) + "</p>"
        '<div class="trip-facts">' + facts + "</div>"
        "</header>"
    )


def trip_index(days, venues, intro=None) -> str:
    lead = raw((intro or {}).get("meta", {}).get("lead"))
    letter = ""
    if intro is not None:
        sign = raw(intro["meta"].get("signature"))
        letter = (
            '<section class="trip-letter">'
            '<div class="letter-body">' + to_html(intro["body"]) + "</div>"
            + ('<div class="sign">' + html.escape(sign) + "</div>" if sign else "")
            + "</section>"
        )
    cards = "".join(day_card(d) for d in days)
    body = (
        trip_hero(days, venues, lead) + letter +
        '<div class="days-grid">' + cards + "</div>" +
        '<footer class="foot">Собрано для Леночки \u00b7 ноябрь 2026 '
        "\u00b7 всё, что меняется, меняется здесь же</footer>"
    )
    return page("Леночка приезжает \u2014 Москва, ноябрь", body, depth=0, active="trip",
                css=("style.css", "trip.css"), fonts=FONTS_TRIP, body_class="trip")


def trip_place_page(venue) -> str:
    meta = dict(venue["meta"])
    title = clean(meta.get("title")) or html.escape(venue["stem"])
    category = clean(meta.get("category"))
    status = clean(meta.get("status"))

    badges = ""
    if status:
        badges += '<span class="badge badge-quiet">' + status + "</span>"
    if category:
        badges += '<span class="badge">' + category + "</span>"

    address = raw(meta.get("address"))
    links = meta.get("links") if isinstance(meta.get("links"), dict) else {}
    if address and not links.get("maps"):
        links = dict(links)
        links["maps"] = maps_url(address)
        meta["links"] = links

    body = (
        '<a class="back" href="../lenochka.html">\u2190 Все дни</a>'
        '<article class="day-page">'
        "<h1>" + title + "</h1>"
        '<div class="badges">' + badges + "</div>"
        + link_chips(meta)
        + spec_rows(meta, TRIP_FACT_FIELDS) +
        '<div class="prose">' + to_html(venue["body"]) + "</div>"
        "</article>"
    )
    return page(title + " \u2014 Леночка приезжает", body, depth=1, active="trip",
                css=("style.css", "trip.css"), fonts=FONTS_TRIP, body_class="trip")


def trip_day_page(day, total) -> str:
    day_slots, evening, alone = group_slots(day["slots"])
    meta = day["meta"]

    badges = ""
    if raw(meta.get("hotel")):
        badges += '<span class="badge">' + linkify(raw(meta.get("hotel"))) + "</span>"

    parts = ['<article class="day-page">']
    parts.append('<div class="eyebrow">' + day_label(day) + "</div>")
    parts.append("<h1>" + (clean(meta.get("title")) or html.escape(day["stem"])) + "</h1>")
    if raw(meta.get("mood")):
        parts.append('<p class="day-mood">' + linkify(raw(meta.get("mood"))) + "</p>")
    parts.append('<div class="badges">' + badges + "</div>")

    facts = []
    if raw(meta.get("time")):
        facts.append(("Когда", raw(meta.get("time"))))
    if raw(meta.get("hotel")):
        facts.append(("Гостиница", raw(meta.get("hotel")).strip("[]")))
    if facts:
        cells = "".join(
            "<div><dt>" + label + "</dt><dd>" + html.escape(value) + "</dd></div>"
            for label, value in facts
        )
        parts.append('<dl class="specs">' + cells + "</dl>")

    if day_slots:
        parts.append('<ul class="timeline">')
        parts.append("".join(slot_row(s, "li") for s in day_slots))
        parts.append("</ul>")

    if evening:
        parts.append('<div class="evening-block"><h2>Вечер</h2>')
        parts.append("".join(evening_row(s) for s in evening))
        parts.append("</div>")

    if alone:
        parts.append('<div class="alone-block"><h2>Вечер без меня</h2>')
        parts.append("".join(evening_row(s) for s in alone))
        parts.append("</div>")

    body_html = to_html(day["body"])
    if body_html.strip():
        parts.append('<div class="prose">' + body_html + "</div>")

    prev_link = ""
    if day["num"] > 1:
        prev = day["prev"]
        prev_link = ('<a href="' + prev["slug"] + '.html">\u2190 День '
                     + "%02d" % prev["num"] + "</a>")
    next_link = ""
    if day["num"] < total:
        nxt = day["next"]
        next_link = ('<a class="next" href="' + nxt["slug"] + '.html">День '
                     + "%02d" % nxt["num"] + " \u2192</a>")
    parts.append('<div class="day-nav">' + prev_link + next_link + "</div>")
    parts.append("</article>")

    return page(day_label(day) + " \u2014 Леночка приезжает", "".join(parts),
                depth=1, active="trip",
                css=("style.css", "trip.css"), fonts=FONTS_TRIP, body_class="trip")


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def load_places():
    """Parse every published note of tab 1."""
    if not VAULT_PLACES.is_dir():
        raise NoteError("Vault not found: " + str(VAULT_PLACES))
    places = []
    skipped = []
    for note in sorted(VAULT_PLACES.glob("*.md")):
        parsed = read_note(note)
        if parsed is None:
            skipped.append(note.name)
            continue
        parsed["slug"] = slugify(raw(parsed["meta"].get("slug")) or parsed["stem"])
        places.append(parsed)
    return places, skipped


def load_trip():
    """Parse days and venues of tab 2, days in calendar order."""
    for folder in (TRIP_DAYS, TRIP_PLACES):
        if not folder.is_dir():
            raise NoteError("Trip folder not found: " + str(folder))

    venues = []
    for note in sorted(TRIP_PLACES.glob("*.md")):
        parsed = read_note(note)
        if parsed is None:
            continue
        parsed["slug"] = slugify(raw(parsed["meta"].get("slug")) or parsed["stem"])
        venues.append(parsed)

    days = []
    for note in sorted(TRIP_DAYS.glob("*.md")):
        parsed = read_note(note)
        if parsed is None:
            continue
        when = as_date(parsed["meta"].get("date"))
        if when is None:
            raise NoteError("day note without a valid 'date': " + note.name)
        parsed["date"] = when
        parsed["weekday"] = WEEKDAYS[when.weekday()]
        parsed["slots"] = load_slots(parsed, note.name)
        days.append(parsed)

    days.sort(key=lambda d: d["date"])
    seen = set()
    for index, day in enumerate(days, start=1):
        if day["date"] in seen:
            raise NoteError("two day notes for " + str(day["date"]))
        seen.add(day["date"])
        day["num"] = index
        day["slug"] = raw(day["meta"].get("slug")) or "den-%02d" % index

    for index, day in enumerate(days):
        day["prev"] = days[index - 1] if index > 0 else None
        day["next"] = days[index + 1] if index + 1 < len(days) else None

    return days, venues


def load_intro():
    """Optional Intro.md in the trip project: hero lead + the letter on tab 2."""
    path = VAULT_TRIP / "Intro.md"
    if not path.is_file():
        return None
    return read_note(path)


def assign_wiki_links(entries) -> None:
    """note stem and title -> published slug, for wiki-link resolution."""
    WIKI_LINKS.clear()
    for entry in entries:
        WIKI_LINKS[entry["stem"]] = entry["slug"]
        title = entry["meta"].get("title")
        if title:
            WIKI_LINKS[str(title).strip()] = entry["slug"]


def dedupe_slugs(entries) -> None:
    """Guard against two notes producing the same page path."""
    seen = {}
    for entry in entries:
        base = entry["slug"]
        if base in seen:
            seen[base] += 1
            entry["slug"] = base + "-" + str(seen[base])
        else:
            seen[base] = 1


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    # Parse and validate EVERYTHING before touching the output directory, so a
    # broken note aborts the build instead of silently dropping content from
    # the published site.
    try:
        places, skipped = load_places()
        days, venues = load_trip()
    except NoteError as exc:
        print("BUILD ABORTED -- nothing was written.")
        print("  ! " + str(exc))
        return 2
    intro = load_intro()

    if not places:
        print("BUILD ABORTED -- no published places found.")
        return 2
    if not days:
        print("BUILD ABORTED -- no published trip days found.")
        return 2

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "places").mkdir(parents=True)
    (OUT / "lenochka").mkdir(parents=True)
    (OUT / "assets").mkdir(parents=True)

    (OUT / "assets" / "style.css").write_text(STYLE, encoding="utf-8")
    (OUT / "assets" / "trip.css").write_text(TRIP_STYLE, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    # ---- tab 1: places -------------------------------------------------- #
    dedupe_slugs(places)
    assign_wiki_links(places)
    set_prefix("")

    order = {"must visit": 0, "nice to have": 1}
    places.sort(key=lambda p: (
        order.get(str(p["meta"].get("priority", "")).lower(), 2),
        str(p["meta"].get("title") or p["stem"]).lower(),
    ))

    cards = "\n".join(card_html(p) for p in places)
    masthead = (
        '<header class="masthead">'
        "<h1>\U0001f5fa\ufe0f Классные места</h1>"
        "<p>Курируемый список направлений для будущих путешествий</p>"
        '<span class="count">' + str(len(places)) + " " + plural(len(places)) + "</span>"
        "</header>"
    )
    index_body = (
        masthead +
        '<div class="grid">' + cards + "</div>" +
        '<footer class="foot">Сгенерировано из Obsidian \u00b7 только заметки с тегом #public</footer>'
    )
    (OUT / "index.html").write_text(page("Классные места", index_body), encoding="utf-8")

    for place in places:
        target = OUT / "places" / (place["slug"] + ".html")
        target.write_text(detail_page(place), encoding="utf-8")

    # ---- tab 2: the trip ------------------------------------------------- #
    dedupe_slugs(days + venues)
    assign_wiki_links(days + venues)

    # on lenochka.html the day/venue pages live one folder down
    set_prefix("lenochka/")
    (OUT / "lenochka.html").write_text(trip_index(days, venues, intro), encoding="utf-8")
    set_prefix("")

    for venue in venues:
        target = OUT / "lenochka" / (venue["slug"] + ".html")
        target.write_text(trip_place_page(venue), encoding="utf-8")

    for day in days:
        target = OUT / "lenochka" / (day["slug"] + ".html")
        target.write_text(trip_day_page(day, len(days)), encoding="utf-8")

    print("Tab 1 -- places: " + str(len(places)))
    for place in places:
        print("  - " + place["stem"] + "  ->  places/" + place["slug"] + ".html")
    if skipped:
        print("  not published (no #public tag): " + ", ".join(skipped))
    print("Tab 2 -- trip: " + str(len(days)) + " day(s), " + str(len(venues)) + " venue(s)")
    for day in days:
        print("  - " + day_label(day) + "  ->  lenochka/" + day["slug"] + ".html")
    print("Output: " + str(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
