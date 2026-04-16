"""
Serposcope API クライアント

Serposcope (http://localhost:9001) への接続・操作を担う。
- キーワード登録（記事投稿時に呼び出し）
- 順位取得（毎日の sync_ranks.py で使用）

前提:
  - Serposcope が localhost:9001 で起動済み
  - .env に SERPOSCOPE_USER / SERPOSCOPE_PASS を設定
  - Serposcope の Settings で Google.co.jp（日本語）の検索エンジンを追加済み
  - グループ（例: "AIVice"）を作成済み → SERPOSCOPE_GROUP_ID を .env に設定
"""
from __future__ import annotations

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SERPO_URL  = os.getenv("SERPOSCOPE_URL",      "http://localhost:9001")
SERPO_USER = os.getenv("SERPOSCOPE_USER",     "admin")
SERPO_PASS = os.getenv("SERPOSCOPE_PASS",     "")
SERPO_GID  = int(os.getenv("SERPOSCOPE_GROUP_ID", "1"))


class SerposcopeClient:
    """セッションベースの Serposcope API クライアント。"""

    def __init__(self) -> None:
        self._session: requests.Session | None = None

    # ─────────────────────────────────────────────
    # 認証
    # ─────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        if self._session is not None:
            return self._session
        s = requests.Session()
        resp = s.post(
            f"{SERPO_URL}/api/user/login",
            data={"username": SERPO_USER, "password": SERPO_PASS},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Serposcope ログイン失敗 ({resp.status_code}): {resp.text[:200]}"
            )
        self._session = s
        return s

    # ─────────────────────────────────────────────
    # グループ・検索エンジン
    # ─────────────────────────────────────────────

    def list_groups(self) -> list[dict]:
        """登録グループ一覧を返す。"""
        s = self._get_session()
        resp = s.get(f"{SERPO_URL}/api/group", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def list_search_engines(self) -> list[dict]:
        """登録済み検索エンジン一覧を返す。"""
        s = self._get_session()
        resp = s.get(f"{SERPO_URL}/api/search-engine", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_google_jp_engine_id(self) -> int | None:
        """
        Google.co.jp / ja の検索エンジン ID を返す。
        未登録の場合は None。
        Serposcope の Settings で追加してから使用すること。
        """
        engines = self.list_search_engines()
        for e in engines:
            # "google.co.jp" かつ言語 "ja" のエントリを探す
            country = (e.get("country") or "").lower()
            lang    = (e.get("tag") or e.get("lang") or "").lower()
            name    = (e.get("name") or "").lower()
            if "google" in name and ("co.jp" in name or "japan" in country or lang == "ja"):
                return e.get("id")
        # フォールバック: google 系の最初のエントリ
        for e in engines:
            if "google" in (e.get("name") or "").lower():
                return e.get("id")
        return None

    # ─────────────────────────────────────────────
    # キーワード登録
    # ─────────────────────────────────────────────

    def add_keyword(
        self,
        keyword: str,
        group_id: int | None = None,
        engine_id: int | None = None,
    ) -> bool:
        """
        キーワードをグループに追加する。

        Args:
            keyword:   追跡するキーワード
            group_id:  グループID（未指定は SERPOSCOPE_GROUP_ID）
            engine_id: 検索エンジンID（未指定は Google JP を自動取得）

        Returns:
            True: 登録成功 / False: 既登録または失敗
        """
        gid = group_id or SERPO_GID
        eid = engine_id or self.get_google_jp_engine_id()
        if eid is None:
            raise RuntimeError(
                "Google JP の検索エンジンが Serposcope に未登録です。"
                " Settings → Search Engines で追加してください。"
            )

        s = self._get_session()
        resp = s.post(
            f"{SERPO_URL}/api/search/add",
            data={
                "groupId":        gid,
                "keywords":       keyword,   # 1行1キーワード（複数行も可）
                "searchEngineId": eid,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"[serposcope] キーワード登録: 「{keyword}」 (group={gid}, engine={eid})")
            return True
        # 409 = 既登録など
        print(f"[serposcope] 登録スキップ ({resp.status_code}): 「{keyword}」 {resp.text[:100]}")
        return False

    # ─────────────────────────────────────────────
    # 順位取得
    # ─────────────────────────────────────────────

    def get_ranks(self, group_id: int | None = None) -> list[dict]:
        """
        グループ内の全キーワードの最新順位を返す。

        Returns:
            [
              {
                "keyword": "ChatGPT 使い方",
                "rank":    3,           # 圏外は None
                "url":     "https://...",
                "date":    "2026-04-05",
              },
              ...
            ]
        """
        gid = group_id or SERPO_GID
        s = self._get_session()

        # 検索リスト取得
        resp = s.get(
            f"{SERPO_URL}/api/search",
            params={"groupId": gid},
            timeout=15,
        )
        resp.raise_for_status()
        searches = resp.json()  # [{id, keyword, ...}, ...]

        results: list[dict] = []
        for search in searches:
            sid     = search.get("id")
            keyword = search.get("keyword") or search.get("name") or ""

            rank_resp = s.get(
                f"{SERPO_URL}/api/rank",
                params={"searchId": sid},
                timeout=10,
            )
            if rank_resp.status_code != 200:
                results.append({"keyword": keyword, "rank": None, "url": "", "date": ""})
                continue

            data = rank_resp.json()
            # Serposcope が返す形式: {"rank": N, "url": "...", "date": "..."} など
            # バージョンによって構造が異なる可能性あり
            rank = data.get("rank") if isinstance(data, dict) else None
            url  = data.get("url", "") if isinstance(data, dict) else ""
            date_str = data.get("date", "") if isinstance(data, dict) else ""

            # list 形式で返ってくる場合は最新（先頭）を取得
            if isinstance(data, list) and data:
                latest = data[0]
                rank     = latest.get("rank")
                url      = latest.get("url", "")
                date_str = latest.get("date", "")

            results.append({
                "keyword": keyword,
                "rank":    rank,
                "url":     url,
                "date":    date_str,
            })

        return results

    def get_ranks_as_dict(self, group_id: int | None = None) -> dict[str, int | None]:
        """
        {keyword: rank} の辞書を返すショートカット。
        圏外キーワードの rank は None。
        """
        return {r["keyword"]: r["rank"] for r in self.get_ranks(group_id)}
