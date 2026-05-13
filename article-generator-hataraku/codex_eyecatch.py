#!/usr/bin/env python3
"""
Codex アイキャッチ専用ディレクター。

Claude Code が作成した WordPress 下書きに対して、
AIライフスタイルブランド調のアイキャッチを生成し featured image に設定する。
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth


def _plain_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    return html.unescape(text).strip()


def _safe_slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", (text or "").lower()).strip("-")
    return slug or fallback


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WordPress下書きにCodexブランドのアイキャッチを自動設定します。"
    )
    parser.add_argument("--blog", default="workup-ai", help="blogs/配下のブログ名")
    parser.add_argument("--post-id", type=int, help="対象のWordPress投稿ID")
    parser.add_argument("--limit", type=int, default=1, help="処理する下書き数")
    parser.add_argument("--overwrite", action="store_true", help="既存アイキャッチも上書きする")
    parser.add_argument("--dry-run", action="store_true", help="取得だけ確認して生成・更新しない")
    return parser.parse_args()


def _fetch_target_drafts(
    wp_url: str,
    auth: HTTPBasicAuth,
    post_id: int | None,
    limit: int,
    overwrite: bool,
) -> list[dict]:
    base = wp_url.rstrip("/")
    fields = "id,title,slug,status,featured_media,link,modified"

    if post_id:
        resp = requests.get(
            f"{base}/wp-json/wp/v2/posts/{post_id}",
            auth=auth,
            params={"context": "edit", "_fields": fields},
            timeout=30,
        )
        resp.raise_for_status()
        post = resp.json()
        return [post] if overwrite or not int(post.get("featured_media") or 0) else []

    resp = requests.get(
        f"{base}/wp-json/wp/v2/posts",
        auth=auth,
        params={
            "status": "draft",
            "orderby": "modified",
            "order": "desc",
            "per_page": min(max(limit * 3, 3), 50),
            "context": "edit",
            "_fields": fields,
        },
        timeout=30,
    )
    resp.raise_for_status()

    targets: list[dict] = []
    for post in resp.json():
        if not overwrite and int(post.get("featured_media") or 0):
            continue
        targets.append(post)
        if len(targets) >= limit:
            break
    return targets


def _set_featured_media(
    wp_url: str,
    auth: HTTPBasicAuth,
    post_id: int,
    media_id: int,
    source_url: str,
    title: str,
) -> None:
    payload = {
        "featured_media": media_id,
        "meta": {
            "ssp_meta_ogimage_url": source_url,
            "swell_meta_thumb_caption": title,
            "_swell_post_eye_catch_caption": title,
        },
    }
    resp = requests.post(
        f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}",
        auth=auth,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()


def main() -> int:
    args = _parse_args()

    os.environ["ARTICLE_SITE"] = args.blog
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from generate_lite import load_blog_config
    from modules import wp_context
    from modules.image_generator import generate_lifestyle_eyecatch_image
    from modules.wordpress_poster import upload_media

    cfg = load_blog_config(args.blog)
    wp_context.set_context(
        cfg.wp_url,
        cfg.wp_username,
        cfg.wp_app_password,
        wp_post_status=cfg.wp_post_status,
        candidate_ss_id=cfg.candidate_ss_id,
        candidate_sheet=cfg.candidate_sheet,
        image_style=cfg.image_style,
        blog_meta={
            "site_purpose": cfg.site_purpose,
            "target": cfg.target,
            "writing_taste": cfg.writing_taste,
            "genre_detail": cfg.genre_detail or cfg.genre,
            "search_intent": cfg.search_intent,
        },
        asp_ss_id=cfg.asp_ss_id,
        eyecatch_model=cfg.eyecatch_model or "gpt-image-2",
        article_image_model=cfg.article_image_model,
    )

    auth = HTTPBasicAuth(cfg.wp_username, cfg.wp_app_password)
    posts = _fetch_target_drafts(
        cfg.wp_url,
        auth,
        post_id=args.post_id,
        limit=args.limit,
        overwrite=args.overwrite,
    )

    if not posts:
        print("[codex-eyecatch] 対象の下書きがありません")
        return 0

    print(f"[codex-eyecatch] 対象: {len(posts)}件")
    for post in posts:
        post_id = int(post["id"])
        title = _plain_title(post.get("title", {}).get("rendered", ""))
        slug = _safe_slug(post.get("slug", ""), f"post-{post_id}")
        print(f"\n[codex-eyecatch] #{post_id} {title}")

        if args.dry_run:
            continue

        image_bytes = generate_lifestyle_eyecatch_image(
            title=title,
            keyword=title,
            article_theme=cfg.genre,
        )
        alt_text = f"{title}のアイキャッチ画像"
        media_id, source_url = upload_media(
            image_bytes=image_bytes,
            filename=f"{slug}-codex-eyecatch.jpg",
            mime_type="image/jpeg",
            alt_text=alt_text,
            title=alt_text,
            caption=f"#{cfg.display_name} #AIライフスタイル",
        )
        _set_featured_media(cfg.wp_url, auth, post_id, media_id, source_url, title)
        edit_url = f"{cfg.wp_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
        print(f"[codex-eyecatch] featured image 設定完了: media_id={media_id}")
        print(f"[codex-eyecatch] 編集URL: {edit_url}")

    wp_context.clear_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
