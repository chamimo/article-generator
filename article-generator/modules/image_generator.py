"""
Step 5: Hugging Face Inference API (FLUX.1-schnell) 画像生成

- generate_eyecatch_image()  : アイキャッチ（人物あり・横長）
- generate_h2_image()        : H2記事内画像（人物なし・抽象背景）
"""
from __future__ import annotations

import io
import random
import re
import time
import anthropic
from huggingface_hub import InferenceClient

from config import HUGGINGFACE_API_KEY, ANTHROPIC_API_KEY

HF_MODEL   = "black-forest-labs/FLUX.1-schnell"
W_EYECATCH = 1216
H_EYECATCH = 832

# ─────────────────────────────────────────────
# 固定プロファイル（アイキャッチ用人物）
# ─────────────────────────────────────────────
_PERSON_PROFILE = (
    "A single photorealistic Japanese woman, light-brown hair with see-through bangs, "
    "large clear eyes, translucent skin, natural pink-toned makeup, soft gentle smile, "
    "positioned on the right or left side of frame, holding a smartphone, "
    "no shadows, no reflections, photorealistic only, no anime, no illustration"
)

# ─────────────────────────────────────────────
# 背景バリエーション（A / B / C）
# ─────────────────────────────────────────────
_BG_A = (
    "Soft Abstract background: pastel mist-like gradients, soft gentle curves, "
    "airy color transitions, dreamy light atmosphere"
)
_BG_B = (
    "Modern Tech Abstract background: geometric lines, digital grid patterns, "
    "luminous light streaks, cool blue and purple tech tones"
)
_BG_C = (
    "Dynamic Flow Abstract background: sweeping curves, dynamic ribbon shapes, "
    "flowing gradient colors, energetic abstract motion"
)
_BG_OPTIONS = [_BG_A, _BG_B, _BG_C]
_BG_LABELS  = ["Soft Abstract", "Modern Tech Abstract", "Dynamic Flow Abstract"]

# ─────────────────────────────────────────────
# 共通スタイルサフィックス（H2記事内画像用）
# ─────────────────────────────────────────────
_ABSTRACT_SUFFIX = (
    "no people, no human figures, no face, no text, no watermark, "
    "high quality digital art, vibrant colors, professional blog image"
)

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────────
# 内部: FLUX 呼び出し
# ─────────────────────────────────────────────

def _call_flux(prompt: str, width: int, height: int) -> bytes:
    """
    FLUX.1-schnell で画像を生成し JPEG バイト列を返す。
    最大3回リトライ。
    """
    if not HUGGINGFACE_API_KEY:
        raise RuntimeError("HUGGINGFACE_API_KEY が設定されていません")

    client = InferenceClient(token=HUGGINGFACE_API_KEY)

    for attempt in range(3):
        try:
            result = client.text_to_image(
                prompt=prompt,
                model=HF_MODEL,
                width=width,
                height=height,
            )
            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=90)
            img_bytes = buf.getvalue()
            print(f"[image_generator] 完了 ({len(img_bytes)//1024}KB, {width}x{height})")
            return img_bytes

        except Exception as e:
            err = str(e)
            if "loading" in err.lower() or "503" in err:
                wait = min(30, 10 * (attempt + 1))
                print(f"[image_generator] モデル起動待機 ({wait}秒)...")
                time.sleep(wait)
            elif attempt < 2:
                print(f"[image_generator] リトライ {attempt + 1}/3: {e}")
                time.sleep(5)
            else:
                raise RuntimeError(f"FLUX画像生成失敗: {e}") from e

    raise RuntimeError("FLUX画像生成: リトライ上限")


def _theme_hint(text: str) -> str:
    """Claude Haiku でキーワード/タイトルを背景テーマの英語句に変換する。"""
    msg = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=30,
        messages=[{
            "role": "user",
            "content": (
                f"Convert this Japanese topic into a short English visual theme phrase "
                f"(3-6 words, noun phrase only, no explanation, no markdown): {text}"
            ),
        }],
    )
    # 複数行・マークダウン記号を除去して最初の行だけ使う
    raw = msg.content[0].text.strip()
    first_line = raw.splitlines()[0]
    return re.sub(r'[#*`"\']+', '', first_line).strip()


# ─────────────────────────────────────────────
# 公開API
# ─────────────────────────────────────────────

def generate_eyecatch_image(keyword: str, article_theme: str = "") -> bytes:
    """
    アイキャッチ画像を生成する（人物あり）。

    - 人物: 固定の日本人女性プロファイル
    - 背景: A/B/C からランダム、キーワード・テーマを反映
    - サイズ: 1216×832
    """
    bg_style = random.choice(_BG_OPTIONS)
    bg_label = _BG_LABELS[_BG_OPTIONS.index(bg_style)]

    topic = article_theme or keyword
    theme = _theme_hint(topic)

    prompt = (
        f"{_PERSON_PROFILE}, "
        f"{bg_style}, theme: {theme}, "
        "no text, no title overlay, photorealistic, ultra high quality"
    )

    print(f"[image_generator] アイキャッチ生成 (背景:{bg_label}, テーマ:{theme})")
    return _call_flux(prompt, W_EYECATCH, H_EYECATCH)


def generate_h2_image(h2_title: str, keyword: str = "") -> bytes:
    """
    H2記事内画像を生成する（人物なし・抽象背景）。

    - 背景: A/B/C からランダム、H2タイトルを反映
    - サイズ: 1216×832
    """
    bg_style = random.choice(_BG_OPTIONS)
    bg_label = _BG_LABELS[_BG_OPTIONS.index(bg_style)]

    topic = h2_title or keyword
    theme = _theme_hint(topic)

    prompt = (
        f"{bg_style}, theme: {theme}, "
        f"{_ABSTRACT_SUFFIX}"
    )

    print(f"[image_generator] H2画像生成 (背景:{bg_label}, テーマ:{theme})")
    return _call_flux(prompt, W_EYECATCH, H_EYECATCH)


def generate_image_for_article(keyword: str, article_theme: str = "") -> bytes:
    """後方互換エイリアス（アイキャッチ生成）。"""
    return generate_eyecatch_image(keyword, article_theme)


# ─────────────────────────────────────────────
# ImageFX プロンプト生成
# ─────────────────────────────────────────────

_IMAGEFX_NO_PERSON = (
    "no people, no human, no woman, no man, no face, no silhouette, "
    "no body parts, no shadows of people, no reflections of people, "
    "purely abstract background only"
)

_IMAGEFX_BG_A = (
    "Modern soft-tech abstract background: large smooth cool-toned color planes "
    "(blue, mint, silver, purple allowed), with angled or straight lines "
    "and minimal UI-like micro-lines."
)

_IMAGEFX_BG_B = (
    "Dynamic flow abstract background with gently flowing curves or soft lines, "
    "any color palette allowed, expressing movement and gentle energy."
)

_IMAGEFX_BG_C = (
    "Soft abstract pastel background with smooth gradients, airy shapes, "
    "gentle color transitions."
)

_IMAGEFX_BG_OPTIONS = [
    ("A", _IMAGEFX_BG_A),
    ("B", _IMAGEFX_BG_B),
    ("C", _IMAGEFX_BG_C),
]


def generate_imagefx_prompt(keyword: str, title: str) -> str:
    """
    ImageFX 用アイキャッチプロンプトを生成する（人物なし・純粋抽象背景）。

    - 人物: 完全禁止
    - 背景タイプ: A/B/C からランダム選択
    - 背景の色・雰囲気: 記事テーマから Claude Haiku で生成
    - ウォーターマーク・タイトルテキスト: 固定ルールで追記

    Returns:
        完成した ImageFX プロンプト文字列
    """
    bg_label, bg_base = random.choice(_IMAGEFX_BG_OPTIONS)

    # 背景の色・雰囲気をテーマから生成
    theme_resp = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        messages=[{
            "role": "user",
            "content": (
                f"For an article about '{keyword}' titled '{title}', "
                "describe the background color and atmosphere in English (10-15 words). "
                "Start with colors. No explanation. Only the description.\n"
                "Example: 'teal and blue tones with flowing sound wave patterns and soft glow'"
            ),
        }],
    )
    theme_desc = theme_resp.content[0].text.strip().splitlines()[0]
    theme_desc = re.sub(r'[#*`"\']+', '', theme_desc).strip()

    # 記事タイトルを英訳（短縮）
    title_resp = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{
            "role": "user",
            "content": (
                f"Translate to short English (max 5 words, title case, no punctuation): {title}"
            ),
        }],
    )
    en_title = title_resp.content[0].text.strip().splitlines()[0]
    en_title = re.sub(r'[#*`]+', '', en_title).strip()

    prompt = (
        f"{bg_base}\n"
        f"Background color and atmosphere: {theme_desc}\n\n"
        f"{_IMAGEFX_NO_PERSON}\n\n"
        f'Place one large "AIVice" watermark in the empty area, opacity 8–12%.\n\n'
        f'Add the text "{en_title}" in white or soft white, '
        f"blending naturally with the background."
    )

    print(f"[imagefx] 背景:{bg_label} / テーマ:{theme_desc[:50]}")
    print(f"[imagefx] タイトル(英): {en_title}")
    return prompt
