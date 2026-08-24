# 石川・金沢おすすめMAP 〜YouTube旅Vlog & Xのファン投稿から〜

石川県（金沢・加賀・羽咋）のおすすめスポットを、エリア別に色分けした地図＋一覧にまとめた静的サイト。
スポットをクリックすると出典（YouTube紹介動画の埋め込み / Xポストへのリンク）がモーダルで見られる。

出典は2系統:

1. **YouTube旅Vlog 8本**（初期データ、手動で洗い出し）
2. **Xの「#ぽこピーの回覧板」石川公演 関連のおすすめ投稿**（日次自動収集、下記パイプライン）

公開URL: https://oneliner22.github.io/ishikawa-osusume-map/

## 構成

- `index.html` — アプリ本体。`data/*.json` を実行時に fetch して描画（ビルド工程なし）
- `data/spots.json` — **スポットデータの正本**（エリア/カテゴリ/座標/説明/出典）
- `data/videos.json` — YouTube出典のメタ情報（動画ID → タイトル/チャンネル）
- `data/config.json` — タイトル・リード文・地図中心/ズーム等
- `data/pipeline.json` — 自動収集パイプラインの設定（クエリ/bbox/受入ゲート/モデル）
- `data/ledger.json` — 処理済みXポストID・著者判定のキャッシュ（二重入稿防止）
- `data/aliases.json` — 略称→正規スポット名（「21美」→「金沢21世紀美術館」等）
- `data/pending.json` — 受入ゲート不合格で保留になった候補（地図には出ない）
- `validate.py` — データ整合性チェック（`python validate.py`）

`spots.json` のスポットは `sources` 配列で出典を持つ:

```json
{"type": "youtube", "id": "IQEjL6koxoU"}
{"type": "x", "url": "https://x.com/<handle>/status/<id>", "author": "<handle>", "date": "2026-07-31", "quote": "..."}
```

X出典のURLは必ず **正規形**（`https://x.com/<handle>/status/<id>`）で持つ。
`https://x.com/i/web/status/<id>` は X 側のリダイレクト頼みで、投稿者が年齢制限付き
アカウントだと未ログイン閲覧者にリダイレクトが解決されず X の404が出る
（著者ハンドルが取れなかった場合のみこの形式にフォールバックする。validate.py が警告する）。

`"embed": false` が付いた出典は、投稿者のアカウント設定（年齢制限）により
埋め込みも未ログイン閲覧もできないポスト。X の oEmbed が 403 を返すかどうかで
日次ジョブが毎日判定し直す（可否は投稿者の設定変更で変わるため）。
地図側は埋め込みを試みず、引用カードに注記を出す。

自動追加スポットは任意で `address` / `hours` / `url` / `place_id` / `added` / `out_of_pref` を持つ。

## ローカルプレビュー

fetch を使うため file:// では動かない。リポジトリ直下で:

```
python -m http.server
# → http://localhost:8000/
```

編集後は `python validate.py` で整合性チェック。

## 自動収集パイプライン（Cloud Run Jobs）

日次で以下を実行し、合格スポットを `spots.json` に直接コミットする（人手レビューなし）:

```
Cloud Scheduler → Cloud Run Job (GCP: salmon-chan)
 1. xdev で X を検索 (回覧板 (金沢 OR 石川) -is:retweet)、台帳にない新規ポストを取得
 2. 添付画像をダウンロード（おすすめリストは画像内記載が主流）
 3. Gemini (flash lite) が本文+全画像からスポット候補を抽出
 3b. 二段階目: 適格(候補あり・著者fan)となった投稿について「本人の続き投稿」
    (自分のリプ・自己引用RT。単体ではキーワードに合致しないことが多い) を
    conversation_id / url: 検索で同run内に収穫し、3 と同じ抽出にかけて合流させる
    (引用の引用は続き投稿を新起点に最大3周。日をまたぐ監視はしない)
 4. aliases + 既存スポットと照合。既存なら sources に言及を追記
 5. Google Places API で裏取り（実在/正規名称/住所/座標/営業時間/営業状況）
 6. 受入ゲート（コード強制）:
    - Places 一致（Gemini pro が同一性を判定）
    - business_status = OPERATIONAL
    - マージン付きbbox内 (lat 35.8-38.1 / lng 135.9-137.7)
    - 著者がbotでない（投稿単体判定→曖昧なら from: 検索、著者単位でキャッシュ）
    - 日次300件のサーキットブレーカー（超過時は全停止+Issue起票）
 7. 不合格は pending.json へ。合格分を commit & push（GitHub Pages が自動配信）
```

誤入稿時は `sources` に由来が残っているため `git revert` で戻せる。

### 日次 pending 整理（毎日 7:40 JST、日次ジョブ完了後）

日次ジョブのワンショット判定で保留になった候補（表記揺れ・同名多店舗など）を、
Gemini のツールループ（Places再検索・出典ポスト再読）で精査して回収する:

- 掲載可能 → `spots.json` へ登録 / 既存スポットへ出典追記（名寄せ）
- 表記揺れ → `aliases.json` に登録して再発防止
- 閉業・県外・ノイズ → pending から削除
- 判断不能 → `needs_human` を付けて pending に残す（人間へエスカレーション）

日次ジョブと同じく、掲載可否の最終判定（place_id の実在根拠・営業状況・bbox）は
コード側で強制する。

実装は `pipeline/` 配下:

- `daily_job.py` — 日次ジョブ本体（上記フローを1プロセスで実行）
- `pending_resolver.py` — 日次 pending 整理ジョブ（daily_job のヘルパーを流用）
- `mcp_client.py` — xdev MCP (streamable HTTP) の最小クライアント
- `refresh_hours.py` — 営業時間を週7日ぶんに入れ直す一回きりのジョブ（place_id から
  Place Details を引き直す）。以前は先頭2日だけ保存しており、Places が月曜始まりで
  返すため全店が「月火だけ営業」に見えていた
- `deploy.sh` — salmon-chan への初回デプロイ一式（API有効化/Secret/ビルド/ジョブ/スケジューラ）。
  `GITHUB_TOKEN_VALUE` と `XDEV_MCP_URL_VALUE` を環境変数で渡して実行

運用コマンド:

```
# 手動実行
gcloud run jobs execute ishikawa-spots-daily --region asia-northeast1 --project central-bulwark-427114-j7 --wait
# ログ確認
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=ishikawa-spots-daily' --project central-bulwark-427114-j7 --limit 50 --format 'value(textPayload)'

# 単発スクリプトを既存ジョブのイメージで走らせる (pending ジョブは --command python なので args だけ差し替わる)
gcloud builds submit pipeline --tag asia-northeast1-docker.pkg.dev/central-bulwark-427114-j7/ishikawa-spots/daily:latest --project central-bulwark-427114-j7
gcloud run jobs update ishikawa-spots-pending --region asia-northeast1 --project central-bulwark-427114-j7 --image asia-northeast1-docker.pkg.dev/central-bulwark-427114-j7/ishikawa-spots/daily:latest
gcloud run jobs execute ishikawa-spots-pending --region asia-northeast1 --project central-bulwark-427114-j7 --args refresh_hours.py --wait
```

失敗・サーキットブレーカー・validate 不合格時は GitHub Issue が自動起票される。

## 出典・クレジット

スポット情報は以下の旅Vlogおよび X のファン投稿に基づく（著作権は各投稿者に帰属）:
東海オンエア / ponz pon! / なぐもふうか / なかはらちゃんねる / まめとだいふく / 古田愛理 / HOWELL / かっぱちゃんねる

座標は Google Places / OpenStreetMap Nominatim / 公式サイト等で裏取り。番地が確定できないものは「およその位置」と明記。
