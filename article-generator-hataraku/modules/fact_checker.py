"""
事実確認モジュール

製品・企業情報を含む記事の生成前に、Web検索で基本情報を確認する。
確認済み情報のみを記事に使用し、不確かな情報は表現を和らげる指示を生成する。
"""
import json
import re
import anthropic
from config import ANTHROPIC_API_KEY

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 事実確認が必要な記事を示すパターン
_NEEDS_CHECK_RE = re.compile(
    r'(レビュー|検証|比較|スペック|価格|メーカー|ブランド|製品|機種|モデル'
    r'|おすすめ.{0,5}選|国産|海外製|評判|口コミ|選び方)',
    re.IGNORECASE,
)

# 確認対象の製品・ブランド名を抽出するパターン（カタカナ製品名・英数字ブランド名）
_BRAND_RE = re.compile(
    r'([A-Za-z][A-Za-z0-9\s\-\.]{1,30}|[ァ-ヶー]{3,15})',
)


def needs_fact_check(keyword: str) -> bool:
    """製品・企業情報を含む記事かどうかを判定する。"""
    return bool(_NEEDS_CHECK_RE.search(keyword))


def check_facts(keyword: str, article_theme: str = "") -> dict:
    """
    Web検索でキーワードに関連する製品・企業情報を事実確認する。

    Returns:
        {
            "verified":  [str, ...],   # 確認済みの事実
            "uncertain": [str, ...],   # 不確かな情報（「〜とされています」表現推奨）
            "warnings":  [str, ...],   # 記事生成時に注意すべき点
            "prompt_block": str,       # プロンプトに追加するテキストブロック
        }
    """
    context = f"キーワード: {keyword}"
    if article_theme:
        context += f"\n記事テーマ: {article_theme}"

    instruction = f"""\
以下の記事キーワードに関連する製品・企業情報を検索し、事実確認を行ってください。

{context}

## 必ず確認してほしい項目
1. 製品・ブランドの国籍・製造元（国産 / 海外製の区別）
2. メーカー名・開発企業名（正式名称）
3. 現在の価格帯・スペック（主要モデル）
4. その他、記事に誤りが生じやすい重要な事実

## 出力形式（JSONのみ・コードブロック不要）
{{
  "verified": [
    "確認できた事実1（出典・根拠を簡潔に付記）",
    "確認できた事実2"
  ],
  "uncertain": [
    "確認できなかった・情報が錯綜している項目1",
    "確認できなかった・情報が錯綜している項目2"
  ],
  "warnings": [
    "記事生成時に特に注意すべき点1",
    "記事生成時に特に注意すべき点2"
  ]
}}

検索で確認できた情報だけを verified に入れ、
確認できなかった・曖昧な情報は uncertain に入れてください。
"""

    try:
        msg = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": instruction}],
        )

        # テキストブロックを結合して JSON を抽出
        full_text = "".join(
            block.text for block in msg.content
            if hasattr(block, "text") and block.text
        )

        m = re.search(r'\{[\s\S]*\}', full_text)
        if not m:
            raise ValueError("JSONが見つかりません")

        result = json.loads(m.group())
        verified  = result.get("verified", [])
        uncertain = result.get("uncertain", [])
        warnings  = result.get("warnings", [])

    except Exception as e:
        print(f"[fact_checker] 事実確認エラー: {e}")
        verified, uncertain, warnings = [], [], []

    prompt_block = _build_prompt_block(verified, uncertain, warnings)
    return {
        "verified":  verified,
        "uncertain": uncertain,
        "warnings":  warnings,
        "prompt_block": prompt_block,
    }


def _build_prompt_block(verified: list, uncertain: list, warnings: list) -> str:
    """事実確認結果をプロンプトに追加するテキストに変換する。"""
    lines = ["## 事実確認済み情報（Web検索で確認・必ずこの情報に基づいて記述すること）"]

    if verified:
        lines.append("### 確認済み事実（そのまま記事に使用してよい）")
        for v in verified:
            lines.append(f"- {v}")
    else:
        lines.append("- 確認済み情報なし（一般的な知識に基づいて記述してください）")

    if uncertain:
        lines.append("\n### 不確かな情報（「〜とされています」「〜と言われています」などの表現に変えること）")
        for u in uncertain:
            lines.append(f"- {u}")

    if warnings:
        lines.append("\n### 記事生成時の注意事項（必ず守ること）")
        for w in warnings:
            lines.append(f"- {w}")

    lines.append(
        "\n国産・海外製の区別・価格・スペック・会社名は上記の確認済み情報を使用し、"
        "不確かな場合は「〜とされています」「公式サイトでご確認ください」などの表現を使うこと。"
    )

    return "\n".join(lines)
