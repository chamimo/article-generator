"""
workup-ai.com サイト設定

このファイルに workup-ai.com 固有の全設定を集約する。
新しいサイトを追加する場合は sites/<site名>/config.py を同じ形式で作成すること。
"""
import os
from dotenv import load_dotenv

# ── パス解決 ──────────────────────────────────────────────────────────────
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))          # sites/workup-ai/
_ROOT_DIR = os.path.dirname(os.path.dirname(_SITE_DIR))         # article-generator/

# .env 読み込み順: ルート .env → サイト固有 .env（上書き）
load_dotenv(os.path.join(_ROOT_DIR, ".env"))
load_dotenv(os.path.join(_SITE_DIR, ".env"), override=True)     # サイト専用 .env (省略可)

# ── Anthropic ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── WordPress ─────────────────────────────────────────────────────────────
WP_URL           = os.getenv("WP_URL", "https://workup-ai.com").rstrip("/")
WP_USERNAME      = os.getenv("WP_USERNAME", "")
WP_APP_PASSWORD  = os.getenv("WP_APP_PASSWORD", "")

# ── Google Sheets ──────────────────────────────────────────────────────────
GOOGLE_SHEETS_ID       = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH",
    os.path.join(_ROOT_DIR, "credentials.json"),
)

# ── Hugging Face ───────────────────────────────────────────────────────────
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")

# ── Google Search Console ──────────────────────────────────────────────────
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "https://workup-ai.com/")

# ── サイト情報 ──────────────────────────────────────────────────────────────
SITE_NAME  = "AIVice"
SITE_THEME = "AIツール・生成AI活用情報メディア"

# ── WordPress 投稿設定 ─────────────────────────────────────────────────────
WP_CATEGORY_ID = int(os.getenv("WP_CATEGORY_ID", "1"))
WP_STATUS      = os.getenv("WP_STATUS", "draft")

# ── フィルター設定 ────────────────────────────────────────────────────────
MIN_SEARCH_VOLUME = int(os.getenv("MIN_SEARCH_VOLUME", "50"))

# ── パス ──────────────────────────────────────────────────────────────────
DATA_DIR              = os.path.join(_ROOT_DIR, "data")
FILTERED_KEYWORDS_CSV = os.path.join(DATA_DIR, "filtered_keywords.csv")

# ── Google Sheets 列設定 ──────────────────────────────────────────────────
SHEETS_KEYWORD_COL  = "キーワード"
SHEETS_AIM_COL      = "AIM判定"
SHEETS_VOLUME_COL   = "検索ボリューム"
AIM_POSITIVE_VALUES = {"○", "◯", "AIM", "aim", "あり", "YES", "yes", "true", "True", "1"} | {"claude"}

# ── Google Sheets シート名 ────────────────────────────────────────────────
SHEETS_MAIN_SHEET_NAME    = os.getenv("SHEETS_MAIN_SHEET_NAME", "")
SHEETS_ARTICLE_LIST_NAME  = os.getenv("SHEETS_ARTICLE_LIST_NAME", "投稿記事一覧")
SHEETS_LEGEND_NAME        = os.getenv("SHEETS_LEGEND_NAME", "凡例")

# ─────────────────────────────────────────────────────────────────────────
# CTA設定
#
# 新しいASP案件を追加する手順：
#   1. 下記リストに新しい dict を追記する
#   2. name    : 管理用の案件名（ログに表示される）
#   3. keywords: キーワードに含まれる文字列リスト（小文字一致）
#   4. positions: 挿入位置のリスト
#       "top"    → 「この記事のポイント」cap-block の直後
#       "middle" → H2[2] と H2[3] の間（ASP案件向け）
#       "bottom" → 「まとめ」H3 の直前
#   5. block   : 挿入するGutenbergブロックHTML（SWELLテーマ形式）
# ─────────────────────────────────────────────────────────────────────────
CTA_CONFIG: list[dict] = [
    # ── PLAUD ─────────────────────────────────────────────────
    {
        "name": "PLAUD",
        "keywords": ["plaud", "ボイスレコーダー", "録音", "icレコーダー", "ＩＣレコーダー", "プラウド"],
        "positions": ["top", "bottom"],
        "block": """\
<!-- wp:group {"metadata":{"categories":["call-to-action"],"patternName":"core/block/7009","name":"【テンプレート】マイクロコピーmc"},"className":"has-border -border02 is-style-bg_stripe","layout":{"type":"constrained"}} -->
<div class="wp-block-group has-border -border02 is-style-bg_stripe">
<!-- wp:paragraph {"className":"has-text-align-center u-mb-0 u-mb-ctrl"} -->
<p class="has-text-align-center u-mb-0 u-mb-ctrl"><span class="swl-inline-color has-swl-main-color"><strong><span style="font-size:16px" class="swl-fz"><strong><strong>＼ 必要だと感じたら今すぐ確認がお得 ／ </strong></strong></span></strong></span></p>
<!-- /wp:paragraph -->
<!-- wp:loos/button {"hrefUrl":"/plaud","isNewTab":true,"className":"is-style-btn_shiny"} -->
<div class="swell-block-button is-style-btn_shiny"><a href="/plaud" target="_blank" rel="noopener noreferrer" class="swell-block-button__link"><span>＞＞ PLAUD NOTE公式サイトをチェックしてみる</span></a></div>
<!-- /wp:loos/button -->
</div>
<!-- /wp:group -->""",
    },
    # ── Notta ─────────────────────────────────────────────────
    {
        "name": "Notta",
        "keywords": ["文字起こし", "議事録", "ボイスメモ", "要約", "会議", "notta", "ノッタ"],
        "positions": ["top", "bottom"],
        "block": """\
<!-- wp:group {"className":"is-style-bg_stripe has-border -border02","layout":{"type":"constrained"}} -->
<div class="wp-block-group is-style-bg_stripe has-border -border02">
<!-- wp:paragraph {"className":"has-text-align-center u-mb-0 u-mb-ctrl"} -->
<p class="has-text-align-center u-mb-0 u-mb-ctrl"><span class="swl-inline-color has-swl-main-color"><strong><span style="font-size:17px" class="swl-fz">＼ </span>今なら無料トライアル＆自動参加ボットがすぐ使える！<span style="font-size:17px" class="swl-fz">／</span></strong><br></span><span class="swl-fz u-fz-s">🎉 会議のムダをゼロに！AI議事録で生産性アップ 🎉</span></p>
<!-- /wp:paragraph -->
<!-- wp:loos/button {"hrefUrl":"/notta","isNewTab":true,"iconName":"LsChevronRight","color":"red","fontSize":"1.1em","btnSize":"l","className":"is-style-btn_shiny u-mb-ctrl u-mb-10"} -->
<div class="swell-block-button red_ -size-l is-style-btn_shiny u-mb-ctrl u-mb-10" style="--the-fz:1.1em"><a href="/notta" target="_blank" rel="noopener noreferrer" class="swell-block-button__link" data-has-icon="1"><svg class="__icon" height="1em" width="1em" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" viewBox="0 0 48 48"><path d="m33 25.1-13.1 13c-.8.8-2 .8-2.8 0-.8-.8-.8-2 0-2.8L28.4 24 17.1 12.7c-.8-.8-.8-2 0-2.8.8-.8 2-.8 2.8 0l13.1 13c.6.6.6 1.6 0 2.2z"></path></svg><span><strong>Notta（ノッタ）公式サイトをみる</strong></span></a></div>
<!-- /wp:loos/button -->
<!-- wp:paragraph {"align":"center"} -->
<p class="has-text-align-center"><span style="font-size:18px" class="swl-fz"><strong><span class="swl-bg-color has-swl-pale-04-background-color"><span class="swl-inline-color has-swl-deep-03-color">🎁 <strong>初回利用者限定：チーム全員で使える無料トライアル実施中！</strong><br></span></span></strong></span><span class="swl-bg-color has-swl-pale-04-background-color"><span class="swl-inline-color has-swl-main-color"><span class="swl-fz u-fz-s">AI要約・話者分離・自動参加のフル機能を今すぐ体験できま</span>す🏃‍♀️</span></span></p>
<!-- /wp:paragraph -->
</div>
<!-- /wp:group -->""",
    },
    # ── ASP案件テンプレート ────────────────────────────────────
    # 新しい案件を追加する場合は以下のブロックをコピーして編集する。
    # {
    #     "name": "スピーク",
    #     "keywords": ["スピーク", "speak"],
    #     "positions": ["top", "middle", "bottom"],
    #     "block": """\
    # <!-- wp:group ... -->
    # ...CTAのGutenbergブロックHTMLをここに貼り付け...
    # <!-- /wp:group -->""",
    # },
]
