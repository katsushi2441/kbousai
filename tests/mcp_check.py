#!/usr/bin/env python3
"""kbousai_mcp.py を標準入出力で直接叩いて確かめる（kbousai が動いていること）。  /usr/bin/python3 tests/mcp_check.py"""
import json, subprocess, sys, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
reqs = [
    {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'bousai_ask', 'arguments': {'address': '沖縄県南大東村', 'question': '台風は直撃する？'}}},
    {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'bousai_facts', 'arguments': {'lat': 35.1417, 'lon': 136.855}}},
    {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'bousai_ask', 'arguments': {'question': '逃げた方がいい？'}}},
    {'jsonrpc': '2.0', 'id': 6, 'method': 'nope'},
]
p = subprocess.run([sys.executable, os.path.join(HERE, 'kbousai_mcp.py')], input='\n'.join(json.dumps(r, ensure_ascii=False) for r in reqs) + '\n',
                   capture_output=True, text=True, timeout=180)
out = {r['id']: r for r in map(json.loads, p.stdout.splitlines())}
ok = 0
def check(cond, label):
    global ok
    print(('OK  ' if cond else 'NG  ') + label); ok += bool(cond)
    if not cond: sys.exit(1)
check(out[1]['result']['serverInfo']['name'] == 'kbousai', 'initialize')
check(len(out) == 6, '通知には応答しない')
check([t['name'] for t in out[2]['result']['tools']] == ['bousai_ask', 'bousai_facts'], 'tools/list')
t3 = out[3]['result']['content'][0]['text']
check(not out[3]['result']['isError'] and '警戒レベル相当' in t3 and '南大東村' in t3, 'bousai_ask（住所）')
f4 = json.loads(out[4]['result']['content'][0]['text'])
check('名古屋市' in f4['場所'] and '雨（アメダス）' in f4 and 'キキクル' in f4, 'bousai_facts（GPS）')
check(out[5]['result']['isError'] and 'address' in out[5]['result']['content'][0]['text'], '場所なしはエラーで返す')
check(out[6]['error']['code'] == -32601, '知らないメソッド')
print(f'{ok} 件 OK'); print('---'); print(t3)
