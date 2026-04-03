"""
AIVice 記事自動生成システム
https://workup-ai.com

Usage:
    # フルフロー（ラッコCSV → フィルター → Sheets AIM → 記事生成 → WP投稿）
    python main.py --csv path/to/rakko_keywords.csv

    # Sheetsのみ（CSVスキップ）
    python main.py --sheets-only

    # キーワードを直接指定
    python main.py --keyword "ChatGPT 使い方" --volume 8100

    # ドライラン（WP投稿しない）
    python main.py --csv keywords.csv --dry-run

    # カニバリチェックをスキップ
    python main.py --keyword "xxx" --no-cannibal-check

    # クラスターファイルから記事生成（build_clusters.py 実行後）
    python main.py --clusters
    python main.py --clusters --limit 1 --dry-run
"""
import argparse
import json
import os
import sys
import time

from modules.keyword_filter import load_and_filter
from modules.sheets_fetcher import get_aim_keywords, get_non_aim_keywords
from modules.article_generator import generate_article, generate_article_from_cluster
from modules.cannibal_checker import check_cannibalization
from modules.wordpress_poster import post_article_with_image
from modules.image_generator import generate_image_for_article
from config import MIN_SEARCH_VOLUME

KEYWORD_CLUSTERS_PATH = os.path.join(os.path.dirname(__file__), "output", "keyword_clusters.json")


def run_clusters_pipeline(
    clusters: list[dict],
    dry_run: bool = False,
    sub_keywords: list[str] | None = None,
) -> list[dict]:
    """
    keyword_clusters.json のクラスターリストから記事を生成・投稿する。
    skip=True のグループは自動的にスキップ。
    """
    results = []
    active = [c for c in clusters if not c.get("skip")]
    skipped = [c for c in clusters if c.get("skip")]

    print(f"[clusters] 対象: {len(active)}件 / スキップ: {len(skipped)}件")

    for i, cluster in enumerate(active, 1):
        main_kw = cluster["main_keyword"]
        print(f"\n{'='*60}")
        print(f"[{i}/{len(active)}] G{cluster['group_id']:02d} 「{main_kw}」")
        related = cluster.get("related_keywords", [])
        if related:
            print(f"  関連KW: {', '.join(related)}")
        if cluster.get("note"):
            print(f"  差別化: {cluster['note']}")
        print("=" * 60)

        try:
            article = generate_article_from_cluster(cluster, sub_keywords=sub_keywords)

            if dry_run:
                print(f"[dry-run] 投稿スキップ: 「{article['title']}」")
                results.append({
                    "keyword": main_kw,
                    "title": article["title"],
                    "status": "dry-run",
                })
            else:
                # 画像生成（失敗しても投稿は続行）
                image_bytes = None
                try:
                    image_bytes = generate_image_for_article(
                        keyword=main_kw,
                        article_theme=cluster.get("article_theme", ""),
                    )
                except Exception as img_err:
                    print(f"[image_generator] 画像生成スキップ（続行）: {img_err}")

                post_result = post_article_with_image(article, image_bytes=image_bytes)
                results.append({
                    "keyword": main_kw,
                    "title": article["title"],
                    "status": "success",
                    **post_result,
                })

        except Exception as e:
            print(f"[ERROR] 「{main_kw}」の処理中にエラー: {e}")
            results.append({"keyword": main_kw, "status": "error", "error": str(e)})

        if i < len(active):
            time.sleep(3)

    # skip されたグループも結果に含める
    for c in skipped:
        results.append({
            "keyword": c["main_keyword"],
            "status": "skipped",
            "reason": f"カニバリ: {c.get('note', 'skip=true')}",
        })

    return results


def run_pipeline(
    keywords: list[dict],
    dry_run: bool = False,
    skip_cannibal: bool = False,
    sub_keywords: list[str] | None = None,
) -> list[dict]:
    results = []
    total = len(keywords)

    for i, kw in enumerate(keywords, 1):
        keyword = kw["キーワード"]
        volume = kw.get("検索ボリューム", 0)
        print(f"\n{'='*60}")
        print(f"[{i}/{total}] キーワード: 「{keyword}」 (vol: {volume:,})")
        print("=" * 60)

        try:
            # --- 修正3: カニバリチェック ---
            differentiation_note = ""
            if not skip_cannibal:
                cannibal = check_cannibalization(keyword)
                if cannibal["status"] == "skip":
                    similar = cannibal.get("similar_titles", [])
                    print(f"[カニバリ] スキップ: 既存記事と重複 → {similar[:2]}")
                    results.append({
                        "keyword": keyword,
                        "status": "skipped",
                        "reason": f"カニバリ: {similar[:2]}",
                    })
                    continue
                elif cannibal["status"] == "differentiate":
                    differentiation_note = cannibal.get("differentiation_note", "")
                    print(f"[カニバリ] 差別化モードで生成: {differentiation_note}")

            # --- Step 4: 記事生成 ---
            article = generate_article(keyword, volume, differentiation_note, sub_keywords=sub_keywords)

            if dry_run:
                print(f"[dry-run] 投稿スキップ: 「{article['title']}」")
                results.append({
                    "keyword": keyword,
                    "title": article["title"],
                    "status": "dry-run",
                })
            else:
                # --- Step 5: 画像生成 → Step 6: WordPress投稿 ---
                image_bytes = None
                try:
                    image_bytes = generate_image_for_article(keyword=keyword)
                except Exception as img_err:
                    print(f"[image_generator] 画像生成スキップ（続行）: {img_err}")

                post_result = post_article_with_image(article, image_bytes=image_bytes)
                results.append({
                    "keyword": keyword,
                    "title": article["title"],
                    "status": "success",
                    **post_result,
                })

        except Exception as e:
            print(f"[ERROR] 「{keyword}」の処理中にエラー: {e}")
            results.append({"keyword": keyword, "status": "error", "error": str(e)})

        if i < total:
            time.sleep(3)

    return results


def print_summary(results: list[dict]) -> None:
    print(f"\n{'='*60}")
    print("【処理結果サマリー】")
    print("=" * 60)
    success  = [r for r in results if r["status"] in ("success", "dry-run")]
    skipped  = [r for r in results if r["status"] == "skipped"]
    errors   = [r for r in results if r["status"] == "error"]
    print(f"投稿: {len(success)}件 / スキップ: {len(skipped)}件 / エラー: {len(errors)}件 / 合計: {len(results)}件")
    for r in success:
        label = "[dry-run]" if r["status"] == "dry-run" else "[投稿済]"
        print(f"  {label} {r['title']} ({r['keyword']})")
        if r.get("edit_url"):
            print(f"           {r['edit_url']}")
    for r in skipped:
        print(f"  [SKIP]   {r['keyword']} — {r.get('reason','')}")
    for r in errors:
        print(f"  [ERROR]  {r['keyword']}: {r.get('error','')}")


def main():
    parser = argparse.ArgumentParser(description="AIVice 記事自動生成システム")
    parser.add_argument("--csv", help="ラッコキーワードCSVのパス")
    parser.add_argument("--sheets-only", action="store_true")
    parser.add_argument("--keyword", help="単一キーワードを直接指定")
    parser.add_argument("--volume", type=int, default=MIN_SEARCH_VOLUME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-cannibal-check", action="store_true", help="カニバリチェックをスキップ")
    parser.add_argument("--clusters", action="store_true",
                        help="output/keyword_clusters.json を使ってクラスターベースで記事生成")
    args = parser.parse_args()

    # ── サブキーワード（AIM未判定）を一度だけ取得 ──
    sub_keywords: list[str] = []
    try:
        sub_keywords = get_non_aim_keywords()
    except Exception as e:
        print(f"[警告] サブキーワード取得失敗（続行）: {e}")

    # ── クラスターモード ──────────────────────
    if args.clusters:
        if not os.path.exists(KEYWORD_CLUSTERS_PATH):
            print(f"[ERROR] {KEYWORD_CLUSTERS_PATH} が見つかりません。先に build_clusters.py を実行してください。")
            sys.exit(1)
        with open(KEYWORD_CLUSTERS_PATH, encoding="utf-8") as f:
            clusters = json.load(f)
        if args.limit:
            active = [c for c in clusters if not c.get("skip")]
            skip_list = [c for c in clusters if c.get("skip")]
            clusters = active[: args.limit] + skip_list
        print(f"\n[clusters] {KEYWORD_CLUSTERS_PATH} からクラスターを読み込み: {len(clusters)}件")
        results = run_clusters_pipeline(clusters, dry_run=args.dry_run, sub_keywords=sub_keywords)
        print_summary(results)
        return

    keywords: list[dict] = []

    if args.keyword:
        keywords = [{"キーワード": args.keyword, "検索ボリューム": args.volume}]

    elif args.csv:
        print("\n[STEP 1-2] ラッコキーワードCSVを読み込み・フィルタリング...")
        filtered_df = load_and_filter(args.csv)
        csv_keywords = filtered_df[["キーワード", "検索ボリューム"]].to_dict("records")

        print("\n[STEP 3] GoogleスプレッドシートからAIM判定キーワードを取得...")
        try:
            aim_keywords = get_aim_keywords()
            aim_set = {kw["キーワード"] for kw in aim_keywords}
            keywords = [kw for kw in csv_keywords if kw["キーワード"] in aim_set]
            print(f"[main] CSV×AIM一致キーワード: {len(keywords)}件")
            if not keywords:
                print("[警告] 0件のためCSV全件で続行します")
                keywords = csv_keywords
        except Exception as e:
            print(f"[警告] GoogleSheets取得失敗: {e} → CSV全件で続行します")
            keywords = csv_keywords

    elif args.sheets_only:
        print("\n[STEP 3] GoogleスプレッドシートからAIM判定キーワードを取得...")
        keywords = get_aim_keywords()

    else:
        parser.print_help()
        sys.exit(1)

    if not keywords:
        print("[ERROR] 処理対象キーワードが0件です。終了します。")
        sys.exit(1)

    if args.limit:
        keywords = keywords[: args.limit]

    print(f"\n[main] 処理対象: {len(keywords)}件")
    for kw in keywords[:5]:
        print(f"  - {kw['キーワード']} (vol: {kw.get('検索ボリューム', '?'):,})")
    if len(keywords) > 5:
        print(f"  ... 他 {len(keywords) - 5} 件")

    print("\n[STEP 4-6] 記事生成・WordPress投稿を開始...")
    results = run_pipeline(
        keywords,
        dry_run=args.dry_run,
        skip_cannibal=args.no_cannibal_check,
        sub_keywords=sub_keywords,
    )
    print_summary(results)


if __name__ == "__main__":
    main()
