"""
groowill-film site configuration.

This keeps WordPress / Sheets credentials site-scoped while sharing the common
article generation engine.
"""
import os
from dotenv import load_dotenv

_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(os.path.dirname(_SITE_DIR))

load_dotenv(os.path.join(_ROOT_DIR, ".env"))
load_dotenv(os.path.join(_SITE_DIR, ".env"), override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

WP_URL = os.getenv("GROOWILL_FILM_WP_URL", os.getenv("WP_URL", "https://www.groowill.co.jp")).rstrip("/")
WP_USERNAME = os.getenv("GROOWILL_FILM_WP_USERNAME", os.getenv("WP_USERNAME", ""))
WP_APP_PASSWORD = os.getenv("GROOWILL_FILM_WP_APP_PASSWORD", os.getenv("WP_APP_PASSWORD", ""))

GOOGLE_SHEETS_ID = os.getenv("GROOWILL_FILM_GOOGLE_SHEETS_ID", os.getenv("GOOGLE_SHEETS_ID", ""))
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH",
    os.path.join(_ROOT_DIR, "credentials.json"),
)

HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
GSC_SITE_URL = os.getenv("GROOWILL_FILM_GSC_SITE_URL", f"{WP_URL}/")

SITE_NAME = "グルーウィル法人フィルム"
SITE_THEME = "法人向け保護フィルム・特殊サイズ・業務用端末フィルム"

WP_CATEGORY_ID = int(os.getenv("GROOWILL_FILM_WP_CATEGORY_ID", os.getenv("WP_CATEGORY_ID", "1")))
WP_STATUS = os.getenv("GROOWILL_FILM_WP_STATUS", os.getenv("WP_STATUS", "draft"))

MIN_SEARCH_VOLUME = int(os.getenv("GROOWILL_FILM_MIN_SEARCH_VOLUME", "0"))

DATA_DIR = os.path.join(_SITE_DIR, "data")
FILTERED_KEYWORDS_CSV = os.path.join(DATA_DIR, "filtered_keywords.csv")

SHEETS_KEYWORD_COL = "キーワード"
SHEETS_AIM_COL = "AIM判定"
SHEETS_VOLUME_COL = "検索ボリューム"
AIM_POSITIVE_VALUES = {"○", "◯", "AIM", "aim", "あり", "YES", "yes", "true", "True", "1"}

SHEETS_MAIN_SHEET_NAME = os.getenv("GROOWILL_FILM_SHEETS_MAIN_SHEET_NAME", "")
SHEETS_ARTICLE_LIST_NAME = os.getenv("GROOWILL_FILM_SHEETS_ARTICLE_LIST_NAME", "投稿記事一覧")
SHEETS_LEGEND_NAME = os.getenv("GROOWILL_FILM_SHEETS_LEGEND_NAME", "凡例")

CTA_CONFIG: list[dict] = []
