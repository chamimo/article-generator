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


# ─────────────────────────────────────────────
# メディアアップロード
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# H2記事内画像ヘルパー
# ─────────────────────────────────────────────

def _extract_h2_blocks(content: str) -> list[re.Match]:
    """
    コンテンツ内の H2 ブロック全体にマッチするリストを返す。
    H3 は <!-- wp:heading {"level":3} --> なので区別できる。
    """
    pattern = re.compile(
        r'<!-- wp:heading -->\s*<h2[^>]*>.*?</h2>\s*<!-- /wp:heading -->',
        re.DOTALL,
    )
    return list(pattern.finditer(content))


def _extract_h2_title(block_text: str) -> str:
    """H2ブロックのテキストからタイトル文字列を取り出す。"""
    m = re.search(r'<h2[^>]*>(.*?)</h2>', block_text, re.DOTALL)
    if not m:
        return ""
    return re.sub(r'<[^>]+>', '', m.group(1)).strip()


def _build_wp_image_block(src_url: str, alt: str) -> str:
    """wp:image ブロック文字列を生成する。"""
    return (
        '\n\n<!-- wp:image {"sizeSlug":"medium","align":"center"} -->\n'
        f'<figure class="wp-block-image size-medium aligncenter">\n'
        f'<img src="{src_url}" alt="{alt}"/>\n'
        '</figure>\n'
        '<!-- /wp:image -->'
    )


def _inject_h2_images(content: str, h2_image_data: list[tuple[str, str]]) -> str:
    """
    コンテンツ内の各 H2 ブロック直後に wp:image ブロックを挿入する。

    Args:
        content       : 元のコンテンツ文字列
        h2_image_data : [(alt_text, src_url), ...] ※ H2 の順番と対応
    """
    matches = _extract_h2_blocks(content)
    if not matches or not h2_image_data:
        return content

    # 後ろから挿入（前から挿入するとオフセットがずれる）
    for i, match in enumerate(reversed(matches)):
        idx = len(matches) - 1 - i
        if idx >= len(h2_image_data):
            continue
        alt, src_url = h2_image_data[idx]
        image_block = _build_wp_image_block(src_url, alt)
        insert_pos = match.end()
        content = content[:insert_pos] + image_block + content[insert_pos:]

    return content


# ─────────────────────────────────────────────
# タグ
# ─────────────────────────────────────────────

def get_or_create_tags(tag_names: list[str]) -> list[int]:
    """
    タグ名のリストからWP tag IDを返す。存在しないタグは新規作成する。
    """
    tag_ids: list[int] = []
    for name in tag_names[:5]:
        name = name.strip()
        if not name:
            continue
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
            r = requests.post(
                f"{WP_URL}/wp-json/wp/v2/tags",
                auth=_auth(),
                json={"name": name},
                timeout=10,
            )
            r.raise_for_status()
            tag_ids.append(r.json()["id"])
    return tag_ids


# ─────────────────────────────────────────────
# 投稿作成
# ─────────────────────────────────────────────

def create_post(article: dict, featured_media_id: int | None = None) -> dict:
    """
    WordPress REST APIで投稿を作成する。

    Returns:
        {"id": int, "url": str, "edit_url": str}
    """
    category_id = article.get("category_id") or WP_CATEGORY_ID

    tag_ids: list[int] = []
    if article.get("tags"):
        print(f"[wordpress] タグ設定: {article['tags']}")
        tag_ids = get_or_create_tags(article["tags"])

    # imagefx_prompt を本文末尾にHTMLコメントとして挿入（下書き確認用）
    content = article["content"]
    imagefx_prompt = article.get("imagefx_prompt", "")
    if imagefx_prompt:
        content = content.rstrip() + f"\n\n<!-- imagefx_prompt\n{imagefx_prompt}\n-->"

    payload: dict = {
        "title": article["title"],
        "content": content,
        "status": WP_STATUS,
        "slug": article.get("slug", ""),
        "categories": [category_id],
        "meta": {
            "ssp_meta_title":        article.get("title", ""),
            "ssp_meta_description":  article.get("meta_description", ""),
            "_yoast_wpseo_metadesc": article.get("meta_description", ""),
            "rank_math_description": article.get("meta_description", ""),
            "imagefx_prompt":        article.get("imagefx_prompt", ""),
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

    # imagefx_prompt の保存確認（REST API で取得して表示）
    try:
        verify = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            auth=_auth(),
            params={"context": "edit", "_fields": "meta"},
            timeout=10,
        )
        saved_prompt = verify.json().get("meta", {}).get("imagefx_prompt", "")
        if saved_prompt:
            print("\n" + "─" * 60)
            print("【ImageFX プロンプト（保存確認）】")
            print("─" * 60)
            print(saved_prompt)
            print("─" * 60 + "\n")
        else:
            print("[wordpress] imagefx_prompt: 未登録（functions.phpへのスニペット追加が必要）")
    except Exception:
        pass

    return {"id": post_id, "url": post.get("link", ""), "edit_url": edit_url}


# ─────────────────────────────────────────────
# メインエントリ
# ─────────────────────────────────────────────

def post_article_with_image(article: dict, image_bytes: bytes | None = None) -> dict:
    """
    ① カテゴリ自動選択
    ② アイキャッチ画像アップロード（人物あり）
    ③ H2記事内画像を生成・アップロード・コンテンツに挿入
    ④ WordPress に下書き投稿
    ⑤ スプレッドシートに投稿済みフラグを書き込む
    """
    from modules.image_generator import generate_h2_image  # 循環import回避

    # ① カテゴリ
    if not article.get("category_id"):
        article["category_id"] = select_category(
            keyword=article.get("keyword", article["title"]),
            article_title=article["title"],
        )

    # ② アイキャッチ（人物あり）
    featured_media_id = None
    if image_bytes:
        slug = re.sub(r"[^a-z0-9\-]", "", article.get("slug", "article").lower())
        media_id, _ = upload_media(image_bytes, f"{slug or 'featured'}.jpg")
        featured_media_id = media_id

    # ③ H2記事内画像を生成・挿入
    h2_matches = _extract_h2_blocks(article.get("content", ""))
    if h2_matches:
        print(f"[wordpress] H2画像生成: {len(h2_matches)}枚")
        h2_image_data: list[tuple[str, str]] = []
        keyword = article.get("keyword", article["title"])
        for i, match in enumerate(h2_matches, 1):
            h2_title = _extract_h2_title(match.group(0))
            try:
                img_bytes = generate_h2_image(h2_title, keyword)
                slug_base = re.sub(r"[^a-z0-9\-]", "", article.get("slug", "article").lower())
                _, src_url = upload_media(img_bytes, f"{slug_base or 'article'}-h2-{i}.jpg")
                h2_image_data.append((h2_title, src_url))
                print(f"[wordpress] H2画像[{i}] アップロード完了: {h2_title[:30]}")
            except Exception as e:
                print(f"[wordpress] H2画像[{i}] スキップ（続行）: {e}")

        if h2_image_data:
            article["content"] = _inject_h2_images(article["content"], h2_image_data)
            print(f"[wordpress] H2画像 {len(h2_image_data)}枚 をコンテンツに挿入しました")

    # ④ 投稿
    result = create_post(article, featured_media_id=featured_media_id)

    # ⑤ スプレッドシート書き込み
    keyword = article.get("keyword", "")
    if keyword:
        mark_posted(
            keyword=keyword,
            post_id=result["id"],
            post_url=result.get("url", ""),
        )

    return result
