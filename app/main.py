# -*- coding: utf-8 -*-
"""Kurage 防災AIチャット (kbousai) :18393

住所（または GPS）とチャットで、その地点の ハザード・警報・観測・避難・被害 を1画面に出し、
「逃げた方がいい？」「川は氾濫しそう？」「津波は来る？」「台風は直撃する？」に答える。

設計:
- **結論は規則で決める**（judge.py）。AI は決まった結論を、質問に合わせて言い換えるだけ
- **カードは AI を待たずに出す**。災害の日に AI が遅くても、事実はすぐ見える
- 取れなかった情報は「無い」と言わず「取得できない」と書く
"""
import os
import secrets
import threading
import time

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import judge, sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLLAMA = os.environ.get('KBOUSAI_OLLAMA', 'http://127.0.0.1:11434')
MODEL = os.environ.get('KBOUSAI_MODEL', 'gemma4:12b-it-qat')
E = os.environ.get
PUBLIC = E('KBOUSAI_PUBLIC_URL', 'http://127.0.0.1:18393/')
# 画面に出す名前・ロゴ・計測・関連リンク。**設定が無いときは計測タグを出さない**（配布先から当社へ計測が飛ばないように）
BRAND = E('KBOUSAI_BRAND', '防災AIチャット')
BRAND_SUB = E('KBOUSAI_BRAND_SUB', '')
LOGO = E('KBOUSAI_LOGO_URL', 'static/mascot.png')
LOGO_ALT = E('KBOUSAI_LOGO_ALT', BRAND)
GA_ID = E('KBOUSAI_GA_ID', '')
OPERATOR = E('KBOUSAI_OPERATOR', '')            # 例: 株式会社〇〇
OPERATOR_URL = E('KBOUSAI_OPERATOR_URL', '')
AI_LABEL = E('KBOUSAI_AI_LABEL', MODEL.split(':')[0])
PV_URL = E('KBOUSAI_PV_URL', '')                # 紹介動画（空なら出さない）
PV_POSTER = E('KBOUSAI_PV_POSTER', '')
PV_NOTE = E('KBOUSAI_PV_NOTE', '')
BUY_URL = E('KBOUSAI_BUY_URL', '')              # 導入版の案内（空なら出さない。配布先では出ない）
BUY_TEXT = E('KBOUSAI_BUY_TEXT', '')
ABOUT_PROMO = ('<p>自治体の防災ページ・会社の防災担当・不動産会社のサイトに、自社の防災AIチャットボットとして置くこともできます。'
               '<a href="https://exbridge.jp/solution/bousai-ai-chatbot.html?ref=kbousai-about">防災AIチャットボットの導入について</a></p>')
# 同じサーバーに置いた各エンジンの画面（詳しく見るリンク）。空ならリンクを出さない
LINKS = {k: E(f'KBOUSAI_LINK_{k.upper()}', '') for k in ('kflood', 'khazard', 'ktsunami', 'krefuge')}
LINK_NAMES = {'kflood': '洪水・内水ハザードマップ', 'khazard': '土砂災害ハザードマップ',
              'ktsunami': '津波浸水想定マップ', 'krefuge': '避難所マップ'}

app = FastAPI(title='Kurage 防災AIチャット', docs_url=None, redoc_url=None, openapi_url=None)
app.mount('/static', StaticFiles(directory=os.path.join(ROOT, 'static')), name='static')

_rate = {}
_rate_lock = threading.Lock()


def client_ip(request: Request):
    return (request.headers.get('x-forwarded-for') or request.client.host or '').split(',')[0].strip()


def limited(ip, per_min, bucket):
    now = time.time()
    with _rate_lock:
        q = [t for t in _rate.get((ip, bucket), []) if now - t < 60]
        if len(q) >= per_min:
            return True
        q.append(now)
        _rate[(ip, bucket)] = q
        if len(_rate) > 5000:
            _rate.clear()
    return False


# /api/ask の結果を AI の言い換え用に少しだけ持つ（利用者から任意の文を AI に渡させないため）
# 答えの言葉（2026-10-02）。結論は規則のまま、AIの言い換えだけを選んだ言葉にする。
# 外国語の質問は、質問の種類（避難・川・台風…）の見分けが日本語の語で作られているので、先に日本語へ直してから見分ける
LANGS = {
    'ja': ('日本語', '日本語で'),
    'easy': ('やさしい日本語', 'やさしい日本語で（短い文で、むずかしい言葉は使わず、言いかえる）'),
    'en': ('English', 'in English'),
    'zh': ('中文', '用简体中文'),
    'ko': ('한국어', '한국어로'),
    'vi': ('Tiếng Việt', 'bằng tiếng Việt'),
    'pt': ('Português', 'em português'),
    'tl': ('Tagalog', 'sa wikang Tagalog'),
    'ne': ('नेपाली', 'नेपाली भाषामा'),
}


def to_japanese(msg):
    """外国語の質問を日本語に直す（質問の種類を見分けるためだけに使う）。失敗したら元のまま返す"""
    try:
        r = requests.post(f'{OLLAMA}/api/generate', timeout=20, json=dict(
            model=MODEL, stream=False, think=False, keep_alive='30m',
            prompt=f'次の質問を、自然な日本語の1文に訳してください。訳だけを書いてください。\n\n{msg}',
            options=dict(temperature=0, num_predict=80)))
        r.raise_for_status()
        t = (r.json().get('response') or '').strip().splitlines()
        return t[0][:200] if t else msg
    except Exception:  # noqa: BLE001
        return msg


_asked = {}
_asked_lock = threading.Lock()


def _remember(facts, msg, lang='ja'):
    tok = secrets.token_urlsafe(12)
    with _asked_lock:
        _asked[tok] = (time.time(), facts, msg, lang)
        for k in [k for k, v in _asked.items() if time.time() - v[0] > 900]:
            _asked.pop(k, None)
    return tok


@app.get('/api/ask')
def api_ask(request: Request, q: str = '', lat: float = None, lon: float = None, msg: str = '', lang: str = 'ja'):
    ip = client_ip(request)
    if limited(ip, 15, 'ask'):
        raise HTTPException(429, '短い時間に多くの質問がありました。1分ほど待ってからもう一度どうぞ')
    msg = (msg or '').strip()[:200]
    if lang not in LANGS:
        raise HTTPException(400, '答えの言葉の指定が正しくありません')
    if lat is not None and lon is not None:
        if not (20 < lat < 46 and 122 < lon < 154):
            raise HTTPException(400, '日本の中の場所を指定してください')
        addr = sources.reverse(lat, lon) or f'緯度{lat:.4f} 経度{lon:.4f}'
        how = 'gps'
    else:
        q = (q or '').strip()[:100]
        if not q:
            raise HTTPException(400, '住所を入れるか、「現在地」を押してください')
        try:
            g = sources.geocode(q)
        except Exception:  # noqa: BLE001
            raise HTTPException(503, '住所検索（国土地理院）に接続できませんでした。少し待ってからもう一度どうぞ')
        if not g:
            raise HTTPException(404, 'その住所が見つかりませんでした。都道府県から入れてみてください')
        lat, lon, addr, how = g['lat'], g['lon'], g['address'], 'address'
    # 外国語の質問は日本語に直してから見分ける（日本語の語が1つも当たらないときだけ。chip の日本語はそのまま当たる）
    msg_ja = msg
    if lang not in ('ja', 'easy') and msg and not any(any(w in msg for w in ws) for _, _, ws in judge.INTENTS):
        msg_ja = to_japanese(msg)
    intent = judge.intent_of(msg_ja)
    hz = sources.REFUGE_HAZARD.get(intent, '')
    key = ('snap', round(lat, 4), round(lon, 4), hz)
    snap = sources.cached(key, 120, lambda: sources.snapshot(lat, lon, addr, ip, hz))
    ans = judge.answer(snap, msg_ja)
    tok = _remember(judge.facts_for_ai(snap, ans), msg, lang)
    return JSONResponse(dict(located_by=how, snapshot=snap, answer=ans, token=tok),
                        headers={'Cache-Control': 'no-store'})


_ai_sem = threading.BoundedSemaphore(2)

AI_RULES = """あなたは防災の案内係です。下の「事実」だけを使って、利用者の質問に__LANG__答えてください。
- 事実に無い情報（数字・地名・予報・施設）を足さない
- 質問への答えは「判定」の行にある。判定に書いてあることを「分かりません」と言わない。判定に無いことだけ「この画面では分かりません」と言う
- 「判定」の結論（避難すべきか、どの段階か）を変えない。弱めない・強めない
- はじめの1文で、質問への答えを言い切る。次に、その理由になる事実を1〜2つ。最後に、いまやることを1つ
- 全部で3〜4文（日本語なら200字以内）。見出し・箇条書き・絵文字は使わない
- 日本語以外で答えるときも、地名・避難先・施設の名前は日本語の表記をそのまま残す（現地で看板と照らし合わせられるように）
- 医療・保険・法律の判断はしない"""


@app.get('/api/say')
def api_say(request: Request, token: str = ''):
    """規則で決めた答えを、質問に合わせて AI が言い換える。失敗しても画面の答えはそのまま使える。"""
    if limited(client_ip(request), 8, 'say'):
        return JSONResponse(dict(status='busy'))
    with _asked_lock:
        it = _asked.get(token)
    if not it:
        return JSONResponse(dict(status='expired'))
    _, facts, msg, lang = it
    if not _ai_sem.acquire(timeout=2):
        return JSONResponse(dict(status='busy'))
    try:
        prompt = f"{AI_RULES.replace('__LANG__', LANGS[lang][1])}\n\n# 事実\n{facts}\n\n# 質問\n{msg or 'いま避難した方がいいですか？'}\n\n# 答え\n"
        r = requests.post(f'{OLLAMA}/api/generate', timeout=45, json=dict(
            model=MODEL, prompt=prompt, stream=False, think=False, keep_alive='30m',
            options=dict(temperature=0.2, num_predict=600 if lang not in ('ja', 'easy') else 400)))
        r.raise_for_status()
        text = judge.clean_ai(r.json().get('response'))
        if not text:
            return JSONResponse(dict(status='empty'))
        return JSONResponse(dict(status='ok', text=text, model=MODEL))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(dict(status='unavailable', error=type(e).__name__))
    finally:
        _ai_sem.release()


@app.get('/healthz')
def healthz():
    return dict(ok=True)


@app.get('/', response_class=HTMLResponse)
def index():
    import html as H
    import json as J
    with open(os.path.join(ROOT, 'templates', 'index.html'), encoding='utf-8') as f:
        page = f.read()
    ga = ('<script async src="https://www.googletagmanager.com/gtag/js?id=%s"></script>'
          "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}"
          "gtag('js',new Date());gtag('config','%s');</script>" % (H.escape(GA_ID), H.escape(GA_ID))) if GA_ID else ''
    rel = '・'.join(f'<a href="{H.escape(u)}">{LINK_NAMES[k]}</a>' for k, u in LINKS.items() if u)
    foot = ''
    if BUY_URL:
        rel = (rel + '・' if rel else '') + f'<a href="{H.escape(BUY_URL)}" target="_blank" rel="noopener">導入版（Kurage App Store）</a>'
    if rel or OPERATOR:
        foot = ' <p>' + (f'関連：{rel}' if rel else '')
        if OPERATOR:
            op = f'<a href="{H.escape(OPERATOR_URL)}">{H.escape(OPERATOR)}</a>' if OPERATOR_URL else H.escape(OPERATOR)
            foot += f'　運営：{op}'
        foot += '</p>'
    pv = ''
    if PV_URL:
        pv = ('<section class="pv" aria-label="紹介動画"><h2>1分でわかる動画</h2>'
              f'<video src="{H.escape(PV_URL)}" poster="{H.escape(PV_POSTER)}" controls playsinline preload="none" width="1920" height="1080"></video>'
              + (f'<p class="note">{H.escape(PV_NOTE)}</p>' if PV_NOTE else '') + '</section>')
    buy = ''
    if BUY_URL:
        buy = ('<section class="buy" aria-label="導入版"><p><b>このチャットを、自治体・事務所・会社の名前で公開できます</b>'
               f'{H.escape(BUY_TEXT)}</p><a class="cta" href="{H.escape(BUY_URL)}" target="_blank" rel="noopener">導入版を見る（Kurage App Store）</a></section>')
    # 右上の誘導（2026-10-03）。下まで読まない人が多いのでヘッダーにも置く。BUY_URL がある当社の公開先だけ
    head_cta = ''
    if BUY_URL:
        head_cta = ('<nav class="hcta" aria-label="導入と相談">'
                    f'<a class="hot" href="{H.escape(BUY_URL)}" target="_blank" rel="noopener">導入版</a>'
                    '<a href="https://exbridge.jp/ai-it-komon.html?ref=kbousai-head-komon">AI-IT顧問</a>'
                    '<a href="https://kurage.exbridge.jp/reseller.html?ref=kbousai-head-reseller">販売代理店募集</a></nav>')
    cfg = J.dumps(dict(links={k: v for k, v in LINKS.items() if v}, ai_label=AI_LABEL), ensure_ascii=False)
    for k, v in (('__GA__', ga), ('__PUBLIC__', H.escape(PUBLIC)), ('__BRAND_SUB__', H.escape(BRAND_SUB)),
                 ('__BRAND__', H.escape(BRAND)), ('__LOGO_ALT__', H.escape(LOGO_ALT)), ('__LOGO__', H.escape(LOGO)),
                 ('__ABOUT_PROMO__', ABOUT_PROMO if BUY_URL else ''),   # 導入の案内は当社の公開先だけ（配布先では BUY_URL が空）
                 ('__FOOTER__', foot), ('__HEAD_CTA__', head_cta), ('__PV__', pv), ('__BUY__', buy), ('__CFG__', cfg.replace('</', '<\\/'))):
        page = page.replace(k, v)
    return HTMLResponse(page, headers={'Cache-Control': 'no-cache'})


@app.get('/robots.txt', response_class=PlainTextResponse)
def robots():
    return f'User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {PUBLIC}sitemap.xml\n'


@app.get('/sitemap.xml')
def sitemap():
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'<url><loc>{PUBLIC}</loc><lastmod>2026-09-28</lastmod></url>\n</urlset>\n')
    return PlainTextResponse(body, media_type='application/xml')


@app.get('/llms.txt', response_class=PlainTextResponse)
def llms():
    p = os.path.join(ROOT, 'llms.txt')
    if not os.path.exists(p):
        raise HTTPException(404)
    with open(p, encoding='utf-8') as f:
        return f.read()


@app.get('/favicon.ico')
def favicon():
    return FileResponse(os.path.join(ROOT, 'static', 'favicon.png'))
