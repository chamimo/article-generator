"""
サイト設定プロキシ

ARTICLE_SITE 環境変数で指定されたサイトの設定を読み込み、
全モジュールに透過的に公開する。

環境変数:
  ARTICLE_SITE=workup-ai  （デフォルト）

設定ファイルの場所:
  sites/<ARTICLE_SITE>/config.py

全モジュールは引き続き "from config import X" でインポートできる。
"""
import importlib.util
import os

_SITE     = os.environ.get("ARTICLE_SITE", "workup-ai")
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# blogs/ 優先、sites/ をフォールバック
_BLOGS_CFG = os.path.join(_BASE_DIR, "blogs", _SITE, "config.py")
_SITES_CFG = os.path.join(_BASE_DIR, "sites",  _SITE, "config.py")

if os.path.exists(_BLOGS_CFG):
    _CFG_PATH = _BLOGS_CFG
elif os.path.exists(_SITES_CFG):
    _CFG_PATH = _SITES_CFG
else:
    raise FileNotFoundError(
        f"[config] サイト設定が見つかりません: {_SITE}\n"
        f"  blogs/{_SITE}/config.py または sites/{_SITE}/config.py を作成してください。\n"
        f"  テンプレート: sites/new-blog/config.py.sample"
    )

_spec = importlib.util.spec_from_file_location("_site_config", _CFG_PATH)
_m    = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)

# ── 全設定変数を再エクスポート ──────────────────────────────────────────
ANTHROPIC_API_KEY      = _m.ANTHROPIC_API_KEY
OPENAI_API_KEY         = getattr(_m, "OPENAI_API_KEY", "")
WP_URL                 = _m.WP_URL
WP_USERNAME            = _m.WP_USERNAME
WP_APP_PASSWORD        = _m.WP_APP_PASSWORD
GOOGLE_SHEETS_ID       = _m.GOOGLE_SHEETS_ID
GOOGLE_CREDENTIALS_PATH = _m.GOOGLE_CREDENTIALS_PATH
HUGGINGFACE_API_KEY    = _m.HUGGINGFACE_API_KEY
GSC_SITE_URL           = _m.GSC_SITE_URL
SITE_NAME              = _m.SITE_NAME
SITE_THEME             = _m.SITE_THEME
WP_CATEGORY_ID         = _m.WP_CATEGORY_ID
WP_STATUS              = _m.WP_STATUS
MIN_SEARCH_VOLUME      = _m.MIN_SEARCH_VOLUME
DATA_DIR               = _m.DATA_DIR
FILTERED_KEYWORDS_CSV  = _m.FILTERED_KEYWORDS_CSV
SHEETS_KEYWORD_COL     = _m.SHEETS_KEYWORD_COL
SHEETS_AIM_COL         = _m.SHEETS_AIM_COL
SHEETS_VOLUME_COL      = _m.SHEETS_VOLUME_COL
AIM_POSITIVE_VALUES    = _m.AIM_POSITIVE_VALUES
CTA_CONFIG             = _m.CTA_CONFIG
SHEETS_MAIN_SHEET_NAME   = _m.SHEETS_MAIN_SHEET_NAME
SHEETS_ARTICLE_LIST_NAME = _m.SHEETS_ARTICLE_LIST_NAME
SHEETS_LEGEND_NAME       = _m.SHEETS_LEGEND_NAME
