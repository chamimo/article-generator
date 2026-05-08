#!/usr/bin/env python3
"""
保育士から異業種転職記事生成スクリプト（使い捨て）
- ほいく畑・保育エイド・保育バランス・保育メトロ を含む
- 生成後 post 512 を上書き更新する
"""
import sys, os, logging, json, base64, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

from modules import article_generator as _ag
_ag._ARTICLE_STRUCTURE[9000] = (14, 18, 10, 12, 20000)

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
        "target":        "保育士から転職・異業種キャリアチェンジを考えている20〜40代",
        "writing_taste": (
            "経験者の本音・リアル。転職を複数回経験したWeb担当者の視点で、失敗談も交えた共感重視の文体。"
            "結論が明確で実用的。信頼感があり論理的。比較・メリット・デメリット・向いている人をはっきり示す。"
            "読者が迷わず行動できるよう背中を押すトーン。"
            "NG表現：〜してみてください／〜がおすすめです／ぜひ〜"
        ),
        "genre_detail":  "保育士転職・キャリアチェンジ・異業種転職",
        "search_intent": "Do（比較・検討）＋Feel（悩み・不安に寄り添う）",
    },
)

asp_list = [
    {"name": "ほいく畑",     "url": "https://hataraku-navi.com/hoikubatake",  "priority": 1,
     "description": "保育専門求人サイト。保育業界で働きたい方におすすめ。"},
    {"name": "保育エイド",   "url": "https://hataraku-navi.com/hoiku-aid",    "priority": 2,
     "description": "人間関係を重視して職場を探したい方に。"},
    {"name": "保育バランス", "url": "https://hataraku-navi.com/hoiku-balance","priority": 2,
     "description": "働きやすさ重視で探したい方におすすめ。"},
    {"name": "保育メトロ",   "url": "https://hataraku-navi.com/hoiku-metro",  "priority": 2,
     "description": "通いやすい保育求人を探したい方におすすめ。"},
]

KEYWORD = "保育士 転職 異業種"
TITLE   = "保育士から異業種転職は可能？おすすめ職種7選と成功のコツを徹底解説"
UPDATE_POST_ID = 512  # 既存記事を上書き更新

OUTLINE = """\
【記事構成・必ず全項目を守ること】

■ タイトル（固定）
保育士から異業種転職は可能？おすすめ職種7選と成功のコツを徹底解説

■ 導入（300字前後）
- 「保育士から異業種転職ってできるの？」という疑問に直接答える書き出し
- 保育士が培ったスキル（コミュニケーション・忍耐力・マルチタスク）は異業種でも高く評価される
- 一方で「異業種を目指すか、保育士として転職するか」迷っている読者にも両方の選択肢を示す

■ H2: 保育士が異業種転職を考えるきっかけと本音
  H3: 給与・待遇への不満（低賃金・残業代なし）
    - 保育士の平均年収は全職種平均より低い現実
    - 「もっと稼ぎたい」という気持ちは正当な転職動機
  H3: 人間関係のストレス（職場の閉鎖性）
    - 女性が多い職場特有の人間関係の難しさ
    - 保護者対応・上司・同僚との三重ストレス
  H3: 体力的な限界（子どもと向き合う消耗感）
    - 腰痛・持病・体力低下で続けられなくなるケース
    - 30代以降は特にキャリアの転換期として意識しやすい
  H3: 「このまま保育士でいいのか」というキャリア不安
    - スキルアップの機会が少ない・昇給が見えない
    - 別の分野で自分の可能性を試したいという気持ち

■ H2: 保育士から異業種転職で活かせるスキル・強み
  H3: コミュニケーション能力（保護者・子ども・スタッフ）
    - 相手の気持ちを読む力・わかりやすく説明する力は全業種で評価される
  H3: マルチタスク・瞬時の問題解決力
    - 複数の子どもを同時に見る経験は、営業・医療・サービス業で活きる
  H3: 責任感・忍耐力・気配り
    - 命を預かる仕事で培った責任感は異業種でも大きな強みになる
  H3: リーダーシップ・後輩指導経験
    - 主任・クラスリーダー経験があれば管理職候補にもなれる

■ H2: 保育士から異業種転職 おすすめ職種7選
  H3: ① 一般事務・医療事務（未経験歓迎が多い定番ルート）
    - 保育士の記録・書類作成スキルがそのまま活きる
    - 医療事務は資格を取るとさらに有利
  H3: ② 営業職（コミュ力を活かして稼げる職種）
    - 保護者対応の経験が「人の話を聞く力」として評価される
    - インセンティブ次第で収入アップが期待できる
  H3: ③ 介護・福祉系（保育と近い資格・経験を活用）
    - 初任者研修（旧ホームヘルパー2級）があれば即戦力
    - 社会的需要が高く安定している
  H3: ④ 教育系（塾講師・学童・習い事指導）
    - 子どもとの関わり経験をそのまま活かせる準異業種
    - 正社員・パート・講師業など働き方の幅が広い
  H3: ⑤ Webライター・コンテンツ制作
    - 保育知識×文章力で育児・教育系メディアに強い
    - 在宅でも働ける・副業スタートも可能
  H3: ⑥ 販売・接客・ホテル・ブライダル（サービスのプロへ）
    - おもてなしの心・笑顔・コミュニケーション力は接客業でも最高の武器
  H3: ⑦ ITエンジニア・プログラマー（未経験からでも挑戦できる時代）
    - スクール+転職エージェントのセットで未経験入社の実績多数
    - 将来的に在宅・フリーランス・リモートワークへの道も開ける

■ H2: 保育士から異業種転職を成功させるコツ
  H3: 「保育士の強み」を職務経歴書で言語化する
    - 「子どもの世話をしていた」ではなく「30名の安全管理・コミュニケーション設計に従事」と書く
  H3: 未経験・第二新卒・異業種歓迎の求人を狙う
    - 業界・職種未経験OKの求人は思った以上に多い
    - 転職サイトの検索フィルターで絞る方法
  H3: 転職エージェントに相談して非公開求人を探す
    - エージェントは無料で使えて、異業種転職の実績が豊富なところが多い
    - 「保育士から転職したい」と明示して相談するのがポイント
  H3: 転職活動の時期は「余裕があるうちに」動く
    - 燃え尽きてから探すより、在職中の転職活動が成功率が高い
    - まず情報収集だけでもOK

■ H2: 「保育士として別の職場に転職」も選択肢のひとつ
（環境・人間関係を変えるだけで解決するケースも多い）
  H3: ほいく畑 ― 保育業界最大級の専門求人サイト
    - 保育士・幼稚園教諭・保育補助など保育専門の求人に特化
    - 非公開求人・好条件の職場情報が豊富
    - 「今より良い保育園に移りたい」なら最初に使いたいサービス
    ★ほいく畑のCTA挿入
  H3: 保育エイド ― 人間関係重視で職場を選びたい方に
    - 職場の雰囲気・スタッフ間の関係性にフォーカスした求人情報
    - 「前の職場で人間関係に疲れた」という人に特に向いている
    ★保育エイドのCTA挿入
  H3: 保育バランス ― 働きやすさ重視で探したい方に
    - 残業少なめ・休日取得しやすい・シフト融通が利く求人に強み
    - プライベートを大切にしながら保育士として働きたい方向け
    ★保育バランスのCTA挿入
  H3: 保育メトロ ― 通いやすい保育求人を探したい方に
    - 最寄り駅・路線からアクセスの良い職場を探せる
    - 「通勤が体の負担になっている」という方には特におすすめ
    ★保育メトロのCTA挿入

■ H2: 異業種転職 vs 保育士として転職 ― どちらが自分に合うか
  H3: こんな人は「異業種転職」が向いている
    - 収入を大幅に上げたい・保育以外のスキルを身につけたい・在宅で働きたいなど
  H3: こんな人は「保育士のまま転職」が向いている
    - 子どもが好き・保育の仕事自体は嫌いではない・職場環境だけ変えたいなど
  H3: どちらか決まらなければ「情報収集だけ」から始める
    - 求人を見るだけでも自分が何を求めているか見えてくる
    - 複数のサービスに同時登録してから比較するのも有効

■ まとめ
  H3: 保育士のスキルは異業種でも必ず活かせる
    - 最初の一歩は情報収集だけでいい
    - 「保育士として転職」と「異業種転職」の両軸で選択肢を広げよう

■ FAQ（10問・各250字以上で丁寧に回答）
1. 保育士から異業種転職は難しい？
2. 保育士の資格・免許は異業種転職で役に立つ？
3. 未経験の業界に転職するとき、最初に何をすればいい？
4. 保育士から転職して後悔した、という声もあるけど大丈夫？
5. 30代・40代でも異業種転職できる？
6. 保育士から営業職に転職するのはアリ？
7. 保育士から在宅ワークに転職する方法は？
8. 保育士から転職するとき履歴書に何を書けばいい？
9. 転職活動中も今の保育士の仕事を続けた方がいい？
10. 保育士専門の転職サイトと一般の転職サイト、どちらを使うべき？
"""

_CACHE = os.path.join(os.path.dirname(__file__), "_cache_hoikushi_igyoshu.json")

check_stop()

log.info("=" * 60)
log.info(f"記事生成開始（はた楽ナビ）: 「{TITLE}」")
log.info("=" * 60)

if os.path.exists(_CACHE):
    log.info(f"[cache] 生成済み記事を読み込みます: {_CACHE}")
    with open(_CACHE, encoding="utf-8") as f:
        article = json.load(f)
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
        json.dump(article, f, ensure_ascii=False, indent=2)
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

# post 512 を上書き更新
log.info(f"WordPress post {UPDATE_POST_ID} 更新開始...")
_auth_str = base64.b64encode(
    f"{blog_cfg.wp_username}:{blog_cfg.wp_app_password}".encode()
).decode()
_headers = {"Authorization": f"Basic {_auth_str}", "Content-Type": "application/json"}

_payload = {
    "title":   article["title"],
    "content": article["content"],
    "status":  blog_cfg.wp_post_status,
}
if article.get("meta_description"):
    _payload["meta"] = {
        "ssp_meta_description":  article["meta_description"],
        "_yoast_wpseo_metadesc": article["meta_description"],
        "rank_math_description": article["meta_description"],
    }

_r = requests.post(
    f"{blog_cfg.wp_url}/wp-json/wp/v2/posts/{UPDATE_POST_ID}",
    headers=_headers,
    data=json.dumps(_payload),
    timeout=30,
)

if _r.status_code == 200:
    _updated = _r.json()
    _edit_url = f"{blog_cfg.wp_url}/wp-admin/post.php?post={UPDATE_POST_ID}&action=edit"
    log.info(f"✅ 更新完了: ID={UPDATE_POST_ID} → {_edit_url}")
    print(f"\n投稿URL: {_edit_url}")
else:
    log.error(f"❌ 更新失敗: HTTP {_r.status_code}")
    log.error(_r.text[:500])
    # 更新に失敗した場合は新規投稿にフォールバック
    log.info("新規投稿にフォールバックします...")
    result = post(article, dry_run=False, blog_cfg=blog_cfg, asp_list=asp_list)
    log.info(f"✅ 新規投稿完了: ID={result['id']} → {result['edit_url']}")
    print(f"\n投稿URL: {result['edit_url']}")
