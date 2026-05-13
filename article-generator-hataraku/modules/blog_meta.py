"""
blog_meta.py
ブログ管理シートからブログ別メタデータを動的に取得するモジュール。

取得するフィールド:
  - site_purpose        : サイトの目的
  - target              : ターゲット
  - writing_taste       : 文章のテイスト
  - genre               : ジャンル
  - search_intent       : 検索意図タイプ（Know / Do / Buy）
  - eyecatch_model      : サムネ生成モデル（空=FLUX.1-schnell）
  - article_image_model : 記事内画像生成モデル（空=FLUX.1-schnell）

値が空の場合は空文字列を返す（デフォルト動作）。
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

MGMT_SS_ID    = os.environ.get("BLOG_MGMT_SS_ID", "1_pgNf2-JNlT2uwJFGzlVPGpuVpj2mf5eSsa_YLwMwGc")
MGMT_SHEET    = "ブログ管理"

_COL_DIR_NAME            = "ディレクトリ名"
_COL_STATUS              = "ステータス"
_COL_SITE_PURPOSE        = "サイトの目的"
_COL_TARGET              = "ターゲット"
_COL_WRITING_TASTE       = "文章のテイスト"
_COL_GENRE               = "ジャンル"
_COL_SEARCH_INTENT       = "検索意図タイプ"  # ヘッダーに改行が含まれるため前方一致で解決
_COL_EYECATCH_MODEL      = "サムネモデル"
_COL_ARTICLE_IMAGE_MODEL = "記事内画像モデル"

# プロセス内キャッシュ（実行1回につき1回だけシートを読む）
_cache: dict[str, dict] | None = None


def _load_sheet(credentials_path: str) -> dict[str, dict]:
    """シート全体を読み込み {ディレクトリ名: メタデータ} 形式で返す。"""
    global _cache
    if _cache is not None:
        return _cache

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        log.warning(f"[blog_meta] gspread 未インストール: {e}")
        _cache = {}
        return _cache

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        gc    = gspread.authorize(creds)
        ws    = gc.open_by_key(MGMT_SS_ID).worksheet(MGMT_SHEET)
        rows  = ws.get_all_values()
    except Exception as e:
        log.warning(f"[blog_meta] 管理シート読み込みエラー: {e}")
        _cache = {}
        return _cache

    if not rows:
        _cache = {}
        return _cache

    # ヘッダーを正規化して列インデックスを解決
    raw_headers = rows[0]
    # 改行・スペース除去した形で比較（「検索意図タイプ\n（Know / Do / Buy）」対応）
    normalized = [h.strip().replace("\n", "").replace(" ", "").replace("　", "") for h in raw_headers]

    def _find_col(name: str) -> int | None:
        clean = name.replace(" ", "").replace("　", "")
        for i, h in enumerate(normalized):
            if h == clean or h.startswith(clean):
                return i
        return None

    col = {
        "dir":           _find_col(_COL_DIR_NAME),
        "purpose":       _find_col(_COL_SITE_PURPOSE),
        "target":        _find_col(_COL_TARGET),
        "taste":         _find_col(_COL_WRITING_TASTE),
        "genre":         _find_col(_COL_GENRE),
        "intent":        _find_col(_COL_SEARCH_INTENT),
        "eyecatch":      _find_col(_COL_EYECATCH_MODEL),
        "article_image": _find_col(_COL_ARTICLE_IMAGE_MODEL),
    }

    result: dict[str, dict] = {}
    for row in rows[1:]:
        def _cell(key: str) -> str:
            idx = col.get(key)
            if idx is None or idx >= len(row):
                return ""
            return (row[idx] or "").strip()

        dir_name = _cell("dir")
        if not dir_name:
            continue
        result[dir_name] = {
            "site_purpose":        _cell("purpose"),
            "target":              _cell("target"),
            "writing_taste":       _cell("taste"),
            "genre":               _cell("genre"),
            "search_intent":       _cell("intent"),
            "eyecatch_model":      _cell("eyecatch"),
            "article_image_model": _cell("article_image"),
        }

    log.info(f"[blog_meta] {len(result)} 件のブログメタデータを管理シートから読み込みました")
    _cache = result
    return _cache


def load_blog_meta(blog_name: str, credentials_path: str = "./credentials.json") -> dict:
    """
    指定ブログのメタデータを管理シートから返す。

    Returns:
        {
            "site_purpose":  str,  # 空文字 = Claude自動判断
            "target":        str,
            "writing_taste": str,
            "genre":         str,
            "search_intent": str,  # "Know" / "Do" / "Buy" / ""
        }
    """
    data = _load_sheet(credentials_path)
    meta = data.get(blog_name, {})
    if meta:
        log.info(
            f"[blog_meta] {blog_name}: "
            f"目的={'あり' if meta.get('site_purpose') else '空'}  "
            f"ターゲット={'あり' if meta.get('target') else '空'}  "
            f"テイスト={'あり' if meta.get('writing_taste') else '空'}  "
            f"意図={meta.get('search_intent') or '空'}"
        )
    else:
        log.debug(f"[blog_meta] {blog_name}: 管理シートに未登録（デフォルト使用）")
    return {
        "site_purpose":        meta.get("site_purpose", ""),
        "target":              meta.get("target", ""),
        "writing_taste":       meta.get("writing_taste", ""),
        "genre":               meta.get("genre", ""),
        "search_intent":       meta.get("search_intent", ""),
        "eyecatch_model":      meta.get("eyecatch_model", ""),
        "article_image_model": meta.get("article_image_model", ""),
    }


def clear_cache() -> None:
    """テスト・ブログ切り替え時にキャッシュをクリアする。"""
    global _cache
    _cache = None
