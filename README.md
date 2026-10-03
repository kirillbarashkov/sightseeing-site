# Классные места — генератор сайта

Статический сайт со списком направлений для путешествий.
Источник данных — заметки Obsidian, помеченные тегом `#public`.

**Живой сайт:** https://kirillbarashkov.github.io/sightseeing-site/

## Как это работает

```
Obsidian vault (D:\...\02-Sightseeing\Places\*.md)
        │
        │  python build.py
        ▼
site_build/                  ← готовый статический сайт
    index.html               ← сетка карточек
    places/<slug>.html       ← страница на каждое место
    assets/style.css
        │
        │  git push origin gh-pages
        ▼
GitHub Pages
```

Markdown рендерится **на этапе сборки** (Python-модуль `markdown`), поэтому
на сайте нет клиентского JS и ничего не ломается в браузере.

## Требования

- Python 3.10+
- `pip install pyyaml markdown`

## Сборка

```bash
python build.py
```

Скрипт читает хранилище, отбирает заметки с тегом `public` в YAML-свойстве
`tags`, и полностью пересобирает `site_build/`. Пустые поля не выдумываются —
если `best_season` или `estimated_cost` не заполнены, они просто не показываются.

## Публикация

```bash
# 1. собрать
python build.py

# 2. выложить (из чистой копии site_build/)
git push -f origin gh-pages
```

Ветка `gh-pages` содержит **только** результат сборки. Исходники живут в `main`.

> ⚠️ Никогда не делай `git merge` между `main` и `gh-pages` — истории не связаны,
> в `index.html` попадут маркеры конфликта и сайт сломается. Ветки независимы.

## Схема заметки

```yaml
---
category: Природа            # Природа | Город | Событие
status: Планируется          # Планируется | Отслеживание | Посещено
priority: Must visit         # Must visit | Nice to have
estimated_cost:              # заполняется вручную, не выдумывается
best_season: Лето
location: Сахалинская область
links:
  site: https://...
  maps: https://yandex.ru/maps/...
tags: [sightseeing, russia, public]   # public = публикуется на сайте
---
```

Тег `public` определяет видимость на сайте. Убрать его — заметка исчезнет
из сборки, оставаясь в Obsidian.

## Настройки GitHub Pages

`Settings → Pages → Source: Deploy from a branch → gh-pages → / (root)`
