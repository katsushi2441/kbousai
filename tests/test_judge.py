# -*- coding: utf-8 -*-
"""規則の確認。実データに頼らず、作った snapshot で結論を固定する。  .venv/bin/python -m pytest -q tests"""
from app import judge, sources


def snap(**kw):
    s = dict(address='愛知県名古屋市中川区', pref='愛知県', flood=dict(
        national=dict(status='inside', max=dict(rank=2, label='0.5m以上3.0m未満'), collapse=[]),
        naisui={}, takashio={}, alert=dict(status='ok', items=[], max_level=None, place='中川区野田学区'),
        jma=dict(status='ok', items=[])), dosha=dict(judged=True, in_hazard_zone=False, nearest=dict(distance_m=900)),
        tsunami_zone=dict(inundated=False, elevation=dict(m=5.0)), refuge=dict(shelters=[
            dict(name='野田小学校', walk_minutes=5, distance_m=400)]),
        amedas=dict(status='ok', station='名古屋', distance_km=3.1, rain10m=0, rain1h=0, rain3h=0, rain24h=0, observed_at='x'),
        kikikuru=dict(status='ok', items={}), typhoon=dict(status='ok', storms=[]),
        tsunami=dict(status='ok', active={}, local={}, local_max=None))
    for k, v in kw.items():
        s[k] = v
    return s


def test_intent():
    assert judge.intent_of('川が氾濫しそう？') == 'river'
    assert judge.intent_of('津波は来る？') == 'tsunami'
    assert judge.intent_of('台風は直撃する？') == 'typhoon'
    assert judge.intent_of('裏の崖が心配') == 'landslide'
    assert judge.intent_of('近くの避難所は？') == 'shelter'
    assert judge.intent_of('逃げた方がいい？') == 'evacuate'
    assert judge.intent_of('') == 'evacuate'


def test_thunder_is_not_an_evacuation_level():
    s = snap()
    s['flood']['jma']['items'] = [dict(code='14', name='雷注意報', kind='advisory')]
    assert judge.answer(s, '逃げた方がいい？')['level'] == 0


def test_heavy_rain_danger_warning_is_level4():
    s = snap()
    s['flood']['jma']['items'] = [dict(code='43', name='レベル4大雨危険警報', kind='danger')]
    a = judge.answer(s, '逃げた方がいい？')
    assert a['level'] == 4
    assert any('全員' in x for x in a['lines'])


def test_city_order_outranks_and_risky_place_named():
    s = snap()
    s['flood']['alert'].update(max_level=4, items=[dict(level=4, label='避難指示')])
    s['flood']['national']['collapse'] = [dict(label='氾濫流')]
    a = judge.answer(s, '川が氾濫しそう？')
    assert a['level'] == 4 and '家屋倒壊等氾濫想定区域' in a['risky']
    assert any('野田小学校' in x for x in a['lines'])


def test_kikikuru_purple_counts():
    s = snap(kikikuru=dict(status='ok', items=dict(land=dict(label='土砂災害', now=4, ahead=4, now_label='危険（紫）',
                                                          ahead_label='危険（紫）', scope='この地点'))))
    assert judge.answer(s, '土砂崩れは大丈夫？')['level'] == 4
    # 土砂の危険は、津波の質問の段階には入れない
    assert judge.answer(s, '津波は来る？')['level'] == 0


def test_tsunami_warning_local():
    s = snap(tsunami=dict(status='ok', active={'愛知県外海': '津波警報'}, local={'愛知県外海': '津波警報'}, local_max='津波警報'))
    a = judge.answer(s, '津波は来る？')
    assert a['level'] == 4 and any('高い所' in x for x in a['lines'])


def test_unavailable_is_not_none():
    s = snap(tsunami=dict(status='unavailable'))
    a = judge.answer(s, '津波は来る？')
    assert any('取得できませんでした' in x for x in a['lines'])


def test_typhoon_edge_is_not_called_safe():
    st = dict(number='26', name='スリゲ', category='台風', intensity='非常に強い', pressure='945', max_wind='50',
              location='南大東島の北西約140km', issued='', closest_km=120, closest_at='09月28日 09時ごろ',
              closest_hours=5, storm_km=119, in_storm_area=False, in_probability_circle=False, url='')
    a = judge.answer(snap(typhoon=dict(status='ok', storms=[st])), '台風は直撃する？')
    assert any('すぐ外' in x for x in a['lines'])
    assert not any('入らない予報' in x for x in a['lines'])


def test_pixel_levels_match_jma_legend():
    assert sources._pixel_level((0xaa, 0x00, 0xaa, 255)) == 4
    assert sources._pixel_level((0xff, 0x28, 0x00, 255)) == 3
    assert sources._pixel_level((0xf2, 0xe7, 0x00, 255)) == 2
    assert sources._pixel_level((0x0c, 0x00, 0x0c, 255)) == 5
    assert sources._pixel_level((0x80, 0xff, 0xff, 255)) == 0   # 水色（今後の情報に留意）は段階に入れない
    assert sources._pixel_level((0, 0, 0, 0)) == 0


def test_typhoon_passing_now_inside_gale():
    """2026-09-28 06時の南大東村（実測）: 約113km・暴風域85km・強風域の中。『入らない・避難不要』だけで終わらせない。"""
    st = dict(number='26', name='スリゲ', category='台風', intensity='非常に強い', pressure='945', max_wind='50',
              location='南大東島の北西約120km', issued='', closest_km=113, closest_at='09月28日 06時ごろ',
              closest_hours=0, storm_km=85, in_storm_area=False, in_probability_circle=False, in_gale_now=True, url='')
    a = judge.answer(snap(typhoon=dict(status='ok', storms=[st])), '台風は直撃する？')
    txt = ''.join(a['lines'])
    assert '強風域' in txt and 'いま、この地点から約113km' in txt
    assert '入らない予報' not in txt
    assert '停電' in txt


def test_nearby_order_in_same_city_is_mentioned():
    s = snap()
    s['flood']['alert']['nearby'] = [dict(level=4, label='避難指示', target='日吉本町3丁目の一部')]
    a = judge.answer(s, '逃げた方がいい？')
    assert a['level'] == 0
    assert any('日吉本町3丁目の一部' in x and '警戒レベル4' in x for x in a['lines'])
