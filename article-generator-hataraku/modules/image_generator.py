"""
画像生成モジュール

- generate_eyecatch_image()  : アイキャッチ（横長・ブログ別モデル対応）
- generate_h2_image()        : H2記事内画像（人物なし・ブログ別モデル対応）

対応モデル:
  - gpt-image-2               : OpenAI Images API
  - black-forest-labs/FLUX.1-* : Hugging Face Inference API（デフォルト）

生成画像のローカル保存:
  output/images/{yyyymmdd_HHMMSS}_{type}_{model_short}.jpg
  （デバッグ・品質確認用。常に保存される）
"""
from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import random
import re
import time
from datetime import datetime
import anthropic
from huggingface_hub import InferenceClient
from modules import wp_context

from config import HUGGINGFACE_API_KEY, ANTHROPIC_API_KEY

# ローカル保存先（スクリプトルートの output/images/）
_OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output" / "images"

_DEFAULT_HF_MODEL = "black-forest-labs/FLUX.1-schnell"
# gpt-image-2 の横長サイズ。WordPress側のワイド(16:9)クロップに合わせる。
_GPT_IMAGE_SIZE   = "1536x864"

# FLUX 向けキャンバスサイズ（既存の値を維持）
W_EYECATCH = 1216
H_EYECATCH = 832

# 後方互換エイリアス
HF_MODEL = _DEFAULT_HF_MODEL

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
# テーマ別シーンテンプレート（variant "c" 専用）
# キーワード → テーマ → シーン背景プロンプト
# ─────────────────────────────────────────────

_SCENE_THEME_KEYWORDS: dict[str, list[str]] = {
    "income":       ["副業", "稼ぐ", "収入", "月収", "副収入", "収益", "フリーランス", "マネタイズ", "稼げ", "在宅ワーク"],
    "beginner":     ["初心者", "入門", "使い方", "始め方", "基礎", "やり方", "わかる", "登録", "設定", "最初"],
    "productivity": ["活用", "効率", "業務", "自動化", "仕事", "プロンプト", "業務効率", "ビジネス", "時短", "改善"],
    "discover":     ["ChatGPT", "Claude", "Gemini", "API", "ノーコード", "Midjourney", "ツール", "アプリ", "GPT", "生成AI"],
    "learning":     ["学習", "スキル", "講座", "資格", "学ぶ", "勉強", "習得", "Udemy", "教育"],
}

# テーマ × 2バリアント。「左側を空ける」制約なし — PILが自前で読取領域を作る
_SCENE_TEMPLATES: dict[str, list[str]] = {
    "income": [
        # v0: 真上からフラットレイ（人物なし）
        "Top-down aerial flat-lay of a productive desk, Japanese lifestyle blog thumbnail, 16:9. "
        "Items artfully arranged: open laptop with soft glow, smartphone, coffee cup, small succulent plant, "
        "notebook with pen, a few coins or a card. Clean wooden or marble desk surface. "
        "Natural daylight from above. Warm aesthetic color story fills the ENTIRE frame. "
        "COLORS: warm cream, amber, sage green, off-white. Rich composition edge-to-edge. "
        "NO person visible. NO text, NO numbers, NO labels anywhere. Japanese lifestyle photography style.",

        # v1: コワーキングスペース・人物中央寄り
        "Vibrant modern co-working space, Japanese lifestyle blog thumbnail, 16:9. "
        "Young professional (gender-neutral, back or 3/4 view, NO face) seated CENTER-FRAME at a shared desk. "
        "Open bright co-working space extends behind them — other softly-blurred people, plants, large windows. "
        "Warm afternoon sunlight fills the whole scene. Laptop open. "
        "Rich full-frame composition with interesting detail throughout. "
        "COLORS: warm white, natural wood, golden afternoon light. "
        "NO text, NO numbers, NO UI labels. Cinematic wide-angle photography style.",
    ],
    "beginner": [
        # v0: 手元クローズアップ
        "Close-up of hands lightly resting on a laptop keyboard, 16:9 blog thumbnail. "
        "Hands positioned CENTER-FRAME, slightly above center. Warm morning light falling across hands and keys. "
        "Shallow depth of field — blurred background shows: coffee cup, small plant, open notebook. "
        "Rich tactile detail: keyboard texture, soft skin tones, warm light. "
        "COLORS: warm cream, soft gold, pale morning blue. "
        "NO face, NO head, NO text, NO numbers, NO labels. Warm cinematic close-up photography.",

        # v1: 勉強コーナー・人物左寄り
        "Cozy personal study corner, Japanese lifestyle blog thumbnail, 16:9. "
        "Person (side silhouette or torso only, NO face) occupies LEFT 40% of frame at a warm desk. "
        "RIGHT side richly detailed: warm bokeh bookshelf, fairy lights, house plant, afternoon curtain light. "
        "The entire frame is warm and lived-in. No empty or plain areas. "
        "COLORS: amber, cream, soft teal. "
        "NO text, NO numbers, NO labels. Painterly warm photography style.",
    ],
    "productivity": [
        # v0: ダークデスク・デュアルモニター・人物中央後方
        "Dark ambient tech workspace, dramatic Japanese blog thumbnail, 16:9. "
        "Person (back view, NO face) in CENTER-RIGHT, facing two glowing monitors showing abstract blue UI. "
        "Dark room with dramatic rim lighting on shoulders. Minimal dark desk. "
        "Scene is dramatically lit — interesting shadows and highlights fill the whole frame. "
        "COLORS: deep navy (#0A0E2A), electric blue (#4169E1), warm amber accent lamp far corner. "
        "NO text, NO numbers, NO labels. Dark cinematic photography, rich throughout.",

        # v1: 抽象データビジュアライゼーション（人物小さい）
        "Abstract futuristic data visualization, Japanese blog thumbnail, 16:9. "
        "Glowing network nodes and flowing lines of light fill the entire frame. "
        "A small human silhouette stands in lower-center reaching toward the grid — tiny relative to the data landscape. "
        "Richly detailed digital art fills every corner. "
        "COLORS: deep space blue (#050A20), cyan (#00E5FF), electric blue, warm gold accents. "
        "NO text, NO numbers, NO labels. Digital art style, complex and detailed.",
    ],
    "discover": [
        # v0: ドラマチックな夜・画面の光
        "Dramatic night discovery scene, Japanese blog thumbnail, 16:9. "
        "Person (back view, NO face) RIGHT 60%, seated very close to a brightly glowing screen in a dark room. "
        "Screen light illuminates the person with cool blue/white. Dark atmospheric room fills the rest. "
        "A warm amber desk lamp glows softly far-LEFT, creating warm-cool contrast across the whole frame. "
        "Rich cinematic lighting throughout — nothing is simply blank. "
        "COLORS: deep dark (#0A0A15), electric blue screen, warm amber lamp. "
        "NO text, NO numbers, NO labels. Cinematic noir style.",

        # v1: バイブラント抽象テック（人物なし）
        "Vibrant abstract digital tech art, Japanese blog thumbnail, 16:9. "
        "Swirling colorful abstract shapes suggesting AI/data: flowing lines, geometric shapes, light particles. "
        "NO person. Bold colors fill the entire frame — visually rich in every corner. "
        "COLORS: electric blue (#4169E1), hot coral (#FF5A78), golden (#FFD700), deep purple (#5B21B6). "
        "Bold, energetic, modern. NO text, NO numbers, NO labels. Digital abstract art.",
    ],
    "learning": [
        # v0: 本・文具・フラットレイ（人物なし）
        "Aesthetic book and study objects flat-lay, Japanese blog thumbnail, 16:9. "
        "Artfully arranged from above: stack of colorful books, open notebook with pen, coffee cup, "
        "reading glasses, small plant, sticky notes, highlighter. Warm wooden surface. "
        "Afternoon light creates gentle long shadows. Rich composition fills the entire frame. "
        "COLORS: warm cream, earth tones, pops of coral and teal. "
        "NO person. NO text, NO numbers, NO labels. Lifestyle photography, edge-to-edge composition.",

        # v1: カフェ・ヘッドフォン・人物中央
        "Person with headphones studying at a modern cafe, Japanese blog thumbnail, 16:9. "
        "Person visible from shoulders up (back or 3/4 angle, NO face) positioned CENTER of frame, "
        "focused on laptop. Warm modern cafe surrounds them: soft bokeh patrons, plants, wooden furniture. "
        "Entire frame is warm, rich, and interesting — no blank areas. "
        "COLORS: warm amber light, cream, soft teal/green. "
        "NO text, NO numbers, NO labels. Warm cinematic style.",
    ],
    "default": [
        "Warm aesthetic Japanese lifestyle blog thumbnail background, 16:9. "
        "Abstract soft bokeh light effects: warm orbs of light, gentle geometric shapes, soft gradients. "
        "Rich, interesting, full-frame composition with NO blank areas. "
        "COLORS: warm cream (#FFF8F0), sky blue (#5BA8E5), soft coral (#FF8A70), golden amber. "
        "NO person required. NO text, NO numbers, NO labels. Lifestyle photography aesthetic.",
    ],
}


def _detect_scene_theme(keyword: str) -> str:
    """キーワードからシーンテーマを判定する（完全一致 → デフォルト）。"""
    for theme, kws in _SCENE_THEME_KEYWORDS.items():
        for kw in kws:
            if kw in keyword:
                return theme
    return "default"


def _get_scene_template(keyword: str) -> str:
    """テーマに応じたシーン背景プロンプトをランダムに選択して返す。"""
    theme     = _detect_scene_theme(keyword)
    variants  = _SCENE_TEMPLATES.get(theme, _SCENE_TEMPLATES["default"])
    selected  = random.choice(variants)
    print(f"[IMAGE] scene theme: {theme}  ({len(variants)} variants available)")
    return selected


_JP_TO_EN: dict[str, str] = {
    "シンプル": "simple", "やさしい": "gentle", "教育": "education",
    "フラット": "flat", "インフォグラフィック": "infographic", "パステル": "pastel",
    "テック": "tech", "デザイン": "design", "スタイル": "style",
    "ブルー": "blue", "グリーン": "green", "ホワイト": "white",
    "ラベンダー": "lavender", "ミント": "mint", "オレンジ": "orange",
    "PC": "PC", "タブレット": "tablet", "ノート": "notebook",
    "チェックリスト": "checklist", "グラフ": "chart", "アイコン": "icon",
    "中心": "focused", "系": "", "・": " ", "　": " ",
}


def _jp_to_en(text: str) -> str:
    """日本語キーワードを英語に置換し、残った日本語文字を除去する。"""
    for jp, en in _JP_TO_EN.items():
        # 英語単語の置換時はスペースで区切る
        replacement = f" {en} " if en else " "
        text = text.replace(jp, replacement)
    # 残った日本語（ひらがな・カタカナ・漢字）を除去
    text = re.sub(r'[　-鿿]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _get_style_hint() -> str:
    """
    wp_contextのimage_style設定からFLUXプロンプト用スタイル指示文字列を生成する。
    設定がない場合はブログのgenreからスタイルを推測する。
    """
    cfg = wp_context.get_image_style()
    if not cfg:
        # blog_metaのgenreからスタイル推測
        meta = wp_context.get_blog_meta()
        genre = meta.get("genre_detail") or meta.get("genre", "")
        if genre:
            genre_en = _jp_to_en(genre)[:60]
            return f"flat design illustration, pastel colors, soft gradient, topic: {genre_en}"
        return "flat design illustration, pastel colors, soft gradient background"

    parts = []

    # スタイル
    if cfg.get("style"):
        parts.append(_jp_to_en(cfg["style"])[:80])

    # メインカラー（カラーコードを抽出）
    color_codes = re.findall(r'#[0-9A-Fa-f]{6}', " ".join(filter(None, [
        cfg.get("color_main", ""), cfg.get("color_sub", "")
    ])))
    if color_codes:
        parts.append(f"colors: {' '.join(color_codes[:4])}")
    elif cfg.get("color_main"):
        parts.append(f"main color: {_jp_to_en(cfg['color_main'])[:40]}")

    # tone（最初の文のみ・数字除去）
    if cfg.get("tone"):
        tone_raw = cfg["tone"].split("。")[0]
        tone_en = _jp_to_en(tone_raw)
        tone_en = re.sub(r'\b\d+\b', '', tone_en).strip()
        if tone_en:
            parts.append(tone_en[:60])

    return ", ".join(p for p in parts if p) or "flat design illustration, pastel colors"


def _get_motifs_hint() -> str:
    """
    image_styleのmotifsをプロンプト用英語句で返す。
    未設定の場合は空文字を返す（Claudeにトピックから推測させる）。
    """
    cfg = wp_context.get_image_style()
    motifs = cfg.get("motifs", [])
    if not motifs:
        return ""
    return ", ".join(_jp_to_en(m) for m in motifs[:8])


# ─────────────────────────────────────────────
# 内部: FLUX 呼び出し
# ─────────────────────────────────────────────

def _call_flux(prompt: str, width: int, height: int,
               model: str = _DEFAULT_HF_MODEL) -> bytes:
    """
    Hugging Face Inference API で画像を生成し JPEG バイト列を返す。
    最大3回リトライ。model を省略すると FLUX.1-schnell を使用。
    """
    if not HUGGINGFACE_API_KEY:
        raise RuntimeError("HUGGINGFACE_API_KEY が設定されていません")

    client = InferenceClient(token=HUGGINGFACE_API_KEY)

    for attempt in range(3):
        try:
            result = client.text_to_image(
                prompt=prompt,
                model=model,
                width=width,
                height=height,
            )
            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=90)
            img_bytes = buf.getvalue()
            print(f"[image_generator] 完了 ({len(img_bytes)//1024}KB, {width}x{height}, model={model})")
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


def _call_openai_image(prompt: str) -> bytes:
    """
    gpt-image-2 で画像を生成し JPEG バイト列を返す。
    サイズは 1536x1024（横長）、quality は medium。
    レスポンスは b64_json → URL の順でフォールバック。
    """
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY
    except ImportError as e:
        raise RuntimeError(f"openai パッケージが未インストールです（pip install openai）: {e}") from e

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY が設定されていません（.env を確認してください）")

    import requests as _requests

    client = OpenAI(api_key=OPENAI_API_KEY)
    print(f"[image_generator] OpenAI gpt-image-2 生成開始 (size={_GPT_IMAGE_SIZE}, quality=medium)")

    resp = client.images.generate(
        model="gpt-image-2",
        prompt=prompt,
        n=1,
        size=_GPT_IMAGE_SIZE,
        quality="medium",
    )

    img_data = resp.data[0]
    if img_data.b64_json:
        img_bytes = base64.b64decode(img_data.b64_json)
    elif img_data.url:
        r = _requests.get(img_data.url, timeout=30)
        r.raise_for_status()
        img_bytes = r.content
    else:
        raise RuntimeError("gpt-image-2: 画像データが返されませんでした")

    print(f"[image_generator] OpenAI gpt-image-2 完了 ({len(img_bytes)//1024}KB)")
    return img_bytes


def _call_model(model: str, prompt: str, width: int, height: int) -> bytes:
    """
    モデル名に応じて適切なAPIを呼び出す。

    - "gpt-image-2"            → OpenAI Images API
    - それ以外（FLUX 系など）  → Hugging Face Inference API
    """
    if model == "gpt-image-2":
        return _call_openai_image(prompt)
    return _call_flux(prompt, width, height, model=model or _DEFAULT_HF_MODEL)


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

def _build_eyecatch_prompt(keyword: str, article_theme: str, variant: str = "a") -> tuple[str, bool]:
    """
    アイキャッチ用プロンプトを生成する。

    優先順:
      0. variant "c" → キーワードテーマ別シーンテンプレート（動的・AIVice専用）
      1. image_style.eyecatch_templates[variant]（A/Bバリアント対応テンプレート）
      2. image_style.eyecatch_template（旧形式・フォールバック）
      3. Haiku 動的生成（テンプレートなし既存ブログ用）

    Returns:
      (prompt, is_template): is_template=True のときは suffix を付けない
    """
    cfg   = wp_context.get_image_style()
    topic = article_theme or keyword

    # ── 0. variant "c" → テーマ別シーンテンプレート ──────────
    if variant == "c":
        prompt = _get_scene_template(keyword)
        return prompt, True

    # ── 1. バリアント対応テンプレート ────────────────────────
    templates = cfg.get("eyecatch_templates", {})
    template  = templates.get(variant) or cfg.get("eyecatch_template", "")
    if template:
        topic_en = _theme_hint(topic) if topic else "AI technology"
        prompt   = template.format(topic=topic_en)
        print(f"[IMAGE] eyecatch topic_en: {topic_en}")
        return prompt, True

    # ── 2. テンプレートなし → Haiku で生成（既存ブログ用フォールバック）──
    style_hint  = _get_style_hint()
    motifs_hint = _get_motifs_hint()
    motifs_line = (
        f"Focus on simple icons and objects related to the topic: {motifs_hint}."
        if motifs_hint else
        "Focus on icons and objects that visually represent the article topic. "
        "Do NOT use laptops or generic business icons unless the topic is about business/tech."
    )
    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    f"Create a short English image prompt (20-30 words) for a blog header illustration "
                    f"about: '{topic}'. "
                    f"Style: {style_hint}. "
                    f"{motifs_line} No people, no hands, no faces. "
                    "Avoid: robots, cyberpunk, neon colors, dark backgrounds, clutter, realistic photos. "
                    "Output the prompt only."
                ),
            }],
        )
        raw = msg.content[0].text.strip().splitlines()[0]
        return re.sub(r'[#*`"\']+', '', raw).strip(), False
    except Exception as e:
        print(f"[image_generator] Haikuプロンプト生成失敗、フォールバック使用: {e}")
        safe_topic = re.sub(r'[^\w\s]', ' ', topic).strip()
        return f"flat design icons for {safe_topic}, {style_hint}", False


# ─────────────────────────────────────────────
# PIL テキストオーバーレイ（variant "c" 用）
# ─────────────────────────────────────────────

_FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",   # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJKjp-Bold.otf",
]
_FONT_REG_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",   # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _find_font(candidates: list[str]):
    """候補リストから存在する最初のフォントパスを返す（なければ None）。"""
    from PIL import ImageFont
    for path in candidates:
        if pathlib.Path(path).exists():
            try:
                ImageFont.truetype(path, 10)
                return path
            except Exception:
                continue
    return None


def _generate_overlay_texts(keyword: str) -> dict:
    """Haiku でサムネイル用オーバーレイテキストを生成する（6フィールド）。"""
    import json as _json
    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=280,
            messages=[{
                "role": "user",
                "content": (
                    f"YouTubeサムネイル・ブログサムネイル用テキストをJSONで出力してください。\n"
                    f"キーワード: {keyword}\n\n"
                    f"出力形式（JSONのみ・説明不要）:\n"
                    f'{{"strip_label": "帯ラベル（3〜6文字・例: 初心者OK）", '
                    f'"pre_title": "プレタイトル（6〜10文字・感嘆系・例: 5分でわかる！）", '
                    f'"main_word": "核心キーワード（3〜6文字・一番伝えたいこと・例: ChatGPT）", '
                    f'"accent_word": "補足（4〜9文字・体言止め・例: 使い方講座）", '
                    f'"supplement": "補足メッセージ（16〜24文字・例: はじめてでも迷わない基本を解説！）", '
                    f'"badge": "丸バッジ（2〜5文字・例: 無料）"}}\n\n'
                    f"ルール: 日本語のみ。main_wordは最重要キーワードの核心（短く強く）。"
                    f"読者が「自分のことだ」と思える言葉選び。参考画像スタイル: ChatGPT使い方講座。"
                ),
            }],
        )
        raw   = msg.content[0].text.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        return _sanitize_overlay_texts(_json.loads(raw[start:end]))
    except Exception as e:
        print(f"[IMAGE] overlay text生成失敗、フォールバック使用: {e}")
        return _sanitize_overlay_texts({
            "strip_label": "初心者向け",
            "pre_title":   "5分でわかる！",
            "main_word":   keyword[:5],
            "accent_word": "使い方ガイド",
            "supplement":  "はじめてでも迷わない基本と活用法",
            "badge":       "無料",
        })



def _sanitize_overlay_phrase(value: str) -> str:
    """アイキャッチで避けたい強い/冗長な表現を置き換える。"""
    text = str(value or "")
    replacements = {
        "完全活用ガイド": "活用の基本",
        "完全ガイド": "やさしく解説",
        "完全攻略": "やさしく解説",
        "完全解説": "基本解説",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()


def _sanitize_overlay_texts(texts: dict) -> dict:
    if not isinstance(texts, dict):
        return texts
    for key in ("strip_label", "pre_title", "main_word", "accent_word", "supplement", "badge"):
        if key in texts:
            texts[key] = _sanitize_overlay_phrase(texts[key])
    return texts


# ─── アイキャッチ多様化ランダムプール ──────────────────────────────────────
import random as _rand_mod

_RAND_COMPOSITIONS = [
    "overhead flat-lay top-down view, objects beautifully arranged on a surface",
    "oblique 45-degree angle, dynamic perspective, depth and dimension",
    "tight close-up macro, single subject fills the frame, shallow depth of field",
    "wide establishing shot, subject small, generous breathing space all around",
    "strong asymmetric composition, subject pushed far to one edge",
    "bold negative space dominant, subject occupies less than a third of frame",
    "window as main subject, light flooding through, interior partially visible",
    "no desk no table, outdoor environment, nature or street context",
    "rich layered depth, foreground elements, midground subject, soft background",
    "looking-up low angle toward light source, airy and expansive",
]

_RAND_SCENES = [
    "quiet morning home desk, first light, ceramic mug",
    "bright midday room, open windows, clear and fresh atmosphere",
    "late afternoon golden hour, warm raking light, long soft shadows",
    "gentle rainy day indoors, window with soft rain droplets, cozy warmth",
    "independent cafe, espresso, background hum of people, warm wood",
    "Japanese tatami room, low wooden table, natural washi light",
    "living room sofa corner, blanket, small plant, relaxed afternoon",
    "balcony or small patio, potted plants, open sky, fresh air feel",
    "home study lined with books, quiet focus, reading lamp",
    "close-up moment of hand writing in an open notebook",
    "smartphone held lightly in hand, soft screen glow",
    "laptop screen showing a glowing chat interface, hands at keyboard",
    "walking path in a park or quiet street, thinking in motion",
]

_RAND_PERSONS = [
    "Japanese woman in her 20s, natural and fresh, casual outfit",
    "Japanese woman in her 30s, calm and elegant, relaxed posture",
    "Japanese man, casual and unhurried, thoughtful expression",
    "parent and small child together at a table, warm interaction",
    "person seen entirely from behind, back view, facing window or landscape",
    "side profile, face softly lit from one side, serene",
    "hands only close-up — no face at all, holding mug or phone or pen",
    "no people at all, still-life scene of objects only",
]

_RAND_TASTES = [
    "polished lifestyle magazine editorial, intentional and composed",
    "clean advertising campaign, aspirational and minimal",
    "personal note.com blog header, warm and approachable",
    "soft cinematic quality, shallow depth of field, film-like grain",
    "emotional indie photography, personal and atmospheric",
    "stark minimalist, extreme empty space, single element",
    "warm lived-in domestic, authentic textures, real imperfection",
    "optimistic near-future, clean lines, softly high-tech",
    "slightly urban modern city aesthetic, concrete and plants",
    "natural organic earthy, botanical, linen and clay tones",
]

_RAND_PALETTES = [
    "warm beige and cream, ivory and linen",
    "clean bright white and soft ivory",
    "muted sage green, natural white, light forest",
    "hazy sky blue, pale cream, morning mist",
    "warm terracotta orange, sandy earth, clay",
    "deep charcoal accent with warm off-white — high contrast",
    "cool silver-gray and clean white, minimal",
    "warm sunrise amber, soft peach, golden glow",
]

_RAND_LAYOUTS = [
    "editorial_left",  # 雑誌編集風：ラベル→ルール→大タイトル→細サブ
    "split_scale",     # 前半細字→後半極大（ジャンプ率最大）
    "giant_word",      # 1語を極大に（画面の20%）
    "vertical_accent", # 縦組みメイン＋横英字サブ
    "apple_clean",     # Apple広告風：1文・極大・余白
    "nordic_minimal",  # 北欧ミニマル：ルール＋大タイトル＋細英字
    "band_editorial",  # frosted帯＋タグ＋タイトル＋英字
    "zine_corner",     # ZINE風：コーナーに散らした自由配置
]
# ─────────────────────────────────────────────────────────────────────────────

def _generate_ad_concept(keyword: str, article_theme: str = "") -> dict:
    """
    Haiku が記事テーマからライフスタイル誌アートディレクションを生成する。
    text_placement / text_color / tag を含む2段階合成用コンセプトを返す。
    """
    import json as _json
    topic = article_theme or keyword
    try:
        # ── コード側でランダム要素を選び Haiku に「必ず使え」と指示 ──
        _comp      = _rand_mod.choice(_RAND_COMPOSITIONS)
        _scene_r   = _rand_mod.choice(_RAND_SCENES)
        _person_r  = _rand_mod.choice(_RAND_PERSONS)
        _taste_r   = _rand_mod.choice(_RAND_TASTES)
        _palette_r = _rand_mod.choice(_RAND_PALETTES)
        _place_r   = _rand_mod.choice(["bottom-left","lower-center","center-left","upper-left","bottom-right"])
        _layout_r  = _rand_mod.choice(_RAND_LAYOUTS)

        print(f"[IMAGE] rand comp  : {_comp[:50]}")
        print(f"[IMAGE] rand scene : {_scene_r}")
        print(f"[IMAGE] rand person: {_person_r}")
        print(f"[IMAGE] rand taste : {_taste_r}")
        print(f"[IMAGE] rand palette: {_palette_r}")
        print(f"[IMAGE] rand place : {_place_r}  layout: {_layout_r}")

        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=560,
            messages=[{
                "role": "user",
                "content": (
                    f"あなたはライフスタイル雑誌のアートディレクターです。\n"
                    f"記事テーマ: {topic}\n\n"
                    f"【必ずこの要素をそのまま使うこと — 変更禁止】\n"
                    f"・構図スタイル: {_comp}\n"
                    f"・シーン: {_scene_r}\n"
                    f"・人物: {_person_r}\n"
                    f"・テイスト: {_taste_r}\n"
                    f"・配色: {_palette_r}\n\n"
                    f"設計方針:\n"
                    f"・希望感・暮らし感・軽やかさ・前向きさ・やさしさ\n"
                    f"・「AIを使うと人生が少し整う」そんな空気感\n"
                    f"・余白を大切に\n"
                    f"・絶対NG: 孤独感・重い世界観・量産ブログ的コピー\n\n"
                    f"出力（JSONのみ・説明不要）:\n"
                    f'{{"world": "この記事の世界観を1文で",'
                    f'"emotion": "画像から漂う感情（やさしい希望 / 暮らしが整う感じ 等）",'
                    f'"scene": "指定の構図・シーン・人物を忠実に英語で記述",'
                    f'"light": "英語で光の質（指定シーンに合った自然な光）",'
                    f'"palette": "英語で色調（指定配色を詳細に）",'
                    f'"text_placement": "{_place_r}",'
                    f'"text_color": "dark または white（背景の明るさに合わせて）",'
                    f'"tag": "小タグ（3〜6文字・省略可）",'
                    f'"copy": "メインコピー（6〜14文字・詩的・自然体）",'
                    f'"subcopy": "サブコピー（8〜16文字・省略可）",'
                    f'"layout_style": "{_layout_r}"}}\n'
                ),
            }],
        )
        raw     = msg.content[0].text.strip()
        s       = raw.find("{")
        e       = raw.rfind("}") + 1
        concept = _json.loads(raw[s:e])
        # layout_style が返ってこない場合に補完
        if "layout_style" not in concept:
            concept["layout_style"] = _layout_r
        print(f"[IMAGE] world     : {concept.get('world')}")
        print(f"[IMAGE] emotion   : {concept.get('emotion')}")
        print(f"[IMAGE] placement : {concept.get('text_placement')}  color: {concept.get('text_color')}  layout: {concept.get('layout_style')}")
        print(f"[IMAGE] copy      : 「{concept.get('copy')}」 / sub: 「{concept.get('subcopy')}」")
        return concept
    except Exception as e_:
        print(f"[IMAGE] コンセプト生成失敗、フォールバック: {e_}")
        theme = _detect_scene_theme(keyword)
        _FB: dict[str, dict] = {
            "income":       {"world": "朝の光の中で、新しい働き方がひとつ増えた", "emotion": "やさしい期待感 / 暮らしが整う感じ", "scene": "bright morning desk notebook open coffee mug natural window light airy", "light": "warm soft morning sunlight through white linen curtain, bright and clear", "palette": "warm ivory cream linen soft beige natural wood", "text_placement": "bottom-left", "text_color": "dark", "tag": "副業", "copy": "暮らしに、余白を。", "subcopy": "AIと始める新しい朝"},
            "beginner":     {"world": "朝の窓辺でAIと向き合う、軽やかなはじまり", "emotion": "やさしい驚き / 朝の軽やかさ", "scene": "close-up hands around ceramic coffee mug open laptop bright morning window soft bokeh", "light": "soft diffused morning light through sheer white curtain, warm and bright", "palette": "warm cream ivory linen soft white beige", "text_placement": "lower-center", "text_color": "dark", "tag": "入門", "copy": "AIと、はじめる朝。", "subcopy": ""},
            "productivity": {"world": "午前中の自然光の中で、仕事がスッと整っていく", "emotion": "軽やかな充実感 / 暮らしが整う感じ", "scene": "bright airy home desk morning sunlight wooden surface notebook open plants", "light": "bright warm morning sunlight, soft and diffused, airy atmosphere", "palette": "warm ivory cream beige natural wood soft sage", "text_placement": "bottom-left", "text_color": "dark", "tag": "効率化", "copy": "仕事が、整う朝。", "subcopy": ""},
            "discover":     {"world": "明るい午前中に、新しいAIの使い方が見つかった", "emotion": "好奇心と発見の喜び / 軽やかさ", "scene": "bright desk morning light hands on laptop ceramic mug small plant natural window", "light": "warm bright morning sunlight through window, soft and natural", "palette": "soft cream ivory warm white beige natural wood", "text_placement": "center-left", "text_color": "dark", "tag": "発見", "copy": "出会う、新しいAI。", "subcopy": ""},
            "learning":     {"world": "午前の光の中で、知識が少しずつ積み重なる", "emotion": "学びの喜び・静かな充実", "scene": "overhead flat-lay open books notebook pen dried flower warm wooden surface bright morning", "light": "warm bright morning light from window, soft shadows, airy", "palette": "warm cream earth tone ivory soft sage natural linen", "text_placement": "lower-center", "text_color": "dark", "tag": "学習", "copy": "学ぶ、この時間。", "subcopy": ""},
        }
        return _FB.get(theme, {"world": "朝の窓辺でAIと向き合う、軽やかな一日のはじまり", "emotion": "やさしい希望 / 暮らしが整う感じ", "scene": "bright morning desk natural window light ceramic mug open laptop airy room", "light": "warm soft morning sunlight, bright and airy", "palette": "warm ivory cream linen beige", "text_placement": "lower-center", "text_color": "dark", "tag": "", "copy": "AIと、暮らす。", "subcopy": ""})


def _build_background_only_prompt(keyword: str, concept: dict) -> str:
    """
    テキストなし背景専用プロンプト。
    text_placement に応じてクリーンスペースをgpt-image-2に指示する。
    """
    scene     = concept.get("scene",     "cozy desk morning light")
    light     = concept.get("light",     "soft natural light")
    palette   = concept.get("palette",   "warm cream")
    placement = concept.get("text_placement", "lower-center")

    area_map = {
        "bottom-left":  "keep the lower-left quarter naturally calm and uncluttered — intentional open negative space",
        "lower-center": "keep the lower 32% relatively clear with gentle depth — breathing room for text overlay",
        "center-left":  "keep the left half with open airy negative space — text will live on the left",
        "upper-left":   "keep the upper-left area airy and clean — editorial open space at top-left",
        "bottom-right": "keep the lower-right area calm and uncluttered — space for subtle text",
    }
    area_hint = area_map.get(placement, "keep natural open negative space in the composition")

    return (
        f"Japanese natural lifestyle magazine background photograph, 16:9 landscape. "
        f"SCENE: {scene}. "
        f"LIGHT: {light}. Bright, warm, natural daylight. Soft and airy — morning to midday light quality. "
        f"PALETTE: {palette}. Ivory, beige, cream, warm white, natural wood tones — light and breathable. "
        f"COMPOSITION: {area_hint}. Generous negative space, uncluttered, calm. "
        f"Style: Muji lifestyle campaign, Linné magazine Japan, Kinarino, Kinfolk, Pinterest natural aesthetic. "
        f"MOOD: hopeful, warm, peaceful, 'life feels a little more in order' — the opposite of dark or heavy. "
        f"ABSOLUTELY NO: dark tones, dramatic shadows, night scenes, cinematic lighting, moody atmosphere, lonely or melancholic mood, film poster look. "
        f"ABSOLUTELY NO text of any kind — no Japanese characters, no English words, no numbers, no watermarks. "
        f"Pure photography. Bright and natural. Human and warm."
    )


def _build_magazine_html(
    bg_b64: str, concept: dict, width: int = 1536, height: int = 1024
) -> str:
    """雑誌表紙風 HTML テンプレート（8スタイル）。
    layout_style: editorial_left / split_scale / giant_word / vertical_accent /
                  apple_clean / nordic_minimal / band_editorial / zine_corner
    """
    tag          = concept.get("tag", "")
    copy_        = concept.get("copy", "")
    subcopy      = concept.get("subcopy", "")
    placement    = concept.get("text_placement", "lower-center")
    color_mode   = concept.get("text_color", "white")
    layout_style = concept.get("layout_style", "editorial_left")

    # ── カラー設定 ──────────────────────────────────────────────────────────
    if color_mode == "white":
        c_main   = "#FFFFFF"
        c_sub    = "rgba(255,255,255,0.78)"
        c_small  = "rgba(255,255,255,0.52)"
        c_rule   = "rgba(255,255,255,0.32)"
        c_en     = "rgba(255,255,255,0.50)"
        c_band   = "rgba(8,6,4,0.54)"
        grads = {
            "bottom-left":  "linear-gradient(158deg, transparent 38%, rgba(0,0,0,0.46) 100%)",
            "lower-center": "linear-gradient(to top, rgba(0,0,0,0.46) 0%, rgba(0,0,0,0.14) 50%, transparent 74%)",
            "center-left":  "linear-gradient(to right, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0.10) 54%, transparent 76%)",
            "upper-left":   "linear-gradient(to bottom, rgba(0,0,0,0.38) 0%, rgba(0,0,0,0.08) 46%, transparent 68%)",
            "bottom-right": "linear-gradient(202deg, transparent 38%, rgba(0,0,0,0.44) 100%)",
        }
    else:
        c_main   = "#1E1A15"
        c_sub    = "rgba(30,26,21,0.70)"
        c_small  = "rgba(30,26,21,0.46)"
        c_rule   = "rgba(30,26,21,0.20)"
        c_en     = "rgba(30,26,21,0.42)"
        c_band   = "rgba(252,248,240,0.86)"
        grads    = {k: "none" for k in ["bottom-left","lower-center","center-left","upper-left","bottom-right"]}

    grad = grads.get(placement, grads.get("lower-center", "none"))
    px   = int(width  * 0.055)
    py   = int(height * 0.072)
    tl   = len(copy_)

    # ── フォントファミリー ──────────────────────────────────────────────────
    f_serif = '"Hiragino Mincho ProN","游明朝体","Yu Mincho","HiraMinProN-W6","Noto Serif CJK JP",serif'
    f_sans  = '"Hiragino Kaku Gothic ProN","游ゴシック体","Yu Gothic",sans-serif'
    f_latin = '"Helvetica Neue","Helvetica","Arial",sans-serif'

    # ── テキスト分割：句読点 or 中間 ──────────────────────────────────────
    def _split(text):
        for sep in "、。！？":
            idx = text.find(sep)
            if 2 <= idx <= len(text) - 2:
                return text[:idx + 1], text[idx + 1:]
        mid = max(2, len(text) // 2)
        return text[:mid], text[mid:]

    copy_a, copy_b = _split(copy_)

    # ── 英字アクセント ────────────────────────────────────────────────────
    _en_map = {
        "副業": "SIDE JOB", "AI": "AI LIFE", "活用": "AI TOOLS",
        "効率": "WORK SMARTER", "学習": "LEARN", "発見": "DISCOVER",
        "入門": "GET STARTED", "自動": "AUTOMATION", "比較": "COMPARE",
        "収益": "INCOME", "ツール": "TOOLS", "方法": "HOW TO",
        "朝": "MORNING", "整": "ORGANIZE", "始": "BEGIN",
        "暮": "DAILY LIFE", "仕事": "WORK LIFE", "時間": "YOUR TIME",
    }
    en_word = next((v for k, v in _en_map.items() if k in (tag + copy_)), "AI LIFE")

    # ── 共通ベース CSS ────────────────────────────────────────────────────
    base_css = (
        f"*{{margin:0;padding:0;box-sizing:border-box;}}"
        f"html,body{{width:{width}px;height:{height}px;overflow:hidden;background:#ede8de;}}"
        f'.bg{{position:absolute;inset:0;background-image:url("data:image/jpeg;base64,{bg_b64}");'
        f"background-size:cover;background-position:center;}}"
        f".grad{{position:absolute;inset:0;background:{grad};}}"
    )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 1 : editorial_left — 雑誌編集風
    # ────────────────────────────────────────────────────────────────────────
    if layout_style == "editorial_left":
        if   tl <= 6:  fs = int(height * 0.132)
        elif tl <= 10: fs = int(height * 0.110)
        else:          fs = int(height * 0.090)

        if   placement == "lower-center": block_pos = f"bottom:{py}px;left:50%;transform:translateX(-50%);max-width:{int(width*.54)}px;"
        elif placement == "center-left":  block_pos = f"top:50%;transform:translateY(-50%);left:{px}px;max-width:{int(width*.48)}px;"
        elif placement == "upper-left":   block_pos = f"top:{int(height*.09)}px;left:{px}px;max-width:{int(width*.50)}px;"
        elif placement == "bottom-right": block_pos = f"bottom:{py}px;right:{px}px;max-width:{int(width*.46)}px;text-align:right;"
        else:                             block_pos = f"bottom:{py}px;left:{px}px;max-width:{int(width*.50)}px;"

        tag_v  = tag if tag else en_word[:10]
        sub_h  = f'<p class="sub">{subcopy}</p>' if subcopy else ""
        css = (base_css +
            f".block{{position:absolute;{block_pos}}}"
            f".label{{font-family:{f_latin};font-size:{int(height*.016)}px;font-weight:300;"
            f"letter-spacing:.40em;color:{c_small};text-transform:uppercase;margin-bottom:{int(height*.018)}px;}}"
            f".rule{{width:{int(width*.070)}px;height:1px;background:{c_rule};margin-bottom:{int(height*.026)}px;}}"
            f".title{{font-family:{f_serif};font-size:{fs}px;font-weight:700;line-height:1.20;"
            f"letter-spacing:-.022em;color:{c_main};text-shadow:0 2px 38px rgba(0,0,0,.20);"
            f"margin-bottom:{int(height*.020)}px;word-break:keep-all;}}"
            f".sub{{font-family:{f_sans};font-size:{int(height*.020)}px;font-weight:300;"
            f"letter-spacing:.18em;color:{c_sub};line-height:1.7;}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="block"><div class="label">{tag_v}</div>'
            f'<div class="rule"></div><h1 class="title">{copy_}</h1>{sub_h}</div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 2 : split_scale — 前半細字→後半極大
    # ────────────────────────────────────────────────────────────────────────
    elif layout_style == "split_scale":
        bl = len(copy_b)
        if   bl <= 4:  fs_b = int(height * 0.172)
        elif bl <= 7:  fs_b = int(height * 0.142)
        else:          fs_b = int(height * 0.115)
        fs_a = int(height * 0.038)

        if   placement == "center-left":  block_pos = f"top:50%;transform:translateY(-50%);left:{px}px;max-width:{int(width*.52)}px;"
        elif placement == "upper-left":   block_pos = f"top:{int(height*.08)}px;left:{px}px;max-width:{int(width*.52)}px;"
        elif placement == "lower-center": block_pos = f"bottom:{py}px;left:{px}px;max-width:{int(width*.52)}px;"
        else:                             block_pos = f"bottom:{py}px;left:{px}px;max-width:{int(width*.52)}px;"

        css = (base_css +
            f".block{{position:absolute;{block_pos}}}"
            f".pre{{font-family:{f_serif};font-size:{fs_a}px;font-weight:400;"
            f"letter-spacing:.04em;color:{c_sub};margin-bottom:{int(height*.002)}px;}}"
            f".main{{font-family:{f_serif};font-size:{fs_b}px;font-weight:700;line-height:1.10;"
            f"letter-spacing:-.030em;color:{c_main};text-shadow:0 3px 50px rgba(0,0,0,.22);"
            f"margin-bottom:{int(height*.016)}px;word-break:keep-all;}}"
            f".en-foot{{font-family:{f_latin};font-size:{int(height*.013)}px;font-weight:300;"
            f"letter-spacing:.42em;color:{c_en};text-transform:uppercase;}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="block">'
            f'<div class="pre">{copy_a}</div>'
            f'<h1 class="main">{copy_b}</h1>'
            f'<div class="en-foot">{en_word}</div></div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 3 : giant_word — 1語極大
    # ────────────────────────────────────────────────────────────────────────
    elif layout_style == "giant_word":
        if   tl <= 4:  fs = int(height * 0.205)
        elif tl <= 6:  fs = int(height * 0.168)
        elif tl <= 9:  fs = int(height * 0.135)
        else:          fs = int(height * 0.108)

        if   placement == "lower-center": block_pos = f"bottom:{int(py*.8)}px;left:50%;transform:translateX(-50%);text-align:center;max-width:{int(width*.82)}px;"
        elif placement == "upper-left":   block_pos = f"top:{int(height*.06)}px;left:{px}px;max-width:{int(width*.62)}px;"
        elif placement == "bottom-right": block_pos = f"bottom:{py}px;right:{px}px;max-width:{int(width*.60)}px;text-align:right;"
        else:                             block_pos = f"bottom:{py}px;left:{px}px;max-width:{int(width*.62)}px;"

        tag_or_sub = subcopy if subcopy else (tag if tag else "")
        tiny_h = f'<div class="tiny-sub">{tag_or_sub}</div>' if tag_or_sub else ""
        css = (base_css +
            f".block{{position:absolute;{block_pos}}}"
            f".giant{{font-family:{f_serif};font-size:{fs}px;font-weight:700;line-height:1.08;"
            f"letter-spacing:-.020em;color:{c_main};"
            f"text-shadow:0 4px 70px rgba(0,0,0,.24);margin-bottom:{int(height*.014)}px;word-break:keep-all;}}"
            f".tiny-sub{{font-family:{f_sans};font-size:{int(height*.018)}px;font-weight:300;"
            f"letter-spacing:.24em;color:{c_small};}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="block"><h1 class="giant">{copy_}</h1>{tiny_h}</div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 4 : vertical_accent — 縦組みメイン＋横英字
    # ────────────────────────────────────────────────────────────────────────
    elif layout_style == "vertical_accent":
        fs_v   = int(height * 0.090)
        v_left = px if placement in ("bottom-left","center-left","upper-left") else int(width * 0.68)
        v_top  = int(height * 0.08)
        tag_h  = f'<div class="vert-tag">{tag}</div>' if tag else ""
        sub_h  = f'<div class="vert-sub">{subcopy}</div>' if subcopy else ""
        css = (base_css +
            f".vwrap{{position:absolute;top:{v_top}px;left:{v_left}px;"
            f"display:flex;align-items:flex-start;gap:{int(width*.022)}px;}}"
            f".vtext{{font-family:{f_serif};font-size:{fs_v}px;font-weight:700;"
            f"line-height:1.50;letter-spacing:.14em;color:{c_main};"
            f"writing-mode:vertical-rl;text-orientation:mixed;"
            f"text-shadow:0 2px 30px rgba(0,0,0,.18);max-height:{int(height*.80)}px;}}"
            f".vside{{display:flex;flex-direction:column;justify-content:space-between;"
            f"padding:{int(height*.04)}px 0;min-height:{int(height*.48)}px;}}"
            f".ven{{font-family:{f_latin};font-size:{int(height*.014)}px;font-weight:300;"
            f"letter-spacing:.40em;color:{c_en};text-transform:uppercase;}}"
            f".vert-tag{{font-family:{f_sans};font-size:{int(height*.016)}px;font-weight:300;"
            f"letter-spacing:.22em;color:{c_small};}}"
            f".vert-sub{{font-family:{f_sans};font-size:{int(height*.017)}px;font-weight:300;"
            f"letter-spacing:.14em;color:{c_sub};line-height:1.8;}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="vwrap">'
            f'<div class="vtext">{copy_}</div>'
            f'<div class="vside"><div class="ven">{en_word}</div>{tag_h}{sub_h}</div>'
            f'</div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 5 : apple_clean — Apple広告風
    # ────────────────────────────────────────────────────────────────────────
    elif layout_style == "apple_clean":
        if   tl <= 5:  fs = int(height * 0.160)
        elif tl <= 8:  fs = int(height * 0.132)
        elif tl <= 12: fs = int(height * 0.110)
        else:          fs = int(height * 0.090)

        if   placement == "lower-center": block_pos = f"bottom:{int(py*1.3)}px;left:50%;transform:translateX(-50%);text-align:center;max-width:{int(width*.72)}px;"
        elif placement == "upper-left":   block_pos = f"top:{int(height*.08)}px;left:{px}px;max-width:{int(width*.54)}px;"
        elif placement == "bottom-right": block_pos = f"bottom:{py}px;right:{px}px;max-width:{int(width*.54)}px;text-align:right;"
        else:                             block_pos = f"bottom:{py}px;left:{px}px;max-width:{int(width*.54)}px;"

        css = (base_css +
            f".block{{position:absolute;{block_pos}}}"
            f".atitle{{font-family:{f_serif};font-size:{fs}px;font-weight:700;line-height:1.18;"
            f"letter-spacing:-.025em;color:{c_main};"
            f"text-shadow:0 2px 50px rgba(0,0,0,.18);margin-bottom:{int(height*.030)}px;word-break:keep-all;}}"
            f".aen{{font-family:{f_latin};font-size:{int(height*.016)}px;font-weight:300;"
            f"letter-spacing:.38em;color:{c_en};text-transform:uppercase;}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="block"><h1 class="atitle">{copy_}</h1>'
            f'<div class="aen">{en_word}</div></div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 6 : nordic_minimal — 北欧ミニマル
    # ────────────────────────────────────────────────────────────────────────
    elif layout_style == "nordic_minimal":
        if   tl <= 6:  fs = int(height * 0.142)
        elif tl <= 10: fs = int(height * 0.118)
        else:          fs = int(height * 0.096)

        if placement in ("bottom-left","lower-center","bottom-right"):
            block_pos = f"bottom:{py}px;left:{px}px;max-width:{int(width*.52)}px;"
        else:
            block_pos = f"top:{int(height*.08)}px;left:{px}px;max-width:{int(width*.52)}px;"

        detail = f"{en_word}  ·  {tag}" if tag else en_word
        css = (base_css +
            f".block{{position:absolute;{block_pos}}}"
            f".nrule{{width:{int(width*.10)}px;height:1px;background:{c_rule};margin-bottom:{int(height*.030)}px;}}"
            f".ntitle{{font-family:{f_serif};font-size:{fs}px;font-weight:600;line-height:1.22;"
            f"letter-spacing:-.012em;color:{c_main};"
            f"text-shadow:0 2px 38px rgba(0,0,0,.14);margin-bottom:{int(height*.026)}px;word-break:keep-all;}}"
            f".ndetail{{font-family:{f_latin};font-size:{int(height*.014)}px;font-weight:300;"
            f"letter-spacing:.34em;color:{c_small};text-transform:uppercase;}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="block"><div class="nrule"></div>'
            f'<h1 class="ntitle">{copy_}</h1>'
            f'<div class="ndetail">{detail}</div></div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 7 : band_editorial — frosted帯エディトリアル
    # ────────────────────────────────────────────────────────────────────────
    elif layout_style == "band_editorial":
        if   tl <= 6:  fs = int(height * 0.094)
        elif tl <= 10: fs = int(height * 0.078)
        else:          fs = int(height * 0.064)
        band_y_map = {
            "bottom-left":  int(height * 0.730),
            "lower-center": int(height * 0.748),
            "center-left":  int(height * 0.420),
            "upper-left":   int(height * 0.108),
            "bottom-right": int(height * 0.730),
        }
        bt = band_y_map.get(placement, int(height * 0.748))
        bh = int(height * 0.196)
        tag_h = (
            f'<div class="btag">{tag}</div><div class="bsep"></div>'
            if tag else ""
        )
        css = (base_css +
            f".band{{position:absolute;top:{bt}px;left:0;right:0;height:{bh}px;"
            f"background:{c_band};backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);"
            f"display:flex;align-items:center;padding:0 {px}px;gap:{int(width*.036)}px;}}"
            f".bsep{{width:1px;height:{int(bh*.55)}px;background:{c_rule};flex-shrink:0;}}"
            f".btag{{font-family:{f_sans};font-size:{int(height*.017)}px;font-weight:300;"
            f"letter-spacing:.22em;color:{c_small};white-space:nowrap;flex-shrink:0;}}"
            f".btitle{{font-family:{f_serif};font-size:{fs}px;font-weight:700;line-height:1.18;"
            f"letter-spacing:-.022em;color:{c_main};word-break:keep-all;flex:1;}}"
            f".ben{{font-family:{f_latin};font-size:{int(height*.013)}px;font-weight:300;"
            f"letter-spacing:.36em;color:{c_en};text-transform:uppercase;white-space:nowrap;"
            f"flex-shrink:0;margin-left:auto;}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<div class="band">{tag_h}'
            f'<h1 class="btitle">{copy_}</h1>'
            f'<div class="ben">{en_word}</div></div>'
        )

    # ────────────────────────────────────────────────────────────────────────
    # STYLE 8 : zine_corner — ZINE風コーナー自由配置
    # ────────────────────────────────────────────────────────────────────────
    else:
        if   tl <= 5:  fs = int(height * 0.152)
        elif tl <= 8:  fs = int(height * 0.126)
        elif tl <= 12: fs = int(height * 0.104)
        else:          fs = int(height * 0.084)
        tag_h = f'<div class="ztag">{tag}</div>' if tag else ""
        sub_h = f'<div class="zsub">{subcopy}</div>' if subcopy else ""
        css = (base_css +
            f".zmain{{position:absolute;bottom:{py}px;left:{px}px;"
            f"font-family:{f_serif};font-size:{fs}px;font-weight:700;line-height:1.16;"
            f"letter-spacing:-.022em;color:{c_main};text-shadow:0 2px 40px rgba(0,0,0,.20);"
            f"word-break:keep-all;max-width:{int(width*.52)}px;}}"
            f".ztop{{position:absolute;top:{int(height*.062)}px;right:{px}px;text-align:right;}}"
            f".zen{{font-family:{f_latin};font-size:{int(height*.013)}px;font-weight:300;"
            f"letter-spacing:.40em;color:{c_en};text-transform:uppercase;}}"
            f".ztag{{font-family:{f_sans};font-size:{int(height*.015)}px;font-weight:300;"
            f"letter-spacing:.22em;color:{c_small};margin-top:{int(height*.008)}px;}}"
            f".zsub{{position:absolute;bottom:{py}px;right:{px}px;text-align:right;"
            f"font-family:{f_sans};font-size:{int(height*.018)}px;font-weight:300;"
            f"letter-spacing:.16em;color:{c_sub};}}"
        )
        body = (
            f'<div class="bg"></div><div class="grad"></div>'
            f'<h1 class="zmain">{copy_}</h1>'
            f'<div class="ztop"><div class="zen">{en_word}</div>{tag_h}</div>'
            f'{sub_h}'
        )

    return (
        f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
        f"<style>{css}</style></head><body>{body}</body></html>"
    )


def _render_magazine_pil_fallback(
    bg_bytes: bytes, concept: dict, width: int, height: int
) -> bytes:
    """PIL による雑誌風テキスト合成（Playwright不可時のフォールバック）。"""
    from PIL import Image, ImageDraw, ImageFont
    import io as _io

    img = Image.open(_io.BytesIO(bg_bytes)).convert("RGBA")
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)

    tag        = concept.get("tag", "")
    copy_      = concept.get("copy", "")
    subcopy    = concept.get("subcopy", "")
    placement  = concept.get("text_placement", "lower-center")
    color_mode = concept.get("text_color", "white")

    C_MAIN = (255,255,255,255) if color_mode == "white" else (26,23,20,255)
    C_SUB  = (255,255,255,175) if color_mode == "white" else (38,30,22,168)
    C_TAG  = (255,255,255,148) if color_mode == "white" else (38,30,22,128)

    # グラデーションオーバーレイ（white モードのみ・薄め）
    if color_mode == "white":
        ov  = Image.new("RGBA", (width, height), (0,0,0,0))
        dov = ImageDraw.Draw(ov)
        gh  = int(height * 0.55)
        for yi in range(gh):
            t = yi / gh
            a = int(105 * (1.0 - t**0.60))
            dov.line([(0, height-1-yi),(width, height-1-yi)], fill=(8,6,4,a))
        img = Image.alpha_composite(img, ov)

    bold_path = _find_font(_FONT_BOLD_CANDIDATES)
    reg_path  = _find_font(_FONT_REG_CANDIDATES)

    def _fnt(path, sz):
        if path:
            try:
                return ImageFont.truetype(path, sz)
            except Exception:
                pass
        return ImageFont.load_default()

    def _tsz(text, font):
        d  = ImageDraw.Draw(Image.new("RGBA", (1,1)))
        bb = d.textbbox((0,0), text, font=font)
        return bb[2]-bb[0], bb[3]-bb[1]

    title_len = len(copy_)
    if   title_len <= 5:  fs = int(height * 0.142)
    elif title_len <= 8:  fs = int(height * 0.116)
    elif title_len <= 12: fs = int(height * 0.096)
    else:                 fs = int(height * 0.080)

    f_title = _fnt(bold_path, fs)
    f_sub   = _fnt(reg_path,  int(height * 0.022))
    f_tag   = _fnt(reg_path,  int(height * 0.020))

    def _block_h():
        h = 0
        if tag: h += _tsz(tag, f_tag)[1] + int(height*.028)
        h += _tsz(copy_, f_title)[1] + int(height*.026)
        if subcopy: h += _tsz(subcopy, f_sub)[1]
        return h

    PAD  = int(width  * 0.052)
    PADB = int(height * 0.078)
    draw = ImageDraw.Draw(img)

    if placement == "bottom-left":
        tx, ty = PAD, height - PADB - _block_h()
    elif placement == "lower-center":
        tw, _ = _tsz(copy_, f_title)
        tx    = (width - tw) // 2
        ty    = height - PADB - _block_h()
    elif placement == "center-left":
        tx, ty = PAD, (height - _block_h()) // 2
    elif placement == "upper-left":
        tx, ty = PAD, int(height * .082)
    else:
        tw, _ = _tsz(copy_, f_title)
        tx    = (width - tw) // 2
        ty    = height - PADB - _block_h()

    y = ty
    if tag:
        draw.text((tx, y), tag, font=f_tag, fill=C_TAG)
        y += _tsz(tag, f_tag)[1] + int(height*.028)
    sd = int(height*.004)
    draw.text((tx+sd, y+sd), copy_, font=f_title, fill=(0,0,0,55))
    draw.text((tx,    y   ), copy_, font=f_title, fill=C_MAIN)
    y += _tsz(copy_, f_title)[1] + int(height*.026)
    if subcopy:
        draw.text((tx, y), subcopy, font=f_sub, fill=C_SUB)

    out = Image.new("RGB", img.size, (255,255,255))
    out.paste(img, mask=img.split()[3])
    buf = _io.BytesIO()
    out.save(buf, format="JPEG", quality=93)
    print("[IMAGE] overlay: PIL フォールバック合成完了")
    return buf.getvalue()


def _render_magazine_overlay(
    bg_bytes: bytes,
    concept: dict,
    width: int = 1536,
    height: int = 1024,
) -> bytes:
    """
    背景画像 + コンセプトから雑誌表紙風アイキャッチを合成する。
    Playwright (HTML/CSS→PNG) → PIL フォールバック の順で試みる。
    """
    try:
        from playwright.sync_api import sync_playwright
        import base64 as _b64

        bg_b64 = _b64.b64encode(bg_bytes).decode()
        html   = _build_magazine_html(bg_b64, concept, width, height)

        with sync_playwright() as p:
            browser   = p.chromium.launch(args=["--no-sandbox"])
            page      = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html, wait_until="networkidle")
            png_bytes = page.screenshot(type="png", full_page=False)
            browser.close()

        from PIL import Image
        import io as _io
        pil_img = Image.open(_io.BytesIO(png_bytes)).convert("RGB")
        buf = _io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=93)
        print("[IMAGE] overlay: Playwright HTML/CSS合成完了")
        return buf.getvalue()

    except Exception as e_:
        print(f"[IMAGE] Playwright失敗 → PIL フォールバック: {e_}")
        return _render_magazine_pil_fallback(bg_bytes, concept, width, height)

# 5カラーパレット（ov=クリームOV RGB, title=暗色テキスト, accent=アクセント,
#                  lb=ラベル/パネル背景, sb=カード背景, bd=バッジ色）
_OV_PALETTES = [
    {"name": "coral",  "ov": (255,248,240), "title": (26,35,94),   "accent": (255,72,125),  "lb": (66,133,244),  "sb": (255,252,245), "bd": (255,72,125)},
    {"name": "teal",   "ov": (228,248,245), "title": (10,45,55),   "accent": (0,148,133),   "lb": (0,120,110),   "sb": (220,248,245), "bd": (0,148,133)},
    {"name": "purple", "ov": (244,236,255), "title": (38,18,75),   "accent": (124,58,237),  "lb": (91,33,182),   "sb": (244,240,255), "bd": (124,58,237)},
    {"name": "amber",  "ov": (255,250,225), "title": (58,28,8),    "accent": (210,105,0),   "lb": (175,80,8),    "sb": (255,248,220), "bd": (210,105,0)},
    {"name": "rose",   "ov": (255,236,241), "title": (75,12,28),   "accent": (220,38,68),   "lb": (185,18,55),   "sb": (255,234,240), "bd": (220,38,68)},
]


def _overlay_eyecatch_text(img_bytes: bytes, texts: dict) -> bytes:
    """PIL オーバーレイ。6レイアウト × 5パレット をランダム選択。
    各レイアウトは自前で読み取り可能領域を生成（背景の空きに依存しない）。

    L0 YouTube Bottom : 下ダークグラデ + テキスト下部 + バッジ上右
    L1 Magazine Panel : 左ソリッドパネル（全テキスト左） + 右は画像のみ
    L2 Floating Card  : 半透明カードが画像上にフロート（3位置ランダム）
    L3 Minimal Impact : 全体薄OV + 1巨大ワード中央 + 最小装飾
    L4 Top Band       : 上部ソリッドバンドに全テキスト + 下部は画像のみ
    L5 Sticker Pop    : 各要素が独立スティッカー + OVなし + 高コントラスト
    """
    from PIL import Image, ImageDraw, ImageFont
    import io as _io

    img = Image.open(_io.BytesIO(img_bytes)).convert("RGBA")
    W, H = img.size

    pal       = random.choice(_OV_PALETTES)
    layout_id = random.randint(0, 5)
    print(f"[IMAGE] overlay layout={layout_id}  palette={pal['name']}")

    C_TITLE = (*pal["title"], 255)
    C_ACNT  = (*pal["accent"], 245)
    C_WHITE = (255, 255, 255, 255)

    font_bold_path = _find_font(_FONT_BOLD_CANDIDATES)
    font_reg_path  = _find_font(_FONT_REG_CANDIDATES)
    PAD_L = int(W * 0.042)
    PAD_R = int(W * 0.042)
    PAD_T = int(H * 0.042)

    _md = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def _load(path, size):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _tw(text, font):
        bb = _md.textbbox((0, 0), text, font=font)
        return bb[2]-bb[0], bb[3]-bb[1]

    def _auto_size(text, path, max_sz, min_sz, max_w):
        for sz in range(max_sz, min_sz-1, -4):
            f = _load(path, sz)
            w, _ = _tw(text, f)
            if w <= max_w:
                return f, sz
        return _load(path, min_sz), min_sz

    def _pill(base, x, y, text, font, bg, fg=C_WHITE):
        px, py = int(W*0.018), int(H*0.015)
        d  = ImageDraw.Draw(base)
        bb = d.textbbox((0,0), text, font=font)
        tw, th = bb[2]-bb[0], bb[3]-bb[1]
        pw, ph = tw+px*2, th+py*2
        lyr = Image.new("RGBA", (pw, ph), (0,0,0,0))
        ld  = ImageDraw.Draw(lyr)
        try:
            ld.rounded_rectangle([0,0,pw-1,ph-1], radius=ph//2, fill=bg)
        except Exception:
            ld.rectangle([0,0,pw-1,ph-1], fill=bg)
        base.paste(lyr, (x, y), lyr)
        ImageDraw.Draw(base).text((x+px, y+py-bb[1]), text, font=font, fill=fg)
        return pw, ph

    def _box_text(base, x, y, text, font, bg, fg, max_w=None, radius_ratio=3):
        if max_w is None:
            max_w = int(W*0.52)
        px, py = int(W*0.018), int(H*0.014)
        d  = ImageDraw.Draw(base)
        bb = d.textbbox((0,0), text, font=font)
        tw = min(bb[2]-bb[0], max_w)
        th = bb[3]-bb[1]
        pw, ph = tw+px*2, th+py*2
        lyr = Image.new("RGBA", (pw, ph), (0,0,0,0))
        ld  = ImageDraw.Draw(lyr)
        try:
            ld.rounded_rectangle([0,0,pw-1,ph-1], radius=ph//radius_ratio, fill=bg)
        except Exception:
            ld.rectangle([0,0,pw-1,ph-1], fill=bg)
        base.paste(lyr, (x, y), lyr)
        ImageDraw.Draw(base).text((x+px, y+py-bb[1]), text, font=font, fill=fg)
        return pw, ph

    def _badge(base, cx, cy, r, text, font):
        lyr = Image.new("RGBA", (r*2, r*2), (0,0,0,0))
        ld  = ImageDraw.Draw(lyr)
        ld.ellipse([0,0,r*2-1,r*2-1], fill=(*pal["bd"], 240))
        base.paste(lyr, (cx-r, cy-r), lyr)
        d  = ImageDraw.Draw(base)
        bb = d.textbbox((0,0), text, font=font)
        tw, th = bb[2]-bb[0], bb[3]-bb[1]
        d.text((cx-tw//2, cy-th//2-bb[1]), text, font=font, fill=C_WHITE,
               stroke_width=1, stroke_fill=(*pal["title"],100))

    f_strip = _load(font_bold_path, int(H * 0.044))
    f_pre   = _load(font_bold_path, int(H * 0.048))
    f_acnt  = _load(font_bold_path, int(H * 0.068))
    f_suppl = _load(font_reg_path,  int(H * 0.037))
    f_badge = _load(font_bold_path, int(H * 0.042))

    strip_text  = texts.get("strip_label", "AI活用")
    pre_text    = texts.get("pre_title",   "5分でわかる！")
    main_word   = texts.get("main_word",   "AI活用")
    accent_word = texts.get("accent_word", "活用ガイド")
    supplement  = texts.get("supplement",  "")
    badge_text  = texts.get("badge",       "")

    # ══════════════════════════════════════════════════════════
    # L0: YouTube Bottom
    #   下部ダークグラデ(60%) + テキスト下寄り + バッジ上右
    # ══════════════════════════════════════════════════════════
    if layout_id == 0:
        gh = int(H * 0.60)
        ov = Image.new("RGBA", (W, H), (0,0,0,0))
        d  = ImageDraw.Draw(ov)
        for yi in range(gh):
            t = yi / gh
            a = int(205 * (1.0 - t**0.55))
            d.line([(0, H-1-yi),(W, H-1-yi)], fill=(12,15,30, a))
        img  = Image.alpha_composite(img, ov)
        draw = ImageDraw.Draw(img)

        _pill(img, PAD_L, PAD_T, strip_text, f_strip, (*pal["lb"],230))
        draw = ImageDraw.Draw(img)
        if badge_text:
            _badge(img, W-PAD_R-int(H*0.09), PAD_T+int(H*0.09),
                   int(H*0.082), badge_text, f_badge)

        pre_y = int(H * 0.44)
        pre_w, pre_h = _tw(pre_text, f_pre)
        draw = ImageDraw.Draw(img)
        draw.text((PAD_L, pre_y), pre_text, font=f_pre,
                  fill=(*pal["accent"],240))

        f_main, _ = _auto_size(main_word, font_bold_path,
                                int(H*0.22), int(H*0.10), int(W*0.55))
        main_w, main_h = _tw(main_word, f_main)
        main_y = pre_y + pre_h + int(H*0.010)
        sd = int(H*0.007)
        draw.text((PAD_L+sd, main_y+sd), main_word, font=f_main, fill=(0,0,0,60))
        draw.text((PAD_L, main_y), main_word, font=f_main, fill=C_WHITE)

        acnt_w, acnt_h = _tw(accent_word, f_acnt)
        if PAD_L + main_w + int(W*0.022) + acnt_w < int(W*0.72):
            draw.text((PAD_L+main_w+int(W*0.022), main_y+(main_h-acnt_h)//2),
                      accent_word, font=f_acnt, fill=(*pal["accent"],240))
            acnt_bottom = main_y + main_h
        else:
            draw.text((PAD_L, main_y+main_h+int(H*0.010)),
                      accent_word, font=f_acnt, fill=(*pal["accent"],240))
            acnt_bottom = main_y + main_h + acnt_h + int(H*0.010)

        if supplement:
            sup_y = max(acnt_bottom + int(H*0.018), int(H*0.842))
            draw.text((PAD_L, sup_y), "\u2713  "+supplement,
                      font=f_suppl, fill=(210,220,240,195))

    # ══════════════════════════════════════════════════════════
    # L1: Magazine Panel
    #   左44%ソリッドパネル（lb色） / 全テキスト左 / 右は画像のみ
    # ══════════════════════════════════════════════════════════
    elif layout_id == 1:
        panel_w = int(W * 0.44)
        pl = Image.new("RGBA", (panel_w, H), (*pal["lb"], 228))
        img.paste(pl, (0, 0), pl)
        draw = ImageDraw.Draw(img)
        draw.rectangle([panel_w-int(W*0.006), 0, panel_w, H],
                       fill=(*pal["accent"],200))

        lbl_y = int(H * 0.058)
        _, lbl_h = _pill(img, PAD_L, lbl_y, strip_text, f_strip,
                         (255,255,255,175), (*pal["lb"],255))
        draw = ImageDraw.Draw(img)

        pre_y = lbl_y + lbl_h + int(H*0.034)
        _, pre_h = _tw(pre_text, f_pre)
        draw.text((PAD_L, pre_y), pre_text, font=f_pre, fill=C_WHITE)

        f_main, _ = _auto_size(main_word, font_bold_path,
                                int(H*0.22), int(H*0.10), panel_w - PAD_L*2)
        main_w, main_h = _tw(main_word, f_main)
        main_y = pre_y + pre_h + int(H*0.016)
        sd = int(H*0.006)
        draw.text((PAD_L+sd, main_y+sd), main_word, font=f_main, fill=(0,0,0,45))
        draw.text((PAD_L, main_y), main_word, font=f_main, fill=C_WHITE)

        acnt_y = main_y + main_h + int(H*0.014)
        _, acnt_h = _tw(accent_word, f_acnt)
        draw.text((PAD_L, acnt_y), accent_word, font=f_acnt,
                  fill=(255,255,200,245))

        if supplement:
            sup_y = min(acnt_y+acnt_h+int(H*0.028), int(H*0.820))
            _box_text(img, PAD_L, sup_y, "\u2713  "+supplement, f_suppl,
                      (255,255,255,155), (*pal["title"],230),
                      max_w=panel_w-PAD_L*2)
            draw = ImageDraw.Draw(img)

        if badge_text:
            _badge(img, int(W*0.795), int(H*0.500),
                   int(H*0.080), badge_text, f_badge)

    # ══════════════════════════════════════════════════════════
    # L2: Floating Card
    #   半透明カード（top_left / center / bottom_left ランダム）
    # ══════════════════════════════════════════════════════════
    elif layout_id == 2:
        card_pos   = random.choice(["top_left", "center", "bottom_left"])
        card_max_w = int(W * 0.50)
        f_main, _  = _auto_size(main_word, font_bold_path,
                                 int(H*0.18), int(H*0.09),
                                 card_max_w - int(W*0.028)*2)
        main_w, main_h = _tw(main_word, f_main)
        _, pre_h   = _tw(pre_text, f_pre)
        _, acnt_h  = _tw(accent_word, f_acnt)
        lbl_ph     = _tw(strip_text, f_strip)[1] + int(H*0.015)*2
        _, sup_h   = _tw("\u2713  "+supplement, f_suppl) if supplement else (0, 0)
        sup_box_h  = (sup_h + int(H*0.014)*2 + int(H*0.020)) if supplement else 0

        cpx, cpy   = int(W*0.028), int(H*0.026)
        card_w     = card_max_w
        card_h     = (cpy*2 + lbl_ph + int(H*0.024) +
                      pre_h  + int(H*0.016) +
                      main_h + int(H*0.014) +
                      acnt_h + sup_box_h)

        if card_pos == "top_left":
            card_x, card_y = int(W*0.038), int(H*0.048)
        elif card_pos == "center":
            card_x = (W - card_w) // 2
            card_y = int(H * 0.110)
        else:
            card_x = int(W * 0.038)
            card_y = H - card_h - int(H * 0.048)

        sh = Image.new("RGBA", (card_w+10, card_h+10), (0,0,0,0))
        sd2 = ImageDraw.Draw(sh)
        try:
            sd2.rounded_rectangle([5,5,card_w+4,card_h+4],
                                   radius=int(H*0.028), fill=(0,0,0,55))
        except Exception:
            sd2.rectangle([5,5,card_w+4,card_h+4], fill=(0,0,0,55))
        img.paste(sh, (card_x-3, card_y-3), sh)

        cl = Image.new("RGBA", (card_w, card_h), (0,0,0,0))
        cd = ImageDraw.Draw(cl)
        try:
            cd.rounded_rectangle([0,0,card_w-1,card_h-1],
                                  radius=int(H*0.028), fill=(*pal["sb"],238))
        except Exception:
            cd.rectangle([0,0,card_w-1,card_h-1], fill=(*pal["sb"],238))
        img.paste(cl, (card_x, card_y), cl)
        draw = ImageDraw.Draw(img)

        tx = card_x + cpx
        ty = card_y + cpy
        _pill(img, tx, ty, strip_text, f_strip, (*pal["lb"],230))
        ty += lbl_ph + int(H*0.024)
        draw = ImageDraw.Draw(img)
        draw.text((tx, ty), pre_text, font=f_pre, fill=C_ACNT)
        ty += pre_h + int(H*0.016)
        draw.text((tx, ty), main_word, font=f_main, fill=C_TITLE)
        ty += main_h + int(H*0.014)
        draw.text((tx, ty), accent_word, font=f_acnt, fill=C_ACNT)
        if supplement:
            ty += acnt_h + int(H*0.020)
            _box_text(img, tx, ty, "\u2713  "+supplement, f_suppl,
                      (*pal["ov"],225), C_TITLE, max_w=card_w-cpx*2)
            draw = ImageDraw.Draw(img)

        if badge_text:
            bx = W - PAD_R - int(H*0.09)
            by = (H - int(H*0.12)) if card_pos != "bottom_left" else (PAD_T + int(H*0.09))
            _badge(img, bx, by, int(H*0.075), badge_text, f_badge)

    # ══════════════════════════════════════════════════════════
    # L3: Minimal Impact
    #   全体薄OV + 1巨大ワード中央（幅85%まで）
    # ══════════════════════════════════════════════════════════
    elif layout_id == 3:
        ov = Image.new("RGBA", (W, H), (*pal["ov"], 158))
        img  = Image.alpha_composite(img, ov)
        draw = ImageDraw.Draw(img)
        cx   = W // 2

        pre_w, pre_h = _tw(pre_text, f_pre)
        pre_y = int(H * 0.150)
        draw.text((cx-pre_w//2, pre_y), pre_text, font=f_pre, fill=C_ACNT)

        ly = pre_y + pre_h + int(H*0.016)
        lw = int(W * 0.26)
        draw.line([(cx-lw//2, ly),(cx+lw//2, ly)],
                  fill=(*pal["accent"],175), width=int(H*0.005))

        f_main, _ = _auto_size(main_word, font_bold_path,
                                int(H*0.26), int(H*0.12), int(W*0.85))
        main_w, main_h = _tw(main_word, f_main)
        main_y = ly + int(H*0.028)
        sd = int(H*0.008)
        draw.text((cx-main_w//2+sd, main_y+sd), main_word,
                  font=f_main, fill=(0,0,0,50))
        draw.text((cx-main_w//2, main_y), main_word, font=f_main, fill=C_TITLE)

        acnt_w, acnt_h = _tw(accent_word, f_acnt)
        acnt_y = main_y + main_h + int(H*0.018)
        draw.text((cx-acnt_w//2, acnt_y), accent_word, font=f_acnt, fill=C_ACNT)

        lbl_w, _ = _tw(strip_text, f_strip)
        px_s     = int(W*0.018)
        pill_tw  = lbl_w + px_s*2
        _pill(img, cx-pill_tw//2, acnt_y+acnt_h+int(H*0.024),
              strip_text, f_strip, (*pal["lb"],230))
        draw = ImageDraw.Draw(img)

        if badge_text:
            _badge(img, cx, int(H*0.906), int(H*0.055), badge_text, f_badge)

    # ══════════════════════════════════════════════════════════
    # L4: Top Band
    #   上部48%ソリッドバンドに全テキスト（白） / 下は画像のみ
    # ══════════════════════════════════════════════════════════
    elif layout_id == 4:
        band_h = int(H * 0.480)
        bl = Image.new("RGBA", (W, band_h), (*pal["lb"], 238))
        img.paste(bl, (0, 0), bl)
        draw = ImageDraw.Draw(img)
        cx   = W // 2

        pre_w, pre_h = _tw(pre_text, f_pre)
        pre_y = int(H*0.038)
        draw.text((cx-pre_w//2, pre_y), pre_text, font=f_pre, fill=C_WHITE)

        f_main, _ = _auto_size(main_word, font_bold_path,
                                int(H*0.20), int(H*0.10), int(W*0.88))
        main_w, main_h = _tw(main_word, f_main)
        main_y = pre_y + pre_h + int(H*0.020)
        draw.text((cx-main_w//2, main_y), main_word, font=f_main, fill=C_WHITE)

        acnt_w, acnt_h = _tw(accent_word, f_acnt)
        acnt_y = main_y + main_h + int(H*0.010)
        draw.text((cx-acnt_w//2, acnt_y), accent_word, font=f_acnt,
                  fill=(255,255,180,240))

        lbl_w, _ = _tw(strip_text, f_strip)
        px_s     = int(W*0.018)
        _pill(img, W-PAD_R-lbl_w-px_s*2, int(H*0.368),
              strip_text, f_strip, (255,255,255,175), (*pal["lb"],255))
        draw = ImageDraw.Draw(img)

        draw.line([(0,band_h),(W,band_h)],
                  fill=(*pal["accent"],175), width=int(H*0.006))

        if supplement:
            draw.text((PAD_L, band_h+int(H*0.058)), "\u2713  "+supplement,
                      font=f_suppl, fill=(*pal["title"],200))

        if badge_text:
            _badge(img, W-PAD_R-int(H*0.085), band_h+int(H*0.155),
                   int(H*0.075), badge_text, f_badge)

    # ══════════════════════════════════════════════════════════
    # L5: Sticker Pop
    #   OVほぼなし + 各要素が独立スティッカー
    # ══════════════════════════════════════════════════════════
    else:
        ov = Image.new("RGBA", (W, H), (*pal["ov"], 75))
        img  = Image.alpha_composite(img, ov)
        draw = ImageDraw.Draw(img)

        f_main, _ = _auto_size(main_word, font_bold_path,
                                int(H*0.22), int(H*0.10), int(W*0.50))
        main_w, main_h = _tw(main_word, f_main)
        bpx, bpy = int(W*0.022), int(H*0.018)
        bw, bh   = main_w+bpx*2, main_h+bpy*2
        box_x    = PAD_L
        box_y    = int(H * 0.510)
        _box_text(img, box_x, box_y, main_word, f_main,
                  (*pal["lb"],242), C_WHITE, max_w=main_w+2, radius_ratio=6)
        draw = ImageDraw.Draw(img)

        acnt_y = box_y + bh + int(H*0.012)
        _, acnt_h = _tw(accent_word, f_acnt)
        draw.text((PAD_L, acnt_y), accent_word, font=f_acnt,
                  fill=C_ACNT, stroke_width=2, stroke_fill=(255,255,255,175))

        pre_y = box_y - int(H*0.068)
        pre_w, _ = _tw(pre_text, f_pre)
        draw.text((PAD_L+2, pre_y+2), pre_text, font=f_pre, fill=(0,0,0,75))
        draw.text((PAD_L, pre_y), pre_text, font=f_pre, fill=C_WHITE)

        lbl_w, _ = _tw(strip_text, f_strip)
        px_s     = int(W*0.018)
        _pill(img, W-PAD_R-lbl_w-px_s*2, int(H*0.052),
              strip_text, f_strip, (*pal["bd"],238))
        draw = ImageDraw.Draw(img)

        if supplement:
            sup_y = acnt_y + acnt_h + int(H*0.018)
            draw.text((PAD_L+1, sup_y+1), supplement, font=f_suppl,
                      fill=(0,0,0,60))
            draw.text((PAD_L, sup_y), supplement, font=f_suppl,
                      fill=(*pal["title"],205))

        if badge_text:
            _badge(img, int(W*0.088), int(H*0.880),
                   int(H*0.068), badge_text, f_badge)

    # ── RGBA → RGB → JPEG ────────────────────────────────────
    out = Image.new("RGB", img.size, (255, 255, 255))
    out.paste(img, mask=img.split()[3])
    buf = _io.BytesIO()
    out.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _is_beginner_guide_title(title: str) -> bool:
    """クリック前に内容を把握したい入門・比較系タイトルかを判定する。"""
    triggers = (
        "初心者", "入門", "使い方", "始め方", "やり方", "おすすめ",
        "比較", "無料", "選", "ガイド", "解説", "できること",
    )
    return any(t in title for t in triggers)


def _select_beginner_guide_template(title: str) -> str:
    """タイトル内容から初心者ガイド型バナーの構図テンプレートを選ぶ。"""
    def _pick(pool: list[str]) -> str:
        history_path = _OUTPUT_DIR.parent / "eyecatch_template_history.json"
        recent: list[str] = []
        try:
            if history_path.exists():
                data = json.loads(history_path.read_text(encoding="utf-8"))
                recent = [str(x) for x in data.get("beginner_guide", [])][-4:]
        except Exception:
            recent = []

        available = [tpl for tpl in pool if tpl not in recent[-2:]]
        if not available:
            available = [tpl for tpl in pool if tpl != (recent[-1] if recent else "")]
        if not available:
            available = pool

        selected = random.choice(available)
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if history_path.exists():
                data = json.loads(history_path.read_text(encoding="utf-8"))
            seq = [str(x) for x in data.get("beginner_guide", [])]
            seq.append(selected)
            data["beginner_guide"] = seq[-12:]
            history_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return selected

    if any(k in title for k in ("副業", "稼ぐ", "月収", "収益", "アフィリエイト", "在宅")):
        return _pick(["cafe_side", "flatlay", "app_cards", "right_person", "left_person", "hands_closeup", "dark_desk"])
    if any(k in title for k in ("おすすめ", "比較", "無料", "選", "商用利用")):
        return _pick(["flatlay", "app_cards", "cafe_side", "right_person", "left_person", "hands_closeup", "dark_desk"])
    return _pick(["right_person", "flatlay", "cafe_side", "app_cards", "left_person", "hands_closeup", "dark_desk", "no_person_room"])


def _build_beginner_guide_background_prompt(title: str, template: str = "right_person") -> str:
    """初心者ガイド型バナーの背景写真プロンプト。文字はPILで後合成する。"""
    palette = random.choice([
        "ivory, warm white, muted blush pink, soft blue, natural wood, deep navy accents",
        "warm cream, pale sage green, dusty rose, natural wood, soft charcoal accents",
        "clean white, pale sky blue, light beige, muted coral, deep navy accents",
        "linen ivory, soft peach, warm gray, botanical green, dark blue-gray accents",
        "soft lavender, warm gray, muted navy, pale yellow, natural wood accents",
        "deep teal, cream, muted gold, warm walnut wood, soft white accents",
        "dusty blue, pale mint, warm beige, muted rose, charcoal navy accents",
    ])
    base = (
        "16:9 horizontal Japanese lifestyle blog thumbnail background, exact wide banner composition. "
        "Keep all important subjects away from the outer 8% edges so WordPress thumbnail crops will not cut them off. "
        "Style: polished lifestyle magazine cover, Pinterest, note header, friendly beginner guide, airy and warm. "
        f"Palette: {palette}. ABSOLUTELY NO text, no letters, no numbers, no logos, no watermark. "
        "No decorative symbols, no sparkle marks, no star glyphs, no ✧-like ornaments anywhere. "
        f"Topic feeling: {title}. "
    )

    if template == "flatlay":
        scene = random.choice([
            "top-down flatlay of a bright wooden desk with laptop corner, smartphone, notebook, pencil, coffee cup, small plant",
            "overhead view of a soft ivory desk with tablet, open planner, sticky notes, tea cup, simple flowers",
            "clean flatlay of AI work tools on a linen table: laptop, phone, notebook, pen, ceramic mug, botanical accent",
        ])
        return (
            base +
            f"Scene: {scene}. No people, no face, still-life only. "
            "The center and right side have beautiful lifestyle objects and gentle natural shadows. "
            "LEFT 56% remains bright and calm with clean ivory negative space for large Japanese typography."
        )

    if template == "app_cards":
        scene = random.choice([
            "bright home desk with laptop and phone, softly blurred pastel app-like cards floating as abstract blank rectangles",
            "minimal workspace with tablet and notebook, subtle blank UI cards as translucent shapes, natural morning light",
            "soft cafe table with laptop, coffee, and several clean blank rounded rectangles suggesting app comparison cards",
        ])
        return (
            base +
            f"Scene: {scene}. The cards are blank shapes only, with absolutely no readable text. "
            "RIGHT 48% contains the lifestyle tech objects and blank card shapes. "
            "LEFT 52% remains clear ivory negative space for typography."
        )

    if template == "cafe_side":
        person = random.choice([
            "a young Japanese woman in her early 20s, gentle side profile, shoulder-length brown hair, dusty blue blouse",
            "a young Japanese woman in her 20s seen from behind at a cafe table, sage green cardigan, relaxed posture",
            "a young Japanese woman in her late 20s with short bob hair, muted pink knit top, calm smile",
            "hands-only close-up of a young person typing on a laptop beside coffee, no face visible",
        ])
        return (
            base +
            f"RIGHT 45%: {person}, using a laptop at a quiet independent cafe by a window. "
            "Warm pale wood, soft greenery, coffee cup, late morning natural light. "
            "LEFT 55% remains bright ivory negative space for large Japanese text overlay."
        )

    if template == "left_person":
        person = random.choice([
            "a young Japanese woman in her early 20s with shoulder-length dark hair, navy cardigan over a white tee",
            "a Japanese woman in her late 20s with short bob hair, muted terracotta sweater, natural makeup",
            "a young Japanese man in his 20s, soft beige overshirt, calm focused expression",
            "a young Japanese woman with low ponytail, pale blue shirt, relaxed profile",
        ])
        scene = random.choice([
            "quiet home workspace with wood shelves and plants",
            "small cafe table near a bright window",
            "minimal studio desk with tablet, notebook, coffee, and soft shadows",
        ])
        return (
            base +
            f"LEFT 42%: {person}, using a laptop or tablet in a {scene}. "
            "RIGHT 58% remains clean bright negative space for large Japanese typography. "
            "Editorial composition, different from standard right-person thumbnails."
        )

    if template == "hands_closeup":
        scene = random.choice([
            "close-up of hands using a tablet with stylus, laptop edge, colored sticky notes, coffee cup",
            "hands arranging notebook, smartphone, and small blank cards on a warm wooden desk",
            "over-the-shoulder view with only hands visible, laptop and notebook, no face",
        ])
        return (
            base +
            f"Scene: {scene}. No visible face. Natural light, practical AI workflow mood. "
            "Use a stronger composition with objects on one side and clean negative space on the other."
        )

    if template == "dark_desk":
        return (
            base +
            "Evening calm workspace with deep teal wall, warm desk lamp, laptop, notebook, coffee, small plant, cozy but not dark. "
            "No people or only hands visible. Premium magazine mood, muted navy and amber accents. "
            "Large clean negative space for typography."
        )

    if template == "no_person_room":
        return (
            base +
            "No people. A quiet Scandinavian room corner with laptop on wooden desk, open notebook, ceramic cup, plants, linen curtain, soft sunlight. "
            "Lifestyle brand-ad mood with generous negative space and no face."
        )

    scene = random.choice([
        "bright Scandinavian home workspace, soft morning natural window light, plants, ceramic mug, notebook",
        "minimal living room work corner, linen curtain, small plant, warm tea cup, relaxed afternoon light",
        "clean home study desk, open notebook, white wall, botanical accent, clear midday natural light",
    ])
    person = random.choice([
        "a young Japanese woman in her early 20s, natural soft makeup, warm brown hair in a loose bun, dusty blue knit sweater",
        "a young Japanese woman in her early 20s, shoulder-length dark brown hair, sage green blouse, calm approachable smile",
        "a young Japanese woman in her 20s seen in gentle side profile, muted pink cardigan, focused and relaxed",
        "a Japanese woman in her late 20s with short bob hair, navy sweater, thoughtful expression",
        "a young Japanese man in his 20s, light gray shirt, relaxed and focused at a laptop",
    ])
    return (
        base +
        f"RIGHT 42%: {person}, calmly using a laptop at a bright wooden desk. "
        f"Scene: {scene}, gentle warm atmosphere. "
        "LEFT 58%: very clean bright ivory negative space with a subtle curved translucent "
        "white area, intentionally empty for large Japanese text overlay."
    )


def _guide_overlay_texts(title: str, texts: dict, template: str = "right_person") -> dict:
    """タイトルから初心者ガイド型に合う短い表示テキストへ整える。"""
    texts = _sanitize_overlay_texts(texts)
    head_kw = _extract_title_head_keyword(title)
    main = texts.get("main_word", "").strip() or head_kw or "AI活用"
    accent = texts.get("accent_word", "").strip() or "入門ガイド"
    strip = texts.get("strip_label", "").strip() or "初心者OK"

    if "ChatGPT" in title or "GPT" in title:
        main = "ChatGPT"
        if "入門" in title:
            accent = "入門ガイド"
        elif "使い方" in title:
            accent = "使い方講座"
    elif "画像生成AI" in title:
        main = "画像生成AI"
        if "無料" in title and "選" in title:
            m = re.search(r'(\d+|[0-9０-９]+)選', title)
            count = m.group(1) if m else ""
            accent = f"無料{count}選比較" if count else "無料比較ガイド"
        else:
            accent = "入門ガイド"
    elif "Claude" in title:
        main = "Claude"
    elif "Gemini" in title:
        main = "Gemini"
    elif head_kw and not any(x in main for x in ("AI", "ChatGPT", "Claude", "Gemini")):
        main = head_kw

    if "商用利用" in title:
        strip = "商用利用OK"
    elif "初心者" in title or "入門" in title:
        strip = "初心者OK"

    icon_sets = _select_icon_labels(title, site="aivice")
    palette_name = random.choice(["blush", "sage", "sky", "peach", "pop_pink", "royal_blue", "mint_yellow"])
    glyph_pool = ["search", "note", "sparkle", "check", "heart", "book", "yen"]
    if template == "left_person":
        text_side = "right"
    elif template in ("flatlay", "hands_closeup", "dark_desk", "no_person_room"):
        text_side = random.choice(["left", "right"])
    else:
        text_side = random.choice(["left", "left", "right"])

    return _sanitize_overlay_texts({
        "strip_label": strip,
        "pre_title": texts.get("pre_title", "").strip() or "はじめてでも、やさしく学べる",
        "main_word": main[:12],
        "accent_word": accent[:12],
        "supplement": "基本から使い方まで これ1本",
        "badge": random.choice([strip, "初心者OK", "やさしく解説"]),
        "icon_labels": icon_sets,
        "_palette_name": palette_name,
        "_template": template,
        "_panel_curve": random.choice(["soft", "wide", "diagonal"]),
        "_ribbon_x": random.choice([0.615, 0.645, 0.675]),
        "_sub_layout": random.choice(["ribbon_top", "badge_circle", "sticky_note", "icon_cards"]),
        "_text_side": text_side,
        "_icon_style": "dynamic",
        "_icon_glyphs": random.sample(glyph_pool, 3),
        "_hide_top_icon": random.choice([True, False]),
        "_hide_badge": random.choice([False, False, True]),
        "_hide_icons": random.choice([False, False, True]),
    })


def _overlay_beginner_guide_banner(img_bytes: bytes, texts: dict) -> bytes:
    """添付サンプル寄せの初心者ガイド型バナー。16:9前提で安全余白を広めに取る。"""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    import io as _io

    img = Image.open(_io.BytesIO(img_bytes)).convert("RGBA")
    W, H = img.size
    text_side = texts.get("_text_side", "left")
    if text_side == "right":
        img = ImageOps.mirror(img)
    font_bold_path = _find_font(_FONT_BOLD_CANDIDATES)
    font_reg_path = _find_font(_FONT_REG_CANDIDATES)

    def _load(path, size):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    md = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def _bbox(text, font):
        bb = md.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1], bb

    def _fit(text, path, max_sz, min_sz, max_w):
        for sz in range(max_sz, min_sz - 1, -3):
            font = _load(path, sz)
            tw, _, _ = _bbox(text, font)
            if tw <= max_w:
                return font
        return _load(path, min_sz)

    def _text(draw, xy, text, font, fill, stroke=0, stroke_fill=(255, 255, 255, 180)):
        _, _, bb = _bbox(text, font)
        x, y = xy
        draw.text((x, y - bb[1]), text, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=stroke_fill)

    template = texts.get("_template", "right_person")

    # 読み取り面を生成。背景写真は残しつつ、文字を載せる面を作る。
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    curve = texts.get("_panel_curve", "soft")
    panel_w = {"soft": 0.58, "wide": 0.62, "diagonal": 0.55}.get(curve, 0.58)
    if template in ("flatlay", "app_cards"):
        panel_w = {"soft": 0.52, "wide": 0.56, "diagonal": 0.50}.get(curve, 0.52)
    if text_side == "right":
        panel_x0 = W - int(W * panel_w)
        od.rectangle([panel_x0, 0, W, H], fill=(255, 252, 246, 218))
    else:
        od.rectangle([0, 0, int(W * panel_w), H], fill=(255, 252, 246, 218))
    if curve == "diagonal":
        if text_side == "right":
            od.polygon([(int(W * 0.55), 0), (int(W * 0.34), 0), (int(W * 0.46), H), (int(W * 0.67), H)],
                       fill=(255, 252, 246, 205))
        else:
            od.polygon([(int(W * 0.45), 0), (int(W * 0.66), 0), (int(W * 0.54), H), (int(W * 0.33), H)],
                       fill=(255, 252, 246, 205))
    else:
        if text_side == "right":
            od.pieslice([int(W * 0.20), -int(H * 0.22), int(W * 0.66), int(H * 1.22)],
                        -90, 90, fill=(255, 252, 246, 205))
        else:
            od.pieslice([int(W * 0.34), -int(H * 0.22), int(W * 0.80), int(H * 1.22)],
                        90, 270, fill=(255, 252, 246, 205))
    img = Image.alpha_composite(img, ov)
    draw = ImageDraw.Draw(img)

    palettes = {
        "blush": {"navy": (18, 41, 78, 255), "blue": (72, 104, 136, 255), "coral": (225, 128, 130, 255), "soft": (242, 173, 166, 220), "cream": (255, 252, 246, 235), "yellow": (236, 185, 77, 255), "ribbon": (219, 128, 118, 228)},
        "sage":  {"navy": (20, 55, 54, 255), "blue": (80, 118, 110, 255), "coral": (194, 126, 112, 255), "soft": (172, 205, 187, 220), "cream": (250, 253, 246, 235), "yellow": (220, 177, 82, 255), "ribbon": (125, 166, 148, 228)},
        "sky":   {"navy": (16, 38, 78, 255), "blue": (54, 103, 151, 255), "coral": (218, 119, 137, 255), "soft": (165, 202, 232, 220), "cream": (250, 253, 255, 235), "yellow": (235, 190, 81, 255), "ribbon": (105, 154, 204, 228)},
        "peach": {"navy": (58, 42, 38, 255), "blue": (100, 91, 84, 255), "coral": (219, 125, 92, 255), "soft": (244, 181, 142, 220), "cream": (255, 251, 245, 235), "yellow": (231, 179, 76, 255), "ribbon": (223, 142, 108, 228)},
        "pop_pink": {"navy": (35, 25, 55, 255), "blue": (95, 86, 180, 255), "coral": (236, 74, 117, 255), "soft": (246, 105, 143, 220), "cream": (255, 247, 251, 238), "yellow": (255, 214, 90, 255), "ribbon": (239, 76, 118, 232)},
        "royal_blue": {"navy": (8, 32, 83, 255), "blue": (46, 92, 190, 255), "coral": (236, 92, 125, 255), "soft": (84, 127, 220, 220), "cream": (248, 251, 255, 238), "yellow": (255, 210, 85, 255), "ribbon": (48, 126, 204, 232)},
        "mint_yellow": {"navy": (19, 61, 65, 255), "blue": (0, 137, 135, 255), "coral": (235, 112, 119, 255), "soft": (255, 230, 95, 220), "cream": (250, 255, 250, 238), "yellow": (255, 220, 64, 255), "ribbon": (0, 158, 147, 232)},
    }
    pal = palettes.get(texts.get("_palette_name", "blush"), palettes["blush"])
    navy = pal["navy"]
    blue = pal["blue"]
    coral_soft = pal["soft"]
    cream = pal["cream"]
    yellow = pal["yellow"]

    safe_x = int(W * 0.045) if text_side == "left" else int(W * 0.455)
    # 右上のWordPressカテゴリーバッジと競合しないよう、上部要素は少し下げる。
    safe_y = int(H * 0.105)
    text_w = int(W * 0.52)

    quiet_layout = bool(texts.get("_quiet_layout"))
    f_pre = _fit(texts["pre_title"], font_reg_path, int(H * 0.050 if quiet_layout else H * 0.055), int(H * 0.034), text_w)
    f_main = _fit(texts["main_word"], font_bold_path, int(H * 0.158 if quiet_layout else H * 0.185), int(H * 0.094), text_w)
    f_acc = _fit(texts["accent_word"], font_bold_path, int(H * 0.092 if quiet_layout else H * 0.112), int(H * 0.060), text_w)
    f_sup = _fit(texts["supplement"], font_bold_path, int(H * 0.040 if quiet_layout else H * 0.043), int(H * 0.028), int(W * 0.42))
    f_small = _load(font_bold_path, int(H * 0.030))
    f_badge = _load(font_bold_path, int(H * 0.036))
    sub_layout = texts.get("_sub_layout", "ribbon_top")

    pre_x = safe_x
    pre_y = safe_y
    if sub_layout in ("ribbon_top", "icon_cards"):
        if not texts.get("_hide_top_icon"):
            # 小さな初心者マーク風アイコン
            ix, iy = safe_x, safe_y - int(H * 0.004)
            draw.polygon([(ix, iy + 28), (ix + 26, iy + 12), (ix + 26, iy + 62), (ix, iy + 48)],
                         fill=(91, 168, 229, 255), outline=navy)
            draw.polygon([(ix + 28, iy + 12), (ix + 55, iy + 28), (ix + 55, iy + 48), (ix + 28, iy + 62)],
                         fill=(255, 209, 102, 255), outline=navy)
            pre_x = safe_x + int(W * 0.055)
    elif sub_layout == "badge_circle":
        strip_w, strip_h, _ = _bbox(texts["strip_label"], f_badge)
        draw.rounded_rectangle(
            [safe_x, safe_y - int(H * 0.020), safe_x + strip_w + int(W * 0.050), safe_y + strip_h + int(H * 0.020)],
            radius=int(H * 0.018), fill=(*pal["ribbon"][:3], 220)
        )
        _text(draw, (safe_x + int(W * 0.020), safe_y), texts["strip_label"], f_badge, (255, 255, 255, 255))
        pre_y = safe_y + int(H * 0.104)
    else:
        note_w = int(W * 0.245)
        note_h = int(H * 0.070)
        note_y = safe_y - int(H * 0.012)
        draw.polygon(
            [(safe_x, note_y), (safe_x + note_w, note_y - int(H * 0.016)),
             (safe_x + note_w - int(W * 0.012), note_y + note_h), (safe_x + int(W * 0.010), note_y + note_h + int(H * 0.010))],
            fill=(*pal["ribbon"][:3], 225)
        )
        _text(draw, (safe_x + int(W * 0.022), note_y + int(H * 0.026)), texts["strip_label"], f_badge, (255, 255, 255, 255))
        pre_y = safe_y + int(H * 0.112)

    _text(draw, (pre_x, pre_y), texts["pre_title"], f_pre, (36, 34, 31, 245))
    tw, th, _ = _bbox(texts["pre_title"], f_pre)
    draw.line([(pre_x + int(tw * 0.04), pre_y + th + int(H * 0.010)),
               (pre_x + int(tw * 0.94), pre_y + th + int(H * 0.010))],
              fill=coral_soft, width=max(4, int(H * 0.006)))

    main_y = int(H * (0.275 if quiet_layout else 0.245))
    shadow = (0, 0, 0, 34)
    _text(draw, (safe_x + 4, main_y + 4), texts["main_word"], f_main, shadow)
    _text(draw, (safe_x, main_y), texts["main_word"], f_main, navy)
    main_w, main_h, _ = _bbox(texts["main_word"], f_main)
    draw.line([(safe_x + int(main_w * 0.02), main_y + main_h + int(H * 0.018)),
               (safe_x + int(main_w * 0.98), main_y + main_h + int(H * 0.018))],
              fill=coral_soft, width=max(6, int(H * 0.011)))

    acc_y = main_y + main_h + int(H * (0.090 if quiet_layout else 0.070))
    _text(draw, (safe_x, acc_y), texts["accent_word"], f_acc, blue, stroke=1)
    _, acc_h, _ = _bbox(texts["accent_word"], f_acc)

    # 補足帯
    sup_y = acc_y + acc_h + int(H * (0.100 if quiet_layout else 0.080))
    sup_text = texts["supplement"]
    sw, sh, _ = _bbox(sup_text, f_sup)
    band_x = safe_x + int(W * 0.050)
    band_pad_x = int(W * 0.022)
    band_pad_y = int(H * 0.014)
    draw.rounded_rectangle(
        [band_x - band_pad_x, sup_y - band_pad_y, band_x + sw + band_pad_x, sup_y + sh + band_pad_y],
        radius=int(H * 0.022), fill=cream,
    )
    draw.line([(band_x - band_pad_x + 6, sup_y + sh + band_pad_y - 2),
               (band_x + sw + band_pad_x - 6, sup_y + sh + band_pad_y - 2)],
              fill=(230, 224, 214, 210), width=2)
    _text(draw, (band_x, sup_y), sup_text, f_sup, navy)

    # バッジ装飾。旅ブログなど静かなレイアウトでは省略する。
    if not texts.get("_hide_badge"):
        bw, bh, _ = _bbox(texts["badge"], f_badge)
        if sub_layout == "badge_circle":
            cx = int(W * 0.812) if text_side == "left" else int(W * 0.185)
            cy = int(H * 0.585)
            rr = int(H * 0.083)
            draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(*pal["ribbon"][:3], 230),
                         outline=(255, 255, 255, 230), width=3)
            _text(draw, (cx - bw // 2, cy - bh // 2), texts["badge"], f_badge, (255, 255, 255, 255))
        elif sub_layout == "sticky_note":
            nx = int(W * 0.392) if text_side == "left" else int(W * 0.785)
            ny = int(H * 0.710)
            nw, nh = int(W * 0.168), int(H * 0.118)
            draw.polygon([(nx, ny + 10), (nx + nw, ny), (nx + nw - 8, ny + nh), (nx + 10, ny + nh + 8)],
                         fill=(255, 223, 111, 238), outline=(214, 172, 76, 190))
            _text(draw, (nx + int(W * 0.022), ny + int(H * 0.036)), texts["badge"], f_badge, navy)
        else:
            rib_w, rib_h = int(W * 0.118), int(H * 0.195)
            rib_x = int(W * float(texts.get("_ribbon_x", 0.640)))
            if text_side == "right":
                rib_x = int(W * 0.360)
            # 右上カテゴリーバッジ用の領域を空けるため、リボンは中央寄りに少し下げる。
            rib_y = int(H * 0.045)
            ribbon = Image.new("RGBA", (rib_w, rib_h + int(H * 0.040)), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ribbon)
            rd.polygon([(0, 0), (rib_w, 0), (rib_w, rib_h), (rib_w // 2, rib_h - int(H * 0.034)), (0, rib_h)],
                       fill=pal["ribbon"])
            rd.line([(8, 0), (8, rib_h - 10), (rib_w // 2, rib_h - int(H * 0.050)),
                     (rib_w - 8, rib_h - 10), (rib_w - 8, 0)], fill=(255, 255, 255, 210), width=2)
            img.paste(ribbon, (rib_x, rib_y), ribbon)
            draw = ImageDraw.Draw(img)
            _text(draw, (rib_x + (rib_w - bw) // 2, int(H * 0.072)), texts["badge"], f_badge, (255, 255, 255, 255))

    # 下部アイコン3つ
    if not texts.get("_hide_icons"):
        labels = texts.get("icon_labels", ["文章作成", "アイデア", "時短"])
        icon_style = texts.get("_icon_style", "default")
        icon_glyphs = texts.get("_icon_glyphs", [])
        if sub_layout == "icon_cards":
            centers = [safe_x + int(W * 0.110), safe_x + int(W * 0.250), safe_x + int(W * 0.390)]
            cy = int(H * 0.825)
            r = int(H * 0.060)
        else:
            centers = [safe_x + int(W * 0.100), safe_x + int(W * 0.250), safe_x + int(W * 0.400)]
            cy = int(H * 0.835)
            r = int(H * 0.074)
        for idx, (cx, label) in enumerate(zip(centers, labels)):
            if sub_layout == "icon_cards":
                card_w, card_h = int(W * 0.120), int(H * 0.120)
                draw.rounded_rectangle([cx - card_w // 2, cy - card_h // 2, cx + card_w // 2, cy + card_h // 2],
                                       radius=int(H * 0.016), fill=(255, 255, 255, 238),
                                       outline=(230, 225, 218, 255), width=2)
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 238),
                             outline=(230, 225, 218, 255), width=2)
            glyph = icon_glyphs[idx] if idx < len(icon_glyphs) else ""
            if glyph == "search":
                draw.ellipse([cx - 28, cy - 38, cx + 20, cy + 10], outline=navy, width=4)
                draw.line([(cx + 16, cy + 6), (cx + 36, cy + 26)], fill=navy, width=4)
                draw.ellipse([cx - 8, cy - 18, cx + 2, cy - 8], fill=yellow)
            elif glyph == "note":
                draw.rounded_rectangle([cx - 30, cy - 40, cx + 28, cy + 24], radius=8, outline=navy, width=4)
                draw.line([(cx - 17, cy - 20), (cx + 15, cy - 20)], fill=yellow, width=4)
                draw.line([(cx - 17, cy - 3), (cx + 18, cy - 3)], fill=navy, width=3)
                draw.line([(cx - 17, cy + 13), (cx + 10, cy + 13)], fill=navy, width=3)
            elif glyph == "sparkle":
                draw.polygon([(cx, cy - 42), (cx + 10, cy - 10), (cx + 42, cy), (cx + 10, cy + 10), (cx, cy + 42), (cx - 10, cy + 10), (cx - 42, cy), (cx - 10, cy - 10)],
                             fill=(255, 255, 255, 0), outline=navy)
                draw.polygon([(cx, cy - 28), (cx + 7, cy - 7), (cx + 28, cy), (cx + 7, cy + 7), (cx, cy + 28), (cx - 7, cy + 7), (cx - 28, cy), (cx - 7, cy - 7)],
                             fill=yellow)
            elif glyph == "check":
                draw.rounded_rectangle([cx - 34, cy - 34, cx + 34, cy + 34], radius=12, outline=navy, width=4)
                draw.line([(cx - 20, cy + 2), (cx - 5, cy + 18), (cx + 24, cy - 18)], fill=yellow, width=6)
            elif glyph == "heart":
                draw.ellipse([cx - 24, cy - 24, cx - 2, cy - 2], fill=yellow, outline=navy, width=3)
                draw.ellipse([cx + 2, cy - 24, cx + 24, cy - 2], fill=yellow, outline=navy, width=3)
                draw.polygon([(cx - 26, cy - 10), (cx + 26, cy - 10), (cx, cy + 30)], fill=yellow, outline=navy)
            elif glyph == "home":
                draw.line([(cx - 32, cy + 4), (cx, cy - 34), (cx + 32, cy + 4)], fill=navy, width=5)
                draw.rounded_rectangle([cx - 22, cy + 2, cx + 22, cy + 34], radius=4, outline=navy, width=4)
                draw.rectangle([cx - 6, cy + 14, cx + 8, cy + 34], fill=yellow, outline=navy)
            elif glyph == "book":
                draw.rounded_rectangle([cx - 34, cy - 34, cx - 2, cy + 30], radius=6, outline=navy, width=4)
                draw.rounded_rectangle([cx + 2, cy - 34, cx + 34, cy + 30], radius=6, outline=navy, width=4)
                draw.line([(cx, cy - 28), (cx, cy + 34)], fill=navy, width=3)
                draw.line([(cx - 24, cy - 12), (cx - 10, cy - 12)], fill=yellow, width=4)
            elif glyph == "yen":
                _text(draw, (cx - 18, cy - 34), "¥", _load(font_bold_path, int(H * 0.070)), navy)
                draw.line([(cx - 28, cy + 16), (cx + 28, cy + 16)], fill=yellow, width=4)
            elif icon_style == "curiosity":
                if idx == 0:
                    draw.ellipse([cx - 28, cy - 38, cx + 20, cy + 10], outline=navy, width=4)
                    draw.line([(cx + 16, cy + 6), (cx + 36, cy + 26)], fill=navy, width=4)
                    draw.ellipse([cx - 8, cy - 18, cx + 2, cy - 8], fill=yellow)
                elif idx == 1:
                    draw.rounded_rectangle([cx - 28, cy - 38, cx + 28, cy + 22], radius=8, outline=navy, width=4)
                    draw.line([(cx - 16, cy - 18), (cx + 16, cy - 18)], fill=yellow, width=4)
                    draw.line([(cx - 16, cy - 2), (cx + 12, cy - 2)], fill=navy, width=3)
                    draw.line([(cx - 16, cy + 12), (cx + 18, cy + 12)], fill=navy, width=3)
                else:
                    draw.polygon([(cx, cy - 42), (cx + 10, cy - 10), (cx + 42, cy), (cx + 10, cy + 10), (cx, cy + 42), (cx - 10, cy + 10), (cx - 42, cy), (cx - 10, cy - 10)],
                                 fill=(255, 255, 255, 0), outline=navy)
                    draw.polygon([(cx, cy - 28), (cx + 7, cy - 7), (cx + 28, cy), (cx + 7, cy + 7), (cx, cy + 28), (cx - 7, cy + 7), (cx - 28, cy), (cx - 7, cy - 7)],
                                 fill=yellow)
            elif icon_style == "lifestyle":
                if idx == 0:
                    draw.arc([cx - 30, cy - 34, cx + 30, cy + 26], 210, 520, fill=navy, width=4)
                    draw.polygon([(cx + 28, cy - 16), (cx + 42, cy - 26), (cx + 38, cy - 8)], fill=yellow)
                elif idx == 1:
                    draw.line([(cx - 24, cy + 12), (cx, cy - 30), (cx + 24, cy + 12)], fill=navy, width=4)
                    draw.line([(cx - 14, cy + 12), (cx - 14, cy + 34), (cx + 14, cy + 34), (cx + 14, cy + 12)], fill=navy, width=4)
                else:
                    draw.ellipse([cx - 24, cy - 32, cx + 24, cy + 16], outline=navy, width=4)
                    draw.arc([cx - 32, cy - 2, cx + 32, cy + 44], 200, 340, fill=yellow, width=4)
            elif idx == 0:
                draw.line([(cx - 22, cy - 5), (cx + 14, cy - 38)], fill=navy, width=4)
                draw.polygon([(cx + 14, cy - 38), (cx + 26, cy - 48), (cx + 21, cy - 31)], outline=navy, fill=(255, 255, 255, 0))
                draw.line([(cx - 25, cy + 18), (cx + 22, cy + 8)], fill=yellow, width=3)
            elif idx == 1:
                draw.ellipse([cx - 22, cy - 42, cx + 22, cy + 2], outline=navy, width=4)
                draw.rectangle([cx - 12, cy + 0, cx + 12, cy + 14], outline=navy, width=3)
                draw.line([(cx, cy - 52), (cx, cy - 62)], fill=yellow, width=4)
                draw.line([(cx - 30, cy - 30), (cx - 42, cy - 36)], fill=yellow, width=4)
                draw.line([(cx + 30, cy - 30), (cx + 42, cy - 36)], fill=yellow, width=4)
            else:
                draw.ellipse([cx - 34, cy - 44, cx + 34, cy + 24], outline=navy, width=4)
                draw.line([(cx, cy - 38), (cx, cy - 5)], fill=navy, width=4)
                draw.line([(cx, cy - 5), (cx + 24, cy - 22)], fill=navy, width=4)
                draw.arc([cx - 38, cy - 48, cx + 38, cy + 28], 300, 45, fill=yellow, width=4)
            lw, _, _ = _bbox(label, f_small)
            _text(draw, (cx - lw // 2, cy + r + int(H * 0.020)), label, f_small, navy)

    # さりげない装飾
    for sx, sy in [(int(W * 0.525), int(H * 0.125)), (int(W * 0.545), int(H * 0.760)), (int(W * 0.205), int(H * 0.935))]:
        draw.polygon([(sx, sy - 13), (sx + 5, sy - 4), (sx + 15, sy), (sx + 5, sy + 4), (sx, sy + 13), (sx - 5, sy + 4), (sx - 15, sy), (sx - 5, sy - 4)],
                     fill=(239, 173, 132, 190))

    out = Image.new("RGB", img.size, (255, 255, 255))
    out.paste(img, mask=img.split()[3])
    buf = _io.BytesIO()
    out.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _is_career_site_theme(title: str, article_theme: str = "") -> bool:
    """はた楽ナビ向けの転職・副業・キャリア領域かを判定する。"""
    haystack = f"{title} {article_theme}"
    if any(k in article_theme for k in ("AI", "テクノロジー", "オンライン学習", "プログラミング", "資格", "スキルアップ", "雑学", "生活情報", "飛騨", "旅行・観光")):
        return False
    keys = (
        "転職", "副業", "キャリア", "仕事", "派遣", "フリーランス", "求人",
        "給与", "職場", "就職", "面接", "履歴書", "職務経歴書", "メンタル",
        "ストレス", "辞めたい", "社会復帰", "ブランク", "在宅ワーク",
        "アルバイト", "パート", "正社員",
    )
    return any(k in haystack for k in keys)


def _extract_title_head_keyword(title: str) -> str:
    """タイトル冒頭の重要KWを短く抜き出す。"""
    head = re.split(r'[がをにはでとの、。！!？?｜|:：・]', title.strip(), maxsplit=1)[0]
    head = re.sub(r'[「」『』【】\[\]（）()]', '', head).strip()
    if 2 <= len(head) <= 12:
        return head
    return head[:12] if len(head) > 12 else ""


def _select_icon_labels(title: str, site: str = "aivice") -> list[str]:
    """記事内容に応じて下部アイコンの文言を変える。"""
    if site == "curiosity":
        if any(k in title for k in ("なぜ", "理由", "意味", "由来", "違い")):
            return random.choice([["理由", "違い", "豆知識"], ["なぜ？", "意味", "背景"]])
        if any(k in title for k in ("グルメ", "食べ物", "料理", "レシピ", "スイーツ", "カフェ")):
            return random.choice([["味", "選び方", "保存"], ["食べ方", "栄養", "比較"]])
        if any(k in title for k in ("健康", "睡眠", "疲労", "ダイエット", "ストレス", "運動")):
            return random.choice([["体調", "習慣", "注意点"], ["原因", "対策", "目安"]])
        if any(k in title for k in ("節約", "お得", "料金", "値段", "口コミ", "評判")):
            return random.choice([["料金", "比較", "口コミ"], ["お得", "注意点", "選び方"]])
        if any(k in title for k in ("ドラマ", "映画", "アニメ", "配信", "キャスト", "声優")):
            return random.choice([["配信", "見どころ", "順番"], ["作品", "人物", "話題"]])
        if any(k in title for k in ("コスメ", "メイク", "スキンケア", "ファッション")):
            return random.choice([["使い方", "選び方", "口コミ"], ["色味", "成分", "比較"]])
        return random.choice([["理由", "方法", "注意点"], ["豆知識", "比較", "使い方"], ["気になる", "調べた", "まとめ"]])

    if site == "hida":
        if any(k in title for k in ("宿", "ホテル", "旅館", "民宿", "泊")):
            return random.choice([["立地", "温泉", "予算"], ["部屋", "食事", "口コミ"]])
        if any(k in title for k in ("温泉", "下呂", "露天風呂", "日帰り入浴")):
            return random.choice([["湯めぐり", "効能", "日帰り"], ["宿", "料金", "癒し"]])
        if any(k in title for k in ("グルメ", "ランチ", "カフェ", "食べ歩き", "飛騨牛", "名物")):
            return random.choice([["名物", "お店", "予算"], ["食べ歩き", "ランチ", "お土産"]])
        if any(k in title for k in ("白川郷", "古い町並", "高山", "古川", "観光", "モデルコース", "日帰り")):
            return random.choice([["見どころ", "所要時間", "アクセス"], ["散策", "写真", "休憩"]])
        if any(k in title for k in ("桜", "紅葉", "雪", "祭", "春", "夏", "秋", "冬")):
            return random.choice([["季節", "服装", "写真"], ["行事", "景色", "時間"]])
        return random.choice([["見どころ", "アクセス", "予算"], ["散策", "宿", "グルメ"], ["季節", "写真", "思い出"]])

    if site == "career":
        if any(k in title for k in ("保育士", "介護士", "看護師")):
            return random.choice([["人間関係", "転職", "相談"], ["疲れ", "改善", "次の職場"]])
        if any(k in title for k in ("面接", "選考")):
            return random.choice([["質問対策", "逆質問", "印象"], ["準備", "受け答え", "内定"]])
        if any(k in title for k in ("履歴書", "職務経歴書", "志望動機")):
            return random.choice([["書き方", "自己PR", "添削"], ["実績", "強み", "応募"]])
        if any(k in title for k in ("副業", "在宅", "フリーランス")):
            return random.choice([["在宅", "収入", "継続"], ["案件", "単価", "時間"]])
        if any(k in title for k in ("辞めたい", "ストレス", "メンタル", "疲れ")):
            return random.choice([["不安", "整理", "相談"], ["休む", "守る", "次の一歩"]])
        return random.choice([["準備", "比較", "行動"], ["不安", "整理", "一歩"], ["仕事", "お金", "将来"]])

    if "画像生成" in title:
        return random.choice([["無料", "商用利用", "日本語"], ["画質", "料金", "使い方"]])
    if any(k in title for k in ("ブログ", "SEO", "ライティング")):
        return random.choice([["構成", "執筆", "改善"], ["SEO", "時短", "品質"]])
    if any(k in title for k in ("副業", "稼ぐ", "収益", "アフィリエイト")):
        return random.choice([["案件", "収益", "継続"], ["始め方", "ツール", "収入"]])
    if any(k in title for k in ("比較", "おすすめ", "選")):
        return random.choice([["料金", "機能", "選び方"], ["比較", "無料", "用途"]])
    return random.choice([["文章作成", "アイデア", "時短"], ["はじめ方", "比較", "活用"], ["スマホ", "副業", "効率化"]])


def _is_hida_site_theme(title: str, article_theme: str = "") -> bool:
    """飛騨の思い出向けの旅行・地域情報かを判定する。"""
    haystack = f"{title} {article_theme}"
    specific_keys = (
        "飛騨", "高山", "白川郷", "古川", "下呂", "奥飛騨", "岐阜",
        "古い町並", "飛騨牛", "朝市",
    )
    if any(k in haystack for k in specific_keys):
        return True
    if not any(k in article_theme for k in ("飛騨", "高山", "地域情報", "旅行・観光")):
        return False
    generic_keys = (
        "観光", "旅行", "旅", "温泉", "宿", "ホテル", "旅館", "民宿",
        "グルメ", "ランチ", "カフェ", "食べ歩き", "お土産",
        "祭り", "世界遺産", "モデルコース", "日帰り",
        "アクセス", "紅葉", "雪景色", "桜",
    )
    return any(k in haystack for k in generic_keys)


def _is_curiosity_site_theme(title: str, article_theme: str = "") -> bool:
    """気になることブログ向けの雑学・生活情報領域かを判定する。"""
    haystack = f"{title} {article_theme}"
    if any(k in article_theme for k in ("雑学", "エンタメ", "生活情報")):
        return True
    if any(k in article_theme for k in ("AI", "テクノロジー", "オンライン学習", "プログラミング", "資格", "スキルアップ", "転職", "キャリア", "飛騨", "旅行・観光")):
        return False
    keys = (
        "なぜ", "理由", "意味", "違い", "方法", "使い方", "豆知識",
        "暮らし", "生活", "トレンド", "話題", "気になる", "調べてみた",
        "食べ物", "健康", "お金", "ことば", "口コミ", "評判",
    )
    return any(k in haystack for k in keys)


def _is_learning_site_theme(title: str, article_theme: str = "") -> bool:
    """オンライン学習ナビ向けの学習・資格・スキルアップ領域かを判定する。"""
    haystack = f"{title} {article_theme}"
    if any(k in article_theme for k in ("オンライン学習", "プログラミング", "資格", "スキルアップ")):
        return True
    keys = (
        "オンライン学習", "プログラミング", "資格", "スキルアップ", "独学",
        "通信教育", "スクール", "学習", "勉強", "塾", "小学生",
        "Python", "JavaScript", "TOEIC", "ITパスポート", "Web制作",
    )
    return any(k in haystack for k in keys)


def _select_learning_template(title: str) -> str:
    """オンライン学習ナビ用アイキャッチの構図をタイトルから選ぶ。"""
    if any(k in title for k in ("プログラミング", "Python", "JavaScript", "Web制作", "IT")):
        return random.choice(["coding_desk", "study_compare", "online_lesson"])
    if any(k in title for k in ("塾", "通信教育", "小学生", "算数", "英語", "国語")):
        return random.choice(["kids_study", "study_compare", "notebook_learning"])
    if any(k in title for k in ("資格", "TOEIC", "ITパスポート")):
        return random.choice(["notebook_learning", "online_lesson", "study_compare"])
    return random.choice(["online_lesson", "notebook_learning", "study_compare"])


def _build_learning_background_prompt(title: str, template: str) -> str:
    """オンライン学習ナビ向けの背景写真プロンプト。文字はPillowで後合成する。"""
    base = (
        "16:9 horizontal Japanese online learning media thumbnail background. "
        "Calm, trustworthy, practical study lifestyle, clean editorial style, not flashy advertising. "
        "Keep one side clean for large Japanese typography and keep key objects away from outer 8% edges. "
        "Palette: clean white, soft blue, pale yellow, warm wood, gentle green, deep navy accents. "
        "ABSOLUTELY NO text, no letters, no numbers, no logos, no watermark. "
        f"Topic feeling: {title}. "
    )
    if template == "coding_desk":
        return base + "Bright desk with laptop showing abstract blank code-like blocks, notebook, coffee, plant, morning light. No readable screen text."
    if template == "kids_study":
        return base + "Warm home study desk for a child: open notebook, pencils, tablet corner, parent support feeling, soft daylight, no faces needed."
    if template == "study_compare":
        return base + "Organized comparison desk with laptop, tablet, notebook, blank cards, pen, calm learning decision mood."
    if template == "notebook_learning":
        return base + "Close-up of notebook, tablet, pen, sticky notes as blank shapes, tea cup, soft natural light, focused study mood."
    return base + "Online lesson scene at a clean desk with laptop, headphones, notebook, tablet, warm natural light, generous negative space."


def _learning_overlay_texts(title: str, texts: dict, template: str) -> dict:
    """オンライン学習ナビ向けにタイトル文字を短く整える。"""
    head_kw = _extract_title_head_keyword(title)
    main = head_kw or texts.get("main_word", "").strip() or "オンライン学習"
    accent = "学び方ガイド"
    strip = "学習ナビ"

    if "プログラミングスクール" in title:
        main = "プログラミング"
        accent = "スクール比較"
    elif "塾" in title and "通信教育" in title:
        main = "塾と通信教育"
        accent = "選び方ガイド"
    elif "算数" in title and "苦手" in title:
        main = "算数苦手を"
        accent = "克服する方法"
    elif "独学" in title:
        accent = "独学の進め方"
    elif "資格" in title:
        accent = "資格の始め方"

    glyph_pool = ["book", "note", "check", "search", "sparkle", "home"]
    return {
        "strip_label": strip,
        "pre_title": random.choice(["迷わない学び方", "挫折しない学習法", "次の一歩を整理"]),
        "main_word": main[:12],
        "accent_word": accent[:12],
        "supplement": random.choice(["自分に合う学び方を選ぶ", "独学とスクールを整理", "続けやすい方法を見つける"]),
        "badge": random.choice(["保存版", "やさしく解説", "比較"]),
        "icon_labels": random.choice([["独学", "費用", "比較"], ["教材", "時間", "継続"], ["学習法", "料金", "選び方"]]),
        "_palette_name": random.choice(["sky", "mint_yellow", "sage", "royal_blue"]),
        "_template": template,
        "_panel_curve": random.choice(["soft", "wide", "diagonal"]),
        "_ribbon_x": random.choice([0.610, 0.640, 0.670]),
        "_sub_layout": random.choice(["ribbon_top", "icon_cards"]),
        "_text_side": random.choice(["left", "left", "right"]),
        "_hide_badge": random.choice([True, False]),
        "_hide_icons": random.choice([True, False, False]),
        "_hide_top_icon": True,
        "_quiet_layout": True,
        "_icon_style": "dynamic",
        "_icon_glyphs": random.sample(glyph_pool, 3),
    }


def _select_curiosity_template(title: str) -> str:
    """気になることブログ用アイキャッチの構図をタイトルから選ぶ。"""
    if any(k in title for k in ("なぜ", "理由", "意味", "由来", "違い", "豆知識", "ことば")):
        pool = ["question_flatlay", "notebook_closeup", "soft_illustration"]
    elif any(k in title for k in ("グルメ", "食べ物", "料理", "レシピ", "スイーツ", "カフェ")):
        pool = ["food_table", "kitchen_lifestyle", "question_flatlay"]
    elif any(k in title for k in ("健康", "睡眠", "疲労", "ダイエット", "ストレス", "運動")):
        pool = ["wellness_morning", "notebook_closeup", "home_lifestyle"]
    elif any(k in title for k in ("節約", "お得", "料金", "値段", "口コミ", "評判", "比較")):
        pool = ["desk_compare", "notebook_closeup", "home_lifestyle"]
    elif any(k in title for k in ("ドラマ", "映画", "アニメ", "配信", "キャスト", "声優")):
        pool = ["living_entertainment", "soft_illustration", "question_flatlay"]
    elif any(k in title for k in ("コスメ", "メイク", "スキンケア", "ファッション")):
        pool = ["beauty_flatlay", "home_lifestyle", "desk_compare"]
    else:
        pool = ["question_flatlay", "notebook_closeup", "home_lifestyle", "soft_illustration"]

    history_path = _OUTPUT_DIR.parent / "eyecatch_template_history.json"
    recent: list[str] = []
    try:
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
            recent = [str(x) for x in data.get("curiosity", [])][-4:]
    except Exception:
        recent = []

    available = [tpl for tpl in pool if tpl not in recent[-2:]] or pool
    selected = random.choice(available)
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
        seq = [str(x) for x in data.get("curiosity", [])]
        seq.append(selected)
        data["curiosity"] = seq[-12:]
        history_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return selected


def _build_curiosity_background_prompt(title: str, template: str) -> str:
    """気になることブログ向けの背景写真プロンプト。文字はPillowで後合成する。"""
    palette = random.choice([
        "warm ivory, soft yellow, dusty blue, sage green, natural wood",
        "clean white, pale mint, muted coral, light beige, ink navy",
        "cream, soft sky blue, apricot, warm gray, botanical green",
        "linen white, butter yellow, light teal, soft pink, charcoal",
    ])
    base = (
        "16:9 horizontal Japanese curiosity lifestyle blog thumbnail background. "
        "Friendly magazine editorial style, everyday question, helpful and approachable, not flashy YouTube thumbnail. "
        "Keep all important objects away from the outer 8% edges and keep one side clean for large Japanese typography. "
        f"Palette: {palette}. ABSOLUTELY NO text, no letters, no numbers, no logos, no watermark. "
        f"Topic feeling: {title}. "
    )
    if template == "question_flatlay":
        return (
            base +
            "A bright desk flatlay with notebook, blank colorful sticky notes, mug, pen, small plant, magnifying glass, soft daylight. "
            "Curious everyday research mood with clean negative space."
        )
    if template == "notebook_closeup":
        return (
            base +
            "Close-up of hands writing in a notebook beside a smartphone, tea cup, small household object related to the topic, warm natural light. "
            "No readable writing, calm and useful mood, generous negative space."
        )
    if template == "food_table":
        return (
            base +
            "Cozy kitchen or dining table with simple food, plate, cup, napkin, small ingredients, natural morning light. "
            "Editorial lifestyle food scene, clean negative space for typography."
        )
    if template == "kitchen_lifestyle":
        return (
            base +
            "A warm home kitchen counter with utensils, ingredients, towel, small plant, soft sunlight, everyday practical atmosphere. "
            "No people or hands only, no readable labels, clean negative space."
        )
    if template == "wellness_morning":
        return (
            base +
            "Calm wellness morning scene: glass of water, towel, simple breakfast, notebook, soft curtain light, fresh and reassuring mood. "
            "Clean negative space for typography."
        )
    if template == "desk_compare":
        return (
            base +
            "Organized comparison desk with laptop corner, calculator, receipt-like blank paper, pen, small household item, coffee. "
            "No readable text, practical and trustworthy, clean negative space."
        )
    if template == "living_entertainment":
        return (
            base +
            "Cozy living room entertainment scene: sofa, tablet or TV remote, blanket, tea, soft lamp light, relaxed curiosity mood. "
            "No screens with readable content, clean negative space."
        )
    if template == "beauty_flatlay":
        return (
            base +
            "Soft beauty and lifestyle flatlay with skincare bottles without labels, compact mirror, towel, flowers, warm daylight. "
            "Clean and gentle, one side empty for typography."
        )
    return (
        base +
        "Bright home lifestyle desk with notebook, phone, mug, small plant, and a few blank pastel cards, everyday curiosity mood. "
        "Clean negative space for typography."
    )


def _curiosity_overlay_texts(title: str, texts: dict, template: str) -> dict:
    """気になることブログ向けにタイトル文字を短く整える。"""
    head_kw = _extract_title_head_keyword(title)
    main = head_kw or texts.get("main_word", "").strip() or "気になる"
    accent = texts.get("accent_word", "").strip() or "やさしく解説"
    strip = "気になる話"
    hide_icons = random.choice([True, True, False])
    hide_badge = random.choice([True, True, False])

    if any(k in title for k in ("なぜ", "理由", "意味", "由来", "違い")):
        accent = "理由をやさしく解説"
        strip = "なるほど豆知識"
    elif any(k in title for k in ("グルメ", "食べ物", "料理", "レシピ", "スイーツ", "カフェ")):
        accent = "おいしい豆知識"
        strip = "暮らしのグルメ"
    elif any(k in title for k in ("健康", "睡眠", "疲労", "ダイエット", "ストレス", "運動")):
        accent = "毎日を整えるヒント"
        strip = "生活習慣メモ"
    elif any(k in title for k in ("節約", "お得", "料金", "値段", "口コミ", "評判", "比較")):
        accent = "損しない選び方"
        strip = "お得メモ"
    elif any(k in title for k in ("ドラマ", "映画", "アニメ", "配信", "キャスト", "声優")):
        accent = "話題をチェック"
        strip = "エンタメメモ"
    elif any(k in title for k in ("コスメ", "メイク", "スキンケア", "ファッション")):
        accent = "選び方ガイド"
        strip = "美容メモ"

    if "算数" in title and "苦手" in title and "克服" in title:
        main = "算数苦手を"
        accent = "克服する方法"
        strip = "学びのメモ"
    elif "国語" in title and "苦手" in title and "克服" in title:
        main = "国語苦手を"
        accent = "克服する方法"
        strip = "学びのメモ"
    elif "英語" in title and "苦手" in title and "克服" in title:
        main = "英語苦手を"
        accent = "克服する方法"
        strip = "学びのメモ"
    elif "ITスキル" in title:
        main = "ITスキル"
        accent = "学び方ガイド"
        strip = "学びのメモ"
    elif "未経験" in title and any(k in title for k in ("学ぶ", "独学", "スクール")):
        main = "未経験から"
        accent = "学び方ガイド"
        strip = "学びのメモ"

    sub_layout = random.choice(["ribbon_top", "icon_cards"]) if not hide_icons else "ribbon_top"
    glyph_pool = ["search", "note", "sparkle", "check", "heart", "home", "book", "yen"]
    return {
        "strip_label": strip[:9],
        "pre_title": random.choice(["ふと気になる疑問", "暮らしの小さな発見", "知ると少し楽しい"]),
        "main_word": main[:12],
        "accent_word": accent[:12],
        "supplement": random.choice(["日常の疑問をすっきり整理", "知っておくと少し便利", "読みやすくまとめました"]),
        "badge": random.choice(["へぇ！", "保存版", "やさしく解説"]),
        "icon_labels": _select_icon_labels(title, site="curiosity"),
        "_palette_name": random.choice(["sky", "peach", "mint_yellow", "blush"]),
        "_template": template,
        "_panel_curve": random.choice(["soft", "wide", "diagonal"]),
        "_ribbon_x": random.choice([0.610, 0.640, 0.670]),
        "_sub_layout": sub_layout,
        "_text_side": random.choice(["left", "left", "right"]),
        "_hide_badge": hide_badge,
        "_hide_icons": hide_icons,
        "_hide_top_icon": True,
        "_quiet_layout": True,
        "_icon_style": "dynamic",
        "_icon_glyphs": random.sample(glyph_pool, 3),
    }


def _select_hida_template(title: str) -> str:
    """飛騨の思い出用アイキャッチの構図をタイトルから選ぶ。"""
    if any(k in title for k in ("鬼仏", "与平", "飢饉", "昔話", "民話", "再生物語", "鬼と呼ばれた")):
        pool = ["old_mountain_village", "poor_old_town", "town_evening"]
    elif any(k in title for k in ("宿", "ホテル", "旅館", "民宿", "泊", "温泉", "下呂", "奥飛騨")):
        pool = ["ryokan_room", "onsen_morning", "town_evening", "travel_flatlay"]
    elif any(k in title for k in ("グルメ", "ランチ", "カフェ", "食べ歩き", "飛騨牛", "名物", "お土産")):
        pool = ["local_food", "market_walk", "travel_flatlay", "town_morning"]
    elif any(k in title for k in ("白川郷", "古い町並", "高山", "古川", "観光", "モデルコース", "日帰り", "朝市")):
        pool = ["town_morning", "market_walk", "town_evening", "travel_flatlay"]
    elif any(k in title for k in ("桜", "紅葉", "雪", "祭", "春", "夏", "秋", "冬")):
        pool = ["seasonal_path", "town_evening", "ryokan_room", "market_walk"]
    else:
        pool = ["town_morning", "travel_flatlay", "ryokan_room", "market_walk"]

    history_path = _OUTPUT_DIR.parent / "eyecatch_template_history.json"
    recent: list[str] = []
    try:
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
            recent = [str(x) for x in data.get("hida", [])][-4:]
    except Exception:
        recent = []

    available = [tpl for tpl in pool if tpl not in recent[-2:]] or pool
    selected = random.choice(available)
    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if history_path.exists():
            data = json.loads(history_path.read_text(encoding="utf-8"))
        seq = [str(x) for x in data.get("hida", [])]
        seq.append(selected)
        data["hida"] = seq[-12:]
        history_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return selected


def _build_hida_background_prompt(title: str, template: str) -> str:
    """飛騨の思い出向けの背景写真プロンプト。文字はPillowで後合成する。"""
    palette = random.choice([
        "warm ivory, natural wood brown, moss green, muted indigo, soft morning gold",
        "snow white, cedar wood, quiet charcoal, pale blue gray, warm lantern amber",
        "rice paper ivory, old town brown, river green, dusty rose, soft beige",
        "cream, hinoki wood, deep forest green, warm gray, subdued terracotta",
    ])
    base = (
        "16:9 horizontal Japanese local travel magazine thumbnail background. "
        "A quiet Hida Takayama travel memory mood, editorial lifestyle photography, warm and trustworthy, not a sales banner. "
        "Keep all important scenery and people away from the outer 8% edges so WordPress crops will not cut them. "
        f"Palette: {palette}. ABSOLUTELY NO text, no letters, no numbers, no logos, no watermark. "
        "No decorative symbols, no sparkle marks, no star glyphs, no ✧-like ornaments anywhere. "
        f"Topic feeling: {title}. "
    )
    if template == "ryokan_room":
        return (
            base +
            "A calm Japanese ryokan room with tatami, low wooden table, tea set, yukata fabric, shoji window, soft morning light. "
            "A hint of mountain scenery outside the window. Left or right side has clean negative space for Japanese typography."
        )
    if template == "onsen_morning":
        return (
            base +
            "A serene hot spring travel atmosphere: wooden bath entrance, steam, hand towel, warm lantern light, natural stone and greenery. "
            "No visible nudity, no crowded people. Large clean negative space for typography."
        )
    if template == "local_food":
        return (
            base +
            "A cozy Hida local food table: simple Japanese set meal, Hida beef skewer or local sweets, ceramic dishes, wooden tray, tea. "
            "Natural window light, inviting but calm. One side has clean negative space for typography."
        )
    if template == "market_walk":
        return (
            base +
            "Morning market and old town walk in Hida Takayama: wooden storefronts, noren curtains, small local goods, soft pedestrians blurred in background. "
            "Warm daylight, gentle travel snapshot feeling. One side has clean negative space for typography."
        )
    if template == "town_evening":
        return (
            base +
            "Hida old town street at quiet golden hour, wooden machiya houses, warm lanterns beginning to glow, stone path slightly wet, nostalgic atmosphere. "
            "No readable signs. Large clean negative space for typography."
        )
    if template == "old_mountain_village":
        return (
            base +
            "An old poor mountain village in historical Hida, weathered wooden houses, dark cedar walls, rough dirt path, distant snowy mountains, "
            "cold wind atmosphere, muted winter light, no modern objects, no cars, no electric wires. "
            "A humble and solemn human drama mood, with one side kept clean for Japanese typography."
        )
    if template == "poor_old_town":
        return (
            base +
            "A narrow old Hida street from long ago, simple wooden houses with worn lattice doors, patched eaves, straw bundles, quiet poverty, "
            "overcast light, earthy colors, no modern signs, no shop banners, no vehicles. "
            "Nostalgic but severe atmosphere, clean negative space for Japanese typography."
        )
    if template == "seasonal_path":
        season = random.choice([
            "autumn red leaves along a quiet river path",
            "soft winter snow on wooden roofs and a calm street",
            "fresh summer green mountains and a clear river",
            "spring blossoms near a traditional wooden street",
        ])
        return (
            base +
            f"A seasonal Hida travel scene: {season}, quiet and poetic, natural light, local landscape. "
            "One side has clean negative space for typography."
        )
    return (
        base +
        "A neat travel flatlay on a wooden table: map, notebook, camera, train ticket-like blank paper, tea cup, small local souvenir. "
        "No readable text. Calm natural light and generous negative space for typography."
    )


def _extract_quoted_work_title(title: str) -> str:
    """記事タイトル中の小説・作品名を抜き出す。例: 『ヘアピンと鼻水』。"""
    m = re.search(r"[『「](.+?)[』」]", title or "")
    return m.group(1).strip() if m else ""


def _hida_overlay_texts(title: str, texts: dict, template: str) -> dict:
    """飛騨の思い出向けにタイトル文字を短く整える。"""
    head_kw = _extract_title_head_keyword(title)
    work_title = _extract_quoted_work_title(title)
    main = head_kw or texts.get("main_word", "").strip() or "飛騨旅"
    accent = texts.get("accent_word", "").strip() or "旅のしおり"
    strip = "飛騨の思い出"

    if work_title and "小説" in title:
        main = work_title
        accent = "飛騨弁の短編小説" if "飛騨弁" in title else "短編小説"
        strip = "ものがたり"
    elif "白川郷" in title:
        main = "白川郷"
        accent = "やさしい旅ガイド"
        strip = "世界遺産さんぽ"
    elif "高山" in title:
        main = "飛騨高山" if "飛騨" in title else "高山"
        accent = "町歩きガイド"
        strip = "高山さんぽ"
    elif "下呂" in title or "温泉" in title:
        main = "温泉旅" if not head_kw else head_kw
        accent = "癒しの過ごし方"
        strip = "湯けむり旅"
    elif any(k in title for k in ("宿", "ホテル", "旅館", "民宿")):
        main = head_kw or "宿選び"
        accent = "失敗しない選び方"
        strip = "宿のしおり"
    elif any(k in title for k in ("グルメ", "ランチ", "カフェ", "食べ歩き", "飛騨牛", "名物")):
        main = head_kw or "飛騨グルメ"
        accent = "味わう旅"
        strip = "おいしい飛騨"
    elif any(k in title for k in ("モデルコース", "日帰り", "観光")):
        main = head_kw or "飛騨観光"
        accent = "迷わない歩き方"
        strip = "旅の道しるべ"

    if work_title and "小説" in title:
        pre_title = random.choice(["飛騨の物語", "心に残る短編", "語り継ぐ物語"])
        if any(k in title for k in ("再生", "鬼仏", "与平", "鬼と呼ばれた")):
            supplement = random.choice(["凍った心がほどけていく", "人との出会いが男を変える", "赦しと再生の物語"])
        elif any(k in title for k in ("初恋", "恋", "想い")):
            supplement = random.choice(["あの日の気持ちを物語に", "淡い想いをたどる", "静かに読める飛騨の短編"])
        else:
            supplement = random.choice(["人のぬくもりを描く短編", "胸に残る飛騨の物語", "静かに読める飛騨の短編"])
    else:
        pre_title = random.choice(["旅の記憶", "静かな町歩き", "飛騨の一日"])
        supplement = random.choice(["土地の空気まで楽しむ", "静かに過ごす旅時間", "思い出に残る旅の準備"])

    return {
        "strip_label": strip[:9],
        "pre_title": pre_title,
        "main_word": main[:12],
        "accent_word": accent[:12],
        "supplement": supplement,
        "badge": "",
        "icon_labels": [],
        "_palette_name": random.choice(["sage", "peach", "sky", "mint_yellow"]),
        "_template": template,
        "_panel_curve": random.choice(["soft", "wide", "diagonal"]),
        "_ribbon_x": random.choice([0.595, 0.625, 0.655]),
        "_sub_layout": "ribbon_top",
        "_text_side": random.choice(["left", "left", "right"]),
        "_hide_badge": True,
        "_hide_icons": True,
        "_quiet_layout": True,
    }


def _select_career_template(title: str) -> str:
    """はた楽ナビ用アイキャッチの構図をタイトルから選ぶ。"""
    if any(k in title for k in ("面接", "履歴書", "職務経歴書", "志望動機", "選考")):
        return random.choice(["document_desk", "office_person", "interview"])
    if any(k in title for k in ("辞めたい", "ストレス", "メンタル", "疲れ", "職場", "人間関係")):
        return random.choice(["window_thinking", "cafe_calm", "document_desk"])
    if any(k in title for k in ("副業", "フリーランス", "在宅", "収入", "給与", "稼ぐ")):
        return random.choice(["home_work", "cafe_calm", "document_desk"])
    return random.choice(["office_person", "document_desk", "cafe_calm", "home_work"])


def _build_career_background_prompt(title: str, template: str) -> str:
    """はた楽ナビ向けの背景写真プロンプト。文字はPillowで後合成する。"""
    palette = random.choice([
        "warm ivory, navy, soft green, natural wood, muted coral accents",
        "clean white, slate blue, pale yellow, warm gray, soft beige",
        "cream, forest green, dusty blue, light wood, gentle peach",
        "off-white, charcoal navy, sage, muted gold, linen beige",
    ])
    base = (
        "16:9 horizontal Japanese career lifestyle blog thumbnail background. "
        "Polished but human editorial style, trustworthy career media, not corporate stock. "
        "Keep all key objects away from outer 8% edges. "
        f"Palette: {palette}. ABSOLUTELY NO text, no letters, no numbers, no logos, no watermark. "
        f"Topic feeling: {title}. "
    )
    if template == "document_desk":
        return (
            base +
            "Top-down desk flatlay with resume-like blank papers, notebook, pen, laptop corner, coffee cup, small plant. "
            "Calm natural daylight, organized but lived-in. One side has clean negative space for Japanese typography."
        )
    if template == "interview":
        return (
            base +
            "Soft office meeting room, two people implied by hands and notebooks only, no clear faces, interview preparation atmosphere. "
            "Warm window light, tidy table, subtle plant. Left or right side has clean negative space for typography."
        )
    if template == "window_thinking":
        return (
            base +
            "A Japanese adult in their late 20s to 30s, side/back view by a bright window, holding a mug, thoughtful but hopeful. "
            "Cozy room, soft morning light, notebook and laptop nearby. Large clean negative space for typography."
        )
    if template == "home_work":
        return (
            base +
            "Home workspace with laptop, planner, smartphone, warm tea, soft linen curtain, relaxed remote work atmosphere. "
            "Japanese adult hands or back view only, practical and calm. Clean negative space for typography."
        )
    if template == "cafe_calm":
        return (
            base +
            "Quiet cafe table near a window, laptop, notebook, coffee, soft greenery, calm career planning mood. "
            "Japanese adult in soft side profile or hands only, natural and not glamorous. Clean negative space for typography."
        )
    return (
        base +
        "Bright modern office corner, Japanese adult in business casual, side profile or back view, laptop and notebook. "
        "Natural window light, plants, calm and hopeful career change atmosphere. Clean negative space for typography."
    )


def _career_overlay_texts(title: str, texts: dict, template: str) -> dict:
    """はた楽ナビ向けにタイトル文字を短く整える。"""
    head_kw = _extract_title_head_keyword(title)
    main = head_kw or texts.get("main_word", "").strip() or "働き方"
    accent = texts.get("accent_word", "").strip() or "解説"
    strip = texts.get("strip_label", "").strip() or "はた楽ナビ"
    glyph_pool = ["note", "check", "home", "heart", "search", "book", "yen"]

    if head_kw:
        main = head_kw

    if "転職" in title:
        main = head_kw or "転職"
        accent = "失敗しない進め方"
        strip = "転職ガイド"
    elif "副業" in title:
        main = "副業"
        accent = "はじめ方ガイド"
        strip = "副業・在宅"
    elif "面接" in title:
        main = "面接対策"
        accent = "よくある不安を整理"
        strip = "選考対策"
    elif "履歴書" in title or "職務経歴書" in title:
        main = "書類作成"
        accent = "伝わる書き方"
        strip = "応募準備"
    elif "仕事行きたくない" in title:
        main = "仕事行きたくない"
        accent = "5月の不調サイン" if "5月" in title else "原因と対処法"
        strip = "心を整える"
    elif "辞めたい" in title or "ストレス" in title or "メンタル" in title or "病気" in title:
        main = "仕事の悩み"
        accent = "原因と対処法"
        strip = "心を整える"

    quiet = any(k in title for k in ("仕事行きたくない", "辞めたい", "ストレス", "メンタル", "病気", "疲れ"))
    return {
        "strip_label": strip[:8],
        "pre_title": random.choice(["ひとりで抱えない", "心と働き方を整える", "無理しないために"]) if quiet else random.choice(["迷ったときの道しるべ", "働き方を整える", "次の一歩を考える"]),
        "main_word": main[:12],
        "accent_word": accent[:12],
        "supplement": random.choice(["症状を整理して早めに休む", "無理せず状態を見直す", "つらさを言葉にして整理"]) if quiet else random.choice(["不安を整理して次へ進む", "リアルな悩みに寄り添う", "自分に合う働き方を探す"]),
        "badge": random.choice(["やさしく解説", "保存版", "迷わない"]),
        "icon_labels": _select_icon_labels(title, site="career"),
        "_palette_name": random.choice(["sage", "sky", "peach", "royal_blue", "mint_yellow"]),
        "_template": template,
        "_panel_curve": random.choice(["soft", "wide", "diagonal"]),
        "_ribbon_x": random.choice([0.615, 0.645, 0.675]),
        "_sub_layout": "ribbon_top" if quiet else random.choice(["ribbon_top", "badge_circle", "sticky_note", "icon_cards"]),
        "_text_side": random.choice(["left", "right"]),
        "_icon_style": "dynamic",
        "_icon_glyphs": random.sample(glyph_pool, 3),
        "_quiet_layout": quiet,
        "_hide_badge": quiet,
        "_hide_icons": random.choice([True, False]) if quiet else False,
        "_hide_top_icon": quiet,
    }


def _save_debug_image(img_bytes: bytes, image_type: str, model: str) -> None:
    """生成画像を output/images/ にローカル保存する（品質確認用）。"""
    try:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        model_short = model.split("/")[-1].replace(".", "-")  # "FLUX.1-schnell" → "FLUX1-schnell"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _OUTPUT_DIR / f"{ts}_{image_type}_{model_short}.jpg"
        path.write_bytes(img_bytes)
        print(f"[IMAGE] 保存: {path}")
    except Exception as e:
        print(f"[IMAGE] ローカル保存スキップ: {e}")


def generate_eyecatch_image(keyword: str, article_theme: str = "", variant: str = "a") -> bytes:
    """
    アイキャッチ画像を生成する。
    variant:
      "a" — シンプルフラットイラスト路線
      "b" — 人物×ライフスタイル路線（AI生成のみ）
      "c" — 完成形サムネ一括生成（gpt-image-2 がテキスト込みデザインを1枚で生成）
    wp_context.get_eyecatch_model() でブログ別モデルを取得し、
    未設定の場合は FLUX.1-schnell を使用する。
    """
    model = wp_context.get_eyecatch_model() or _DEFAULT_HF_MODEL
    print(f"[IMAGE] eyecatch model: {model}  variant: {variant}")

    # variant "c": 2段階生成 ① 背景画像（テキストなし）② HTML/CSSタイポグラフィ合成
    if variant == "c":
        print("[IMAGE] 世界観コンセプト生成中...")
        concept   = _generate_ad_concept(keyword, article_theme)
        bg_prompt = _build_background_only_prompt(keyword, concept)
        print(f"[IMAGE] 背景生成中 (テキストなし) placement={concept.get('text_placement')}...")
        bg_bytes  = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        from PIL import Image as _PILImg
        import io as _io_tmp
        _tmp = _PILImg.open(_io_tmp.BytesIO(bg_bytes))
        bg_w, bg_h = _tmp.size
        del _tmp
        print(f"[IMAGE] 雑誌表紙タイポグラフィ合成中 ({bg_w}×{bg_h})...")
        final_bytes = _render_magazine_overlay(bg_bytes, concept, bg_w, bg_h)
        _save_debug_image(final_bytes, "eyecatch_vc", model)
        return final_bytes

    prompt, is_template = _build_eyecatch_prompt(keyword, article_theme, variant)
    if is_template:
        full_prompt = prompt
    else:
        style_hint = _get_style_hint()
        suffix = (
            f"flat design illustration, {style_hint}, minimal icons, "
            "no people, no hands, no face, no human, no text, no watermark, "
            "high quality digital art"
        )
        full_prompt = f"{prompt}, {suffix}"

    print(f"[IMAGE] eyecatch prompt: {full_prompt[:80]}...")
    img_bytes = _call_model(model, full_prompt, W_EYECATCH, H_EYECATCH)
    _save_debug_image(img_bytes, f"eyecatch_v{variant}", model)
    return img_bytes


def generate_eyecatch_variants(
    keyword: str,
    article_theme: str = "",
    count: int = 2,
) -> list[bytes]:
    """
    記事ごとに複数パターンのアイキャッチを生成する（variant "c" 専用）。
    各パターンは独立したコンセプトで生成するため、毎回異なる世界観になる。
    戻り値: 生成した JPEG バイト列のリスト（count 件）
    """
    model = wp_context.get_eyecatch_model() or _DEFAULT_HF_MODEL
    results: list[bytes] = []
    for i in range(count):
        print(f"\n[IMAGE] ─── variant {i + 1}/{count} ────────────────")
        concept   = _generate_ad_concept(keyword, article_theme)
        bg_prompt = _build_background_only_prompt(keyword, concept)
        print(f"[IMAGE] 背景生成中 placement={concept.get('text_placement')}...")
        bg_bytes  = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        from PIL import Image as _PILImg
        import io as _io_tmp
        _tmp = _PILImg.open(_io_tmp.BytesIO(bg_bytes))
        bg_w, bg_h = _tmp.size
        del _tmp
        print(f"[IMAGE] タイポグラフィ合成中 ({bg_w}×{bg_h})...")
        img_bytes = _render_magazine_overlay(bg_bytes, concept, bg_w, bg_h)
        _save_debug_image(img_bytes, f"eyecatch_vc_p{i + 1}", model)
        results.append(img_bytes)
    return results


def generate_lifestyle_eyecatch_image(
    title: str,
    keyword: str = "",
    article_theme: str = "",
) -> bytes:
    """
    Codex用: AIライフスタイルブランド向けの完成アイキャッチを生成する。

    背景はテキストなしで生成し、PILで読みやすい日本語タイポグラフィを後合成する。
    既存の variant="c" よりも、初心者向けブログの一覧画面で読める
    サムネイル感を少し強めたディレクター用ルート。
    """
    model = wp_context.get_eyecatch_model() or _DEFAULT_HF_MODEL
    topic = keyword or title
    print(f"[IMAGE] lifestyle eyecatch model: {model}")

    if _is_hida_site_theme(title, article_theme):
        print("[IMAGE] 飛騨の思い出向け・旅メディア型バナーで生成します")
        hida_template = _select_hida_template(title)
        print(f"[IMAGE] hida template: {hida_template}")
        bg_prompt = _build_hida_background_prompt(title, hida_template)
        bg_bytes = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        texts = _hida_overlay_texts(title, _generate_overlay_texts(title), hida_template)
        final_bytes = _overlay_beginner_guide_banner(bg_bytes, texts)
        _save_debug_image(final_bytes, "codex_hida_travel_eyecatch", model)
        return final_bytes

    if _is_learning_site_theme(title, article_theme):
        print("[IMAGE] オンライン学習ナビ向け・学習メディア型バナーで生成します")
        learning_template = _select_learning_template(title)
        print(f"[IMAGE] learning template: {learning_template}")
        bg_prompt = _build_learning_background_prompt(title, learning_template)
        bg_bytes = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        texts = _learning_overlay_texts(title, _generate_overlay_texts(title), learning_template)
        final_bytes = _overlay_beginner_guide_banner(bg_bytes, texts)
        _save_debug_image(final_bytes, "codex_webstudy_learning_eyecatch", model)
        return final_bytes

    if _is_career_site_theme(title, article_theme):
        print("[IMAGE] はた楽ナビ向けキャリア型バナーで生成します")
        career_template = _select_career_template(title)
        print(f"[IMAGE] career template: {career_template}")
        bg_prompt = _build_career_background_prompt(title, career_template)
        bg_bytes = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        texts = _career_overlay_texts(title, _generate_overlay_texts(title), career_template)
        final_bytes = _overlay_beginner_guide_banner(bg_bytes, texts)
        _save_debug_image(final_bytes, "codex_hataraku_career_eyecatch", model)
        return final_bytes

    if _is_curiosity_site_theme(title, article_theme):
        print("[IMAGE] 気になることブログ向け・雑学ライフ型バナーで生成します")
        curiosity_template = _select_curiosity_template(title)
        print(f"[IMAGE] curiosity template: {curiosity_template}")
        bg_prompt = _build_curiosity_background_prompt(title, curiosity_template)
        bg_bytes = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        texts = _curiosity_overlay_texts(title, _generate_overlay_texts(title), curiosity_template)
        final_bytes = _overlay_beginner_guide_banner(bg_bytes, texts)
        _save_debug_image(final_bytes, "codex_hapipo8_curiosity_eyecatch", model)
        return final_bytes

    if _is_beginner_guide_title(title):
        print("[IMAGE] 初心者ガイド型バナーで生成します")
        guide_template = _select_beginner_guide_template(title)
        print(f"[IMAGE] guide template: {guide_template}")
        bg_prompt = _build_beginner_guide_background_prompt(title, guide_template)
        bg_bytes = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)
        texts = _guide_overlay_texts(title, _generate_overlay_texts(title), guide_template)
        final_bytes = _overlay_beginner_guide_banner(bg_bytes, texts)
        _save_debug_image(final_bytes, "codex_beginner_guide_eyecatch", model)
        return final_bytes

    print("[IMAGE] 感情・世界観コンセプト生成中...")
    concept = _generate_ad_concept(topic, article_theme or title)
    scene = concept.get("scene", "")
    concept["scene"] = (
        f"{scene}. If a person is visible, make them a young Japanese adult in their early 20s, "
        "natural and approachable, soft casual knit or simple lifestyle outfit, calm expression. "
        "The image should feel like a quiet AI lifestyle magazine, not a sales thumbnail."
    )

    bg_prompt = _build_background_only_prompt(topic, concept)
    print(f"[IMAGE] ライフスタイル背景生成中 placement={concept.get('text_placement')}...")
    bg_bytes = _call_model(model, bg_prompt, W_EYECATCH, H_EYECATCH)

    print("[IMAGE] タイトル解析・サムネ文字生成中...")
    texts = _generate_overlay_texts(title)
    if "AI" in title or "ChatGPT" in title or "GPT" in title:
        texts.setdefault("strip_label", "初心者OK")
    texts["supplement"] = texts.get("supplement") or "暮らしと仕事が少し整う"

    print("[IMAGE] 読みやすいタイポグラフィ合成中...")
    final_bytes = _overlay_eyecatch_text(bg_bytes, texts)
    _save_debug_image(final_bytes, "codex_lifestyle_eyecatch", model)
    return final_bytes


def _build_h2_image_prompt(h2_title: str, keyword: str) -> str:
    """
    H2タイトル・キーワードから記事テーマに合ったFLUXプロンプトをClaude Haikuで生成する。
    フラットデザイン・かわいいビジネス系・パステルカラー・人物なし。
    Haiku呼び出し失敗時はフォールバックプロンプトを使用する。
    """
    style_hint = _get_style_hint()
    motifs_hint = _get_motifs_hint()
    motifs_line = (
        f"Focus on simple icons: {motifs_hint}."
        if motifs_hint else
        "Focus on icons and objects that visually represent the section topic. Do NOT use laptops or generic business icons unless the topic is about business/tech."
    )
    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    f"Create a short English image prompt (20-30 words) for a blog section illustration "
                    f"about: keyword='{keyword}', section='{h2_title}'. "
                    f"Style: {style_hint}. "
                    f"{motifs_line} No people, no hands, no faces. "
                    "Avoid: robots, cyberpunk, neon colors, dark backgrounds, clutter, realistic photos. "
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
        return (
            f"flat design icons for {safe_topic}, "
            f"{style_hint}"
        )


def generate_h2_image(h2_title: str, keyword: str = "") -> bytes:
    """
    H2記事内画像を生成する（フラットデザイン・人物なし）。
    wp_context.get_article_image_model() でブログ別モデルを取得し、
    未設定の場合は FLUX.1-schnell を使用する。
    """
    model = wp_context.get_article_image_model() or _DEFAULT_HF_MODEL
    print(f"[IMAGE] h2 model: {model}")

    topic = h2_title or keyword
    prompt = _build_h2_image_prompt(topic, keyword)
    style_hint = _get_style_hint()
    suffix = (
        f"flat design illustration, {style_hint}, minimal icons, "
        "no people, no hands, no face, no human, no text, no watermark, "
        "high quality digital art"
    )
    full_prompt = f"{prompt}, {suffix}"

    print(f"[IMAGE] h2 prompt: {full_prompt[:80]}...")
    img_bytes = _call_model(model, full_prompt, W_EYECATCH, H_EYECATCH)
    _save_debug_image(img_bytes, "h2", model)
    return img_bytes


def generate_image_for_article(keyword: str, article_theme: str = "", article_type: str = "", **kwargs) -> bytes:
    """
    アイキャッチ生成のメインエントリ。
    eyecatch_model が gpt-image-2 の場合は variant="c"（コンセプト駆動・ライフスタイル誌風）を使用。
    それ以外は variant="a"（FLUXフラットイラスト）を使用。
    """
    model = wp_context.get_eyecatch_model() or _DEFAULT_HF_MODEL
    if model == "gpt-image-2":
        return generate_eyecatch_image(keyword, article_theme, variant="c")
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
                f"For a blog header illustration about '{keyword}' titled '{title}', "
                "describe specific flat design icons and objects (15-20 words). "
                "Style: cute and modern, kawaii business style, pastel colors, minimal icons. "
                "Focus on: simple icons representing the topic (laptop, speech bubbles, stars, coins, "
                "checkmarks, calendars, lightbulbs, charts, etc.). "
                "Avoid: people, hands, faces, robots, circuits, neon colors, dark elements. "
                "No explanation. Only the description.\n"
                "Examples: "
                "'cute flat icons of laptop and speech bubbles with stars, soft pink and mint pastel tones' "
                "'minimal flat design with calendar, coins and upward arrow, soft lavender and cream gradient'"
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
        "modern minimal style, elegant design, soft pastel tones, warm neutral colors, "
        "clean and sophisticated, no text, no watermark, high quality\n\n"
        f'Place one large "AIVice" watermark in the empty area, opacity 8–12%.\n\n'
        f'Add the text "{en_title}" in white or soft white, '
        f"blending naturally with the background."
    )

    print(f"[imagefx] 背景:{bg_label} / ビジュアル:{theme_desc[:50]}")
    print(f"[imagefx] タイトル(英): {en_title}")
    return prompt
