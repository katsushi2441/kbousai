# -*- coding: utf-8 -*-
"""kbousai が1地点ぶん集める情報。**取れなかったものは「無い」と言わず status で返す。**

  ハザード  … 連携する kflood(洪水・内水・高潮)・khazard(土砂)・ktsunami(津波浸水想定)
  警報      … 気象庁の警報・注意報（kflood 経由。住所の文字列で引く）
  観測      … 気象庁 アメダス（最寄り観測所の雨量）とキキクル（危険度分布）のタイルの色
  台風      … 気象庁 台風情報（予報円・暴風警戒域と地点の距離）
  津波      … 気象庁 津波警報・注意報
  避難      … 市区町村の避難情報（kflood。名古屋市・東京都・千葉県・神奈川県・静岡県）と避難先（krefuge）

気象庁のデータは「気象庁ホームページ利用規約」（公共データ利用規約 第1.0版準拠）で、出典を書いて使う。
**川の水位は取りに行かない。** 国土交通省「川の防災情報」は「ツール等による定期的なデータ収集は…お控えください」
と明記しているので、リンクで案内する（2026-09-28 確認）。
"""
import io
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from PIL import Image

UA = {'User-Agent': os.environ.get('KBOUSAI_UA', 'kbousai/1.0 (bousai-chat)')}
JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KFLOOD = os.environ.get('KBOUSAI_KFLOOD', 'http://127.0.0.1:18386')
KHAZARD = os.environ.get('KBOUSAI_KHAZARD', 'http://127.0.0.1:18376')
KTSUNAMI = os.environ.get('KBOUSAI_KTSUNAMI', 'http://127.0.0.1:18380')
KREFUGE = os.environ.get('KBOUSAI_KREFUGE', 'http://127.0.0.1:18378')

GSI_SEARCH = 'https://msearch.gsi.go.jp/address-search/AddressSearch'
GSI_REVERSE = 'https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress'
JMA = 'https://www.jma.go.jp/bosai'

RIVER_URL = 'https://www.river.go.jp/index'
RIVER_NAME = '国土交通省「川の防災情報」'

_lock = threading.Lock()
_cache = {}


def cached(key, sec, fn):
    """同じ取得を sec 秒まとめる。失敗したら前回値を stale 付きで返す（災害時にアクセスが集中しても元を叩きすぎない）。"""
    now = time.time()
    with _lock:
        c = _cache.get(key)
        if c and now - c[0] < sec:
            return c[1]
    try:
        v = fn()
    except Exception:  # noqa: BLE001
        if c:
            return c[1]
        raise
    with _lock:
        _cache[key] = (now, v)
        if len(_cache) > 3000:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:1000]:
                _cache.pop(k, None)
    return v


def _get_json(url, params=None, timeout=10, headers=None):
    r = requests.get(url, params=params, timeout=timeout, headers=headers or UA)
    r.raise_for_status()
    return r.json()


def now_jst():
    return datetime.now(JST).strftime('%Y-%m-%d %H:%M')


# ---------------------------------------------------------------- 住所
_MUNI = None


def muni_name(code):
    global _MUNI
    if _MUNI is None:
        with open(os.path.join(ROOT, 'data', 'muni.json'), encoding='utf-8') as f:
            _MUNI = json.load(f)
    return _MUNI.get(str(code).lstrip('0').zfill(5) if code else '')


def geocode(q):
    """国土地理院の住所検索。クエリを含む候補を優先（kflood・khazard と同じ）。"""
    items = cached(('geo', q), 3600, lambda: _get_json(GSI_SEARCH, {'q': q}))
    if not items:
        return None

    def score(it):
        t = it.get('properties', {}).get('title', '')
        return (q in t, t.startswith(q), -len(t))
    it = max(items, key=score)
    lon, lat = it['geometry']['coordinates']
    return dict(lat=float(lat), lon=float(lon), address=it['properties'].get('title', ''))


def reverse(lat, lon):
    """GPS の緯度経度 → 住所（都道府県＋市区町村＋町字）。取れなければ None。"""
    key = ('rev', round(lat, 4), round(lon, 4))
    try:
        j = cached(key, 3600, lambda: _get_json(GSI_REVERSE, {'lat': lat, 'lon': lon}, timeout=8))
    except Exception:  # noqa: BLE001
        return None
    r = (j or {}).get('results') or {}
    m = muni_name(r.get('muniCd'))
    if not m:
        return None
    return f"{m[0]}{m[1]}{r.get('lv01Nm') or ''}".replace('－', '')


PREF_RE = re.compile(r'^(北海道|東京都|京都府|大阪府|.{2,3}?県)')


def pref_of(address):
    m = PREF_RE.match(address or '')
    return m.group(1) if m else None


# ---------------------------------------------------------------- 連携するエンジン
def _sibling(base, path, params, xff, timeout=15):
    """連携する各エンジン。利用者の IP を X-Forwarded-For で渡す（各サービスの回数制限を利用者ごとに効かせる）。"""
    h = dict(UA)
    if xff:
        h['X-Forwarded-For'] = xff
    try:
        r = requests.get(base + path, params=params, timeout=timeout, headers=h)
        if r.status_code == 429:
            return dict(status='busy')
        r.raise_for_status()
        d = r.json()
        d.setdefault('status_http', 200)
        return d
    except Exception as e:  # noqa: BLE001
        return dict(status='unavailable', error=type(e).__name__)


def kflood(lat, lon, addr, xff):
    return _sibling(KFLOOD, '/api/check', {'lat': lat, 'lon': lon, 'addr': addr}, xff)


def khazard(lat, lon, xff):
    return _sibling(KHAZARD, '/api/check', {'lat': lat, 'lon': lon}, xff)


def ktsunami(lat, lon, xff):
    return _sibling(KTSUNAMI, '/api/check', {'lat': lat, 'lon': lon}, xff)


def krefuge(lat, lon, hazard, xff):
    return _sibling(KREFUGE, '/api/check', {'lat': lat, 'lon': lon, 'hazard': hazard}, xff)


# ---------------------------------------------------------------- アメダス
def _deg(v):
    return v[0] + v[1] / 60.0


def dist_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def amedas(lat, lon):
    """最寄りの雨量を測っている観測所の、10分・1時間・3時間・24時間の雨量と風。"""
    try:
        table = cached('amedastable', 86400, lambda: _get_json(f'{JMA}/amedas/const/amedastable.json', timeout=20))
        latest = cached('amedas_latest', 60, lambda: requests.get(
            f'{JMA}/amedas/data/latest_time.txt', headers=UA, timeout=8).text.strip())
        t = datetime.fromisoformat(latest)
        stamp = t.strftime('%Y%m%d%H%M00')
        data = cached(('amedas', stamp), 600, lambda: _get_json(f'{JMA}/amedas/data/map/{stamp}.json', timeout=15))
    except Exception as e:  # noqa: BLE001
        return dict(status='unavailable', error=type(e).__name__)
    best = None
    for code, st in table.items():
        obs = data.get(code) or {}
        if 'precipitation1h' not in obs:
            continue
        d = dist_km(lat, lon, _deg(st['lat']), _deg(st['lon']))
        if best is None or d < best[0]:
            best = (d, code, st, obs)
    if not best:
        return dict(status='unavailable', error='no_station')
    d, code, st, obs = best
    val = lambda k: (obs.get(k) or [None])[0]  # noqa: E731
    return dict(status='ok', station=st['kjName'], code=code, distance_km=round(d, 1),
                rain10m=val('precipitation10m'), rain1h=val('precipitation1h'),
                rain3h=val('precipitation3h'), rain24h=val('precipitation24h'),
                wind=val('wind'), gust=val('gust'),
                observed_at=t.strftime('%Y-%m-%d %H:%M'),
                source='気象庁 アメダス', source_url=f'https://www.jma.go.jp/bosai/amedas/#amdno={code}')


# ---------------------------------------------------------------- キキクル（危険度分布）
# 色 → 段階。気象庁 risk.properties の凡例（2026-09-28 取得）と同じ色。
RISK_COLORS = [
    (5, (0x0c, 0x00, 0x0c), '災害切迫（黒）'),
    (4, (0xaa, 0x00, 0xaa), '危険（紫）'),
    (3, (0xff, 0x28, 0x00), '警戒（赤）'),
    (2, (0xf2, 0xe7, 0x00), '注意（黄）'),
]
RISK_LABEL = {lv: lab for lv, _, lab in RISK_COLORS}
RISK_ELEMENTS = {
    'land': '土砂災害',
    'inund': '浸水害（大雨による浸水）',
    'flood': '洪水害（中小河川）',
    'designated_river': '指定河川洪水予報（大きな川）',
}
RISK_Z = 10


def _pixel_level(rgba):
    r, g, b, a = rgba
    if a < 64:
        return 0
    best, bd = 0, 1e9
    for lv, (cr, cg, cb), _ in RISK_COLORS:
        dd = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dd < bd:
            best, bd = lv, dd
    return best if bd < 60 ** 2 else 0     # 凡例に無い色（水色の「今後の情報に留意」など）は0扱い


def _tile(url):
    def load():
        r = requests.get(url, headers=UA, timeout=10)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert('RGBA')
    return cached(('tile', url), 600, load)


def _risk_at(base, element, lat, lon, radius_px):
    """地点の周り radius_px（z10 で1px≒150m）の中でいちばん高い段階。"""
    n = 2 ** RISK_Z
    fx = (lon + 180) / 360 * n * 256
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 256
    best = 0
    for dx in range(-radius_px, radius_px + 1):
        for dy in range(-radius_px, radius_px + 1):
            if dx * dx + dy * dy > radius_px * radius_px:
                continue
            px, py = int(fx) + dx, int(fy) + dy
            tx, ty = px // 256, py // 256
            img = _tile(f'{base}/surf/{element}/{RISK_Z}/{tx}/{ty}.png')
            if img is None:
                continue
            best = max(best, _pixel_level(img.getpixel((px % 256, py % 256))))
            if best == 5:
                return best
    return best


def kikikuru(lat, lon):
    """いま（実況）と、2時間先までの予想のうち最大。土砂・浸水は地点、川は周り約2kmで見る。"""
    try:
        tt = cached('risk_targets', 120, lambda: _get_json(f'{JMA}/jmatile/data/risk/targetTimes.json'))
    except Exception as e:  # noqa: BLE001
        return dict(status='unavailable', error=type(e).__name__)
    latest = max(x['basetime'] for x in tt)
    frames = [x for x in tt if x['basetime'] == latest]
    out = {}
    try:
        for el, label in RISK_ELEMENTS.items():
            radius = 1 if el in ('land', 'inund') else 13
            now_lv, ahead = 0, 0
            for fr in frames:
                if el not in fr.get('elements', []):
                    continue
                base = f"{JMA}/jmatile/data/risk/{fr['basetime']}/{fr['member']}/{fr['validtime']}"
                lv = _risk_at(base, el, lat, lon, radius)
                if fr['validtime'] == fr['basetime']:
                    now_lv = max(now_lv, lv)
                ahead = max(ahead, lv)
            out[el] = dict(label=label, now=now_lv, ahead=ahead,
                           now_label=RISK_LABEL.get(now_lv, '色なし（危険度の表示なし）'),
                           ahead_label=RISK_LABEL.get(ahead, '色なし（危険度の表示なし）'),
                           scope='この地点' if el in ('land', 'inund') else '周り約2km')
    except Exception as e:  # noqa: BLE001
        return dict(status='unavailable', error=type(e).__name__)
    at = datetime.strptime(latest, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).astimezone(JST)
    return dict(status='ok', items=out, observed_at=at.strftime('%Y-%m-%d %H:%M'),
                source='気象庁 キキクル（危険度分布）',
                source_url=f'https://www.jma.go.jp/bosai/risk/#zoom:12/lat:{lat:.4f}/lon:{lon:.4f}')


# ---------------------------------------------------------------- 台風
def _interp(a, b, f):
    return a + (b - a) * f


def _storm_radius(part):
    """予報円の中心で描かれた暴風警戒域の半径（m）。実況は暴風域の半径。"""
    c = part.get('center')
    sw = part.get('stormWarningArea') or {}
    best = None
    for arc in sw.get('arc') or []:
        (clat, clon), rad = arc[0], arc[1]
        if c and abs(clat - c[0]) < 1e-6 and abs(clon - c[1]) < 1e-6:
            best = max(best or 0, rad)
    return best


def typhoon(lat, lon):
    """発生中の台風ごとに、地点へいちばん近づく時刻・距離と、暴風警戒域・予報円に入るか。

    予報の各時刻の間は1時間刻みで直線補間する（中心・半径とも）。**気象庁の暴風警戒域の形とは厳密には違う**近似。
    """
    try:
        lst = cached('tc_list', 300, lambda: _get_json(f'{JMA}/typhoon/data/targetTc.json'))
    except Exception as e:  # noqa: BLE001
        return dict(status='unavailable', error=type(e).__name__)
    storms = []
    for tc in lst or []:
        tid = tc.get('tropicalCyclone')
        try:
            fc = cached(('tc_fc', tid), 300, lambda: _get_json(f'{JMA}/typhoon/data/{tid}/forecast.json'))
            sp = cached(('tc_sp', tid), 300, lambda: _get_json(f'{JMA}/typhoon/data/{tid}/specifications.json'))
        except Exception:  # noqa: BLE001
            continue
        title = sp[0] if sp else {}
        now_spec = next((p for p in sp[1:] if int(p.get('advancedHours', 0)) == 0), {})
        pts = []
        for p in fc[1:]:
            c = p.get('center')
            if not c:
                continue
            h = int(p.get('advancedHours', 0))
            prob = (p.get('probabilityCircle') or {}).get('radius') or 0
            storm = _storm_radius(p)
            vt = (p.get('validtime') or {}).get('JST')
            pts.append((h, c[0], c[1], prob, storm, vt))
        pts.sort()
        best = None
        for (h1, la1, lo1, pr1, st1, vt1), (h2, la2, lo2, pr2, st2, vt2) in zip(pts, pts[1:]):
            for k in range(max(1, h2 - h1)):
                f = k / max(1, h2 - h1)
                la, lo = _interp(la1, la2, f), _interp(lo1, lo2, f)
                d = dist_km(lat, lon, la, lo)
                if best is None or d < best['km']:
                    t = datetime.fromisoformat(vt1) + timedelta(hours=h2 - h1) * f if vt1 else None
                    best = dict(km=d, hours=h1 + (h2 - h1) * f, at=t.strftime('%m月%d日 %H時ごろ') if t else '',
                                prob_km=_interp(pr1, pr2, f) / 1000,
                                storm_km=(_interp(st1 or 0, st2 or 0, f) / 1000) if (st1 or st2) else None)
        if not best and pts:
            h, la, lo, pr, st, vt = pts[-1]
            best = dict(km=dist_km(lat, lon, la, lo), hours=h, at='', prob_km=pr / 1000,
                        storm_km=(st or 0) / 1000 or None)
        # 暴風警戒域に入るか: 予報円半径＋暴風半径（気象庁の円の半径）以内
        in_storm = bool(best and best['storm_km'] and best['km'] <= best['storm_km'])
        in_prob = bool(best and best['prob_km'] and best['km'] <= best['prob_km'])
        storms.append(dict(
            number=(title.get('typhoonNumber') or '')[-2:].lstrip('0'),
            name=(title.get('name') or {}).get('jp', ''),
            category=(title.get('category') or {}).get('jp', ''),
            intensity=now_spec.get('intensity', ''), pressure=now_spec.get('pressure', ''),
            max_wind=((now_spec.get('maximumWind') or {}).get('sustained') or {}).get('m/s', ''),
            location=now_spec.get('location', ''),
            issued=((title.get('issue') or {}).get('JST') or '')[:16].replace('T', ' '),
            closest_km=round(best['km']) if best else None, closest_at=best['at'] if best else '',
            closest_hours=round(best['hours']) if best else None,
            storm_km=round(best['storm_km']) if best and best['storm_km'] else None,
            in_storm_area=in_storm, in_probability_circle=in_prob,
            url=f'https://www.jma.go.jp/bosai/map.html#contents=typhoon'))
    return dict(status='ok', storms=storms, fetched_at=now_jst(), source='気象庁 台風情報',
                source_url='https://www.jma.go.jp/bosai/map.html#contents=typhoon')


# ---------------------------------------------------------------- 津波
TSUNAMI_RANK = {'大津波警報': 3, '津波警報': 2, '津波注意報': 1}


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def tsunami(pref):
    """いま出ている津波警報・注意報。都道府県名を含む津波予報区のものを「この地域」として返す。

    ここ24時間の電文を新しい順に読み、予報区ごとに最新の種別を採る（解除は落とす）。
    """
    try:
        lst = cached('tsunami_list', 60, lambda: _get_json(f'{JMA}/tsunami/data/list.json'))
    except Exception as e:  # noqa: BLE001
        return dict(status='unavailable', error=type(e).__name__)
    cutoff = datetime.now(JST) - timedelta(hours=24)
    areas = {}
    for it in sorted(lst or [], key=lambda x: x.get('rdt') or x.get('at') or '', reverse=True):
        rdt = it.get('rdt') or it.get('at') or ''
        try:
            if rdt and datetime.fromisoformat(rdt) < cutoff:
                continue
        except ValueError:
            pass
        fn = it.get('json')
        if not fn:
            continue
        try:
            doc = cached(('tsunami_doc', fn), 3600, lambda: _get_json(f'{JMA}/tsunami/data/{fn}'))
        except Exception:  # noqa: BLE001
            continue
        for node in _walk(doc):
            area = node.get('Area') if isinstance(node.get('Area'), dict) else None
            cat = node.get('Category') if isinstance(node.get('Category'), dict) else None
            if not area or not cat:
                continue
            name = area.get('Name')
            kind = ((cat.get('Kind') or {}).get('Name')) or ''
            if name and name not in areas:
                areas[name] = kind
    active = {a: k for a, k in areas.items() if any(w in k for w in TSUNAMI_RANK)}
    key = (pref or '').rstrip('都道府県') if pref and pref != '北海道' else (pref or '')
    local = {a: k for a, k in active.items() if key and key in a}
    top = max((TSUNAMI_RANK.get(next((w for w in TSUNAMI_RANK if w in k), ''), 0) for k in local.values()), default=0)
    return dict(status='ok', active=active, local=local,
                local_max=next((w for w, r in TSUNAMI_RANK.items() if r == top), None),
                fetched_at=now_jst(), source='気象庁 津波警報・注意報',
                source_url='https://www.jma.go.jp/bosai/map.html#contents=tsunami')


# ---------------------------------------------------------------- まとめて
REFUGE_HAZARD = {'river': 'flood', 'rain': 'inlflood', 'tsunami': 'tsunami', 'landslide': 'landslid',
                 'typhoon': 'surge'}


def snapshot(lat, lon, address, xff=None, refuge_hazard=''):
    """1地点ぶん、全部を並行で集める。1つが遅くても他は返す（各取得に timeout あり）。"""
    pref = pref_of(address)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = dict(
            flood=ex.submit(kflood, lat, lon, address, xff),
            dosha=ex.submit(khazard, lat, lon, xff),
            tsunami_zone=ex.submit(ktsunami, lat, lon, xff),
            refuge=ex.submit(krefuge, lat, lon, refuge_hazard, xff),
            amedas=ex.submit(amedas, lat, lon),
            kikikuru=ex.submit(kikikuru, lat, lon),
            typhoon=ex.submit(typhoon, lat, lon),
            tsunami=ex.submit(tsunami, pref),
        )
        out = {}
        for k, f in futs.items():
            try:
                out[k] = f.result(timeout=25)
            except Exception as e:  # noqa: BLE001
                out[k] = dict(status='unavailable', error=type(e).__name__)
    out.update(lat=lat, lon=lon, address=address, pref=pref, checked_at=now_jst(),
               river=dict(url=RIVER_URL, name=RIVER_NAME,
                          note='川の水位は、国土交通省「川の防災情報」で最寄りの水位観測所を見てください。'
                               '（自動で集めることが禁止されているので、この画面には取り込んでいません）'),
               damage=dict(status='none',
                           note='被害（けが人・住宅の被害・通行止め）は、全国をまとめて機械で読めるデータが公開されていません。'
                                '市区町村・都道府県の災害情報と、総務省消防庁の災害情報を見てください。',
                           links=[dict(name='総務省消防庁 災害情報', url='https://www.fdma.go.jp/disaster/info/')]))
    return out
