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
import random
import re
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

_LIBRARY_EYECATCH_BLOGS = {"hapipo8", "kaerudoko", "ys-trend", "groowill-film"}


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


def _fetch_target_posts(
    wp_url: str,
    auth: HTTPBasicAuth,
    post_id: int | None,
    limit: int,
    overwrite: bool,
    status: str = "draft",
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
            "status": status or "draft",
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


def _fetch_media_candidates(
    wp_url: str,
    auth: HTTPBasicAuth,
    search_term: str = "",
    per_page: int = 50,
) -> list[dict]:
    params = {
        "media_type": "image",
        "per_page": per_page,
        "_fields": "id,source_url,alt_text,caption,date",
    }
    if search_term:
        params["search"] = search_term

    try:
        resp = requests.get(
            f"{wp_url.rstrip('/')}/wp-json/wp/v2/media",
            auth=auth,
            params=params,
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


def _select_library_media(
    wp_url: str,
    auth: HTTPBasicAuth,
    title: str,
) -> dict | None:
    """
    OpenAI画像生成を使わないブログ用に、既存メディアライブラリから1枚選ぶ。

    まず記事タイトル由来の語で探し、見つからなければ直近の画像から選ぶ。
    これにより対象ブログでは有料の gpt-image-2 を呼ばず、以前の無料画像運用に戻す。
    """
    search_terms: list[str] = []
    plain = _plain_title(title)
    if plain:
        search_terms.append(plain)
        search_terms.extend([part for part in re.split(r"[\s　・｜|／/、。!！?？:：]+", plain) if len(part) >= 2][:4])

    seen_terms: set[str] = set()
    for term in search_terms:
        if term in seen_terms:
            continue
        seen_terms.add(term)
        candidates = _fetch_media_candidates(wp_url, auth, search_term=term)
        if candidates:
            chosen = random.choice(candidates)
            print(f"[codex-eyecatch] 既存ライブラリ画像を選択: search={term} media_id={chosen.get('id')}")
            return chosen

    candidates = _fetch_media_candidates(wp_url, auth, search_term="")
    if candidates:
        chosen = random.choice(candidates)
        print(f"[codex-eyecatch] 既存ライブラリ画像を選択: recent media_id={chosen.get('id')}")
        return chosen

    return None


def _resolve_generator_root(blog_name: str) -> Path:
    """
    blog_config.json が存在する generator ルートを解決する。

    優先順位:
      1. BLOG_CONFIG_PATH 環境変数 (blog_config.json への直接パス)
      2. ARTICLE_GENERATOR_ROOT 環境変数 (generator ルートディレクトリ)
      3. カレントディレクトリ配下 blogs/{blog}/blog_config.json
      4. スクリプト自身のディレクトリ (既存の動作)
      5. 兄弟ディレクトリのフォールバック検索
    """
    # 1. BLOG_CONFIG_PATH
    explicit = os.environ.get("BLOG_CONFIG_PATH")
    if explicit:
        p = Path(explicit)
        if p.exists():
            # blogs/<blog>/blog_config.json → root は3階層上
            return p.parent.parent.parent

    # 2. ARTICLE_GENERATOR_ROOT
    root_env = os.environ.get("ARTICLE_GENERATOR_ROOT")
    if root_env:
        root = Path(root_env)
        if (root / "blogs" / blog_name / "blog_config.json").exists():
            return root

    # 3. カレントディレクトリ
    if (Path.cwd() / "blogs" / blog_name / "blog_config.json").exists():
        return Path.cwd()

    # 4. スクリプト自身のディレクトリ (従来の動作)
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "blogs" / blog_name / "blog_config.json").exists():
        return script_dir

    # 5. 兄弟ディレクトリを検索
    for sibling in script_dir.parent.iterdir():
        if sibling.is_dir() and (sibling / "blogs" / blog_name / "blog_config.json").exists():
            return sibling

    # 見つからない場合はスクリプトディレクトリに戻す (FileNotFoundError は load_blog_config が出す)
    return script_dir


def main() -> int:
    args = _parse_args()

    os.environ["ARTICLE_SITE"] = args.blog
    generator_root = _resolve_generator_root(args.blog)
    sys.path.insert(0, str(generator_root))
    if generator_root != Path(__file__).resolve().parent:
        print(f"[codex-eyecatch] generator root: {generator_root}")

    import inspect
    from generate_lite import load_blog_config
    from modules import wp_context
    from modules.wordpress_poster import upload_media

    cfg = load_blog_config(args.blog)

    # image_generate=false のブログはアイキャッチ自動設定をスキップ
    if not getattr(cfg, "extra", {}).get("image_generate", True):
        print(f"[codex-eyecatch] {args.blog} は画像生成・アイキャッチ自動設定を無効化しているためスキップしました")
        return 0

    _ctx_params = inspect.signature(wp_context.set_context).parameters
    _ctx_kwargs: dict = dict(
        wp_post_status=cfg.wp_post_status,
        candidate_ss_id=cfg.candidate_ss_id,
        candidate_sheet=cfg.candidate_sheet,
        image_style=getattr(cfg, "image_style", {}),
        blog_meta={
            "site_purpose": getattr(cfg, "site_purpose", ""),
            "target": getattr(cfg, "target", ""),
            "writing_taste": getattr(cfg, "writing_taste", ""),
            "genre_detail": getattr(cfg, "genre_detail", "") or getattr(cfg, "genre", ""),
            "search_intent": getattr(cfg, "search_intent", ""),
        },
        asp_ss_id=getattr(cfg, "asp_ss_id", ""),
    )
    if "eyecatch_model" in _ctx_params:
        _ctx_kwargs["eyecatch_model"] = getattr(cfg, "eyecatch_model", "") or "gpt-image-2"
    if "article_image_model" in _ctx_params:
        _ctx_kwargs["article_image_model"] = getattr(cfg, "article_image_model", "")
    wp_context.set_context(cfg.wp_url, cfg.wp_username, cfg.wp_app_password, **_ctx_kwargs)

    auth = HTTPBasicAuth(cfg.wp_username, cfg.wp_app_password)
    posts = _fetch_target_posts(
        cfg.wp_url,
        auth,
        post_id=args.post_id,
        limit=args.limit,
        overwrite=args.overwrite,
        status=cfg.wp_post_status or "draft",
    )

    if not posts:
        print(f"[codex-eyecatch] 対象の投稿がありません status={cfg.wp_post_status or 'draft'}")
        return 0

    print(f"[codex-eyecatch] 対象: {len(posts)}件")
    for post in posts:
        post_id = int(post["id"])
        title = _plain_title(post.get("title", {}).get("rendered", ""))
        slug = _safe_slug(post.get("slug", ""), f"post-{post_id}")
        print(f"\n[codex-eyecatch] #{post_id} {title}")

        if args.dry_run:
            continue

        if args.blog in _LIBRARY_EYECATCH_BLOGS:
            media = _select_library_media(cfg.wp_url, auth, title)
            if not media:
                print("[codex-eyecatch] 既存ライブラリ画像が見つからないためスキップ")
                continue

            media_id = int(media["id"])
            source_url = media.get("source_url", "")
            _set_featured_media(cfg.wp_url, auth, post_id, media_id, source_url, title)
            edit_url = f"{cfg.wp_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
            print(f"[codex-eyecatch] 既存ライブラリ画像を featured image に設定: media_id={media_id}")
            print(f"[codex-eyecatch] 編集URL: {edit_url}")
            continue

        from modules.image_generator import generate_lifestyle_eyecatch_image
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
