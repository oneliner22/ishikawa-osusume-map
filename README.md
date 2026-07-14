# 石川・金沢おすすめMAP 〜YouTube旅Vlogから〜

YouTubeの旅Vlog 8本から洗い出した石川県（金沢・加賀・羽咋）のおすすめスポットを、
エリア別に色分けした地図＋一覧にまとめた単一HTMLサイト。
スポットをクリックすると、実際に訪れている紹介動画（YouTube埋め込み）がモーダルで見られる。

公開URL: https://oneliner22.github.io/ishikawa-osusume-map/

## 構成

- `index.html` — 生成物（データ埋め込み済み単一ファイル、file:// でも動く）
- `template.html` — テンプレート（Leaflet + markercluster、YouTube埋め込みモーダル）
- `build_spots.py` — スポット定義（エリア/カテゴリ/座標/説明/出典動画ID）→ `data/spots.json`
- `build_html.py` — `data/*.json` + `template.html` → `index.html`
- `data/videos.json` — 出典YouTube動画（ID → タイトル/チャンネル）
- `data/config.json` — タイトル・リード文・地図中心/ズーム等

## ビルド

```
python build_spots.py
python build_html.py
```

## 出典

スポット情報は以下の旅Vlogに基づく（動画の著作権は各チャンネルに帰属）:
東海オンエア / ponz pon! / なぐもふうか / なかはらちゃんねる / まめとだいふく / 古田愛理 / HOWELL / かっぱちゃんねる

座標は OpenStreetMap Nominatim / 公式サイト等で裏取り。番地が確定できないものは「およその位置」と明記。
