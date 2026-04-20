"""
blog_registry.py
ブログ管理シートから稼働中ブログ一覧を取得するモジュール。

管理スプレッドシート（CANDIDATE_SS_ID）の「ブログ管理」シートを読み込み、
ステータスが「稼働中」の行のみを処理対象として返す。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

# 管理スプレッドシートID（環境変数で上書き可）
MGMT_SS_ID = os.environ.get(
    "BLOG_MGMT_SS_ID",
    "1_pgNf2-JNlT2uwJFGzlVPGpuVpj2mf5eSsa_YLwMwGc",
)
MGMT_SHEET_NAME = "ブログ管理"
ACTIVE_STATUS   = "稼働中"

# 列マッピング（ヘッダー行で動的解決するが、固定フォールバック用に保持）
_COL_BLOG_NAME  = "ブログ名"
_COL_DIR_NAME   = "ディレクトリ名"
_COL_STATUS     = "ステータス"
_COL_PV_URL     = "PV記事URL"
_COL_CMP_URL    = "比較記事URL"
_COL_CV_URL     = "成約記事URL"


def load_active_blogs(credentials_path: str = "./credentials.json") -> list[dict]:
    """
    ブログ管理シートから稼働中ブログ一覧を返す。

    Returns:
        list of dict with keys:
          - name        : ディレクトリ名（blogs/ 以下のフォルダ名）
          - display_name: ブログ名（表示用）
          - guide_links : {"pv_url": ..., "comparison_url": ..., "cv_url": ...}
        空リストの場合はフォールバックを想定。
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        log.warning(f"[blog_registry] gspread/google-auth が未インストール: {e}")
        return []

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        gc    = gspread.authorize(creds)
        sh    = gc.open_by_key(MGMT_SS_ID)
        ws    = sh.worksheet(MGMT_SHEET_NAME)
    except Exception as e:
        log.warning(f"[blog_registry] ブログ管理シート接続エラー: {e}")
        return []

    try:
        all_values = ws.get_all_values()
    except Exception as e:
        log.warning(f"[blog_registry] シート読み込みエラー: {e}")
        return []

    if not all_values:
        log.warning("[blog_registry] ブログ管理シートが空です")
        return []

    # ヘッダー行でカラム番号を動的解決
    headers = all_values[0]
    col = {h.strip(): i for i, h in enumerate(headers)}

    required = [_COL_DIR_NAME, _COL_STATUS]
    for r in required:
        if r not in col:
            log.warning(f"[blog_registry] 必須列「{r}」がシートに見つかりません（列: {headers}）")
            return []

    results: list[dict] = []
    for row_idx, row in enumerate(all_values[1:], start=2):
        def _cell(col_name: str) -> str:
            idx = col.get(col_name)
            if idx is None or idx >= len(row):
                return ""
            return (row[idx] or "").strip()

        status   = _cell(_COL_STATUS)
        dir_name = _cell(_COL_DIR_NAME)

        if status != ACTIVE_STATUS:
            continue
        if not dir_name:
            log.warning(f"[blog_registry] row {row_idx}: ディレクトリ名が空のためスキップ")
            continue

        guide_links = {
            "pv_url":         _cell(_COL_PV_URL),
            "comparison_url": _cell(_COL_CMP_URL),
            "cv_url":         _cell(_COL_CV_URL),
        }

        results.append({
            "name":         dir_name,
            "display_name": _cell(_COL_BLOG_NAME) or dir_name,
            "guide_links":  guide_links,
        })
        log.debug(f"[blog_registry] 稼働中ブログ登録: {dir_name}")

    log.info(f"[blog_registry] ブログ管理シートから {len(results)} 件の稼働中ブログを読み込みました")
    return results
