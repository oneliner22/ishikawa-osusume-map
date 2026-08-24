# -*- coding: utf-8 -*-
"""本人リプ続きの一括バックフィル (ワンショット)。

spots.json に採用済みのX言及 (=ledger で result:processed の投稿) について、
投稿者本人がスレッドにぶら下げた続きリプライ・自己引用RTを xdev ストアから
連鎖探索し、未処理のものを従前のパイプライン (extract → ground → author gate →
Places → judge → gate) で分類・判定する。

前提: 対象著者の `from:<handle> is:reply` と `from:<handle> is:quote` を事前に
x_ingest (archive) でストアへ投入しておくこと (ストアは短期保持のため、実行直前に投入する)。

使い方 (リポ直下で):
  python tools/selfreply_backfill.py          # ドライラン (報告のみ)
  python tools/selfreply_backfill.py --apply  # data/*.json に反映

必要な環境変数:
  PLACES_API_KEY  (必須)
  XDEV_MCP_URL    (省略時 ~/.claude.json の mcpServers から xdev の url を拾う)
  GCP_PROJECT     (省略時 central-bulwark-427114-j7)
"""
import copy
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

os.environ.setdefault("GCP_PROJECT", "central-bulwark-427114-j7")
os.environ.setdefault("GITHUB_REPO", "oneliner22/ishikawa-osusume-map")
os.environ.setdefault("GITHUB_TOKEN", "local-dummy-token")  # 本スクリプトは push/Issue しない

if "PLACES_API_KEY" not in os.environ:
    sys.exit("PLACES_API_KEY を環境変数で渡すこと (gcloud secrets versions access "
             "latest --secret=places-api-key --project central-bulwark-427114-j7)")


def resolve_xdev_url():
    if os.environ.get("XDEV_MCP_URL"):
        return os.environ["XDEV_MCP_URL"]
    cfg = json.load(io.open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "mcpServers" and isinstance(v, dict):
                    for name, sv in v.items():
                        if "xdev" in name.lower() and isinstance(sv, dict) and sv.get("url"):
                            found.append(sv["url"])
                else:
                    walk(v)
    walk(cfg)
    if not found:
        sys.exit("XDEV_MCP_URL が見つからない (env にも ~/.claude.json にもない)")
    return found[0]


os.environ["XDEV_MCP_URL"] = resolve_xdev_url()

import daily_job as dj  # noqa: E402  (env 設定後に import すること)
from mcp_client import McpClient  # noqa: E402

APPLY = "--apply" in sys.argv
REPORT_PATH = os.path.join(ROOT, "tools", "selfreply_dryrun_report.json")


def load(name):
    return json.load(io.open(os.path.join(ROOT, "data", name), encoding="utf-8"))


def save(name, obj):
    json.dump(obj, io.open(os.path.join(ROOT, "data", name), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def sql_rows(mcp, query, max_rows=200):
    rows = mcp.call("run_sql", {"max_rows": max_rows, "query": query})
    posts = rows.get("rows", rows) if isinstance(rows, dict) else rows
    if posts and isinstance(posts[0], list):
        cols = rows.get("columns", [])
        posts = [dict(zip(cols, r)) for r in posts]
    return posts or []


def discover_chains(mcp, eligible, authors):
    """適格投稿を起点に、適格著者による返信・引用RTの連鎖をストアから辿る。
    起点・中継が処理済みでも探索は続け、未処理の投稿だけを返す。"""
    in_authors = ", ".join(f"'{a}'" for a in sorted(authors))
    seen = set(eligible)
    frontier = sorted(eligible)
    edges = {}  # id -> (author, ref_id, created_at, ref_type)
    while frontier:
        in_ids = ", ".join(f"'{i}'" for i in frontier)
        rows = sql_rows(mcp,
            "SELECT DISTINCT id, author_name, ref_type, ref_id, created_at FROM tweets "
            f"WHERE ref_type IN ('replied_to', 'quoted') AND ref_id IN ({in_ids}) "
            f"AND author_name IN ({in_authors}) ORDER BY created_at")
        frontier = []
        for r in rows:
            pid = str(r["id"])
            if pid in seen:
                continue
            seen.add(pid)
            edges[pid] = (r["author_name"], str(r["ref_id"]), str(r["created_at"]),
                          r.get("ref_type", ""))
            frontier.append(pid)
    return edges


def fetch_full(mcp, ids):
    if not ids:
        return []
    in_ids = ", ".join(f"'{i}'" for i in ids)
    rows = sql_rows(mcp,
        "SELECT t.id, any_value(t.created_at) created_at, any_value(t.author_id) author_id, "
        "any_value(t.author_name) author_name, max(t.author_followers) author_followers, "
        "any_value(t.text) AS \"text\", any_value(t.media_urls) media_urls, "
        "max(t.like_count) like_count, max(t.reply_count) reply_count "
        f"FROM tweets t WHERE t.id IN ({in_ids}) GROUP BY t.id ORDER BY created_at")
    return rows


def main():
    spots_doc = load("spots.json")
    pipeline_cfg = load("pipeline.json")
    ledger = load("ledger.json")
    aliases = load("aliases.json")
    pending = load("pending.json")
    if not APPLY:  # ドライランは深いコピー上で動かし、ファイルには触れない
        spots_doc, ledger, pending = (copy.deepcopy(x) for x in (spots_doc, ledger, pending))
    spots = spots_doc["spots"]
    areas = spots_doc["areas"]
    bbox = pipeline_cfg["bbox"]
    style_examples = [s["desc"] for s in spots[:3]]
    processed = ledger["processed_posts"]

    # 適格 = processed かつ result:processed (bot/offtopic は起点にしない)
    eligible = {pid for pid, v in processed.items() if v.get("result") == "processed"}
    authors = {v.get("author") for v in processed.values()
               if v.get("result") == "processed" and v.get("author")}
    dj.log(f"eligible posts: {len(eligible)} / authors: {len(authors)}")

    mcp = McpClient(os.environ["XDEV_MCP_URL"])
    edges = discover_chains(mcp, eligible, authors)
    new_ids = [pid for pid in edges if pid not in processed]
    dj.log(f"thread members found: {len(edges)} (new: {len(new_ids)})")
    posts = fetch_full(mcp, new_ids)
    if len(posts) < len(new_ids):
        missing = set(new_ids) - {str(p["id"]) for p in posts}
        dj.log("WARN: store に本文が無い:", sorted(missing))

    report = {"mode": "apply" if APPLY else "dry_run", "date": dj.TODAY,
              "posts": [], "summary": {}}
    stats = {"added": [], "source_added": [], "pending": 0,
             "skipped_bot": 0, "skipped_offtopic": 0}
    known_place_ids = {s.get("place_id"): s for s in spots if s.get("place_id")}
    slugs = {s["slug"] for s in spots}
    desc_refresh = {}
    new_sources = []  # apply 時に embed 判定する新規X出典

    for post in posts:
        pid = str(post["id"])
        author = post.get("author_name", "")
        post_url = dj.x_post_url(pid, author)
        post_date = str(post.get("created_at", ""))[:10] or dj.TODAY
        edge = edges.get(pid, ("", "", "", ""))
        entry = {"id": pid, "author": author, "date": post_date,
                 "url": post_url, "text": (post.get("text") or "")[:200],
                 "reply_to": edge[1], "ref_type": edge[3] if len(edge) > 3 else "",
                 "candidates": []}
        report["posts"].append(entry)

        images = dj.download_images(post.get("media_urls"))
        # 抽出には「本人の続き投稿」という取得文脈を1行添える (単体では回覧板・石川への
        # 言及がない続き投稿を取りこぼさないため。スポット名は含まないので捏造には働かない)
        ctx_post = dict(post)
        ctx_post["text"] = ("(注: この投稿は、#ぽこピーの回覧板 向け石川おすすめ紹介"
                            "スレッドに投稿者本人がぶら下げた続きの投稿"
                            " (リプライまたは自己引用RT))\n"
                            + (post.get("text") or ""))
        ex = dj.extract_spots(ctx_post, images)
        cands = dj.ground_candidates(ctx_post, images, ex["candidates"]) \
            if ex["is_recommendation"] else []
        if not cands:
            entry["result"] = "not_recommendation"
            processed[pid] = {"date": dj.TODAY, "result": "not_recommendation"}
            stats["skipped_offtopic"] += 1
            continue
        verdict = dj.author_gate(mcp, ledger, post)
        if verdict == "bot":
            entry["result"] = "author_bot"
            processed[pid] = {"date": dj.TODAY, "result": "author_bot"}
            stats["skipped_bot"] += 1
            continue
        entry["result"] = "processed"

        for cand in cands:
            c_rep = {"name": cand["name"], "hint": cand.get("hint", ""),
                     "quote": cand.get("quote", "")}
            entry["candidates"].append(c_rep)
            src = {"type": "x", "url": post_url, "author": author,
                   "date": post_date, "quote": cand.get("quote", "")}
            if verdict == "uncertain":
                c_rep["action"] = "pending:author_uncertain"
                stats["pending"] += 1
                pending["items"].append({"name": cand["name"],
                                         "reason": "author_uncertain",
                                         "hint": cand.get("hint", ""),
                                         "post": post_url, "date": dj.TODAY})
                continue
            existing = dj.match_existing(cand["name"], aliases, spots)
            if existing:
                if dj.has_source(existing["sources"], post_url):
                    c_rep["action"] = f"source_dup:{existing['name']}"
                else:
                    existing["sources"].append(src)
                    new_sources.append(src)
                    stats["source_added"].append(existing["name"])
                    desc_refresh[existing["slug"]] = existing
                    c_rep["action"] = f"source_added:{existing['name']}"
                continue
            try:
                places = dj.places_search(cand["name"], cand.get("hint"), bbox)
            except Exception as e:
                c_rep["action"] = f"pending:places_error"
                stats["pending"] += 1
                pending["items"].append({"name": cand["name"],
                                         "reason": f"places_error: {e}",
                                         "hint": cand.get("hint", ""),
                                         "post": post_url, "date": dj.TODAY})
                continue
            judged = dj.judge_candidate(cand, places, areas, style_examples)
            idx = judged.get("place_index", 0)
            place = places[idx] if places and 0 <= idx < len(places) else {}
            reason = dj.gate(judged, place, bbox) if place else "places_no_match"
            if reason:
                c_rep["action"] = f"pending:{reason}"
                stats["pending"] += 1
                pending["items"].append({"name": cand["name"], "reason": reason,
                                         "hint": cand.get("hint", ""),
                                         "post": post_url, "date": dj.TODAY})
                continue
            place_id = place["id"]
            if place_id in known_place_ids:  # 名寄せ漏れ: 同一施設に出典追記
                ex_spot = known_place_ids[place_id]
                if not dj.has_source(ex_spot["sources"], post_url):
                    ex_spot["sources"].append(src)
                    new_sources.append(src)
                    stats["source_added"].append(ex_spot["name"])
                    desc_refresh[ex_spot["slug"]] = ex_spot
                    c_rep["action"] = f"source_added(place_id):{ex_spot['name']}"
                else:
                    c_rep["action"] = f"source_dup:{ex_spot['name']}"
                continue
            area_id = judged.get("area_id", "new")
            if area_id == "new" or area_id not in {a["id"] for a in areas}:
                new_name = judged.get("new_area_name") or "その他エリア"
                hit = next((a for a in areas if a["name"] == new_name), None)
                if hit:
                    area_id = hit["id"]
                else:
                    area_id = dj.re.sub(r"[^a-z0-9]", "",
                                        (judged.get("slug") or "area")) + "-area"
                    areas.append({"id": area_id, "name": new_name,
                                  "color": dj.AREA_PALETTE[len(areas) % len(dj.AREA_PALETTE)]})
            slug = dj.re.sub(r"[^a-z0-9-]", "", (judged.get("slug") or "spot").lower()) or "spot"
            while slug in slugs:
                slug += "2"
            slugs.add(slug)
            lat = place["location"]["latitude"]
            lng = place["location"]["longitude"]
            spot = {"slug": slug, "name": place["displayName"]["text"],
                    "area": area_id, "cat": judged.get("category", "観光"),
                    "lat": round(lat, 5), "lng": round(lng, 5), "approx": False,
                    "desc": judged.get("desc", cand.get("quote", "")),
                    "address": place.get("formattedAddress", ""),
                    "place_id": place_id, "added": dj.TODAY, "sources": [src]}
            hours = place.get("regularOpeningHours", {}).get("weekdayDescriptions")
            if hours:
                spot["hours"] = list(hours)
            if place.get("websiteUri"):
                spot["url"] = place["websiteUri"]
            if not (dj.ISHIKAWA_STRICT["lat_min"] <= lat <= dj.ISHIKAWA_STRICT["lat_max"]
                    and dj.ISHIKAWA_STRICT["lng_min"] <= lng <= dj.ISHIKAWA_STRICT["lng_max"]):
                spot["out_of_pref"] = True
            spots.append(spot)
            known_place_ids[place_id] = spot
            stats["added"].append(spot["name"])
            c_rep["action"] = "new_spot"
            c_rep["new_spot"] = {k: spot[k] for k in
                                 ("slug", "name", "area", "cat", "lat", "lng",
                                  "desc", "address")}
        processed[pid] = {"date": dj.TODAY, "result": "processed", "author": author}

    for slug, spot in desc_refresh.items():
        old = spot["desc"]
        try:
            dj.refresh_desc(spot)
        except Exception as e:
            dj.log("desc refresh skip:", slug, repr(e))
        for p_entry in report["posts"]:
            for c in p_entry["candidates"]:
                if c.get("action", "").endswith(":" + spot["name"]):
                    c["desc_update"] = {"old": old, "new": spot["desc"]}

    report["summary"] = {
        "new_posts": len(posts),
        "added_spots": stats["added"], "source_added": stats["source_added"],
        "pending": stats["pending"], "skipped_offtopic": stats["skipped_offtopic"],
        "skipped_bot": stats["skipped_bot"]}
    json.dump(report, io.open(REPORT_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    dj.log("report ->", REPORT_PATH)
    dj.log("summary:", json.dumps(report["summary"], ensure_ascii=False))

    if not APPLY:
        dj.log("DRY_RUN: data/*.json は変更していない")
        return
    for src in new_sources:
        dj.set_embed_flag(src)
    save("spots.json", spots_doc)
    save("ledger.json", ledger)
    save("pending.json", pending)
    v = dj.subprocess.run([sys.executable, "validate.py"], cwd=ROOT,
                          capture_output=True, encoding="utf-8", errors="replace")
    dj.log(v.stdout.strip())
    if v.returncode != 0:
        sys.exit("validate.py 失敗。commit しないこと")
    dj.log("applied. git diff を確認して commit すること")


if __name__ == "__main__":
    main()
