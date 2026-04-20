"""
WPメディアライブラリの既存画像にキャプション（#タグ）を自動付与するスクリプト

- キャプションが空の画像を対象にClaudeHaikuで分析
- カテゴリーに応じた#タグをキャプションとして設定
- ALTテキストが空の場合も自動設定

Usage:
    python3 tag_media.py --dry-run  # 確認のみ
    python3 tag_media.py            # 実際に更新
    python3 tag_media.py --limit 20 # 最大20件処理
    python3 tag_media.py --all      # キャプション有り画像も再処理
"""
from __future__ import annotations

import argparse
import base64
import json
import time

import anthropic
import requests
from requests.auth import HTTPBasicAuth

from config import ANTHROPIC_API_KEY, WP_URL, WP_USERNAME, WP_APP_PASSWORD

# ─────────────────────────────────────────────
# カテゴリー定義（upload_library.py と共通）
# ─────────────────────────────────────────────
_CATEGORIES = [
    (
        ["chatgpt", "gpt", "openai", "claude", "gemini", "生成ai", "チャット", "llm", "プロンプト"],
        ["#ChatGPT", "#AI活用"],
    ),
    (
        ["文字起こし", "議事録", "ボイスレコーダー", "録音", "icレコーダー", "plaud", "notta", "ボイスメモ", "音声"],
        ["#文字起こし", "#議事録", "#ボイスレコーダー"],
    ),
    (
        ["画像生成", "midjourney", "stable diffusion", "dall-e", "ai画像", "イラスト"],
        ["#AI画像生成", "#Midjourney"],
    ),
    (
        ["スクール", "学習", "勉強", "資格", "キャリア", "プログラミング", "コース", "udemy"],
        ["#AIスクール", "#学習"],
    ),
    (
        ["動画", "video", "filmora", "youtube", "編集", "ショート"],
        ["#動画生成", "#Filmora"],
    ),
]
_DEFAULT_TAGS = ["#AI活用", "#AIツール"]

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)


# ─────────────────────────────────────────────
# WP REST API
# ─────────────────────────────────────────────

def _fetch_media_list(limit: int | None = None, skip_captioned: bool = True) -> list[dict]:
    """
    WPメディアライブラリから画像一覧を取得する。
    skip_captioned=True のとき、キャプション済みは除外。
    """
    items: list[dict] = []
    page = 1
    per_page = 100

    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/media",
            auth=_auth(),
            params={
                "per_page": per_page,
                "page": page,
                "media_type": "image",
                "_fields": "id,title,caption,alt_text,source_url,mime_type",
            },
            timeout=30,
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for item in batch:
            caption_raw = item.get("caption", {})
            caption_text = (
                caption_raw.get("rendered", "") if isinstance(caption_raw, dict)
                else str(caption_raw)
            ).strip()
            # <p>タグを除去して純テキスト化
            import re
            caption_text = re.sub(r'<[^>]+>', '', caption_text).strip()

            if skip_captioned and caption_text:
                continue  # キャプションあり → スキップ

            # 画像のみ
            if not item.get("mime_type", "").startswith("image/"):
                continue

            items.append({
                "id":         item["id"],
                "title":      item["title"]["rendered"] if isinstance(item.get("title"), dict) else str(item.get("title", "")),
                "caption":    caption_text,
                "alt_text":   item.get("alt_text", ""),
                "source_url": item.get("source_url", ""),
                "mime_type":  item.get("mime_type", "image/jpeg"),
            })

            if limit and len(items) >= limit:
                print(f"[tag_media] --limit {limit} 件で打ち切り")
                return items

        if len(batch) < per_page:
            break
        page += 1

    return items


def _download_image(url: str) -> bytes | None:
    """画像をダウンロードしてバイト列を返す。失敗時は None。"""
    try:
        resp = requests.get(url, auth=_auth(), timeout=30)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  [WARN] ダウンロード失敗: {e}")
        return None


_EN_KEYWORDS = [
    (["voice-recorder", "transcription", "meeting", "dictation", "notta", "plaud", "recording", "minutes"],
     ["#文字起こし", "#議事録", "#ボイスレコーダー"]),
    (["chatgpt", "gpt", "openai", "claude", "gemini", "llm", "prompt", "chat-ai"],
     ["#ChatGPT", "#AI活用"]),
    (["ai-image", "image-gen", "midjourney", "stable-diffusion", "dall-e", "imagefx", "image_fx"],
     ["#AI画像生成", "#Midjourney"]),
    (["school", "learning", "course", "udemy", "career", "programming", "coding"],
     ["#AIスクール", "#学習"]),
    (["video", "filmora", "youtube", "editing", "short-video"],
     ["#動画生成", "#Filmora"]),
]


def _fallback_from_filename(filename: str) -> dict:
    """Haiku 分析失敗時にファイル名からカテゴリーを推測するフォールバック。"""
    name = filename.lower()
    # 英語キーワードで判定
    for keywords, tag_list in _EN_KEYWORDS:
        if any(k in name for k in keywords):
            return {"category_label": "フォールバック（英語KW）", "tags": tag_list, "alt_text": "AIツール関連のイメージ画像"}
    # 日本語キーワードで判定
    for keywords, tag_list in _CATEGORIES:
        if any(k in name for k in keywords):
            return {"category_label": "フォールバック（日本語KW）", "tags": tag_list, "alt_text": "AIツール関連のイメージ画像"}
    return {"category_label": "その他AI系（自動）", "tags": _DEFAULT_TAGS, "alt_text": "AIツール関連のイメージ画像"}


def _analyze_image_bytes(image_bytes: bytes, mime_type: str, filename: str = "") -> dict:
    """
    Claude Haiku で画像を分析してカテゴリー・ALT・タグを返す。
    Haiku 失敗時はファイル名フォールバックを使用する。
    """
    data = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": data,
                        },
                    },
                    {
                        "type": "text",
                        "content": (
                            "この画像を分析して以下のJSONのみ返してください（コードブロック記号不要）:\n"
                            '{"category":"AI・ChatGPT系"|"文字起こし・議事録系"|"AI画像生成系"|"AIスクール・学習系"|"動画生成・編集系"|"その他AI系",'
                            '"alt_text":"画像の内容を日本語で30字以内で説明"}'
                        ),
                    },
                ],
            }],
        )

        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = json.loads(raw)
        category_label = result.get("category", "その他AI系")
        alt_text       = result.get("alt_text", "")

        label_lower = category_label.lower()
        tags = _DEFAULT_TAGS
        for keywords, tag_list in _CATEGORIES:
            if any(k in label_lower for k in keywords):
                tags = tag_list
                break

        return {"category_label": category_label, "tags": tags, "alt_text": alt_text}

    except Exception as e:
        print(f"  [WARN] Haiku分析失敗、ファイル名フォールバック使用: {e}")
        return _fallback_from_filename(filename)


def _update_media(media_id: int, caption: str, alt_text: str) -> bool:
    """WP REST API でキャプション・ALTを更新する。"""
    patch: dict = {"caption": caption}
    if alt_text:
        patch["alt_text"] = alt_text
    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            auth=_auth(),
            json=patch,
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  [ERROR] 更新失敗 ID:{media_id}: {e}")
        return False


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="WPメディアライブラリに#タグを自動付与")
    parser.add_argument("--dry-run", action="store_true", help="更新せず分析結果のみ表示")
    parser.add_argument("--limit",   type=int, help="処理件数の上限")
    parser.add_argument("--all",     action="store_true", help="キャプション済み画像も再処理")
    args = parser.parse_args()

    skip_captioned = not args.all
    print(f"[tag_media] メディア一覧を取得中... {'（キャプションなしのみ）' if skip_captioned else '（全件）'}")
    items = _fetch_media_list(limit=args.limit, skip_captioned=skip_captioned)

    if not items:
        print("[tag_media] 対象画像が0件です。")
        return

    print(f"[tag_media] 対象: {len(items)}件")
    if args.dry_run:
        print("[tag_media] ★ドライランモード: WP更新は行いません")

    success = error = skip = 0

    for i, item in enumerate(items, 1):
        media_id = item["id"]
        url      = item["source_url"]
        print(f"\n[{i}/{len(items)}] ID:{media_id}  {url.split('/')[-1]}")

        # 画像ダウンロード
        image_bytes = _download_image(url)
        if not image_bytes:
            skip += 1
            continue

        # Haiku で分析
        try:
            analysis = _analyze_image_bytes(image_bytes, item["mime_type"], item.get("source_url", "").split("/")[-1])
        except Exception as e:
            print(f"  [ERROR] 分析失敗: {e}")
            error += 1
            continue

        caption  = " ".join(analysis["tags"])
        alt_text = analysis["alt_text"] if not item["alt_text"] else ""  # ALTが既にあれば上書きしない
        label    = analysis["category_label"]

        print(f"  カテゴリー : {label}")
        print(f"  キャプション: {caption}")
        if alt_text:
            print(f"  ALT（新規）: {alt_text}")
        else:
            print(f"  ALT（既存）: {item['alt_text']!r} → スキップ")

        if not args.dry_run:
            if _update_media(media_id, caption, alt_text):
                print(f"  ✓ 更新完了")
                success += 1
            else:
                error += 1
        else:
            success += 1

        # レート制限対策
        if i < len(items):
            time.sleep(0.5)

    print(f"\n{'='*60}")
    mode = "ドライラン" if args.dry_run else "更新"
    print(f"【{mode}完了】成功: {success}件 / スキップ: {skip}件 / エラー: {error}件 / 合計: {len(items)}件")
    print("=" * 60)


if __name__ == "__main__":
    main()
