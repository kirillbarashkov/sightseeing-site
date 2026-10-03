#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sightseeing site builder.

Reads notes tagged #public from the Obsidian vault and produces a static
site in ./site_build:

    index.html              -- grid of cards, one per place
    places/<slug>.html      -- full detail page per place
    assets/style.css        -- Vercel-style design system
    .nojekyll               -- stop GitHub Pages from running Jekyll

Usage:  python build.py
"""

from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")

try:
    import markdown as md
except ImportError:
    sys.exit("Missing dependency: pip install markdown")


VAULT_PLACES = Path(r"D:\DataBases\mstr_obs_git\02-Projects\02-Sightseeing\Places")
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


WIKI_LINKS = {}  # note stem -> slug, filled in main() before rendering


def _wiki_link(match):
    """Obsidian [[Note]] / [[Note|Alias]] -> anchor to the published page.

    Links to notes that are not published degrade to plain text, so the site
    never shows literal double brackets or a dead link.
    """
    target = match.group(1).strip()
    alias = match.group(2)
    label = (alias or target).strip()
    slug = WIKI_LINKS.get(target)
    if slug is None:
        return label
    return '<a href="' + slug + '.html">' + html.escape(label) + "</a>"


def to_html(body: str) -> str:
    """Markdown body -> HTML, with Obsidian checkboxes and callouts handled."""
    # drop the note's own leading H1 -- the page already renders the title
    body = re.sub(r"^\s*#\s+[^\n]*\n?", "", body, count=1)
    # Obsidian wiki-links -> real anchors (or plain text when not published)
    body = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", _wiki_link, body)
    # Obsidian callouts: "> [!info] Title" -> "> **INFO Title**"
    body = re.sub(r"^>\s*\[!(\w+)\]\s*(.*)$", _callout, body, flags=re.M)
    # strip empty template fields like "- Транспорт: "
    body = re.sub(r"^\s*[-*]\s+[^\n:]+:\s*$\n?", "", body, flags=re.M)
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
    for raw in body.splitlines():
        line = raw.strip()
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


# --------------------------------------------------------------------------- #
# styling
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
  margin-bottom: 40px;
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
}
""".strip()


def page(title: str, body: str, depth: int = 0) -> str:
    """Wrap content in the shared document shell."""
    prefix = "../" * depth
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>" + html.escape(title) + "</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?'
        'family=Geist:wght@300;400;500;600&family=Geist+Mono:wght@400;500'
        '&display=swap" rel="stylesheet">\n'
        '<link rel="stylesheet" href="' + prefix + 'assets/style.css">\n'
        "</head>\n<body>\n<div class=\"wrap\">\n"
        + body +
        "\n</div>\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------- #
# page builders
# --------------------------------------------------------------------------- #

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


FACT_FIELDS = (
    ("Локация", "location"),
    ("Перелёт", "flight_cost"),
    ("Сезон", "best_season"),
    ("Стоимость", "estimated_cost"),
)


def spec_rows(meta) -> str:
    """Objective facts about the place, as a flat grid of cards.

    Unknown values are omitted rather than shown as a placeholder -- an empty
    cell carries no information and only makes the page look unfinished.
    """
    cells = []
    for label, key in FACT_FIELDS:
        value = clean(meta.get(key))
        if value is None:
            continue
        cells.append("<div><dt>" + label + "</dt><dd>" + value + "</dd></div>")
    if not cells:
        return ""
    return '<dl class="specs">' + "".join(cells) + "</dl>"


def link_chips(meta) -> str:
    """Masked, clickable link pills -- never a raw URL on the page."""
    links = meta.get("links") or {}
    if not isinstance(links, dict):
        return ""
    chips = []
    site = clean(links.get("site"))
    maps = clean(links.get("maps"))
    if site:
        chips.append(
            '<a class="chip" href="' + site + '" target="_blank" rel="noopener">'
            + ICON_LINK + "<span>Сайт</span></a>"
        )
    if maps:
        chips.append(
            '<a class="chip" href="' + maps + '" target="_blank" rel="noopener">'
            + ICON_MAP + "<span>Карта</span></a>"
        )
    if not chips:
        return ""
    return '<div class="actions">' + "".join(chips) + "</div>"

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
        + spec_rows(meta) +
        '<div class="prose">' + to_html(place["body"]) + "</div>"
        "</article>"
    )
    return page(title + " \u2014 Классные места", body, depth=1)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    if not VAULT_PLACES.is_dir():
        print("Vault not found: " + str(VAULT_PLACES))
        return 1

    # Parse and validate EVERYTHING before touching the output directory, so a
    # broken note aborts the build instead of silently dropping a place from
    # the published site.
    places = []
    skipped = []
    errors = []
    for note in sorted(VAULT_PLACES.glob("*.md")):
        try:
            parsed = read_note(note)
        except NoteError as exc:
            errors.append(str(exc))
            continue
        if parsed is None:
            skipped.append(note.name)
            continue
        parsed["slug"] = slugify(parsed["stem"])
        places.append(parsed)

    if errors:
        print("BUILD ABORTED -- nothing was written. Fix these notes:")
        for message in errors:
            print("  ! " + message)
        return 2

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "places").mkdir(parents=True)
    (OUT / "assets").mkdir(parents=True)

    (OUT / "assets" / "style.css").write_text(STYLE, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    # guard against slug collisions
    seen = {}
    for place in places:
        base = place["slug"]
        if base in seen:
            seen[base] += 1
            place["slug"] = base + "-" + str(seen[base])
        else:
            seen[base] = 1

    # wiki-link targets: note stem and title -> published slug
    WIKI_LINKS.clear()
    for place in places:
        WIKI_LINKS[place["stem"]] = place["slug"]
        title = place["meta"].get("title")
        if title:
            WIKI_LINKS[str(title).strip()] = place["slug"]

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

    print("Built " + str(len(places)) + " place(s):")
    for place in places:
        print("  - " + place["stem"] + "  ->  places/" + place["slug"] + ".html")
    if skipped:
        print("Not published (no #public tag): " + ", ".join(skipped))
    print("Output: " + str(OUT))
    return 0


def plural(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "место"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "места"
    return "мест"


if __name__ == "__main__":
    raise SystemExit(main())
