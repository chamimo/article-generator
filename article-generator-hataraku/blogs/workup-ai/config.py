import json, os
from dotenv import load_dotenv

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_DIR))
load_dotenv(os.path.join(_ROOT, ".env"))

with open(os.path.join(_DIR, "blog_config.json"), encoding="utf-8") as _f:
    _c = json.load(_f)

ANTHROPIC_API_KEY       = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY          = os.getenv("OPENAI_API_KEY", "")
WP_URL                  = (os.getenv(_c.get("wp_url_env", "WP_URL")) or _c.get("wp_url", "")).rstrip("/")
WP_USERNAME             = os.getenv(_c.get("wp_username_env", "WP_USERNAME"), "")
WP_APP_PASSWORD         = os.getenv(_c.get("wp_app_password_env", "WP_APP_PASSWORD"), "")
GOOGLE_SHEETS_ID        = _c.get("candidate_ss_id", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", os.path.join(_ROOT, "credentials.json"))
HUGGINGFACE_API_KEY     = os.getenv("HUGGINGFACE_API_KEY", "")
GSC_SITE_URL            = WP_URL.rstrip("/") + "/"
SITE_NAME               = _c.get("display_name", "")
SITE_THEME              = _c.get("genre", "")
WP_CATEGORY_ID          = int(os.getenv("WP_CATEGORY_ID", "1"))
WP_STATUS               = _c.get("wp_post_status") or os.getenv("WP_STATUS", "draft")
MIN_SEARCH_VOLUME       = _c.get("min_volume", int(os.getenv("MIN_SEARCH_VOLUME", "0")))
DATA_DIR                = os.path.join(_ROOT, "data")
FILTERED_KEYWORDS_CSV   = os.path.join(DATA_DIR, "filtered_keywords.csv")
SHEETS_KEYWORD_COL      = "キーワード"
SHEETS_AIM_COL          = "AIM判定"
SHEETS_VOLUME_COL       = "検索ボリューム"
AIM_POSITIVE_VALUES     = {"○", "◯", "AIM", "aim", "あり", "YES", "yes", "true", "True", "1"} | {"claude"}
SHEETS_MAIN_SHEET_NAME   = _c.get("candidate_sheet", "キーワード")
SHEETS_ARTICLE_LIST_NAME = "投稿記事一覧"
SHEETS_LEGEND_NAME       = "凡例"

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
]
