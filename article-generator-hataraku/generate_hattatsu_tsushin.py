#!/usr/bin/env python3
"""
発達障害 通信教育 おすすめ 記事生成スクリプト - オンライン学習ナビ
すらら導線最強・スタディサプリ/スマイルゼミ体験談ベース
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
        "target":        "発達障害（ADHD・ASD・LD）の子どもを持つ保護者・自宅学習の通信教育を探している親",
        "writing_taste": (
            "やさしく丁寧で安心感のある文章。信頼性を重視し初心者でも理解できる構成。"
            "比較・メリット・デメリットをバランスよく提示。"
            "不安を解消し納得して選べるトーン。"
            "体験談を前面に出し、EEATを意識した一人称目線の記述も交える。"
            "NG表現：〜してみてください／〜がおすすめです／ぜひ〜"
        ),
        "genre_detail":  "通信教育・発達障害支援・タブレット学習・オンライン学習",
        "search_intent": "Do（比較・検討）＋Feel（不安・悩みに寄り添う）＋Buy（サービス選び）",
    },
)

asp_list = [
    {"name": "すらら",       "url": "https://web-study1.com/surara",                "priority": 1,
     "description": "無学年式AI学習。ゲーミフィケーション×すららコーチのサポートで発達障害・不登校の子にも対応。声優ナレーションのアニメ教材で楽しく学べる。"},
    {"name": "スマイルゼミ", "url": "https://web-study1.com/smile-zemi",            "priority": 2,
     "description": "シンプル設計でサクサク進む。余計な装飾がなくやるべきことだけに集中できる環境。集中力が続きにくい子にも向いている。"},
    {"name": "スタディサプリ", "url": "https://web-study1.com/studysapuri-chugaku", "priority": 2,
     "description": "コーチングコースで現役大学生が友達感覚でサポート。外部との接点がやる気につながる子に。月額が安くコスパ抜群。"},
]

KEYWORD = "発達障害 通信教育 おすすめ"
TITLE   = "発達障害の子に通信教育は有効？すらら・スマイルゼミ・スタディサプリを体験談で比較"

TESTIMONIAL = """\
【体験談（実際のユーザー声・EEATとして必ず自然に組み込む）】

すららについては、コーチに励ましてもらえたことがとても大きかったです。「最近がんばっていますね」「ここまで進んだんですね」と声をかけてもらえるだけで、子どもの顔が変わるのがわかりました。発達障害の子はどうしても「自分はできない」という気持ちを抱えやすいのですが、コーチという存在がいてくれることで、親子ともに安心感が違いました。オンライン学習でありながら、コーチの指導があることで孤独感が薄れるのもよかったです。

また、すららのゲーミフィケーションや先取り学習の仕組みは、やる気につながりました。「すらカップ」などのイベントで目標ができると、自然と集中して取り組む姿が見られました。アニメのキャラクターや声優さんが楽しい雰囲気を出してくれていて、発達障害の子でも「勉強＝楽しい」と感じられる演出になっていたと思います。

一方で、スタディサプリのコーチングコースも試しました。現役の大学生の方が担当してくださり、趣味の話なども交えながら友達感覚で接してくれたことが、子どもにとっては新鮮だったようです。「外の人と話す」という経験自体が刺激になったようで、やる気のスイッチが入ることもありました。ただ、教材の難易度設定が学年固定なので、さかのぼり学習が必要な子には向きにくいと感じました。

スマイルゼミは、余計な装飾やキャラクターが少なく、やるべき課題だけがシンプルに表示される設計が、うちの子には合っていました。刺激が多いとパニックになりやすいタイプの子には、こちらのほうが集中しやすいと思います。実際に喜んで取り組んでいましたが、さかのぼり学習や先取り学習の自由度が低く、「もっと先に進みたい」という場面では物足りなさを感じることもありました。

理想をいえば、すららのような無学年制・コーチサポートと、スマイルゼミのようなシンプルなUIが組み合わさったサービスがあればよかったのですが、それぞれ特長が違うので、お子さんのタイプに合わせて選ぶのがいちばんだと思っています。

（※すらら体験談の詳細はこちらの記事でも紹介しています → 不登校の子の通信教育体験談記事へ内部リンク）
"""

OUTLINE = f"""\
【記事構成・必ず全項目を守ること】

■ タイトル（固定）
発達障害の子に通信教育は有効？すらら・スマイルゼミ・スタディサプリを体験談で比較

■ 読者像
- 子どもに発達障害（ADHD・ASD・LD）があり、学習の遅れや学習嫌いに悩んでいる保護者
- 学校の授業についていけない、集中力が続かない子どもに合う教材を探している親
- 通信教育・タブレット学習を検討しているが発達障害に対応しているか不安な人

■ 導入（350字前後）
- 「発達障害の子でも、通信教育で本当に学べるの？」という親の不安から書き出す
- 発達障害の特性（注意散漫・過集中・感覚過敏など）に合った学習方法なら成果が出ている
- この記事では実際の体験談をもとに、発達障害の子に向く通信教育の選び方を解説する
- すらら への1回目リンク挿入

{TESTIMONIAL}

■ H2: 発達障害の子に通信教育が向いている理由
  H3: 自分のペース・自分のタイミングで学べる
    - 時間割や登校プレッシャーがなく、調子のいいときだけ学習できる
    - 短時間・細切れでも積み上がるゲーム型設計が発達障害の特性とマッチ
  H3: さかのぼり学習で「わからない」を放置しない
    - 学年に縛られず、つまずいた単元まで戻れる無学年式の重要性
    - 発達障害で学習空白がある子ほど「さかのぼり」が有効
  H3: 視覚・音・ゲームで学習意欲を引き出せる
    - アニメ・声優・エフェクトで「勉強＝楽しい」に変えるゲーミフィケーションの効果
    - 発達障害の子は「好き」にハマると集中力が爆発するタイプが多い
  H3: コーチ・メンターとの接点が孤立感を防ぐ
    - 学校に行けない・友達がいない時期でも「外の人との関係」が自己肯定感を守る
    - コーチからの声かけや褒め言葉が継続の原動力になる

■ H2: すらら ― 発達障害の子に特に向いている理由（体験談ベース）
（※以下の構成に必ず体験談の内容を自然に組み込むこと）
  H3: すらら とはどんな通信教育か
    - 無学年式AIアダプティブラーニング×ゲーミフィケーションの特徴
    - 小学生・中学生・高校生に対応、発達障害・不登校サポートも充実
    - 声優ナレーションのアニメ教材で視覚・聴覚から楽しく学べる設計
    ★すらら の CTA挿入（1回目）
  H3: すららコーチのサポートで安心感が段違い（体験談より）
    - 専任コーチが定期的に励ましのメッセージを送ってくれる
    - 「最近がんばっていますね」の一言が子どもの表情を変えた体験談を具体的に紹介
    - 発達障害の子は自己否定感が強い→コーチの声かけが自己肯定感の支えになる
    - 親へのサポートもある点が他サービスと異なる
  H3: ゲーミフィケーション×アニメで「勉強嫌い」が変わる（体験談より）
    - ポイント・イベント・ご褒美システムで学習をゲーム感覚に変える仕組み
    - 発達障害のお子さんが喜ぶアニメ演出・声優ナレーションの魅力
    - 「すらカップ」などのイベントで自然と集中・長時間学習が生まれた体験談エピソード
  H3: 先取り・さかのぼり学習で発達障害の凸凹に対応
    - 得意科目は学年関係なくどんどん先に進める（例：小5で中2数学）
    - 苦手単元はAIが自動でさかのぼって補修してくれる
    - 発達障害の「学習の凸凹」に最も対応している仕組みである理由を解説
  H3: すらら のデメリット・向いていない子（正直に）
    - テンポがゆっくりめで、テキパキ進めたい子にはストレスになることも
    - シンプルな画面設計を好む子には視覚的な演出が多く感じる場合もある
    - 向いている子・向いていない子をはっきり整理する
    ★すらら の CTA挿入（2回目）

■ H2: スマイルゼミ ― シンプルUIで集中できる子向け（体験談ベース）
  H3: スマイルゼミ の特徴と発達障害の子への向き・不向き
    - 余計な装飾がなく、やるべきことだけがシンプルに表示される設計
    - 感覚過敏・刺激過多になりやすい子には集中しやすい環境
    - 体験談：「シンプルなUIが合っていて喜んで取り組んでいた」エピソードを紹介
  H3: スマイルゼミ の注意点
    - さかのぼり学習・先取り学習の自由度が低く、学習空白がある子には制限を感じることも
    - 「もっと先に進みたい」タイプの子には物足りなさが出る場合がある
    ★スマイルゼミ の CTA挿入

■ H2: スタディサプリ ― コーチングコースで「外の人とのつながり」を作る（体験談ベース）
  H3: スタディサプリ コーチングコースの特徴
    - 現役大学生がコーチとして趣味の話も交えながら友達感覚でサポート
    - 「外の人と話す」体験がやる気のスイッチになる子もいる
    - 体験談：コーチとの対話がやりがいにつながったエピソードを紹介
  H3: スタディサプリ の注意点
    - 学年固定の教材設計でさかのぼり学習が難しい
    - 動画授業メインなので、映像に集中しにくい特性の子には合わない場合も
    ★スタディサプリ の CTA挿入

■ H2: 発達障害の子に合う通信教育を選ぶポイント
  H3: さかのぼり学習・先取り学習に対応しているか
    - 学習の凸凹に対応するためには「無学年式」がベスト
  H3: コーチ・サポート体制があるか
    - 継続のカギは「誰かに見てもらえている」安心感
  H3: 視覚・聴覚刺激の量を子どもに合わせて選ぶ
    - ゲーム・アニメが好きな子 → すらら型
    - シンプルな環境が落ち着く子 → スマイルゼミ型
  H3: 無料体験で子ども自身に選ばせる
    - 親が決めるより、子どもが「やってみたい」と言えるかどうかが継続の分かれ目

■ まとめ
  H3: 発達障害の子こそ「特性に合った通信教育」で可能性を広げられる
    - 3サービスの向き・不向きを簡潔に整理
    - すらら が総合的に発達障害の子のニーズに最も応えている理由を自然なトーンで伝える
    - まずは無料体験から（押しつけにならない自然なトーンで）
    ★すらら の CTA挿入（まとめ・最終）

■ FAQ（10問・各250字以上で丁寧に回答）
1. 発達障害の子でも通信教育で学力は上がる？
2. ADHD・ASD・LDでは向いている通信教育が違う？
3. すらら は発達障害の公式サポートがある？
4. 学習障害（LD）の子に通信教育は有効？
5. 通信教育で集中力が続かない子はどうすれば？
6. 発達障害の子に紙教材とタブレット教材どちらが向いている？
7. 不登校と発達障害が重なっている場合の教材選びは？
8. すらら の料金・費用は？発達障害向け割引はある？
9. スマイルゼミは発達障害の子に向いている？
10. 通信教育だけで学習の遅れを取り戻すことはできる？
"""

import json as _json
_CACHE = os.path.join(os.path.dirname(__file__), "_cache_hattatsu_tsushin.json")

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
