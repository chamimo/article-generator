"""
7ブログのASP案件マスターからロングテールKWを生成し、キーワードシートに追記する。
"""
import sys, os
sys.path.insert(0, '/Users/yama/article-generator-hataraku')
from dotenv import load_dotenv
load_dotenv('/Users/yama/article-generator-hataraku/.env')

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
creds = Credentials.from_service_account_file(
    '/Users/yama/article-generator-hataraku/credentials.json',
    scopes=SCOPES
)
gc = gspread.authorize(creds)

# ブログ一覧
BLOGS = [
    {
        "name": "はた楽ナビ",
        "key": "hataraku",
        "ss_id": "1w0oAjA8JflYqHZP31XeF2RYZ_jxdznRl6D2e8387jLU",
        "genre": "就労支援・転職・副業・フリーランス",
    },
    {
        "name": "AIVice",
        "key": "workup-ai",
        "ss_id": "1_pgNf2-JNlT2uwJFGzlVPGpuVpj2mf5eSsa_YLwMwGc",
        "genre": "AIツール・自動化・副業・IT活用",
    },
    {
        "name": "ワイズトレンド",
        "key": "ys-trend",
        "ss_id": "1PPkCm-QEK-H9SSsAJiFksKhNl3IyDk495--xmChSGRM",
        "genre": "生活・エンタメ・副業・お金・IT",
    },
    {
        "name": "どこで売ってるナビ",
        "key": "kaerudoko",
        "ss_id": "16h7aV0iHC8dsQR05xMeKTqUvMSXb2lGcNfxr6P6lp8I",
        "genre": "商品・販売店・価格比較",
    },
    {
        "name": "気になることブログ",
        "key": "hapipo8",
        "ss_id": "1Mz5yztHfu8gnQ6JaPau47daK0Y4ykogTKNWyPtdDGrM",
        "genre": "コスメ・カフェ・雑貨・ライフスタイル",
    },
    {
        "name": "飛騨の思い出",
        "key": "hida-no-omoide",
        "ss_id": "16DZ0M_EbviPRhZBNwV_FpEJL2SjsuZw9BLKwAJE9AWE",
        "genre": "観光・風景・グルメ・体験",
    },
    {
        "name": "オンライン学習ナビ",
        "key": "web-study1",
        "ss_id": "1fyJCqT5Ohqb6OgY2w6LxAVydeuXuD6CdMweh1w1zMAM",
        "genre": "オンライン学習・教材・勉強法",
    },
]

ASP_SHEET_CANDIDATES = ["ASP案件マスター", "ASP案件マスター のコピー", "ASP案件マスター "]
KW_SHEET_NAME = "キーワード"

# AIVice 専用設定
AIVICE_ASP_SHEET = "ASP案件"  # シート名が異なる
AIVICE_KW_SHEET = "KW調査"   # キーワードシート名が異なる（D列がKW）


def fetch_asp_items(ss_id: str, blog_name: str, blog_key: str = "") -> list[dict]:
    """ASP案件マスターシートから案件リストを取得する。"""
    try:
        ss = gc.open_by_key(ss_id)
    except Exception as e:
        print(f"  [ERROR] スプレッドシート接続失敗: {e}")
        return []

    # AIVice は専用シート名・列構成
    if blog_key == "workup-ai":
        return _fetch_asp_aivice(ss)

    ws = None
    for sheet_name in ASP_SHEET_CANDIDATES:
        try:
            ws = ss.worksheet(sheet_name)
            print(f"  シート「{sheet_name}」を使用")
            break
        except Exception:
            continue

    if ws is None:
        print(f"  [WARN] ASP案件マスターシートが見つかりません")
        return []

    rows = ws.get_all_values()
    if len(rows) < 2:
        print(f"  [WARN] データがありません")
        return []

    items = []
    for row in rows[1:]:
        def cell(i): return row[i].strip() if i < len(row) else ""
        name = cell(0)
        priority = cell(2)
        url = cell(3)
        appeal = cell(4)
        if not name:
            continue
        items.append({
            "name": name,
            "priority": priority,
            "url": url,
            "appeal": appeal,
        })
    return items


def _fetch_asp_aivice(ss) -> list[dict]:
    """AIVice専用ASP案件取得（「ASP案件」シート、列構成が異なる）。
    ヘッダー: '', 案件名, ジャンル, 報酬, EPC, 確定率, おすすめ度, メインブログ, サブ訴求ブログ, AIViceでの訴求軸, ...
    """
    try:
        ws = ss.worksheet(AIVICE_ASP_SHEET)
        print(f"  シート「{AIVICE_ASP_SHEET}」を使用（AIVice専用）")
    except Exception as e:
        print(f"  [ERROR] AIVice ASP案件シート取得失敗: {e}")
        return []

    rows = ws.get_all_values()
    if len(rows) < 2:
        return []

    items = []
    for r in rows[1:]:
        if len(r) < 8:
            continue
        name = r[1].strip() if len(r) > 1 else ""
        priority = r[6].strip() if len(r) > 6 else ""
        main_blog = r[7].strip() if len(r) > 7 else ""
        sub_blog = r[8].strip() if len(r) > 8 else ""
        appeal = r[9].strip() if len(r) > 9 else ""

        if not name:
            continue
        # AIVice向け案件のみ（メインまたはサブ）
        if "AIVice" not in main_blog and "AIVice" not in sub_blog:
            continue

        items.append({
            "name": name,
            "priority": priority,
            "url": "",  # URLはアフィリURLシートに別途あるが今回はKW生成のみ
            "appeal": appeal,
        })
    return items


def fetch_existing_keywords(ss_id: str, blog_key: str = "") -> set[str]:
    """キーワードシートの既存KW（A列）を取得する。"""
    try:
        ss = gc.open_by_key(ss_id)
        # AIVice は KW調査シートのD列
        if blog_key == "workup-ai":
            return _fetch_existing_kw_aivice(ss)
        ws = ss.worksheet(KW_SHEET_NAME)
        rows = ws.get_all_values()
        existing = set()
        for row in rows[1:]:  # ヘッダー除外
            if row and row[0].strip():
                existing.add(row[0].strip())
        return existing
    except Exception as e:
        print(f"  [ERROR] キーワードシート読み込み失敗: {e}")
        return set()


def _fetch_existing_kw_aivice(ss) -> set[str]:
    """AIVice専用既存KW取得（KW調査シートのD列）。"""
    try:
        ws = ss.worksheet(AIVICE_KW_SHEET)
        rows = ws.get_all_values()
        existing = set()
        for row in rows[1:]:
            if len(row) > 3 and row[3].strip():
                existing.add(row[3].strip())
        return existing
    except Exception as e:
        print(f"  [ERROR] AIVice KW調査シート読み込み失敗: {e}")
        return set()


def generate_kw_hataraku(item: dict) -> list[str]:
    """はた楽ナビ用KW生成（就労支援・転職・副業）。"""
    name = item["name"]
    appeal = item["appeal"]
    kws = []

    # 案件名から基底キーワードを決定
    if any(w in name for w in ["就労移行", "就労支援"]):
        kws += [
            f"{name} おすすめ 比較",
            f"{name} 評判 口コミ 利用者",
            f"{name} 料金 無料",
            f"{name} 選び方 ポイント",
            f"{name} 発達障害 向き",
        ]
    elif any(w in name for w in ["転職", "エージェント", "求人"]):
        kws += [
            f"{name} 評判 口コミ",
            f"{name} おすすめ 使い方",
            f"{name} 登録 流れ 手順",
            f"{name} メリット デメリット",
            f"{name} 20代 30代 比較",
        ]
    elif any(w in name for w in ["副業", "フリーランス", "案件"]):
        kws += [
            f"{name} 始め方 初心者",
            f"{name} 稼げる 月収",
            f"{name} 評判 おすすめ",
            f"{name} 登録 手順",
            f"{name} 比較 メリット",
        ]
    elif any(w in name for w in ["クラウド", "ランサーズ", "ランサ"]):
        kws += [
            f"{name} 始め方 初心者",
            f"{name} 評判 口コミ",
            f"{name} 稼ぎ方 コツ",
            f"{name} 登録 手順",
        ]
    elif any(w in name for w in ["IT", "スキル", "プログラミング", "研修"]):
        kws += [
            f"{name} 料金 費用",
            f"{name} 評判 口コミ",
            f"{name} 内容 カリキュラム",
            f"{name} 就職 転職",
            f"{name} 無料 体験",
        ]
    else:
        # 汎用
        kws += [
            f"{name} 評判 口コミ",
            f"{name} 料金 比較",
            f"{name} おすすめ 使い方",
            f"{name} 登録 方法",
            f"{name} メリット デメリット",
        ]
    return kws


def generate_kw_workup_ai(item: dict) -> list[str]:
    """AIVice用KW生成（AIツール・自動化・副業）。"""
    name = item["name"]
    kws = []

    if any(w in name for w in ["ChatGPT", "GPT"]):
        kws += [
            f"ChatGPT 使い方 初心者",
            f"ChatGPT 仕事 効率化",
            f"ChatGPT プラグイン おすすめ",
            f"ChatGPT 無料 有料 違い",
            f"ChatGPT 副業 稼ぎ方",
        ]
    elif "Claude" in name:
        kws += [
            f"Claude AI 使い方 日本語",
            f"Claude ChatGPT 比較",
            f"Claude 料金 無料 プラン",
            f"Claude Pro 使い方 おすすめ",
        ]
    elif "Gemini" in name:
        kws += [
            f"Gemini AI 使い方",
            f"Gemini ChatGPT 比較 違い",
            f"Gemini 無料 機能",
            f"Gemini Advanced おすすめ",
        ]
    elif any(w in name for w in ["Midjourney", "画像生成", "Stable Diffusion", "DALL"]):
        kws += [
            f"Midjourney 使い方 日本語",
            f"画像生成AI おすすめ 比較",
            f"Midjourney 料金 プラン",
            f"AI画像生成 副業 稼ぎ方",
            f"Stable Diffusion 始め方",
        ]
    elif any(w in name for w in ["Notion", "自動化", "Zapier", "Make"]):
        kws += [
            f"{name} 使い方 初心者",
            f"{name} 自動化 設定",
            f"{name} 料金 無料 プラン",
            f"{name} テンプレート おすすめ",
        ]
    elif any(w in name for w in ["副業", "AI副業"]):
        kws += [
            f"AI 副業 稼ぎ方 初心者",
            f"AI 副業 おすすめ 月収",
            f"ChatGPT 副業 始め方",
            f"AI 自動化 副業 種類",
        ]
    else:
        kws += [
            f"{name} 使い方 初心者",
            f"{name} 料金 比較",
            f"{name} おすすめ 機能",
            f"{name} 評判 口コミ",
        ]
    return kws


# AIVice 追加KW（最新AIツール系）
WORKUP_AI_EXTRA_KW = [
    "Claude Sonnet 使い方 日本語",
    "Gemini 2.0 使い方 おすすめ",
    "Grok AI 使い方 日本語",
    "Perplexity AI 使い方 検索",
    "Suno AI 音楽生成 使い方",
    "Midjourney v6 使い方 日本語",
    "NotebookLM 使い方 要約",
    "Cursor AI コーディング 使い方",
    "Copilot 無料 使い方 初心者",
    "AI動画生成 おすすめ ツール 比較",
    "生成AI 副業 稼ぎ方 2024",
    "AI文章生成 ツール 無料 おすすめ",
    "Dify 使い方 日本語 チャットbot",
    "Claude API 使い方 料金",
    "Gemini Advanced 料金 使い方",
]


def generate_kw_ys_trend(item: dict) -> list[str]:
    """ワイズトレンド用KW生成（生活・エンタメ・副業・お金・IT）。"""
    name = item["name"]
    kws = []

    if any(w in name for w in ["副業", "稼ぐ", "在宅"]):
        kws += [
            f"{name} 始め方 初心者",
            f"{name} 評判 口コミ",
            f"{name} 稼げる 月収",
            f"{name} 無料 登録",
            f"{name} おすすめ 比較",
        ]
    elif any(w in name for w in ["投資", "株", "FX", "仮想通貨", "資産"]):
        kws += [
            f"{name} 始め方 初心者",
            f"{name} 評判 メリット デメリット",
            f"{name} 手数料 比較",
            f"{name} 無料 口座開設",
            f"{name} おすすめ 安全",
        ]
    elif any(w in name for w in ["動画", "配信", "YouTube", "TikTok"]):
        kws += [
            f"{name} 使い方 初心者",
            f"{name} 無料 機能",
            f"{name} おすすめ 比較",
            f"{name} 始め方",
        ]
    elif any(w in name for w in ["SIM", "格安", "スマホ", "通信"]):
        kws += [
            f"{name} 料金 比較",
            f"{name} おすすめ プラン",
            f"{name} 乗り換え 手順",
            f"{name} メリット デメリット",
            f"{name} 評判 口コミ",
        ]
    else:
        kws += [
            f"{name} 評判 口コミ",
            f"{name} 料金 比較",
            f"{name} おすすめ 使い方",
            f"{name} 始め方 初心者",
            f"{name} メリット デメリット",
        ]
    return kws


def generate_kw_kaerudoko(item: dict) -> list[str]:
    """どこで売ってるナビ用KW生成（どこで売ってる・販売店・通販）。"""
    name = item["name"]
    kws = [
        f"{name} どこで売ってる 販売店",
        f"{name} 通販 購入 方法",
        f"{name} 安い 最安値 比較",
        f"{name} どこで買える 店舗",
        f"{name} 在庫 確認",
    ]
    return kws


def generate_kw_kaerudoko_from_product(product: str) -> list[str]:
    """どこで売ってるナビ用KW生成（商品名ベース）。"""
    kws = [
        f"{product} どこで売ってる",
        f"{product} 販売店",
        f"{product} 通販",
        f"{product} コンビニ",
        f"{product} 売ってない",
    ]
    return kws


def generate_kw_hapipo8(item: dict) -> list[str]:
    """気になることブログ用KW生成（コスメ・カフェ・ライフスタイル）。"""
    name = item["name"]
    kws = []

    if any(w in name for w in ["コスメ", "美容", "スキン", "化粧", "コスメ", "クリーム", "美白", "保湿"]):
        kws += [
            f"{name} 口コミ 効果",
            f"{name} 使い方 おすすめ",
            f"{name} 比較 どれがいい",
            f"{name} 成分 安全",
            f"{name} 購入 通販",
        ]
    elif any(w in name for w in ["カフェ", "コーヒー", "紅茶", "飲み物"]):
        kws += [
            f"{name} おすすめ メニュー",
            f"{name} 口コミ 評判",
            f"{name} 値段 料金",
            f"{name} 近く 場所",
        ]
    elif any(w in name for w in ["雑貨", "インテリア", "グッズ", "アイテム"]):
        kws += [
            f"{name} おすすめ 口コミ",
            f"{name} 購入 通販",
            f"{name} 人気 ランキング",
            f"{name} 値段 比較",
        ]
    elif any(w in name for w in ["ダイエット", "痩せ", "健康", "エクサ"]):
        kws += [
            f"{name} 効果 口コミ",
            f"{name} 始め方 初心者",
            f"{name} おすすめ 比較",
            f"{name} やり方 方法",
            f"{name} 期間 結果",
        ]
    else:
        kws += [
            f"{name} 口コミ 評判",
            f"{name} おすすめ 使い方",
            f"{name} 比較 どれがいい",
            f"{name} 購入 値段",
            f"{name} 人気 ランキング",
        ]
    return kws


# 飛騨の思い出 用フォールバックKW（ASP案件がない場合）
HIDA_FALLBACK_KW = [
    "飛騨高山 観光 おすすめ スポット",
    "飛騨高山 旅行 モデルコース 1泊2日",
    "飛騨高山 グルメ おすすめ 食べ歩き",
    "飛騨高山 ホテル おすすめ じゃらん",
    "飛騨高山 旅館 口コミ 人気",
    "飛騨古川 観光 おすすめ",
    "高山祭 2024 日程 見どころ",
    "飛騨の里 見どころ アクセス",
    "飛騨高山 温泉 日帰り おすすめ",
    "飛騨高山 冬 観光 雪",
    "飛騨高山 アクセス 名古屋 新幹線",
    "飛騨高山 お土産 おすすめ 人気",
    "白川郷 アクセス 飛騨高山 から",
    "飛騨高山 宿泊 安い ゲストハウス",
    "飛騨高山 子供 観光 ファミリー",
]


def generate_kw_hida(item: dict) -> list[str]:
    """飛騨の思い出用KW生成（観光・グルメ・体験）。"""
    name = item["name"]
    kws = [
        f"{name} 飛騨高山 アクセス",
        f"{name} 口コミ 評判",
        f"{name} 予約 方法",
        f"{name} おすすめ 時期",
    ]
    return kws


def generate_kw_web_study1(item: dict) -> list[str]:
    """オンライン学習ナビ用KW生成（オンライン学習・教材・勉強法）。"""
    name = item["name"]
    kws = []

    if any(w in name for w in ["スタディサプリ", "スタサプ"]):
        kws += [
            f"スタディサプリ 評判 口コミ 社会人",
            f"スタディサプリ 料金 プラン 比較",
            f"スタディサプリ 使い方 英語",
            f"スタディサプリ 無料 体験 登録",
            f"スタディサプリ 資格 おすすめ",
        ]
    elif any(w in name for w in ["英語", "TOEIC", "英検", "英会話"]):
        kws += [
            f"{name} 評判 口コミ",
            f"{name} 料金 比較",
            f"{name} 無料 体験",
            f"{name} 効果 上達",
            f"{name} 初心者 始め方",
        ]
    elif any(w in name for w in ["プログラミング", "Python", "Java", "HTML", "Ruby", "Web"]):
        kws += [
            f"{name} 料金 比較",
            f"{name} 評判 口コミ",
            f"{name} 無料 体験",
            f"{name} 転職 就職",
            f"{name} 初心者 おすすめ",
        ]
    elif any(w in name for w in ["資格", "通信", "講座"]):
        kws += [
            f"{name} 評判 口コミ",
            f"{name} 料金 費用",
            f"{name} 合格率 難易度",
            f"{name} 無料 資料請求",
            f"{name} おすすめ 比較",
        ]
    elif any(w in name for w in ["子供", "こども", "小学", "中学", "高校", "受験"]):
        kws += [
            f"{name} 評判 口コミ 親",
            f"{name} 料金 月額 比較",
            f"{name} 無料 体験 登録",
            f"{name} 効果 成績",
            f"{name} おすすめ 学年",
        ]
    else:
        kws += [
            f"{name} 評判 口コミ",
            f"{name} 料金 比較",
            f"{name} 無料 体験",
            f"{name} おすすめ 使い方",
            f"{name} 始め方 初心者",
        ]
    return kws


# web-study1 フォールバックKW（ASP案件がない場合のジャンルKW）
WEB_STUDY1_FALLBACK_KW = [
    "スタディサプリ 評判 口コミ 社会人",
    "スタディサプリ 料金 プラン 比較",
    "スタディサプリ 使い方 英語",
    "スタディサプリ 無料 体験 登録",
    "スタディサプリ 資格 おすすめ",
    "進研ゼミ 小学講座 評判 口コミ",
    "進研ゼミ 中学講座 料金 比較",
    "スマイルゼミ 評判 進研ゼミ 比較",
    "スマイルゼミ 料金 月額 小学生",
    "Z会 評判 口コミ 難しい",
    "Z会 料金 比較 タブレット",
    "ポピー 通信教育 評判",
    "天神 通信教育 口コミ 料金",
    "公文式 月謝 料金 比較",
    "英語 通信教育 小学生 おすすめ",
    "オンライン英会話 子供 おすすめ 比較",
    "オンライン英会話 初心者 安い おすすめ",
    "DMM英会話 評判 料金 比較",
    "レアジョブ 評判 料金 比較",
    "TOEIC 勉強法 初心者 独学",
    "TOEIC 教材 おすすめ 2024",
    "英検 2級 勉強法 独学",
    "英検 準2級 テキスト おすすめ",
    "プログラミング 独学 初心者 方法",
    "プログラミング スクール 社会人 おすすめ",
    "Python 独学 初心者 参考書",
    "子供 プログラミング 通信教育 おすすめ",
    "ヒューマンアカデミー 通信講座 評判 口コミ",
    "ユーキャン 評判 口コミ 資格",
    "ユーキャン おすすめ 資格 稼げる",
]

# ブログキー → KW生成関数のマッピング
KW_GEN_MAP = {
    "hataraku": generate_kw_hataraku,
    "workup-ai": generate_kw_workup_ai,
    "ys-trend": generate_kw_ys_trend,
    "kaerudoko": generate_kw_kaerudoko,
    "hapipo8": generate_kw_hapipo8,
    "hida-no-omoide": generate_kw_hida,
    "web-study1": generate_kw_web_study1,
}


def append_keywords(ss_id: str, keywords: list[str], blog_key: str = "") -> bool:
    """キーワードシートのA列末尾にキーワードを追記する。"""
    try:
        ss = gc.open_by_key(ss_id)
        # AIVice は KW調査シートのD列
        if blog_key == "workup-ai":
            return _append_kw_aivice(ss, keywords)
        ws = ss.worksheet(KW_SHEET_NAME)
        rows_data = [[kw] for kw in keywords]
        ws.append_rows(rows_data, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        print(f"  [ERROR] キーワード書き込み失敗: {e}")
        return False


def _append_kw_aivice(ss, keywords: list[str]) -> bool:
    """AIVice専用キーワード追記（KW調査シートのD列）。"""
    try:
        ws = ss.worksheet(AIVICE_KW_SHEET)
        # 末尾行を確認
        all_values = ws.get_all_values()
        next_row = len(all_values) + 1
        # D列に追記（D列はインデックス4）
        # gspreadでD列のみ更新するため、セル指定で書き込む
        cell_list = []
        for i, kw in enumerate(keywords):
            cell_list.append(gspread.Cell(next_row + i, 4, kw))  # D列 = 4
        ws.update_cells(cell_list, value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        print(f"  [ERROR] AIVice KW追記失敗: {e}")
        return False


def fetch_kaerudoko_products(ss_id: str) -> list[str]:
    """どこで売ってるナビの商品シートから商品名を取得する。"""
    try:
        ss = gc.open_by_key(ss_id)
        ws = ss.worksheet("商品")
        rows = ws.get_all_values()
        products = [r[0].strip() for r in rows if r and r[0].strip()]
        return products
    except Exception as e:
        print(f"  [ERROR] 商品シート取得失敗: {e}")
        return []


def process_blog(blog: dict) -> dict:
    """1ブログを処理する。"""
    print(f"\n{'='*60}")
    print(f"ブログ: {blog['name']} ({blog['key']})")
    print(f"SS_ID: {blog['ss_id'][:20]}...")

    result = {
        "name": blog["name"],
        "asp_count": 0,
        "added_count": 0,
        "added_kws": [],
        "errors": [],
    }

    # Step 1: ASP案件を読み込む
    asp_items = fetch_asp_items(blog["ss_id"], blog["name"], blog["key"])
    result["asp_count"] = len(asp_items)
    print(f"  ASP案件: {len(asp_items)}件")
    for item in asp_items:
        print(f"    [{item['priority']}] {item['name']}")

    # Step 2: 既存KWを読み込む
    existing_kws = fetch_existing_keywords(blog["ss_id"], blog["key"])
    print(f"  既存KW: {len(existing_kws)}件")

    # Step 3: ロングテールKW生成
    gen_func = KW_GEN_MAP.get(blog["key"])
    new_kws = []
    candidate_kws = []

    if blog["key"] == "kaerudoko":
        # kaerudokoは商品シートからKW生成（ASP案件ではなく商品ベース）
        products = fetch_kaerudoko_products(blog["ss_id"])
        print(f"  商品数: {len(products)}件")
        for product in products:
            kws = generate_kw_kaerudoko_from_product(product)
            candidate_kws.extend(kws)

    elif blog["key"] == "web-study1" and len(asp_items) == 0:
        # web-study1 ASP案件なし → フォールバックKW使用
        print(f"  ASP案件なし → オンライン学習系フォールバックKWを使用")
        candidate_kws = WEB_STUDY1_FALLBACK_KW

    elif blog["key"] == "hida-no-omoide":
        # 飛騨の思い出: ASP案件からKW + フォールバックKW
        for item in asp_items:
            if gen_func:
                kws = gen_func(item)
                candidate_kws.extend(kws)
        candidate_kws.extend(HIDA_FALLBACK_KW)

    else:
        for item in asp_items:
            if gen_func:
                kws = gen_func(item)
                candidate_kws.extend(kws)

        # workup-ai は追加KWも生成
        if blog["key"] == "workup-ai":
            candidate_kws.extend(WORKUP_AI_EXTRA_KW)

    # 重複除去
    seen = set()
    for kw in candidate_kws:
        kw = kw.strip()
        if not kw:
            continue
        if kw in existing_kws:
            continue
        if kw in seen:
            continue
        seen.add(kw)
        new_kws.append(kw)

    result["added_kws"] = new_kws
    result["added_count"] = len(new_kws)
    print(f"  新規KW候補: {len(new_kws)}件")

    # Step 4: キーワードシートに追記
    if new_kws:
        ok = append_keywords(blog["ss_id"], new_kws, blog["key"])
        if ok:
            print(f"  書き込み完了: {len(new_kws)}件")
        else:
            result["errors"].append("書き込み失敗")
    else:
        print(f"  追加KWなし（全て重複または生成なし）")

    return result


def main():
    print("=" * 60)
    print("ロングテールKW生成・追記スクリプト 開始")
    print("=" * 60)

    all_results = []
    for blog in BLOGS:
        try:
            result = process_blog(blog)
            all_results.append(result)
        except Exception as e:
            print(f"  [ERROR] {blog['name']} 処理エラー: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "name": blog["name"],
                "asp_count": 0,
                "added_count": 0,
                "added_kws": [],
                "errors": [str(e)],
            })

    # 最終レポート
    print("\n" + "=" * 60)
    print("最終レポート")
    print("=" * 60)
    for r in all_results:
        print(f"\n【{r['name']}】")
        print(f"  読み込み案件数: {r['asp_count']}件")
        print(f"  追加KW数: {r['added_count']}件")
        if r["added_kws"]:
            print("  追加KW一覧:")
            for kw in r["added_kws"]:
                print(f"    - {kw}")
        if r["errors"]:
            print(f"  エラー: {r['errors']}")

    print("\n完了")


if __name__ == "__main__":
    main()
