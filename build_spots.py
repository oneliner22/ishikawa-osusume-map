# -*- coding: utf-8 -*-
"""石川版スポット定義 -> data/spots.json
YouTube旅Vlog(ヨウヤク堂在庫)から洗い出したスポット。videos は data/videos.json のIDを参照。
座標: Nominatim実測(正確) / 丁目中心+目視オフセット(approx=True)。
"""
import json, io

AREAS = [
    {"id": "higashiyama", "name": "ひがし茶屋街・東山",       "color": "#e8543f"},
    {"id": "kenrokuen",   "name": "兼六園・21美・小立野",     "color": "#3f7fd6"},
    {"id": "omicho",      "name": "近江町・金沢駅周辺",       "color": "#2f9e7d"},
    {"id": "katamachi",   "name": "片町・香林坊",             "color": "#7b5cd6"},
    {"id": "kaga",        "name": "加賀温泉郷（山代・小松）", "color": "#e0489a"},
    {"id": "hakui",       "name": "羽咋・千里浜",             "color": "#b07d2a"},
]

SPOTS = []
def add(slug, name, area, cat, lat, lng, approx, desc, videos):
    SPOTS.append({"slug": slug, "name": name, "area": area, "cat": cat,
                  "lat": lat, "lng": lng, "approx": approx, "desc": desc, "videos": videos})

# ---- ひがし茶屋街・東山 ----
add("higashichaya", "ひがし茶屋街", "higashiyama", "レトロ", 36.5726, 136.6667, False,
    "歴史あるレトロな街並みが魅力の金沢随一の観光名所。浴衣をレンタルして和傘を差しながら散策すると風情倍増。金箔ソフトや金箔かき氷、フルーツ大福など映えスイーツの宝庫。",
    ["IQEjL6koxoU", "fAJonNwHvNI", "Xe50E0cVjSY", "IS1YgB2f1C4", "AeQIsxmDoDQ"])
add("gauche", "茶房＆BAR ゴーシュ", "higashiyama", "カフェ・喫茶", 36.5721, 136.6674, True,
    "ひがし茶屋街の町家にある静かで落ち着いたバー（東山1-16-5）。サイフォン珈琲とウイスキー300種。夜の茶屋街で過ごす大人の時間に。",
    ["78piZBG6C4c"])
add("amiya", "金澤東山 AMIYA", "higashiyama", "グルメ", 36.5716, 136.6660, True,
    "ひがし茶屋街近くの「おでん・輪島ふぐ・のどぐろ AMIYA」（東山1-12-12）。贅沢にのどぐろを敷き詰めた「のどぐろひつまぶし」（約3,080円）が看板。お茶漬けにして二度楽しめる。",
    ["IQEjL6koxoU"])

# ---- 兼六園・21美・小立野 ----
add("kenrokuen", "兼六園", "kenrokuen", "観光", 36.5624, 136.6624, False,
    "日本三名園の一つ。美しい庭園を眺めながら名物「加賀あんころ餅」を抹茶とともにいただくのが定番。名酒の飲み比べができる時期も。",
    ["IQEjL6koxoU", "Xe50E0cVjSY", "fAJonNwHvNI", "AeQIsxmDoDQ"])
add("kanazawajo", "金沢城公園", "kenrokuen", "観光", 36.5658, 136.6594, False,
    "兼六園とセットで巡りたい加賀百万石のシンボル。石川門とお堀の景観が見事。",
    ["IQEjL6koxoU", "Xe50E0cVjSY"])
add("museum21", "金沢21世紀美術館", "kenrokuen", "観光", 36.5608, 136.6582, False,
    "有名な「スイミング・プール」（要予約）やうさぎの椅子など、写真映えするポップな現代アートが並ぶ人気美術館。",
    ["IQEjL6koxoU", "AeQIsxmDoDQ"])
add("library", "石川県立図書館", "kenrokuen", "観光", 36.5487, 136.6804, False,
    "円形劇場のような美しく立体的な大空間。テーマ別のユニークな陳列、作業用デスクやおしゃれなカフェも併設。1日中居たくなる美しさ。",
    ["IS1YgB2f1C4"])
add("dai7gyoza", "第七ギョーザの店", "kenrokuen", "グルメ", 36.5508, 136.6890, False,
    "石川県民のソウルフード（もりの里1-259）。カリカリ・ジューシーな「ホワイト餃子」は一度食べたら病みつき。地元民でも並ぶ人気店。",
    ["78piZBG6C4c"])

# ---- 近江町・金沢駅周辺 ----
add("omicho", "近江町市場", "omicho", "グルメ", 36.5717, 136.6560, False,
    "金沢の台所。朝からカニ（冬は香箱蟹・カニ面）、大ぶりの生牡蠣、ウニ、大トロ、ホタテなどをその場で食べ歩き。サクサクの「近江町コロッケ」も大人気。",
    ["78piZBG6C4c", "LoxqRUcfqRY", "IS1YgB2f1C4", "AeQIsxmDoDQ", "IQEjL6koxoU"])
add("enishi", "鮮彩 えにし", "omicho", "グルメ", 36.5711, 136.6554, False,
    "近江町いちば館2Fにある大口水産直営の海鮮居酒屋（青草町88）。のど黒をまるごと使った「のど黒ひつまぶし」が看板で、3通りの食べ方で楽しめる。",
    ["Xe50E0cVjSY"])
add("morimori", "もりもり寿し 金沢駅前店", "omicho", "グルメ", 36.5793, 136.6498, False,
    "地元でも大行列を作る回転寿司（金沢フォーラス6F）。ガスエビやカニなど新鮮で肉厚な北陸の幸を贅沢に。近江町店など市内に複数店舗あり。",
    ["IQEjL6koxoU", "9jCGPugyhBw"])
add("uan", "雨庵 金沢", "omicho", "宿", 36.5674, 136.6557, True,
    "金沢城近くの和モダンなブティックホテル（尾山町6-30）。掘りごたつのラウンジ、無料のお蕎麦、こだわりのアメニティが魅力。",
    ["IQEjL6koxoU"])

# ---- 片町・香林坊 ----
add("appare", "元祖 金沢炉端 あっぱれ 片町本店", "katamachi", "グルメ", 36.5594, 136.6483, True,
    "金沢おでんの人気店（片町2-2-15 北國ビルB1F）。出汁の染みた大根やバイ貝、冬限定の「カニ面」は絶品。カニの甲羅に熱燗を注ぐ締めの一杯も格別。",
    ["IQEjL6koxoU"])
add("takasago", "おでん 高砂", "katamachi", "グルメ", 36.5608, 136.6503, True,
    "創業昭和11年の金沢おでんの老舗（片町1-3-29）。地元の人に愛され続ける味。カニ面を筆頭に冬の味覚が揃う。",
    ["78piZBG6C4c"])
add("korinkyo", "香林居", "katamachi", "宿", 36.5619, 136.6545, False,
    "香林坊にある蒸留所併設のブティックホテル（片町1-1-31）。サウナ付きのおしゃれな滞在が人気。",
    ["LoxqRUcfqRY"])

# ---- 加賀温泉郷 ----
add("kosoyu", "山代温泉 古総湯", "kaga", "温泉", 36.2890, 136.3615, False,
    "山代温泉のシンボル。明治時代の共同浴場を復元したレトロな温泉で、ステンドグラスと九谷焼タイルが美しい。心まで温まる。",
    ["IQEjL6koxoU"])
add("kaikaga", "星野リゾート 界 加賀", "kaga", "宿", 36.2887, 136.3620, True,
    "古総湯の目の前に建つ温泉旅館（山代温泉18-47）。九谷焼や山中漆器の器で味わう蟹・のどぐろのフルコース、毎晩の加賀獅子舞、館内工房での「金継ぎ」体験も。",
    ["IQEjL6koxoU"])
add("mangetsu", "九谷満月", "kaga", "体験", 36.3040, 136.3528, True,
    "北陸最大級の九谷焼専門店（加賀市中代町ル95-2）。ろくろ・絵付け体験で湯呑み作りに挑戦できる。九谷焼の豆皿やお猪口のお土産選びも。",
    ["IQEjL6koxoU"])
add("yunokuni", "加賀伝統工芸村 ゆのくにの森", "kaga", "体験", 36.3236, 136.4375, False,
    "13万坪の敷地に伝統工芸の体験館が集まるテーマパーク（小松市粟津町ナ3-3）。グラスにイラストを刻むサンドブラスト体験などが楽しめる。",
    ["fAJonNwHvNI"])

# ---- 羽咋・千里浜 ----
add("chirihama", "千里浜なぎさドライブウェイ", "hakui", "自然", 36.8791, 136.7621, False,
    "日本で唯一、車やバイクで波打ち際の砂浜を走れる爽快なドライブコース（全長約8km）。夕日の時間帯は特に絶景。",
    ["Xe50E0cVjSY"])

# ---- 出力 & バリデーション ----
videos = json.load(io.open("data/videos.json", encoding="utf-8"))
missing = [(s["slug"], v) for s in SPOTS for v in s["videos"] if v not in videos]
print("video id not found:", missing if missing else "none")
slugs = [s["slug"] for s in SPOTS]
assert len(slugs) == len(set(slugs)), "duplicate slug"
areas = {a["id"] for a in AREAS}
assert all(s["area"] in areas for s in SPOTS), "unknown area"

json.dump({"areas": AREAS, "spots": SPOTS},
          io.open("data/spots.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("spots:", len(SPOTS), "areas:", len(AREAS),
      "videos used:", len({v for s in SPOTS for v in s['videos']}))
