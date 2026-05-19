"""
rewrite_executor.py

「リライト提案」シートの「リライト実行」列が「now」の記事を自動リライトし、
WordPress に下書き保存するモジュール。

処理フロー:
    1. スプレッドシートから「リライト実行」=「now」の行を取得
    2. 対象記事の現在本文を WordPress REST API で取得
    3. GSC 流入クエリを取得
    4. Claude Sonnet でリライト案を生成
    5. WordPress に下書き（draft）保存
    6. シートのステータス・実施日・結果メモを更新し「リライト実行」を「完了」に変更
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta

import gspread
import requests
from google.oauth2.service_account import Credentials
from requests.auth import HTTPBasicAuth

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_REWRITE_SHEET_NAME = "リライト提案"
_NOW_TRIGGER = "now"


# ──────────────────────────────────────────────────────────
# スプレッドシート操作
# ──────────────────────────────────────────────────────────

def _open_sheet(ss_id: str) -> tuple[gspread.Spreadsheet, gspread.Worksheet]:
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(ss_id)
    ws = ss.worksheet(_REWRITE_SHEET_NAME)
    return ss, ws


def _get_col_map(ws: gspread.Worksheet) -> dict[str, int]:
    """ヘッダー行 → {列名: 1始まりインデックス} のマップを返す。"""
    headers = ws.row_values(1)
    return {h: i + 1 for i, h in enumerate(headers)}


def _find_now_rows(ws: gspread.Worksheet, col_map: dict[str, int]) -> list[dict]:
    """「リライト実行」列が「now」（大文字小文字不問）の行データを返す。"""
    exec_col = col_map.get("リライト実行")
    if not exec_col:
        print("[executor] 「リライト実行」列が見つかりません")
        return []

    all_rows  = ws.get_all_values()
    headers   = all_rows[0]
    now_rows  = []

    for row_idx, row in enumerate(all_rows[1:], start=2):
        # 行が短い場合は空値で補完
        padded = row + [""] * (len(headers) - len(row))
        val = padded[exec_col - 1].strip().lower()
        if val != _NOW_TRIGGER:
            continue
        status = padded[col_map.get("ステータス", 0) - 1] if "ステータス" in col_map else ""
        if status in ("下書き作成済み", "公開済み"):
            print(f"[executor] スキップ（ステータス={status}）: 行{row_idx}")
            continue
        now_rows.append({
            "row_idx":       row_idx,
            "title":         padded[col_map.get("記事タイトル", 3) - 1],
            "url":           padded[col_map.get("URL", 4) - 1],
            "strength":      padded[col_map.get("リライト強度", 0) - 1]    if "リライト強度"      in col_map else "",
            "reason":        padded[col_map.get("提案理由", 0) - 1]        if "提案理由"          in col_map else "",
            "intents":       padded[col_map.get("追加すべき検索意図", 0) - 1] if "追加すべき検索意図" in col_map else "",
            "h2_h3":         padded[col_map.get("追加H2/H3案", 0) - 1]    if "追加H2/H3案"       in col_map else "",
            "faq":           padded[col_map.get("FAQ案", 0) - 1]           if "FAQ案"             in col_map else "",
            "internal":      padded[col_map.get("内部リンク案", 0) - 1]    if "内部リンク案"       in col_map else "",
            "asp":           padded[col_map.get("ASP導線案", 0) - 1]       if "ASP導線案"         in col_map else "",
            "cta":           padded[col_map.get("CTA案", 0) - 1]           if "CTA案"             in col_map else "",
            "top_queries":   padded[col_map.get("主な流入クエリ", 0) - 1]  if "主な流入クエリ"     in col_map else "",
        })

    return now_rows


def _update_row(ws: gspread.Worksheet, col_map: dict[str, int], row_idx: int,
                status: str, memo: str, success: bool = True) -> None:
    today = date.today().strftime("%Y/%m/%d")
    updates = {
        # 成功時のみ「完了」に変更。失敗時は「now」のまま残してリトライできるようにする
        "リライト実行": "完了" if success else "now",
        "ステータス":   status,
        "実施日":       today if success else "",
        "結果メモ":     memo,
    }
    for col_name, value in updates.items():
        col = col_map.get(col_name)
        if col:
            ws.update_cell(row_idx, col, value)


# ──────────────────────────────────────────────────────────
# WordPress
# ──────────────────────────────────────────────────────────

def _slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _fetch_wp_post(wp_url: str, auth: HTTPBasicAuth, page_url: str) -> dict | None:
    """URLからWP記事データ（id, title, content raw, status）を取得。"""
    slug = _slug_from_url(page_url)
    resp = requests.get(
        f"{wp_url}/wp-json/wp/v2/posts",
        auth=auth,
        params={
            "slug":    slug,
            "context": "edit",
            "_fields": "id,title,content,link,status",
        },
        timeout=30,
    )
    resp.raise_for_status()
    posts = resp.json()
    if not posts:
        return None
    return posts[0]


def _save_wp_post(wp_url: str, auth: HTTPBasicAuth, post_id: int,
                  content: str, current_status: str) -> str:
    """WP記事の本文を更新する。公開済みなら公開状態を維持し非公開にしない。"""
    resp = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
        auth=auth,
        json={"content": content, "status": current_status},
        timeout=60,
    )
    resp.raise_for_status()
    return f"{wp_url}/wp-admin/post.php?post={post_id}&action=edit"


# ──────────────────────────────────────────────────────────
# GSC クエリ取得（1ページ分）
# ──────────────────────────────────────────────────────────

def _fetch_page_gsc_queries(gsc_client, page_url: str) -> list[dict]:
    """対象URLの過去90日の流入クエリを取得。"""
    from datetime import date, timedelta
    end_date   = date.today() - timedelta(days=3)
    start_date = end_date - timedelta(days=89)
    url_with_slash = page_url.rstrip("/") + "/"

    service = gsc_client._get_service()
    try:
        resp = service.searchanalytics().query(
            siteUrl=gsc_client.site_url,
            body={
                "startDate": start_date.isoformat(),
                "endDate":   end_date.isoformat(),
                "dimensions": ["query"],
                "dimensionFilterGroups": [{
                    "filters": [{
                        "dimension":  "page",
                        "operator":   "equals",
                        "expression": url_with_slash,
                    }]
                }],
                "rowLimit": 50,
            },
        ).execute()
    except Exception as e:
        print(f"[executor] GSCクエリ取得エラー（続行）: {e}")
        return []

    return [
        {
            "query":       row["keys"][0],
            "clicks":      row.get("clicks",      0),
            "impressions": row.get("impressions", 0),
            "position":    row.get("position",    0.0),
        }
        for row in resp.get("rows", [])
    ]


# ──────────────────────────────────────────────────────────
# Claude リライト生成
# ──────────────────────────────────────────────────────────

_PATCH_RE = re.compile(
    r'\[INSERT:\s*(?P<pos>[^\]]+)\]\s*\n(?P<content>.*?)\[/INSERT\]',
    re.DOTALL,
)


def _find_after_heading(content: str, heading_text: str) -> int:
    """指定見出しブロック直後の位置を返す。見つからなければ -1。"""
    m = re.search(
        r'<!-- wp:heading[^>]*-->.*?' + re.escape(heading_text) + r'.*?<!-- /wp:heading -->',
        content, re.DOTALL | re.IGNORECASE,
    )
    return m.end() if m else -1


def _find_before_heading(content: str, heading_text: str) -> int:
    """指定見出しブロック直前の位置を返す。見つからなければ -1。"""
    m = re.search(
        r'<!-- wp:heading[^>]*-->.*?' + re.escape(heading_text) + r'.*?<!-- /wp:heading -->',
        content, re.DOTALL | re.IGNORECASE,
    )
    return m.start() if m else -1


def _resolve_position(content: str, pos_spec: str) -> int:
    """挿入位置の指定文字列を実際のインデックスに変換する。"""
    s = pos_spec.strip()
    m = re.match(r'(after|before)\s+(h2|h3)\s+"?(.+?)"?\s*$', s, re.IGNORECASE)
    if m:
        direction, _level, text = m.group(1).lower(), m.group(2), m.group(3)
        if direction == 'after':
            return _find_after_heading(content, text)
        else:
            return _find_before_heading(content, text)
    if 'まとめ' in s:
        pos = _find_before_heading(content, 'まとめ')
        return pos if pos >= 0 else len(content)
    return -1


def _apply_patches(original: str, patch_text: str) -> str:
    """Claudeが出力したパッチ群を元記事に適用する。元記事の文字は削らない。"""
    patches = list(_PATCH_RE.finditer(patch_text))
    if not patches:
        return original

    insertions: list[tuple[int, str]] = []
    for patch in patches:
        pos_spec   = patch.group('pos')
        new_block  = '\n' + patch.group('content').strip() + '\n'
        insert_pos = _resolve_position(original, pos_spec)
        if insert_pos >= 0:
            insertions.append((insert_pos, new_block))
        else:
            print(f"[executor] パッチ挿入位置が見つかりません: {pos_spec!r} → 末尾に追加")
            insertions.append((len(original), new_block))

    # 後ろから挿入することでオフセットのズレを防ぐ
    result = original
    for pos, block in sorted(insertions, key=lambda x: -x[0]):
        result = result[:pos] + block + result[pos:]
    return result


def _count_wp_images(content: str) -> int:
    """記事内の <!-- wp:image --> ブロック数を数える。"""
    return len(re.findall(r'<!-- wp:image', content))


def _find_imageless_h2_positions(content: str) -> list[tuple[int, str]]:
    """画像が直後にないH2ブロックの (終端位置, H2テキスト) リストを返す。"""
    results = []
    for m in re.finditer(
        r'<!-- wp:heading[^>]*-->.*?<h2[^>]*>(.*?)</h2>.*?<!-- /wp:heading -->',
        content, re.DOTALL,
    ):
        end_pos   = m.end()
        h2_text   = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        # 直後500字以内に wp:image がなければ候補
        lookahead = content[end_pos:end_pos + 500]
        if '<!-- wp:image' not in lookahead:
            results.append((end_pos, h2_text))
    return results


def _upload_image_to_wp(wp_url: str, auth: HTTPBasicAuth,
                         img_bytes: bytes, filename: str, alt_text: str) -> tuple[int, str]:
    """バイト列をWPメディアにアップロードして (media_id, src_url) を返す。"""
    resp = requests.post(
        f"{wp_url}/wp-json/wp/v2/media",
        auth=auth,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/jpeg",
        },
        data=img_bytes,
        timeout=120,
    )
    resp.raise_for_status()
    data     = resp.json()
    media_id = data["id"]
    src_url  = data.get("source_url", "")
    try:
        requests.post(f"{wp_url}/wp-json/wp/v2/media/{media_id}",
                      auth=auth, json={"alt_text": alt_text}, timeout=10)
    except Exception:
        pass
    return media_id, src_url


def _build_wp_image_block(media_id: int, src_url: str, alt_text: str) -> str:
    return (
        f'\n<!-- wp:image {{"id":{media_id},"sizeSlug":"large","linkDestination":"none"}} -->\n'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{src_url}" alt="{alt_text}" class="wp-image-{media_id}"/>'
        f'</figure>\n'
        f'<!-- /wp:image -->\n'
    )


def _add_rewrite_images(
    content: str, wp_url: str, auth: HTTPBasicAuth,
    keyword: str, slug: str, max_add: int = 3,
) -> str:
    """記事内画像が少ない場合、FLUX画像を最大 max_add 枚追加する。"""
    try:
        from modules.image_generator import generate_h2_image
    except ImportError:
        print("[executor] image_generator インポート失敗 → 画像追加スキップ")
        return content

    current_img_count = _count_wp_images(content)
    can_add = max_add - current_img_count
    if can_add <= 0:
        print(f"[executor] 画像{current_img_count}枚 → 追加不要")
        return content

    candidates = _find_imageless_h2_positions(content)
    if not candidates:
        print("[executor] 画像挿入候補H2なし → スキップ")
        return content

    result      = content
    added       = 0
    offset      = 0  # 挿入によるオフセット補正

    for pos, h2_text in candidates[:can_add]:
        try:
            img_bytes = generate_h2_image(h2_text, keyword)
            filename  = f"{slug}-rewrite-{added + 1:02d}.jpg"
            alt_text  = f"{h2_text}のイメージ画像"
            media_id, src_url = _upload_image_to_wp(wp_url, auth, img_bytes, filename, alt_text)
            img_block = _build_wp_image_block(media_id, src_url, alt_text)
            insert_at = pos + offset
            result    = result[:insert_at] + img_block + result[insert_at:]
            offset   += len(img_block)
            added    += 1
            print(f"[executor] 画像追加[{added}] H2:{h2_text[:30]} → {filename}")
        except Exception as e:
            print(f"[executor] 画像生成失敗（続行）: {e}")

    print(f"[executor] 画像: {current_img_count}枚 → {current_img_count + added}枚")
    return result


def _fetch_recent_wp_posts(wp_url: str, auth: HTTPBasicAuth, n: int = 10) -> list[dict]:
    """ブログの最近の公開記事一覧 (title, link) を取得する。"""
    try:
        resp = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            auth=auth,
            params={"per_page": n, "status": "publish", "_fields": "title,link"},
            timeout=15,
        )
        return [{"title": p["title"]["rendered"], "link": p["link"]} for p in resp.json()]
    except Exception:
        return []


def _generate_rewrite(row: dict, current_content: str, gsc_queries: list[dict],
                       blog_cfg: dict, recent_posts: list[dict] | None = None) -> str:
    """Claude Sonnet で追加パッチを生成し元記事に適用して返す。"""
    import anthropic
    from config import ANTHROPIC_API_KEY

    try:
        from modules.api_guard import record_usage
    except ImportError:
        record_usage = lambda *a, **k: None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # GSCクエリ上位10件（クリック数降順）
    top_queries = sorted(gsc_queries, key=lambda x: -x["clicks"])[:10]
    query_text  = "\n".join(
        f"・{q['query']} (クリック:{q['clicks']} / 表示:{q['impressions']} / 順位:{q['position']:.1f})"
        for q in top_queries
    ) or "（データなし）"

    writing_style = blog_cfg.get("writing_style", {})
    blog_name     = blog_cfg.get("display_name", "")
    genre         = blog_cfg.get("genre", "")

    proposal_parts = []
    if row.get("reason"):   proposal_parts.append(f"【提案理由】\n{row['reason']}")
    if row.get("intents"):  proposal_parts.append(f"【追加すべき検索意図】\n{row['intents']}")
    if row.get("h2_h3"):    proposal_parts.append(f"【追加H2/H3案】\n{row['h2_h3']}")
    if row.get("faq"):      proposal_parts.append(f"【FAQ案】\n{row['faq']}")
    if row.get("internal"): proposal_parts.append(f"【内部リンク案】\n{row['internal']}")
    if row.get("asp"):      proposal_parts.append(f"【ASP導線案】\n{row['asp']}")
    if row.get("cta"):      proposal_parts.append(f"【CTA案】\n{row['cta']}")
    proposal_text = "\n\n".join(proposal_parts) or "（提案テキストなし。GSCクエリを参考に補強）"

    strength = row.get("strength", "軽微〜中規模")

    # 同ブログの最近の記事一覧（古い情報の誘導先候補）
    recent_posts_text = ""
    if recent_posts:
        recent_posts_text = "\n## 同ブログの最近の公開記事（古い情報への誘導先として活用可）\n"
        for p in recent_posts[:8]:
            recent_posts_text += f"・{p['title']}  {p['link']}\n"

    system_prompt = f"""あなたはSEO特化のコンテンツライターです。
ブログ名: {blog_name}
ジャンル: {genre}
文章のトーン: {writing_style.get("tone", "実用的でわかりやすい")}

## 出力形式（厳守）
既存記事には一切手を加えず、「追加するブロックだけ」を以下の形式で出力してください。

[INSERT: after H3 "挿入先の見出しテキスト"]
（ここにWordPress Gutenbergブロック形式の追加コンテンツ）
[/INSERT]

[INSERT: after H2 "挿入先のH2テキスト"]
（H4やH3を追加する場合もここに書く）
[/INSERT]

[INSERT: before H2 "まとめ"]
（まとめ前に新H2セクションを追加する場合）
[/INSERT]

## リライトルール（厳守）
- **文字数は絶対に減らさない**。追加のみ行う
- **既存のH2・H3は変更しない**（テキスト・順序・構成）
- 新しいH2・H3を追加することはOKだが追加しすぎない（既存H2の20%増し以内が目安）
- **H4を積極的に活用**して既存H3の内容を深掘りする
- **古い情報・過去の日付・廃止されたサービス**を見つけたら：
  - 「最新情報」としてH4または段落で補足する
  - 同ブログに関連する最新記事があれば <!-- wp:paragraph --><p>最新情報は<a href="URL">こちらの記事</a>をご覧ください。</p><!-- /wp:paragraph --> で誘導する
- 追加コンテンツはWordPress SWELL形式（Gutenbergブロック）で書く
- 挿入先の見出しテキストは記事内の実際の文字列をそのまま使う

## 文章ルール
- やさしく寄り添う口調。「〜ですね」「〜してみてくださいね」を自然に使う
- 「〜ですよ」は使わない
- 「完全」「徹底」をタイトル・見出しに使わない
- ASPリンクが不明な場合は <!-- アフィリリンク: {{サービス名}} --> とコメントで明示"""

    user_prompt = f"""以下の記事に不足している内容を追加してください。

## 対象記事
タイトル: {row['title']}
URL: {row['url']}
リライト強度: {strength}

## リライト提案
{proposal_text}

## GSC流入クエリ（過去90日）
{query_text}
{recent_posts_text}
## 現在の記事本文
{current_content}

---
【作業指示】
1. 既存H2・H3を一切変更せず、追加コンテンツだけを [INSERT] 形式で出力してください
2. 既存本文の出力・削除は絶対禁止。追加のみ
3. 古い情報があれば最新情報をH4で補足するか、関連最新記事へのリンクで誘導してください
4. H4を使って既存H3の内容を深掘りしてください（複数箇所OK）
5. H2・H3の追加は本当に必要な場合のみ（追加しすぎない）"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    record_usage(
        "claude-sonnet-4-6",
        msg.usage.input_tokens,
        msg.usage.output_tokens,
        f"rewrite:{row['url']}",
    )

    patch_text = msg.content[0].text.strip()
    result     = _apply_patches(current_content, patch_text)
    print(f"[executor] パッチ適用: {len(current_content)}字 → {len(result)}字 (+{len(result)-len(current_content)}字)")
    return result


# ──────────────────────────────────────────────────────────
# メインエントリ
# ──────────────────────────────────────────────────────────

def run_rewrite(blog_name: str) -> None:
    """「リライト実行」=「now」の記事を自動リライトしてWP下書き保存する。"""
    import json as _json
    from modules.gsc_client import GSCClient

    # ブログ設定
    cfg_path = os.path.join(
        os.path.dirname(__file__), "..", "blogs", blog_name, "blog_config.json"
    )
    with open(cfg_path) as f:
        blog_cfg = _json.load(f)

    display_name  = blog_cfg.get("display_name", blog_name)
    wp_url        = blog_cfg.get("wp_url", "").rstrip("/")
    ss_id         = blog_cfg.get("main_ss_id", "")
    wp_username   = os.getenv(blog_cfg.get("wp_username_env", ""), "")
    wp_password   = os.getenv(blog_cfg.get("wp_app_password_env", ""), "")
    wp_auth       = HTTPBasicAuth(wp_username, wp_password)

    if not ss_id:
        print("[executor] main_ss_id が未設定")
        return

    print(f"\n{'='*60}")
    print(f"[executor] リライト実行開始: {display_name}")
    print(f"{'='*60}")

    # シートから「now」行を取得
    _, ws  = _open_sheet(ss_id)
    col_map = _get_col_map(ws)
    now_rows = _find_now_rows(ws, col_map)

    if not now_rows:
        print("[executor] 「now」の記事なし → 終了")
        return

    print(f"[executor] リライト対象: {len(now_rows)}件")

    # GSCクライアント初期化
    gsc = GSCClient(site_url=wp_url + "/")

    for i, row in enumerate(now_rows, 1):
        print(f"\n[executor] [{i}/{len(now_rows)}] {row['title'][:50]}")
        print(f"           URL: {row['url']}")

        try:
            # WP記事取得
            post = _fetch_wp_post(wp_url, wp_auth, row["url"])
            if not post:
                print(f"[executor] WP記事が見つかりません → スキップ")
                _update_row(ws, col_map, row["row_idx"], "エラー", "WP記事が見つかりません", success=False)
                continue

            post_id         = post["id"]
            current_content = post["content"]["raw"]
            current_status  = post.get("status", "publish")
            print(f"[executor] WP記事取得完了 (ID={post_id}, {len(current_content)}字, status={current_status})")

            # GSCクエリ取得
            gsc_queries = _fetch_page_gsc_queries(gsc, row["url"])
            print(f"[executor] GSCクエリ: {len(gsc_queries)}件")

            # 同ブログの最近記事取得（古い情報の誘導先候補）
            recent_posts = _fetch_recent_wp_posts(wp_url, wp_auth)

            # Claude リライト生成（追記パッチ方式）
            print(f"[executor] Claude リライト生成中...")
            rewritten = _generate_rewrite(row, current_content, gsc_queries, blog_cfg, recent_posts)
            print(f"[executor] 生成完了: {len(rewritten)}字")

            # 画像が少ない場合はFLUXで追加（最大3枚まで）
            slug    = _slug_from_url(row["url"])
            keyword = row.get("title", slug)
            rewritten = _add_rewrite_images(rewritten, wp_url, wp_auth, keyword, slug, max_add=3)

            # WP保存（公開済みなら公開状態を維持）
            edit_url = _save_wp_post(wp_url, wp_auth, post_id, rewritten, current_status)
            print(f"[executor] WP保存完了 (status={current_status}): {edit_url}")

            # シート更新
            sheet_status = "公開済み" if current_status == "publish" else "下書き作成済み"
            _update_row(ws, col_map, row["row_idx"], sheet_status, edit_url)
            print(f"[executor] シート更新完了")

        except Exception as e:
            print(f"[executor] エラー: {e}")
            _update_row(ws, col_map, row["row_idx"], "エラー", str(e)[:100], success=False)

    print(f"\n{'='*60}")
    print(f"[executor] 完了: {len(now_rows)}件処理")
    print(f"{'='*60}\n")
