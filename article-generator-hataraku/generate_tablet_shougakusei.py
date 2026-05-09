#!/usr/bin/env python3
"""
タブレット学習 小学生 比較 記事生成スクリプト - オンライン学習ナビ
体験談（スマイルゼミ・チャレンジタッチ・すらら・スタディサプリ）ベース
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

from modules import article_generator as _ag
_ag._ARTICLE_STRUCTURE[9000] = (14, 18, 10, 12, 18000)

from generate_lite import load_blog_config, post
from modules import wp_context
from modules.article_generator import generate_article
from modules.wp_pattern_fetcher import fetch_patterns, match_pattern, insert_pattern_cta, insert_per_h3_cta
from modules.api_guard import check_stop

blog_cfg = load_blog_config("web-study1")

wp_context.set_context(
    wp_url=blog_cfg.wp_url,
    wp_username=blog_cfg.wp_username,
    wp_app_password=blog_cfg.wp_app_password,
    wp_post_status=blog_cfg.wp_post_status,
    candidate_ss_id=blog_cfg.candidate_ss_id,
    candidate_sheet=blog_cfg.candidate_sheet,
    image_style=getattr(blog_cfg, "image_style", None),
    asp_ss_id=blog_cfg.asp_ss_id,
    blog_meta={
        "display_name":  blog_cfg.display_name,
        "wp_url":        blog_cfg.wp_url,
        "genre":         blog_cfg.genre,
        "site_purpose":  "オンライン学習・通信教育サービスの紹介と比較でアフィリエイト収益化",
        "target":        "小学生のタブレット学習を検討している保護者・複数サービスを比較して選びたい親",
        "writing_taste": (
            "やさしく丁寧で安心感のある文章。実際に複数サービスを使った体験談ベースで信頼性重視。"
            "比較・メリット・デメリットをバランスよく提示。不安を解消し納得して選べるトーン。"
            "「どの子に何が合うか」を軸に整理し、背中を押す実用的な構成。"
            "NG表現：〜してみてください／〜がおすすめです／ぜひ〜"
        ),
        "genre_detail":  "通信教育・タブレット学習・小学生・比較",
        "search_intent": "Do（比較・検討）＋Buy（サービス選び・申し込み）",
    },
)

asp_list = [
    {"name": "すらら",       "url": "https://web-study1.com/surara",                   "priority": 1,
     "description": "無学年式。先取り・さかのぼり学習。すららコーチのサポート。不登校・発達障害にも対応。"},
    {"name": "スマイルゼミ", "url": "https://web-study1.com/smile-zemi",               "priority": 1,
     "description": "シンプル設計でサクサク進む。漢検サポートあり。習慣化しやすい。"},
    {"name": "進研ゼミ 小学講座", "url": "https://web-study1.com/shinkenzemi-syougakukouza", "priority": 2,
     "description": "チャレンジタッチ。キャラクター・エンタメ感が強く楽しさで勉強ハードルを下げる。"},
    {"name": "Z会",          "url": "https://web-study1.com/zkai",                     "priority": 2,
     "description": "思考力・記述力を鍛える。難関中学受験にも対応。"},
    {"name": "スタディサプリ", "url": "https://web-study1.com/studysapuri-chugaku",    "priority": 2,
     "description": "授業動画がわかりやすい。月額が安くコスパ抜群。シンプルで集中しやすい。"},
    {"name": "こどもチャレンジ", "url": "https://web-study1.com/shimajiro",            "priority": 2,
     "description": "しまじろうと一緒に学ぶ。幼児〜小学校低学年向け。生活習慣・情操教育も。"},
]

KEYWORD = "タブレット学習 小学生 比較"
TITLE   = "小学生タブレット学習6社を徹底比較！すらら・スマイルゼミ・進研ゼミ…体験談で選び方を解説"

TESTIMONIAL = """\
【実際に使った体験談（EEATとして必ず自然に組み込む・各サービスの紹介H3に対応する箇所で使用）】

我が家では、子どもの学習スタイルや成長に合わせて、いくつかの通信教育教材を実際に利用してきました。
最初は「スマイルゼミ」から始まり、その後「チャレンジタッチ」、そして「すらら」、さらに「スタディサプリ」も活用しています。
それぞれ特徴がかなり違っていて、子どもの性格や、その時期の状態によって合う教材も変わると感じました。

通信教育にしたことで、塾の送り迎えが不要・家で学習できる・子どものペースで進められる、というメリットも大きく、我が家にはかなり合っていたと思います。

＜スマイルゼミ＞
最初に始めた通信教育教材。シンプルな設計で、開いた瞬間に「今日やること」がわかりやすかった。操作や学習導線に迷いが少なく、取り組みやすかった。テンポよく「サクサク進められる感じ」が子どもに合っていた。毎日の学習習慣づくりにつながった。漢検の受験料サポート制度があり、実際に漢検にチャレンジできた。「検定に挑戦する」というモチベーションにもつながった。塾のように送り迎えが不要で、親の負担が少なかった。

＜チャレンジタッチ（進研ゼミ 小学講座）＞
キャラクター要素が豊富で、ゲーム感覚やエンタメ感が強め。全体的に「楽しく勉強しよう！」という雰囲気。明るく陽キャっぽい世界観が特徴的。勉強へのハードルを下げやすい印象。楽しさ重視なので、子どもによって好みは分かれるかもしれない。クイズ感覚で進められる部分もあり、自然と勉強に触れやすかった。継続のきっかけづくりには良かった。

＜すらら＞
コロナ禍やさまざまな事情の中で導入。「無学年式」のため、先取り学習・さかのぼり学習ができた。小学5年生の段階で、中学2年生までの数学を進めることができた。得意科目をどんどん伸ばせた。苦手単元は前の学年まで戻って復習できた。「わからないまま進む」を防ぎやすかった。すららコーチのサポートがとても良かった。メッセージや声かけが励みになった。ゲーミフィケーション要素が強く、やる気につながった（すらカップなどのイベント）。気づいたらかなり進んでいた、ということがよくあった。一方で、全体的なテンポはややゆっくりめに感じることもあった。

＜スタディサプリ＞
小学生〜高校生まで利用。とにかく授業がわかりやすかった。先生の教え方が上手で、引き込まれる授業だった。シンプルな設計で使いやすかった。余計な装飾が少なく、勉強に集中しやすかった。「授業の質」を重視する人にはかなり合うと感じた。学校の授業で理解しづらかった部分の補強にも役立った。
"""

OUTLINE = f"""\
【記事構成・必ず全項目を守ること】

■ タイトル（固定）
小学生タブレット学習6社を徹底比較！すらら・スマイルゼミ・進研ゼミ…体験談で選び方を解説

■ サブキーワード（本文・見出しに自然に組み込む）
- タブレット学習 おすすめ 小学生
- タブレット学習 安い / コスパ

■ 読者像
- 小学生の子どもにタブレット学習を検討している保護者
- 複数サービスを比較して「どれが我が子に合うか」を判断したい
- 塾の代わり・学習習慣づくり・得意を伸ばす目的で探している

■ 導入（350字前後）
- 「タブレット学習って結局どれがいいの？」という保護者の疑問から書き出す
- 実際に4つのサービスを使い比べた体験談をもとに解説することを宣言
- すらら・スマイルゼミ・進研ゼミ・スタディサプリの4つを実際に使ったことを冒頭で提示
- すらら への1回目リンク挿入

{TESTIMONIAL}

■ H2: 小学生タブレット学習の選び方 ― 失敗しないための4つの軸
  H3: ① 学習スタイルに合うか（自学習型 vs 授業動画型）
    - 「自分でどんどん進める」のが好きか、「先生の授業を見たい」かで向くサービスが変わる
    - スマイルゼミ・すらら＝自学習型 / スタディサプリ＝授業動画型
  H3: ② 続けやすい仕掛けがあるか（ゲーム感 vs シンプル感）
    - キャラクター・ゲーム感が好きな子 → 進研ゼミ・すらら
    - シンプルに集中したい子 → スマイルゼミ・スタディサプリ
  H3: ③ 先取り・さかのぼり学習に対応しているか
    - 学年を超えて進める「無学年式」はすらら だけ
    - 学習に抜けがある子・先取りしたい子には特に重要な軸
  H3: ④ 費用・コスパで選ぶ（月額の目安）
    - 安い順: スタディサプリ（月2,178円〜）→ すらら → スマイルゼミ → 進研ゼミ → Z会
    - タブレット端末代・入会金・解約時の違約金も考慮して比較

■ H2: 【体験談あり】6サービスを徹底比較
  H3: ① スマイルゼミ ― 習慣化しやすく迷わず進める（体験談あり）
    - シンプル設計で開いたらすぐ「今日やること」がわかる
    - サクサク進む快感が学習習慣づくりに最適
    - 漢検受験料サポートで「検定挑戦」モチベーションも生まれた
    - 体験談：「テンポよく進められる感じが子どもに合っていた。毎日の習慣になった」
    - 向いている子：学習の流れをつかむのが好き・習慣化させたい
    ★スマイルゼミのCTA挿入
  H3: ② 進研ゼミ 小学講座（チャレンジタッチ）― 楽しさで勉強ハードルを下げる（体験談あり）
    - キャラクター×エンタメ感で「勉強が苦じゃない」雰囲気を作る
    - 明るく楽しい世界観で継続のきっかけに
    - 体験談：「陽キャっぽい雰囲気。楽しさ重視。クイズ感覚で自然と勉強に触れやすかった」
    - 向いている子：楽しいノリで勉強したい・エンタメ感がモチベーションになる子
    ★進研ゼミのCTA挿入
  H3: ③ すらら ― 無学年式で得意を伸ばし苦手をつぶす最強の仕組み（体験談あり）
    - 先取り学習：小5で中2数学を達成した実例を具体的に紹介
    - さかのぼり学習：苦手単元を前学年まで遡って復習できる
    - すららコーチのサポートで親子ともに安心感（体験談詳述）
    - ゲーミフィケーション×すらカップで自然と長時間集中
    - 体験談：「気づいたらかなり進んでいた。コーチのメッセージが励みになった」
    - デメリット：テンポがゆっくりめ。どんどん先へ進みたいタイプには少しもどかしいことも
    - 向いている子：学習に空白がある子・先取りしたい子・不登校・学習意欲に波がある子
    ★すらら のCTA挿入（メイン・2回目）
  H3: ④ Z会 ― 思考力・記述力を鍛えたい子に（比較情報）
    - ペーパーレス対応・AI学習機能。難関中学受験を視野に入れた設計
    - 問題の質が高く「じっくり考える力」を養える
    - 費用はやや高め・忍耐力のある子向け
    - 向いている子：中学受験を検討・思考力を鍛えたい・難易度の高い問題が好き
    ★Z会のCTA挿入
  H3: ⑤ スタディサプリ小学講座 ― コスパ最強・授業の質で選ぶなら（体験談あり）
    - 月額2,178円〜でプロ講師の授業が見放題
    - 先生の教え方が上手で「授業を見るのが苦じゃない」感覚
    - シンプル設計で余計な装飾がなく集中しやすい
    - 体験談：「学校の授業でわかりにくかった部分の補強にとても役立った」
    - 向いている子：授業の質重視・コスパを最優先したい・補習・苦手克服目的
    ★スタディサプリのCTA挿入
  H3: ⑥ こどもチャレンジ（しまじろう） ― 幼児〜低学年のスタートに
    - しまじろうのキャラクターで生活習慣・情操教育から自然に学び始める
    - 幼児〜小学1・2年生の「はじめての学習習慣」づくりに最適
    - 上の学年になったら進研ゼミ小学講座（チャレンジタッチ）へ移行しやすい
    ★こどもチャレンジのCTA挿入

■ H2: 目的別・子どものタイプ別 おすすめの選び方まとめ
  H3: 学習習慣を作りたい → スマイルゼミ or 進研ゼミ
    - 習慣化しやすい設計・毎日のルーティンになりやすい
  H3: 苦手克服・学習の抜けを補いたい → すらら
    - さかのぼり学習で学年をさかのぼって基礎を固められる
    ★すらら のCTA挿入（3回目）
  H3: 得意科目を先取りして伸ばしたい → すらら
    - 学年の壁がない無学年式で「もっとやりたい」をブレーキしない
  H3: コスパ重視・補習目的 → スタディサプリ
    - 月2,178円〜でプロ授業が見放題
  H3: 中学受験を見据えている → Z会 or すらら
    - Z会は記述・思考力特化 / すらら は先取りで早期に応用問題まで到達できる

■ まとめ
  H3: 迷ったらすらら の無料体験から試してみる
    - 無学年式・コーチサポート・ゲーミフィケーションで続けやすく、どの子にも対応幅が広い
    - まず無料体験で子どもに合うか確認してから入会できる
    ★すらら の CTA挿入（まとめ・4回目）

■ FAQ（10問・各200字以上）
1. 小学生のタブレット学習は何歳から始めるのがいい？
2. スマイルゼミと進研ゼミ、どちらが続けやすい？
3. すらら は費用が高い？他と比べてどうか
4. タブレット学習で視力は悪くなる？対策は？
5. 学習習慣がない子でもタブレット学習で続けられる？
6. 塾とタブレット学習の併用はあり？
7. すらら の無学年式とはどういう意味？どんな子に向いている？
8. 進研ゼミとチャレンジタッチの違いは？
9. スタディサプリ小学講座は本当に安くていい？デメリットは？
10. 子どもがタブレット学習を嫌がるときの対処法は？
"""

import json as _json
_CACHE = os.path.join(os.path.dirname(__file__), "_cache_tablet_shougakusei.json")

check_stop()

log.info("=" * 60)
log.info(f"記事生成開始（オンライン学習ナビ）: 「{TITLE}」")
log.info("=" * 60)

if os.path.exists(_CACHE):
    log.info(f"[cache] 生成済み記事を読み込みます: {_CACHE}")
    with open(_CACHE, encoding="utf-8") as f:
        article = _json.load(f)
    log.info(f"[cache] タイトル: {article.get('title')}")
else:
    article = generate_article(
        keyword=KEYWORD,
        volume=500,
        differentiation_note=OUTLINE,
        target_length=9000,
        forced_title=TITLE,
        asp_list=asp_list,
        enable_fact_check=True,
        article_type="monetize",
    )
    with open(_CACHE, "w", encoding="utf-8") as f:
        _json.dump(article, f, ensure_ascii=False, indent=2)
    log.info(f"[cache] 記事を保存しました: {_CACHE}")

log.info(f"記事生成完了: 「{article['title']}」 コンテンツ長: {len(article.get('content','')   ):,}字")

# CTA挿入
try:
    patterns = fetch_patterns(blog_cfg)
    if patterns:
        article["content"], n_h3 = insert_per_h3_cta(article["content"], patterns, asp_list)
        if n_h3 > 0:
            log.info(f"パターンCTA挿入（H3末尾）: {n_h3}件")
        asp_names = [item["name"] for item in asp_list]
        matched = match_pattern(KEYWORD, patterns, asp_names=asp_names)
        if matched:
            article["content"] = insert_pattern_cta(article["content"], matched, skip_mention=(n_h3 > 0))
            log.info(f"パターンCTA挿入（KWマッチ）: 「{matched.title}」(ID:{matched.id})")
except Exception as e:
    log.warning(f"CTAパターン挿入スキップ: {e}")

article["_article_type"] = "monetize"
article["_kw_status"]    = "claude"

log.info("WordPress 投稿開始...")
result = post(article, dry_run=False, blog_cfg=blog_cfg, asp_list=asp_list)
log.info(f"✅ 投稿完了: ID={result['id']} → {result['edit_url']}")
print(f"\n投稿URL: {result['edit_url']}")
