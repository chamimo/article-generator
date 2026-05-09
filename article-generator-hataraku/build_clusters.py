"""
キーワードクラスター構築スクリプト

STEP 1: WP既存記事取得 → output/existing_articles.json
STEP 2: AIMキーワード × カニバリチェック → グループ化 → output/keyword_clusters.json

Usage:
    python build_clusters.py [blog_name]
    python build_clusters.py hapipo8
"""
import sys
import os

# ブログ名をCLIから受け取り、config のサイト切り替えに反映（importより前に設定）
if len(sys.argv) > 1:
    os.environ["ARTICLE_SITE"] = sys.argv[1]

import json
import requests
from requests.auth import HTTPBasicAuth
import anthropic
from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, ANTHROPIC_API_KEY
from modules.sheets_fetcher import get_aim_keywords, get_excluded_keywords
from modules.sheets_updater import mark_cannibal_results_bulk, setup_legend_sheet

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
EXISTING_ARTICLES_PATH = os.path.join(OUTPUT_DIR, "existing_articles.json")
KEYWORD_CLUSTERS_PATH = os.path.join(OUTPUT_DIR, "keyword_clusters.json")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────────
# STEP 1
# ─────────────────────────────────────────────

def fetch_existing_articles() -> list[dict]:
    """WordPress REST APIで全記事の title / slug / categories を取得する。"""
    articles: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
            params={
                "per_page": 100,
                "page": page,
                "status": "any",
                "_fields": "id,title,slug,categories,link",
            },
            timeout=15,
        )
        if resp.status_code == 400:
            break  # ページ超過
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            articles.append({
                "id": p["id"],
                "title": p["title"]["rendered"],
                "slug": p["slug"],
                "categories": p.get("categories", []),
                "link": p.get("link", ""),
            })
        if len(batch) < 100:
            break
        page += 1

    print(f"[build_clusters] 既存記事取得: {len(articles)}件")
    return articles


# ─────────────────────────────────────────────
# STEP 2
# ─────────────────────────────────────────────

_CLUSTER_BATCH_SIZE = 100  # 1回のAPI呼び出しで処理するキーワード数


def _cluster_batch(
    kw_batch: list[dict],
    existing_titles: list[str],
    group_id_offset: int,
) -> list[dict]:
    """キーワードのバッチを1回のClaude API呼び出しでクラスター化する。"""
    existing_text = "\n".join(f"- {t}" for t in existing_titles)
    kw_lines = [f'- {kw["キーワード"]} (vol:{kw["検索ボリューム"]})' for kw in kw_batch]
    kw_text = "\n".join(kw_lines)

    prompt = f"""あなたはSEOコンサルタントです。以下のAIM判定済みキーワードを分析してください。

## 既存記事タイトル（{len(existing_titles)}件）
{existing_text}

## AIM判定済みキーワード（{len(kw_batch)}件）
{kw_text}

## タスク
1. 各キーワードについて、既存記事と内容が大きく被るかを判定する
2. 被らないキーワードを意味的・テーマ的にグループ化する

## グループ化ルール
- 同じ検索意図・テーマのキーワードを1グループにまとめる
- 1グループ最大5キーワード
- main_keyword は最も短く・検索ボリュームが高いものを選ぶ
- 既存記事とほぼ同じ内容になるグループは "skip": true にする
- 既存記事に近いが切り口を変えれば書けるグループは "skip": false にして "note" に差別化案を記載する
- group_id は {group_id_offset + 1} から始める

## 出力（JSONのみ・前後の説明・コードブロック記号は不要）
[
  {{
    "group_id": {group_id_offset + 1},
    "main_keyword": "キーワード",
    "related_keywords": ["関連KW1", "関連KW2"],
    "article_theme": "記事テーマ（日本語で簡潔に）",
    "skip": false,
    "note": ""
  }}
]"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return json.loads(raw)


def cluster_keywords(aim_keywords: list[dict], existing_articles: list[dict]) -> list[dict]:
    """
    Claude APIでAIMキーワードを以下の順で処理する。
    1. 既存記事とのカニバリ判定（skip / differentiate / ok）
    2. ok・differentiate なキーワードを意味的にグループ化
    キーワード数が多い場合はバッチ処理する。
    """
    existing_titles = [a["title"] for a in existing_articles[:300]]
    all_clusters: list[dict] = []
    group_id_offset = 0

    for batch_start in range(0, len(aim_keywords), _CLUSTER_BATCH_SIZE):
        batch = aim_keywords[batch_start: batch_start + _CLUSTER_BATCH_SIZE]
        batch_end = min(batch_start + _CLUSTER_BATCH_SIZE, len(aim_keywords))
        print(f"  バッチ {batch_start + 1}–{batch_end} / {len(aim_keywords)} 件を処理中...")
        batch_clusters = _cluster_batch(batch, existing_titles, group_id_offset)
        all_clusters.extend(batch_clusters)
        group_id_offset += len(batch_clusters)

    return all_clusters


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── STEP 1 ──────────────────────────────
    print("\n[STEP 1] WordPress既存記事を取得中...")
    articles = fetch_existing_articles()
    with open(EXISTING_ARTICLES_PATH, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"[STEP 1] 保存完了: {EXISTING_ARTICLES_PATH}")

    # ── STEP 2 ──────────────────────────────
    print("\n[STEP 2] AIM判定キーワードを取得中...")
    aim_keywords = get_aim_keywords(extra_aim_values={"add", "now"})
    if not aim_keywords:
        print("[ERROR] AIMキーワードが0件です。終了します。")
        return

    # 投稿済み・カニバリスキップ済みのキーワードを除外
    excluded = get_excluded_keywords()
    if excluded:
        before = len(aim_keywords)
        aim_keywords = [kw for kw in aim_keywords if kw["キーワード"] not in excluded]
        print(f"[STEP 2] 除外後: {len(aim_keywords)}件（除外: {before - len(aim_keywords)}件）")

    if not aim_keywords:
        print("[STEP 2] 処理対象キーワードが0件です。終了します。")
        return

    print(f"[STEP 2] Claude APIでグループ化・カニバリ判定中（{len(aim_keywords)}件）...")
    clusters = cluster_keywords(aim_keywords, articles)

    with open(KEYWORD_CLUSTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(clusters, f, ensure_ascii=False, indent=2)

    # ── 結果表示 ────────────────────────────
    skip_count = sum(1 for c in clusters if c.get("skip"))
    active_count = len(clusters) - skip_count

    print(f"\n[STEP 2] クラスター数: {len(clusters)}件")
    print(f"         投稿対象: {active_count}件 / スキップ: {skip_count}件")
    print(f"[STEP 2] 保存完了: {KEYWORD_CLUSTERS_PATH}\n")
    print("─" * 60)
    print(f"{'状態':<6} {'G':>3}  {'メインKW':<30}  {'関連KW数':>4}  差別化メモ")
    print("─" * 60)
    for c in clusters:
        status = "[SKIP]" if c.get("skip") else "[OK]  "
        n_rel = len(c.get("related_keywords", []))
        note = c.get("note", "")[:40]
        print(f"{status} G{c['group_id']:02d}  {c['main_keyword']:<30}  {n_rel:>4}  {note}")
    print("─" * 60)

    # ── スプレッドシートにカニバリ判定結果を一括書き込む ──
    print("\n[STEP 3] スプレッドシートにカニバリ判定結果を書き込み中...")
    mark_cannibal_results_bulk(clusters)
    print("[STEP 3] 完了")

    # ── 凡例シートを作成・更新 ──
    print("\n[STEP 4] 凡例シートを作成・更新中...")
    setup_legend_sheet()
    print("[STEP 4] 完了")


if __name__ == "__main__":
    main()
