"""
記事自動生成システム（マルチサイト対応）

Usage:
    # サイト指定（省略時は workup-ai）
    python main.py --site workup-ai --clusters --limit 5

    # フルフロー（ラッコCSV → フィルター → Sheets AIM → 記事生成 → WP投稿）
    python main.py --site workup-ai --csv path/to/rakko_keywords.csv

    # Sheetsのみ（CSVスキップ）
    python main.py --site workup-ai --sheets-only

    # キーワードを直接指定
    python main.py --site workup-ai --keyword "ChatGPT 使い方" --volume 8100

    # ドライラン（WP投稿しない）
    python main.py --site workup-ai --csv keywords.csv --dry-run

    # クラスターファイルから記事生成（build_clusters.py 実行後）
    python main.py --site workup-ai --clusters
    python main.py --site workup-ai --clusters --limit 1 --dry-run
"""
import argparse
import json
import os
import sys
import time

# ── --site を最初に解析し、config インポート前に ARTICLE_SITE を設定 ──────
# config.py は import 時点で ARTICLE_SITE を参照するため、
# argparse の本解析より前に parse_known_args で先行取得する。
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--site", default="workup-ai")
_pre_args, _ = _pre.parse_known_args()
os.environ["ARTICLE_SITE"] = _pre_args.site

# ── 以降のインポートは ARTICLE_SITE 設定後 ──────────────────────────────
from modules.keyword_filter import load_and_filter
from modules.sheets_fetcher import get_aim_keywords, get_non_aim_keywords, get_excluded_keywords
from modules.article_generator import generate_article, generate_article_from_cluster
from modules.cannibal_checker import check_cannibalization, add_session_title
from modules.wordpress_poster import post_article_with_image
from modules.image_generator import generate_image_for_article
from modules.keyword_utils import detect_parent_keyword
from config import MIN_SEARCH_VOLUME

_SITE = os.environ["ARTICLE_SITE"]
KEYWORD_CLUSTERS_PATH = os.path.join(os.path.dirname(__file__), "output", "keyword_clusters.json")


def _interleave_clusters(active: list[dict]) -> list[dict]:
    """
    親キーワードが偏らないよう、異なる親グループを交互に並び替える（ラウンドロビン）。
    親キーワードは _detect_parent_keyword() で動的に検出するためハードコード不要。
    """
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in active:
        parent = detect_parent_keyword(c.get("main_keyword", ""))
        c["_category"] = parent
        groups[parent].append(c)

    # グループ件数の多い順に並べてラウンドロビン
    sorted_groups = sorted(groups.values(), key=len, reverse=True)
    interleaved: list[dict] = []
    i = 0
    while any(g for g in sorted_groups):
        idx = i % len(sorted_groups)
        if sorted_groups[idx]:
            interleaved.append(sorted_groups[idx].pop(0))
        i += 1

    return interleaved


def run_clusters_pipeline(
    clusters: list[dict],
    dry_run: bool = False,
    sub_keywords: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    keyword_clusters.json のクラスターリストから記事を生成・投稿する。
    skip=True のグループは自動的にスキップ。
    親キーワードが偏らないようラウンドロビンで並び替えた後に limit を適用する。
    """
    results = []
    active = [c for c in clusters if not c.get("skip")]
    skipped = [c for c in clusters if c.get("skip")]

    # ── 投稿済み・カニバリスキップ済みをシートから取得して除外 ──
    try:
        excluded = get_excluded_keywords()
        excluded_lower = {k.lower() for k in excluded}
        before = len(active)
        active = [c for c in active if c["main_keyword"].lower() not in excluded_lower]
        posted_skip = before - len(active)
        if posted_skip:
            print(f"[clusters] 投稿済みスキップ: {posted_skip}件（シート照合）")
    except Exception as e:
        print(f"[警告] 投稿済みキーワード取得失敗（スキップチェックなし）: {e}")

    # 親キーワード分散：ラウンドロビンで並び替え（limit適用前）
    active = _interleave_clusters(active)

    # limit はインターリーブ後に適用することで多様性を保証
    if limit:
        active = active[:limit]

    from collections import Counter
    parent_count = Counter(c.get("_category", "?") for c in active)
    print(f"[clusters] 対象: {len(active)}件 / スキップ: {len(skipped)}件")
    print(f"[clusters] 親KWグループ: {dict(parent_count)}")

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
            add_session_title(article.get("title", ""))

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
            # 生成したタイトルをセッションキャッシュに登録（同一セッション内カニバリ防止）
            add_session_title(article.get("title", ""))

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
    parser.add_argument("--site", default=os.environ.get("ARTICLE_SITE", "workup-ai"),
                        help="対象サイト名 (sites/<site>/config.py を使用)")
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
        print(f"\n[clusters] {KEYWORD_CLUSTERS_PATH} からクラスターを読み込み: {len(clusters)}件")
        results = run_clusters_pipeline(
            clusters,
            dry_run=args.dry_run,
            sub_keywords=sub_keywords,
            limit=args.limit,
        )
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
