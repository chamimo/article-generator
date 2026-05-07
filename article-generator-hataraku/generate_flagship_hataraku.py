#!/usr/bin/env python3
"""
看板記事専用生成スクリプト - はた楽ナビ
「転職したいけど不安 何から始める」
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

# ── 看板記事用構造を追加（H3×20〜28 / FAQ×10〜12 / max_tokens=20000）──
from modules import article_generator as _ag
_ag._ARTICLE_STRUCTURE[12000] = (20, 28, 10, 12, 20000)

from generate_lite import load_blog_config, post
from modules import wp_context
from modules.article_generator import generate_article
from modules.wp_pattern_fetcher import fetch_patterns, match_pattern, insert_pattern_cta, insert_per_h3_cta
from modules.api_guard import check_stop

blog_cfg = load_blog_config("hataraku")

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
        "site_purpose":  "就労支援・転職・副業系サービスの紹介と比較でアフィリエイト収益化",
        "target":        "働き方に悩む20〜40代・副業や転職を考えている人・発達障害やIT就労に興味がある層・体調や環境的な理由で通勤が難しい人",
        "writing_taste": (
            "経験者の本音・リアル。転職を複数回経験したWeb担当者の視点で、失敗談も交えた共感重視の文体。"
            "結論が明確で実用的。信頼感があり論理的。比較・メリット・デメリット・向いている人をはっきり示す。"
            "読者が迷わず行動できるよう背中を押すトーン。"
            "NG表現：〜してみてください／〜がおすすめです／ぜひ〜"
        ),
        "genre_detail":  "就労支援・転職・副業・フリーランス・ITスキル・在宅ワーク",
        "search_intent": "Feel（不安・悩み）＋Do（比較・検討）",
    },
)

asp_list = [
    {"name": "転職AGENT Navi",          "url": "https://hataraku-navi.com/agent-navi",  "priority": 1},
    {"name": "ヒューマンアカデミー",       "url": "https://hataraku-navi.com/human-academy","priority": 1},
    {"name": "Neuro Dive",              "url": "https://hataraku-navi.com/neuro_dive",   "priority": 1},
    {"name": "ニューロダイブ",             "url": "https://hataraku-navi.com/neuro_dive",   "priority": 1},
    {"name": "ウズウズIT",               "url": "https://hataraku-navi.com/uzuuzu_it",   "priority": 1},
    {"name": "クラウドワークス",           "url": "https://hataraku-navi.com/crowdworks",  "priority": 1},
    {"name": "atGP",                    "url": "https://hataraku-navi.com/atgp",         "priority": 2},
    {"name": "atGPジョブトレ IT・Web",   "url": "https://hataraku-navi.com/atgp_job",    "priority": 2},
    {"name": "FREENANCE",               "url": "https://hataraku-navi.com/freenance",    "priority": 2},
    {"name": "Midworks",                "url": "https://hataraku-navi.com/midworks",     "priority": 2},
]

OUTLINE = """
【看板記事・体験談ベース・人間味重視】以下のアウトラインを忠実に反映してください。
検索意図は Feel（不安・悩みに寄り添う）＋ Do（具体的な行動ルートを示す）です。

■ タイトル（固定）
転職したいけど不安で踏み出せない人へ｜何から始めるか、体験談をもとに解説

■ 導入（300字前後）
- 転職したいけど不安で動けない、という気持ちはよくわかる、という書き出し
- 人間関係・スキル不足・通勤の不安など、理由は人それぞれ
- 筆者自身も体が強くなく、通勤でつらい思いをして在宅ワークへ転換した経験がある
- この記事では不安の整理から具体的な一歩まで、実体験をもとに書いた

■ H2: 転職したいけど不安――あなたの「不安の正体」はどれですか？
  H3: 人間関係がまたうまくいかないかもしれない
    - 前職でのつらい経験がフラッシュバックする
    - 新しい職場にも同じような人がいたら…という恐怖
    - でも環境が変わると人間関係も変わる可能性が高い
  H3: 自分にはスキルが足りない気がする
    - 「即戦力じゃないと採用されない」という思い込み
    - 実はポテンシャル採用・未経験OKの求人は多い
    - スキルより「行動できるかどうか」を見ている企業も多い
  H3: 通勤・体調管理への不安
    - 朝の満員電車が体にきつい
    - 体調を崩したらどうしよう、という心配
    - 筆者自身もここが一番の悩みだった（体験として触れる）
  H3: 転職に失敗したらどうしよう
    - 失敗のイメージが先行してしまう
    - でも「転職しないリスク」も存在する
    ★体験談を挿入：20代・女性・事務職「初めての転職で不安が大きく…失敗してもいいや、という気持ちで動いたのが良かったです」

■ H2: 転職したいけど不安なとき、まず何から始めるか
  H3: まず「何が不安なのか」を紙に書き出す
    - 漠然とした不安を言語化するだけで楽になる
    - 「スキル不安なのか」「人間関係不安なのか」で対策が変わる
  H3: 情報収集から始める（求人を見るだけでもOK）
    - 転職サイトを見るだけ、は立派な第一歩
    - 求人を見ると「自分に何が足りないか」「何が向いているか」が見えてくる
  H3: 転職エージェントに相談してみる（無料・1回でOK）
    - エージェントは「転職を強制する場所」ではない
    - 自分の状況を話すだけでも整理になる
    - 無料で使えるので気軽に相談できる
    ★転職AGENT NaviのCTA挿入
    ★体験談を挿入：30代・男性・製造業「担当者が丁寧にヒアリングしてくれたおかげで、自分でも気づいていなかった強みを言語化できました。年収が150万円上がりました」

■ H2: まず資格・スキルを身につけてから転職したい人へ
  H3: ヒューマンアカデミーで資格から入るルート
    - IT・医療事務・デザイン・ネイルなど幅広いジャンルの資格講座
    - 資格があると「自分にはこれがある」という自信になる
    - 在宅学習も可能で、仕事をしながら取得できる
    ★ヒューマンアカデミーのCTA挿入
  H3: ITスキルをゼロから身につけるならウズウズIT
    - 未経験・第二新卒向けのITスクール
    - 就職支援まで一括サポート
    - プログラミング・インフラ・クラウドなど選べる
    ★ウズウズITのCTA挿入
  H3: 体調や障害で不安がある人はNeuro Dive（ニューロダイブ）も選択肢に
    - 発達障害・精神障害のある方を専門にサポートするIT就労支援
    - IT・Webスキルを身につけながら安定就労を目指せる
    - 在宅での訓練・就労も視野に入れられる
    ★Neuro DiveのCTA挿入
  H3: atGPジョブトレ IT・Webという選択肢もある
    - IT・Webスキルを訓練してから就職を目指すプログラム
    - 障害のある方・体調に不安のある方にも対応
    ★atGPジョブトレのCTA挿入

■ H2: 外で働くのが難しい・在宅ワークを考えている人へ
  H3: 在宅ワークができる仕事は、今や選び放題の時代
    - WEB制作・SEOライティング・デザイン・動画編集・データ入力など
    - AI時代になって「AIを使えるスキル」があると在宅でできる仕事の幅が大きく広がった
    - AI開発・AIプロンプト設計・AIを使ったコンテンツ制作なども在宅で可能
  H3: クラウドワークスで小さく始める方法
    - 登録無料で、スキルがなくても始められる案件がある
    - ライティング・データ入力・アンケートなどから経験を積める
    - 実績を積むことで単価を上げていける
    ★クラウドワークスのCTA挿入
  H3: フリーランスとして独立するなら保険も考えておく（FREENANCE）
    - 会社員の社保がなくなるフリーランスは収入・保険の備えが必要
    - フリーランス専用の保険・保障サービスFREENANCEが便利
    ★FREENANCEのCTA挿入

■ H2: 筆者の話｜体が弱くて通勤できなくなり、在宅の道へ進んだ（★差別化・人間味）
  H3: 朝の通勤でお腹を壊して遅刻が続いた
    - もともと体が強くなく、通勤ラッシュでストレスがかかるとお腹の調子が悪くなりがちだった
    - 遅刻が重なり、職場での居心地が悪くなっていった
    - 「このまま続けるのが正解なのか」という疑問が大きくなった
  H3: 在宅ワークへの転換を決めた理由
    - 「通勤しなくていいなら、仕事への不安の半分は消える」と気づいた
    - まずWEB制作の勉強を始め、副業として小さく実績を積んだ
    - SEOライティングもできるようになり、在宅の仕事が増えていった
  H3: AIを使いこなすことで、さらに自由が広がった
    - Claude Codeをはじめ、AIツールを活用することで自分ひとりでできる仕事の幅が増えた
    - デザイン・コーディング・記事執筆・SEO施策まで、AIを使えば一人でかなりこなせる
    - 「好きな時間・好きな場所で仕事する」という環境を自分で作れるようになった
  H3: 自分の働きやすい環境を作ることで、不安が大幅に減った
    - 通勤ストレスがなくなっただけで、仕事への向き合い方が変わった
    - 体調が安定したことで、成果も出しやすくなった
    - 転職は怖いけど、「働き方を変える」選択肢があると知ることが第一歩

■ H2: AI時代だからこそ、働き方の選択肢は広がっている（★SEO強・差別化）
  H3: AIを使ったデザイン・ライティング・開発は在宅でできる
    - Midjourney・Canvaを使ったデザイン制作
    - AIライティング・プロンプトエンジニアリング
    - Claude Code・GitHub Copilotを使ったコーディング支援
  H3: フリーランスとして活動するなら Midworks も選択肢
    - フリーランスエンジニア・クリエイター向けのエージェント
    - 案件紹介＋保険・福利厚生サポートが充実
    ★MidworksのCTA挿入
  H3: 「会社員じゃないとダメ」という思い込みを手放してみる
    - 正社員・派遣・業務委託・フリーランスなど選択肢は複数ある
    - 転職を考えるとき「正社員以外」も含めて視野を広げると可能性が広がる

■ まとめ
  H3: 転職の不安は行動することで少しずつ和らいでいく
    - 最初の一歩は情報収集だけでいい
    - 不安の正体を書き出して、自分に合った「出口」を探そう
    - 環境を変える勇気は、自分を守るための選択でもある

■ FAQ（10問・各200字以上）
1. 転職したいけど不安で動けない、どうすればいい？
2. 転職の何から始めればいいかわからない
3. スキルなしでも転職できる？
4. 通勤が体的につらい場合、転職先をどう選べばいい？
5. 在宅ワークに転職するには何が必要？
6. 資格を取ってから転職するのは遠回り？
7. 発達障害・体調不良があっても転職できる？
8. 転職エージェントは怖い・強引というイメージがあるけど大丈夫？
9. フリーランスは不安定すぎる？会社員との比較
10. AI時代に求められるスキルとは？未経験から目指せる？
"""

KEYWORD = "転職したいけど不安 何から始める"
TITLE   = "転職したいけど不安で踏み出せない人へ｜何から始めるか、体験談をもとに解説"

check_stop()

log.info("=" * 60)
log.info(f"看板記事生成開始（はた楽ナビ）: 「{TITLE}」")
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

log.info(f"記事生成完了: 「{article['title']}」 コンテンツ長: {len(article.get('content',''))   :,}字")

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
