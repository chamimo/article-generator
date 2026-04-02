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
    "A single photorealistic Japanese woman in her 20s, clean office lady style. "
    "Dark black or deep dark brown hair, straight and neat. "
    "Natural minimal makeup, clear porcelain skin, gentle calm smile. "
    "Wearing a simple white or light-colored blouse. "
    "Positioned clearly on the RIGHT side of the image, leaving the LEFT side open for text overlay. "
    "No smartphone. No props. No shadows. No reflections. "
    "Photorealistic only. No anime. Ultra high quality."
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

def _build_eyecatch_prompt(keyword: str, article_theme: str) -> str:
    """
    キーワード・記事テーマから人物なしのアイキャッチ用FLUXプロンプトをClaude Haikuで生成する。
    フラットイラスト・モダンデザイン風、テキストなし。
    """
    topic = article_theme or keyword
    msg = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{
            "role": "user",
            "content": (
                f"Create a short English image prompt (20-30 words) for a blog header illustration "
                f"about: '{topic}'. "
                "Style: flat illustration, modern tech design, vibrant colors, wide horizontal format. "
                "Focus on visual objects/icons representing the topic (no people, no text, no watermark). "
                "Examples: "
                "'smartphone with colorful sound wave icons and AI nodes, flat illustration, blue and white color palette' "
                "'microphone with flowing text lines and digital circuit patterns, modern flat design, teal and purple' "
                "Output the prompt only."
            ),
        }],
    )
    raw = msg.content[0].text.strip().splitlines()[0]
    return re.sub(r'[#*`"\']+', '', raw).strip()


def generate_eyecatch_image(keyword: str, article_theme: str = "") -> bytes:
    """
    アイキャッチ画像を生成する（人物なし・テーマ反映フラットイラスト）。

    - プロンプト: キーワード・記事テーマからClaude Haikuで自動生成
    - スタイル: フラットイラスト・モダンデザイン風
    - サイズ: 1216×832
    """
    prompt = _build_eyecatch_prompt(keyword, article_theme)
    suffix = (
        "no people, no human, no face, no silhouette, "
        "no text, no watermark, high quality digital art, professional blog header"
    )
    full_prompt = f"{prompt}, {suffix}"

    print(f"[image_generator] アイキャッチ生成 (人物なし): {prompt[:60]}...")
    return _call_flux(full_prompt, W_EYECATCH, H_EYECATCH)


def _build_h2_image_prompt(h2_title: str, keyword: str) -> str:
    """
    H2タイトル・キーワードから記事テーマに合ったFLUXプロンプトをClaude Haikuで生成する。
    フラットイラスト・モダンデザイン風、人物なし・テキストなし。
    """
    msg = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{
            "role": "user",
            "content": (
                f"Create a short English image prompt (20-30 words) for a blog illustration "
                f"about: keyword='{keyword}', section='{h2_title}'. "
                "Style: flat illustration, modern design, vibrant colors, no people, no text, no watermark. "
                "Focus on visual objects/icons that represent the topic. "
                "Examples: 'smartphone with sound wave icons and microphone, flat illustration style, modern tech design, blue and white color palette' "
                "Output the prompt only."
            ),
        }],
    )
    raw = msg.content[0].text.strip().splitlines()[0]
    return re.sub(r'[#*`"\']+', '', raw).strip()


def generate_h2_image(h2_title: str, keyword: str = "") -> bytes:
    """
    H2記事内画像を生成する（人物なし・テーマ反映フラットイラスト）。

    - プロンプト: H2タイトル・キーワードからClaude Haikuで自動生成
    - スタイル: フラットイラスト・モダンデザイン風
    - サイズ: 1216×832
    """
    topic = h2_title or keyword
    prompt = _build_h2_image_prompt(topic, keyword)
    suffix = (
        "flat illustration style, modern design, no people, no human, no face, "
        "no text, no watermark, high quality digital art, clean background"
    )
    full_prompt = f"{prompt}, {suffix}"

    print(f"[image_generator] H2画像生成 (テーマ反映): {prompt[:60]}...")
    return _call_flux(full_prompt, W_EYECATCH, H_EYECATCH)


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
    ImageFX 用アイキャッチプロンプトを生成する（人物なし・テーマ反映フラットイラスト）。

    - 人物: 完全禁止
    - ビジュアル: 記事テーマに合ったフラットイラスト・モダンデザイン
    - 背景スタイル: A/B/C からランダム選択
    - ウォーターマーク・タイトルテキスト: 固定ルールで追記

    Returns:
        完成した ImageFX プロンプト文字列
    """
    bg_label, bg_base = random.choice(_IMAGEFX_BG_OPTIONS)

    # テーマに合ったビジュアル説明をClaude Haikuで生成
    theme_resp = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": (
                f"For a blog header image about '{keyword}' titled '{title}', "
                "describe specific visual objects/icons (15-20 words) for a flat illustration style. "
                "No people. Focus on objects, icons, devices, and abstract elements. "
                "No explanation. Only the description.\n"
                "Examples: "
                "'smartphone with sound wave icons and microphone, AI nodes, teal and blue color scheme' "
                "'chat bubbles with AI circuit patterns, glowing nodes and digital grid, dark blue and purple'"
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
        f"{theme_desc}\n"
        f"{bg_base}\n\n"
        f"{_IMAGEFX_NO_PERSON}\n"
        "flat illustration style, modern design, no text, no watermark, high quality\n\n"
        f'Place one large "AIVice" watermark in the empty area, opacity 8–12%.\n\n'
        f'Add the text "{en_title}" in white or soft white, '
        f"blending naturally with the background."
    )

    print(f"[imagefx] 背景:{bg_label} / ビジュアル:{theme_desc[:50]}")
    print(f"[imagefx] タイトル(英): {en_title}")
    return prompt
