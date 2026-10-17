#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vault linter for the Sightseeing site.

Checks both projects before a build and prints EVERYTHING it finds, instead of
stopping at the first problem like the builder does.

    python check.py            # errors + warnings, exit 1 on errors
    python check.py --strict    # warnings fail too
    python check.py --quiet     # only the summary line

Rules:
  ошибки   -- сборка остановится: кривой YAML, нет даты, кривая таблица
              расписания, отсутствует файл картинки, ссылка не http(s)
  предупреждения -- собрать можно, но что-то поедет: заметка без #public
              (на сайт не попадёт), ссылка на непубличную заметку (на сайте
              станет обычным текстом), ссылка на несуществующую заметку,
              картинка без подписи, место, которое не упоминает ни один день
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

import build as B

PLACE_REQUIRED = ("category", "location", "priority")
# categories where "status" (куплено/забронировано) actually means something
NEEDS_STATUS = {"отель", "гостиница", "ресторан", "концерт", "театр", "круиз", "спектакль"}

errors: list = []
warnings: list = []
notes_seen = 0


def err(note: str, message: str) -> None:
    errors.append((note, message))


def warn(note: str, message: str) -> None:
    warnings.append((note, message))


def read_frontmatter(path: Path):
    """-> (meta or None, body, yaml_error or None)."""
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        return None, text, "нет frontmatter (заметка начинается не с ---)"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text, "frontmatter не закрыт строкой ---"
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        return None, parts[2], str(exc).replace("\n", " ")
    if not isinstance(meta, dict):
        return None, parts[2], "frontmatter не является набором полей"
    return meta, parts[2], None


def tags_of(meta) -> list:
    tags = (meta or {}).get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    return [str(t).strip().lstrip("#") for t in tags]


def note_index():
    """stem -> (path, is_public) for every note in both projects."""
    index = {}
    for folder in (B.VAULT_PLACES, B.TRIP_DAYS, B.TRIP_PLACES):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            meta, _, _ = read_frontmatter(path)
            index[path.stem] = (path, "public" in tags_of(meta))
    return index


def wiki_targets(text: str) -> list:
    return [m.group(1).strip() for m in B.WIKI_RE.finditer(text)]


def check_links(note: str, text: str, index: dict, label: str = "") -> None:
    for target in wiki_targets(text):
        if target not in index:
            warn(note, "ссылка [[" + target + "]] " + label + ": такой заметки нет в проекте")
        elif not index[target][1]:
            warn(note, "ссылка [[" + target + "]] " + label
                 + ": заметка без #public, на сайте станет обычным текстом")


def check_image(note: str, meta: dict) -> None:
    image = str(meta.get("image") or "").strip()
    if not image:
        return
    if not image.startswith(("http://", "https://")):
        if not (B.VAULT_TRIP / image).is_file():
            err(note, "картинка не найдена: " + image + " (путь считается от корня проекта)")
    if not str(meta.get("image_credit") or "").strip():
        warn(note, "есть картинка, но нет image_credit — на сайте подпись будет пустой")
    elif not str(meta.get("image_credit_url") or "").strip():
        warn(note, "есть подпись, но нет image_credit_url — нельзя проверить источник")


def check_places() -> None:
    global notes_seen
    for path in sorted(B.VAULT_PLACES.glob("*.md")):
        notes_seen += 1
        rel = "Places/" + path.name
        meta, body, bad = read_frontmatter(path)
        if bad:
            err(rel, bad)
            continue
        if "public" not in tags_of(meta):
            warn(rel, "нет тега #public — на сайт не попадёт")
        for field in PLACE_REQUIRED:
            value = str(meta.get(field) or "").strip()
            if not value:
                warn(rel, "пустое обязательное поле '" + field + "'")
        links = meta.get("links") or {}
        if links and not isinstance(links, dict):
            err(rel, "links должен быть словарём site/maps")
        for key, url in (links or {}).items():
            if not str(url).startswith(("http://", "https://")):
                err(rel, "ссылка '" + str(key) + "' не начинается с http(s)")
        check_links(rel, body, INDEX)


def check_days() -> None:
    global notes_seen
    dates = {}
    for path in sorted(B.TRIP_DAYS.glob("*.md")):
        notes_seen += 1
        rel = "Days/" + path.name
        meta, body, bad = read_frontmatter(path)
        if bad:
            err(rel, bad)
            continue
        if "public" not in tags_of(meta):
            warn(rel, "нет тега #public — на сайт не попадёт")
            continue
        when = B.as_date(meta.get("date"))
        if when is None:
            err(rel, "нет или не разобрана дата 'date'")
        elif when in dates:
            err(rel, "та же дата, что и в " + dates[when])
        else:
            dates[when] = path.name
        if meta.get("slots"):
            err(rel, "slots в шапке — расписание должно быть таблицей в разделе '"
                + B.SCHEDULE_HEADING + "'")
        try:
            slots = B.parse_schedule(body, path.name)
        except B.NoteError as exc:
            err(rel, str(exc))
            slots = []
        if not slots:
            warn(rel, "расписание пустое")
        if not str(meta.get("mood") or "").strip():
            warn(rel, "нет 'mood' — карточка дня останется без строки настроения")
        check_image(rel, meta)
        check_links(rel, body, INDEX, "(в теле дня)")
        for slot in slots:
            check_links(rel, slot["what"], INDEX, "(в расписании)")


def check_venues() -> None:
    global notes_seen
    referenced = ""
    for path in sorted(B.TRIP_DAYS.glob("*.md")):
        referenced += path.read_text(encoding="utf-8")

    for path in sorted(B.TRIP_PLACES.glob("*.md")):
        notes_seen += 1
        rel = "Places/" + path.name
        meta, body, bad = read_frontmatter(path)
        if bad:
            err(rel, bad)
            continue
        if "public" not in tags_of(meta):
            warn(rel, "нет тега #public — на сайт не попадёт")
            continue
        if not str(meta.get("category") or "").strip():
            warn(rel, "нет 'category' — не будет плашки и счётчика в шапке")
        try:
            links = B.parse_body_links(body, path.name)
        except B.NoteError as exc:
            err(rel, str(exc))
            links = {}
        if not str(meta.get("address") or "").strip() and "maps" not in links:
            warn(rel, "нет адреса и ссылки на карту — чип «Карта» не появится")
        category = str(meta.get("category") or "").strip().lower()
        if category in NEEDS_STATUS and not str(meta.get("status") or "").strip():
            warn(rel, "нет 'status' — не видно, куплено/забронировано или нет")
        if "[[" + path.stem + "]]" not in referenced:
            warn(rel, "место не упоминается ни в одном дне")
        check_image(rel, meta)
        check_links(rel, body, INDEX)


def main() -> int:
    global INDEX
    parser = argparse.ArgumentParser(description="Линтер заметок Sightseeing")
    parser.add_argument("--strict", action="store_true", help="считать предупреждения ошибками")
    parser.add_argument("--quiet", action="store_true", help="только итоговая строка")
    args = parser.parse_args()

    missing = [f for f in (B.VAULT_PLACES, B.TRIP_DAYS, B.TRIP_PLACES) if not f.is_dir()]
    if missing:
        for folder in missing:
            print("нет папки: " + str(folder))
        return 2

    INDEX = note_index()
    check_places()
    check_days()
    check_venues()

    if not args.quiet:
        for title, items in (("ОШИБКИ", errors), ("ПРЕДУПРЕЖДЕНИЯ", warnings)):
            if not items:
                continue
            print(title + " (" + str(len(items)) + ")")
            for note, message in items:
                print("  " + note + ": " + message)
            print()

    print("Проверено заметок: " + str(notes_seen)
          + " · ошибок: " + str(len(errors))
          + " · предупреждений: " + str(len(warnings)))
    if errors:
        return 1
    if warnings and args.strict:
        print("Строгий режим: предупреждения считаются ошибками.")
        return 1
    return 0


INDEX: dict = {}

if __name__ == "__main__":
    raise SystemExit(main())
