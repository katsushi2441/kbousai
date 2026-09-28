# -*- coding: utf-8 -*-
"""質問の種類を決め、集めた事実から「いま何をすべきか」を**規則で**決める。

AI（gemma4）はここで決めた結論を言い換えるだけで、結論は変えない。
段階は内閣府「避難情報に関するガイドライン」（令和8年3月改定）の警戒レベルに合わせる。
  レベル3 高齢者等避難／レベル4 避難指示（危険な場所から全員避難）／レベル5 緊急安全確保（命を守る行動）
気象庁の情報は「警戒レベル相当」として同じ物差しに載せる（キキクル 黄=2・赤=3・紫=4・黒=5 相当）。
"""
import re

INTENTS = [
    # (key, 表示名, 語)  上から順に当てる
    # 交通は運行情報を取り込んでいないので、正直にそう言って各社の情報へ案内する（2026-09-28 に「電車の影響は？」が来た）
    ('transport', '交通への影響', ('電車', '鉄道', '運休', '運転見合わせ', '新幹線', '飛行機', '欠航', '航空', 'バス',
                               '交通', '通勤', '通学', '高速道路', '通行止め', 'フェリー')),
    ('tsunami', '津波', ('津波', 'つなみ', '高台')),
    ('typhoon', '台風', ('台風', '直撃', '暴風', '上陸', '風が')),
    ('landslide', '土砂災害', ('土砂', 'がけ', '崖', '山崩れ', '土石流', '地すべり', '地滑り')),
    ('river', '川の氾濫', ('川', '河川', '氾濫', '洪水', '決壊', '水位', '堤防', 'あふれ')),
    ('rain', '大雨', ('雨', '冠水', '浸水', '内水', '道路が')),
    ('shelter', '避難先', ('避難所', '避難場所', 'どこに逃げ', 'どこへ逃げ', 'どこに行', '逃げる場所')),
    ('evacuate', '避難の判断', ('逃げ', '避難', '危ない', '大丈夫', '安全', 'どうすれば', 'どうしたら')),
]
INTENT_LABEL = {k: lab for k, lab, _ in INTENTS}
INTENT_LABEL['when'] = 'いつ・見通し'

# 「いつ」「何時」「10月1日はどう」。台風が出ていれば最接近の時刻で答える（2026-09-28 に来た自由な質問）
WHEN_RE = re.compile(r'いつ|何時|何日|何曜|明日|あした|明後日|あさって|今夜|今晩|今日|週末|見通し|\d+\s*月\s*\d+\s*日|\d+\s*日(は|に|の)')


def intent_of(msg):
    m = msg or ''
    for key, _, words in INTENTS:
        if any(w in m for w in words):
            # 「台風はいつ来る？」は台風の答えに、「電車は明日動く？」は交通の答えに入る（どちらも時刻を答える）
            return key
    if WHEN_RE.search(m):
        return 'when'
    return 'evacuate'


LINKS = {
    'transport': [dict(name='鉄道の運行情報（Yahoo!路線情報）', url='https://transit.yahoo.co.jp/diainfo'),
                  dict(name='道路の交通情報（日本道路交通情報センター）', url='https://www.jartic.or.jp/')],
    'when': [dict(name='気象庁の天気予報', url='https://www.jma.go.jp/bosai/forecast/'),
             dict(name='気象庁の台風情報', url='https://www.jma.go.jp/bosai/map.html#contents=typhoon')],
}


LEVEL_ACTION = {
    5: '命を守る行動をとってください（緊急安全確保）。外へ出るのが危ないときは、建物の2階以上の、崖から離れた部屋へ。',
    4: '危険な場所にいる人は全員、避難してください（避難指示の段階）。',
    3: '高齢の方・体の不自由な方・小さな子のいる家は、避難を始めてください（高齢者等避難の段階）。ほかの人も準備を。',
    2: '避難の準備をしておく段階です。避難先と道順、持ち出す物を確かめてください。',
    0: 'いま、避難が必要な情報は出ていません。',
}

WARN_LEVEL = {'special': 5, 'danger': 4, 'warning': 3, 'advisory': 2}


def _ok(d):
    return isinstance(d, dict) and d.get('status') not in ('unavailable', 'busy')


def _signals(s):
    """警戒レベル相当の材料を並べる。(level, 何が, 出典) のリスト。"""
    sig = []
    fl = s.get('flood') or {}
    al = fl.get('alert') or {}
    if al.get('status') == 'ok' and al.get('max_level'):
        sig.append((int(al['max_level']), f"{al.get('place') or '市区町村'}に避難情報（警戒レベル{al['max_level']}）", al.get('source') or '市区町村'))
    for it in (fl.get('jma') or {}).get('items') or []:
        # 警戒レベル相当になるのは 大雨・洪水・土砂・高潮 と特別警報だけ（雷・強風・波浪・暴風は避難の段階ではない）
        name = it.get('name') or ''
        if it.get('kind') == 'special' or any(w in name for w in ('大雨', '洪水', '土砂', '高潮')):
            lv = WARN_LEVEL.get(it.get('kind'), 0)
            if lv >= 2:
                sig.append((lv, name, '気象庁'))
    kk = s.get('kikikuru') or {}
    for el, v in (kk.get('items') or {}).items():
        if v.get('now', 0) >= 2:
            sig.append((v['now'], f"キキクル {v['label']}：{v['now_label']}（{v['scope']}）", '気象庁'))
    ts = s.get('tsunami') or {}
    if ts.get('local_max'):
        sig.append(({'大津波警報': 5, '津波警報': 4, '津波注意報': 3}[ts['local_max']], ts['local_max'], '気象庁'))
    return sorted(sig, key=lambda x: -x[0])


def _hazard_lines(s):
    """その地点のハザード（平時の想定）。"""
    out = []
    fl = s.get('flood') or {}
    nat = fl.get('national') or {}
    if nat.get('max'):
        out.append(f"洪水の想定：浸水 {nat['max']['label']}（想定最大規模）")
    elif nat.get('status') == 'uncovered':
        out.append('洪水の想定：判定に使うデータに無い地域です（想定なしという意味ではありません）')
    elif _ok(fl) and nat:
        out.append('洪水の想定：浸水想定区域の外')
    if nat.get('collapse'):
        out.append('家屋倒壊等氾濫想定区域：' + '・'.join(x['label'] for x in nat['collapse']) + '（家ごと流される・壊れるおそれ）')
    nai = fl.get('naisui') or {}
    if nai.get('status') == 'inside':
        out.append(f"内水（下水・水路があふれる）の想定：{nai.get('depth_label') or '浸水あり'}")
    tk = fl.get('takashio') or {}
    if tk.get('status') == 'inside':
        out.append(f"高潮の想定：{tk.get('depth_label') or '浸水あり'}")
    d = s.get('dosha') or {}
    if d.get('judged'):
        if d.get('in_hazard_zone'):
            out.append('土砂災害：' + '・'.join(z.get('zone_kind_label', '') for z in d.get('zones') or []) or '土砂災害警戒区域の中')
        else:
            n = (d.get('nearest') or {}).get('distance_m')
            out.append('土砂災害：警戒区域の外' + (f'（最寄りの区域まで約{n}m）' if n is not None else ''))
    t = s.get('tsunami_zone') or {}
    if _ok(t) and 'inundated' in t:
        out.append('津波の想定：' + (f"浸水 {t.get('depth_label')}" if t.get('inundated') else '浸水想定なし')
                   + (f"／この地点の標高 約{t['elevation']['m']}m" if (t.get('elevation') or {}).get('m') is not None else ''))
    return out


def _risky_place(s, intent):
    """この地点が「立ち退くべき場所」か。家屋倒壊・土砂の区域・浸水3m以上・津波浸水。"""
    fl = s.get('flood') or {}
    nat = fl.get('national') or {}
    rank = (nat.get('max') or {}).get('rank') or 0
    d = s.get('dosha') or {}
    t = s.get('tsunami_zone') or {}
    reasons = []
    if nat.get('collapse') and intent in ('river', 'evacuate', 'rain', 'typhoon'):
        reasons.append('家屋倒壊等氾濫想定区域')
    if rank >= 3 and intent in ('river', 'evacuate', 'rain', 'typhoon'):
        reasons.append(f"浸水 {nat['max']['label']} の想定")
    if d.get('in_hazard_zone') and intent in ('landslide', 'evacuate', 'rain', 'typhoon'):
        reasons.append('土砂災害警戒区域')
    if t.get('inundated') and intent in ('tsunami', 'evacuate'):
        reasons.append('津波の浸水想定区域')
    return reasons


def _exposures(s, intent):
    """平時の想定のうち、この質問に関係するものを短く。"""
    fl = s.get('flood') or {}
    nat, nai, tk = fl.get('national') or {}, fl.get('naisui') or {}, fl.get('takashio') or {}
    d, t = s.get('dosha') or {}, s.get('tsunami_zone') or {}
    rel = {'river': ('flood',), 'rain': ('flood', 'naisui', 'dosha'), 'landslide': ('dosha',),
           'tsunami': ('tsunami',), 'typhoon': ('flood', 'takashio', 'dosha')}.get(
        intent, ('flood', 'naisui', 'takashio', 'dosha', 'tsunami'))
    out = []
    if 'flood' in rel and nat.get('max'):
        out.append(f"洪水（浸水 {nat['max']['label']}）")
    if 'naisui' in rel and nai.get('status') == 'inside':
        out.append(f"内水（{nai.get('depth_label') or '浸水あり'}）")
    if 'takashio' in rel and tk.get('status') == 'inside':
        out.append(f"高潮（{tk.get('depth_label') or '浸水あり'}）")
    if 'dosha' in rel and d.get('in_hazard_zone'):
        out.append('土砂災害警戒区域')
    if 'tsunami' in rel and t.get('inundated'):
        out.append(f"津波（浸水 {t.get('depth_label') or 'あり'}）")
    return out


def _filter_signals(sig, intent):
    keys = {
        'river': ('洪水', '河川', '大雨', '避難情報'),
        'rain': ('大雨', '浸水', '洪水', '避難情報'),
        'landslide': ('土砂', '大雨', '避難情報'),
        'tsunami': ('津波', '避難情報'),
        'typhoon': ('暴風', '大雨', '高潮', '波浪', '洪水', '土砂', '避難情報', '浸水'),
    }.get('typhoon' if intent in ('when', 'transport') else intent)
    if not keys:
        return sig
    return [x for x in sig if any(k in x[1] for k in keys)]


def answer(s, msg):
    """規則による答え。返すのは画面に出す文と、どのカードを開くか。"""
    intent = intent_of(msg)
    sig_all = _signals(s)
    sig = _filter_signals(sig_all, intent)
    level = sig[0][0] if sig else 0
    lines, notes = [], []
    risky = _risky_place(s, intent)

    if intent == 'tsunami':
        ts = s.get('tsunami') or {}
        if not _ok(ts):
            lines.append('気象庁の津波情報を取得できませんでした。テレビ・ラジオ・自治体の防災無線を確かめてください。')
        elif ts.get('local'):
            lines.append(f"{s.get('pref') or 'この地域'}の沿岸に{ts['local_max']}が出ています：" + '、'.join(f'{a}（{k}）' for a, k in ts['local'].items()))
            lines.append('海岸・川の河口から離れ、できるだけ高い所へ。津波は繰り返し来ます。解除まで戻らないでください。')
        elif ts.get('active'):
            lines.append('いま津波警報・注意報が出ていますが、この地域の予報区は含まれていません：' + '、'.join(ts['active']))
        else:
            lines.append('いま、津波警報・注意報は出ていません（気象庁）。')
            lines.append('海の近くで強い揺れ、または長い揺れを感じたら、警報を待たずに高い所へ逃げてください。')
    elif intent in ('typhoon', 'when', 'transport'):
        ty = s.get('typhoon') or {}
        storms = ty.get('storms') or []
        if intent == 'transport':
            lines.append('電車・飛行機・道路の運行情報は、この画面には取り込んでいません。下の各社・各機関の情報で確かめてください。'
                         '台風が近づくときは、鉄道会社が前もって計画運休を発表することがあります。')
        if intent == 'when' and not storms:
            lines.append('この画面で時刻まで答えられるのは、台風が近づく時刻だけです。雨の降り始めや強まる時間は、気象庁の天気予報で確かめてください。')
        if not _ok(ty):
            lines.append('気象庁の台風情報を取得できませんでした。')
        elif not storms:
            lines.append('いま、発生中の台風はありません（気象庁）。')
        for st in storms:
            head = f"台風{st['number']}号" + (f"（{st['name']}）" if st['name'] else '')
            desc = f"{head}は{st['location']}にあり、{st['intensity'] + '勢力で' if st['intensity'] and st['intensity'] != '-' else ''}中心気圧{st['pressure']}hPa。"
            lines.append(desc)
            if st.get('in_gale_now'):
                lines.append('この地点は、いま台風の強風域（風速15m/s以上の範囲）に入っています。')
            if st['closest_km'] is not None:
                if (st.get('closest_hours') or 0) <= 1:
                    near = f"いま、この地点から約{st['closest_km']}kmの所まで近づいています（いちばん近い時間帯です）。"
                else:
                    near = f"予報では、{st['closest_at'] or '予報期間の終わり'}にこの地点から約{st['closest_km']}kmまで近づきます。"
                if st['in_probability_circle']:
                    near += '台風の中心が、この地点の上を通る可能性があります（予報円の中）。'
                if st['in_storm_area']:
                    near += '暴風警戒域に入る予報です。'
                elif st.get('storm_km') and st['closest_km'] <= st['storm_km'] + max(50, st['storm_km'] * 0.3):
                    # 境目の近くを「入らない」と言い切らない（予報は外れうる・計算は近似）
                    area = '暴風域' if (st.get('closest_hours') or 0) <= 1 else '暴風警戒域'
                    near += (f"{area}（半径 約{st['storm_km']}km）のすぐ外を通る{'位置です' if area == '暴風域' else '予報です'}。"
                             '進路が少しずれれば暴風域に入ります。入る前提で備えてください。')
                elif st['closest_km'] > 500:
                    near += '暴風警戒域からは離れています。'
                else:
                    near += '暴風警戒域には入らない予報です。'
                lines.append(near)
        wx = [it['name'] for it in ((s.get('flood') or {}).get('jma') or {}).get('items') or []
              if any(w in it.get('name', '') for w in ('暴風', '強風', '波浪', '高潮', '大雨', '洪水', '土砂'))]
        if wx:
            lines.append('この市町村に出ている警報・注意報：' + '、'.join(wx) + '。')
        if storms:
            notes.append('近づく距離は、気象庁の予報円・暴風警戒域の中心と半径を1時間ごとに補間して計算した目安です。正式な範囲は気象庁の台風情報で確かめてください。')
    elif intent == 'landslide':
        kk = ((s.get('kikikuru') or {}).get('items') or {}).get('land')
        if kk:
            lines.append(f"土砂キキクル（この地点）：いま{kk['now_label']}、2時間先まで最大{kk['ahead_label']}。")
    elif intent in ('river', 'rain'):
        items = (s.get('kikikuru') or {}).get('items') or {}
        els = ('flood', 'designated_river', 'inund') if intent == 'river' else ('inund', 'flood')
        shown = [items[e] for e in els if e in items]
        if shown and all(v['ahead'] == 0 for v in shown):
            lines.append('キキクル（' + '・'.join(v['label'] for v in shown) + '）：この地点と周りに、いまも2時間先までも、危険度の色は出ていません。')
        else:
            for v in shown:
                lines.append(f"{v['label']}のキキクル（{v['scope']}）：いま{v['now_label']}、2時間先まで最大{v['ahead_label']}。")
        am = s.get('amedas') or {}
        if am.get('status') == 'ok':
            lines.append(f"雨（アメダス {am['station']}、約{am['distance_km']}km）：1時間 {am['rain1h']}mm・24時間 {am['rain24h']}mm（{am['observed_at']}）。")
        if intent == 'river':
            notes.append('川の水位は、国土交通省「川の防災情報」で最寄りの水位観測所を見てください（この画面には取り込んでいません）。')

    # 結論（どの質問でも最後に付ける）
    if level >= 2:
        lines.insert(0, '【' + '／'.join(x[1] for x in sig[:3]) + '】')
    if intent == 'shelter':
        pass
    elif level >= 4 and risky:
        lines.append(f"この地点は{'・'.join(risky)}にあたります。{LEVEL_ACTION[level]}")
    elif level >= 4:
        lines.append(LEVEL_ACTION[level] + 'この地点は想定上の危険区域ではありませんが、周りの道が危なくなる前に判断してください。')
    elif level == 3 and risky:
        lines.append(f"この地点は{'・'.join(risky)}にあたります。{LEVEL_ACTION[3]}")
    elif level >= 2:
        lines.append(LEVEL_ACTION[level if level in LEVEL_ACTION else 2])
    elif intent in ('typhoon', 'evacuate', 'when', 'transport') and any(
            st.get('in_storm_area') or st.get('in_probability_circle') or st.get('in_gale_now')
            or (st.get('closest_km') or 1e9) <= 300
            for st in (s.get('typhoon') or {}).get('storms') or []):
        lines.append('いまは避難の段階ではありませんが、風が強まる前に、飛ばされそうな物を片付け、停電・断水に備えてください。'
                     '暴風の中の外出や、川・海・崖の見回りはしないでください。')
    else:
        ex = _exposures(s, intent)
        tail = ''
        if ex:
            tail = f"ただし、この地点には {'・'.join(ex)} の想定があります。"
            if risky:
                tail += f"特に{'・'.join(risky)}は、情報が出たら家から離れる（立ち退き避難）が必要な場所です。"
            else:
                tail += '情報が出たら早めに動いてください。'
        lines.append(LEVEL_ACTION[0] + tail)

    near = [x for x in ((s.get('flood') or {}).get('alert') or {}).get('nearby') or [] if x.get('level')]
    if near:
        # 同じ市区町村の一部の地区に出ている発令。住所が地区まで分からないので段階には入れないが、黙らない
        lines.append('同じ市区町村の一部の地区に、避難情報が出ています：'
                     + '、'.join(f"{x.get('target') or '一部の地区'}（警戒レベル{x['level']} {x.get('label') or ''}）" for x in near[:5])
                     + '。この地区にお住まいなら、すぐに避難の判断をしてください。')
    ref = s.get('refuge') or {}
    shelters = (ref.get('shelters') or [])[:3]
    if shelters and (intent == 'shelter' or level >= 3 or intent == 'tsunami'):
        lines.append('近い避難先：' + '、'.join(f"{x['name']}（徒歩{x['walk_minutes']}分）" for x in shelters))
    if (s.get('flood') or {}).get('alert', {}).get('status') in (None, 'uncovered'):
        notes.append('この市区町村の避難情報（避難指示など）は、まだ自動で取り込めていません。市区町村のサイト・防災無線で確かめてください。')
    return dict(intent=intent, intent_label=INTENT_LABEL.get(intent, '避難の判断'), level=level,
                signals=[dict(level=a, what=b, source=c) for a, b, c in sig_all],
                risky=risky, hazards=_hazard_lines(s), lines=lines, notes=notes, links=LINKS.get(intent, []))


def facts_for_ai(s, ans):
    """AI に渡す事実。ここに無いことは言わせない。"""
    f = [f"場所: {s.get('address')}", f"質問の種類: {ans['intent_label']}",
         f"警戒レベル相当（規則で判定）: {ans['level'] or 'なし'}"]
    f += ['判定: ' + x for x in ans['lines']]
    f += ['平時の想定: ' + x for x in ans['hazards']]
    f += ['注意: ' + x for x in ans['notes']]
    return '\n'.join(f)


_SAFE = re.compile(r'[\r\n]{3,}')


def clean_ai(text):
    return _SAFE.sub('\n\n', (text or '').strip())[:600]
