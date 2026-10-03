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


def read_note(path: Path):
    """Parse one note. Returns a dict for #public notes, else None."""
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        print("  ! YAML error in %s: %s" % (path.name, exc))
        return None

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


def to_html(body: str) -> str:
    """Markdown body -> HTML, with Obsidian checkboxes turned into glyphs."""
    # drop the note's own leading H1 -- the page already renders the title
    body = re.sub(r"^\s*#\s+[^\n]*\n?", "", body, count=1)
    # strip empty template fields like "- Транспорт: "
    body = re.sub(r"^\s*[-*]\s+[^\n:]+:\s*$\n?", "", body, flags=re.M)
    body = re.sub(r"^(\s*)- \[ \]", lambda m: m.group(1) + "- \u2610", body, flags=re.M)
    body = re.sub(r"^(\s*)- \[[xX]\]", lambda m: m.group(1) + "- \u2611", body, flags=re.M)
    return md.markdown(body, extensions=["extra", "sane_lists", "nl2br"])


def excerpt(body: str, limit: int = 160) -> str:
    """First real paragraph of the note body, as plain text."""
    text = re.sub(r"^#+ .*$", "", body, flags=re.M)          # drop headings
    text = re.sub(r"^\s*- \[.\]\s*", "", text, flags=re.M)    # drop checklist
    text = re.sub(r"^[#>*\-\s]+", "", text, flags=re.M)
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
.detail .badges { display: flex; gap: 8px; margin-bottom: 40px; }
.specs {
  margin: 0 0 48px;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1px;
  background: var(--line);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--line) 0 0 0 1px;
}
.specs div { padding: 14px 18px; background: var(--surface); }
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


def spec_rows(meta) -> str:
    rows = []

    def add(label, value, is_link=False):
        if value is None:
            return
        if is_link:
            cell = '<a href="' + value + '" target="_blank" rel="noopener">' + value + "</a>"
        else:
            cell = value
        rows.append("<div><dt>" + label + "</dt><dd>" + cell + "</dd></div>")

    add("Статус", clean(meta.get("status")))
    add("Приоритет", clean(meta.get("priority")))
    add("Категория", clean(meta.get("category")))
    add("Локация", clean(meta.get("location")))
    add("Сезон", clean(meta.get("best_season")))
    add("Стоимость", clean(meta.get("estimated_cost")))

    links = meta.get("links") or {}
    if isinstance(links, dict):
        site = links.get("site")
        maps = links.get("maps")
        if site:
            add("Сайт", html.escape(str(site).strip()), is_link=True)
        if maps:
            add("Карта", html.escape(str(maps).strip()), is_link=True)

    if not rows:
        return ""
    return '<dl class="specs">' + "".join(rows) + "</dl>"


def detail_page(place) -> str:
    meta = place["meta"]
    title = clean(meta.get("title")) or html.escape(place["stem"])
    category = clean(meta.get("category"))
    priority = clean(meta.get("priority"))

    badges = ""
    if category:
        badges += '<span class="badge">' + category + "</span>"
    if priority:
        cls = PRIORITY_CLASS.get(str(meta.get("priority", "")).lower(), "")
        badges += '<span class="badge" style="background:#fafafa;color:#4d4d4d">' + priority + "</span>"

    body = (
        '<a class="back" href="../index.html">\u2190 Все места</a>'
        '<article class="detail">'
        "<h1>" + title + "</h1>"
        '<div class="badges">' + badges + "</div>"
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

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "places").mkdir(parents=True)
    (OUT / "assets").mkdir(parents=True)

    (OUT / "assets" / "style.css").write_text(STYLE, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    places = []
    skipped = []
    for note in sorted(VAULT_PLACES.glob("*.md")):
        parsed = read_note(note)
        if parsed is None:
            skipped.append(note.name)
            continue
        parsed["slug"] = slugify(parsed["stem"])
        places.append(parsed)

    # guard against slug collisions
    seen = {}
    for place in places:
        base = place["slug"]
        if base in seen:
            seen[base] += 1
            place["slug"] = base + "-" + str(seen[base])
        else:
            seen[base] = 1

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
        print("Skipped (not #public or invalid): " + ", ".join(skipped))
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
