#!/usr/bin/env python3
"""Печатает страницы сайта в PDF и кладёт их в хранилище Obsidian.

Куда: 02-Projects/03-Lenochka-coming/PDF/. Файл должен остаться, даже если сайт
погасят, поэтому он живёт рядом с исходниками, а не в сборке.

PDF — не скриншот главной: в один документ складываются и вложенные страницы
(дни, места), а ссылки переписываются на внутренние якоря, чтобы в PDF они
оставались кликабельными.

Вызывается из build.py автоматически; отдельный запуск — пересобрать без сайта.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "site_build"
VAULT_PDF = Path(r"D:/DataBases/mstr_obs_git/02-Projects/03-Lenochka-coming/PDF")

TARGETS = [
    ("lenochka.html", "Леночка приезжает.pdf"),
    ("kak-eto-bylo.html", "Как это было.pdf"),
]

CHROME_CANDIDATES = [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]

WRAP_OPEN = '<div class="wrap">'
BUNDLE_CSS = """
<style>
  .pdf-section { break-before: page; page-break-before: always; }
  .pdf-section.first { break-before: auto; page-break-before: auto; }
  .pdf-section .topnav { display: none; }
  .pdf-day-head { margin: 0 0 18px; font-family: 'Geist Mono', ui-monospace, monospace;
                  font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
                  color: #8a7a6d; }
  .pdf-back { margin: 26px 0 0; font-size: 13px; color: #8a7a6d; }
  @media print {
    .trip-hero { margin-bottom: 20px; }
    .trip-hero h1 { font-size: 34px; letter-spacing: -1.2px; }
    .trip-hero .lead { font-size: 15px; }
    .trip-facts { margin-top: 12px; }
    .trip-letter { margin-top: 18px; padding: 16px 18px; break-inside: auto; }
    .trip-letter .letter-body { font-size: 13.2px; line-height: 1.55; }
    .trip-letter .letter-body p { margin: 0 0 8px; }
    .days-grid { break-before: page; page-break-before: always; }
  }
</style>
"""


def chrome():
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    return shutil.which("chrome") or shutil.which("chromium")


def _wrap_content(markup: str) -> str:
    """Внутренности .wrap без навигации и подвала."""
    if WRAP_OPEN in markup:
        markup = markup.split(WRAP_OPEN, 1)[1]
    markup = markup.rsplit("</div>", 2)[0]
    markup = re.sub(r'<nav class="topnav">.*?</nav>', "", markup, flags=re.S)
    markup = re.sub(r'<footer class="foot">.*?</footer>', "", markup, flags=re.S)
    return markup.strip()


def _anchor(name: str) -> str:
    return "t-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def bundle(main_html: Path, children: list[Path]) -> str:
    """Один документ: главная страница + вложенные, со ссылками на якоря."""
    mapping = {}
    for child in children:
        key = child.stem
        mapping[key] = _anchor(key)

    def fix(markup: str) -> str:
        def repl(match):
            href = match.group(1)
            base = Path(href.split("#")[0]).stem if href else ""
            if base in mapping:
                return 'href="#' + mapping[base] + '"'
            if href.endswith((".html", "/")) or href in ("index.html", "lenochka.html"):
                return 'href="#t-top"'
            return match.group(0)

        markup = re.sub(r'href="([^"]+\.html[^"]*)"', repl, markup)
        return markup

    parts = ['<section class="pdf-section first" id="t-top">' + fix(_wrap_content(main_html.read_text(encoding="utf-8"))) + "</section>"]
    for child in children:
        body = fix(_wrap_content(child.read_text(encoding="utf-8")))
        parts.append(
            '<section class="pdf-section" id="' + mapping[child.stem] + '">'
            + '<p class="pdf-back"><a href="#t-top">↑ к оглавлению</a></p>'
            + body
            + "</section>"
        )

    head = main_html.read_text(encoding="utf-8")
    head = head.split("</head>", 1)[0] + BUNDLE_CSS + "</head>\n<body class=\"trip\">\n<div class=\"wrap\">"
    doc = head + "\n".join(parts) + "\n</div>\n</body>\n</html>\n"
    return absolutize(doc)


REL_RE = re.compile(r'(src|href)="((?!https?:|#|file:|mailto:|data:)[^"]+)"')


def absolutize(markup: str) -> str:
    """Сборка печатается из _print/, поэтому относительные пути стали бы битыми."""
    base = BUILD.as_uri() + "/"

    def repl(match):
        attr, value = match.group(1), match.group(2)
        return attr + '="' + base + value.lstrip("./") + '"'

    return REL_RE.sub(repl, markup)


def children_for(main_html: Path) -> list[Path]:
    """Дни и места, на которые ссылается главная страница."""
    kids = []
    markup = main_html.read_text(encoding="utf-8")
    for href in re.findall(r'href="((?:\.\./)?[^"]+\.html)"', markup):
        base = Path(href).name
        if base == main_html.name or base in ("index.html",):
            continue
        candidate = BUILD / "lenochka" / base
        if candidate.is_file() and candidate not in kids:
            kids.append(candidate)
    days = sorted(p for p in kids if p.name.startswith("den-"))
    venues = sorted(p for p in kids if not p.name.startswith("den-"))
    return days + venues


def export_one(binary, html, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    cmd = [
        binary,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=25000",
        "--print-to-pdf=" + str(out).replace("\\", "/"),
        html.resolve().as_uri(),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.exists():
        print("  ! pdf не напечатался: " + html.name + " (код " + str(r.returncode) + ")")
        print("    " + (r.stderr or "")[-300:])
        return False
    print("  pdf: " + out.name + " (" + ("%.2f" % (out.stat().st_size / 1e6)) + " МБ)")
    return True


def export_all(build_dir=BUILD):
    binary = chrome()
    if not binary:
        print("  ! не найден Chrome/Edge — PDF пропущен")
        return 0
    stage = build_dir / "_print"
    made = 0
    for name, pdf_name in TARGETS:
        main_html = build_dir / name
        if not main_html.is_file():
            continue
        kids = children_for(main_html)
        stage.mkdir(exist_ok=True)
        bundled = stage / (Path(name).stem + "-print.html")
        bundled.write_text(bundle(main_html, kids), encoding="utf-8")
        print("  разделов в PDF: " + str(1 + len(kids)))
        if export_one(binary, bundled, VAULT_PDF / pdf_name):
            made += 1
    return made


def main():
    if not BUILD.is_dir():
        print("нет site_build: сначала python build.py", flush=True)
        return 1
    return 0 if export_all() else 1


if __name__ == "__main__":
    sys.exit(main())
