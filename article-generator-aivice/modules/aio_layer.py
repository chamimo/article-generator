"""
AIO common layer for article generation.

This module keeps AI Overview / generative-AI friendly structure rules out of
site-specific prompts. Site profiles can override emphasis and templates
without changing the shared generation flow.
"""
from __future__ import annotations

import importlib.util
import os
import re
from html import unescape
from pathlib import Path
from typing import Any


DEFAULT_AIO_PROFILE: dict[str, Any] = {
    "enabled": True,
    "mode": "common",
    "audience": "検索ユーザー",
    "conversion_goal": "",
    "author_name": "編集部",
    "source_policy": "公式情報・一次情報・信頼できる公開情報を優先する",
    "reference_label": "出典・参考情報",
    "required_sections": [
        "Query→Intent→Answer",
        "PREP",
        "FAQ",
        "HowTo",
        "Evidence/Reference",
        "著者情報・更新日",
        "1段落1テーマ",
        "AIO品質チェックリスト",
    ],
}


COMMON_AIO_RULES = """\
## AIO共通レイヤー（全ブログ共通・必須）
AI Overviewや生成AIが内容を理解・引用しやすいように、次の設計を記事全体に反映してください。

### Query→Intent→Answer設計
- メインキーワードをQueryとして扱い、検索者が「知りたいこと」「比較したいこと」「次に取りたい行動」をIntentとして明示的に整理する
- 冒頭60〜80字に、検索意図へ直接答えるAnswerを置く
- 各H2/H3は、Queryまたは関連質問に対する小さなAnswerとして読める見出しにする

### PREP構成
- 重要なH3本文は、Point（結論）→ Reason（理由）→ Example（具体例）→ Point（再結論）の順で書く
- 先に結論、その後に条件・例外・比較軸を補足する

### FAQ / HowTo
- FAQは検索者の再質問・比較・不安・導入前確認に答える
- 手順説明が自然なテーマでは、HowToとして「手順」「準備するもの」「注意点」が分かる構成を入れる
- FAQ回答は単なる短文ではなく、判断基準や例外を含める

### Evidence / Reference
- 仕様、価格、制度、統計、医療・学校・法人導入などの事実は、出典名と年月を本文中に明示する
- 公式サイト、メーカー資料、公的機関、一次情報を優先し、不明な場合は断定しない
- 記事末尾付近に「出典・参考情報」ブロックを置き、参照した情報名を箇条書きでまとめる

### 著者情報・更新日・出典情報
- まとめの後に、著者情報、更新日、出典方針が分かる短い情報ブロックを入れる
- 更新日は記事生成時点の年月日として扱い、古くなりやすい情報は「最新情報は公式情報を確認」と補足する

### 1段落1テーマ
- 1つの段落では1テーマだけ扱う。複数の論点を同じ段落に詰め込まない
- 段落は短めに分け、各段落が単独で引用されても意味が通るようにする

### 最終ろ過プロンプト
出力直前に、以下の観点で自己点検してからJSONを返してください。
- 冒頭に直接回答があるか
- 各H2/H3が検索意図に対応しているか
- PREPの流れが崩れていないか
- FAQ/HowTo/Evidence/Referenceが自然に入っているか
- 著者情報、更新日、出典情報が明示されているか
- 1段落1テーマになっているか
- 誇張、根拠不明の断定、古い情報の断言がないか

### AIO品質チェックリスト
記事内のまとめ付近に、読者向けの自然な形でAIO品質チェックリストを含めてください。
チェック項目は「検索意図への回答」「判断基準」「手順」「注意点」「出典」「次の行動」を含めます。
"""


COMMON_BOOK_DERIVED_AIO_RULES = """\
## 書籍要点から反映する共通AIO補足（全ブログ共通・軽量）
- SEOを土台に、AEO（質問への直接回答）、GEO（根拠・比較・引用されやすさ）、LLMO（意味の一貫性・知識体系化）を薄く意識する
- 検索キーワードをQuery→Intent→Answerに分解し、冒頭、H2直下、FAQでは結論ファーストにする
- PREP→FAQ→HowToの流れを自然に使い、定義、要約、比較、手順をAI Overviewが拾いやすい形で明確にする
- Evidence（根拠）、Traceability（出典・条件・確認元）、Retention（1段落1テーマ・単体で意味が通る段落）を意識する
- FAQは質問と回答だけで完結させ、必要に応じてEvidenceやReferenceを添える。ただし未確認情報や実績は作らない
- 読者が次に取る行動、注意点、確認すべき条件を明確にする
"""


GROOWILL_AIO_RULES = """\
## グルーウィル法人フィルム専用モード
この記事は、法人担当者からの問い合わせにつながる構成を優先してください。

### 対象読者
- 学校ICT担当、自治体・教育委員会、医療機関の購買・情報システム担当
- 業務用端末をまとめて管理する法人担当者
- 特殊サイズ、機能別、機種別の保護フィルムを探している担当者

### 専用テンプレート
- 学校ICT: 端末配布、GIGA端末、児童生徒の破損対策、貼付作業、予備在庫、年度更新を扱う
- 医療機関: 清拭、衛生管理、受付端末、電子カルテ端末、視認性、現場運用を扱う
- 業務用端末: ハンディターミナル、タブレット、POS、工場・物流・店舗利用、まとめ発注を扱う
- 特殊サイズ: 型番不明、特注、採寸、既製品で合わない場合、少量・大量相談を扱う
- 機能別: 反射防止、ブルーライトカット、覗き見防止、抗菌、衝撃吸収、ペーパーライクを扱う

### 法人問い合わせ導線
- 冒頭で「どの端末に、どの機能のフィルムが、何枚必要か」を整理する
- H2/H3で「選び方」「導入前確認」「見積もり時に必要な情報」「よくある失敗」を扱う
- CTAは押し売りではなく「端末名・型番・台数・希望機能を伝えると相談しやすい」という案内にする
- お問い合わせ内容は当サイト運営者および提携先企業に共有され、具体的な仕様・お見積り・納期の案内は提携先企業より直接ご連絡する場合があることを自然に補足する
- 共有・直接連絡の説明は、相談窓口メモ、CTA付近、記事末尾、必要なFAQに絞り、本文中で同じ長文を何度も繰り返さない
- 本文中では「詳しい仕様・お見積り・納期は、個別の内容を確認したうえでのご案内となります」のような短い表現を使ってよい
- 当サイトがすべての仕様回答や見積り回答を行うように見える表現は避ける
- 個人購入より、法人一括導入、特殊サイズ相談、複数拠点配布、貼付・予備在庫の観点を優先する
"""


CATEGORY_TEMPLATES: dict[str, str] = {
    "school_ict": "学校ICT向け: 端末配布、破損対策、年度更新、台数管理、貼付作業まで含めて構成する",
    "medical": "医療機関向け: 衛生管理、清拭、視認性、受付・診療端末の運用を中心に構成する",
    "business_device": "業務用端末向け: 店舗、工場、物流、営業現場の端末保護とまとめ発注を中心に構成する",
    "custom_size": "特殊サイズ向け: 採寸、型番確認、既製品で合わない場合の相談導線を中心に構成する",
    "function": "機能別向け: 反射防止、覗き見防止、抗菌、衝撃吸収などの選び方を中心に構成する",
}


def load_site_module(site_name: str, module_name: str) -> Any | None:
    """Load sites/<site_name>/<module_name>.py when it exists."""
    root = Path(__file__).resolve().parents[1]
    path = root / "sites" / site_name / f"{module_name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_site_{site_name}_{module_name}", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_aio_profile(site_name: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge default, site prompt_profile.py, category_templates.py and blog_config extra."""
    profile = dict(DEFAULT_AIO_PROFILE)
    extra = extra or {}

    prompt_profile = load_site_module(site_name, "prompt_profile")
    if prompt_profile and hasattr(prompt_profile, "AIO_PROFILE"):
        profile.update(getattr(prompt_profile, "AIO_PROFILE"))

    category_templates = load_site_module(site_name, "category_templates")
    templates = dict(CATEGORY_TEMPLATES)
    if category_templates and hasattr(category_templates, "CATEGORY_TEMPLATES"):
        templates.update(getattr(category_templates, "CATEGORY_TEMPLATES"))
    profile["category_templates"] = templates

    swell_profile = load_site_module(site_name, "swell_profile")
    if swell_profile and hasattr(swell_profile, "SWELL_DECORATION_RULES"):
        profile["swell_decoration_rules"] = getattr(swell_profile, "SWELL_DECORATION_RULES")
    if swell_profile and hasattr(swell_profile, "BOOK_DERIVED_AIO_RULES"):
        profile["book_derived_aio_rules"] = getattr(swell_profile, "BOOK_DERIVED_AIO_RULES")

    profile.update(extra.get("aio_profile", {}))
    profile["enabled"] = bool(extra.get("aio_enabled", profile.get("enabled", True)))
    profile["mode"] = extra.get("aio_mode", profile.get("mode", "common"))
    profile["site_name"] = extra.get("site_name", site_name)
    return profile


def detect_groowill_template(keyword: str, profile: dict[str, Any]) -> str:
    """Choose a Groowill category template from keyword text."""
    kw = keyword.lower()
    mapping = [
        ("school_ict", ["学校", "ict", "giga", "教育委員会", "児童", "生徒", "タブレット学習"]),
        ("medical", ["医療", "病院", "クリニック", "電子カルテ", "受付", "清拭", "抗菌"]),
        ("business_device", ["業務用", "法人", "pos", "ハンディ", "工場", "物流", "店舗", "端末"]),
        ("custom_size", ["特殊サイズ", "特注", "オーダー", "サイズ", "型番", "採寸"]),
        ("function", ["反射防止", "覗き見", "ブルーライト", "抗菌", "衝撃", "ペーパーライク", "機能"]),
    ]
    templates = profile.get("category_templates") or CATEGORY_TEMPLATES
    for key, terms in mapping:
        if any(term in kw for term in terms):
            return templates.get(key, "")
    return templates.get("business_device", "")


def build_aio_prompt_section(
    keyword: str,
    article_type: str,
    target_length: int,
    profile: dict[str, Any] | None = None,
) -> str:
    """Build prompt text injected into the user prompt."""
    profile = profile or DEFAULT_AIO_PROFILE
    if not profile.get("enabled", True):
        return ""
    common_rules = COMMON_AIO_RULES
    if profile.get("mode") == "groowill_film":
        common_rules = (
            common_rules
            .replace("公式サイト、メーカー資料、公的機関、一次情報を優先し", "提携先企業の公開情報、端末仕様、公的機関、一次情報を優先し")
            .replace("最新情報は公式情報を確認", "最新情報は提携先企業や関係機関の情報を確認")
        )

    lines = [
        common_rules,
        COMMON_BOOK_DERIVED_AIO_RULES,
        "## AIOプロファイル",
        f"- 想定読者: {profile.get('audience', '検索ユーザー')}",
        f"- 記事タイプ: {article_type}",
        f"- 目標文字数: {target_length}",
        f"- 著者名: {profile.get('author_name', '編集部')}",
        f"- 出典方針: {profile.get('source_policy', DEFAULT_AIO_PROFILE['source_policy'])}",
    ]
    if profile.get("conversion_goal"):
        lines.append(f"- CV目標: {profile['conversion_goal']}")

    if profile.get("mode") == "groowill_film":
        template = detect_groowill_template(keyword, profile)
        lines.extend([GROOWILL_AIO_RULES, f"### 今回の記事テンプレート\n{template}"])

    faq_template = profile.get("faq_template")
    if faq_template:
        lines.append(f"## サイト別FAQテンプレート\n{faq_template}")

    cta_note = profile.get("cta_note")
    if cta_note:
        lines.append(f"## サイト別CTA・免責補足\n{cta_note}")

    swell_rules = profile.get("swell_decoration_rules")
    if swell_rules:
        lines.append(f"## サイト別SWELL装飾ルール\n{swell_rules}")

    book_rules = profile.get("book_derived_aio_rules") or profile.get("book_notes_rules")
    if book_rules:
        lines.append(f"## 書籍要点から反映するAIO/LLMOルール\n{book_rules}")

    custom_rules = profile.get("custom_rules")
    if custom_rules:
        lines.append(f"## サイト別AIO追加ルール\n{custom_rules}")

    return "\n".join(lines) + "\n"


def _strip_tags(html: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def run_aio_quality_check(article: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a lightweight quality checklist for logs/dry-run review."""
    profile = profile or DEFAULT_AIO_PROFILE
    content = article.get("content", "") or ""
    text = _strip_tags(content)
    checks = {
        "has_direct_answer_intro": len(text[:180]) >= 60 and ("です" in text[:180] or "ます" in text[:180]),
        "has_faq": "faq" in content.lower() or "よくある質問" in content,
        "has_howto_signal": any(word in text for word in ("手順", "方法", "流れ", "準備", "進め方")),
        "has_evidence_reference": any(word in text for word in ("出典", "参考", "公式", "一次情報")),
        "has_author_or_updated": any(word in text for word in ("著者", "監修", "更新日", "最終更新")),
        "has_aio_checklist": "AIO品質チェックリスト" in text or "品質チェックリスト" in text,
        "one_theme_paragraph_likely": _paragraphs_are_reasonable(content),
    }
    score = sum(1 for ok in checks.values() if ok)
    return {
        "enabled": bool(profile.get("enabled", True)),
        "mode": profile.get("mode", "common"),
        "score": score,
        "max_score": len(checks),
        "checks": checks,
    }


def _paragraphs_are_reasonable(content: str) -> bool:
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", content, flags=re.S)
    if not paragraphs:
        return False
    long_count = 0
    for paragraph in paragraphs[:30]:
        text = _strip_tags(paragraph)
        if len(text) > 260:
            long_count += 1
    return long_count <= max(2, len(paragraphs[:30]) // 5)
