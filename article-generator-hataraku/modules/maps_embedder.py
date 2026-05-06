"""
Google Maps を記事に自動挿入するモジュール。hida-no-omoide 専用。

APIキー不要の埋め込み URL (maps.google.com/maps?output=embed) を使用。
キーワード・タイトルから Claude Haiku で場所クエリを抽出し、
「まとめ」「おわりに」見出し直後に iframe を1枚挿入する。
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse

log = logging.getLogger(__name__)

_SUMMARY_HEADING_RE = re.compile(
    r'(<h[23][^>]*>\s*(?:まとめ|おわりに|さいごに|最後に|総まとめ)[^<]*</h[23]>)',
    re.IGNORECASE,
)


def _extract_map_info(keyword: str, title: str) -> dict | None:
    """
    Claude Haiku でキーワード・タイトルから地図モードとクエリを抽出する。
    Returns: {"mode": "place"|"search", "query": str}  or None（スキップ）
    """
    try:
        import anthropic
        from modules.api_guard import check_stop, record_usage
    except ImportError as e:
        log.warning(f"[maps_embedder] インポートエラー: {e}")
        return None

    prompt = f"""飛騨・高山の観光記事のキーワードとタイトルを読んで、Google Maps Embed APIに渡す地図情報をJSONで返してください。

キーワード: {keyword}
タイトル: {title}

判定ルール:
1. 固有名詞の単一スポット（神社・寺・朝市・カフェ・博物館・旅館・橋・滝など）→ mode: "place", query: スポット名（例: "宮川朝市 高山市"）
2. エリアや複数スポット（〇選・おすすめ・観光スポット・グルメ・ルートなど）→ mode: "search", query: "飛騨高山 ＋テーマ" 形式（例: "飛騨高山 カフェ"）
3. 地図が不適切な記事（お土産通販・賞味期限・日持ち・価格・買取など）→ mode: "skip"

JSONのみ返してください（説明不要）:
{{"mode": "place" or "search" or "skip", "query": "検索クエリ（日本語）"}}"""

    try:
        check_stop()
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        record_usage("claude-haiku-4-5-20251001",
                     msg.usage.input_tokens, msg.usage.output_tokens, f"maps:{keyword}")
        raw = msg.content[0].text.strip()
        # コードブロック除去
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
        data = json.loads(raw)
        if data.get("mode") == "skip" or not data.get("query"):
            log.debug(f"[maps_embedder] スキップ判定: {keyword}")
            return None
        return {"mode": data["mode"], "query": data["query"]}
    except Exception as e:
        log.warning(f"[maps_embedder] 地図情報抽出エラー: {e}")
        return None


def _build_iframe(query: str) -> str:
    """APIキー不要の Google Maps 埋め込み iframe HTML を生成する。"""
    encoded = urllib.parse.quote(query)
    src = f"https://maps.google.com/maps?q={encoded}&output=embed&hl=ja"
    return (
        f'\n<iframe\n'
        f'  src="{src}"\n'
        f'  width="100%" height="400"\n'
        f'  style="border:0; border-radius:8px; margin:16px 0;"\n'
        f'  allowfullscreen="" loading="lazy">\n'
        f'</iframe>\n'
    )


def insert_map(content: str, keyword: str, title: str) -> str:
    """
    記事コンテンツの「まとめ」見出し直後にGoogle Mapsのiframeを挿入する。

    挿入できない場合（場所不明・まとめ見出しなし）は元の content をそのまま返す。
    """
    # まとめ見出しを探す
    m = _SUMMARY_HEADING_RE.search(content)
    if not m:
        log.debug("[maps_embedder] まとめ見出しが見つからないためスキップ")
        return content

    # 地図情報を抽出
    map_info = _extract_map_info(keyword, title)
    if not map_info:
        return content

    iframe_html = _build_iframe(map_info["query"])

    # まとめ見出し直後に挿入
    insert_pos = m.end()
    new_content = content[:insert_pos] + iframe_html + content[insert_pos:]

    print(f"[maps_embedder] ✅ 地図挿入: mode={map_info['mode']} / query={map_info['query']}")
    log.info(f"[maps_embedder] 地図挿入完了: mode={map_info['mode']} query={map_info['query']}")
    return new_content
