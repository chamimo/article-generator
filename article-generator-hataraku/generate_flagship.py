#!/usr/bin/env python3
"""
看板記事専用生成スクリプト
文字数・H3数の制限を緩和した高品質記事を生成してWordPressに投稿する。
"""
import sys
import os
import logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── ① 看板記事用構造を追加（H3×20〜28本 / FAQ×10〜12問 / max_tokens=20000）──
from modules import article_generator as _ag
_ag._ARTICLE_STRUCTURE[12000] = (20, 28, 10, 12, 20000)

# ── ② 必要モジュールのインポート ──
import json
from generate_lite import load_blog_config, post, fetch_patterns as _fetch_patterns
from modules import wp_context
from modules.article_generator import generate_article
from modules.wp_pattern_fetcher import fetch_patterns, match_pattern, insert_pattern_cta, insert_per_h3_cta
from modules.api_guard import check_stop

# ── ③ ブログ設定ロード & コンテキストセット ──
blog_cfg = load_blog_config("web-study1")

wp_context.set_context(
    wp_url=blog_cfg.wp_url,
    wp_username=blog_cfg.wp_username,
    wp_app_password=blog_cfg.wp_app_password,
    wp_post_status=blog_cfg.wp_post_status,
    candidate_ss_id=blog_cfg.candidate_ss_id,
    candidate_sheet=blog_cfg.candidate_sheet,
    image_style=blog_cfg.image_style,
    asp_ss_id=blog_cfg.asp_ss_id,
    blog_meta={
        "display_name":  blog_cfg.display_name,
        "wp_url":        blog_cfg.wp_url,
        "genre":         blog_cfg.genre,
        "site_purpose":  "教育・学習サービスの比較と紹介でアフィリエイト収益化",
        "target":        "子どもの教育を考える親・スキルアップしたい初心者",
        "writing_taste": (
            "やさしく丁寧で安心感のある文章。信頼性を重視し初心者でも理解できる構成。"
            "比較・メリット・デメリットをバランスよく提示。不安を解消し納得して選べるトーン。"
            "今回は親目線の体験談を前面に出した実体験ベースの比較記事。"
        ),
        "genre_detail":  "オンライン学習・プログラミング教育・教材・スキルアップ",
        "search_intent": "Know・Do中心＋Buy（教室・サービス比較）",
    },
)

# ── ④ アフィリエイトリスト ──
asp_list = [
    {"name": "Tech Kids School",                                    "url": "https://web-study1.com/tech-kids",          "priority": 1},
    {"name": "DMM WEBCAMP プログラミングコース",                     "url": "https://web-study1.com/web-camp_programing", "priority": 1},
    {"name": "Udemy",                                               "url": "https://web-study1.com/udemy",               "priority": 1},
    {"name": "小中学生専門のオンランプログラミングスクール【アンズテック】", "url": "https://web-study1.com/anzutech",         "priority": 1},
    {"name": "アンズテック",                                          "url": "https://web-study1.com/anzutech",           "priority": 1},
]

# ── ⑤ 記事アウトライン（differentiation_note として渡す）──
OUTLINE = """
【看板記事・体験談ベース比較記事】以下のアウトラインを忠実に反映してください。

■ 導入（250〜300字）
- 2020年プログラミング教育必修化・AI時代の到来という背景
- 親として「何を選べばいいかわからなかった」という共感からスタート
- 実際にいろいろ試してわかったことをベースにした記事、という前置き

■ H2: わが家で実際に試した子どものプログラミング学習
  H3: 最初は「マイクラ×Scratch」の通学型教室に通った
    - 子どもが楽しんでいた（ゲーム要素があって取り組みやすかった）
    - ただし教室が遠く、送迎が大変で続かなかった現実
  H3: 書籍だけでは継続が難しかった
    - 書籍を購入して親が教えようとしたが、教えることの難しさを実感
    - 親自身もプログラミング知識が必要になり限界を感じた
  H3: ProgateとドットインストールはAIかなり楽しんでいた
    - ゲーム感覚・レベルアップ感覚で進められる
    - 自分のペースで、無料から始められる良さ
    - 今でもおすすめしたいサービス
  H3: 今はClaude CodeなどAI開発にも興味を持ち始めている
    - 自然言語でコードを書けるようになったAI時代
    - 小学生でもAIを使って開発できる可能性が広がっている
  H3: それでも「基礎理解」は必要だと痛感した（★重要）
    - AIにコードを書かせてもバグやエラーで詰まることがある
    - エラーの意味がわからないと修正できない
    - AI任せでは乗り越えられない壁がある → だから基礎学習に意義がある

■ H2: 子どものプログラミング学習で感じた「続く子」の特徴
  H3: 好きなテーマがある（ゲーム・ロボット・マイクラなど）
  H3: 自分でどんどん触れる環境がある
  H3: 正解より試行錯誤を楽しめる性格
  H3: 親が管理しすぎず見守っている

■ H2: 子ども向けプログラミング教室おすすめ比較
  【必ず比較テーブルを入れる。HTML tableタグではなくWordPress SWELL形式の wp:table ブロックで出力すること】
  テーブル列: 教室名 | 形式 | 対象年齢 | 特徴 | 料金目安 | 向いている子
  テーブル内容:
  - Tech Kids School | 通学+オンライン | 小中学生 | 本格カリキュラム、ゲーム・AI制作 | 月額約28,000円〜 | 本格派・将来エンジニア志望
  - アンズテック | オンライン専門 | 小〜中学生 | 初心者向け・マンツーマン対応 | 月額約8,800円〜 | はじめてのオンライン
  - チャレンジタッチ | タブレット | 小学1〜6年 | プログラミング入門コース付き | 月額約3,400円〜 | まず試してみたい
  - スマイルゼミ | タブレット | 小〜中学生 | タブレット学習型・プログラミング対応 | 月額約3,278円〜 | 勉強習慣づくりと一緒に
  - すらら | オンライン | 小〜高校生 | 自分のペース・対話型AI | 月額約8,228円〜 | マイペース・苦手意識あり
  - Udemy | 動画（買い切り） | 小学生〜大人 | セール時は数百円〜・繰り返し可 | 1講座数百円〜 | 自主性ある子・親子学習

  H3: 本格的に学ばせたいならTech Kids School
    - ゲーム制作・AI・本格カリキュラム
    - 将来のIT・AI分野を本気で目指す子向け
    - 有名企業出身の講師が教える安心感
    ★ ここでTech Kids SchoolのCTAパターンを挿入する

  H3: オンラインではじめてならアンズテックがかなり良さそう（体験談あり）
    - 小中学生専門のオンラインプログラミングスクール
    - 通学型で挫折した経緯があるのでオンラインの手軽さは大きな魅力
    - 体験談：「うちは通学が遠くて続かなかったのでオンラインは本当に魅力的。アンズテックはマンツーマン対応があって親としても安心できる。」
    ★ ここでアンズテックのCTAパターンを挿入する

  H3: 家で気軽に始めるならチャレンジタッチ・スマイルゼミ
    - プログラミングの入口として敷居が低い
    - すでに使っているタブレット学習に追加できる

  H3: UdemyはAI・プログラミング学習コスパ最強だった（SEO強）
    - 買い切りで何度でも見返せる
    - セール時（年に数回）は1講座1,200円以下になることも
    - 親子で一緒に学習できるのが良かった
    ★ ここでUdemyのCTAパターンを挿入する

  H3: ProgateとドットインストールはAIでも今でもおすすめ
    - 完全無料から始められる（Progate）
    - ゲーム感覚でレベルアップできる仕組みが継続につながる
    - アフィリリンクなしでもぜひ紹介したいサービス（信頼度高い）

  H3: ゲーム好きならSwitchのプログラミング系ゲームも入口になる
    - 「はじめてゲームプログラミング」（Nintendo Switch）
    - マイクラのコマンドブロックやMakeCodeでのプログラミング学習
    - 遊び感覚で「プログラミングって面白い」と感じさせる第一歩

■ H2: AI時代だからこそ「基礎理解」が大事だと感じている（★差別化・親目線の気づき）
  H3: Claude CodeなどAI開発ツールを小学生も使える時代になった
    - 自然言語でコードが書ける → プログラミングの敷居が劇的に下がった
    - Claude CodeやCopilotを実際に子どもが使っている事例を紹介
  H3: でも「なぜエラーになるか」がわからないと詰まる
    - AIが書いたコードのバグ・エラーが理解できない問題
    - AI任せの限界 → エラーログが読めない = 解決できない
  H3: 基礎理解があるとAIが100倍活きる
    - コードを読んで「何をしているか」がわかる
    - AIの出力を評価・修正できる力がつく
    - これが「AI時代の本当のプログラミング力」という親目線の気づき

■ まとめ（H3としてまとめ見出しを設ける）
  H3: 子どものプログラミング学習は「楽しい」がいちばん大事
    - 続けることが最優先
    - まずは本人が楽しいと感じるものを選ぶのがコツ
    - 失敗してもいい → 試行錯誤すること自体がプログラミング的思考

■ FAQ（10問・各200字以上）
1. 子どものプログラミング教室は何歳から始めればいい？
2. 通学型とオンライン型、どちらが向いている？
3. プログラミング教室の月謝の相場はどのくらい？
4. 子どもが飽きてしまったらどうする？
5. 女の子にもプログラミング学習は向いている？
6. 発達障害・不登校の子でも通えるプログラミング教室はある？
7. 無料で始められるプログラミング学習はある？
8. 小学生と中学生では教室の選び方が違う？
9. Scratchとは何？どんな子に向いている？
10. 将来ITエンジニアを目指すならどの教室がおすすめ？

■ 比較テーブル出力形式（WordPress SWELL）
必ず以下の形式でwp:tableブロックを使って比較テーブルを出力すること:
<!-- wp:table {"className":"is-style-stripes"} -->
<figure class="wp-block-table is-style-stripes"><table><thead>...</thead><tbody>...</tbody></table></figure>
<!-- /wp:table -->
"""

KEYWORD = "子ども プログラミング教室 おすすめ 比較"
TITLE   = "子ども向けプログラミング教室おすすめ比較｜実際に試してわかった続けやすい学び方"

# ── ⑥ 安全装置チェック ──
check_stop()

# ── ⑦ 記事生成 ──
log.info("=" * 60)
log.info(f"看板記事生成開始: 「{TITLE}」")
log.info("=" * 60)

article = generate_article(
    keyword=KEYWORD,
    volume=0,
    differentiation_note=OUTLINE,
    target_length=12000,
    forced_title=TITLE,
    asp_list=asp_list,
    enable_fact_check=True,
)

content_len = len(article.get("content", ""))
log.info(f"記事生成完了: 「{article['title']}」 コンテンツ長: {content_len:,}字")

# ── ⑧ WPパターンCTA挿入 ──
try:
    patterns = fetch_patterns(blog_cfg)
    if patterns:
        # H3末尾への案件別CTA挿入
        article["content"], n_h3 = insert_per_h3_cta(
            article["content"], patterns, asp_list
        )
        if n_h3 > 0:
            log.info(f"パターンCTA挿入（H3末尾）: {n_h3}件")

        # キーワードマッチCTA（ポイントブロック直後 + 末尾）
        asp_names = [item["name"] for item in asp_list]
        matched = match_pattern(KEYWORD, patterns, asp_names=asp_names)
        if matched:
            article["content"] = insert_pattern_cta(
                article["content"], matched, skip_mention=(n_h3 > 0)
            )
            log.info(f"パターンCTA挿入（KWマッチ）: 「{matched.title}」(ID:{matched.id})")
    else:
        log.info("パターンなし（CTAスキップ）")
except Exception as e:
    log.warning(f"CTAパターン挿入スキップ: {e}")

# ── ⑨ 記事タイプ付与 ──
article["_article_type"] = "monetize"
article["_kw_status"]    = "claude"

# ── ⑩ WordPress投稿 ──
log.info("WordPress 投稿開始...")
try:
    result = post(article, dry_run=False, blog_cfg=blog_cfg, asp_list=asp_list)
    log.info(f"✅ 投稿完了: ID={result['id']} → {result['edit_url']}")
    print(f"\n投稿URL: {result['edit_url']}")
except Exception as e:
    log.error(f"❌ 投稿エラー: {e}")
    raise
