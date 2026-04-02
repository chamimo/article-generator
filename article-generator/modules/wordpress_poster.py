"""
Step 6: WordPress REST APIで下書き投稿
"""
import re
import requests
from requests.auth import HTTPBasicAuth
from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, WP_CATEGORY_ID, WP_STATUS
from modules.category_selector import select_category
from modules.sheets_updater import mark_posted


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)


def upload_media(image_bytes: bytes, filename: str, mime_type: str = "image/jpeg") -> tuple[int, str]:
    """
    WordPress メディアライブラリに画像をアップロードする。

    Returns:
        (media_id, source_url)
    """
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/media",
        auth=_auth(),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime_type,
        },
        data=image_bytes,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"[wordpress] メディアアップロード完了 (ID: {data['id']})")
    return data["id"], data.get("source_url", "")


def get_or_create_tags(tag_names: list[str]) -> list[int]:
    """
    タグ名のリストからWP tag IDを返す。存在しないタグは新規作成する。
    """
    tag_ids: list[int] = []
    for name in tag_names[:5]:  # 念のため上限を守る
        name = name.strip()
        if not name:
            continue
        # 既存タグ検索
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/tags",
            auth=_auth(),
            params={"search": name, "per_page": 5, "_fields": "id,name"},
            timeout=10,
        )
        resp.raise_for_status()
        matches = [t for t in resp.json() if t["name"] == name]
        if matches:
            tag_ids.append(matches[0]["id"])
        else:
            # 新規作成
            r = requests.post(
                f"{WP_URL}/wp-json/wp/v2/tags",
                auth=_auth(),
                json={"name": name},
                timeout=10,
            )
            r.raise_for_status()
            tag_ids.append(r.json()["id"])
    return tag_ids


def create_post(article: dict, featured_media_id: int | None = None) -> dict:
    """
    WordPress REST APIで投稿を作成する。

    Returns:
        {"id": int, "url": str, "edit_url": str}
    """
    category_id = article.get("category_id") or WP_CATEGORY_ID

    # タグIDを取得（article に tags リストがある場合）
    tag_ids: list[int] = []
    if article.get("tags"):
        print(f"[wordpress] タグ設定: {article['tags']}")
        tag_ids = get_or_create_tags(article["tags"])

    payload: dict = {
        "title": article["title"],
        "content": article["content"],
        "status": WP_STATUS,
        "slug": article.get("slug", ""),
        "categories": [category_id],
        "meta": {
            # SEO SIMPLE PACK（正式キー名: ssp_meta_title / ssp_meta_description）
            "ssp_meta_title": article.get("title", ""),
            "ssp_meta_description": article.get("meta_description", ""),
            # Yoast SEO / RankMath（共存させておく）
            "_yoast_wpseo_metadesc": article.get("meta_description", ""),
            "rank_math_description": article.get("meta_description", ""),
        },
    }
    if tag_ids:
        payload["tags"] = tag_ids
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        auth=_auth(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()

    post = resp.json()
    post_id = post["id"]
    edit_url = f"{WP_URL}/wp-admin/post.php?post={post_id}&action=edit"
    print(f"[wordpress] 投稿完了 (ID: {post_id}) → {edit_url}")
    return {"id": post_id, "url": post.get("link", ""), "edit_url": edit_url}


def post_article_with_image(article: dict, image_bytes: bytes | None = None) -> dict:
    """
    ① カテゴリ自動選択（article_generator が設定済みならスキップ）
    ② アイキャッチ画像アップロード（image_bytes が None なら省略）
    ③ WordPress に下書き投稿
    """
    # ① カテゴリ
    if not article.get("category_id"):
        article["category_id"] = select_category(
            keyword=article.get("keyword", article["title"]),
            article_title=article["title"],
        )

    # ② アイキャッチ画像
    featured_media_id = None
    if image_bytes:
        slug = re.sub(r"[^a-z0-9\-]", "", article.get("slug", "article").lower())
        media_id, _ = upload_media(image_bytes, f"{slug or 'featured'}.jpg")
        featured_media_id = media_id

    # ③ 投稿
    result = create_post(article, featured_media_id=featured_media_id)

    # ④ スプレッドシートに投稿済みフラグを書き込む
    keyword = article.get("keyword", "")
    if keyword:
        mark_posted(
            keyword=keyword,
            post_id=result["id"],
            post_url=result.get("url", ""),
        )

    return result
