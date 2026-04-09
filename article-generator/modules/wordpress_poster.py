"""
Step 6: WordPress REST APIで下書き投稿
"""
import random
import re
import requests
from requests.auth import HTTPBasicAuth
from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, WP_CATEGORY_ID, WP_STATUS, CTA_CONFIG
from modules.keyword_utils import detect_parent_keyword
from modules.category_selector import select_category
from modules.sheets_updater import mark_posted


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)


# ─────────────────────────────────────────────
# CTA挿入
# CTA設定は config.py の CTA_CONFIG で一元管理。
# 新しい案件の追加は config.py のみ編集すればよい。
# ─────────────────────────────────────────────

# メディアライブラリ検索・カテゴリ判定用（CTA設定とは独立して管理）
_PLAUD_KEYWORDS = ("ボイスレコーダー", "録音", "icレコーダー", "ＩＣレコーダー", "plaud", "プラウド")
_NOTTA_KEYWORDS = ("文字起こし", "議事録", "ボイスメモ", "要約", "会議", "notta", "ノッタ")


def _select_cta_entry(keyword: str) -> dict | None:
    """
    CTA_CONFIG からキーワードにマッチする最初のエントリを返す。
    マッチしない場合は None。
    """
    kw = keyword.lower()
    for entry in CTA_CONFIG:
        if any(k in kw for k in entry.get("keywords", [])):
            return entry
    return None


def _inject_cta(content: str, keyword: str) -> str:
    """
    CTA_CONFIG の設定に基づき、記事コンテンツに CTA ブロックを挿入する。

    挿入位置（config.py の positions リストで指定）:
      "top"    → 「この記事のポイント」cap-block の直後
      "middle" → H2[2] と H2[3] の間（2番目のH2ブロック直後）
      "bottom" → 「まとめ」H3 の直前

    全挿入点を先に収集してから後ろ→前の順で挿入し、オフセットずれを防ぐ。
    """
    entry = _select_cta_entry(keyword)
    if not entry:
        return content

    cta   = entry["block"]
    name  = entry.get("name", "")
    positions = entry.get("positions", ["top", "bottom"])

    # ── 挿入点を収集（元コンテンツに対して検索）──
    # (offset, insert_before: bool, label)
    #   insert_before=True  → content[:offset] + cta + "\n\n" + content[offset:]
    #   insert_before=False → content[:offset] + "\n\n" + cta + content[offset:]
    insertion_points: list[tuple[int, bool, str]] = []

    if "bottom" in positions:
        matome_pat = re.compile(
            r'<!-- wp:heading \{"level":3\} -->\s*<h3[^>]*>[^<]*まとめ[^<]*</h3>\s*<!-- /wp:heading -->',
            re.DOTALL,
        )
        m = matome_pat.search(content)
        if m:
            insertion_points.append((m.start(), True, "bottom"))
        else:
            print(f"[wordpress] CTA[bottom] スキップ: まとめH3が見つからない ({name})")

    if "middle" in positions:
        h2_matches = _extract_h2_blocks(content)
        if len(h2_matches) >= 3:
            insertion_points.append((h2_matches[1].end(), False, "middle"))
        else:
            print(f"[wordpress] CTA[middle] スキップ: H2が{len(h2_matches)}個（3個必要）({name})")

    if "top" in positions:
        capblock_m = re.search(r'<!-- /wp:loos/cap-block -->', content)
        if capblock_m:
            insertion_points.append((capblock_m.end(), False, "top"))
        else:
            print(f"[wordpress] CTA[top] スキップ: cap-blockが見つからない ({name})")

    if not insertion_points:
        return content

    # ── オフセット降順（後ろ→前）で挿入 ──
    insertion_points.sort(key=lambda x: x[0], reverse=True)
    for offset, insert_before, label in insertion_points:
        if insert_before:
            content = content[:offset] + cta + "\n\n" + content[offset:]
        else:
            content = content[:offset] + "\n\n" + cta + content[offset:]
        print(f"[wordpress] CTA挿入[{label}]: {name}")

    return content


# ─────────────────────────────────────────────
# メディアアップロード
# ─────────────────────────────────────────────

def upload_media(
    image_bytes: bytes,
    filename: str,
    mime_type: str = "image/jpeg",
    alt_text: str = "",
    title: str = "",
    caption: str = "",
) -> tuple[int, str]:
    """
    WordPress メディアライブラリに画像をアップロードする。
    alt_text / title / caption を指定すると PATCH で自動設定する。

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
    media_id = data["id"]

    if alt_text or title or caption:
        patch: dict = {}
        if alt_text:
            patch["alt_text"] = alt_text
        if title:
            patch["title"] = title
        if caption:
            patch["caption"] = caption
        requests.post(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            auth=_auth(),
            json=patch,
            timeout=10,
        )

    print(f"[wordpress] メディアアップロード完了 (ID: {media_id})")
    return media_id, data.get("source_url", "")


def _get_eyecatch_caption_tags(keyword: str) -> str:
    """
    キーワードから親グループ名を動的に検出し、
    WPキャプションに書き込む「#タグ」文字列を返す。

    detect_parent_keyword() で検出した親グループ名をそのままタグとして使用する。
    例: "文字起こしツール 比較" → "#文字起こしツール"
        "photodirector 使い方" → "#photodirector"
        "aiボイスレコーダー アプリ" → "#aiボイスレコーダー"
    """
    parent = detect_parent_keyword(keyword)
    return f"#{parent}"


def _get_category_search_terms(keyword: str) -> list[str]:
    """キーワードからメディアライブラリ検索用キャプションタグを返す。"""
    kw = keyword.lower()
    terms: list[str] = []
    if any(k in kw for k in _PLAUD_KEYWORDS):
        terms += ["PLAUD", "ボイスレコーダー", "録音"]
    if any(k in kw for k in _NOTTA_KEYWORDS):
        terms += ["Notta", "文字起こし", "議事録"]
    if not terms:
        terms.append(keyword.split()[0] if keyword else "AI")
    return terms


def _fetch_media_by_tag(search_term: str) -> list[dict]:
    """キャプション中の #タグ でメディアライブラリを検索しランダム1件を返す。"""
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/media",
            auth=_auth(),
            params={
                "media_type": "image",
                "search": f"#{search_term}",
                "per_page": 50,
                "_fields": "id,source_url,alt_text,caption",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        return resp.json()
    except Exception:
        return []


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


def _extract_h3_titles(content: str) -> list[str]:
    """コンテンツ内の全 H3 見出しテキストをリストで返す。"""
    titles = []
    for m in re.finditer(r'<h3[^>]*>(.*?)</h3>', content, re.DOTALL):
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if text:
            titles.append(text)
    return titles


def _estimate_char_count(content: str) -> int:
    """HTML タグを除いたテキストの文字数を返す（目安）。"""
    text = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    return len(text.replace('\n', '').replace(' ', ''))


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
    スラッグ重複(term_exists)の場合は既存IDを使用する。
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
            if r.status_code == 400:
                # term_exists: スラッグ重複 → レスポンスの term_id を使用
                body = r.json()
                term_id = body.get("data", {}).get("term_id")
                if term_id:
                    tag_ids.append(int(term_id))
                    print(f"[wordpress] タグ既存(term_exists)使用: {name} (id={term_id})")
                else:
                    print(f"[wordpress] タグ作成スキップ(400): {name}")
            else:
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

def post_article_with_image(
    article: dict,
    image_bytes: bytes | None = None,
    asp_links: dict | None = None,
) -> dict:
    """
    ① カテゴリ自動選択
    ② アイキャッチ画像アップロード（FLUX生成・{slug}-eyecatch.jpg）
    ③ H2記事内画像: 1枚目FLUX / 2枚目以降メディアライブラリ優先（なければFLUX）
    ④ CTA挿入（まとめH3直前）
    ⑤ WordPress に下書き投稿
    ⑥ スプレッドシートに投稿済みフラグを書き込む
    """
    from modules.image_generator import generate_h2_image  # 循環import回避

    keyword = article.get("keyword", article["title"])
    slug = re.sub(r"[^a-z0-9\-]", "", article.get("slug", "article").lower()) or "article"

    # ① カテゴリ
    if not article.get("category_id"):
        article["category_id"] = select_category(
            keyword=keyword,
            article_title=article["title"],
        )

    # ② アイキャッチ（渡された image_bytes 優先 → なければライブラリ検索）
    featured_media_id = None
    search_terms = _get_category_search_terms(keyword)

    if image_bytes:
        eyecatch_alt = f"{keyword}のイメージ画像"
        eyecatch_caption = _get_eyecatch_caption_tags(keyword)
        media_id, eyecatch_url = upload_media(
            image_bytes,
            f"{slug}-eyecatch.jpg",
            alt_text=eyecatch_alt,
            title=eyecatch_alt,
            caption=eyecatch_caption,
        )
        print(f"[wordpress] アイキャッチ キャプションタグ付与: {eyecatch_caption}")
        featured_media_id = media_id
        if eyecatch_url:
            article["eyecatch_url"] = eyecatch_url
    else:
        # ライブラリからアイキャッチを選択
        for term in search_terms:
            candidates = _fetch_media_by_tag(term)
            if candidates:
                chosen = random.choice(candidates)
                src_url = chosen.get("source_url", "")
                media_id_str = chosen.get("id")
                if src_url and media_id_str:
                    featured_media_id = int(media_id_str)
                    article["eyecatch_url"] = src_url
                    print(f"[wordpress] アイキャッチ ライブラリ選択 (#{term}): {src_url.split('/')[-1]}")
                    break
        if not featured_media_id:
            print("[wordpress] アイキャッチ: ライブラリ該当なし・スキップ")

    # ③ H2記事内画像（全枚: ライブラリ優先 → FLUXフォールバック）
    h2_matches = _extract_h2_blocks(article.get("content", ""))
    if h2_matches:
        print(f"[wordpress] H2画像処理: {len(h2_matches)}枚")
        h2_image_data: list[tuple[str, str]] = []

        for i, match in enumerate(h2_matches, 1):
            h2_title = _extract_h2_title(match.group(0))
            img_alt = f"{h2_title}のイメージ画像" if h2_title else f"{keyword}のイメージ画像"
            filename = f"{slug}-{i:02d}.jpg"
            src_url = ""
            chosen_id = None

            # ライブラリから検索（全枚共通）
            for term in search_terms:
                candidates = _fetch_media_by_tag(term)
                if candidates:
                    chosen = random.choice(candidates)
                    src_url = chosen.get("source_url", "")
                    if src_url:
                        chosen_id = chosen.get("id")
                        print(f"[wordpress] H2画像[{i}] ライブラリ選択 (#{term}): {src_url.split('/')[-1]}")
                        break

            # ライブラリ画像のALTを使用するたびに上書き（同一画像が複数記事で使われるため）
            if chosen_id:
                try:
                    requests.post(
                        f"{WP_URL}/wp-json/wp/v2/media/{chosen_id}",
                        auth=_auth(),
                        json={"alt_text": img_alt},
                        timeout=10,
                    )
                    print(f"[wordpress] H2画像[{i}] ライブラリALT更新: {img_alt}")
                except Exception as alt_err:
                    print(f"[wordpress] H2画像[{i}] ALT更新失敗（続行）: {alt_err}")

            # ライブラリになければFLUXフォールバック
            if not src_url:
                try:
                    img_bytes = generate_h2_image(h2_title, keyword)
                    _, src_url = upload_media(img_bytes, filename, alt_text=img_alt, title=img_alt)
                    print(f"[wordpress] H2画像[{i}] FLUX生成（ライブラリ該当なし）: {h2_title[:30]}")
                except Exception as e:
                    print(f"[wordpress] H2画像[{i}] スキップ（続行）: {e}")

            if src_url:
                h2_image_data.append((img_alt, src_url))

        if h2_image_data:
            article["content"] = _inject_h2_images(article["content"], h2_image_data)
            print(f"[wordpress] H2画像 {len(h2_image_data)}枚 をコンテンツに挿入しました")

    # ④ 内部リンク挿入（H3セクション末尾に分散）
    try:
        from modules.internal_linker import (
            get_published_articles, select_related_articles, inject_internal_links
        )
        published = get_published_articles()
        if published:
            related = select_related_articles(
                keyword=keyword,
                article_title=article.get("title", ""),
                published_articles=published,
                asp_links=asp_links or {},
                article_content=article.get("content", ""),
            )
            if related:
                article["content"] = inject_internal_links(
                    article["content"], related,
                    keyword=keyword,
                    article_title=article.get("title", ""),
                )
                titles = [a["title"][:30] for a in related]
                print(f"[internal_linker] 内部リンク {len(related)}件 挿入: {titles}")
            else:
                print("[internal_linker] 関連記事なし・内部リンクなし")
    except Exception as _il_err:
        print(f"[internal_linker] スキップ（続行）: {_il_err}")

    # ⑤ CTA挿入（まとめH3直前）
    article["content"] = _inject_cta(article["content"], keyword)

    # ⑥ 投稿
    result = create_post(article, featured_media_id=featured_media_id)

    # ⑦ スプレッドシート書き込み
    if keyword:
        sub_kws = _extract_h3_titles(article.get("content", ""))
        char_count = _estimate_char_count(article.get("content", ""))
        mark_posted(
            keyword=keyword,
            post_id=result["id"],
            post_url=result.get("url", ""),
            sub_keywords=sub_kws,
            article_title=article.get("title", ""),
            related_keywords=article.get("related_keywords", []),
            category_name=article.get("category_name", ""),
            tags=article.get("tags", []),
            char_count=char_count,
            eyecatch_url=article.get("eyecatch_url", ""),
        )


    return result
