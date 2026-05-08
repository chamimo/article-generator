#!/usr/bin/env python3
"""
看板記事生成スクリプト - はた楽ナビ
「社会復帰 支援」
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

from modules import article_generator as _ag
_ag._ARTICLE_STRUCTURE[12000] = (20, 26, 10, 12, 20000)

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
        "target":        "社会復帰を目指す人・ブランクがある人・精神的・身体的な理由で仕事を休んでいた人・発達障害などで就職に不安がある人",
        "writing_taste": (
            "読者の不安・迷い・自己否定感に完全に寄り添う、温かく柔らかいトーン。"
            "「焦らなくて大丈夫」「不安に思うのは当然です」「まず話を聞いてもらうだけでいい」という言葉を自然に使う。"
            "背中を押す際も「無理しなくていい」「自分のペースで」という表現に徹する。"
            "「絶対に就職できる」「今すぐ申し込んで」のような押しつけ・誇大表現は絶対に禁止。"
            "結論が明確で実用的。比較・メリット・デメリット・向いている人をはっきり示す。"
            "NG表現：〜してみてください／〜がおすすめです／ぜひ〜"
        ),
        "genre_detail":  "就労支援・社会復帰・転職・IT就労・障害者雇用",
        "search_intent": "Feel（不安・悩みに寄り添う）＋Do（具体的な支援先を探す）",
    },
)

asp_list = [
    {"name": "Neuro Dive",            "url": "https://hataraku-navi.com/neuro_dive", "priority": 1,
     "description": "IT・データサイエンス特化の就労移行支援。在宅対応・障害のある方向け。"},
    {"name": "ニューロダイブ",          "url": "https://hataraku-navi.com/neuro_dive", "priority": 1,
     "description": "IT・データサイエンス特化の就労移行支援。在宅対応・障害のある方向け。"},
    {"name": "atGP",                   "url": "https://hataraku-navi.com/atgp",       "priority": 1,
     "description": "障害者向け転職エージェント。非公開求人多数・専任サポート。"},
    {"name": "atGPジョブトレ IT・Web", "url": "https://hataraku-navi.com/atgp_job",  "priority": 2,
     "description": "IT・Webスキルを訓練してから就職を目指すプログラム。"},
    {"name": "ウズウズIT",             "url": "https://hataraku-navi.com/uzuuzu_it", "priority": 2,
     "description": "未経験からITエンジニアを目指せる就職支援スクール。"},
    {"name": "転職AGENT Navi",         "url": "https://hataraku-navi.com/agent-navi","priority": 2,
     "description": "転職エージェント。社会復帰・ブランクありの相談も対応。"},
]

KEYWORD = "社会復帰 支援"
TITLE   = "社会復帰を支援してくれるサービス・制度まとめ｜不安な方へ一歩ずつ解説"

OUTLINE = """\
【看板記事・読者の不安に完全に寄り添う構成・必ず全項目を守ること】

検索意図: Feel（社会復帰したいけど不安・怖い・一歩が踏み出せない）＋Do（自分に合う支援先を見つける）

■ タイトル（固定）
社会復帰を支援してくれるサービス・制度まとめ｜不安な方へ一歩ずつ解説

■ 導入（350字前後）
- 「社会復帰したいけど、どこに相談すればいいかわからない」「自分みたいな人でも支援してもらえるの？」という気持ちから書き出す
- 社会復帰への不安は当然・恥ずかしいことではないという共感
- この記事では支援の種類・選び方・具体的なサービスを丁寧に解説する
- Neuro Dive へのリンクを自然な形で1回目に挿入

■ H2: 社会復帰への不安――「こんな状態の自分でも大丈夫？」
  H3: ブランクが長いと不利になるの？
    - ブランクは「休養が必要だった証拠」で恥ずかしいことではない
    - 就労支援では長期ブランクの人のサポートが専門的に整っている
    - 「1年以上のブランクがある方専門」のサービスも存在する
  H3: 精神疾患・発達障害があっても支援を受けられる？
    - うつ・適応障害・発達障害（ASD・ADHD）・統合失調症などに対応した専門支援が多数ある
    - 障害者手帳がなくても相談できる窓口が増えている
    - 診断書があればより細かいサポートが受けやすくなる
  H3: 「働けるか不安」な人が多い――焦らなくていい理由
    - 最初から「就職」を目指す必要はない・まず「生活リズムを取り戻す」から始める支援もある
    - 支援機関のほとんどは「まず見学・相談だけ」でOK
    - 焦りが一番の敵・自分のペースで動けばいい

■ H2: 社会復帰を支援する制度・機関の種類と選び方
  H3: 就労移行支援とは（原則2年・訓練から就職までサポート）
    - 障害や病気がある方向け・原則無料または低額（収入に応じた自己負担）
    - 「働くためのスキル訓練＋就職活動の支援」を一体的に行う
    - 利用期間中の生活費・障害年金との組み合わせについても解説
  H3: 就労継続支援A型・B型との違い（雇用型か訓練型か）
    - A型は雇用契約あり・B型は雇用契約なし
    - 「まずはB型から」「A型で実績を積んでからオープン就労」という流れも
  H3: ハローワークの「専門援助窓口」（無料・全国対応）
    - 障害のある方・就職困難者向けの専門窓口
    - 「担当者に話を聞いてもらう」だけでも次の一歩が見えやすい
    - 地域障害者職業センター・就業・生活支援センターとの連携も紹介
  H3: 民間の就労支援・転職エージェントという選択肢
    - 障害者雇用専門の転職エージェントは相談・登録が無料
    - 非公開求人・在宅ワーク・フレックスなど働きやすい求人が多い
    - 「まず話を聞いてもらうだけ」でも整理になる

■ H2: Neuro Dive（ニューロダイブ）― IT特化の就労移行支援
（社会復帰を目指す方に特におすすめしたいサービス）
  H3: Neuro Dive とはどんなサービスか
    - IT・データサイエンスに特化した就労移行支援事業所
    - 発達障害・精神障害・身体障害のある方が主な対象
    - 在宅での訓練・就労も視野に入れられる（通所が難しい方でもOK）
    ★Neuro Dive の CTA挿入
  H3: Neuro Dive のメリット（どんな人に向いているか）
    - ITスキル（Python・データ分析・AIツール活用など）を実践的に学べる
    - 就職実績が豊富で、IT企業への就職サポートが手厚い
    - 在宅勤務・フレックス対応の求人とマッチングしやすい
    - 「社会復帰したいけど通勤が不安」という方に特に向いている
  H3: Neuro Dive のデメリット・向いていない人（正直に）
    - ITに全く興味がない・苦手意識が強い方には向かない可能性がある
    - 訓練期間が数ヶ月以上かかる（すぐに働きたい方には長く感じるかも）
    - 「IT＋障害者雇用」という軸以外の就職先は案件が少ない場合もある
  H3: Neuro Dive の利用料金・費用（安心してほしい）
    - 就労移行支援は原則無料または低額（前年度の世帯収入に応じた自己負担）
    - 生活費が不安な方は障害年金・傷病手当金との組み合わせが可能
    - まずは無料見学・無料相談から始められる
    ★Neuro Dive の CTA2回目挿入

■ H2: atGP ― 障害者向け転職エージェント（就職実績豊富）
  H3: atGP の特徴と向いている人
    - 障害者雇用に特化した転職支援・非公開求人多数
    - うつ・発達障害・身体障害など幅広い障害種別に対応
    - 「就労移行支援より早く就職したい」「ある程度動ける状態にある」方向け
    ★atGP の CTA挿入
  H3: atGPジョブトレ IT・Web という選択肢
    - IT・Webスキルを訓練してから安定就労を目指すプログラム
    - 障害のある方・体調に不安のある方にも対応
    ★atGPジョブトレ の CTA挿入

■ H2: 社会復帰の流れ ― 「まず何から始めればいいか」をステップで解説
  H3: ステップ1：自分の状態を整理する（今どんな状態か）
    - 医療的なサポートが必要かどうか・主治医への相談
    - 「働ける状態かどうか」を自分だけで判断しなくていい
  H3: ステップ2：相談窓口に一度だけ連絡してみる
    - 相談するだけ・見学するだけでOK・「登録＝すぐ就職活動」ではない
    - まずNeuro Dive・atGP・ハローワーク専門窓口のどれかに問い合わせてみる
    ★Neuro Dive の CTA3回目挿入
  H3: ステップ3：訓練・準備期間を経て就職活動へ
    - 就労移行支援の場合は数ヶ月〜2年かけてスキルと体力を整える
    - 面接対策・履歴書作成・模擬面接まで支援してもらえる
  H3: ステップ4：就職後のフォローも大切
    - 定着支援・就労定着支援事業（最長3年間）で就職後もサポートが続く
    - 「続けられるか不安」という気持ちは就職後も相談できる

■ H2: 社会復帰を成功させるためのヒント（体験談・アドバイス）
  H3: 「焦らないこと」が最大のコツ
    - 最初から完璧を目指さなくていい・できることから少しずつ
    - 社会復帰に「正解の速度」はない
  H3: 支援機関を複数見学して自分に合うところを選ぶ
    - 一つの支援機関だけで決めなくていい・見学は無料・複数比較がおすすめ
    - 「スタッフと話してみて安心できるかどうか」が大事
  H3: 家族・パートナーへの説明と協力のお願い
    - 支援を使うことを家族に言えないケースもある
    - 「就職の準備をしている」という伝え方だけでも十分
    - 家族説明会がある事業所もある

■ まとめ
  H3: 社会復帰の第一歩は「一度相談してみること」
    - 不安は当然・でも動くことで少しずつ見えてくるものがある
    - 特にIT×就労支援に興味があるなら Neuro Dive に相談してみてほしい
    ★Neuro Dive の CTA4回目・まとめ挿入

■ FAQ（12問・各250字以上で丁寧に回答）
1. 社会復帰を支援してくれる機関はどこに相談すればいい？
2. 就労移行支援は無料で使えるの？費用はいくらかかる？
3. 障害者手帳がなくても就労支援を使える？
4. 社会復帰まで何ヶ月くらいかかるの？
5. 精神疾患（うつ・適応障害）がある場合、どこに相談すべき？
6. 発達障害（ADHD・ASD）がある場合、どんな支援がある？
7. ブランクが3年以上あっても就職できる？
8. 就労移行支援中の生活費はどうすればいい？
9. 在宅・リモートで社会復帰できる方法はある？
10. 家族に言わずに支援を受けることはできる？
11. Neuro Dive は精神障害・発達障害のある人でも利用できる？
12. 社会復帰後、仕事が続かないか不安。定着支援はある？
"""

import json as _json
_CACHE = os.path.join(os.path.dirname(__file__), "_cache_shakai_fukki_hataraku.json")

check_stop()

log.info("=" * 60)
log.info(f"看板記事生成開始（はた楽ナビ）: 「{TITLE}」")
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
        target_length=12000,
        forced_title=TITLE,
        asp_list=asp_list,
        enable_fact_check=True,
        article_type="monetize",
    )
    with open(_CACHE, "w", encoding="utf-8") as f:
        _json.dump(article, f, ensure_ascii=False, indent=2)
    log.info(f"[cache] 記事を保存しました: {_CACHE}")

log.info(f"記事生成完了: 「{article['title']}」 コンテンツ長: {len(article.get('content', '')):,}字")

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
