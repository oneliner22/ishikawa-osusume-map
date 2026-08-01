# -*- coding: utf-8 -*-
"""日次入稿ジョブ (Cloud Run Jobs)。

X検索(xdev) → 画像取得 → Gemini抽出 → bot判定 → Places裏取り →
受入ゲート → data/*.json 更新 → commit/push。詳細は README の
「自動収集パイプライン」参照。人手レビューなしで運用するため、
掲載可否は必ずコード側のゲート (gate 関数) で強制する。

必要な環境変数:
  GITHUB_REPO   owner/name (例 oneliner22/ishikawa-osusume-map)
  GITHUB_TOKEN  push / Issue 起票用
  XDEV_MCP_URL  xdev MCP エンドポイント (認証キー込み)
  PLACES_API_KEY
  GCP_PROJECT / VERTEX_LOCATION (既定 global)
  MODEL_EXTRACT / MODEL_JUDGE (既定は pipeline.json 参照)
  DRY_RUN=1 で push しない (差分はログに出す)
"""
import difflib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date

import requests
from google import genai
from mcp_client import McpClient
from datetime import timedelta

REPO = os.environ["GITHUB_REPO"]
TOKEN = os.environ["GITHUB_TOKEN"]
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
TODAY = date.today().isoformat()

CATS = ["グルメ", "温泉", "カフェ・喫茶", "観光", "レトロ", "雑貨・土産",
        "自然", "動物", "体験", "宿"]
AREA_PALETTE = ["#5c8f3f", "#c2543f", "#3f6fa8", "#a8623f", "#6f3fa8", "#3fa89b"]

client = genai.Client(
    vertexai=True, project=os.environ.get("GCP_PROJECT"),
    location=os.environ.get("VERTEX_LOCATION", "global"))
MODEL_EXTRACT = os.environ.get("MODEL_EXTRACT", "gemini-3.5-flash-lite")
MODEL_JUDGE = os.environ.get("MODEL_JUDGE", "gemini-3.1-pro-preview")


def log(*a):
    print(*a, flush=True)


def gen_json(model, schema, parts):
    """構造化出力つき Gemini 呼び出し。parts は str / (bytes, mime) の混在リスト。"""
    contents = []
    for p in parts:
        if isinstance(p, str):
            contents.append(p)
        else:
            contents.append(genai.types.Part.from_bytes(data=p[0], mime_type=p[1]))
    res = client.models.generate_content(
        model=model, contents=contents,
        config={"response_mime_type": "application/json", "response_schema": schema,
                "temperature": 0})
    return json.loads(res.text)


# ---------------- リポジトリ入出力 ----------------

def clone_repo(workdir):
    url = f"https://x-access-token:{TOKEN}@github.com/{REPO}.git"
    subprocess.run(["git", "clone", "--depth", "1", url, workdir],
                   check=True, capture_output=True)


def load(workdir, name):
    return json.load(io.open(os.path.join(workdir, "data", name), encoding="utf-8"))


def save(workdir, name, obj):
    json.dump(obj, io.open(os.path.join(workdir, "data", name), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def commit_if_changed(workdir, msg):
    subprocess.run(["git", "-C", workdir, "config", "user.name", "oneliner22"], check=True)
    subprocess.run(["git", "-C", workdir, "config", "user.email",
                    "oneliner22@users.noreply.github.com"], check=True)
    subprocess.run(["git", "-C", workdir, "add", "data"], check=True)
    diff = subprocess.run(["git", "-C", workdir, "diff", "--cached", "--stat"],
                          capture_output=True, encoding="utf-8",
                          errors="replace").stdout.strip()
    if not diff:
        log("no changes")
        return
    log(diff)
    if DRY_RUN:
        log("DRY_RUN: skip commit/push")
        return
    subprocess.run(["git", "-C", workdir, "commit", "-m", msg], check=True)
    subprocess.run(["git", "-C", workdir, "push"], check=True)
    log("pushed")


def github_issue(title, body):
    r = requests.post(f"https://api.github.com/repos/{REPO}/issues",
                      headers={"Authorization": f"Bearer {TOKEN}"},
                      json={"title": title, "body": body}, timeout=30)
    log("issue:", r.status_code, title)


# ---------------- 収集 ----------------

def fetch_posts(mcp, ledger, query, max_posts=200, include_refs=False):
    """query を ingest し、台帳未処理の投稿を返す。include_refs=True で reply/引用も含む。"""
    ing = mcp.call("x_ingest", {"query": query, "max_posts": max_posts})
    dataset = ing.get("dataset") if isinstance(ing, dict) else None
    if not dataset:
        raise RuntimeError(f"x_ingest から dataset を特定できない: {ing}")
    ref_cond = "" if include_refs else "AND t.ref_type IS NULL "
    # media_urls は ingest 時期によって NULL の区画があるため、同一IDの別区画から補完する
    rows = mcp.call("run_sql", {"max_rows": 500, "query":
        "SELECT t.id, t.created_at, t.author_id, t.author_name, t.author_followers, "
        "t.text, COALESCE(t.media_urls, mm.mu) media_urls, t.like_count, t.reply_count "
        "FROM tweets t LEFT JOIN (SELECT id, arg_max(media_urls, ingested_at) mu "
        "FROM tweets WHERE media_urls IS NOT NULL GROUP BY id) mm ON mm.id = t.id "
        f"WHERE t.dataset='{dataset}' {ref_cond}"
        "ORDER BY t.created_at DESC"})
    posts = rows.get("rows", rows) if isinstance(rows, dict) else rows
    if posts and isinstance(posts[0], list):  # 列配列形式への保険
        cols = rows.get("columns", [])
        posts = [dict(zip(cols, r)) for r in posts]
    return [p for p in posts if str(p["id"]) not in ledger["processed_posts"]]


ASK_SCHEMA = {"type": "object", "properties": {
    "is_seed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["is_seed"]}


def add_seed(ledger, pid, kind, author, base_date, ttl_days):
    if pid in ledger["seeds"]:
        return
    until = (date.fromisoformat(base_date) + timedelta(days=ttl_days)).isoformat()
    ledger["seeds"][pid] = {"kind": kind, "author": author,
                            "date": base_date, "until": until}
    log(f"seed added: {pid} ({kind}, {author}, until {until})")


def watch_official(mcp, ledger, rh):
    """公式アカウントの投稿を監視し、おすすめ募集らしき投稿をシード化。投稿自体も処理対象として返す。"""
    accounts = rh.get("official_accounts", [])
    if not accounts:
        return []
    q = " OR ".join(f"from:{a}" for a in accounts)
    posts = fetch_posts(mcp, ledger, f"({q})" if len(accounts) > 1 else q,
                        max_posts=50, include_refs=True)
    for p in posts:
        j = gen_json(MODEL_EXTRACT, ASK_SCHEMA, [
            "以下はぽこピー(ぽんぽこ・ピーナッツくん)公式アカウントのX投稿です。"
            "石川公演「ぽこピーの回覧板」に関連して、ファンにおすすめスポット・グルメ等の"
            "情報提供を呼びかけたり質問したりする投稿(そのreplyや引用RTにおすすめ情報が"
            "集まりそうな投稿)かを判定してください。\n"
            f"投稿: {p.get('text', '')}"])
        if j.get("is_seed"):
            add_seed(ledger, str(p["id"]), "official_ask", p.get("author_name", ""),
                     str(p.get("created_at", ""))[:10] or TODAY, rh.get("seed_ttl_days", 35))
    return posts


def harvest_seeds(mcp, ledger, rh):
    """有効なシードの reply・引用RTを収穫する。"""
    active = [(pid, s) for pid, s in ledger["seeds"].items() if s["until"] >= TODAY]
    active.sort(key=lambda kv: kv[1]["date"], reverse=True)
    active = active[:rh.get("max_active_seeds", 25)]
    harvested = []
    for pid, s in active:
        try:
            harvested += fetch_posts(
                mcp, ledger, f"(conversation_id:{pid} OR url:{pid}) -is:retweet",
                max_posts=50, include_refs=True)
        except Exception as e:
            log("harvest skip:", pid, repr(e))
    ledger["seeds"] = {pid: s for pid, s in ledger["seeds"].items()
                       if s["until"] >= TODAY}
    return harvested, len(active)


def as_url_list(v):
    """run_sql の VARCHAR[] は list でも文字列表現でも返り得るため正規化する。"""
    if isinstance(v, list):
        return [u for u in v if isinstance(u, str) and u.startswith("http")]
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [u for u in parsed if isinstance(u, str) and u.startswith("http")]
        except ValueError:
            pass
        return re.findall(r"https?://[^\s'\"\],]+", v)
    return []


def download_images(media_urls, limit=8):
    images = []
    for u in as_url_list(media_urls)[:limit]:
        try:
            r = requests.get(u, timeout=30)
            mime = r.headers.get("content-type", "")
            if r.ok and mime.startswith("image/") and len(r.content) < 10_000_000:
                images.append((r.content, mime.split(";")[0]))
        except requests.RequestException as e:
            log("image skip:", u, e)
    return images


# ---------------- 抽出・判定 ----------------

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_recommendation": {"type": "boolean"},
        "candidates": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "hint": {"type": "string"},
                "quote": {"type": "string"},
            }, "required": ["name"]}},
    }, "required": ["is_recommendation", "candidates"]}


def extract_spots(post, images):
    parts = [
        "以下はX(旧Twitter)の投稿です。「#ぽこピーの回覧板」石川公演(金沢)に向けた"
        "石川県・北陸のおすすめスポット紹介かどうかを判定し、紹介されている具体的な"
        "スポット(店・施設・観光地)を漏れなく抽出してください。\n"
        "- おすすめリストは本文ではなく添付画像内に書かれていることが多い。画像を必ず読むこと。\n"
        "- 【最重要】本文または画像に実際に名前が記載されているスポットのみを抽出すること。"
        "「金沢のおすすめ」という文脈から定番観光地を推測・補完することは厳禁。"
        "名前の記載がなければ candidates は空にする。\n"
        "- name はスポットの正式名称に最も近い表記。hint は住所・エリア・ジャンルなど"
        "特定の手がかり。quote は投稿者の実際の記述の抜粋(30字程度)。実際の記述が"
        "なければ空文字にする。創作・脚色は厳禁。\n"
        "- 一般名詞(「海鮮丼」「温泉」等)や県外が明らかなスポットは含めない。\n"
        f"本文: {post.get('text', '')}"]
    parts += images
    return gen_json(MODEL_EXTRACT, EXTRACT_SCHEMA, parts)


GROUND_SCHEMA = {"type": "object", "properties": {
    "grounded_names": {"type": "array", "items": {"type": "string"}}},
    "required": ["grounded_names"]}


def ground_candidates(post, images, candidates):
    """抽出候補が投稿(本文+画像)に実際に記載されているか検証し、記載のあるものだけ残す。
    文脈からの推測で定番スポットが捏造されるのを防ぐ二重チェック。"""
    if not candidates:
        return candidates
    names = [c["name"] for c in candidates]
    parts = [
        "以下のX投稿(本文+添付画像)に、候補リストの各スポット名が【実際に文字として記載"
        "されているか】を確認してください。表記ゆれ・略称は同一とみなしてよいが、"
        "記載がないものを文脈や一般常識から「ありそう」と補完することは厳禁。\n"
        f"候補: {json.dumps(names, ensure_ascii=False)}\n"
        f"本文: {post.get('text', '')}\n"
        "実際に記載が確認できた候補名のみを grounded_names にそのまま列挙すること。"]
    parts += images
    j = gen_json(MODEL_EXTRACT, GROUND_SCHEMA, parts)
    ok = set(j.get("grounded_names", []))
    kept = [c for c in candidates if c["name"] in ok]
    if len(kept) < len(candidates):
        dropped = [c["name"] for c in candidates if c["name"] not in ok]
        log("grounding dropped:", dropped)
    return kept


AUTHOR_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["fan", "bot", "uncertain"]},
    "reason": {"type": "string"}}, "required": ["verdict"]}


def author_gate(mcp, ledger, post):
    aid = str(post["author_id"])
    cached = ledger["authors"].get(aid)
    if cached:
        return cached["verdict"]
    base = (f"著者名: {post.get('author_name')} / フォロワー: {post.get('author_followers')}\n"
            f"投稿: {post.get('text', '')}")
    j = gen_json(MODEL_EXTRACT, AUTHOR_SCHEMA, [
        "X投稿の著者が「実在のぽこピー(ぽんぽこ・ピーナッツくん)ファンによる善意のおすすめ投稿」か、"
        "「bot・宣伝アカウント・無関係な便乗」かを判定してください。判断できなければ uncertain。\n" + base])
    verdict = j["verdict"]
    if verdict == "uncertain":
        rows = mcp.call("run_sql", {"max_rows": 20, "query":
            f"SELECT text FROM tweets WHERE author_id='{aid}' ORDER BY created_at DESC"})
        others = rows.get("rows", rows) if isinstance(rows, dict) else rows
        history = "\n".join((r.get("text", "") if isinstance(r, dict) else str(r))[:100]
                            for r in (others or [])[:20])
        j = gen_json(MODEL_JUDGE, AUTHOR_SCHEMA, [
            "X投稿の著者がぽこピーファンの実在ユーザーか、bot・宣伝アカウントかを判定してください。"
            "同一著者の過去投稿も参考にすること。判断できなければ uncertain。\n" + base +
            "\n過去投稿:\n" + history])
        verdict = j["verdict"]
    ledger["authors"][aid] = {"verdict": verdict, "name": post.get("author_name"),
                              "date": TODAY}
    return verdict


# ---------------- 裏取り (Places) ----------------

def places_search(name, hint, bbox):
    r = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={"X-Goog-Api-Key": os.environ["PLACES_API_KEY"],
                 "X-Goog-FieldMask":
                     "places.id,places.displayName,places.formattedAddress,"
                     "places.location,places.businessStatus,places.websiteUri,"
                     "places.regularOpeningHours.weekdayDescriptions"},
        json={"textQuery": f"{name} {hint or ''}".strip(), "languageCode": "ja",
              "locationBias": {"rectangle": {
                  "low": {"latitude": bbox["lat_min"], "longitude": bbox["lng_min"]},
                  "high": {"latitude": bbox["lat_max"], "longitude": bbox["lng_max"]}}}},
        timeout=30)
    r.raise_for_status()
    return r.json().get("places", [])[:3]


DESC_SCHEMA = {"type": "object", "properties": {"desc": {"type": "string"}},
               "required": ["desc"]}


def refresh_desc(spot):
    """X言及が増えたスポットの紹介文を、言及内容を織り込んで更新する。"""
    quotes = [f"- {x.get('author', '')}: {x.get('quote', '')}"
              for x in spot["sources"] if x.get("type") == "x" and x.get("quote")]
    if not quotes:
        return
    j = gen_json(MODEL_EXTRACT, DESC_SCHEMA, [
        "スポット紹介文を更新してください。既存の紹介文の情報(動画由来)を核に残しつつ、"
        "Xでのファン言及から加わった観点や推しポイントを自然に織り込むこと。"
        "文体は既存文に合わせ常体(だ・である調/体言止め中心、です・ます調禁止)、"
        "60〜110字、絵文字なし、事実の捏造なし。\n"
        f"スポット名: {spot['name']}\n既存の紹介文: {spot['desc']}\n"
        "Xでの言及:\n" + "\n".join(quotes)])
    if j.get("desc"):
        spot["desc"] = j["desc"]


JUDGE_SCHEMA = {"type": "object", "properties": {
    "match": {"type": "boolean"},
    "place_index": {"type": "integer"},
    "confidence": {"type": "string", "enum": ["high", "low"]},
    "category": {"type": "string", "enum": CATS},
    "area_id": {"type": "string"},
    "new_area_name": {"type": "string"},
    "slug": {"type": "string"},
    "desc": {"type": "string"}}, "required": ["match", "confidence"]}


def judge_candidate(cand, places, areas, style_examples):
    area_desc = "\n".join(f"- {a['id']}: {a['name']}" for a in areas)
    places_desc = "\n".join(
        f"[{i}] {p.get('displayName', {}).get('text')} / {p.get('formattedAddress')} / "
        f"status={p.get('businessStatus')} / ({p['location']['latitude']:.4f},{p['location']['longitude']:.4f})"
        for i, p in enumerate(places))
    return gen_json(MODEL_JUDGE, JUDGE_SCHEMA, [
        "Xで紹介されたスポット候補と、Google Places の検索結果を照合してください。\n"
        f"候補: {cand['name']} / 手がかり: {cand.get('hint', 'なし')} / 言及: {cand.get('quote', '')}\n"
        f"Places結果:\n{places_desc or '(ヒットなし)'}\n\n"
        "1. 候補と同一の施設が結果にあれば match=true, その place_index, confidence "
        "(同名別店・別支店の可能性が残るなら low)。\n"
        f"2. match の場合: category は次から選ぶ: {', '.join(CATS)}。\n"
        f"3. area_id は既存エリアから選ぶ:\n{area_desc}\n"
        "   どれにも地理的に属さない場合のみ area_id='new' とし new_area_name に"
        "「輪島・奥能登」のような簡潔なエリア名を提案。\n"
        "4. slug は小文字英数の短い識別子。\n"
        "5. desc はこの地図の紹介文。以下の文体(常体・体言止め中心、です・ます調禁止)に合わせ、"
        "言及内容を踏まえ50-90字:\n" +
        "\n".join(f"例: {e}" for e in style_examples)])


# ---------------- 受入ゲート ----------------

def gate(judged, place, bbox):
    """掲載可否はここで強制する。戻り値 None=合格 / str=保留理由。"""
    if not judged.get("match"):
        return "places_no_match"
    if judged.get("confidence") != "high":
        return "low_confidence"
    if place.get("businessStatus") != "OPERATIONAL":
        return f"business_status={place.get('businessStatus')}"
    lat = place["location"]["latitude"]
    lng = place["location"]["longitude"]
    if not (bbox["lat_min"] <= lat <= bbox["lat_max"]
            and bbox["lng_min"] <= lng <= bbox["lng_max"]):
        return "out_of_bbox"
    return None


ISHIKAWA_STRICT = {"lat_min": 36.0, "lat_max": 37.6, "lng_min": 136.2, "lng_max": 137.4}


def normalize(name):
    return re.sub(r"[\s　]", "", name).lower()


def match_existing(cand_name, aliases, spots):
    name = aliases.get(cand_name.strip(), cand_name.strip())
    norm = normalize(name)
    for s in spots:
        if normalize(s["name"]) == norm:
            return s
    hits = difflib.get_close_matches(norm, [normalize(s["name"]) for s in spots],
                                     n=1, cutoff=0.85)
    if hits:
        return next(s for s in spots if normalize(s["name"]) == hits[0])
    return None


# ---------------- メイン ----------------

def main():
    workdir = tempfile.mkdtemp(prefix="spots-")
    clone_repo(workdir)
    spots_doc = load(workdir, "spots.json")
    pipeline_cfg = load(workdir, "pipeline.json")
    ledger = load(workdir, "ledger.json")
    aliases = load(workdir, "aliases.json")
    pending = load(workdir, "pending.json")
    bbox = pipeline_cfg["bbox"]
    spots = spots_doc["spots"]
    areas = spots_doc["areas"]
    style_examples = [s["desc"] for s in spots[:3]]

    mcp = McpClient(os.environ["XDEV_MCP_URL"])
    ledger.setdefault("seeds", {})
    rh = pipeline_cfg.get("reply_harvest", {})
    ttl = rh.get("seed_ttl_days", 35)

    # 過去に「おすすめ投稿」として処理済みのものをシードに昇格 (reply/引用RT収穫対象)
    for pid, rec in ledger["processed_posts"].items():
        if rec.get("result") == "processed":
            add_seed(ledger, pid, "reco_post", rec.get("author", ""),
                     rec.get("date", TODAY), ttl)

    official = watch_official(mcp, ledger, rh)
    main_posts = fetch_posts(mcp, ledger, pipeline_cfg["x_query"], max_posts=200)
    harvested, n_seeds = harvest_seeds(mcp, ledger, rh)
    seen_ids, posts = set(), []
    for p in official + main_posts + harvested:
        if str(p["id"]) not in seen_ids:
            seen_ids.add(str(p["id"]))
            posts.append(p)
    log(f"new posts: {len(posts)} (official {len(official)} / main {len(main_posts)} "
        f"/ harvested {len(harvested)} from {n_seeds} seeds)")
    if not posts:
        save(workdir, "ledger.json", ledger)  # シード整理だけでも保存対象
        commit_if_changed(workdir, f"auto-ingest {TODAY}: no new posts (seeds {n_seeds})")
        return

    stats = {"posts": len(posts), "added": [], "source_added": [], "pending": 0,
             "skipped_bot": 0, "skipped_offtopic": 0}
    new_candidates = []  # (cand, post)
    desc_refresh = {}    # slug -> spot: 今回X言及が増え紹介文を更新すべきスポット

    for post in posts:
        pid = str(post["id"])
        post_url = f"https://x.com/i/web/status/{pid}"
        images = download_images(post.get("media_urls"))
        ex = extract_spots(post, images)
        cands = ground_candidates(post, images, ex["candidates"]) \
            if ex["is_recommendation"] else []
        if not cands:
            ledger["processed_posts"][pid] = {"date": TODAY, "result": "not_recommendation"}
            stats["skipped_offtopic"] += 1
            continue
        verdict = author_gate(mcp, ledger, post)
        if verdict == "bot":
            ledger["processed_posts"][pid] = {"date": TODAY, "result": "author_bot"}
            stats["skipped_bot"] += 1
            continue
        post_date = str(post.get("created_at", ""))[:10] or TODAY
        for cand in cands:
            cand["_post"] = {"id": pid, "url": post_url, "date": post_date,
                             "author": post.get("author_name", ""),
                             "author_uncertain": verdict == "uncertain"}
            existing = match_existing(cand["name"], aliases, spots)
            if existing:
                if not any(src.get("url") == post_url for src in existing["sources"]):
                    existing["sources"].append({
                        "type": "x", "url": post_url, "author": cand["_post"]["author"],
                        "date": post_date, "quote": cand.get("quote", "")})
                    stats["source_added"].append(existing["name"])
                    desc_refresh[existing["slug"]] = existing
            else:
                new_candidates.append(cand)
        ledger["processed_posts"][pid] = {"date": TODAY, "result": "processed",
                                          "author": post.get("author_name", "")}

    cap = pipeline_cfg["gates"]["daily_new_spot_cap"]
    if len(new_candidates) > cap:
        github_issue(
            f"[auto-ingest] サーキットブレーカー発動: 新規候補 {len(new_candidates)} 件 > {cap}",
            "検索クエリが他のムーブメントと衝突している可能性があります。"
            f"pipeline.json の x_query を確認してください。\n\n候補例:\n" +
            "\n".join(f"- {c['name']}" for c in new_candidates[:30]))
        log("circuit breaker: abort without commit")
        return

    known_place_ids = {s.get("place_id"): s for s in spots if s.get("place_id")}
    slugs = {s["slug"] for s in spots}

    for cand in new_candidates:
        meta = cand["_post"]
        def hold(reason):
            stats["pending"] += 1
            pending["items"].append({"name": cand["name"], "reason": reason,
                                     "hint": cand.get("hint", ""), "post": meta["url"],
                                     "date": TODAY})
        if meta["author_uncertain"]:
            hold("author_uncertain")
            continue
        try:
            places = places_search(cand["name"], cand.get("hint"), bbox)
        except requests.RequestException as e:
            hold(f"places_error: {e}")
            continue
        judged = judge_candidate(cand, places, areas, style_examples)
        idx = judged.get("place_index", 0)
        place = places[idx] if places and 0 <= idx < len(places) else {}
        reason = gate(judged, place, bbox) if place else "places_no_match"
        if reason:
            hold(reason)
            continue
        place_id = place["id"]
        if place_id in known_place_ids:  # 名寄せ漏れ: 同一施設に出典追記
            ex_spot = known_place_ids[place_id]
            if not any(src.get("url") == meta["url"] for src in ex_spot["sources"]):
                ex_spot["sources"].append({"type": "x", "url": meta["url"],
                                           "author": meta["author"], "date": meta["date"],
                                           "quote": cand.get("quote", "")})
                stats["source_added"].append(ex_spot["name"])
                desc_refresh[ex_spot["slug"]] = ex_spot
            continue
        area_id = judged.get("area_id", "new")
        if area_id == "new" or area_id not in {a["id"] for a in areas}:
            new_name = judged.get("new_area_name") or "その他エリア"
            area_id = re.sub(r"[^a-z0-9]", "", (judged.get("slug") or "area")) + "-area"
            areas.append({"id": area_id, "name": new_name,
                          "color": AREA_PALETTE[len(areas) % len(AREA_PALETTE)]})
        slug = re.sub(r"[^a-z0-9-]", "", (judged.get("slug") or "spot").lower()) or "spot"
        while slug in slugs:
            slug += "2"
        slugs.add(slug)
        lat, lng = place["location"]["latitude"], place["location"]["longitude"]
        spot = {
            "slug": slug, "name": place["displayName"]["text"], "area": area_id,
            "cat": judged.get("category", "観光"), "lat": round(lat, 5),
            "lng": round(lng, 5), "approx": False,
            "desc": judged.get("desc", cand.get("quote", "")),
            "address": place.get("formattedAddress", ""),
            "place_id": place_id, "added": TODAY,
            "sources": [{"type": "x", "url": meta["url"], "author": meta["author"],
                         "date": meta["date"], "quote": cand.get("quote", "")}]}
        hours = place.get("regularOpeningHours", {}).get("weekdayDescriptions")
        if hours:
            spot["hours"] = " / ".join(hours[:2]) + (" ほか" if len(hours) > 2 else "")
        if place.get("websiteUri"):
            spot["url"] = place["websiteUri"]
        if not (ISHIKAWA_STRICT["lat_min"] <= lat <= ISHIKAWA_STRICT["lat_max"]
                and ISHIKAWA_STRICT["lng_min"] <= lng <= ISHIKAWA_STRICT["lng_max"]):
            spot["out_of_pref"] = True
        spots.append(spot)
        known_place_ids[place_id] = spot
        stats["added"].append(spot["name"])

    for spot in desc_refresh.values():
        try:
            refresh_desc(spot)
        except Exception as e:
            log("desc refresh skip:", spot["slug"], repr(e))

    save(workdir, "spots.json", spots_doc)
    save(workdir, "ledger.json", ledger)
    save(workdir, "pending.json", pending)

    v = subprocess.run([sys.executable, "validate.py"], cwd=workdir,
                       capture_output=True, encoding="utf-8", errors="replace")
    log(v.stdout.strip())
    if v.returncode != 0:
        github_issue("[auto-ingest] validate.py 失敗のため入稿中止", v.stdout + v.stderr)
        return

    msg = (f"auto-ingest {TODAY}: +{len(stats['added'])} spots"
           f"{' (' + ', '.join(stats['added'][:5]) + ')' if stats['added'] else ''}, "
           f"src+{len(stats['source_added'])}, pending {stats['pending']}, "
           f"posts {stats['posts']} (bot {stats['skipped_bot']} / offtopic {stats['skipped_offtopic']}, "
           f"seeds {n_seeds})")
    log("summary:", msg)
    commit_if_changed(workdir, msg)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 失敗を Issue で可視化してから落とす
        log("FATAL:", repr(e))
        try:
            github_issue(f"[auto-ingest] ジョブ失敗 {TODAY}", f"```\n{e!r}\n```")
        except Exception:
            pass
        raise
