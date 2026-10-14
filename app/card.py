# -*- coding: utf-8 -*-
"""住所の防災カード（1200×630 PNG）と、その共有ページ。

**なぜ作ったか。** Xで議員や首長の投稿に返信するとき、URLを貼って出る画像が見られ、評価されている
（2026-10-14 国会トラッカーの質疑カード）。災害の日は、被災地の市区町村のページに検索とXから同じくらいの人が来る
（2026-09-21 khazard 実測）。住所で判定した「この場所に想定されている災害」を1枚にして、そのまま貼れるようにする。

**住所は残さない。** カードとページに出すのは市区町村までと、5つの想定（洪水・内水・高潮・土砂・津波）の行だけ。
緯度経度・番地・近くの避難所の名前と距離は保存も表示もしない（数百mで住んでいる場所が分かるため）。
URL はランダムな ID（/c/<id>）で、住所や緯度経度を含めない。
"""
import json
import os
import re
import secrets
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'data', 'cards')
W, H = 1200, 630
FB = '/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc'
FM = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
FR = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
ID_RE = re.compile(r'^[A-Za-z0-9_-]{8,16}$')


def _clean(line):
    """「土砂災害：警戒区域の外（最寄りの区域まで約3677m）」の距離のような、場所の手がかりになる部分を落とす"""
    line = re.sub(r'（最寄り[^）]*）', '', line)
    line = re.sub(r'（[^）]*まで約?\d[\d,.]*k?m）', '', line)
    return line.strip()


def material(area, hazards, checked_at):
    """判定の結果から、カードに残してよいものだけを取り出す"""
    rows = []
    for h in hazards or []:
        h = _clean(str(h))
        if '：' not in h:
            continue
        name, val = h.split('：', 1)
        name = name.replace('の想定', '').replace('（下水・水路があふれる）', '').strip()
        rows.append([name, val.strip()])
    return dict(area=area or '', rows=rows[:6], checked_at=str(checked_at or '')[:16])


def save(mat):
    os.makedirs(DIR, exist_ok=True)
    cid = secrets.token_urlsafe(8)
    mat = dict(mat, created=int(time.time()))
    with open(os.path.join(DIR, cid + '.json'), 'w', encoding='utf-8') as f:
        json.dump(mat, f, ensure_ascii=False)
    return cid


def load(cid):
    if not ID_RE.match(cid or ''):
        return None
    p = os.path.join(DIR, cid + '.json')
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _fit(dr, text, path, size, maxw, minimum=14):
    while size > minimum:
        f = ImageFont.truetype(path, size)
        if dr.textlength(text, font=f) <= maxw:
            return f
        size -= 1
    return ImageFont.truetype(path, size)


def _level(val):
    """値の重さ（色分けだけに使う）。0=想定なし・区域の外 / 1=想定あり / 2=深い（3m以上・特別警戒区域など）"""
    if re.search(r'(外|なし|ありません|対象外|想定されていません)', val):
        return 0
    # 3m以上（「0.3m以上」の「3m以上」に当てない。前に数字や小数点が無いときだけ）・特別警戒区域
    if re.search(r'(特別警戒|レッド)', val) or re.search(r'(?<![\d.])([3-9]|[1-9]\d+)(\.\d+)?m以上', val):
        return 2
    return 1


def png(cid, mat):
    """カード画像。描いたものは手元に置いて使い回す"""
    p = os.path.join(DIR, cid + '.png')
    if os.path.exists(p):
        return p
    img = Image.new('RGB', (W, H), '#ffffff')
    dr = ImageDraw.Draw(img, 'RGBA')
    dr.ellipse([-180, -240, 480, 380], fill=(230, 244, 242, 255))
    dr.ellipse([W - 460, H - 330, W + 220, H + 240], fill=(240, 246, 246, 255))
    X = 56
    tag = '防災カード｜' + (mat.get('area') or '')
    ft = _fit(dr, tag, FM, 22, 700)
    tw = dr.textlength(tag, font=ft)
    dr.rounded_rectangle([X, 34, X + tw + 36, 78], radius=22, fill='#e6f4f2', outline='#bfe3de')
    dr.text((X + 18, 56), tag, font=ft, fill='#0a726b', anchor='lm')
    when = (mat.get('checked_at') or '').replace('T', ' ')
    if when:
        fw = ImageFont.truetype(FR, 18)
        s = f'判定 {when[:4]}年{int(when[5:7])}月{int(when[8:10])}日'
        dr.text((W - X, 56), s, font=fw, fill='#5d6b7a', anchor='rm')
    dr.text((X, 132), 'この場所に想定されている災害', font=ImageFont.truetype(FB, 46), fill='#12202f', anchor='lm')

    rows = mat.get('rows') or []
    y = 186
    rh = min(66, int((H - 90 - y) / max(1, len(rows))))
    colors = {0: ('#eef2f5', '#5d6b7a', '#9aa8b5'), 1: ('#fff4e8', '#12202f', '#e08a1e'), 2: ('#fde9e7', '#12202f', '#d9534f')}
    for name, val in rows:
        lv = _level(val)
        bg, ink, dot = colors[lv]
        dr.rounded_rectangle([X, y, W - X, y + rh - 10], radius=12, fill=bg)
        dr.rectangle([X, y, X + 8, y + rh - 10], fill=dot)
        fn = _fit(dr, name, FM, 26, 190)
        dr.text((X + 28, y + (rh - 10) / 2), name, font=fn, fill='#12202f', anchor='lm')
        fv = _fit(dr, val, FB if lv else FR, 28, W - 2 * X - 260)
        dr.text((X + 240, y + (rh - 10) / 2), val, font=fv, fill=ink, anchor='lm')
        y += rh
    fr = ImageFont.truetype(FR, 18)
    dr.text((X, H - 34), 'kurage.exbridge.jp/kbousai.php　自分の住所で確かめられます', font=fr, fill='#5d6b7a', anchor='lm')
    dr.text((W - X, H - 34), '国の想定（国土数値情報）と自治体のハザードマップから', font=fr, fill='#5d6b7a', anchor='rm')
    img.save(p, optimize=True)
    return p
