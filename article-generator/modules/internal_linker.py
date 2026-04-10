"""
内部リンク自動挿入モジュール

## 選定優先順位
1. ASP成約記事（URL一致）: 言及があれば必ず1本
2. ASP名を含む関連記事（タイトルマッチ）
3. 同じ親キーワードの記事（Jaccard bigram スコアリング）
4. 親KW絞り込み済みその他関連記事（Jaccard bigram スコアリング）

## 挿入位置
- H3セクション末尾に SWELL「あわせて読みたい」カード形式で分散挿入
- H3スロットが足りない場合はテキストリンクでまとめH3直前 or 末尾に補完
"""
from __future__ import annotations

import json
import re
import requests
from html import unescape
from requests.auth import HTTPBasicAuth

from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, CTA_CONFIG
from modules.keyword_utils import detect_parent_keyword

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


def _lead_in_block(text: str) -> str:
    """誘導文の wp:paragraph ブロックを生成する。"""
    return (
        "\n<!-- wp:paragraph -->\n"
        f"<p>{text}</p>\n"
        "<!-- /wp:paragraph -->"
    )


def _text_link_block(article: dict, lead_in: str = "") -> str:
    """テキストリンクの wp:paragraph ブロックを生成する。誘導文があれば文中に組み込む。"""
    title_plain = unescape(article["title"])
    prefix = lead_in if lead_in else "こちらの記事もおすすめです。"
    return (
        "\n<!-- wp:paragraph -->\n"
        f'<p>{prefix}→ <a href="{article["link"]}">{title_plain}</a></p>\n'
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
# ルールベース関連記事選定（Jaccard bigram スコアリング）
# ─────────────────────────────────────────────

def _bigrams(s: str) -> set[str]:
    """文字バイグラムセットを返す（小文字・記号除去後）。"""
    s = re.sub(r'[^\w\u3040-\u9fff]', ' ', s.lower()).strip()
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else set(s)


def _jaccard(a: str, b: str) -> float:
    bg_a = _bigrams(a)
    bg_b = _bigrams(b)
    if not bg_a and not bg_b:
        return 1.0
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


def _rule_select(
    keyword: str,
    article_title: str,
    candidates: list[dict],
    max_count: int,
    label: str = "",
) -> list[dict]:
    """
    Jaccard bigram スコアリングで candidates から関連記事を最大 max_count 件選ぶ。
    API不使用のルールベース実装。
    """
    if not candidates or max_count <= 0:
        return []

    query = f"{keyword} {article_title}"
    scored = sorted(
        candidates,
        key=lambda a: _jaccard(query, unescape(a["title"])),
        reverse=True,
    )
    selected = scored[:max_count]
    if label:
        print(f"[internal_linker] {label}: {len(selected)}件選定（ルールベース）")
    return selected


# ─────────────────────────────────────────────
# メイン選定ロジック（3段階優先順位）
# ─────────────────────────────────────────────

def select_related_articles(
    keyword: str,
    article_title: str,
    published_articles: list[dict],
    max_count: int = 5,
    asp_links: dict | None = None,
    article_content: str = "",
) -> list[dict]:
    """
    公開済み記事から内部リンク候補を優先順位に従って選ぶ。

    優先順位（全ASP案件共通）:
      1. 成約記事（asp_links のURLと一致する記事）        ← 言及があれば必ず1本
      2. ASP案件名を含む関連記事（タイトルにプロダクト名）
      3. 同じ親キーワードの記事（Claude選定）
      4. 親KW絞り込み済みのその他関連記事（Claude選定）

    Returns:
        最大 max_count 件のリスト（優先順位順）
    """
    if not published_articles:
        return []

    parent = detect_parent_keyword(keyword)
    text_to_check = f"{keyword} {article_title} {article_content}".lower()

    selected:     list[dict] = []
    selected_ids: set[int]   = set()
    asp_links     = asp_links or {}

    # 記事内で言及されているASP案件を検出
    mentioned_products = [
        (name, url) for name, url in asp_links.items()
        if name.lower() in text_to_check
    ]

    # ── 優先1: 成約記事（asp_links URL一致）──────────────────────
    # 言及があれば必ず1本以上リンクを確保する
    conv_count = 0
    for product_name, review_url in mentioned_products:
        review_url_norm = review_url.rstrip("/")
        for a in published_articles:
            if a["id"] in selected_ids:
                continue
            if unescape(a["title"]) == article_title:
                continue
            if a.get("link", "").rstrip("/") == review_url_norm:
                selected.append({**a, "_link_type": "asp_conversion"})
                selected_ids.add(a["id"])
                conv_count += 1
                print(f"[internal_linker] 成約記事「{product_name}」→ {a['title'][:40]}")
                break

    # ── 優先2: ASP案件名を含む関連記事（タイトルマッチ）──────────
    kw_match_count = 0
    for product_name, _ in mentioned_products:
        pname_lower = product_name.lower()
        kw_pool = [
            a for a in published_articles
            if a["id"] not in selected_ids
            and unescape(a["title"]) != article_title
            and pname_lower in unescape(a["title"]).lower()
        ]
        for a in kw_pool[:2]:          # 1案件あたり最大2件
            if len(selected) >= max_count:
                break
            selected.append({**a, "_link_type": "asp_related"})
            selected_ids.add(a["id"])
            kw_match_count += 1
        if kw_match_count:
            print(f"[internal_linker] 「{product_name}」関連記事: {kw_match_count}件追加")

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected[:max_count]

    # ── 優先3: 同じ親キーワードの記事（Claude選定）──────────────
    same_parent_pool = [
        a for a in published_articles
        if a["id"] not in selected_ids
        and parent
        and parent in unescape(a["title"]).lower()
    ]
    if same_parent_pool:
        for a in _rule_select(keyword, article_title, same_parent_pool, remaining,
                                label=f"同親KW「{parent}」"):
            if a["id"] not in selected_ids and len(selected) < max_count:
                selected.append({**a, "_link_type": "same_parent"})
                selected_ids.add(a["id"])

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected[:max_count]

    # ── 優先4: 親KW絞り込み済みその他関連記事（Claude選定）────────
    parent_terms = [t for t in re.split(r'[\s・]+', parent or "") if len(t) >= 2]
    if parent_terms:
        others_pool = [
            a for a in published_articles
            if a["id"] not in selected_ids
            and any(t in unescape(a["title"]).lower() for t in parent_terms)
        ]
        if others_pool:
            for a in _rule_select(keyword, article_title, others_pool, remaining,
                                    label="関連補完（親KW絞り込み）"):
                if a["id"] not in selected_ids and len(selected) < max_count:
                    selected.append({**a, "_link_type": "related"})
                    selected_ids.add(a["id"])

    print(
        f"[internal_linker] 内部リンク選定完了: 計{len(selected)}件 "
        f"(成約:{conv_count} / 案件関連:{kw_match_count} "
        f"/ 同親KW+補完:{len(selected) - conv_count - kw_match_count})"
    )
    return selected[:max_count]


# ─────────────────────────────────────────────
# 誘導文の一括生成
# ─────────────────────────────────────────────

_FALLBACKS_ASP = [
    "実際の価格や詳しい情報はこちらで解説しています。",
    "導入を検討している方はこちらも参考にしてください。",
    "購入前に確認しておきたいポイントをまとめています。",
    "詳細なスペックや購入方法はこちらをご覧ください。",
]
_FALLBACKS_REL = [
    "この点についてはこちらの記事で詳しく解説しています。",
    "合わせて読むとより理解が深まります。",
    "関連する内容はこちらの記事もご覧ください。",
    "さらに詳しく知りたい方はこちらも参考にどうぞ。",
    "気になる方はこちらの記事もチェックしてみてください。",
]


def _generate_lead_ins(
    main_keyword: str,
    main_title: str,
    articles: list[dict],
) -> list[str]:
    """
    内部リンク挿入前の誘導文を定型文プールからローテーション生成する（API不使用）。
    リンクタイプ別に異なるプールを使い、同じ文言が連続しないようインデックスをずらす。
    """
    if not articles:
        return []

    result  = []
    asp_idx = 0
    rel_idx = 0
    for a in articles:
        is_asp = a.get("_link_type") == "asp_conversion"
        if is_asp:
            result.append(_FALLBACKS_ASP[asp_idx % len(_FALLBACKS_ASP)])
            asp_idx += 1
        else:
            result.append(_FALLBACKS_REL[rel_idx % len(_FALLBACKS_REL)])
            rel_idx += 1
    return result


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
    keyword: str = "",
    article_title: str = "",
) -> str:
    """
    H3セクション末尾に内部リンクを分散挿入する。
    各リンクの直前にClaude生成の誘導文（wp:paragraph）を挿入する。

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

    # 誘導文を一括生成（slot + extra まとめて1回のAPI呼び出し）
    all_articles = slot_links + extra_links
    lead_ins     = _generate_lead_ins(keyword, article_title, all_articles)
    slot_lead_ins  = lead_ins[:len(slot_links)]
    extra_lead_ins = lead_ins[len(slot_links):]

    # 余剰リンク → 誘導文込みテキストリンクでまとめH3直前 or 末尾
    if extra_links:
        extra_blocks = "".join(
            _text_link_block(a, lead_in=li)
            for a, li in zip(extra_links, extra_lead_ins)
        )
        matome_pat = re.compile(
            r'<!-- wp:heading \{"level":3\} -->\s*<h3[^>]*>[^<]*まとめ[^<]*</h3>\s*<!-- /wp:heading -->',
            re.DOTALL,
        )
        m = matome_pat.search(content)
        if m:
            content = content[:m.start()] + extra_blocks + "\n" + content[m.start():]
        else:
            content = content.rstrip() + "\n" + extra_blocks

    # H3スロット → 誘導文 + SWELLカードを後ろから挿入
    for i in range(len(slot_links) - 1, -1, -1):
        insert_pos = section_ends[i]
        lead  = _lead_in_block(slot_lead_ins[i])
        card  = _card_block(slot_links[i])
        content = content[:insert_pos] + lead + card + "\n" + content[insert_pos:]

    return content
