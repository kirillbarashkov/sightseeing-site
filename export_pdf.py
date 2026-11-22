#!/usr/bin/env python3
"""Печатает страницы сайта в PDF: два файла рядом с сайтом, чтобы их можно было
сохранить и читать, если сайт погасят.

Порядок: build.py -> export_pdf.py -> build.py (второй прогон подхватывает PDF
и ставит ссылки в шапке). PDF лежит в pdf/ в репозитории, не в site_build:
сборка стирает выходную папку.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "site_build"
PDF = ROOT / "pdf"
TARGETS = [("lenochka.html", "lenochka.pdf"), ("kak-eto-bylo.html", "kak-eto-bylo.pdf")]

CHROME_CANDIDATES = [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]


def chrome() -> str | None:
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    return shutil.which("chrome") or shutil.which("chromium")


def export(binary: str, html: Path, out: Path) -> bool:
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
        print("не напечаталось: " + html.name + " | код " + str(r.returncode), flush=True)
        print((r.stderr or "")[-400:], flush=True)
        return False
    print("pdf: " + out.name + " (" + f"{out.stat().st_size / 1e6:.2f}" + " МБ)", flush=True)
    return True


def main() -> int:
    binary = chrome()
    if not binary:
        print("не найден Chrome/Edge", flush=True)
        return 1
    if not BUILD.is_dir():
        print("нет site_build: сначала python build.py", flush=True)
        return 1
    made, skipped = 0, []
    for name, pdf_name in TARGETS:
        html = BUILD / name
        if not html.is_file():
            skipped.append(name)
            continue
        if export(binary, html, PDF / pdf_name):
            made += 1
    if skipped:
        print("пропущено (страница не собрана): " + ", ".join(skipped), flush=True)
    print("готово: " + str(made) + " из " + str(len(TARGETS)), flush=True)
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
