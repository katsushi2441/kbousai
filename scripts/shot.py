#!/usr/bin/env python3
"""画面を実際の端末幅で撮り、横はみ出しを実測する（質問を1つ投げた状態）。
  /usr/bin/python3 scripts/shot.py <URL> <出力先ディレクトリ>
一時プロファイルの headless Chromium（Playwright）。chrome-profile は使わない。
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

url, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (320, 390, 1280):
        pg = b.new_page(viewport={'width': w, 'height': 900})
        pg.goto(url)
        pg.wait_for_selector('.bot .lv', timeout=40000)
        pg.wait_for_timeout(1500)
        sw = pg.evaluate('document.documentElement.scrollWidth')
        pg.screenshot(path=str(out / f'w{w}.png'), full_page=True)
        print(w, 'scrollWidth', sw, 'OK' if sw <= w else 'OVERFLOW')
    b.close()
