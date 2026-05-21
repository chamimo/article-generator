#!/usr/bin/env python3
"""
JSON-LD構造化データ生成・WordPress挿入スクリプト

記事IDを指定すると、WordPress REST APIから記事情報を取得し
Article / FAQPage / BreadcrumbList の3種のJSON-LDを生成して
記事末尾に <!-- wp:html --> ブロックとして追記します。
既存のJSON-LDが含まれるスキーマは上書きせず、不足分のみ追記します。

使用例:
  python3 add_json_ld.py --blog workup-ai --post-id 10369
  python3 add_json_ld.py --blog hataraku  --post-id 123 --dry-run
  python3 add_json_ld.py --blog workup-ai --post-id 10369 --php-only
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone

import requests


# ============================================================
# ブログ設定
# ============================================================
BLOG_CONFIGS = {
    "hataraku": {
        "url":  "https://hataraku-navi.com",
        "user": "wk@naturira.com",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "はた楽ナビ",
    },
    "workup-ai": {
        "url":  "https://workup-ai.com",
        "user": "wk@naturira.com",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "AIVice",
    },
    "ys-trend": {
        "url":  "https://ys-trend.com",
        "user": "yscafe3824",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "ワイズトレンド",
    },
    "kaerudoko": {
        "url":  "https://kaerudoko.com",
        "user": "wk@naturira.com",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "どこで売ってるナビ",
    },
    "hapipo8": {
        "url":  "https://hapipo8.com",
        "user": "tomopuchi",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "気になることブログ",
    },
    "hida-no-omoide": {
        "url":  "https://hida-no-omoide.com",
        "user": "tomopuchi",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "飛騨の思い出",
    },
    "web-study1": {
        "url":  "https://web-study1.com",
        "user": "nekoomochi",
        "pass": "***WP_APP_PASSWORD_REMOVED***",
        "name": "オンライン学習ナビ",
    },
}

BLOG_ALIASES = {
    "aivice": "workup-ai",
    "ai-vice": "workup-ai",
    "hataraku-navi": "hataraku",
}


# ============================================================
# FAQ抽出（SWELLブロック形式）
# ============================================================
def extract_faq(html: str) -> list[dict]:
    """SWELL FAQブロックから質問・回答を抽出する。"""
    items = []
    # SWELL FAQ: <h4 class="faq_q">質問</h4><div class="faq_a"><p>回答</p></div>
    pattern = re.compile(
        r'<h4[^>]*class="faq_q"[^>]*>(.*?)</h4>\s*<div[^>]*class="faq_a"[^>]*>(.*?)</div>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        q = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        a = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if q and a:
            items.append({"question": q, "answer": a})
    return items


# ============================================================
# カテゴリ情報取得
# ============================================================
def get_category_info(wp_url: str, auth: tuple, cat_ids: list[int]) -> list[dict]:
    """カテゴリIDからスラッグ・名称を取得する。"""
    if not cat_ids:
        return []
    cats = []
    for cid in cat_ids[:2]:  # パンくずは最大2階層
        try:
            r = requests.get(
                f"{wp_url}/wp-json/wp/v2/categories/{cid}",
                auth=auth, timeout=10,
            )
            if r.status_code == 200:
                d = r.json()
                cats.append({"id": cid, "name": d.get("name", ""), "slug": d.get("slug", "")})
        except Exception:
            pass
    return cats


# ============================================================
# JSON-LD生成
# ============================================================
def build_article_schema(post: dict, site_name: str, site_url: str) -> dict:
    pub  = post.get("date_gmt", "")[:10]
    mod  = post.get("modified_gmt", post.get("date_gmt", ""))[:10]
    title = post["title"]["rendered"]
    link  = post.get("link", "")
    desc  = re.sub(r"<[^>]+>", "", post.get("excerpt", {}).get("rendered", "")).strip()[:160]
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "datePublished": pub,
        "dateModified": mod,
        "author": {
            "@type": "Organization",
            "name": site_name,
            "url": site_url,
        },
        "publisher": {
            "@type": "Organization",
            "name": site_name,
            "url": site_url,
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": link,
        },
    }


def build_faqpage_schema(faq_items: list[dict]) -> dict | None:
    if not faq_items:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["answer"],
                },
            }
            for item in faq_items
        ],
    }


def build_breadcrumb_schema(
    post: dict, cats: list[dict], site_url: str
) -> dict:
    items = [{"@type": "ListItem", "position": 1, "name": "ホーム", "item": site_url}]
    for i, cat in enumerate(cats, start=2):
        items.append({
            "@type": "ListItem",
            "position": i,
            "name": cat["name"],
            "item": f"{site_url}/category/{cat['slug']}/",
        })
    items.append({
        "@type": "ListItem",
        "position": len(items) + 1,
        "name": post["title"]["rendered"],
        "item": post.get("link", ""),
    })
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


# ============================================================
# Gutenbergブロックとして包む
# ============================================================
def wrap_json_ld(schema: dict) -> str:
    data = json.dumps(schema, ensure_ascii=False, indent=2)
    return (
        '<!-- wp:html -->\n'
        '<script type="application/ld+json">\n'
        f'{data}\n'
        '</script>\n'
        '<!-- /wp:html -->'
    )


# ============================================================
# 既存JSON-LDの検出
# ============================================================
def detect_existing_types(content: str) -> set[str]:
    """content内に既に含まれているJSON-LDの@typeを返す。"""
    found = set()
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', content, re.DOTALL):
        try:
            d = json.loads(m.group(1))
            t = d.get("@type", "")
            if t:
                found.add(t)
        except Exception:
            pass
    return found


# ============================================================
# PHP snippet生成（functions.php用）
# ============================================================
def build_php_snippet(schemas: list[dict], post_id: int) -> str:
    lines = [
        "<?php",
        f"// JSON-LD 構造化データ（post_id: {post_id}）",
        f"// 生成日時: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "// functions.php に追記するか、プラグイン（Code Snippets等）で追加してください",
        "",
        "add_action('wp_head', function() {",
        f"    if (!is_singular() || get_the_ID() !== {post_id}) return;",
        "    ?>",
    ]
    for schema in schemas:
        data = json.dumps(schema, ensure_ascii=False, indent=4)
        lines.append(f'    <script type="application/ld+json">')
        lines.append(f'    {data}')
        lines.append(f'    </script>')
    lines += ["    <?php", "});"]
    return "\n".join(lines)


# ============================================================
# メイン処理
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="JSON-LD構造化データを生成してWordPressに挿入")
    parser.add_argument("--blog",    required=True, help="ブログ名（workup-ai, hataraku など）")
    parser.add_argument("--post-id", required=True, type=int, help="WordPress記事ID")
    parser.add_argument("--dry-run", action="store_true", help="WordPressへの書き込みをスキップ")
    parser.add_argument("--php-only", action="store_true", help="functions.php用PHPスニペットのみ出力")
    args = parser.parse_args()

    blog_key = BLOG_ALIASES.get(args.blog, args.blog)
    cfg = BLOG_CONFIGS.get(blog_key)
    if not cfg:
        print(f"❌ ブログ '{args.blog}' が見つかりません。利用可能: {', '.join(BLOG_CONFIGS)}")
        sys.exit(1)

    wp_url   = cfg["url"]
    auth     = (cfg["user"], cfg["pass"])
    site_name = cfg["name"]

    # --- 記事取得 ---
    print(f"[fetch] 記事取得: {wp_url}/wp-json/wp/v2/posts/{args.post_id}")
    resp = requests.get(
        f"{wp_url}/wp-json/wp/v2/posts/{args.post_id}",
        auth=auth, timeout=15,
        params={"_fields": "id,title,link,content,excerpt,date_gmt,modified_gmt,categories,status"},
    )
    if resp.status_code != 200:
        print(f"❌ 記事取得失敗: HTTP {resp.status_code}")
        sys.exit(1)

    post    = resp.json()
    content = post["content"]["rendered"]
    title   = post["title"]["rendered"]
    print(f"[fetch] タイトル: {title}（status={post.get('status')}）")

    # --- 既存JSON-LD確認 ---
    existing = detect_existing_types(content)
    if existing:
        print(f"[check] 既存JSON-LD: {existing}")
    else:
        print("[check] 既存JSON-LDなし → 3種全て生成します")

    # --- FAQ抽出 ---
    faq_items = extract_faq(content)
    print(f"[faq]   FAQ抽出: {len(faq_items)}問")

    # --- カテゴリ取得 ---
    cat_ids = post.get("categories", [])
    cats    = get_category_info(wp_url, auth, cat_ids)
    cat_names = [c["name"] for c in cats]
    print(f"[cat]   カテゴリ: {cat_names}")

    # --- スキーマ生成（既存は除外） ---
    schemas_to_add = []
    blocks_to_add  = []

    if "Article" not in existing:
        s = build_article_schema(post, site_name, wp_url)
        schemas_to_add.append(s)
        blocks_to_add.append(wrap_json_ld(s))
        print("[schema] Article → 追加")
    else:
        print("[schema] Article → スキップ（既存）")

    if "FAQPage" not in existing and faq_items:
        s = build_faqpage_schema(faq_items)
        schemas_to_add.append(s)
        blocks_to_add.append(wrap_json_ld(s))
        print(f"[schema] FAQPage → 追加 ({len(faq_items)}問)")
    elif not faq_items:
        print("[schema] FAQPage → スキップ（FAQ未検出）")
    else:
        print("[schema] FAQPage → スキップ（既存）")

    if "BreadcrumbList" not in existing:
        s = build_breadcrumb_schema(post, cats, wp_url)
        schemas_to_add.append(s)
        blocks_to_add.append(wrap_json_ld(s))
        print("[schema] BreadcrumbList → 追加")
    else:
        print("[schema] BreadcrumbList → スキップ（既存）")

    if not schemas_to_add:
        print("✅ 追加するJSON-LDなし（全スキーマ既存）")
        return

    # --- PHP snippetモード ---
    if args.php_only:
        php = build_php_snippet(schemas_to_add, args.post_id)
        out_path = f"output/json_ld_{blog_key}_{args.post_id}.php"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(php)
        print(f"\n✅ PHPスニペット出力: {out_path}")
        print("   functions.php に追記するか、Code Snippetsプラグインで追加してください")
        return

    # --- dry-run ---
    new_blocks = "\n\n" + "\n\n".join(blocks_to_add)
    if args.dry_run:
        print("\n===== [DRY RUN] 追記予定のJSON-LD =====")
        print(new_blocks)
        print("======================================")
        return

    # --- WordPress更新 ---
    raw_content = post["content"]["raw"] if "raw" in post["content"] else content
    # raw が取れない場合は rendered を使う（一部環境では raw が空）
    if not raw_content.strip():
        raw_content = content

    updated_content = raw_content.rstrip() + new_blocks

    print(f"[post]  WordPress更新中 (ID: {args.post_id})...")
    upd = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts/{args.post_id}",
        auth=auth,
        json={"content": updated_content},
        timeout=30,
    )
    if upd.status_code in (200, 201):
        d = upd.json()
        print(f"✅ 更新完了: {wp_url}/wp-admin/post.php?post={args.post_id}&action=edit")
        print(f"   status={d.get('status')}  modified={d.get('modified_gmt','')[:10]}")
    else:
        print(f"❌ 更新失敗: HTTP {upd.status_code}")
        print(upd.text[:300])


if __name__ == "__main__":
    main()
