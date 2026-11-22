#!/usr/bin/env python3
"""Печатает страницы сайта в PDF и кладёт их в хранилище Obsidian.

Куда: 02-Projects/03-Lenochka-coming/PDF/ — рядом с исходниками, чтобы файл
остался, даже если сайт погасят. Ссылок на PDF на сайте нет намеренно.

Вызывается из build.py автоматически; отдельный запуск — пересобрать без сайта.
"""
from __future__ import annotations

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


def chrome():
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    return shutil.which("chrome") or shutil.which("chromium")


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
        "--virtual-time-budget=20000",
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
    """Печатает всё, что собралось. Возвращает число готовых файлов."""
    binary = chrome()
    if not binary:
        print("  ! не найден Chrome/Edge — PDF пропущен")
        return 0
    made = 0
    for name, pdf_name in TARGETS:
        html = build_dir / name
        if not html.is_file():
            continue
        if export_one(binary, html, VAULT_PDF / pdf_name):
            made += 1
    return made


def main():
    if not BUILD.is_dir():
        print("нет site_build: сначала python build.py", flush=True)
        return 1
    return 0 if export_all() else 1


if __name__ == "__main__":
    sys.exit(main())
