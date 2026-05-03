"""
Google Search Console API クライアント

サービスアカウントで Search Console の検索パフォーマンスデータを取得する。
取得できる指標: 順位(position)・表示回数(impressions)・クリック数(clicks)・CTR

前提:
  - .env に GSC_SITE_URL を設定（例: https://workup-ai.com/）
  - Search Console のプロパティに
    article-bot@oya-kw-cyousa.iam.gserviceaccount.com を追加済み

NOTE:
  GSC データには約 2〜3 日の遅延がある。
  デフォルトでは直近でデータが存在する日付を自動検出する。
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

GSC_SITE_URL         = os.getenv("GSC_SITE_URL", "https://workup-ai.com/")
GSC_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


class GSCClient:
    """Search Console API クライアント（遅延初期化）。"""

    def __init__(self, site_url: str | None = None, credentials_path: str | None = None) -> None:
        raw = (site_url or GSC_SITE_URL)
        # sc-domain: プロパティはスラッシュ不要
        self.site_url         = raw if raw.startswith("sc-domain:") else raw.rstrip("/") + "/"
        self.credentials_path = credentials_path or GSC_CREDENTIALS_PATH
        self._service         = None

    def _get_service(self):
        if self._service is None:
            creds = Credentials.from_service_account_file(
                self.credentials_path, scopes=_SCOPES
            )
            self._service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        return self._service

    # ─────────────────────────────────────────────
    # ページ×クエリ 一括取得（メイン）
    # ─────────────────────────────────────────────

    def get_page_query_data(
        self,
        target_date: date | None = None,
        row_limit: int = 25000,
    ) -> dict[str, list[dict]]:
        """
        全ページ × 全クエリのデータを取得し、URL → クエリリストの辞書で返す。

        Returns:
            {
              "https://workup-ai.com/chatgpt-tsukaikata": [
                {"query": "chatgpt 使い方", "position": 3.2, "impressions": 120,
                 "clicks": 18, "ctr": 0.15},
                ...
              ],
              ...
            }
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=3)

        date_str = target_date.isoformat()
        service  = self._get_service()

        response = service.searchanalytics().query(
            siteUrl=self.site_url,
            body={
                "startDate":  date_str,
                "endDate":    date_str,
                "dimensions": ["page", "query"],
                "rowLimit":   row_limit,
                "dataState":  "all",
            },
        ).execute()

        page_data: dict[str, list[dict]] = defaultdict(list)
        for row in response.get("rows", []):
            keys  = row.get("keys", [])
            page  = keys[0] if len(keys) > 0 else ""
            query = keys[1] if len(keys) > 1 else ""
            page_data[page].append({
                "query":       query,
                "position":    row.get("position",    0.0),
                "impressions": row.get("impressions", 0),
                "clicks":      row.get("clicks",      0),
                "ctr":         row.get("ctr",         0.0),
            })

        return dict(page_data)

    # ─────────────────────────────────────────────
    # キーワードマッチング
    # ─────────────────────────────────────────────

    @staticmethod
    def find_best_query(target_keyword: str, queries: list[dict]) -> dict | None:
        """
        ページに流入しているクエリ群から、ターゲットキーワードに最も近いものを返す。

        マッチング優先度:
          1. 完全一致（スペース正規化後）
          2. キーワードの全単語がクエリに含まれる → impressions 降順で最上位
          3. キーワードの過半数の単語がクエリに含まれる → impressions 降順で最上位
          4. impressions が最大のクエリ（フォールバック）
        """
        if not queries:
            return None

        kw_normalized = " ".join(target_keyword.lower().split())
        kw_words      = set(kw_normalized.split())

        # 1. 完全一致
        for q in queries:
            if " ".join(q["query"].lower().split()) == kw_normalized:
                return q

        # 2. キーワードの全単語がクエリに含まれる
        full_match = [
            q for q in queries
            if kw_words and kw_words.issubset(set(q["query"].lower().split()))
        ]
        if full_match:
            return max(full_match, key=lambda x: x["impressions"])

        # 3. 過半数の単語が含まれる
        threshold = max(1, len(kw_words) // 2)
        partial_match = [
            q for q in queries
            if len(kw_words & set(q["query"].lower().split())) >= threshold
        ]
        if partial_match:
            return max(partial_match, key=lambda x: x["impressions"])

        # 4. フォールバック: impressions 最大
        return max(queries, key=lambda x: x["impressions"])

    # ─────────────────────────────────────────────
    # 接続確認・最新日付検出
    # ─────────────────────────────────────────────

    def find_latest_date_with_data(self, max_days_back: int = 7) -> date | None:
        """データが存在する最新の日付を返す（最大 max_days_back 日前まで探す）。"""
        service = self._get_service()
        for delta in range(2, max_days_back + 1):
            d        = date.today() - timedelta(days=delta)
            date_str = d.isoformat()
            try:
                resp = service.searchanalytics().query(
                    siteUrl=self.site_url,
                    body={
                        "startDate":  date_str,
                        "endDate":    date_str,
                        "dimensions": ["query"],
                        "rowLimit":   1,
                    },
                ).execute()
                if resp.get("rows"):
                    return d
            except Exception:
                continue
        return None
