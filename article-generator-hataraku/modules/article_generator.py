"""
Step 4: Claude APIで記事構成を生成（WordPress SWELL形式）
"""
import json
from datetime import date
import anthropic
from config import ANTHROPIC_API_KEY
from modules.image_generator import generate_imagefx_prompt
from modules.fact_checker import needs_fact_check, check_facts, detect_person_keyword, PERSON_ARTICLE_INSTRUCTION
from modules.api_guard import check_stop, record_usage

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_AFFILIATE_LINES_PLACEHOLDER = "__AFFILIATE_LINES__"

SYSTEM_PROMPT = f"""\
# 役割
あなたは、SEOに最適化された自然な日本語で文章構造（H2・H3の設計）を行う専門ライターです。
AI特有の不自然さを排除し、読者にとって読みやすく、検索意図に沿った構成を作成します。

# サイト情報
__SITE_INFO__

# 出力ルール
- WordPress SWELLの構造に完全準拠（独自CSSやstyle禁止）
- タイトルは30〜40字程度。キーワードを自然に含め、数字・メリット・疑問形などでクリックを促す（例：「AIボイスレコーダーアプリiPhoneおすすめ7選！文字起こし・要約まで自動化」）
- H2は最大3つ（すべてにキーフレーズを含める）
- H2見出しは疑問形だけでなく「断言・メリット提示・比較・方法提示」など自然に使い分ける。毎回「〜とは？」「〜できる？」にしないこと（例：✅「iPhoneで使えるAIボイスレコーダーアプリの選び方」✅「おすすめアプリ7選を徹底比較」❌「AIボイスレコーダーアプリとは？」）
- H3は合計14〜18本（抽象語禁止、質問形・行動導線を中心に）
- 各H2直下に、そのH2に属するH3タイトルをis-style-num_circleのリスト形式で列挙してから、各H3見出し＋本文のセットを続ける
- 各H3の直下に本文（300〜400字）を追加（SWELLのparagraphブロック）
- 本文トーン: 読者に寄り添うやさしい表現、専門語はカッコで補足
- 各H3の本文は合計400〜500字・段落2〜3つ（1段落120〜150字）に分け、「結論→詳細→具体例」の流れで書く
- 各段落はそれぞれ個別の<!-- wp:paragraph -->ブロックで囲む
- 本文内で①②③のような番号付き列挙が必要な場合は、テキスト内に書かずWordPressの番号付きリストブロックで出力する（段落ブロックとリストブロックを分けて出力）
- FAQは8〜10問（各回答200字以上）
- 結論ファーストな構成
- タグは最大5個（重要度の高いものを厳選）
- まとめチェックリストの直後に締めの文章（150〜200字）を1段落追加する。2〜3文構成で書くこと。構成例：①読者が感じているであろう迷いや苦労に共感する一文（「〜って、慣れるまでどれを選べばいいか本当に迷いますよね」など自然な表現で）→②やさしく背中を押す一文（「気になったものがあれば、まず公式サイトでスペックだけでも確認してみるのがおすすめです」など）。「まず〇〇を試してみてください」「〇〇を選べば間違いありません」のような押しつけがましい表現は使わないこと。キーワードに関連するアフィリリンク登録済みツールがあれば1つだけ自然な文脈で組み込む（リンクのために文章を歪めない）。該当ツールがない場合はリンクなしでよい（登録済みツール以外の公式リンクは不可）

# リンク挿入ルール（厳守）

## アフィリリンク登録済みツール → アフィリリンクのみ・公式リンク不要
以下のツールが記事に登場する場合は、**アフィリリンクのみ**を挿入すること。
公式サイトへのリンクは絶対に追加しないこと。同じツールに2つ以上リンクを貼らないこと。
リンク形式: <a href="{{URL}}" target="_blank" rel="noopener noreferrer">{{ツール名}}</a>

__AFFILIATE_LINES__

## アフィリリンク未登録ツール → 公式サイトリンクのみ
上記リスト以外のツールを紹介する場合のみ、公式サイトへのリンクを貼ること。
形式: <a href="{{公式URL}}" target="_blank" rel="noopener noreferrer">{{ツール名}}公式サイト</a>

## リンク共通ルール
- アフィリ登録済みツールに公式リンクを重ねて貼ることは禁止
- 各ツール: 記事全体で1回のみ（初出時に貼る）
- **記事全体で必ず1つ以上の外部リンク（href="https://..."）を含めること**（アフィリリンク・公式サイトリンクどちらでも可）
- Wikipediaへのリンクは絶対に禁止。存在確認できない架空URLも禁止
- 外部リンクが1つも入らない場合は、記事中で紹介する公的機関・業界団体・政府サイト・ブランド公式サイト・大手メディアのうち最も関連性の高いものへのリンクを1つ追加すること

# カテゴリー（WordPressのID）
- 生成AI・チャット・仕事術: 1397
- クリエイティブ・デザイン: 1396
- AI学習・スクール・キャリア: 1398
- 文字起こし・議事録・ボイスメモ: 1375
- ChatGPT活用・設定: 1371
- プロンプト・呪文: 1366
- Midjourney・にじジャーニー: 1367
- AI画像生成・イラスト: 1365
- AI動画生成・編集: 1376
- Canva・デザインツール: 1369
- PLAUD NOTE: 1399
- Notta: 1400
- AIスクール・資格: 1385
- AIライティング: 1373
- Stable Diffusion: 1368
- プログラミング・開発: 1382
- 資料作成・タスク管理: 1383
- SNS運用（YouTube/インスタ）: 1378
- AI英会話・語学: 1384
- AI販売・商用利用: 1379
- 音声合成・音楽生成: 1386
- iPhone・スマホ録音・アプリ: 1401
- ICレコーダー・機材: 1402
- SMARTスピーカー・AIデバイス: 1407
- Grok（AIアシスタント）: 1406
- Gemini・Google AI: 1372
- クラウドワークス・案件: 1380

# 出力フォーマット（必ずこの順番で contentフィールドに格納）

## 1. 冒頭文（250〜300字）
<!-- wp:paragraph -->
<p>{{冒頭文（キーフレーズ1回）}}</p>
<!-- /wp:paragraph -->

## 2. この記事のポイント
<!-- wp:loos/cap-block {{"className":"is-style-onborder_ttl2"}} -->
<div class="swell-block-capbox cap_box is-style-onborder_ttl2"><div class="cap_box_ttl"><span>この記事のポイント</span></div><div class="cap_box_content">
<ul class="wp-block-list is-style-check_list">
<li>{{ポイント1}}</li>
<li>{{ポイント2}}</li>
<li>{{ポイント3}}</li>
<li>{{キーフレーズを含むポイント4}}</li>
</ul>
</div></div>
<!-- /wp:loos/cap-block -->

## 3. H2・H3構成（H2を最大3回繰り返す）
各H2の直下に、そのH2配下のH3タイトルをis-style-num_circleリストで列挙する。
その後、各H3を「見出しブロック＋paragraphブロック（300〜400字）」のセットで出力する。

<!-- wp:heading -->
<h2 class="wp-block-heading">{{H2（キーフレーズ含む）}}</h2>
<!-- /wp:heading -->

<!-- wp:list {{"ordered":true,"className":"is-style-num_circle"}} -->
<ol class="wp-block-list is-style-num_circle">
<li>{{H3見出し1}}</li>
<li>{{H3見出し2}}</li>
<li>{{H3見出し3}}</li>
<li>{{H3見出し4}}</li>
<li>{{H3見出し5}}</li>
</ol>
<!-- /wp:list -->

<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">{{H3見出し1}}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{{結論・まとめ（120〜150字）。リンクルールに従いアフィリリンクまたは公式リンクを適切に挿入。}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{詳細説明（120〜150字）}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{具体例・補足（120〜150字）。番号付き列挙が必要な場合は段落の後にリストブロックを追加。}}</p>
<!-- /wp:paragraph -->

{{番号付き列挙が必要な場合のみ追加。不要なら省略。}}
<!-- wp:list {{"ordered":true}} -->
<ol class="wp-block-list">
<li>{{項目1}}</li>
<li>{{項目2}}</li>
<li>{{項目3}}</li>
</ol>
<!-- /wp:list -->

<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">{{H3見出し2}}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{{結論（120〜150字）}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{詳細（120〜150字）}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{具体例（120〜150字）}}</p>
<!-- /wp:paragraph -->

（H3を4〜6本繰り返す）
（H2を最大3回繰り返す）

## 4. よくある質問（8〜10問、各回答200字以上）
<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">よくある質問</h3>
<!-- /wp:heading -->

<!-- wp:loos/faq {{"iconRadius":"rounded","qIconStyle":"fill-custom","aIconStyle":"fill-custom","outputJsonLd":true,"titleTag":"h4","className":"is-style-faq-stripe"}} -->
<div class="swell-block-faq -icon-rounded is-style-faq-stripe" data-q="fill-custom" data-a="fill-custom">
<div class="swell-block-faq__item">
<h4 class="faq_q">{{質問文}}</h4>
<div class="faq_a">
<p>{{回答文（200字以上）}}</p>
</div>
</div>
{{8〜10問繰り返し}}
</div>
<!-- /wp:loos/faq -->

## 5. まとめ
<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">まとめ｜{{まとめタイトル}}</h3>
<!-- /wp:heading -->

<!-- wp:list {{"className":"is-style-check_list"}} -->
<ul class="wp-block-list is-style-check_list">
<li>{{まとめ項目1〜10}}</li>
</ul>
<!-- /wp:list -->

<!-- wp:paragraph -->
<p>{{締めの文章（150〜200字・2〜3文）。①読者の迷いや苦労に共感する一文 → ②やさしく背中を押す一文。「まず〇〇を試してみてください」のような押しつけ表現は禁止。アフィリリンク登録済みツールが文脈に自然に合う場合のみ1つ挿入。}}</p>
<!-- /wp:paragraph -->

"""

# ============================================================
# PLAUD NOTE / Notta 優先紹介 — 対象キーワード分類
# ============================================================
_PLAUD_NOTTA_TERMS = [
    # ボイスレコーダー系
    "ボイスレコーダー", "録音", "音声録音", "icレコーダー", "ic レコーダー",
    # 文字起こし系
    "文字起こし", "テキスト化", "書き起こし",
    # 議事録系
    "議事録", "会議録", "ミーティングメモ",
    # 録音ツール系
    "録音アプリ", "録音ツール",
    # メモ系
    "ボイスメモ", "音声メモ",
    # 要約系
    "ai要約", "自動要約",
]

_PLAUD_NOTTA_INSTRUCTION = """\

## PLAUD NOTE・Notta 優先紹介ルール（このキーワードには必須）
このキーワードはボイスレコーダー／文字起こし／議事録／録音系に該当します。
以下のルールを厳守してください。

1. 記事の最初のH2またはH3（冒頭のセクション）で必ずPLAUD NOTEを1位・最初に紹介する
2. 冒頭文（250〜300字の段落）でPLAUD NOTEまたはNottaに言及する場合は**必ずアフィリリンクを挿入**する
3. 各H3本文でPLAUD NOTEまたはNottaが**初登場する段落に必ずアフィリリンクを挿入**する（同一H3内2回目以降は不要）
4. 1記事全体でPLAUD NOTEへのリンクを**最低3回以上**挿入すること（冒頭・各H3初出・まとめ訴求文などで達成する）
5. PLAUD NOTEを紹介した同じセクション内またはすぐ後のH3でNottaも紹介し、Nottaのアフィリリンク（https://workup-ai.com/notta）も挿入する
6. 両ツールの紹介は「押しつけ感」がなく読者に有益な形で自然に組み込むこと
"""


# ============================================================
# 記事タイプ別 構造設定
# target_length → (h3_min, h3_max, faq_min, faq_max, max_tokens)
# ============================================================
_ARTICLE_STRUCTURE: dict[int, tuple[int, int, int, int, int]] = {
    9000: (14, 18, 8, 10, 12000),  # MONETIZE: 比較・レビュー系・高品質
    6000: ( 8, 12, 5,  7, 16000),  # LONGTAIL: 標準SEO記事
    3000: ( 5,  7, 3,  4, 12000),  # FUTURE / TREND: 短め情報記事
}

def _get_structure(target_length: int) -> tuple[int, int, int, int, int]:
    """target_lengthに最も近い構造設定を返す。"""
    if target_length in _ARTICLE_STRUCTURE:
        return _ARTICLE_STRUCTURE[target_length]
    closest = min(_ARTICLE_STRUCTURE.keys(), key=lambda k: abs(k - target_length))
    return _ARTICLE_STRUCTURE[closest]


def _build_system_prompt(
    h3_min: int, h3_max: int, faq_min: int, faq_max: int,
    asp_links: dict | None = None,
) -> str:
    """
    H3本数・FAQ問数・ブログ固有アフィリリンクに応じてSYSTEM_PROMPTを組み立てる。
    asp_links は {名称: URL} の辞書。None または空の場合は「(なし)」と表示。
    ブログ情報（サイト名・テーマ等）は wp_context から動的に取得する。
    """
    prompt = SYSTEM_PROMPT

    # サイト情報（ブログ固有）を動的に差し込む
    try:
        from modules import wp_context
        meta = wp_context.get_blog_meta()
        display_name = meta.get("display_name", "")
        wp_url       = meta.get("wp_url", wp_context.get_wp_url())
        genre        = meta.get("genre", meta.get("genre_detail", ""))
        target       = meta.get("target", "")
        site_lines = f"- サイト名: {display_name}（{wp_url}）\n- テーマ: {genre}"
        if target:
            site_lines += f"\n- 対象読者: {target}"
    except Exception:
        site_lines = "- （ブログ情報未設定）"
    prompt = prompt.replace("__SITE_INFO__", site_lines)

    # アフィリリンク（ブログ固有）を動的に差し込む
    if asp_links:
        affiliate_lines = "\n".join(f"- {name}: {url}" for name, url in asp_links.items())
        affiliate_lines += (
            "\n\n**重要**: 比較・おすすめ・ランキング系の記事では、"
            "上記登録済みサービスをすべて記事内で必ず1回以上紹介し、各サービスにアフィリリンクを挿入すること。"
            "各サービスは個別のH3セクションまたは比較表で取り上げること。"
        )
    else:
        affiliate_lines = "（このブログにはアフィリリンク登録なし）"
    prompt = prompt.replace(_AFFILIATE_LINES_PLACEHOLDER, affiliate_lines)

    prompt = prompt.replace(
        "H3は合計14〜18本（抽象語禁止、質問形・行動導線を中心に）",
        f"H3は合計{h3_min}〜{h3_max}本（抽象語禁止、質問形・行動導線を中心に）",
    )
    prompt = prompt.replace(
        "FAQは8〜10問（各回答200字以上）",
        f"FAQは{faq_min}〜{faq_max}問（各回答200字以上）",
    )
    prompt = prompt.replace(
        "## 4. よくある質問（8〜10問、各回答200字以上）",
        f"## 4. よくある質問（{faq_min}〜{faq_max}問、各回答200字以上）",
    )
    prompt = prompt.replace(
        "{8〜10問繰り返し}",
        f"{{{faq_min}〜{faq_max}問繰り返し}}",
    )
    return prompt


def _get_keyword_research(keyword: str) -> dict:
    """
    Claude Haiku でキーワードリサーチを一括生成する。

    Returns:
        {
            "suggest":  ["サジェスト候補", ...],   # 8〜10個
            "paa":      ["PAA質問文", ...],         # 5〜8個
            "longtail": ["ロングテール複合KW", ...] # 8〜10個
        }
    """
    check_stop()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": (
                f"「{keyword}」のSEO記事向けにキーワードリサーチを行ってください。\n"
                "以下のJSONのみ出力してください（```json などのコードブロック記号は不要）：\n"
                '{"suggest":["サジェスト候補8〜10個（Googleサジェスト想定）"],'
                '"paa":["PAA形式の質問文5〜8個（〜とは・〜やり方・〜比較・〜おすすめなど）"],'
                '"longtail":["3〜5語のロングテール複合キーワード8〜10個"]}'
            ),
        }],
    )
    record_usage("claude-haiku-4-5-20251001",
                 msg.usage.input_tokens, msg.usage.output_tokens, f"kw_research:{keyword}")
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        result = json.loads(raw)
        return {
            "suggest":  result.get("suggest", [])[:10],
            "paa":      result.get("paa", [])[:8],
            "longtail": result.get("longtail", [])[:10],
        }
    except Exception:
        return {"suggest": [], "paa": [], "longtail": []}


def _get_lsi_keywords(keyword: str) -> str:
    """
    Claude Haiku でキーワードの共起語・LSIキーワードを生成する。

    Returns:
        「用語1、用語2、...」形式の文字列（プロンプトに直接埋め込む用）
    """
    check_stop()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"「{keyword}」というキーワードの記事でSEO的に重要な共起語・LSIキーワードを"
                f"15個生成してください。"
                f"読者が同時に検索・気にするであろう関連語句を中心に。"
                f"出力は「語句1、語句2、語句3、...」の形式のみ。説明不要。"
            ),
        }],
    )
    record_usage("claude-haiku-4-5-20251001",
                 msg.usage.input_tokens, msg.usage.output_tokens, f"lsi:{keyword}")
    raw = msg.content[0].text.strip()
    return raw.splitlines()[0] if raw else ""


def _needs_plaud_notta(keyword: str) -> bool:
    """キーワードがPLAUD NOTE/Notta優先紹介の対象かどうかを判定する。"""
    kw = keyword.lower()
    return any(term in kw for term in _PLAUD_NOTTA_TERMS)


# ============================================================
# 検索意図タイプ検出・トーン指示
# ============================================================

_INTENT_SYMPATHY_WORDS = [
    "辞めたい", "疲れた", "不安", "悩み", "ストレス", "しんどい", "つらい",
    "迷って", "怖い", "不満", "嫌", "やめたい", "向いていない", "続かない",
    "人間関係", "職場", "パワハラ", "ブラック", "しんどい", "きつい",
]
_INTENT_COMPARISON_WORDS = [
    "比較", "ランキング", "どちら", "どれ", "違い", "選び方", "メリット",
    "デメリット", "向いてる", "まとめ", "一覧", "どこ",
]
_INTENT_PURCHASE_WORDS = [
    "登録", "申し込み", "始め方", "使い方", "料金", "評判", "口コミ",
    "無料", "体験", "試し", "手順", "流れ", "やり方", "方法",
]

_TONE_INSTRUCTIONS: dict[str, str] = {
    "sympathy": """\
## 検索意図タイプ: 共感系（寄り添い調）
このキーワードで検索するユーザーは「誰かにわかってほしい」「背中を押してほしい」という気持ちを持っています。
文体ルール：
- 冒頭や各H3の冒頭で読者の気持ちに共感する一文を入れる（例：「転職活動って、本当に疲れますよね」）
- 「〜という方は多いのではないでしょうか」「〜という状況、よく聞きます」など共感フレーズを自然に使う
- 専門的・事務的な語調は避け、「一緒に考えましょう」「大丈夫です」のような温かみのある言葉を使う
- 失敗談・苦労話を交えて「あなただけじゃない」と感じさせる表現を盛り込む
""",
    "comparison": """\
## 検索意図タイプ: 比較系（客観的・データ重視）
このキーワードで検索するユーザーは「正しい情報で冷静に選びたい」という気持ちを持っています。
文体ルール：
- 感情的な表現を抑え、事実・数字・比較の切り口を中心に構成する
- 「A社は〜、B社は〜という特徴があります」「向いている人・向いていない人」の軸で整理する
- 「〜がベスト」「絶対〜」などの断定は避け、「〜という観点では〜が優れています」という客観表現を使う
- 読者自身が判断できる情報を提供することを最優先に考える
""",
    "purchase": """\
## 検索意図タイプ: 購買直前（背中を押す）
このキーワードで検索するユーザーは「もう少しの後押しがほしい」という段階にいます。
文体ルール：
- 冒頭・まとめで「まず一歩踏み出してみましょう」のような前向きなフレーズを使う
- 「無料だからリスクはない」「最悪うまくいかなくても〜」などハードルを下げる言葉を自然に入れる
- 登録・申し込みの手順を具体的かつ簡潔に説明する
- ベネフィットを最後に改めて強調し「よし、やってみよう」と思えるよう締める
""",
}


def _detect_search_intent(keyword: str) -> str:
    """
    キーワードから検索意図タイプを判定する。
    Returns: 'sympathy' | 'comparison' | 'purchase' | ''
    """
    kw = keyword.lower()
    scores = {
        "sympathy":   sum(1 for w in _INTENT_SYMPATHY_WORDS   if w in kw),
        "comparison": sum(1 for w in _INTENT_COMPARISON_WORDS  if w in kw),
        "purchase":   sum(1 for w in _INTENT_PURCHASE_WORDS    if w in kw),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else ""


def _build_tone_section(keyword: str) -> str:
    """検索意図に対応したトーン指示文字列を返す。"""
    intent = _detect_search_intent(keyword)
    if not intent:
        return ""
    label = {"sympathy": "共感系", "comparison": "比較系", "purchase": "購買直前"}[intent]
    print(f"[article_generator] 検索意図: {label} → トーン調整")
    return _TONE_INSTRUCTIONS[intent]


def _build_testimonial_section(keyword: str) -> str:
    """スプレッドシートから関連体験談を取得してプロンプトセクションを返す。"""
    try:
        from modules import wp_context
        from modules.testimonial_fetcher import build_prompt_section
        from config import GOOGLE_CREDENTIALS_PATH
        ss_id = wp_context.get_candidate_ss_id()
        section = build_prompt_section(keyword, ss_id, GOOGLE_CREDENTIALS_PATH)
        if section:
            print(f"[article_generator] 体験談: 関連体験談をプロンプトに組み込みました")
        return section
    except Exception as e:
        print(f"[article_generator] 体験談スキップ: {e}")
        return ""


def _build_blog_context_section() -> str:
    """
    wp_contextのblog_metaからブログ専用コンテキストセクションを生成する。
    値が入っている項目のみ出力。全て空の場合は空文字列を返す。
    空欄の項目はClaudeが記事内容から自動判断する。
    """
    try:
        from modules import wp_context
        meta = wp_context.get_blog_meta()
    except Exception:
        return ""

    if not meta:
        return ""

    lines = []
    if meta.get("site_purpose"):
        lines.append(f"【サイトの目的】{meta['site_purpose']}")
    if meta.get("target"):
        lines.append(f"【ターゲット読者】{meta['target']}")
    if meta.get("writing_taste"):
        lines.append(f"【文章のテイスト】{meta['writing_taste']}")
    if meta.get("genre_detail"):
        lines.append(f"【ジャンル】{meta['genre_detail']}")
    if meta.get("search_intent"):
        lines.append(f"【検索意図タイプ】{meta['search_intent']}")

    if not lines:
        return ""

    block = "\n".join(lines)
    return (
        "## ブログのコンテキスト（記事の方向性・文体・読者に合わせて記事を最適化してください）\n"
        f"{block}\n\n"
    )


USER_PROMPT_TEMPLATE = """\
以下のキーワードで記事構成を生成してください。

現在の日付: {current_date}（記事内で年や「今年」「最新」などの表現を使う際は必ずこの年に合わせること）

メインキーワード: {keyword}
月間検索ボリューム: {volume}
{blog_context_section}{related_section}{theme_section}{lsi_section}{keyword_research_section}{sub_keywords_section}{differentiation_section}{fact_check_section}{person_section}{plaud_notta_section}{tone_section}{testimonial_section}{trusted_external_links_section}{forced_title_section}
このキーワードで検索するユーザーの検索意図を踏まえ、上記フォーマットに従って出力してください。

## 出力フォーマット（JSON）
以下のJSONのみ返してください。前後に説明文・コードブロック記号は不要です。

{{
  "title": "H1タイトル（30〜40字程度・キーワードを自然に含む・数字やメリット・疑問形でクリックを促す。例：「AIボイスレコーダーアプリiPhoneおすすめ7選！文字起こし・要約まで自動化」）",
  "seo_title": "タイトルタグ（検索結果に表示されるSEOタイトル。28〜32字・キーワードを先頭に・サイト名は不要。例：「AIボイスレコーダーアプリおすすめ7選｜文字起こし自動化」）",
  "meta_description": "メタディスクリプション（80〜120字・キーワードを含み検索意図に沿ったクリックを促す文章。例：「AIボイスレコーダーアプリのおすすめ7選を解説。文字起こし・議事録作成を自動化したい人向けに、機能・価格・使いやすさを徹底比較します。」）",
  "slug": "url-slug-in-english-kebab-case",
  "image_prompt": "アイキャッチ用英語プロンプト（記事テーマを表す画像、no text, professional blog header, high quality）",
  "tags": ["記事テーマに合うタグ1", "タグ2", "タグ3", "タグ4", "タグ5（必ず5つ）"],
  "content": "WordPress SWELL形式の完全なHTML（セクション1〜5をすべて含む。記事データセクションは不要）"
}}
"""


def _build_article(keyword: str, volume: int, differentiation_note: str = "",
                   related_keywords: list[str] | None = None,
                   article_theme: str = "",
                   sub_keywords: list[str] | None = None,
                   enable_fact_check: bool = True,
                   target_length: int = 9000,
                   asp_links: dict | None = None,
                   forced_title: str | None = None) -> dict:
    """
    記事生成の共通処理。Claude APIを呼び出してJSON記事データを返す。

    target_length に応じてH3本数・FAQ問数・max_tokensを動的に切り替える。
      9000 (MONETIZE): H3×14〜18本 / FAQ×8〜10問 / max_tokens=12,000
      6000 (LONGTAIL):  H3×8〜12本  / FAQ×5〜7問  / max_tokens=10,000
      3000 (TREND):     H3×5〜7本   / FAQ×3〜4問  / max_tokens= 6,000
      3000 (FUTURE):    H3×5〜7本   / FAQ×3〜4問  / max_tokens=4,500
    """
    h3_min, h3_max, faq_min, faq_max, max_tokens = _get_structure(target_length)
    system_prompt = _build_system_prompt(h3_min, h3_max, faq_min, faq_max, asp_links=asp_links)

    use_plaud_notta = _needs_plaud_notta(keyword)
    print(f"[article_generator] 記事構成生成中: 「{keyword}」(vol:{volume})"
          + f" [{target_length:,}字 / H3:{h3_min}〜{h3_max}本 / FAQ:{faq_min}〜{faq_max}問]"
          + (" ※差別化モード" if differentiation_note else "")
          + (" ※PLAUD/Notta優先" if use_plaud_notta else ""))

    # ── 事実確認ステップ（製品・企業情報を含む記事のみ）──
    fact_check_section = ""
    if enable_fact_check and needs_fact_check(keyword):
        print(f"[article_generator] 事実確認中: 「{keyword}」")
        fc = check_facts(keyword, article_theme)
        if fc["verified"] or fc["uncertain"] or fc["warnings"]:
            fact_check_section = fc["prompt_block"] + "\n"
            verified_count  = len(fc["verified"])
            uncertain_count = len(fc["uncertain"])
            warnings_count  = len(fc["warnings"])
            print(f"[article_generator] 事実確認完了: "
                  f"確認済み{verified_count}件 / 不確か{uncertain_count}件 / 注意{warnings_count}件")
            if fc["warnings"]:
                for w in fc["warnings"]:
                    print(f"  ⚠️  {w}")
        else:
            print("[article_generator] 事実確認: 確認情報なし（スキップ）")

    person_section = PERSON_ARTICLE_INSTRUCTION + "\n" if detect_person_keyword(keyword) else ""
    diff_section = f"差別化の方針: {differentiation_note}\n" if differentiation_note else ""
    plaud_notta_section = _PLAUD_NOTTA_INSTRUCTION if use_plaud_notta else ""

    # ブログコンテキスト（管理シートのメタデータ）
    blog_context_section = _build_blog_context_section()

    # 関連キーワード指示
    related_section = ""
    if related_keywords:
        kw_list = "・".join(related_keywords)
        related_section = (
            f"関連キーワード（記事内のH2・H3見出しや本文に自然に含めること）: {kw_list}\n"
        )

    # 記事テーマ指示
    theme_section = f"記事テーマ: {article_theme}\n" if article_theme else ""

    # 共起語・LSIキーワード（Haiku で生成）
    try:
        lsi_words = _get_lsi_keywords(keyword)
        lsi_section = (
            f"共起語・LSIキーワード（H3本文・FAQ・まとめに自然に散りばめること）: {lsi_words}\n"
        ) if lsi_words else ""
        if lsi_words:
            print(f"[article_generator] 共起語: {lsi_words[:60]}...")
    except Exception:
        lsi_section = ""

    # スプレッドシートのAIM未判定サブキーワード
    sub_keywords_section = ""
    if sub_keywords:
        # メインKW・関連KWと重複するものを除く
        existing = {keyword.lower()} | {k.lower() for k in (related_keywords or [])}
        candidates = [k for k in sub_keywords if k.lower() not in existing][:50]
        if candidates:
            sub_keywords_section = (
                "スプレッドシートのサブキーワード候補（関連性が高いものだけH3見出し・本文・FAQに自然に活用。"
                "無理に全部入れる必要はなく、関連性が低いものはスキップでOK。不自然な詰め込み禁止）:\n"
                + "・".join(candidates) + "\n"
            )
            print(f"[article_generator] サブKW候補: {len(candidates)}件 ({candidates[0]}〜)")

    # サジェスト・PAA・ロングテールキーワード（Haiku で生成）
    keyword_research_section = ""
    try:
        kw_research = _get_keyword_research(keyword)
        parts = []
        if kw_research["suggest"]:
            parts.append("サジェストキーワード（H3見出しや本文に自然に使う）: " + "・".join(kw_research["suggest"]))
        if kw_research["paa"]:
            parts.append("関連質問PAA（FAQの質問文やH3見出しに活用する）: " + "・".join(kw_research["paa"]))
        if kw_research["longtail"]:
            parts.append("ロングテールキーワード（本文中に自然に散りばめる）: " + "・".join(kw_research["longtail"]))
        if parts:
            keyword_research_section = "\n".join(parts) + "\n"
            suggest_preview = "・".join(kw_research["suggest"][:3])
            print(f"[article_generator] サジェスト: {suggest_preview}...")
    except Exception:
        pass

    # 検索意図トーン調整
    tone_section = _build_tone_section(keyword)

    # 体験談セクション（スプレッドシートから関連するものを取得）
    testimonial_section = _build_testimonial_section(keyword)

    # 信頼できる外部リンクセクション（ブログ設定で指定がある場合のみ）
    trusted_external_links_section = ""
    try:
        from modules import wp_context as _wpc
        ext_links = _wpc.get_trusted_external_links()
        if ext_links:
            link_lines = "\n".join(
                f"- {item['name']}: {item['url']}" for item in ext_links
            )
            trusted_external_links_section = (
                "## 外部リンク挿入ルール（必須）\n"
                "以下の公式サイト・信頼できる外部リンクのうち、記事テーマに最も自然に合うものを**必ず1件以上**本文中に挿入してください。\n"
                "挿入例：「最新情報や開催時間は<a href=\"URL\" target=\"_blank\" rel=\"noopener noreferrer\">〇〇公式サイト</a>でご確認ください。」\n"
                f"{link_lines}\n"
            )
    except Exception:
        pass

    # タイトル強制指定セクション
    forced_title_section = ""
    if forced_title:
        forced_title_section = (
            f"\n※ タイトルは必ず「{forced_title}」を使用してください。"
            f"このタイトルに合わせた内容・構成で記事を執筆してください。\n"
        )
        print(f"[article_generator] タイトル強制指定: 「{forced_title}」")

    check_stop()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                current_date=date.today().strftime("%Y年%m月%d日"),
                keyword=keyword,
                volume=volume,
                blog_context_section=blog_context_section,
                related_section=related_section,
                theme_section=theme_section,
                lsi_section=lsi_section,
                keyword_research_section=keyword_research_section,
                sub_keywords_section=sub_keywords_section,
                differentiation_section=diff_section,
                fact_check_section=fact_check_section,
                person_section=person_section,
                plaud_notta_section=plaud_notta_section,
                tone_section=tone_section,
                testimonial_section=testimonial_section,
                trusted_external_links_section=trusted_external_links_section,
                forced_title_section=forced_title_section,
            ),
        }],
    )
    record_usage("claude-sonnet-4-6",
                 message.usage.input_tokens, message.usage.output_tokens, f"article:{keyword}")

    # stop_reason チェック: max_tokens に到達した場合はJSONが途切れているので即エラーにする
    if message.stop_reason == "max_tokens":
        raise ValueError(
            f"max_tokens上限（{max_tokens}）に到達しました。JSONが途切れています。"
            f" 出力トークン: {message.usage.output_tokens}"
        )

    raw = message.content[0].text.strip()

    # ```json ... ``` ブロックへの対応
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 制御文字（改行・タブ以外）をエスケープして再試行
        import re as _re
        sanitized = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
        try:
            data = json.loads(sanitized)
        except json.JSONDecodeError as e:
            raise ValueError(f"Claude APIからのJSON解析エラー: {e}\n---\n{raw[:500]}") from e

    for key in ("title", "meta_description", "slug", "image_prompt", "content"):
        if key not in data:
            raise ValueError(f"レスポンスに必須キー '{key}' がありません")

    # タイトル強制指定: 生成後に上書き
    if forced_title:
        data["title"] = forced_title

    # seo_title が未生成の場合は title から生成（32字に切り詰め）
    if not data.get("seo_title"):
        data["seo_title"] = data["title"][:32]

    # category_id は wordpress_poster の select_category() で決定するため、ここでは使わない
    data.pop("category_id", None)
    data.pop("category_name", None)

    # タグを最大5個に制限（不足時は空リストのまま → 投稿時にログ警告）
    if isinstance(data.get("tags"), list):
        data["tags"] = [t for t in data["tags"] if t][:5]
    else:
        data["tags"] = []

    data["keyword"] = keyword
    data["volume"] = volume

    # ImageFX プロンプトを生成してdictに追加
    try:
        data["imagefx_prompt"] = generate_imagefx_prompt(keyword, data["title"])
    except Exception as e:
        print(f"[article_generator] ImageFXプロンプト生成スキップ: {e}")
        data["imagefx_prompt"] = ""

    print(
        f"[article_generator] 完了: 「{data['title']}」"
        f" カテゴリ: {data.get('category_name','未設定')}({data.get('category_id','-')})"
        f" タグ: {data['tags']}"
    )
    return data


def generate_article(keyword: str, volume: int, differentiation_note: str = "",
                     sub_keywords: list[str] | None = None,
                     enable_fact_check: bool = True,
                     target_length: int = 9000,
                     article_type: str = "longtail",
                     asp_list: list | None = None,
                     guide_links: dict | None = None,
                     forced_title: str | None = None) -> dict:
    """
    指定キーワードでSEO記事構成を生成し、辞書で返す。

    Args:
        keyword: メインキーワード
        volume: 月間検索ボリューム
        differentiation_note: カニバリ対策の差別化ヒント（空文字列なら通常生成）
        sub_keywords: スプレッドシートのAIM未判定キーワード（任意活用）
        enable_fact_check: 事実確認ステップを実行するか（デフォルト: True）
        target_length: 目標文字数（9000/6000/3000）。H3本数・FAQ問数・max_tokensを自動調整

    Returns:
        {title, meta_description, slug, image_prompt, category_id, category_name,
         content, keyword, volume}
    """
    # asp_list ({name, url, ...}のリスト) → asp_links ({name: url}の辞書) に変換
    asp_links: dict | None = None
    if asp_list:
        asp_links = {item["name"]: item["url"] for item in asp_list if item.get("name") and item.get("url")}

    return _build_article(keyword, volume, differentiation_note,
                          sub_keywords=sub_keywords, enable_fact_check=enable_fact_check,
                          target_length=target_length, asp_links=asp_links,
                          forced_title=forced_title)


def generate_article_from_cluster(cluster: dict, sub_keywords: list[str] | None = None) -> dict:
    """
    keyword_clusters.json の1グループから記事を生成する。

    Args:
        cluster: {
            "group_id": int,
            "main_keyword": str,
            "related_keywords": list[str],
            "article_theme": str,
            "skip": bool,
            "note": str,
        }

    Returns:
        generate_article と同じ形式の dict（cluster情報を追加）
    """
    main_kw = cluster["main_keyword"]
    related = cluster.get("related_keywords", [])
    theme = cluster.get("article_theme", "")
    note = cluster.get("note", "")

    # 関連KWのボリュームは未知なので0
    volume = cluster.get("volume", 0)

    data = _build_article(
        keyword=main_kw,
        volume=volume,
        differentiation_note=note,
        related_keywords=related,
        article_theme=theme,
        sub_keywords=sub_keywords,
    )
    data["group_id"] = cluster.get("group_id")
    data["related_keywords"] = related
    return data
