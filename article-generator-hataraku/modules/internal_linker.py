"""
内部リンク自動挿入モジュール

## 選定優先順位
1. ASP成約記事（URL一致）: 言及があれば必ず1本
2. ASP名を含む関連記事（タイトルマッチ）
3. 同じ親キーワードの記事（Jaccard bigram スコアリング）
4. 親KW絞り込み済みその他関連記事（Jaccard bigram スコアリング）

## 挿入方針
1. H3セクション本文に製品名が出ている → その製品の記事を優先割り当て（誘導文あり・新タブ）
2. 製品名マッチなし → 空きスロットに順番割り当て
3. H3スロットに入らなかった分 → 記事末尾「✅ 次に読むならこちら」に追加（新タブ）
4. 合計5件以上になるように調整する
"""
from __future__ import annotations

import json
import re
import requests
from datetime import datetime, timezone, timedelta
from html import unescape
from requests.auth import HTTPBasicAuth

from config import CTA_CONFIG
from modules import wp_context
from modules.keyword_utils import detect_parent_keyword

# セッション内キャッシュ（プロセス再起動でリセット）
_published_articles_cache: list[dict] | None = None


# ─────────────────────────────────────────────
# ブロック生成
# ─────────────────────────────────────────────

def _card_block(article: dict) -> str:
    """wp:loos/post-link ブロックを生成する。新しいタブで開く設定つき。"""
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
    return f'\n<!-- wp:loos/post-link {{"linkData":{link_data},"icon":"link","openInNewTab":true}} /-->'


def _lead_in_block(text: str) -> str:
    """誘導文の wp:paragraph ブロックを生成する。"""
    return (
        "\n<!-- wp:paragraph -->\n"
        f"<p>{text}</p>\n"
        "<!-- /wp:paragraph -->"
    )


def _footer_links_block(articles: list[dict]) -> str:
    """記事末尾の「✅ 次に読むならこちら」セクションを生成する。誘導文なし・カードブロック形式。"""
    cards = "\n".join(_card_block(a) for a in articles)
    return (
        '\n<!-- wp:heading {"level":3} -->\n'
        '<h3>✅ 次に読むならこちら</h3>\n'
        '<!-- /wp:heading -->'
        + cards
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
    auth = wp_context.get_auth()

    while True:
        resp = requests.get(
            f"{wp_context.get_wp_url()}/wp-json/wp/v2/posts",
            auth=auth,
            params={
                "per_page": 100,
                "page": page,
                "status": "publish",
                "_fields": "id,title,slug,link,date",
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
                "date":  p.get("date", ""),
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
    max_count: int = 8,
    asp_links: dict | None = None,
    article_content: str = "",
    stop_words: list[str] | None = None,
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

    # ── 事前処理: 2年以上前の記事を除外（古いトレンドネタを内部リンクに使わない）──
    cutoff = datetime.now(timezone.utc) - timedelta(days=730)
    fresh_articles = []
    excluded_old = 0
    for a in published_articles:
        raw_date = a.get("date", "")
        if raw_date:
            try:
                pub = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    excluded_old += 1
                    continue
            except ValueError:
                pass
        fresh_articles.append(a)
    if excluded_old:
        print(f"[internal_linker] 古い記事を除外: {excluded_old}件（2年以上前）→ {len(fresh_articles)}件で選定")
    published_articles = fresh_articles

    # ── 事前処理: 同タイトル記事を高ID優先で1件に絞り込む ───────────
    # WPに同じタイトルの記事が複数存在する場合、IDが大きい（新しい）方を残す
    _title_to_best: dict[str, dict] = {}
    for a in published_articles:
        t = unescape(a["title"]).strip()
        if t not in _title_to_best or a["id"] > _title_to_best[t]["id"]:
            _title_to_best[t] = a
    if len(_title_to_best) < len(published_articles):
        deduped_count = len(published_articles) - len(_title_to_best)
        print(f"[internal_linker] タイトル重複除去: {deduped_count}件の旧記事を除外")
    published_articles = list(_title_to_best.values())

    parent = detect_parent_keyword(keyword)
    text_to_check = f"{keyword} {article_title} {article_content}".lower()

    # 自記事と同一または類似しすぎる記事を事前除外
    # （完全一致 + Jaccard bigram >= 0.40）
    self_similar_ids: set[int] = set()
    for a in published_articles:
        t = unescape(a["title"])
        if t == article_title:
            self_similar_ids.add(a["id"])
        elif article_title and _jaccard(article_title, t) >= 0.40:
            self_similar_ids.add(a["id"])
            print(f"[internal_linker] 類似タイトル除外: 「{t[:40]}」")

    selected:       list[dict] = []
    selected_ids:   set[int]   = set()
    selected_urls:  set[str]   = set()
    selected_titles: set[str]  = set()
    asp_links       = asp_links or {}

    def _can_add(a: dict) -> bool:
        """ID・URL・タイトルのいずれかで重複していなければ True。"""
        if a["id"] in selected_ids:
            return False
        url_norm = a.get("link", "").rstrip("/")
        if url_norm and url_norm in selected_urls:
            print(f"[internal_linker] URL重複スキップ: 「{unescape(a['title'])[:40]}」")
            return False
        t_norm = unescape(a["title"]).strip()
        if t_norm and t_norm in selected_titles:
            print(f"[internal_linker] タイトル重複スキップ: 「{t_norm[:40]}」")
            return False
        return True

    def _add(a: dict) -> None:
        selected.append(a)
        selected_ids.add(a["id"])
        url_norm = a.get("link", "").rstrip("/")
        if url_norm:
            selected_urls.add(url_norm)
        t_norm = unescape(a["title"]).strip()
        if t_norm:
            selected_titles.add(t_norm)

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
            if not _can_add(a):
                continue
            if a["id"] in self_similar_ids:
                continue
            if a.get("link", "").rstrip("/") == review_url_norm:
                _add({**a, "_link_type": "asp_conversion", "_product_name": product_name})
                conv_count += 1
                print(f"[internal_linker] 成約記事「{product_name}」→ {a['title'][:40]}")
                break

    # ── 優先2: ASP案件名を含む関連記事（タイトルマッチ）──────────
    kw_match_count = 0
    for product_name, _ in mentioned_products:
        pname_lower = product_name.lower()
        kw_pool = [
            a for a in published_articles
            if _can_add(a)
            and a["id"] not in self_similar_ids
            and pname_lower in unescape(a["title"]).lower()
        ]
        for a in kw_pool[:2]:          # 1案件あたり最大2件
            if len(selected) >= max_count:
                break
            _add({**a, "_link_type": "asp_related", "_product_name": product_name})
            kw_match_count += 1
        if kw_match_count:
            print(f"[internal_linker] 「{product_name}」関連記事: {kw_match_count}件追加")

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected[:max_count]

    # ── 優先3: 同じ親キーワードの記事（Claude選定）──────────────
    same_parent_pool = [
        a for a in published_articles
        if _can_add(a)
        and a["id"] not in self_similar_ids
        and parent
        and parent in unescape(a["title"]).lower()
    ]
    if same_parent_pool:
        for a in _rule_select(keyword, article_title, same_parent_pool, remaining,
                                label=f"同親KW「{parent}」"):
            if _can_add(a) and len(selected) < max_count:
                _add({**a, "_link_type": "same_parent"})

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected[:max_count]

    # ── 優先4: キーワードトークンマッチング（親KWより広い範囲）────
    # ストップワード除去後の3字以上のトークンがタイトルに含まれる記事を対象にする。
    # 完全に無関係な記事は弾きつつ、同テーマ周辺の記事を拾う。
    _sw_lower = [s.lower() for s in (stop_words or [])]
    kw_tokens = [
        t for t in re.split(r'[\s　]+', keyword.lower())
        if len(t) >= 3 and t not in _sw_lower
    ]
    if kw_tokens:
        token_pool = [
            a for a in published_articles
            if _can_add(a)
            and a["id"] not in self_similar_ids
            and any(t in unescape(a["title"]).lower() for t in kw_tokens)
        ]
        if token_pool:
            for a in _rule_select(keyword, article_title, token_pool, remaining,
                                    label="キーワードトークンマッチ"):
                if _can_add(a) and len(selected) < max_count:
                    _add({**a, "_link_type": "keyword_token"})

    remaining = max_count - len(selected)
    if remaining <= 0:
        return selected[:max_count]

    # ── 優先5: 親KW分割トークン補完 ──────────────────────────────
    parent_terms = [t for t in re.split(r'[\s・]+', parent or "") if len(t) >= 2]
    if parent_terms:
        others_pool = [
            a for a in published_articles
            if _can_add(a)
            and a["id"] not in self_similar_ids
            and any(t in unescape(a["title"]).lower() for t in parent_terms)
        ]
        if others_pool:
            for a in _rule_select(keyword, article_title, others_pool, remaining,
                                    label="関連補完（親KW絞り込み）"):
                if _can_add(a) and len(selected) < max_count:
                    _add({**a, "_link_type": "related"})

    # ── 後処理: キーワード製品リンク確保 ────────────────────────
    # 優先1〜4で親KW（製品名）に関連する記事が選ばれなかった場合に強制追加する。
    # 製品名が3文字以上のとき有効（ai など短い汎用語は対象外）。
    if parent and len(parent.replace(" ", "")) >= 3:
        has_product_link = any(
            parent in unescape(a["title"]).lower()
            for a in selected
        )
        if not has_product_link:
            product_pool = [
                a for a in published_articles
                if _can_add(a)
                and a["id"] not in self_similar_ids
                and parent in unescape(a["title"]).lower()
            ]
            if product_pool:
                scored = sorted(
                    product_pool,
                    key=lambda a: _jaccard(f"{keyword} {article_title}", unescape(a["title"])),
                    reverse=True,
                )
                best = scored[0]
                _add({**best, "_link_type": "keyword_product"})
                print(
                    f"[internal_linker] キーワード製品リンク確保: "
                    f"「{parent}」→ 「{best['title'][:40]}」"
                )

    print(
        f"[internal_linker] 内部リンク選定完了: 計{len(selected)}件 "
        f"(成約:{conv_count} / 案件関連:{kw_match_count} "
        f"/ 同親KW+補完:{len(selected) - conv_count - kw_match_count})"
    )
    return selected[:max_count + 1] if len(selected) > max_count else selected


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
# H3セクション情報の取得
# ─────────────────────────────────────────────

def _find_h3_sections(content: str) -> list[dict]:
    """
    まとめを除く各H3セクションの情報を返す。

    Returns:
        各要素: {"end": int（挿入位置）, "text": str（見出し+本文のプレーンテキスト・小文字）}
    """
    all_heading_starts = [
        m.start() for m in re.finditer(r'<!-- wp:heading', content)
    ]

    h3_pattern = re.compile(
        r'<!-- wp:heading \{"level":3\} -->\s*<h3[^>]*>(.*?)</h3>\s*<!-- /wp:heading -->',
        re.DOTALL,
    )

    sections: list[dict] = []
    for m in h3_pattern.finditer(content):
        h3_title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if "まとめ" in h3_title:
            continue

        h3_block_end = m.end()
        next_heading = next(
            (hs for hs in all_heading_starts if hs > h3_block_end),
            None,
        )
        if next_heading is not None:
            body_raw  = re.sub(r'<[^>]+>', '', content[h3_block_end:next_heading])
            title_low = h3_title.lower()
            body_low  = body_raw.lower()
            sections.append({
                "end":        next_heading,
                "title_text": title_low,               # タイトルのみ（重み付け用）
                "body_text":  body_low,                # 本文のみ（重み付け用）
                "text":       title_low + " " + body_low,  # 後方互換
            })

    return sections


def _dominant_product(section: dict, product_names: list[str]) -> str | None:
    """
    セクション内で最も言及されている製品名を返す。
    タイトル出現は本文の3倍の重みを持つ（タイトルにある製品が支配的とみなす）。
    スコアが同点の場合は先に並んでいる製品を優先（優先度順で渡すこと）。
    いずれの製品も出現しない場合は None。
    """
    title_text = section.get("title_text", "")
    body_text  = section.get("body_text", "")

    best_name:  str | None = None
    best_score: float      = 0.0

    for name in product_names:
        pname       = name.lower()
        title_score = title_text.count(pname) * 3
        body_score  = body_text.count(pname)
        score       = title_score + body_score
        if score > best_score:
            best_score = score
            best_name  = name

    return best_name


def _assign_links_to_sections(
    related_articles: list[dict],
    sections: list[dict],
) -> tuple[list[tuple[int, dict]], list[dict]]:
    """
    製品名マッチングで各リンクを最適なH3セクションに割り当てる。

    Pass1: _product_name を持つ記事 → その製品名がセクション本文に出るスロットに優先割り当て
    Pass2: 残りを空きスロットに順番割り当て
    スロット不足分は footer_links として返す。

    Returns:
        assignments: [(insert_pos, article), ...] セクション順
        footer_links: 割り当てられなかった記事リスト
    """
    from collections import deque

    n_slots = len(sections)
    if n_slots == 0:
        return [], list(related_articles)

    slot_assignment: list[dict | None] = [None] * n_slots
    assigned_ids: set[int] = set()

    product_articles = [a for a in related_articles if a.get("_product_name")]
    generic_articles = [a for a in related_articles if not a.get("_product_name")]

    # 製品ごとに優先度順（asp_conversion > asp_related > その他）の deque を作成
    _TYPE_PRI = {"asp_conversion": 0, "asp_related": 1}
    product_names = list({a["_product_name"] for a in product_articles})
    product_deques: dict[str, deque] = {p: deque() for p in product_names}
    for a in product_articles:
        product_deques[a["_product_name"]].append(a)
    for p in product_names:
        product_deques[p] = deque(
            sorted(product_deques[p],
                   key=lambda a: _TYPE_PRI.get(a.get("_link_type", ""), 99))
        )

    # Pass1: セクションの支配的製品と一致する記事のみ割り当てる
    # 製品支配セクションに無関係な製品・汎用記事は絶対に入れない
    for i, section in enumerate(sections):
        dom = _dominant_product(section, product_names)
        if dom is None or not product_deques[dom]:
            continue
        article = product_deques[dom].popleft()
        slot_assignment[i] = article
        assigned_ids.add(article["id"])
        print(
            f"[internal_linker] 製品名マッチ「{dom}」"
            f"→ セクション{i+1}に割り当て"
        )

    # Pass2: 製品が支配しないセクションにのみ汎用記事を割り当て
    generic_deque: deque = deque(generic_articles)
    for i, section in enumerate(sections):
        if slot_assignment[i] is not None:
            continue
        # 製品支配セクションで記事が枯渇した場合は空スロットのまま（無関係記事は入れない）
        if _dominant_product(section, product_names) is not None:
            continue
        while generic_deque:
            candidate = generic_deque.popleft()
            if candidate["id"] not in assigned_ids:
                slot_assignment[i] = candidate
                assigned_ids.add(candidate["id"])
                break

    # 未割り当て記事 → footer（製品記事も汎用記事も含む）
    footer_links = [a for a in related_articles if a["id"] not in assigned_ids]

    assignments = [
        (sections[i]["end"], slot_assignment[i])
        for i in range(n_slots)
        if slot_assignment[i] is not None
    ]
    return assignments, footer_links


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
    内部リンクを挿入する。

    方針:
    1. H3セクション本文に製品名が出ていればその製品の記事を優先割り当て（誘導文あり・新タブ）
    2. 製品名マッチなしは空きスロットに順番割り当て
    3. H3スロット不足分は記事末尾「✅ 次に読むならこちら」に追加（新タブ）
    4. 合計5件以上になるように調整する
    """
    if not related_articles:
        return content

    TARGET_COUNT = 5
    sections = _find_h3_sections(content)

    # 製品名マッチングでH3スロットに割り当て
    assignments, footer_links = _assign_links_to_sections(related_articles, sections)

    # 後ろから挿入（位置ずれ防止）・誘導文なし、カードのみ
    for i in range(len(assignments) - 1, -1, -1):
        insert_pos, article = assignments[i]
        card = _card_block(article)
        content = content[:insert_pos] + card + "\n" + content[insert_pos:]

    body_count = len(assignments)

    # 末尾リスト「✅ 次に読むならこちら」（H3スロット不足分）
    if footer_links:
        content = content.rstrip() + "\n" + _footer_links_block(footer_links)
        print(f"[internal_linker] 末尾リスト「✅ 次に読むならこちら」: {len(footer_links)}件追加")

    total = body_count + len(footer_links)
    if total < TARGET_COUNT:
        print(f"[internal_linker] 注意: 内部リンク{total}件（目標{TARGET_COUNT}件未達）")

    print(
        f"[internal_linker] 内部リンク挿入完了: 計{total}件 "
        f"(本文H3:{body_count} / 末尾リスト:{len(footer_links)})"
    )
    return content
