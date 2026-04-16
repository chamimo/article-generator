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

_url:      str | None = None
_username: str | None = None
_password: str | None = None


def set_context(
    wp_url:          str | None = None,
    wp_username:     str | None = None,
    wp_app_password: str | None = None,
) -> None:
    """
    ブログ別の WP 認証情報をセットする。
    None を渡すと config.py のデフォルト値にフォールバックする。
    ブログ切り替え時はキャッシュもクリアする。
    """
    global _url, _username, _password
    _url      = wp_url
    _username = wp_username
    _password = wp_app_password
    _clear_caches()


def clear_context() -> None:
    """コンテキストをデフォルトに戻す（ブログ処理終了後に呼ぶ）。"""
    set_context()


def get_wp_url() -> str:
    return _url or _DEFAULT_URL


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
