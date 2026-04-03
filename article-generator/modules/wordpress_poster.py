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
# CTA挿入
# ─────────────────────────────────────────────

_CTA_PLAUD = """\
<!-- wp:group {"metadata":{"categories":["call-to-action"],"patternName":"core/block/7009","name":"【テンプレート】マイクロコピーmc"},"className":"has-border -border02 is-style-bg_stripe","layout":{"type":"constrained"}} -->
<div class="wp-block-group has-border -border02 is-style-bg_stripe"><!-- wp:paragraph {"className":"has-text-align-center u-mb-0 u-mb-ctrl"} -->
<p class="has-text-align-center u-mb-0 u-mb-ctrl"><span class="swl-inline-color has-swl-main-color"><strong><span style="font-size:16px" class="swl-fz"><strong><strong>＼ 必要だと感じたら今すぐ確認がお得 ／ </strong></strong></span></strong></span></p>
<!-- /wp:paragraph -->
<!-- wp:loos/button {"hrefUrl":"/plaud","isNewTab":true,"className":"is-style-btn_shiny"} -->
<div class="swell-block-button is-style-btn_shiny"><a href="/plaud" target="_blank" rel="noopener noreferrer" class="swell-block-button__link"><span>＞＞ PLAUD NOTE公式サイトをチェックしてみる</span></a></div>
<!-- /wp:loos/button --></div>
<!-- /wp:group -->"""

_CTA_NOTTA = """\
<!-- wp:group {"className":"is-style-bg_stripe has-border -border02","layout":{"type":"constrained"}} -->
<div class="wp-block-group is-style-bg_stripe has-border -border02"><!-- wp:paragraph {"className":"has-text-align-center u-mb-0 u-mb-ctrl"} -->
<p class="has-text-align-center u-mb-0 u-mb-ctrl"><span class="swl-inline-color has-swl-main-color"><strong><span style="font-size:17px" class="swl-fz">＼ </span>今なら無料トライアル＆自動参加ボットがすぐ使える！<span style="font-size:17px" class="swl-fz">／</span></strong><br></span><span class="swl-fz u-fz-s">🎉 会議のムダをゼロに！AI議事録で生産性アップ 🎉</span></p>
<!-- /wp:paragraph -->
<!-- wp:loos/button {"hrefUrl":"/notta","isNewTab":true,"iconName":"LsChevronRight","color":"red","fontSize":"1.1em","btnSize":"l","className":"is-style-btn_shiny u-mb-ctrl u-mb-10"} -->
<div class="swell-block-button red_ -size-l is-style-btn_shiny u-mb-ctrl u-mb-10" style="--the-fz:1.1em"><a href="/notta" target="_blank" rel="noopener noreferrer" class="swell-block-button__link" data-has-icon="1"><svg class="__icon" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" viewBox="0 0 48 48"><path d="m33 25.1-13.1 13c-.8.8-2 .8-2.8 0-.8-.8-.8-2 0-2.8L28.4 24 17.1 12.7c-.8-.8-.8-2 0-2.8.8-.8 2-.8 2.8 0l13.1 13c.6.6.6 1.6 0 2.2z"></path></svg><span><strong>Notta（ノッタ）公式サイトをみる</strong></span></a></div>
<!-- /wp:loos/button -->
<!-- wp:paragraph {"align":"center"} -->
<p class="has-text-align-center"><span style="font-size:18px" class="swl-fz"><strong><span class="swl-bg-color has-swl-pale-04-background-color"><span class="swl-inline-color has-swl-deep-03-color">🎁 <strong>初回利用者限定：チーム全員で使える無料トライアル実施中！</strong><br></span></span></strong></span><span class="swl-bg-color has-swl-pale-04-background-color"><span class="swl-inline-color has-swl-main-color"><span class="swl-fz u-fz-s">AI要約・話者分離・自動参加のフル機能を今すぐ体験できま</span>す🏃‍♀️</span></span></p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->"""

_PLAUD_KEYWORDS = ("ボイスレコーダー", "録音", "icレコーダー", "ＩＣレコーダー", "plaud", "プラウド")
_NOTTA_KEYWORDS = ("文字起こし", "議事録", "ボイスメモ", "要約", "会議", "notta", "ノッタ")


def _select_cta(keyword: str) -> str | None:
    """キーワードから挿入すべき CTA ブロックを返す。該当なしは None。"""
    kw = keyword.lower()
    is_plaud = any(k in kw for k in _PLAUD_KEYWORDS)
    is_notta = any(k in kw for k in _NOTTA_KEYWORDS)
    if is_plaud or (is_plaud and is_notta):
        return _CTA_PLAUD
    if is_notta:
        return _CTA_NOTTA
    return None


def _inject_cta(content: str, keyword: str) -> str:
    """まとめ H3 ブロックの直前に CTA を 1 回だけ挿入する。"""
    cta = _select_cta(keyword)
    if not cta:
        return content

    pattern = re.compile(
        r'(<!-- wp:heading \{"level":3\} -->\s*<h3[^>]*>[^<]*まとめ[^<]*</h3>\s*<!-- /wp:heading -->)',
        re.DOTALL,
    )
    m = pattern.search(content)
    if not m:
        print(f"[wordpress] CTA挿入: まとめH3が見つからないためスキップ")
        return content

    insert_pos = m.start()
    cta_label = "PLAUD" if cta is _CTA_PLAUD else "Notta"
    print(f"[wordpress] CTA挿入: {cta_label}用CTAをまとめH3直前に挿入")
    return content[:insert_pos] + cta + "\n\n" + content[insert_pos:]


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
            "ssp_meta_ogimage_url":  article.get("eyecatch_url", ""),
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
        media_id, eyecatch_url = upload_media(image_bytes, f"{slug or 'featured'}.jpg")
        featured_media_id = media_id
        if eyecatch_url:
            article["eyecatch_url"] = eyecatch_url

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

    # ③-2 CTA挿入（まとめH3直前）
    keyword = article.get("keyword", article["title"])
    article["content"] = _inject_cta(article["content"], keyword)

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
