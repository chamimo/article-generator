"""
キーワードから最適なWordPress子カテゴリIDをルールベースで選択する。

カテゴリ階層:
  転職・就職         → 転職エージェント / 履歴書・職務経歴書 / 面接・選考
  派遣・パート       → 派遣法・制度 / 派遣会社選び / パート・アルバイト
  副業・フリーランス → クラウドソーシング / 物販・EC / SNS運用
  キャリア・スキルアップ → WEB制作・デザイン / ITスキル / 資格・勉強
  職場・人間関係     → ストレス・メンタル / 労働・法律 / お金・給与

スコアリング:
  カテゴリ名を語単位に分割し、keyword + article_title との一致長を合算。
  CJK文字は2文字以上、ASCII語は3文字以上でマッチ。
  エイリアスマップでカテゴリ名に直接現れないキーワードを補完（+10点）。
  親カテゴリ（子を持つカテゴリ）は選択から除外し、必ず子カテゴリを選択する。
"""
import re
import requests
from modules import wp_context

# 常に除外するID（未分類 + AIVICE残留ID）
_ALWAYS_EXCLUDE: set[int] = {1, 1405, 1408}

# キャッシュ: 全カテゴリリスト
_category_cache: list[dict] | None = None


def fetch_categories() -> list[dict]:
    """WordPress REST APIから全カテゴリを取得してキャッシュする。"""
    global _category_cache
    if _category_cache is not None:
        return _category_cache

    r = requests.get(
        f"{wp_context.get_wp_url()}/wp-json/wp/v2/categories?per_page=100",
        auth=wp_context.get_auth(),
        timeout=10,
    )
    r.raise_for_status()
    _category_cache = [
        {"id": c["id"], "name": c["name"], "parent": c["parent"]}
        for c in r.json()
    ]
    print(f"[category_selector] カテゴリ取得: {len(_category_cache)}件")
    return _category_cache


def _get_child_categories() -> list[dict]:
    """
    子カテゴリ（leaf）のみ返す。
    親カテゴリ（他カテゴリの parent として参照されているもの）は除外。
    常時除外IDも除く。
    """
    all_cats = fetch_categories()
    parent_ids = {c["parent"] for c in all_cats if c["parent"] != 0}
    return [
        c for c in all_cats
        if c["id"] not in _ALWAYS_EXCLUDE and c["id"] not in parent_ids
    ]


# ─── CJK最小マッチ長 ───────────────────────────────
_CJK_RE = re.compile(r'[\u3000-\u9fff\uf900-\ufaff]')


def _min_len(term: str) -> int:
    """CJK文字を含む語は2文字以上、ASCII語は3文字以上でマッチ。"""
    return 2 if _CJK_RE.search(term) else 3


# ─── キーワードエイリアス（子カテゴリ名の断片にマップ）──────────────
# キー: キーワード中に現れる語
# 値:   子カテゴリ名に含まれる断片（部分一致）
_KEYWORD_ALIASES: dict[str, str] = {
    # 転職・就職 系
    "転職":     "転職",
    "就職":     "転職",
    "内定":     "転職",
    "求人":     "転職",
    "エージェント": "転職エージェント",
    "リクルート":   "転職エージェント",
    "doda":         "転職エージェント",
    "マイナビ":     "転職エージェント",
    "リクナビ":     "転職エージェント",
    "履歴書":       "履歴書",
    "職務経歴":     "履歴書",
    "志望動機":     "履歴書",
    "自己PR":       "履歴書",
    "面接":         "面接",
    "選考":         "面接",
    "ES":           "面接",
    "グループディスカッション": "面接",
    # 派遣・パート 系
    "派遣":         "派遣",
    "3年ルール":    "派遣法",
    "派遣法":       "派遣法",
    "派遣会社":     "派遣会社",
    "パート":       "パート",
    "アルバイト":   "パート",
    "バイト":       "パート",
    # 副業・フリーランス 系（子カテゴリ名に「副業」がないためデフォルトはクラウドソーシング）
    "副業":         "クラウドソーシング",
    "フリーランス": "クラウドソーシング",
    "クラウドソーシング": "クラウドソーシング",
    "ランサーズ":   "クラウドソーシング",
    "クラウドワークス": "クラウドソーシング",
    "物販":         "物販",
    "Amazon":       "物販",
    "メルカリ":     "物販",
    "せどり":       "物販",
    "SNS":          "SNS",
    "instagram":    "SNS",
    "tiktok":       "SNS",
    "x.com":        "SNS",
    "twitter":      "SNS",
    "インスタ":     "SNS",
    # キャリア・スキルアップ 系
    "スキル":       "スキル",
    "キャリア":     "スキル",
    "資格":         "資格",
    "勉強":         "資格",
    "検定":         "資格",
    "昇進":         "スキル",
    "マネジメント": "スキル",
    "WEB制作":      "WEB制作",
    "デザイン":     "WEB制作",
    "HTML":         "WEB制作",
    "CSS":          "WEB制作",
    "JavaScript":   "WEB制作",
    "Python":       "ITスキル",
    "プログラミング": "ITスキル",
    "IT":           "ITスキル",
    "エンジニア":   "ITスキル",
    "独学":         "ITスキル",
    "コーディング": "ITスキル",
    # 職場・人間関係 系
    "仕事":         "ストレス",
    "職場":         "ストレス",
    "残業":         "ストレス",
    "上司":         "ストレス",
    "同僚":         "ストレス",
    "部下":         "ストレス",
    "ハラスメント": "ストレス",
    "パワハラ":     "ストレス",
    "セクハラ":     "ストレス",
    "メンタル":     "ストレス",
    "うつ":         "ストレス",
    "辞め":         "ストレス",
    "退職":         "労働",
    "労働":         "労働",
    "解雇":         "労働",
    "有給":         "労働",
    "休業":         "労働",
    "給与":         "給与",
    "年収":         "給与",
    "収入":         "給与",
    "給料":         "給与",
    "ボーナス":     "給与",
    "手取り":       "給与",
    "在宅":         "SNS",
    "リモート":     "スキル",
}


def _score(keyword: str, article_title: str, category_name: str) -> int:
    """
    キーワード + 記事タイトルとカテゴリ名の一致スコアを返す。

    方向1: カテゴリ名の語がテキストに含まれる → len*2点
    方向2: テキストの語がカテゴリ名に含まれる → len点
    エイリアスボーナス: エイリアス一致 → +10点
    """
    text = f"{keyword} {article_title}".lower()
    cat  = category_name.lower()

    score = 0
    # 方向1: カテゴリ側の語がテキストに含まれる
    for term in re.split(r'[・/（）()\s　]+', cat):
        if len(term) >= _min_len(term) and term in text:
            score += len(term) * 2
    # 方向2: テキスト側の語がカテゴリ名に含まれる
    for word in re.split(r'[\s\u3000]+', text):
        if len(word) >= _min_len(word) and word in cat:
            score += len(word)
    # エイリアスボーナス（キー長 × 5点：具体的な長いキーほど高得点）
    # 例: "副業"(2字)→10点, "メルカリ"(4字)→20点, "クラウドワークス"(8字)→40点
    for alias, target_fragment in _KEYWORD_ALIASES.items():
        if alias.lower() in text and target_fragment.lower() in cat:
            score += len(alias) * 5

    return score


def select_category(keyword: str, article_title: str = "") -> int:
    """
    キーワードと記事タイトルから最適な子カテゴリIDを返す。
    親カテゴリは選択対象から除外し、必ず末端の子カテゴリを返す。

    Returns:
        WordPress カテゴリID（int）
    """
    children = _get_child_categories()
    if not children:
        # フォールバック: 全カテゴリから除外IDだけ省いて選択
        all_cats = fetch_categories()
        children = [c for c in all_cats if c["id"] not in _ALWAYS_EXCLUDE]

    scored = sorted(
        children,
        key=lambda c: _score(keyword, article_title, c["name"]),
        reverse=True,
    )

    best = scored[0]
    best_score = _score(keyword, article_title, best["name"])

    if best_score == 0:
        # スコアゼロ → 「ストレス・メンタル」にフォールバック
        fallback = next(
            (c for c in children if "ストレス" in c["name"] or "メンタル" in c["name"]),
            children[0],
        )
        print(f"[category_selector] 「{keyword}」→ マッチなし、フォールバック: {fallback['name']}({fallback['id']})")
        return fallback["id"]

    print(f"[category_selector] 「{keyword}」→ {best['name']}({best['id']}) score={best_score}")
    return best["id"]
