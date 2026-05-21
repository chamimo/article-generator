"""
ブログ設定シートとメディア人格シートを読み込むモジュール。

スプレッドシート構造:
  ブログ設定  : 「項目」「内容」の2列（縦型キーバリュー）
  メディア人格: 「大項目」「小項目」「設定内容」の3列
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

BLOG_CONFIG_SHEET_NAME   = "ブログ設定"
MEDIA_PERSONA_SHEET_NAME = "メディア人格"

# 記事生成に使うブログ設定の項目名（URL・シート名等のオペレーション系は除外）
_ARTICLE_RELEVANT_KEYS: set[str] = {
    "サイトの目的",
    "備考",
    "SEO方針",
    "検索意図タイプ（Know / Do / Buy）",
    "E-E-A-T方針",
    "内部リンク方針",
    "AI記事ルール",
    "実体験ルール",
    "AI Overview対策",
    "共起語方針",
    "記事生成ルール",
    "見出しルール",
    "タイトルテンプレート",
    "ディスクリプションテンプレート",
    "CTA方針",
    "禁止動作",
    "出力ルール",
    "優先ルール",
    "検索意図優先度",
    "記事チェックルール",
}

def _open_sheet(ss_id: str, sheet_name: str, credentials_path: str):
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(ss_id).worksheet(sheet_name)


def load_blog_config_sheet(
    ss_id: str,
    credentials_path: str = "./credentials.json",
) -> dict[str, str]:
    """
    ブログ設定シートを {項目: 内容} 形式で返す。
    記事生成に関係する項目のみ（_ARTICLE_RELEVANT_KEYS）を含む。
    毎回シートから直接読み込む（キャッシュなし）。
    """
    try:
        ws = _open_sheet(ss_id, BLOG_CONFIG_SHEET_NAME, credentials_path)
        rows = ws.get_all_values()
    except Exception as e:
        log.warning(f"[blog_sheets] ブログ設定シート読み込みエラー: {e}")
        return {}

    result: dict[str, str] = {}
    for row in rows[1:]:  # ヘッダー行をスキップ
        if len(row) < 2:
            continue
        key = (row[0] or "").strip()
        val = (row[1] or "").strip()
        if key and val and key in _ARTICLE_RELEVANT_KEYS:
            result[key] = val

    log.info(f"[blog_sheets] ブログ設定: {len(result)}件 読み込み")
    return result


def load_media_persona_sheet(
    ss_id: str,
    credentials_path: str = "./credentials.json",
) -> list[dict]:
    """
    メディア人格シートを [{大項目, 小項目, 設定内容}] 形式で返す。
    毎回シートから直接読み込む（キャッシュなし）。
    """
    try:
        ws = _open_sheet(ss_id, MEDIA_PERSONA_SHEET_NAME, credentials_path)
        rows = ws.get_all_values()
    except Exception as e:
        log.warning(f"[blog_sheets] メディア人格シート読み込みエラー: {e}")
        return []

    result: list[dict] = []
    for row in rows[1:]:  # ヘッダー行をスキップ
        if len(row) < 3:
            continue
        major   = (row[0] or "").strip()
        minor   = (row[1] or "").strip()
        content = (row[2] or "").strip()
        if minor and content:
            result.append({"大項目": major, "小項目": minor, "設定内容": content})

    log.info(f"[blog_sheets] メディア人格: {len(result)}件 読み込み")
    return result


# AIVice 記事生成の絶対ルール（シート内容を補完する固定ガイドライン）
_META_RULES = """\
### 記事生成の優先順位
1. メディア人格（空気感・人間味・共感・禁止事項）
2. ブログ設定（SEO・CTA・導線・運営方針）
3. 個別記事指示（テーマ・検索意図・記事タイプ）
4. SEO最適化（検索意図・共起語・構成）
5. AI自動補完（不足部分の自然な補完）

### 絶対遵守ルール
- 最優先: 読者理解・安心感・共感（SEOより優先）
- 最重要: AIっぽさ・上から目線・煽り感を排除
- 記事の目的: 読者に「これなら試せそう」と思ってもらうこと
- 生成スタンス: 「教え込む」ではなく「一緒に試す」空気感
- 読者との距離感: 先生ではなく「少し先を試している人」
- 犠牲にしないこと: 人間味・実体験・温度感
- 共感ルール: 解決策を書く前に、まず読者の不安・迷いに共感する
- 実体験ルール: 実際に使った感想・失敗談・困った点を自然に入れる
- 感情ルール: 不安・迷い・疲れ・AIへの怖さも扱う
- 文体ルール: 会話調・やさしい・ひらがな多め・圧を出しすぎない
- 初心者対応: 「わからなくて普通」という前提で書く
- CTAルール: 押し売りせず、やさしく背中を押す
- 禁止: 情弱煽り・AI万能論・過剰断定・マウント
- 絶対に使わない言葉: 情弱、オワコン、人生変わる、誰でも爆稼ぎ、完全放置、不労所得
- 最終確認: 「読んで疲れないか」「AIって怖くなかった」「また読みたい」と思える記事か

### 迷った時の判断基準
読者が安心できること ＞ 読者が理解しやすいこと ＞ 読者が実践しやすいこと ＞ SEOテクニック

### 避ける方向性
AIでラクして稼ぐ系・情弱煽り系・キラキラ起業系・強すぎる断定・AI万能論・難しい専門家キャラ

### 目指す状態
読者と「一緒に試す」伴走者｜SEO＋実体験＋安心感＋人間味｜「AI量産感を減らした温度のあるSEO記事」
"""


def build_persona_prompt(
    blog_config: dict[str, str],
    media_persona: list[dict],
) -> str:
    """
    ブログ設定・メディア人格をプロンプト埋め込み用テキストにフォーマットして返す。
    両方が空の場合は空文字列を返す。
    末尾に _META_RULES（固定ガイドライン）を付加する。
    """
    if not blog_config and not media_persona:
        return ""

    lines: list[str] = [
        "## メディア人格・執筆ガイドライン（以下のルールを必ず遵守して記事を書くこと）\n",
    ]

    if blog_config:
        lines.append("### ブログ設定")
        for key, val in blog_config.items():
            lines.append(f"- {key}: {val}")
        lines.append("")

    if media_persona:
        lines.append("### メディア人格")
        current_major = ""
        for item in media_persona:
            major = item["大項目"]
            if major and major != current_major:
                lines.append(f"\n#### {major}")
                current_major = major
            # 設定内容内の改行は半角スペースに統一してコンパクトに
            content = item["設定内容"].replace("\n\n", " / ").replace("\n", " ")
            lines.append(f"- {item['小項目']}: {content}")
        lines.append("")

    return "\n".join(lines) + "\n" + _META_RULES


