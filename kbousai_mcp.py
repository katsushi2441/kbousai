#!/usr/bin/env python3
"""kbousai の MCP サーバー（stdio・Python 標準ライブラリだけ）。

AIアシスタントやAIエージェントが、防災の質問に「自分の記憶」ではなく、その場所のいまの公開データで答えられるようにする。
中身は kbousai の HTTP API（/api/ask）を呼ぶだけ。**逃げるかどうかの結論は kbousai の規則が決めたもの**で、
このサーバーもAIも結論を変えない。書き込みはしない。

  claude mcp add kbousai -- python3 /path/to/kbousai_mcp.py
  環境変数 KBOUSAI_API … kbousai の場所（既定 http://127.0.0.1:18393/）
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get('KBOUSAI_API', 'http://127.0.0.1:18393/').rstrip('/') + '/'
VERSION = '1.0.0'

PLACE = {
    'address': {'type': 'string', 'description': '住所（例: 愛知県名古屋市中川区尹田町）。lat/lon を渡すときは不要'},
    'lat': {'type': 'number', 'description': '緯度（GPS）'},
    'lon': {'type': 'number', 'description': '経度（GPS）'},
}
TOOLS = [
    {'name': 'bousai_ask',
     'description': '日本の住所か緯度経度について、防災の質問（逃げた方がいい？／川が氾濫しそう？／津波は来る？／台風は直撃する？／'
                    '土砂崩れは大丈夫？／近くの避難所は？）に答える。警戒レベル相当と、いまやることを規則で判定した結果を返す。'
                    '取得できなかった情報は「無い」ではなく「取得できない」と返すので、そのまま利用者に伝えること。',
     'inputSchema': {'type': 'object', 'required': ['question'],
                     'properties': dict(PLACE, question={'type': 'string', 'description': '利用者の質問そのまま'})}},
    {'name': 'bousai_facts',
     'description': 'その場所の防災の事実だけを返す（ハザード・気象庁の警報・アメダスの雨量・キキクル・台風との距離・津波警報・'
                    '市区町村の避難情報・近い指定緊急避難場所）。それぞれに時点と出典が付く。判断はしない。',
     'inputSchema': {'type': 'object', 'properties': PLACE}},
]


def call_api(a, question):
    q = {'msg': question or '逃げた方がいい？'}
    if a.get('lat') is not None and a.get('lon') is not None:
        q.update(lat=a['lat'], lon=a['lon'])
    elif a.get('address'):
        q['q'] = a['address']
    else:
        raise ValueError('address か lat/lon を渡してください')
    req = urllib.request.Request(API + 'api/ask?' + urllib.parse.urlencode(q), headers={'User-Agent': 'kbousai-mcp/' + VERSION})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get('detail')
        except Exception:  # noqa: BLE001
            msg = None
        raise ValueError(msg or f'kbousai が {e.code} を返しました')


def facts(s):
    """snapshot を、AI が読みやすい短い事実のまとまりにする。"""
    fl = s.get('flood') or {}
    j = fl.get('jma') or {}
    al = fl.get('alert') or {}
    am = s.get('amedas') or {}
    kk = s.get('kikikuru') or {}
    ty = s.get('typhoon') or {}
    ts = s.get('tsunami') or {}
    rf = s.get('refuge') or {}
    return {
        '場所': s.get('address'), '時点': s.get('checked_at'),
        # 他の MCP（国土交通データプラットフォームなど）で周りのデータを探すときは、推測せずこの点を使ってもらう
        '緯度経度': {'lat': s.get('lat'), 'lon': s.get('lon'), '説明': '住所から求めた地点（国土地理院）。周りの地図データを探すときはこの点を使う'},
        '警報・注意報': {'状態': j.get('status'), '発表中': [i['name'] for i in j.get('items') or []],
                    '発表時刻': j.get('report_at'), '出典': '気象庁'},
        '市区町村の避難情報': ({'状態': '取得済み', '地域': al.get('place'),
                          '発令': [f"警戒レベル{i.get('level')} {i.get('label')}" for i in al.get('items') or []],
                          '出典': al.get('source')} if al.get('status') == 'ok'
                         else {'状態': '取得できない（この市区町村は自動で取り込めていない）'}),
        '雨（アメダス）': ({'観測所': am.get('station'), '距離km': am.get('distance_km'), '1時間mm': am.get('rain1h'),
                       '24時間mm': am.get('rain24h'), '時点': am.get('observed_at')} if am.get('status') == 'ok'
                      else {'状態': '取得できない'}),
        'キキクル': ({v['label']: {'いま': v['now_label'], '2時間先まで最大': v['ahead_label'], '範囲': v['scope']}
                   for v in (kk.get('items') or {}).values()} if kk.get('status') == 'ok' else {'状態': '取得できない'}),
        '台風': ([{'名前': f"台風{t['number']}号 {t['name']}", '位置': t['location'], '中心気圧hPa': t['pressure'],
                 '最接近': t['closest_at'] or 'いま', '最接近の距離km': t['closest_km'],
                 '暴風警戒域に入る': t['in_storm_area'], 'いま強風域の中': t.get('in_gale_now')}
                for t in ty.get('storms') or []] if ty.get('status') == 'ok' else '取得できない'),
        '津波警報・注意報': ({'この地域': ts.get('local') or 'なし', '全国で発表中': list((ts.get('active') or {}).keys())}
                     if ts.get('status') == 'ok' else '取得できない'),
        '近い避難先': [f"{x['name']}（徒歩{x['walk_minutes']}分）" for x in (rf.get('shelters') or [])[:5]],
        '川の水位': '取り込んでいない（国土交通省「川の防災情報」が定期的な自動収集を控えるよう求めているため）。'
                 'https://www.river.go.jp/ で確認',
    }


def run(name, a):
    if name == 'bousai_ask':
        d = call_api(a, a.get('question'))
        ans = d['answer']
        sn = d['snapshot']
        text = [f"場所: {sn.get('address')}（{sn.get('checked_at')} 時点）・緯度 {sn.get('lat')} 経度 {sn.get('lon')}（住所から求めた地点）",
                f"警戒レベル相当: {ans['level'] or 'なし'}（規則で判定。変えずに伝えること）", '']
        text += ans['lines']
        if ans['hazards']:
            text += ['', '平時の想定:'] + ['・' + x for x in ans['hazards']]
        if ans['notes']:
            text += ['', '注意:'] + ['・' + x for x in ans['notes']]
        if ans.get('links'):
            text += ['', '確かめる先:'] + [f"・{l['name']} {l['url']}" for l in ans['links']]
        text += ['', '出典: 気象庁・国土数値情報・国土地理院・市区町村（Kurage 防災AIチャット）']
        return '\n'.join(text)
    if name == 'bousai_facts':
        d = call_api(a, '逃げた方がいい？')
        return json.dumps(facts(d['snapshot']), ensure_ascii=False, indent=1)
    raise ValueError(f'知らないツールです: {name}')


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if 'id' not in req:
            continue
        rid, method, p = req['id'], req.get('method', ''), req.get('params') or {}
        res, err = None, None
        if method == 'initialize':
            res = {'protocolVersion': p.get('protocolVersion', '2025-06-18'), 'capabilities': {'tools': {}},
                   'serverInfo': {'name': 'kbousai', 'version': VERSION}}
        elif method == 'ping':
            res = {}
        elif method == 'tools/list':
            res = {'tools': TOOLS}
        elif method == 'tools/call':
            try:
                res = {'content': [{'type': 'text', 'text': run(p.get('name', ''), p.get('arguments') or {})}], 'isError': False}
            except Exception as e:  # noqa: BLE001
                res = {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
        else:
            err = {'code': -32601, 'message': f'Method not found: {method}'}
        out = {'jsonrpc': '2.0', 'id': rid}
        out['error' if err else 'result'] = err or res
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
