import json, os
from dotenv import load_dotenv

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_DIR))
load_dotenv(os.path.join(_ROOT, ".env"))

with open(os.path.join(_DIR, "blog_config.json"), encoding="utf-8") as _f:
    _c = json.load(_f)

ANTHROPIC_API_KEY       = os.getenv("ANTHROPIC_API_KEY", "")
WP_URL                  = (os.getenv(_c.get("wp_url_env", "WP_URL")) or _c.get("wp_url", "")).rstrip("/")
WP_USERNAME             = os.getenv(_c.get("wp_username_env", "WP_USERNAME"), "")
WP_APP_PASSWORD         = os.getenv(_c.get("wp_app_password_env", "WP_APP_PASSWORD"), "")
GOOGLE_SHEETS_ID        = _c.get("candidate_ss_id", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", os.path.join(_ROOT, "credentials.json"))
HUGGINGFACE_API_KEY     = os.getenv("HUGGINGFACE_API_KEY", "")
GSC_SITE_URL            = _c.get("gsc_site_url") or (WP_URL.rstrip("/") + "/")
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
CTA_CONFIG: list[dict]   = []
