"""
generate_novel.py
飛騨の思い出ブログの「小説」シートから記事を生成してWordPressに投稿する。

使い方:
  python3 generate_novel.py
  python3 generate_novel.py --dry-run   # WP投稿せず内容を確認
"""
from __future__ import annotations
import argparse
import io
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

import anthropic
import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_CREDENTIALS_PATH, HUGGINGFACE_API_KEY

SS_ID    = "16DZ0M_EbviPRhZBNwV_FpEJL2SjsuZw9BLKwAJE9AWE"
SHEET    = "小説"
WP_URL   = os.environ.get("HIDA_NO_OMOIDE_WP_URL", "https://hida-no-omoide.com")
WP_USER  = os.environ.get("HIDA_NO_OMOIDE_WP_USERNAME", "")
WP_PASS  = os.environ.get("HIDA_NO_OMOIDE_WP_APP_PASSWORD", "")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_HF_MODEL = "black-forest-labs/FLUX.1-schnell"
_IMG_W, _IMG_H = 1216, 832

# ── スラッグ生成 ──────────────────────────────────────────────
def _make_slug(title: str) -> str:
    """タイトルからURLスラッグを生成する（英数字・ハイフンのみ）。"""
    # ひらがな・カタカナ・漢字はローマ字変換の代わりにそのまま許容
    slug = unicodedata.normalize("NFKC", title.strip())
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-").lower()
    return slug or "novel"


# ── Claude で記事を整形 ──────────────────────────────────────
SYSTEM_PROMPT = """\
あなたは飛騨地域の文化・方言に詳しいWordPressライターです。
ユーザーから飛騨を舞台にした小説の原稿とタイトルを受け取り、
WordPress SWELL形式の記事HTMLを生成してください。

## 記事の構成（必ずこの順）
1. **冒頭文**（200〜300字）
   - 物語の世界観・舞台（飛騨の地・時代）を読者に紹介する
   - 読者が「読みたい」と思える導入
   - <!-- wp:paragraph --> ブロックで出力
2. **本文（H2分け）**
   - 原稿を場面・転換点で3〜5つのH2セクションに分ける
   - H2見出し例：「第一章　飢饉の年」「第二章　柿を分ける娘」など、物語の流れに合わせる
   - 各H2内の本文は段落ごとに <!-- wp:paragraph --> ブロックで出力
   - 原稿の文章はそのまま（改変せず）使う。改行・段落分けのみ整える
   - 会話文は前後を適切に段落分けする
3. **飛騨弁の解説**（H2見出し：「飛騨弁・方言の解説」）
   - 本文中に登場する飛騨弁・方言を抽出し、意味を解説する
   - <!-- wp:table --> を使った2列テーブル（飛騨弁 | 標準語・意味）で出力
   - 8〜15語程度を目安に抽出する
4. **まとめ**（H2見出し：「まとめ」、150〜200字）
   - 物語のテーマ・余韻を一言でまとめる
   - 読者へのやさしいメッセージで締める
   - <!-- wp:paragraph --> ブロックで出力

## 出力ルール
- WordPress SWELL形式のHTMLブロックのみ出力する
- 独自style・class追加は禁止（下記のSWELL標準クラスは使用可）
- H2: <!-- wp:heading {"level":2} --><h2 class="wp-block-heading">〇〇</h2><!-- /wp:heading -->
- 段落: <!-- wp:paragraph --><p>〇〇</p><!-- /wp:paragraph -->
- テーブル: <!-- wp:table --><figure class="wp-block-table"><table><tbody><tr><td>飛騨弁</td><td>意味・標準語</td></tr>...</tbody></table></figure><!-- /wp:table -->
- 「参考WEB①」「参考URL」などの表現は絶対に使わない

## リストブロックのSWELL装飾ルール（必須）
本文中で番号付き列挙や箇条書きが必要な場合は、必ず以下のSWELL装飾クラスを使うこと。

**番号付きリスト（四角装飾）:**
<!-- wp:list {"ordered":true,"className":"is-style-num_square"} -->
<ol class="wp-block-list is-style-num_square">
<li>〇〇</li>
<li>〇〇</li>
</ol>
<!-- /wp:list -->

**箇条書きリスト（四角装飾）:**
<!-- wp:list {"className":"is-style-square"} -->
<ul class="wp-block-list is-style-square">
<li>〇〇</li>
<li>〇〇</li>
</ul>
<!-- /wp:list -->

- 飛騨弁解説テーブル直前の「読み方のポイント」など列挙が必要な箇所にも積極的に使う
- 本文段落内に「①②③」などの番号を文字で書かずに、必ずリストブロックで出力する

## 最終出力形式（JSONのみ・前後の説明文不要）
{
  "title": "記事H1タイトル（小説タイトルをそのまま使用）",
  "seo_title": "SEOタイトル（28〜32字・飛騨 小説 などを含む）",
  "meta_description": "メタディスクリプション（80〜120字）",
  "slug": "url-slug",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
  "content": "WordPress SWELL形式の完全なHTML"
}
"""


def generate_novel_article(title: str, body: str) -> dict:
    """小説原稿からWordPress記事データを生成する。"""
    print(f"[novel] 記事生成中: 「{title}」（{len(body):,}字）")
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"タイトル: {title}\n\n"
                f"小説原稿:\n{body}"
            ),
        }],
    )
    raw = msg.content[0].text.strip()
    # JSON抽出（出力が途中で切れた場合も対処）
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError(f"JSONが見つかりません: {raw[:200]}")
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSONパースエラー（出力が途中で切れた可能性）: {e}\n"
            f"stop_reason={msg.stop_reason}, 出力末尾200字: ...{raw[-200:]}"
        )


# ── 記事内画像生成・挿入 ─────────────────────────────────────

# 飛騨高山固有の要素を明示し、富士山など他地域の要素を排除する共通ベース
_HIDA_IMAGE_BASE = (
    "Hida Takayama scenery, Gifu prefecture Japan, "
    "traditional gassho-zukuri thatched-roof farmhouse, cedar and hinoki forest, "
    "Miyagawa river, Sanmachi Suji old merchant street with wooden sake breweries, "
    "Hida Folk Village, Norikura highland plateau, Northern Alps Hotaka peaks, "
    "NO Mount Fuji, NO ocean, NO tropical plants, no text, no watermark"
)

# スタイルバリエーション（写実調と水彩イラスト調をランダムで切り替え）
_HIDA_STYLES = [
    "Japanese watercolor illustration style, soft ink wash, delicate brushwork, muted earthy tones, artistic",
    "traditional Japanese landscape painting style, ukiyo-e inspired, serene atmosphere, artistic illustration",
    "soft watercolor landscape, gentle pastel tones, tranquil Japanese countryside illustration",
    "photorealistic landscape photography, natural light, cinematic, detailed texture",
]

import random as _random

# H2タイトルのキーワードからシーン説明を補足するマッピング（飛騨固有の要素に絞る）
_SCENE_HINTS: list[tuple[list[str], str]] = [
    (["冬", "雪", "寒", "氷"],
     "deep snow covering gassho-zukuri rooftops of Shirakawa-go, frozen Miyagawa river, "
     "snow-laden cedar branches, quiet white winter morning in Hida mountains"),
    (["春", "桜", "花", "梅"],
     "cherry blossoms along Miyagawa river bank, Takayama morning market in spring, "
     "pink petals falling on old wooden merchant buildings"),
    (["夏", "川", "緑", "新緑"],
     "lush green cedar and hinoki forest in Hida highlands, clear cold mountain stream, "
     "summer sunlight filtering through forest canopy"),
    (["秋", "紅葉", "祭", "収穫"],
     "vivid autumn maple and ginkgo foliage along Sanmachi Suji, "
     "Takayama autumn festival floats, red and gold mountain slopes of Hida"),
    (["山", "峠", "険し", "登"],
     "rugged mountain pass in Northern Alps, Norikura plateau high alpine scenery, "
     "misty Hotaka peaks above Hida valley, steep cedar forest trail"),
    (["里", "村", "農", "田", "畑"],
     "traditional gassho-zukuri farmhouse surrounded by rice paddies in mountain valley, "
     "Hida Folk Village rustic landscape, smoke rising from farmhouse hearth"),
    (["市", "町", "宿", "旅籠", "商"],
     "Sanmachi Suji historic wooden merchant street, sake brewery lattice walls, "
     "stone-paved alley in old Takayama town, traditional inn facade"),
    (["川", "水", "橋", "渡"],
     "Miyagawa river with clear emerald water, old stone bridge in Hida, "
     "river flowing through cedar forest, mountain stream reflection"),
    (["夜", "月", "星", "暗"],
     "lantern-lit Sanmachi Suji street at night, starry sky over Hida mountains, "
     "moonlight reflecting on Miyagawa river surface"),
    (["朝", "夜明け", "霧", "朝霧"],
     "morning mist rising from Hida river valley, dawn light over Northern Alps, "
     "Miyagawa morning market in early mist, misty cedar forest at sunrise"),
    (["祭", "神社", "屋台"],
     "Takayama Sanno Festival elaborate yatai float decorated with intricate carvings, "
     "Hida shrine lanterns at dusk, festival procession on old town street"),
]


def _scene_hint_for_h2(h2_title: str) -> str:
    for keywords, hint in _SCENE_HINTS:
        if any(k in h2_title for k in keywords):
            return hint
    return (
        "Takayama old town Sanmachi Suji street, wooden sake brewery buildings, "
        "quiet Hida mountain valley scenery, traditional Japanese rural landscape"
    )


def _generate_novel_image(h2_title: str, idx: int) -> bytes:
    """H2タイトルに合わせた飛騨高山固有の風景画像をFLUXで生成する。"""
    from huggingface_hub import InferenceClient
    hint = _scene_hint_for_h2(h2_title)
    style = _random.choice(_HIDA_STYLES)
    prompt = f"{_HIDA_IMAGE_BASE}, {hint}, {style}"
    print(f"[novel-img] 画像{idx+1}生成: ...{hint[:60]}")
    hf = InferenceClient(token=HUGGINGFACE_API_KEY)
    result = hf.text_to_image(prompt, model=_HF_MODEL, width=_IMG_W, height=_IMG_H)
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _upload_image_to_wp(img_bytes: bytes, filename: str, alt: str) -> tuple[int, str]:
    """画像をWordPressメディアライブラリにアップロードしてIDとURLを返す。"""
    import requests
    from requests.auth import HTTPBasicAuth
    resp = requests.post(
        f"{WP_URL.rstrip('/')}/wp-json/wp/v2/media",
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg",
        },
        data=img_bytes,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    media_id = data["id"]
    src_url  = data.get("source_url", "")
    # altテキストを設定
    requests.post(
        f"{WP_URL.rstrip('/')}/wp-json/wp/v2/media/{media_id}",
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
        json={"alt_text": alt, "title": alt},
        timeout=10,
    )
    print(f"[novel-img] アップロード完了: ID={media_id} {src_url[:60]}")
    return media_id, src_url


def _wp_image_block(media_id: int, src_url: str, alt: str) -> str:
    """WordPressのwp:imageブロックHTMLを返す。"""
    return (
        f'<!-- wp:image {{"id":{media_id},"sizeSlug":"large","linkDestination":"none"}} -->'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{src_url}" alt="{alt}" class="wp-image-{media_id}"/>'
        f'</figure>'
        f'<!-- /wp:image -->\n'
    )


def _insert_images_into_content(content: str, images: list[tuple[int, str, str]]) -> str:
    """
    コンテンツのH2ブロック直後に画像を挿入する。
    images: [(media_id, src_url, alt), ...]  最大3件
    """
    H2_PATTERN = re.compile(
        r'(<!-- wp:heading[^>]*-->\s*<h2[^>]*>.*?</h2>\s*<!-- /wp:heading -->)',
        re.DOTALL,
    )
    parts = H2_PATTERN.split(content)
    # parts: [pre, h2_1, between_1, h2_2, between_2, ...]
    result = []
    h2_count = 0
    for part in parts:
        result.append(part)
        if H2_PATTERN.fullmatch(part) and h2_count < len(images):
            media_id, src_url, alt = images[h2_count]
            result.append(_wp_image_block(media_id, src_url, alt))
            h2_count += 1
    return "".join(result)


def generate_and_insert_images(article: dict, title: str) -> dict:
    """
    記事内H2の最初3箇所に画像を生成・アップロード・挿入する。
    アイキャッチは生成しない。
    """
    content = article.get("content", "")
    # H2ブロックは改行を挟んで書かれることが多いため DOTALL + 柔軟なパターン
    H2_PATTERN = re.compile(
        r'<!-- wp:heading[^>]*-->\s*<h2[^>]*>(.*?)</h2>\s*<!-- /wp:heading -->',
        re.DOTALL,
    )
    h2_matches = H2_PATTERN.findall(content)[:3]

    if not h2_matches:
        print("[novel-img] H2が見つかりません。画像挿入をスキップします。")
        return article

    images: list[tuple[int, str, str]] = []
    for idx, h2_text in enumerate(h2_matches):
        clean_title = re.sub(r'<[^>]+>', '', h2_text).strip()
        alt = f"{title}　{clean_title}"
        try:
            img_bytes = _generate_novel_image(clean_title, idx)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"novel_{ts}_{idx+1}.jpg"
            media_id, src_url = _upload_image_to_wp(img_bytes, filename, alt)
            images.append((media_id, src_url, alt))
        except Exception as e:
            print(f"[novel-img] 画像{idx+1}生成エラー（スキップ）: {e}")

    if images:
        article["content"] = _insert_images_into_content(content, images)
        print(f"[novel-img] {len(images)}枚の画像を記事に挿入しました。")

    return article


# ── WordPress投稿 ────────────────────────────────────────────
def post_to_wp(article: dict) -> dict:
    """WordPressに下書き投稿し、IDとURLを返す。"""
    import requests
    from requests.auth import HTTPBasicAuth

    endpoint = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    payload = {
        "title":   article["title"],
        "content": article["content"],
        "status":  "draft",
        "slug":    article.get("slug", ""),
        "meta": {
            "seo_simple_pack_title":       article.get("seo_title", ""),
            "seo_simple_pack_description": article.get("meta_description", ""),
        },
    }
    resp = requests.post(
        endpoint,
        json=payload,
        auth=HTTPBasicAuth(WP_USER, WP_PASS),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    post_id = data["id"]
    post_url = data.get("link", "")
    edit_url = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"

    # タグ設定
    if article.get("tags"):
        _set_tags(article["tags"], post_id)

    print(f"[novel] WP投稿完了: ID={post_id} → {edit_url}")
    return {"id": post_id, "url": post_url, "edit_url": edit_url}


def _set_tags(tag_names: list[str], post_id: int) -> None:
    import requests
    from requests.auth import HTTPBasicAuth
    auth = HTTPBasicAuth(WP_USER, WP_PASS)
    base = WP_URL.rstrip("/")
    tag_ids = []
    for name in tag_names:
        r = requests.post(f"{base}/wp-json/wp/v2/tags",
                          json={"name": name}, auth=auth, timeout=10)
        if r.status_code in (200, 201):
            tag_ids.append(r.json()["id"])
        elif r.status_code == 400:
            # 既存タグ検索
            r2 = requests.get(f"{base}/wp-json/wp/v2/tags",
                               params={"search": name}, auth=auth, timeout=10)
            if r2.ok and r2.json():
                tag_ids.append(r2.json()[0]["id"])
    if tag_ids:
        requests.post(f"{base}/wp-json/wp/v2/posts/{post_id}",
                      json={"tags": tag_ids}, auth=auth, timeout=10)


# ── スプレッドシート更新 ─────────────────────────────────────
def update_sheet(ws, row_idx: int, slug: str, post_id: int,
                 post_url: str, dialect_note: str) -> None:
    """投稿結果とスラッグ・飛騨弁メモをシートに書き戻す。"""
    today = date.today().strftime("%Y/%m/%d")
    # B=スラッグ, D=飛騨弁メモ, E=ステータス, F=投稿日, G=URL, H=ID
    ws.update(range_name=f"B{row_idx}", values=[[slug]])
    if dialect_note:
        ws.update(range_name=f"D{row_idx}", values=[[dialect_note]])
    ws.update(range_name=f"E{row_idx}:H{row_idx}", values=[["投稿済み", today, post_url, str(post_id)]])
    print(f"[novel] シート更新完了: 行{row_idx}")


# ── メイン処理 ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="小説シートから記事を生成してWPに投稿する")
    parser.add_argument("--dry-run", action="store_true", help="WP投稿せず内容を表示")
    parser.add_argument("--limit", type=int, default=1, help="処理件数（デフォルト1件）")
    args = parser.parse_args()

    # スプレッドシート接続
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SS_ID).worksheet(SHEET)
    rows = ws.get_all_values()

    if len(rows) < 2:
        print("小説シートにデータがありません。")
        return

    header = rows[0]
    processed = 0

    for row_idx, row in enumerate(rows[1:], start=2):
        def cell(i):
            return row[i].strip() if i < len(row) else ""

        title   = cell(0)
        slug    = cell(1)
        body    = cell(2)
        status  = cell(4)

        if not title or not body:
            continue
        if status == "投稿済み":
            print(f"[novel] スキップ（投稿済み）: 「{title}」")
            continue

        print(f"\n{'='*60}")
        print(f"処理中: 「{title}」")
        print(f"{'='*60}")

        # 記事生成
        article = generate_novel_article(title, body)

        # スラッグ補完
        if not article.get("slug"):
            article["slug"] = slug or _make_slug(title)

        if args.dry_run:
            print("\n--- DRY RUN: 生成内容 ---")
            print(f"タイトル: {article.get('title')}")
            print(f"SEOタイトル: {article.get('seo_title')}")
            print(f"スラッグ: {article.get('slug')}")
            print(f"タグ: {article.get('tags')}")
            print(f"本文（先頭500字）:\n{article.get('content','')[:500]}")
            processed += 1
            if processed >= args.limit:
                break
            continue

        # 記事内画像生成・挿入（3枚・アイキャッチなし）
        article = generate_and_insert_images(article, title)

        # WP投稿
        result = post_to_wp(article)

        # シート更新
        update_sheet(ws, row_idx,
                     slug=article["slug"],
                     post_id=result["id"],
                     post_url=result["url"],
                     dialect_note="")  # 飛騨弁はarticle内のテーブルに含まれるため空欄でOK

        print(f"\n✅ 完了: 「{article['title']}」")
        print(f"   {result['edit_url']}")
        processed += 1
        if processed >= args.limit:
            break

    print(f"\n合計 {processed} 件処理しました。")


if __name__ == "__main__":
    main()
