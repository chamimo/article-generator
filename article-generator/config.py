import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# WordPress
WP_URL = os.getenv("WP_URL", "https://workup-ai.com").rstrip("/")
WP_USERNAME = os.getenv("WP_USERNAME", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")

# Google Sheets
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")

# Filter settings
MIN_SEARCH_VOLUME = int(os.getenv("MIN_SEARCH_VOLUME", "50"))

# WordPress post settings
WP_CATEGORY_ID = int(os.getenv("WP_CATEGORY_ID", "1"))
WP_STATUS = os.getenv("WP_STATUS", "draft")

# Hugging Face
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")

# Site info
SITE_NAME = "AIVice"
SITE_THEME = "AIツール・生成AI活用情報メディア"

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FILTERED_KEYWORDS_CSV = os.path.join(DATA_DIR, "filtered_keywords.csv")

# Google Sheets column names (adjust to match your sheet)
SHEETS_KEYWORD_COL = "キーワード"
SHEETS_AIM_COL = "AIM判定"
SHEETS_VOLUME_COL = "検索ボリューム"
# Values that count as AIM-positive in the AIM判定 column
AIM_POSITIVE_VALUES = {"○", "◯", "AIM", "aim", "あり", "YES", "yes", "true", "True", "1"}
