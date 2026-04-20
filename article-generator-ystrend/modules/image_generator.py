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
            if "402" in err:
                raise RuntimeError(f"FLUX画像生成失敗（クレジット不足）: {e}") from e
            elif "loading" in err.lower() or "503" in err:
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
# イラストスタイル定義
# ─────────────────────────────────────────────

# STYLE_A: フラットデザイン（信頼感・MONETIZE向け）
_STYLE_A = {
    "label": "A-flat",
    "haiku_style": (
        "Style: flat design illustration, clean and professional, "
        "soft pastel colors, minimal geometric icons. "
        "Focus on symbols representing the topic: coins, charts, checkmarks, "
        "calendars, documents, arrows, stars, speech bubbles, lightbulbs, magnifying glass. "
        "Absolutely NO laptop, NO computer, NO monitor, NO smartphone, NO device screens."
    ),
    "haiku_examples": (
        "'flat design icons of coins, upward chart and checkmarks, soft mint and cream pastel tones, minimal professional style' "
        "'flat illustration of calendar, documents and star icons, soft lavender and peach gradient, clean business style'"
    ),
    "flux_suffix": (
        "flat design illustration, pastel colors, soft gradient background, "
        "clean professional style, minimal geometric icons, "
        "no laptop, no computer, no monitor, no phone, no screen, no device, "
        "no people, no hands, no face, no human, no text, no watermark, "
        "high quality digital art"
    ),
}

# STYLE_B: デフォルメキャラ（親しみやすさ・FUTURE向け）
_STYLE_B = {
    "label": "B-chibi",
    "haiku_style": (
        "Style: cute chibi illustration, kawaii style, soft pastel colors, "
        "adorable round shapes, simple background. "
        "Focus on cute animal or object characters representing the topic "
        "(bunny, bear, cat, penguin, chick — each holding or surrounded by topic-related items). "
        "Absolutely NO laptop, NO computer, NO monitor, NO smartphone, NO device screens."
    ),
    "haiku_examples": (
        "'cute chibi bear holding coins and upward arrow, soft pink and mint pastel tones, kawaii minimal style' "
        "'adorable round penguin with speech bubble and stars, soft lavender gradient, kawaii illustration'"
    ),
    "flux_suffix": (
        "cute chibi illustration, kawaii style, pastel colors, "
        "adorable rounded shapes, simple pastel background, "
        "no laptop, no computer, no monitor, no phone, no screen, no device, "
        "no people, no hands, no human face, no text, no watermark, "
        "high quality digital art"
    ),
}

# STYLE_C: アイコン・オブジェクト系（LONGTAIL ランダム選択肢の一つ）
_STYLE_C = {
    "label": "C-icon",
    "haiku_style": (
        "Style: flat icon design, colorful objects on white or very light background, "
        "clean minimal line icons, modern and simple. "
        "Focus on 3-5 distinct icons representing the topic: documents, magnifying glass, "
        "lightbulb, trophy, shield, leaf, clock, calendar, puzzle piece, graph bars. "
        "Absolutely NO laptop, NO computer, NO monitor, NO smartphone, NO device screens."
    ),
    "haiku_examples": (
        "'minimal flat icons of trophy, lightbulb and upward arrow, colorful on white background, clean icon design' "
        "'flat icon set of magnifying glass, document and shield, soft color fills, modern minimal style'"
    ),
    "flux_suffix": (
        "flat icon design, colorful objects, white or very light background, "
        "clean minimal style, distinct icon shapes, "
        "no laptop, no computer, no monitor, no phone, no screen, no device, "
        "no people, no hands, no face, no human, no text, no watermark, "
        "high quality digital art"
    ),
}

_LONGTAIL_STYLES = [_STYLE_A, _STYLE_B, _STYLE_C]


def _select_style(article_type: str) -> dict:
    """
    記事タイプに応じてスタイルを選択する。
      MONETIZE → A（フラットデザイン・信頼感）
      FUTURE   → B（デフォルメキャラ・親しみやすさ）
      LONGTAIL → A/B/C ランダム
      その他    → A/B/C ランダム
    """
    t = article_type.lower() if article_type else ""
    if "monetize" in t:
        return _STYLE_A
    if "future" in t or "trend" in t:
        return _STYLE_B
    # LONGTAIL / その他: ランダム
    return random.choice(_LONGTAIL_STYLES)


# ─────────────────────────────────────────────
# 公開API
# ─────────────────────────────────────────────

def _build_eyecatch_prompt(keyword: str, article_theme: str, style: dict) -> str:
    """
    キーワード・記事テーマからアイキャッチ用FLUXプロンプトをClaude Haikuで生成する。
    Haiku呼び出し失敗時はキーワードから直接フォールバックプロンプトを生成する。
    """
    topic = article_theme or keyword
    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    f"Create a short English image prompt (20-30 words) for a blog header illustration "
                    f"about: '{topic}'. "
                    f"{style['haiku_style']} "
                    "No people, no hands, no faces. "
                    "Avoid: robots, cyberpunk, neon colors, dark backgrounds, clutter, realistic photos. "
                    f"Examples: {style['haiku_examples']} "
                    "Output the prompt only."
                ),
            }],
        )
        raw = msg.content[0].text.strip().splitlines()[0]
        return re.sub(r'[#*`"\']+', '', raw).strip()
    except Exception as e:
        print(f"[image_generator] Haikuプロンプト生成失敗、フォールバック使用: {e}")
        safe_topic = re.sub(r'[^\w\s]', ' ', topic).strip()
        return f"cute flat design icons for {safe_topic}, pastel colors, minimal style, no laptop, no computer"


def generate_eyecatch_image(keyword: str, article_theme: str = "", article_type: str = "") -> bytes:
    """
    アイキャッチ画像を生成する（スタイルバリエーション対応・人物なし）。

    - スタイル選択: article_type に応じて A/B/C から選択
      MONETIZE→A(フラット), FUTURE→B(デフォルメ), LONGTAIL→ランダム
    - サイズ: 1216×832
    """
    style = _select_style(article_type)
    prompt = _build_eyecatch_prompt(keyword, article_theme, style)
    full_prompt = f"{prompt}, {style['flux_suffix']}"

    print(f"[image_generator] アイキャッチ生成 (スタイル{style['label']}): {prompt[:60]}...")
    return _call_flux(full_prompt, W_EYECATCH, H_EYECATCH)


def _build_h2_image_prompt(h2_title: str, keyword: str, style: dict) -> str:
    """
    H2タイトル・キーワードから記事テーマに合ったFLUXプロンプトをClaude Haikuで生成する。
    Haiku呼び出し失敗時はフォールバックプロンプトを使用する。
    """
    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    f"Create a short English image prompt (20-30 words) for a blog section illustration "
                    f"about: keyword='{keyword}', section='{h2_title}'. "
                    f"{style['haiku_style']} "
                    "No people, no hands, no faces. "
                    "Avoid: robots, cyberpunk, neon colors, dark backgrounds, clutter, realistic photos. "
                    f"Examples: {style['haiku_examples']} "
                    "Output the prompt only."
                ),
            }],
        )
        raw = msg.content[0].text.strip().splitlines()[0]
        return re.sub(r'[#*`"\']+', '', raw).strip()
    except Exception as e:
        print(f"[image_generator] H2プロンプト生成失敗、フォールバック使用: {e}")
        topic = h2_title or keyword
        safe_topic = re.sub(r'[^\w\s]', ' ', topic).strip()
        return f"cute flat design icons for {safe_topic}, pastel colors, minimal style, no laptop, no computer"


def generate_h2_image(h2_title: str, keyword: str = "", article_type: str = "") -> bytes:
    """
    H2記事内画像を生成する（スタイルバリエーション対応・人物なし）。

    - スタイル: アイキャッチと同じ article_type に基づくスタイルを使用
    - サイズ: 1216×832
    """
    style = _select_style(article_type)
    topic = h2_title or keyword
    prompt = _build_h2_image_prompt(topic, keyword, style)
    full_prompt = f"{prompt}, {style['flux_suffix']}"

    print(f"[image_generator] H2画像生成 (スタイル{style['label']}): {prompt[:60]}...")
    return _call_flux(full_prompt, W_EYECATCH, H_EYECATCH)


def generate_image_for_article(keyword: str, article_theme: str = "", article_type: str = "") -> bytes:
    """後方互換エイリアス（アイキャッチ生成）。"""
    return generate_eyecatch_image(keyword, article_theme, article_type)


# ─────────────────────────────────────────────
# ImageFX プロンプト生成
# ─────────────────────────────────────────────

_IMAGEFX_NO_PERSON = (
    "no people, no human, no woman, no man, no face, no silhouette, "
    "no body parts, no shadows of people, no reflections of people, "
    "purely abstract background only"
)

_IMAGEFX_BG_A = (
    "Clean modern workspace background: minimalist desk with soft natural light, "
    "warm beige and white tones, elegant and uncluttered, lifestyle photography aesthetic."
)

_IMAGEFX_BG_B = (
    "Soft pastel gradient background: gentle blush pink, cream and ivory tones, "
    "warm neutral atmosphere, feminine and sophisticated, airy and bright."
)

_IMAGEFX_BG_C = (
    "Elegant lifestyle background: soft morning light with warm neutrals, "
    "gentle depth-of-field effect, clean and airy ambiance, muted earth tones."
)

_IMAGEFX_BG_OPTIONS = [
    ("A", _IMAGEFX_BG_A),
    ("B", _IMAGEFX_BG_B),
    ("C", _IMAGEFX_BG_C),
]


def generate_imagefx_prompt(keyword: str, title: str, article_type: str = "") -> str:
    """
    ImageFX 用アイキャッチプロンプトを生成する（人物なし・テーマ反映・スタイルバリエーション対応）。

    - 人物: 完全禁止
    - ビジュアル: article_type に応じたスタイル（A:フラット/B:デフォルメ/C:アイコン）
    - 背景スタイル: A/B/C からランダム選択
    - ウォーターマーク・タイトルテキスト: 固定ルールで追記
    - ※APIコールなし: キーワードから静的にプロンプトを生成（コスト削減）

    Returns:
        完成した ImageFX プロンプト文字列
    """
    style = _select_style(article_type)
    bg_label, bg_base = random.choice(_IMAGEFX_BG_OPTIONS)

    # テーマ: キーワードから静的生成（APIコール不要）
    safe_kw = re.sub(r'[^\w\s\-]', ' ', keyword).strip()
    theme_desc = (
        f"flat design icons and symbols related to {safe_kw}, "
        f"minimal illustration, soft pastel colors, no people, no devices"
    )

    # タイトル: 英数字のみ抽出（APIコール不要）
    en_title = re.sub(r'[^\w\s\-]', ' ', keyword)[:30].strip() or "Blog Article"

    prompt = (
        f"{theme_desc}\n"
        f"{bg_base}\n\n"
        f"{_IMAGEFX_NO_PERSON}\n"
        "modern minimal style, elegant design, soft pastel tones, warm neutral colors, "
        "clean and sophisticated, no text, no watermark, high quality\n\n"
        f'Place one large "AIVice" watermark in the empty area, opacity 8–12%.\n\n'
        f'Add the text "{en_title}" in white or soft white, '
        f"blending naturally with the background."
    )

    print(f"[imagefx] 背景:{bg_label} / ビジュアル:{theme_desc[:50]}")
    print(f"[imagefx] タイトル(英): {en_title}")
    return prompt
