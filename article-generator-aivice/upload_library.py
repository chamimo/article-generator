"""
画像ライブラリ一括アップロードスクリプト

library_images/ 内の画像を Claude Haiku で分析し、
ファイル名・キャプション・ALTを自動設定して WordPress メディアライブラリに登録する。

Usage:
    python3 upload_library.py
    python3 upload_library.py --dry-run   # WPアップロードせず分析結果だけ確認
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import time
from pathlib import Path

import anthropic
import requests
from requests.auth import HTTPBasicAuth

from config import (
    ANTHROPIC_API_KEY,
    WP_URL,
    WP_USERNAME,
    WP_APP_PASSWORD,
)

# ─────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────

LIBRARY_DIR = Path(__file__).parent / "library_images"
DONE_DIR    = LIBRARY_DIR / "done"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# カテゴリー定義: (判定キーワード, 英語スラッグ, #タグリスト)
_CATEGORIES = [
    (
        ["chatgpt", "gpt", "openai", "claude", "gemini", "生成ai", "チャット", "llm", "プロンプト"],
        "ai-chatgpt",
        ["#ChatGPT", "#AI活用"],
    ),
    (
        ["文字起こし", "議事録", "ボイスレコーダー", "録音", "icレコーダー", "plaud", "notta", "ボイスメモ", "音声"],
        "transcription",
        ["#文字起こし", "#議事録", "#ボイスレコーダー"],
    ),
    (
        ["画像生成", "midjourney", "stable diffusion", "dall-e", "illustrate", "ai画像", "イラスト"],
        "ai-image",
        ["#AI画像生成", "#Midjourney"],
    ),
    (
        ["スクール", "学習", "勉強", "資格", "キャリア", "プログラミング", "コース", "udemy"],
        "ai-school",
        ["#AIスクール", "#学習"],
    ),
    (
        ["動画", "video", "filmora", "youtube", "編集", "ショート", "reels"],
        "video",
        ["#動画生成", "#Filmora"],
    ),
]
_DEFAULT_CATEGORY = ("ai-tool", ["#AI活用", "#AIツール"])

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────────
# ヘルパー
# ─────────────────────────────────────────────

def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)


def _image_to_base64(path: Path) -> tuple[str, str]:
    """画像をbase64エンコードし (data, media_type) を返す。"""
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = mime_map.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def _fallback_from_filename(path: Path) -> dict:
    """Haiku 分析失敗時にファイル名からカテゴリーを推測するフォールバック。"""
    name_lower = path.stem.lower()
    for keywords, slug, tag_list in _CATEGORIES:
        if any(k in name_lower for k in keywords):
            return {
                "category_slug":  slug,
                "tags":           tag_list,
                "alt_text":       "AIツール関連のイメージ画像",
                "description":    slug,
                "category_label": "フォールバック",
            }
    # ImageFX 由来ファイルはAI画像生成扱い
    if "image_fx" in name_lower or "imagefx" in name_lower:
        return {
            "category_slug":  "ai-image",
            "tags":           ["#AI画像生成", "#Midjourney"],
            "alt_text":       "AI生成イメージ画像",
            "description":    "ai-generated-image",
            "category_label": "AI画像生成系（自動）",
        }
    return {
        "category_slug":  _DEFAULT_CATEGORY[0],
        "tags":           _DEFAULT_CATEGORY[1],
        "alt_text":       "AIツール関連のイメージ画像",
        "description":    "ai-tool",
        "category_label": "その他AI系（自動）",
    }


def _analyze_image(path: Path) -> dict:
    """
    Claude Haiku で画像を分析し、カテゴリー・ALT・タグを返す。
    Haiku 呼び出し失敗時はファイル名ベースのフォールバックを使用する。

    Returns:
        {
            "category_slug": "transcription",
            "tags": ["#文字起こし", "#議事録", "#ボイスレコーダー"],
            "alt_text": "AIボイスレコーダーで会議を録音している様子",
            "description": "短い内容説明（英語ファイル名生成用）",
        }
    """
    img_data, media_type = _image_to_base64(path)

    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_data,
                        },
                    },
                    {
                        "type": "text",
                        "content": (
                            "この画像を分析して以下のJSONのみ返してください（```json などのコードブロック記号は不要）:\n"
                            '{"category":"AI・ChatGPT系"|"文字起こし・議事録系"|"AI画像生成系"|"AIスクール・学習系"|"動画生成・編集系"|"その他AI系",'
                            '"alt_text":"画像の内容を日本語で30字以内で説明",'
                            '"description":"3-5 words English noun phrase describing the image content"}'
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
        alt_text       = result.get("alt_text", path.stem)
        description    = result.get("description", path.stem)

        # カテゴリーラベル → スラッグ・タグに変換
        label_lower   = category_label.lower()
        category_slug = _DEFAULT_CATEGORY[0]
        tags          = _DEFAULT_CATEGORY[1]
        for keywords, slug, tag_list in _CATEGORIES:
            if any(k in label_lower for k in keywords):
                category_slug = slug
                tags = tag_list
                break

        return {
            "category_slug":  category_slug,
            "tags":           tags,
            "alt_text":       alt_text,
            "description":    description,
            "category_label": category_label,
        }

    except Exception as e:
        print(f"  [WARN] Haiku分析失敗、ファイル名フォールバック使用: {e}")
        return _fallback_from_filename(path)


def _build_filename(category_slug: str, description: str, counter: int) -> str:
    """カテゴリー英語名-連番.jpg 形式でファイル名を生成する。"""
    # description から英数字・ハイフンのみ残す
    safe_desc = re.sub(r'[^a-zA-Z0-9\s-]', '', description).strip().lower()
    safe_desc = re.sub(r'\s+', '-', safe_desc)[:30]
    if safe_desc:
        return f"{category_slug}-{safe_desc}-{counter:03d}.jpg"
    return f"{category_slug}-{counter:03d}.jpg"


def _get_next_counter(category_slug: str) -> int:
    """done/ フォルダの既存ファイルから次の連番を決定する。"""
    pattern = re.compile(rf'^{re.escape(category_slug)}-.*-?(\d{{3}})\.jpg$')
    max_n = 0
    if DONE_DIR.exists():
        for f in DONE_DIR.iterdir():
            m = pattern.match(f.name)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _upload_to_wp(
    path: Path,
    filename: str,
    alt_text: str,
    caption: str,
) -> tuple[int, str]:
    """WordPress メディアライブラリにアップロードし (media_id, url) を返す。"""
    with open(path, "rb") as f:
        image_bytes = f.read()

    # Content-Type を拡張子から判定
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime_type = mime_map.get(ext, "image/jpeg")

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

    # ALT・キャプションを PATCH で設定
    requests.post(
        f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
        auth=_auth(),
        json={
            "alt_text":  alt_text,
            "caption":   caption,
            "title":     filename.replace(".jpg", ""),
        },
        timeout=15,
    )

    return media_id, data.get("source_url", "")


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="画像ライブラリ一括アップロード")
    parser.add_argument("--dry-run", action="store_true", help="分析のみ・WPアップロードしない")
    args = parser.parse_args()

    DONE_DIR.mkdir(parents=True, exist_ok=True)

    # 対象画像を収集（done/ を除く）
    images = sorted(
        p for p in LIBRARY_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )

    if not images:
        print(f"[upload_library] 対象画像が見つかりません: {LIBRARY_DIR}")
        return

    print(f"[upload_library] 対象: {len(images)}枚")
    if args.dry_run:
        print("[upload_library] ★ドライランモード: WPアップロードは行いません")

    results = []
    # カテゴリー別連番カウンター
    counters: dict[str, int] = {}

    for i, img_path in enumerate(images, 1):
        print(f"\n[{i}/{len(images)}] {img_path.name}")

        try:
            # ── Haiku で画像分析 ──
            analysis = _analyze_image(img_path)
            slug    = analysis["category_slug"]
            tags    = analysis["tags"]
            alt     = analysis["alt_text"]
            desc    = analysis["description"]
            label   = analysis["category_label"]

            # 連番決定
            if slug not in counters:
                counters[slug] = _get_next_counter(slug)
            n = counters[slug]
            counters[slug] += 1

            filename = _build_filename(slug, desc, n)
            caption  = " ".join(tags)

            print(f"  カテゴリー : {label}")
            print(f"  ファイル名 : {filename}")
            print(f"  キャプション: {caption}")
            print(f"  ALT        : {alt}")

            if not args.dry_run:
                media_id, url = _upload_to_wp(img_path, filename, alt, caption)
                print(f"  WP登録完了 → ID:{media_id}  {url}")

                # done/ に移動（リネームして保存）
                dest = DONE_DIR / filename
                # 同名ファイルが存在する場合はサフィックスを追加
                if dest.exists():
                    dest = DONE_DIR / f"{dest.stem}_dup{dest.suffix}"
                shutil.move(str(img_path), dest)
                print(f"  移動完了   → done/{dest.name}")

                results.append({
                    "original": img_path.name,
                    "filename": filename,
                    "media_id": media_id,
                    "url": url,
                    "alt": alt,
                    "caption": caption,
                    "status": "success",
                })
            else:
                results.append({
                    "original": img_path.name,
                    "filename": filename,
                    "alt": alt,
                    "caption": caption,
                    "status": "dry-run",
                })

        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append({
                "original": img_path.name,
                "status": "error",
                "error": str(e),
            })

        # API レート制限対策
        if i < len(images):
            time.sleep(1)

    # ── サマリー表示 ──
    success = [r for r in results if r["status"] in ("success", "dry-run")]
    errors  = [r for r in results if r["status"] == "error"]

    print(f"\n{'='*60}")
    print(f"【完了】成功: {len(success)}枚 / エラー: {len(errors)}枚 / 合計: {len(results)}枚")
    if errors:
        print("エラー一覧:")
        for r in errors:
            print(f"  - {r['original']}: {r.get('error','')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
