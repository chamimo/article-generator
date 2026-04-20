"""
Step 4: Claude APIで記事構成を生成（WordPress SWELL形式）
"""
import json
import anthropic
from config import ANTHROPIC_API_KEY
from modules.image_generator import generate_imagefx_prompt
from modules.fact_checker import needs_fact_check, check_facts
from modules.api_guard import check_stop, record_usage

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ============================================================
# アフィリエイトリンク一覧（ツール名 → Pretty Links URL）
# ワイズトレンドは固定アフィリリンクなし（ASP案件は動的に注入）
# ============================================================
AFFILIATE_LINKS: dict[str, str] = {}

_affiliate_lines = "\n".join(f"- {name}: {url}" for name, url in AFFILIATE_LINKS.items())

SYSTEM_PROMPT = f"""\
# 役割
あなたは、SEOに最適化された自然な日本語で文章構造（H2・H3の設計）を行う専門ライターです。
AI特有の不自然さを排除し、読者にとって読みやすく、検索意図に沿った構成を作成します。

# サイト情報
- サイト名: ワイズトレンド（https://ys-trend.com）
- テーマ: エンタメ・トレンド・ライフスタイル情報メディア
- 対象読者: エンタメ・トレンドに興味がある方
- ライティングスタイル: エンタメ・トレンドに詳しいWebライターの視点で、フレンドリーかつトレンド感のある表現。「〜してみてください」「〜がおすすめです」「ぜひ〜」は使わないこと

# 出力ルール
- WordPress SWELLの構造に完全準拠（独自CSSやstyle禁止）
- タイトルは30〜40字程度。キーワードを自然に含め、数字・メリット・疑問形などでクリックを促す（例：「今期ドラマおすすめ10選！見逃せない名作を一挙まとめ」）
- H2は最大3つ（すべてにキーフレーズを含める）
- H2見出しは疑問形だけでなく「断言・メリット提示・比較・方法提示」など自然に使い分ける。毎回「〜とは？」「〜できる？」にしないこと（例：✅「2026年注目のトレンドファッションアイテム一覧」✅「人気ドラマ7選を徹底比較」❌「ドラマとは？」）
- H3は合計14〜18本（抽象語禁止、質問形・行動導線を中心に）
- 各H2直下に、そのH2に属するH3タイトルをis-style-num_circleのリスト形式で列挙してから、各H3見出し＋本文のセットを続ける
- 各H3の直下に本文（300〜400字）を追加（SWELLのparagraphブロック）
- 本文トーン: フレンドリー・トレンド感・わかりやすく。読者の共感を引き出す軽快な表現
- 各H3の本文は合計400〜500字・段落2〜3つ（1段落120〜150字）に分け、「結論→詳細→具体例」の流れで書く
- 各段落はそれぞれ個別の<!-- wp:paragraph -->ブロックで囲む
- 本文内で①②③のような番号付き列挙が必要な場合は、テキスト内に書かずWordPressの番号付きリストブロックで出力する（段落ブロックとリストブロックを分けて出力）
- FAQは8〜10問（各回答200字以上）
- 結論ファーストな構成
- タグは最大5個（重要度の高いものを厳選）
- まとめチェックリストの直後に締めの文章（150〜200字）を1段落追加する。2〜3文構成で書くこと。読者の共感を引き出す軽快な締め。「まず〇〇を試してみてください」「〇〇がおすすめです」「ぜひ〜」のような表現は使わないこと。プロンプト末尾にASPアフィリリンクが提供されている場合のみ、文脈に合う1つを自然に組み込む（リンクのために文章を歪めない）。該当リンクがない場合はリンクなしでよい

# リンク挿入ルール
- ASPアフィリエイトリンクはプロンプト末尾の「ASP案件リスト」に記載されたURLのみ使用すること
- リンク形式: <a href="{{URL}}" target="_blank" rel="noopener noreferrer">{{サービス名}}</a>
- 各サービスへのリンクは記事全体で1回のみ（初出時に貼る）
- リンクが提供されていないサービスへの外部リンクは不要

# カテゴリー（WordPressのID）
- エンタメ: 109
- ドラマ: 884
- ゲーム: 823
- イベント: 727
- チケット・カード枠: 846
- スポーツ: 4
- ファッション: 395
- フード・ドリンク: 193
- レシピ: 828
- ダイエット・健康: 97
- 美容: 849
- ジャニーズ: 881
- 仕事・転職・副業: 915
- 生活・その他: 1

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
<p>{{結論・まとめ（120〜150字）。リンクルールに従いASPリンクがある場合のみ適切に挿入。}}</p>
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
<p>{{締めの文章（150〜200字・2〜3文）。読者の共感を引き出す軽快な締め。「まず〇〇を試してみてください」「〇〇がおすすめです」「ぜひ〜」のような表現は使わないこと。ASPアフィリリンク提供済みのサービスが文脈に自然に合う場合のみ1つ挿入。}}</p>
<!-- /wp:paragraph -->

"""

# ============================================================
# PLAUD NOTE / Notta 優先紹介 — ワイズトレンドでは不使用
# ============================================================
_PLAUD_NOTTA_TERMS: list[str] = []
_PLAUD_NOTTA_INSTRUCTION = ""

# ============================================================
# 記事タイプ別 構造設定
# target_length → (h3_min, h3_max, faq_min, faq_max, max_tokens)
# ============================================================
_ARTICLE_STRUCTURE: dict[int, tuple[int, int, int, int, int]] = {
    9000: (14, 18, 8, 10, 12000),  # MONETIZE: 比較・レビュー系・高品質
    6000: ( 8, 12, 5,  7, 10500),  # LONGTAIL: 標準SEO記事
    3000: ( 5,  7, 3,  4,  6000),  # FUTURE / TREND: 短め情報記事
}

def _get_structure(target_length: int) -> tuple[int, int, int, int, int]:
    """target_lengthに最も近い構造設定を返す。"""
    if target_length in _ARTICLE_STRUCTURE:
        return _ARTICLE_STRUCTURE[target_length]
    closest = min(_ARTICLE_STRUCTURE.keys(), key=lambda k: abs(k - target_length))
    return _ARTICLE_STRUCTURE[closest]


def build_guide_links_section(guide_links: dict) -> str:
    """
    内部誘導リンク用プロンプトセクションを構築する。
    guide_links: {"pv_url": str, "comparison_url": str, "cv_url": str}
    空のURLはスキップ。全て空の場合は空文字列を返す。
    """
    if not guide_links:
        return ""
    entries = []
    pv_url  = guide_links.get("pv_url", "").strip()
    cmp_url = guide_links.get("comparison_url", "").strip()
    cv_url  = guide_links.get("cv_url", "").strip()
    if pv_url:
        entries.append(f"- 流入記事（PV記事）: {pv_url}")
    if cmp_url:
        entries.append(f"- 比較記事: {cmp_url}")
    if cv_url:
        entries.append(f"- 成約記事（CV記事）: {cv_url}")
    if not entries:
        return ""
    return (
        "\n## 内部誘導リンク（自然な文脈で挿入・1〜2箇所まで）\n"
        "以下の記事URLへ、強制的な誘導にならず**自然な流れ**で本文中1〜2箇所だけ言及してください。\n"
        "「こちらの記事もおすすめです」のような直接的な案内は禁止。\n"
        "話題の流れで「この点については別記事で詳しく触れていますが〜」のように有機的に組み込むこと。\n"
        "読者体験を損なわない箇所に限定し、必要性が低い場合は無理に挿入しないこと。\n\n"
        + "\n".join(entries)
    )


def _build_system_prompt(h3_min: int, h3_max: int, faq_min: int, faq_max: int,
                         asp_links_section: str = "",
                         guide_links_section: str = "") -> str:
    """
    H3本数・FAQ問数に応じてSYSTEM_PROMPTの数値指示を置き換えて返す。
    asp_links_section が指定された場合はASP案件リストをプロンプト末尾に追記する。
    guide_links_section が指定された場合は内部誘導リンク指示をプロンプト末尾に追記する。
    """
    prompt = SYSTEM_PROMPT
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
    # SYSTEM_PROMPT はf-string なので {{8〜10問繰り返し}} → {8〜10問繰り返し} になっている
    prompt = prompt.replace(
        "{8〜10問繰り返し}",
        f"{{{faq_min}〜{faq_max}問繰り返し}}",
    )
    if asp_links_section:
        prompt = prompt + "\n" + asp_links_section
    if guide_links_section:
        prompt = prompt + "\n" + guide_links_section
    return prompt


def _get_keyword_and_lsi(keyword: str) -> tuple[dict, str]:
    """
    Claude Haiku でキーワードリサーチと共起語・LSIを1コールで生成する。

    Returns:
        (kw_research, lsi_words)
        kw_research: {"suggest": [...], "paa": [...], "longtail": [...]}
        lsi_words: 「用語1、用語2、...」形式の文字列
    """
    check_stop()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": (
                f"「{keyword}」のSEO記事向けに以下を一括で生成してください。\n"
                "以下のJSONのみ出力してください（```json などのコードブロック記号は不要）：\n"
                '{"suggest":["サジェスト候補8〜10個（Googleサジェスト想定）"],'
                '"paa":["PAA形式の質問文5〜8個（〜とは・〜やり方・〜比較・〜おすすめなど）"],'
                '"longtail":["3〜5語のロングテール複合キーワード8〜10個"],'
                '"lsi":"読者が同時に検索・気にするであろう関連共起語・LSIキーワードをカンマ区切りで15個"}'
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
        kw_research = {
            "suggest":  result.get("suggest", [])[:10],
            "paa":      result.get("paa", [])[:8],
            "longtail": result.get("longtail", [])[:10],
        }
        lsi_raw = result.get("lsi", "")
        if isinstance(lsi_raw, list):
            lsi_raw = "、".join(lsi_raw)
        lsi_words = str(lsi_raw).splitlines()[0] if lsi_raw else ""
        return kw_research, lsi_words
    except Exception:
        return {"suggest": [], "paa": [], "longtail": []}, ""


def _needs_plaud_notta(keyword: str) -> bool:
    """キーワードがPLAUD NOTE/Notta優先紹介の対象かどうかを判定する。"""
    kw = keyword.lower()
    return any(term in kw for term in _PLAUD_NOTTA_TERMS)


USER_PROMPT_TEMPLATE = """\
以下のキーワードで記事構成を生成してください。

メインキーワード: {keyword}
月間検索ボリューム: {volume}
{related_section}{theme_section}{lsi_section}{keyword_research_section}{sub_keywords_section}{differentiation_section}{fact_check_section}{plaud_notta_section}
このキーワードで検索するユーザーの検索意図を踏まえ、上記フォーマットに従って出力してください。

## 出力フォーマット（JSON）
以下のJSONのみ返してください。前後に説明文・コードブロック記号は不要です。

{{
  "title": "SEOタイトル（30〜40字程度・キーワードを自然に含む・数字やメリット・疑問形でクリックを促す）",
  "meta_description": "メタディスクリプション（メインKW「{keyword}」を必ず2回以上含む・必ず120文字以上160文字以内・検索意図を踏まえたクリックを促す自然な文章・120文字未満は不可）",
  "slug": "url-slug-in-english-kebab-case",
  "category_id": カテゴリーIDの整数,
  "category_name": "カテゴリー名",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
  "content": "WordPress SWELL形式の完全なHTML（セクション1〜5をすべて含む。記事データセクションは不要）"
}}
"""


def _build_article(keyword: str, volume: int, differentiation_note: str = "",
                   related_keywords: list[str] | None = None,
                   article_theme: str = "",
                   sub_keywords: list[str] | None = None,
                   enable_fact_check: bool = True,
                   target_length: int = 9000,
                   article_type: str = "",
                   asp_list: list[dict] | None = None,
                   guide_links: dict | None = None) -> dict:
    """
    記事生成の共通処理。Claude APIを呼び出してJSON記事データを返す。

    target_length に応じてH3本数・FAQ問数・max_tokensを動的に切り替える。
      9000 (MONETIZE): H3×14〜18本 / FAQ×8〜10問 / max_tokens=12,000
      6000 (LONGTAIL):  H3×8〜12本  / FAQ×5〜7問  / max_tokens=10,500
      3000 (TREND):     H3×5〜7本   / FAQ×3〜4問  / max_tokens= 6,000
    """
    h3_min, h3_max, faq_min, faq_max, max_tokens = _get_structure(target_length)
    from modules.asp_fetcher import build_asp_prompt_section
    asp_links_section  = build_asp_prompt_section(asp_list or [])
    guide_links_section = build_guide_links_section(guide_links or {})
    system_prompt = _build_system_prompt(h3_min, h3_max, faq_min, faq_max,
                                         asp_links_section=asp_links_section,
                                         guide_links_section=guide_links_section)

    use_plaud_notta = _needs_plaud_notta(keyword)
    print(f"[article_generator] 記事構成生成中: 「{keyword}」(vol:{volume})"
          + f" [{target_length:,}字 / H3:{h3_min}〜{h3_max}本 / FAQ:{faq_min}〜{faq_max}問]"
          + (" ※差別化モード" if differentiation_note else ""))

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

    diff_section = f"差別化の方針: {differentiation_note}\n" if differentiation_note else ""
    plaud_notta_section = _PLAUD_NOTTA_INSTRUCTION if use_plaud_notta else ""

    # 関連キーワード指示
    related_section = ""
    if related_keywords:
        kw_list = "・".join(related_keywords)
        related_section = (
            f"関連キーワード（記事内のH2・H3見出しや本文に自然に含めること）: {kw_list}\n"
        )

    # 記事テーマ指示
    theme_section = f"記事テーマ: {article_theme}\n" if article_theme else ""

    # キーワードリサーチ + 共起語・LSI（Haiku 1コールで生成）
    lsi_section = ""
    keyword_research_section = ""
    try:
        kw_research, lsi_words = _get_keyword_and_lsi(keyword)
        if lsi_words:
            lsi_section = (
                f"共起語・LSIキーワード（H3本文・FAQ・まとめに自然に散りばめること）: {lsi_words}\n"
            )
            print(f"[article_generator] 共起語: {lsi_words[:60]}...")
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

    # スプレッドシートのAIM未判定サブキーワード
    sub_keywords_section = ""
    if sub_keywords:
        existing = {keyword.lower()} | {k.lower() for k in (related_keywords or [])}
        candidates = [k for k in sub_keywords if k.lower() not in existing][:50]
        if candidates:
            sub_keywords_section = (
                "スプレッドシートのサブキーワード候補（関連性が高いものだけH3見出し・本文・FAQに自然に活用。"
                "無理に全部入れる必要はなく、関連性が低いものはスキップでOK。不自然な詰め込み禁止）:\n"
                + "・".join(candidates) + "\n"
            )
            print(f"[article_generator] サブKW候補: {len(candidates)}件 ({candidates[0]}〜)")

    check_stop()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                keyword=keyword,
                volume=volume,
                related_section=related_section,
                theme_section=theme_section,
                lsi_section=lsi_section,
                keyword_research_section=keyword_research_section,
                sub_keywords_section=sub_keywords_section,
                differentiation_section=diff_section,
                fact_check_section=fact_check_section,
                plaud_notta_section=plaud_notta_section,
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
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude APIからのJSON解析エラー: {e}\n---\n{raw[:500]}") from e

    for key in ("title", "meta_description", "slug", "content"):
        if key not in data:
            raise ValueError(f"レスポンスに必須キー '{key}' がありません")

    if "category_id" in data:
        try:
            data["category_id"] = int(data["category_id"])
        except (ValueError, TypeError):
            data.pop("category_id", None)

    # タグを最大5個に制限
    if isinstance(data.get("tags"), list):
        data["tags"] = data["tags"][:5]
    else:
        data["tags"] = []

    # meta_description 長さ検証（120字未満の場合は Haiku で補完）
    meta_desc = data.get("meta_description", "")
    if len(meta_desc) < 120:
        print(f"[article_generator] meta_description 短すぎ({len(meta_desc)}字) → 再生成")
        try:
            fix_msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": (
                        f"以下のメタディスクリプションを120〜160字に書き直してください。"
                        f"キーワード「{keyword}」を2回以上含め、検索意図に沿ったクリックを促す自然な文章にすること。"
                        f"テキストのみ返してください（説明不要）。\n\n{meta_desc}"
                    ),
                }],
            )
            record_usage(fix_msg.model, fix_msg.usage.input_tokens, fix_msg.usage.output_tokens,
                         label=f"meta_fix:{keyword}")
            fixed = fix_msg.content[0].text.strip()
            if len(fixed) >= 120:
                data["meta_description"] = fixed
                print(f"[article_generator] meta_description 補完完了: {len(fixed)}字")
            else:
                print(f"[article_generator] meta_description 補完後も短い({len(fixed)}字)・そのまま使用")
        except Exception as e:
            print(f"[article_generator] meta_description 補完スキップ: {e}")

    data["keyword"] = keyword
    data["volume"] = volume

    # ImageFX プロンプトを生成してdictに追加
    try:
        data["imagefx_prompt"] = generate_imagefx_prompt(keyword, data["title"], article_type=article_type)
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
                     article_type: str = "",
                     asp_list: list[dict] | None = None,
                     guide_links: dict | None = None) -> dict:
    """
    指定キーワードでSEO記事構成を生成し、辞書で返す。

    Args:
        keyword: メインキーワード
        volume: 月間検索ボリューム
        differentiation_note: カニバリ対策の差別化ヒント（空文字列なら通常生成）
        sub_keywords: スプレッドシートのAIM未判定キーワード（任意活用）
        enable_fact_check: 事実確認ステップを実行するか（デフォルト: True）
        target_length: 目標文字数（9000/6000/3000）。H3本数・FAQ問数・max_tokensを自動調整
        asp_list: ASP案件リスト（fetch_asp_links()の返り値）。プロンプトに注入される。
        guide_links: 内部誘導リンク {"pv_url": str, "comparison_url": str, "cv_url": str}

    Returns:
        {title, meta_description, slug, category_id, category_name,
         content, keyword, volume}
    """
    return _build_article(keyword, volume, differentiation_note,
                          sub_keywords=sub_keywords, enable_fact_check=enable_fact_check,
                          target_length=target_length, article_type=article_type,
                          asp_list=asp_list, guide_links=guide_links)


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
