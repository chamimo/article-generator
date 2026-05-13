"""
test_images.py
画像生成単体テストスクリプト

WP投稿・記事生成は行わず、アイキャッチ画像のみを複数件生成して
output/images/ に保存する。統一感・topic_en・コスト感の確認用。

使い方:
  # デフォルト10件（スクリプト内 DEFAULT_KEYWORDS）
  python3 test_images.py

  # キーワードを直接指定
  python3 test_images.py "ChatGPT 使い方" "Claude 違い" "生成AI 副業"

  # 件数だけ指定（スプレッドシートから先頭N件）
  python3 test_images.py --count 5

  # ブログ変更（デフォルト: workup-ai）
  python3 test_images.py --blog hataraku
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ─────────────────────────────────────────────
# AIVice 向けデフォルトテストキーワード（10件）
# ─────────────────────────────────────────────
DEFAULT_KEYWORDS = [
    "ChatGPT 使い方 初心者",
    "Claude AI 特徴",
    "生成AI 副業 始め方",
    "プロンプト 書き方 コツ",
    "Midjourney 使い方",
    "AI画像生成 無料",
    "ChatGPT API 活用",
    "ノーコード 自動化 ツール",
    "AI ライティング ブログ",
    "Gemini ChatGPT 比較",
]


def _setup_context(blog_name: str) -> None:
    """ブログコンテキストを初期化する。"""
    os.environ["ARTICLE_SITE"] = blog_name
    # config が blog_name を参照するため、importより先に設定
    import importlib, generate_lite as gl
    importlib.reload(gl)

    cfg = gl.load_blog_config(blog_name)
    from modules import wp_context
    wp_context.set_context(
        wp_url=cfg.wp_url,
        image_style=cfg.image_style,
        eyecatch_model=cfg.eyecatch_model,
        article_image_model=cfg.article_image_model,
    )
    return cfg


def _fetch_keywords_from_sheet(blog_name: str, count: int) -> list[str]:
    """スプレッドシートのキーワードシートから先頭 count 件を取得する。"""
    try:
        os.environ["ARTICLE_SITE"] = blog_name
        from generate_lite import load_blog_config, fetch_candidates
        cfg              = load_blog_config(blog_name)
        candidates, _    = fetch_candidates(blog_cfg=cfg)   # (candidates, sub_keywords) を返す
        keywords         = [c["keyword"] for c in candidates[:count]]
        print(f"[test_images] スプレッドシートから {len(keywords)} 件取得")
        return keywords
    except Exception as e:
        print(f"[test_images] スプレッドシート取得失敗、デフォルトキーワード使用: {e}")
        return DEFAULT_KEYWORDS[:count]


def run_test(keywords: list[str], blog_name: str, variants: list[str],
             variant_count: int = 1) -> None:
    """キーワードリストに対してアイキャッチ画像を生成し結果を表示する。
    variant_count > 1 かつ variant に "c" が含まれる場合は
    generate_eyecatch_variants で複数パターンを生成する。
    """
    from modules.image_generator import generate_eyecatch_image, generate_eyecatch_variants

    use_multi = variant_count > 1 and "c" in variants
    total   = len(keywords) * (len(variants) if not use_multi else (len([v for v in variants if v != "c"]) + variant_count))
    success = 0
    failed  = 0
    results = []

    print()
    print("=" * 60)
    if use_multi:
        print(f"  画像生成テスト開始: {len(keywords)} 件 / variant=c×{variant_count}パターン / blog={blog_name}")
    else:
        print(f"  画像生成テスト開始: {len(keywords)} 件 × variant={','.join(variants)} / blog={blog_name}")
    print("=" * 60)

    n = 0
    for kw in keywords:
        for vt in variants:
            if vt == "c" and use_multi:
                # 複数パターン生成
                print()
                print(f"  キーワード: {kw}  variant=c × {variant_count}パターン")
                t0 = time.time()
                try:
                    imgs = generate_eyecatch_variants(keyword=kw, article_theme="", count=variant_count)
                    elapsed = time.time() - t0
                    n += variant_count
                    for pi, img in enumerate(imgs, 1):
                        size_kb = len(img) // 1024
                        success += 1
                        results.append({"kw": kw, "vt": f"c-p{pi}", "ok": True,
                                        "size_kb": size_kb, "sec": elapsed / variant_count})
                    print(f"  → {variant_count}枚成功 ({elapsed:.1f}秒合計)")
                except Exception as e:
                    elapsed = time.time() - t0
                    n += 1
                    failed += 1
                    results.append({"kw": kw, "vt": "c", "ok": False, "error": str(e), "sec": elapsed})
                    print(f"  → 失敗 ({elapsed:.1f}秒): {e}")
            else:
                n += 1
                print()
                print(f"[{n}] キーワード: {kw}  variant={vt}")
                t0 = time.time()
                try:
                    img_bytes = generate_eyecatch_image(keyword=kw, article_theme="", variant=vt)
                    elapsed   = time.time() - t0
                    size_kb   = len(img_bytes) // 1024
                    success  += 1
                    results.append({"kw": kw, "vt": vt, "ok": True, "size_kb": size_kb, "sec": elapsed})
                    print(f"  → 成功 ({size_kb}KB, {elapsed:.1f}秒)")
                except Exception as e:
                    elapsed  = time.time() - t0
                    failed  += 1
                    results.append({"kw": kw, "vt": vt, "ok": False, "error": str(e), "sec": elapsed})
                    print(f"  → 失敗 ({elapsed:.1f}秒): {e}")

    # ─── サマリー ───────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  結果サマリー")
    print("=" * 60)
    print(f"  成功: {success}  失敗: {failed}")
    print()
    print(f"  {'No':<3}  {'VT':<5}  {'結果':<4}  {'KB':>5}  {'秒':>5}  キーワード")
    print(f"  {'-'*3}  {'-'*5}  {'-'*4}  {'-'*5}  {'-'*5}  {'-'*30}")
    for i, r in enumerate(results, 1):
        status = "OK" if r["ok"] else "NG"
        kb     = f"{r.get('size_kb', '-'):>5}" if r["ok"] else "    -"
        sec    = f"{r['sec']:>5.1f}"
        print(f"  {i:<3}  {r['vt']:<5}  {status:<4}  {kb}  {sec}  {r['kw']}")

    print()
    print(f"  画像保存先: article-generator-hataraku/output/images/")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="画像生成単体テスト")
    parser.add_argument("keywords", nargs="*", help="テスト対象キーワード（省略時はデフォルト使用）")
    parser.add_argument("--blog",    default="workup-ai", help="対象ブログ名（デフォルト: workup-ai）")
    parser.add_argument("--count",   type=int, default=None,
                        help="スプレッドシートから取得する件数（keywords 未指定時に有効）")
    parser.add_argument("--variant", default="a",
                        help="テンプレートバリアント: a / b / c / ab（デフォルト: a）")
    parser.add_argument("--variants", type=int, default=1,
                        help="variant=c のとき1キーワードあたり生成するパターン数（デフォルト: 1）")
    args = parser.parse_args()

    # バリアント解析
    if args.variant == "ab":
        variants = ["a", "b"]
    else:
        variants = [v.strip() for v in args.variant.split(",") if v.strip()]

    # ブログコンテキスト初期化
    _setup_context(args.blog)

    # キーワード決定
    if args.keywords:
        keywords = args.keywords
        print(f"[test_images] キーワード直接指定: {len(keywords)} 件")
    elif args.count:
        keywords = _fetch_keywords_from_sheet(args.blog, args.count)
    else:
        keywords = DEFAULT_KEYWORDS
        print(f"[test_images] デフォルトキーワード使用: {len(keywords)} 件")

    run_test(keywords, args.blog, variants, variant_count=args.variants)


if __name__ == "__main__":
    main()
