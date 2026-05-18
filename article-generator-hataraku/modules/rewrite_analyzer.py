"""
rewrite_analyzer.py

GSC分析 → リライト提案シート記入モジュール

使い方:
    from modules.rewrite_analyzer import run_analysis
    run_analysis("workup-ai")
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

import gspread
import requests
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_REWRITE_SHEET_NAME = "リライト提案"

_SHEET_HEADERS = [
    "提案日", "ブログ名", "記事タイトル", "URL", "公開日",
    "クリック数", "表示回数", "CTR", "平均掲載順位",
    "主な流入クエリ", "1クリック以上のクエリ数",
    "リライト推奨度", "リライト強度", "提案理由",
    "追加すべき検索意図", "追加H2/H3案", "FAQ案",
    "内部リンク案", "ASP導線案", "CTA案",
    "想定リスク", "優先度", "リライト実行", "ステータス", "実施日", "結果メモ",
]


# ──────────────────────────────────────────────────────────
# ブログ設定・認証
# ──────────────────────────────────────────────────────────

def _load_blog_cfg(blog_name: str) -> dict:
    cfg_path = os.path.join(
        os.path.dirname(__file__), "..", "blogs", blog_name, "blog_config.json"
    )
    with open(cfg_path) as f:
        return json.load(f)


def _wp_auth(blog_cfg: dict) -> tuple[str, str]:
    username = os.getenv(blog_cfg.get("wp_username_env", ""), "")
    password = os.getenv(blog_cfg.get("wp_app_password_env", ""), "")
    return username, password


# ──────────────────────────────────────────────────────────
# GSCデータ取得（3ヶ月）
# ──────────────────────────────────────────────────────────

def _fetch_gsc_3months(gsc_client) -> dict[str, list[dict]]:
    """過去90日のGSCデータ（page×query集計）を返す。"""
    end_date   = date.today() - timedelta(days=3)
    start_date = end_date - timedelta(days=89)

    service = gsc_client._get_service()
    response = service.searchanalytics().query(
        siteUrl=gsc_client.site_url,
        body={
            "startDate":  start_date.isoformat(),
            "endDate":    end_date.isoformat(),
            "dimensions": ["page", "query"],
            "rowLimit":   25000,
            "dataState":  "all",
        },
    ).execute()

    page_data: dict[str, list[dict]] = defaultdict(list)
    for row in response.get("rows", []):
        keys  = row.get("keys", [])
        page  = keys[0].rstrip("/") if keys else ""
        query = keys[1] if len(keys) > 1 else ""
        page_data[page].append({
            "query":       query,
            "position":    row.get("position",    0.0),
            "impressions": row.get("impressions", 0),
            "clicks":      row.get("clicks",      0),
            "ctr":         row.get("ctr",         0.0),
        })
    return dict(page_data)


# ──────────────────────────────────────────────────────────
# WP記事情報取得
# ──────────────────────────────────────────────────────────

def _fetch_wp_posts(wp_url: str, auth: tuple) -> dict[str, dict]:
    """公開記事の URL → {title, date} マップを返す。"""
    posts: dict[str, dict] = {}
    page = 1
    while True:
        try:
            resp = requests.get(
                f"{wp_url}/wp-json/wp/v2/posts",
                auth=auth,
                params={
                    "status": "publish",
                    "per_page": 100,
                    "page": page,
                    "_fields": "id,title,link,date",
                },
                timeout=30,
            )
        except Exception as e:
            print(f"[rewrite] WP取得エラー (page={page}): {e}")
            break
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        for post in data:
            link = post.get("link", "").rstrip("/")
            posts[link] = {
                "id":    post["id"],
                "title": post["title"]["rendered"],
                "date":  post.get("date", ""),
            }
        page += 1
    return posts


# ──────────────────────────────────────────────────────────
# スコアリング
# ──────────────────────────────────────────────────────────

def _aggregate_page_stats(queries: list[dict]) -> dict:
    total_clicks = sum(q["clicks"] for q in queries)
    total_impr   = sum(q["impressions"] for q in queries)
    ctr          = total_clicks / total_impr if total_impr else 0.0
    weighted_pos = sum(q["position"] * q["impressions"] for q in queries)
    avg_pos      = weighted_pos / total_impr if total_impr else 0.0
    return {
        "clicks":       total_clicks,
        "impressions":  total_impr,
        "ctr":          ctr,
        "avg_position": avg_pos,
    }


def _should_skip(stats: dict, days_since_publish: int | None) -> str | None:
    """対象外なら理由文字列を返す。対象内なら None。"""
    if days_since_publish is not None and days_since_publish < 30:
        return "公開30日以内"
    if stats["clicks"] == 0:
        return "クリック0"
    if stats["avg_position"] <= 2.0 and stats["ctr"] >= 0.10:
        return "順位1〜2位かつCTR良好"
    if stats["impressions"] < 50:
        return "表示回数50未満"
    return None


def _compute_score(stats: dict, queries_with_clicks: list[dict]) -> int:
    score = 0
    pos  = stats["avg_position"]
    ctr  = stats["ctr"]
    impr = stats["impressions"]
    n    = len(queries_with_clicks)

    if 3.0 <= pos <= 15.0:
        score += 3
    elif 15.0 < pos <= 30.0:
        score += 1

    if n >= 5:
        score += 2
    elif n >= 2:
        score += 1

    if pos <= 3.0 and ctr < 0.05:
        score += 2

    if impr >= 1000 and ctr < 0.03:
        score += 2
    elif impr >= 300 and ctr < 0.05:
        score += 1

    return score


def _score_to_meta(score: int, stats: dict) -> tuple[str, str, str]:
    """(優先度, 推奨度, 強度) を返す。"""
    if score >= 7:
        priority, rec = "S", "高"
    elif score >= 5:
        priority, rec = "A", "高"
    elif score >= 3:
        priority, rec = "B", "中"
    else:
        priority, rec = "C", "低"

    pos = stats["avg_position"]
    if score >= 7 or (pos <= 5 and stats["ctr"] < 0.04):
        strength = "中規模〜大規模"
    elif score >= 4:
        strength = "軽微〜中規模"
    else:
        strength = "軽微"

    return priority, rec, strength


# ──────────────────────────────────────────────────────────
# Claude提案テキスト生成
# ──────────────────────────────────────────────────────────

def _generate_proposals_with_claude(candidates: list[dict], blog_cfg: dict) -> list[dict]:
    """Claude Haiku でリライト提案テキストを一括生成。"""
    import anthropic
    from config import ANTHROPIC_API_KEY

    try:
        from modules.api_guard import record_usage
    except ImportError:
        record_usage = lambda *a, **k: None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    pages_json = json.dumps([
        {
            "url":   c["url"],
            "title": c["title"],
            "clicks":      c["stats"]["clicks"],
            "impressions": c["stats"]["impressions"],
            "ctr":         f'{c["stats"]["ctr"]*100:.1f}%',
            "avg_position": round(c["stats"]["avg_position"], 1),
            "top_queries": [
                q["query"]
                for q in sorted(c["queries"], key=lambda x: -x["impressions"])[:8]
            ],
            "queries_with_clicks": [q["query"] for q in c["queries_with_clicks"][:10]],
        }
        for c in candidates
    ], ensure_ascii=False, indent=2)

    blog_name  = blog_cfg.get("display_name", "")
    blog_genre = blog_cfg.get("genre", "")

    prompt = f"""あなたはSEOディレクターです。以下のブログの記事データを分析し、各記事のリライト提案を作成してください。

ブログ名: {blog_name}
ジャンル: {blog_genre}

各記事について以下を日本語で出力してください:
- reason: 提案理由（2〜3文で、具体的なデータに基づいて）
- additional_intents: 追加すべき検索意図（箇条書き、3〜5個）
- h2_h3: 追加H2/H3案（具体的な見出し文言を記載）
- faq: FAQ案（2〜4問、質問文のみ）
- internal_links: 内部リンク案（どんな記事と繋げるか）
- asp: ASP導線案（ブログジャンルに合わせた案。ない場合は「なし」）
- cta: CTA案（読者に促す一言）
- risks: 想定リスク（低/中/高で一言）

以下のJSON形式で出力してください（URLをキーとする辞書）:
{{
  "https://example.com/slug": {{
    "reason": "...",
    "additional_intents": "...",
    "h2_h3": "...",
    "faq": "...",
    "internal_links": "...",
    "asp": "...",
    "cta": "...",
    "risks": "..."
  }}
}}

記事データ:
{pages_json}
"""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    record_usage(
        "claude-haiku-4-5-20251001",
        msg.usage.input_tokens,
        msg.usage.output_tokens,
        "rewrite_proposal",
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        proposal_texts: dict = json.loads(raw)
    except json.JSONDecodeError:
        print("[rewrite] 提案テキストのJSON解析失敗 → 空で継続")
        proposal_texts = {}

    for c in candidates:
        c["proposal_text"] = proposal_texts.get(c["url"], {})

    return candidates


# ──────────────────────────────────────────────────────────
# スプレッドシート書き込み
# ──────────────────────────────────────────────────────────

def _get_or_create_rewrite_sheet(ss: gspread.Spreadsheet) -> gspread.Worksheet:
    try:
        ws = ss.worksheet(_REWRITE_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=_REWRITE_SHEET_NAME, rows=1000, cols=len(_SHEET_HEADERS))
        ws.append_row(_SHEET_HEADERS)
        print(f"[rewrite] シート新規作成: {_REWRITE_SHEET_NAME}")
        return ws

    # ヘッダー行がなければ追加
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(_SHEET_HEADERS)
        return ws

    # 不足している列を末尾に追加（列順は既存シートを尊重し、なければ追加）
    missing = [h for h in _SHEET_HEADERS if h not in first_row]
    if missing:
        for h in missing:
            # 既存列数の右隣に追加
            col_count = len(first_row) + 1
            ws.update_cell(1, col_count, h)
            first_row.append(h)
            print(f"[rewrite] 列追加: {h} ({col_count}列目)")

    return ws


def _write_proposals_to_sheet(candidates: list[dict], blog_cfg: dict) -> int:
    ss_id = blog_cfg.get("main_ss_id", "")
    if not ss_id:
        print("[rewrite] main_ss_id が未設定")
        return 0

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
    gc    = gspread.authorize(creds)
    ss    = gc.open_by_key(ss_id)
    ws    = _get_or_create_rewrite_sheet(ss)

    # 既存URLを収集（重複スキップ用）
    all_vals      = ws.get_all_values()
    existing_urls = {row[3] for row in all_vals[1:] if len(row) > 3 and row[3]}

    today   = date.today().strftime("%Y/%m/%d")
    written = 0

    for c in candidates:
        url = c["url"]
        if url in existing_urls:
            print(f"[rewrite] スキップ（既存）: {url.split('/')[-1]}")
            continue

        stats  = c["stats"]
        pt     = c.get("proposal_text", {})
        top_q  = [
            q["query"]
            for q in sorted(c["queries"], key=lambda x: -x["impressions"])[:5]
        ]

        row = [
            today,
            blog_cfg.get("display_name", ""),
            c["title"],
            url,
            c.get("publish_date", ""),          # 公開日
            stats["clicks"],
            stats["impressions"],
            f'{stats["ctr"]*100:.1f}%',
            round(stats["avg_position"], 1),
            " / ".join(top_q),
            len(c["queries_with_clicks"]),
            c["recommendation"],
            c["strength"],
            pt.get("reason", ""),
            pt.get("additional_intents", ""),
            pt.get("h2_h3", ""),
            pt.get("faq", ""),
            pt.get("internal_links", ""),
            pt.get("asp", ""),
            pt.get("cta", ""),
            pt.get("risks", ""),
            c["priority"],
            "",                                  # リライト実行（ユーザーが「now」と入力）
            "未確認",
            "",                                  # 実施日
            "",                                  # 結果メモ
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"[rewrite] 記入: [{c['priority']}] {c['title'][:40]}")
        written += 1

    return written


# ──────────────────────────────────────────────────────────
# メインエントリ
# ──────────────────────────────────────────────────────────

def run_analysis(blog_name: str, max_proposals: int = 20) -> None:
    """GSC分析 → スコアリング → Claude提案 → シート記入。"""
    from modules.gsc_client import GSCClient

    blog_cfg     = _load_blog_cfg(blog_name)
    display_name = blog_cfg.get("display_name", blog_name)
    wp_url       = blog_cfg.get("wp_url", "").rstrip("/")

    print(f"\n{'='*60}")
    print(f"[rewrite] 分析開始: {display_name}")
    print(f"{'='*60}")

    # GSCデータ取得
    site_url = wp_url + "/"
    gsc      = GSCClient(site_url=site_url)
    print("[rewrite] GSCデータ取得中（過去90日）...")
    try:
        page_data = _fetch_gsc_3months(gsc)
    except Exception as e:
        print(f"[rewrite] GSC取得エラー: {e}")
        return
    print(f"[rewrite] GSCページ数: {len(page_data)}件")

    # WP記事情報取得
    print("[rewrite] WP記事情報取得中...")
    auth     = _wp_auth(blog_cfg)
    wp_posts = {}
    try:
        wp_posts = _fetch_wp_posts(wp_url, auth)
        print(f"[rewrite] WP記事数: {len(wp_posts)}件")
    except Exception as e:
        print(f"[rewrite] WP記事取得エラー（スキップ）: {e}")

    # スコアリング・フィルタリング
    today      = date.today()
    candidates = []

    for url, queries in page_data.items():
        # このブログのURLのみ対象
        if not url.startswith(wp_url):
            continue

        stats               = _aggregate_page_stats(queries)
        queries_with_clicks = [q for q in queries if q["clicks"] >= 1]

        # タイトル・公開日をWP情報から取得
        wp_info = wp_posts.get(url) or wp_posts.get(url.rstrip("/"), {})
        slug    = url.rstrip("/").split("/")[-1]
        title   = wp_info.get("title") or slug

        days_since_publish = None
        publish_date = ""
        pub_str = wp_info.get("date", "")
        if pub_str:
            try:
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                days_since_publish = (today - pub.date()).days
                publish_date = pub.strftime("%Y/%m/%d")
            except Exception:
                pass

        # スキップ判定
        skip_reason = _should_skip(stats, days_since_publish)
        if skip_reason:
            continue

        score = _compute_score(stats, queries_with_clicks)
        if score < 2:
            continue

        priority, recommendation, strength = _score_to_meta(score, stats)

        candidates.append({
            "url":                 url,
            "title":               title,
            "publish_date":        publish_date,
            "stats":               stats,
            "queries":             queries,
            "queries_with_clicks": queries_with_clicks,
            "score":               score,
            "priority":            priority,
            "recommendation":      recommendation,
            "strength":            strength,
            "proposal_text":       {},
        })

    candidates.sort(key=lambda x: -x["score"])
    print(f"[rewrite] 候補: {len(candidates)}件")

    if not candidates:
        print("[rewrite] 候補なし → 終了")
        return

    top = candidates[:max_proposals]

    # Claude提案テキスト生成
    print(f"[rewrite] Claude提案生成中（{len(top)}件）...")
    try:
        top = _generate_proposals_with_claude(top, blog_cfg)
    except Exception as e:
        print(f"[rewrite] Claude提案生成エラー（続行）: {e}")

    # シート記入
    print("[rewrite] スプレッドシートに記入中...")
    written = _write_proposals_to_sheet(top, blog_cfg)

    print(f"\n{'='*60}")
    print(f"[rewrite] 完了: {written}件記入 / {len(top)}件候補 / {len(candidates)}件分析")
    print(f"{'='*60}\n")
