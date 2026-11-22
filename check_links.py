"""Проверка локальных ссылок и картинок в собранном сайте."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "site_build")
bad, total = [], 0
for page in root.rglob("*.html"):
    html = page.read_text(encoding="utf-8")
    for attr, url in re.findall(r'(href|src)="([^"]+)"', html):
        if url.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:")):
            continue
        clean = url.split("#")[0].split("?")[0]
        if not clean:
            continue
        total += 1
        target = (page.parent / clean).resolve()
        if not target.exists():
            bad.append(f"{page.relative_to(root)}: {attr}={url}")
print(f"checked {total} local links across {len(list(root.rglob('*.html')))} pages")
if bad:
    print(f"broken: {len(bad)}")
    for line in bad[:40]:
        print("  ", line)
    sys.exit(1)
print("all local links resolve")
