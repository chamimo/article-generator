"""
WordPress 認証情報コンテキスト管理モジュール

マルチブログ対応のため、モジュールレベルで WP 認証情報を動的に切り替える。
generate_lite.py の post() が set_context() でブログ別の認証情報をセットし、
wordpress_poster / internal_linker / category_selector はすべて
このモジュール経由で認証情報を取得する。

使い方:
    from modules import wp_context
    wp_context.set_context(blog_cfg.wp_url, blog_cfg.wp_username, blog_cfg.wp_app_password)
    try:
        post_article_with_image(...)
    finally:
        wp_context.clear_context()
"""
from __future__ import annotations

from config import WP_URL as _DEFAULT_URL
from config import WP_USERNAME as _DEFAULT_USER
from config import WP_APP_PASSWORD as _DEFAULT_PASS
from requests.auth import HTTPBasicAuth

_url:              str | None = None
_username:         str | None = None
_password:         str | None = None
_post_status:      str | None = None
_candidate_ss_id:  str | None = None
_candidate_sheet:  str | None = None
_image_style:      dict | None = None
_blog_meta:        dict | None = None  # {site_purpose, target, writing_taste, genre_detail, search_intent}
_asp_ss_id:        str  | None = None  # ASP専用SS（空ならcandidate_ss_idにフォールバック）
_default_fallback_category: str = ""   # スコアゼロ時のフォールバックカテゴリ名


def set_context(
    wp_url:           str | None = None,
    wp_username:      str | None = None,
    wp_app_password:  str | None = None,
    wp_post_status:   str | None = None,
    candidate_ss_id:  str | None = None,
    candidate_sheet:  str | None = None,
    image_style:      dict | None = None,
    blog_meta:        dict | None = None,
    asp_ss_id:        str  | None = None,
    default_fallback_category: str = "",
) -> None:
    """
    ブログ別の WP 認証情報をセットする。
    None を渡すと config.py のデフォルト値にフォールバックする。
    ブログ切り替え時はキャッシュもクリアする。
    """
    global _url, _username, _password, _post_status, _candidate_ss_id, _candidate_sheet, _image_style, _blog_meta, _asp_ss_id, _default_fallback_category
    _url              = wp_url
    _username         = wp_username
    _password         = wp_app_password
    _post_status      = wp_post_status
    _candidate_ss_id  = candidate_ss_id
    _candidate_sheet  = candidate_sheet
    _image_style      = image_style or {}
    _blog_meta        = blog_meta or {}
    _asp_ss_id        = asp_ss_id or ""
    _default_fallback_category = default_fallback_category
    _clear_caches()


def clear_context() -> None:
    """コンテキストをデフォルトに戻す（ブログ処理終了後に呼ぶ）。"""
    set_context()


def get_wp_url() -> str:
    return _url or _DEFAULT_URL


def get_post_status() -> str:
    """現在のコンテキストの投稿ステータスを返す。未設定なら config.WP_STATUS にフォールバック。"""
    if _post_status:
        return _post_status
    from config import WP_STATUS
    return WP_STATUS


def get_candidate_ss_id() -> str:
    """ブログ別キーワードスプレッドシートIDを返す。未設定なら config.GOOGLE_SHEETS_ID にフォールバック。"""
    if _candidate_ss_id:
        return _candidate_ss_id
    from config import GOOGLE_SHEETS_ID
    return GOOGLE_SHEETS_ID


def get_candidate_sheet() -> str:
    """ブログ別キーワードシート名を返す。未設定なら config.SHEETS_MAIN_SHEET_NAME にフォールバック。"""
    if _candidate_sheet:
        return _candidate_sheet
    from config import SHEETS_MAIN_SHEET_NAME
    return SHEETS_MAIN_SHEET_NAME


def get_image_style() -> dict:
    """ブログ別画像スタイル設定を返す。未設定なら空dictを返す。"""
    return _image_style or {}


def get_blog_meta() -> dict:
    """ブログ管理シートのメタデータを返す。未設定なら空dictを返す。"""
    return _blog_meta or {}


def get_asp_ss_id() -> str:
    """ASP専用スプレッドシートIDを返す。未設定ならcandidate_ss_idにフォールバック。"""
    if _asp_ss_id:
        return _asp_ss_id
    return get_candidate_ss_id()


def get_default_fallback_category() -> str:
    """スコアゼロ時に使うフォールバックカテゴリ名。未設定なら空文字。"""
    return _default_fallback_category


def get_auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(
        _username or _DEFAULT_USER,
        _password or _DEFAULT_PASS,
    )


def _clear_caches() -> None:
    """
    ブログ切り替え時にモジュールキャッシュをリセットする。
    internal_linker・category_selector がブログをまたいで
    古い記事一覧・カテゴリ一覧を使い続けるのを防ぐ。
    """
    try:
        import modules.internal_linker as _il
        _il._published_articles_cache = None
    except Exception:
        pass
    try:
        import modules.category_selector as _cs
        _cs._category_cache = None
    except Exception:
        pass
    try:
        import modules.sheets_updater as _su
        _su._ss_cache = None
        _su._ws_cache = None
        _su._active_ss_id_cache = None
    except Exception:
        pass
    try:
        import modules.testimonial_fetcher as _tf
        _tf.clear_cache()
    except Exception:
        pass
