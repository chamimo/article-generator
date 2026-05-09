#!/usr/bin/env python3
"""
不登校 通信教育 おすすめ 記事生成スクリプト - オンライン学習ナビ
すらら導線最強・体験談ベース
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
        "target":        "不登校の子どもを持つ保護者・自宅学習の通信教育を探している親",
        "writing_taste": (
            "やさしく丁寧で安心感のある文章。信頼性を重視し初心者でも理解できる構成。"
            "比較・メリット・デメリットをバランスよく提示。"
            "不安を解消し納得して選べるトーン。"
            "体験談を前面に出し、EEATを意識した一人称目線の記述も交える。"
            "NG表現：〜してみてください／〜がおすすめです／ぜひ〜"
        ),
        "genre_detail":  "通信教育・不登校支援・タブレット学習・オンライン学習",
        "search_intent": "Do（比較・検討）＋Feel（不安・悩みに寄り添う）＋Buy（サービス選び）",
    },
)

asp_list = [
    {"name": "すらら",  "url": "https://web-study1.com/surara", "priority": 1,
     "description": "不登校・発達障害の子にも対応。ゲーミフィケーション×AIで先取り・さかのぼり学習が可能。"},
]

KEYWORD = "不登校 通信教育 おすすめ"
TITLE   = "不登校の子に通信教育は有効？すらら体験談とおすすめ教材を徹底解説"

TESTIMONIAL = """\
【体験談（実際のユーザー声・EEATとして必ず自然に組み込む）】

コロナ禍やさまざまな事情が重なり、子どもの学習について悩んでいた時期に、すららを始めてみました。

実際に使ってみて特に良かったと感じたのは、「すららコーチ」の存在です。定期的にメッセージを送ってくださったり、「最近頑張っていますね」と声をかけてくださったりして、子どもだけでなく親の私自身も支えられているような感覚がありました。もちろん担当するコーチによって違いはあると思いますが、我が家は本当に良い先生にマッチングしていただけたなと感謝しています。

また、すららはゲーミフィケーション要素がとても強く、勉強を頑張ることで報酬がもらえたり、イベントが開催されたりと、ゲーム感覚で学習を進められる仕組みがありました。「すらカップ」などのイベントでは「ここまで達成するとプレゼントがもらえる」といった目標があり、子どものやる気につながっていたと思います。

さらに印象的だったのは、「ここまでやったら終了」という感じではなく、自然と次へ次へ進みたくなる設計になっていたことです。他のタブレット教材だと「今日はここまでで終わり」という区切りがはっきりしているものも多いのですが、すららは気づいたらかなり長時間集中して取り組んでいた、ということがよくありました。

「先取り学習」と「さかのぼり学習」ができるところも大きかったです。実際に我が家では、小学校5年生の段階で中学2年生までの数学を進めることができました。得意な科目はどんどん先へ進められるので、子どもの「もっとやりたい」という気持ちを止めなくて済んだのは大きなメリットでした。逆に苦手な単元については、学年を戻って復習できる「さかのぼり学習」が役立ちました。

ただ、全体的にテンポは少しゆっくりめに感じる部分もありました。もっとテンポよくどんどん進めたいタイプの子にとっては、少しイライラしてしまうこともあるかもしれません。それでも、子どもが「勉強＝つらいもの」ではなく、「ゲーム感覚で続けられるもの」と感じられたのは、すららならではの良さだったと思います。
"""

OUTLINE = f"""\
【記事構成・必ず全項目を守ること】

■ タイトル（固定）
不登校の子に通信教育は有効？すらら体験談とおすすめ教材を徹底解説

■ 読者像
- 子どもが不登校になり学習が止まっていることに不安を感じている保護者
- 学校に行けない期間でも「家で無理なく勉強を続けさせてあげたい」という親心
- 通信教育・タブレット学習を検討しているが何を選べばいいかわからない

■ 導入（350字前後）
- 「学校に行けない日が続いているけど、勉強はどうしよう」という親の不安から書き出す
- 不登校でも通信教育を上手く使えば学習を継続できる・実際に成果が出ている事例がある
- この記事ではすらら利用者の体験談をもとに、不登校の子に合う通信教育の選び方を解説する
- すらら への1回目リンク挿入

{TESTIMONIAL}

■ H2: 不登校の子に通信教育が向いている理由
  H3: 自分のペースで学べる（登校プレッシャーがない）
    - 時間割・曜日・場所を選ばず自分のタイミングで学習できる
    - 「今日はここだけやろう」という小さな達成が積み重なる
  H3: 学習の遅れを取り戻しやすい（さかのぼり学習）
    - 不登校期間中に生じた抜けをピンポイントで補える
    - 学年に関係なく苦手単元まで戻れるサービスが不登校の子に特に効果的
  H3: 不登校特例・出席認定との組み合わせ
    - 文部科学省の通知で「ICT学習を出席扱いにできる」制度がある
    - 条件・手続き・学校との連携方法を具体的に解説
  H3: 親の心理的な負担も軽減できる
    - 「子どもが家で何もしていない」という罪悪感・焦りを和らげる
    - 学習の記録・進捗が可視化されることで親も安心できる

■ H2: すらら ― 不登校の子に特に向いている理由（体験談ベース）
（※以下の構成に必ず体験談の内容を自然に組み込むこと）
  H3: すらら とはどんな通信教育か
    - アダプティブラーニング（AI個別最適化）×ゲーミフィケーションの特徴
    - 小学生・中学生・高校生に対応、不登校・発達障害サポートも充実
    - 出席扱い制度への対応実績
    ★すらら の CTA挿入（1回目）
  H3: すららコーチのサポート体制（体験談：「親の私自身も支えられた」）
    - 専任コーチが定期的にフォロー・励ましのメッセージを送ってくれる
    - 子どもだけでなく保護者へのサポートもある点が他サービスと異なる
    - 体験談を引用しながら「コーチの存在が継続のカギ」であることを伝える
  H3: ゲーミフィケーションで勉強嫌いでも続けられる（体験談：「すらカップ」）
    - ポイント・イベント・ご褒美でゲーム感覚で学習できる仕組み
    - 「ここまで達成するとプレゼント」という目標設定がやる気を引き出す
    - 気づいたら長時間集中していた、という体験談エピソードを具体的に紹介
  H3: 先取り学習で得意をとことん伸ばせる（体験談：小5で中2数学を達成）
    - 学年の壁がなく得意科目はどんどん先へ進められる
    - 実際に小学5年生が中学2年生の数学まで先取りできた実例を具体的に記述
    - 「もっとやりたい」という気持ちをブレーキせずに伸ばせる環境
  H3: さかのぼり学習で苦手を丁寧につぶせる
    - 学習のつまずき箇所まで自動で戻ってくれるAI機能
    - 不登校で学習空白がある子どもにこそ必要な機能
  H3: すらら のデメリット・向いていない子（正直に）
    - テンポがゆっくりめで、テキパキ進めたい子にはストレスになることも
    - 「もっとテンポよく進めたい」タイプの子への注意点
    - 向いている子・向いていない子をはっきり整理する
    ★すらら の CTA挿入（2回目）

■ H2: すらら の料金・費用・無料体験について
  H3: 月額料金の目安（小・中・高別）
    - 各学年の月額費・入会金・教材費を具体的に記載
    - 年間費用に換算した場合のコスト感
  H3: 無料体験・お試し期間の活用方法
    - まず無料体験で子どもに合うか確認してから入会できる安心感
    - 無料体験の申し込み方法・期間・できること
    ★すらら の CTA挿入（3回目・まとめ前）

■ H2: 不登校向け通信教育を選ぶときのポイント
  H3: 学習サポート体制（コーチ・先生のフォローがあるか）
    - コーチ・担任・メンタルサポートの有無で継続率が大きく変わる
  H3: さかのぼり学習・先取り学習への対応
    - 学校の進度に縛られず子どものペースで学べるかどうか
  H3: 出席扱い制度に対応しているか
    - 文科省通知対応・学校との連携実績があるサービスを選ぶと安心
  H3: 子どもが「楽しい」と感じる設計かどうか
    - 継続できるかは「好きかどうか」が一番大事
    - 無料体験で子ども自身に触れさせてから決めるのがベスト

■ まとめ
  H3: 不登校の子にこそ「自分のペースで学べる通信教育」が力になる
    - 勉強の遅れへの不安は通信教育で十分カバーできる
    - すらら のコーチ・ゲーミフィケーション・先取り学習が特にこの状況に合っている
    - まずは無料体験から始めてみることをすすめる（押しつけにならない自然なトーンで）
    ★すらら の CTA挿入（まとめ・4回目）

■ FAQ（10問・各250字以上で丁寧に回答）
1. 不登校でも通信教育で出席扱いになる？
2. すらら は不登校の子でも続けられる？
3. 通信教育はどの学年から始めるのがいい？
4. 小学生・中学生・高校生でおすすめは違う？
5. 発達障害（ADHD・ASD）がある子にも通信教育は使える？
6. すらら の月額費用はいくら？家計への負担は？
7. 学習習慣がない子でも通信教育で続けられる？
8. 紙の教材とタブレット教材、どちらが不登校の子に向いている？
9. すらら コーチとはどんな存在？どんなサポートをしてくれる？
10. 通信教育だけで学習の遅れを取り戻すことはできる？
"""

import json as _json
_CACHE = os.path.join(os.path.dirname(__file__), "_cache_futoko_tsushin.json")

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
