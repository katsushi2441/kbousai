#!/usr/bin/env python3
"""OGP 画像 1200×630（ライトテーマ・マスコット入り・数字は焼き込まない）。  /usr/bin/python3 scripts/make_ogp.py"""
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "ogp.png")
MASCOT = "/home/kojima/work/kurage_web/images/kurage-mascot-cutout.png"
FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FM = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

img = Image.new("RGB", (W, H), "#ffffff")
dr = ImageDraw.Draw(img, "RGBA")
dr.ellipse([-180, -240, 480, 380], fill=(227, 240, 248, 255))
dr.ellipse([W - 460, H - 330, W + 220, H + 240], fill=(238, 244, 248, 255))
m = Image.open(MASCOT).convert("RGBA")
m = m.crop(m.getbbox())
mh = 300
m = m.resize((int(m.width * mh / m.height), mh))
img.paste(m, (W - m.width - 70, 150), m)
cx = 500
fb, fh, fh2, fs, fbrand = (ImageFont.truetype(FM, 26), ImageFont.truetype(FB, 60), ImageFont.truetype(FB, 44),
                           ImageFont.truetype(FR, 27), ImageFont.truetype(FM, 28))
badge = "住所か現在地で ・ 気象庁と自治体のデータ"
bw = dr.textlength(badge, font=fb) + 40
dr.rounded_rectangle([cx - bw / 2, 80, cx + bw / 2, 128], radius=24, fill="#e3f0f8", outline="#bcd9ec")
dr.text((cx, 104), badge, font=fb, fill="#0b5d8f", anchor="mm")
dr.text((cx, 205), "いま逃げた方がいい？", font=fh, fill="#16232e", anchor="mm")
dr.text((cx, 283), "川・津波・台風・土砂に答える", font=fh2, fill="#0b5d8f", anchor="mm")
dr.text((cx, 355), "ハザード・警報・観測・避難・被害を1画面に。", font=fs, fill="#51606d", anchor="mm")
dr.text((cx, 395), "結論は規則で決め、AIが言い換えます。", font=fs, fill="#51606d", anchor="mm")
chips = [("注意", "#f2e700", "#000"), ("警戒", "#ff2800", "#fff"), ("危険", "#aa00aa", "#fff"), ("災害切迫", "#0c000c", "#fff")]
x = cx - 250
for t, bg, fg in chips:
    w = dr.textlength(t, font=fb) + 36
    dr.rounded_rectangle([x, 440, x + w, 486], radius=23, fill=bg)
    dr.text((x + w / 2, 463), t, font=fb, fill=fg, anchor="mm")
    x += w + 14
dr.text((60, H - 50), "Kurage 防災AIチャット", font=fbrand, fill="#16232e", anchor="lm")
dr.text((W - 60, H - 50), "kurage.exbridge.jp/kbousai.php/", font=ImageFont.truetype(FR, 22), fill="#51606d", anchor="rm")
img.save(OUT, optimize=True)
print(OUT)
