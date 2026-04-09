"""
内部リンク自動挿入モジュール

## 選定優先順位
1. ASP案件記事（最優先）
   config.py の CTA_CONFIG に登録されたキーワードにマッチする記事。
   成約率向上のため積極的にリンクする。
2. 同じ親キーワードの記事（次点）
   detect_parent_keyword() で検出した同じ親KWを持つ記事から Claude が選ぶ。
3. その他の関連記事（補完）
   上記2カテゴリで5件に満たない場合に Claude が補完。

## 挿入位置
- H3セクション末尾に SWELL「あわせて読みたい」カード形式で分散挿入
- H3スロットが足りない場合はテキストリンクでまとめH3直前 or 末尾に補完
"""
from __future__ import annotations

import json
import re
import requests
import anthropic
from html import unescape
from requests.auth import HTTPBasicAuth

from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, ANTHROPIC_API_KEY, CTA_CONFIG
from modules.keyword_utils import detect_parent_keyword

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# セッション内キャッシュ（プロセス再起動でリセット）
_published_articles_cache: list[dict] | None = None


# ─────────────────────────────────────────────
# ブロック生成
# ─────────────────────────────────────────────

def _card_block(article: dict) -> str:
    """wp:loos/post-link ブロックを生成する。タイトルはJSON安全にエスケープ。"""
    title_plain = unescape(article["title"])
    link_data = json.dumps(
        {
            "title": title_plain,
            "id":    article["id"],
            "url":   article["link"],
            "kind":  "post-type",
            "type":  "post",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f'\n<!-- wp:loos/post-link {{"linkData":{link_data},"icon":"link"}} /-->'


def _text_link_block(article: dict) -> str:
    """👉 テキストリンクの wp:paragraph ブロックを生成する。"""
    title_plain = unescape(article["title"])
    return (
        "\n<!-- wp:paragraph -->\n"
        f'<p>👉 こちらの記事もおすすめ：'
        f'<a href="{article["link"]}">{title_plain}</a></p>\n'
        "<!-- /wp:paragraph -->"
    )


# ─────────────────────────────────────────────
# WP記事取得
# ─────────────────────────────────────────────

def get_published_articles(force_refresh: bool = False) -> list[dict]:
    """
    公開済みWP記事をセッションキャッシュから返す。
    初回またはforce_refresh=Trueの場合はWP APIから取得する。
    """
    global _published_articles_cache
    if _published_articles_cache is not None and not force_refresh:
        return _published_articles_cache

    articles: list[dict] = []
    page = 1
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)

    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            auth=auth,
            params={
                "per_page": 100,
                "page": page,
                "status": "publish",
                "_fields": "id,title,slug,link",
            },
            timeout=15,
        )
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            articles.append({
                "id":    p["id"],
                "title": p["title"]["rendered"],
                "link":  p.get("link", ""),
            })
        if len(batch) < 100:
            break
        page += 1

    _published_articles_cache = articles
    print(f"[internal_linker] 公開済み記事取得: {len(articles)}件")
    return articles


# ─────────────────────────────────────────────
# ASP案件記事の判定
# ─────────────────────────────────────────────

def _find_asp_articles(published_articles: list[dict]) -> list[dict]:
    """
    CTA_CONFIG のキーワードにマッチする公開済み記事を返す（ASP案件記事）。

    CTA_CONFIG の順番がそのまま優先順位になる。
    同じ記事が複数エントリにマッチしても重複なし。
    """
    seen_ids: set[int] = set()
    result:   list[dict] = []

    for entry in CTA_CONFIG:
        kw_list = [k.lower() for k in entry.get("keywords", [])]
        for article in published_articles:
            if article["id"] in seen_ids:
                continue
            title_lower = unescape(article["title"]).lower()
            if any(kw in title_lower for kw in kw_list):
                result.append(article)
                seen_ids.add(article["id"])

    return result


# ─────────────────────────────────────────────
# Claude による関連記事選定（サブ関数）
# ─────────────────────────────────────────────

def _claude_select(
    keyword: str,
    article_title: str,
    candidates: list[dict],
    max_count: int,
    label: str = "",
) -> list[dict]:
    """
    Claude Haiku で candidates から関連性の高い記事を最大 max_count 件選ぶ。
    label はログ表示用。
    """
    if not candidates or max_count <= 0:
        return []

    # トークン削減のため最大200件
    candidates = candidates[:200]

    articles_text = "\n".join(
        f"[{i}] {a['title']}"
        for i, a in enumerate(candidates)
    )

    prompt = (
        f"内部リンク候補を選んでください。\n\n"
        f"## 新規記事\n"
        f"- キーワード: {keyword}\n"
        f"- タイトル: {article_title}\n\n"
        f"## 候補記事（番号付き）\n"
        f"{articles_text}\n\n"
        f"## ルール\n"
        f"1. 新規記事と関連し、読者が次に読みたいと思える記事を選ぶ\n"
        f"2. 内容が同一・類似しすぎてカニバリになる記事は除外する\n"
        f"3. 最大{max_count}件を選ぶ\n\n"
        f"選んだ番号だけをJSON配列で出力してください。説明不要。例: [0, 3, 7]"
    )

    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r'```[a-z]*\n?', '', raw).strip().strip('`').strip()
        indices: list[int] = json.loads(raw)

        selected = [
            candidates[idx]
            for idx in indices
            if isinstance(idx, int) and 0 <= idx < len(candidates)
        ]
        if label:
            print(f"[internal_linker] {label}: {len(selected)}件選定")
        return selected[:max_count]

    except Exception as e:
        print(f"[internal_linker] Claude選定失敗（{label}）: {e}")
        return []


# ─────────────────────────────────────────────
# メイン選定ロジック（3段階優先順位）
# ─────────────────────────────────────────────

def select_related_articles(
    keyword: str,
    article_title: str,
    published_articles: list[dict],
    max_count: int = 5,
) -> list[dict]:
    """
    公開済み記事から内部リンク候補を優先順位に従って選ぶ。

    優先順位:
      1. ASP案件記事   (CTA_CONFIG のキーワードにマッチする記事)
      2. 同親KW記事    (detect_parent_keyword で検出した同グループ)
      3. その他関連記事 (Claude が残り枠を補完)

    Returns:
        最大 max_count 件のリスト（優先順位順）
    """
    if not published_articles:
        return []

    parent = detect_parent_keyword(keyword)

    # ── 1. ASP案件記事（最優先）──
    asp_articles = _find_asp_articles(published_articles)
    # 現在の記事自身は除外（title完全一致で判断）
    asp_articles = [a for a in asp_articles if unescape(a["title"]) != article_title]

    selected:     list[dict] = []
    selected_ids: set[int]   = set()

    for a in asp_articles:
        if len(selected) >= max_count:
            break
        selected.append(a)
        selected_ids.add(a["id"])

    asp_count = len(selected)
    if asp_count:
        print(f"[internal_linker] ASP案件記事: {asp_count}件追加")

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected

    # ── 2. 同じ親キーワードの記事（次点）──
    same_parent_pool = [
        a for a in published_articles
        if a["id"] not in selected_ids
        and parent
        and parent in unescape(a["title"]).lower()
    ]

    if same_parent_pool:
        same_parent_selected = _claude_select(
            keyword, article_title, same_parent_pool, remaining,
            label=f"同親KW「{parent}」"
        )
        for a in same_parent_selected:
            if a["id"] not in selected_ids and len(selected) < max_count:
                selected.append(a)
                selected_ids.add(a["id"])

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected

    # ── 3. その他の関連記事（補完）──
    others_pool = [
        a for a in published_articles
        if a["id"] not in selected_ids
    ]

    if others_pool:
        others_selected = _claude_select(
            keyword, article_title, others_pool, remaining,
            label="その他補完"
        )
        for a in others_selected:
            if a["id"] not in selected_ids and len(selected) < max_count:
                selected.append(a)
                selected_ids.add(a["id"])

    print(f"[internal_linker] 内部リンク選定完了: 計{len(selected)}件 "
          f"(ASP:{asp_count} / 同親KW:{len(selected)-asp_count-(max_count-remaining-asp_count)} / その他:{max_count-remaining-asp_count if remaining < max_count else 0})")

    return selected[:max_count]


# ─────────────────────────────────────────────
# H3セクション末尾の挿入位置特定
# ─────────────────────────────────────────────

def _find_h3_section_ends(content: str) -> list[int]:
    """
    まとめを除く各H3セクションの末尾位置（次の見出しブロック直前）を返す。
    """
    all_heading_starts = [
        m.start() for m in re.finditer(r'<!-- wp:heading', content)
    ]

    h3_pattern = re.compile(
        r'<!-- wp:heading \{"level":3\} -->\s*<h3[^>]*>(.*?)</h3>\s*<!-- /wp:heading -->',
        re.DOTALL,
    )

    section_ends: list[int] = []
    for m in h3_pattern.finditer(content):
        h3_title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if "まとめ" in h3_title:
            continue

        h3_block_end = m.end()
        next_heading  = next(
            (hs for hs in all_heading_starts if hs > h3_block_end),
            None,
        )
        if next_heading is not None:
            section_ends.append(next_heading)

    return section_ends


# ─────────────────────────────────────────────
# コンテンツへの挿入
# ─────────────────────────────────────────────

def inject_internal_links(
    content: str,
    related_articles: list[dict],
) -> str:
    """
    H3セクション末尾に内部リンクを分散挿入する。

    - H3スロット数 ≥ リンク数: 各H3に1件ずつ均等配置
    - H3スロット数 < リンク数: H3に1件ずつ配置、余剰はまとめH3直前に追加
    - H3スロットが0件: 全件をまとめH3直前（なければコンテンツ末尾）に追加
    """
    if not related_articles:
        return content

    section_ends = _find_h3_section_ends(content)
    n_slots  = len(section_ends)

    slot_links  = related_articles[:n_slots]
    extra_links = related_articles[n_slots:]

    # 余剰リンク → テキストリンクでまとめH3直前 or 末尾
    if extra_links:
        extra_blocks = "".join(_text_link_block(a) for a in extra_links)
        matome_pat = re.compile(
            r'<!-- wp:heading \{"level":3\} -->\s*<h3[^>]*>[^<]*まとめ[^<]*</h3>\s*<!-- /wp:heading -->',
            re.DOTALL,
        )
        m = matome_pat.search(content)
        if m:
            content = content[:m.start()] + extra_blocks + "\n" + content[m.start():]
        else:
            content = content.rstrip() + "\n" + extra_blocks

    # H3スロット → SWELLカードを後ろから挿入
    for i in range(len(slot_links) - 1, -1, -1):
        insert_pos = section_ends[i]
        block      = _card_block(slot_links[i])
        content    = content[:insert_pos] + block + "\n" + content[insert_pos:]

    return content
