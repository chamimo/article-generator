"""
キーワード絞り込み強化版（第2パス）

Usage:
    python3 filter_keywords2.py \
        --input /Users/yama/Downloads/filtered_keywords.csv \
        --output /Users/yama/Downloads/filtered_keywords2.csv
"""
import argparse
import csv
import json
import os
import re
import sys
import time

import anthropic

os.environ.setdefault("ARTICLE_SITE", "workup-ai")
from config import ANTHROPIC_API_KEY

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─────────────────────────────────────────────
# ① エンタメ・ドラマ・漫画・バラエティ系
# ─────────────────────────────────────────────
ENTERTAINMENT_RE = re.compile(
    r'(ドラマ|アニメ|漫画|マンガ|映画|バラエティ|テレビ番組|テレビ|TV番組'
    r'|俳優|女優|アイドル|声優|タレント|芸能人|歌手|ミュージシャン'
    r'|小説|ラノベ|ゲーム攻略|キャラクター設定|推しの|エピソード|放送|主演'
    r'|コミック|ファン|聖地|セリフ|主題歌|名言|名シーン|あらすじ|ネタバレ'
    r'|鬼滅|進撃|ワンピース|ナルト|ハイキュー|呪術|チェンソー|スパイファミ'
    r'|韓流|K-POP|アイドルグループ)',
    re.IGNORECASE,
)

# ─────────────────────────────────────────────
# ② 中国語・外国語（日本語でない文字が多い）
# ─────────────────────────────────────────────
FOREIGN_RE = re.compile(
    r'[\uAC00-\uD7AF]'   # ハングル（韓国語）
)

def is_foreign(kw: str) -> bool:
    """韓国語・非日本語文字が含まれる場合 True。"""
    if FOREIGN_RE.search(kw):
        return True
    # ひらがな・カタカナ・漢字・ASCII以外の文字（アラビア文字など）が含まれる
    if re.search(r'[^\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\u3000-\u303F\uFF00-\uFFEF\u0020-\u007E]', kw):
        return True
    return False

# ─────────────────────────────────────────────
# ③ 挨拶・マナー・贈り物系
# ─────────────────────────────────────────────
GREETING_RE = re.compile(
    r'(年賀状|年賀|お年玉|暑中見舞|寒中見舞|お中元|お歳暮|手土産|お土産'
    r'|プレゼント|贈り物|ギフト|ノベルティ|ラッピング'
    r'|お礼.*メッセージ|メッセージカード|お礼状|お礼文|感謝.*手紙'
    r'|挨拶文|スピーチ原稿|乾杯の挨拶|結婚.*メッセージ|出産.*お祝い'
    r'|弔電|香典|葬儀のマナー|法事|お布施'
    r'|敬語.*一覧|敬語.*例文|クッション言葉|ビジネス.*例文|メール.*例文'
    r'|忌み言葉)',
    re.IGNORECASE,
)

# ─────────────────────────────────────────────
# ④-A 地名単体 + 求人/派遣/バイト（超ローカル）
# ─────────────────────────────────────────────
LOCAL_JOB_RE = re.compile(
    r'^(札幌|仙台|横浜|川崎|相模原|千葉|さいたま|大宮|浦和|船橋|江東|渋谷|新宿|池袋|品川|目黒|世田谷'
    r'|中野|杉並|豊島|北区|板橋|練馬|足立|葛飾|江戸川|八王子|立川|武蔵野|三鷹'
    r'|名古屋|京都|大阪|神戸|広島|福岡|北九州|熊本|鹿児島|那覇|沖縄|札幌|旭川|函館'
    r'|茗荷谷|秋葉原|新橋|虎ノ門|六本木|恵比寿|中目黒|代官山|自由が丘|吉祥寺|下北沢'
    r'|[東西南北]?[一-龯]{1,3}(区|市|町|村|県|府|道|都))'
    r'[\s　]+(求人|派遣|バイト|アルバイト|パート|転職|採用)',
    re.IGNORECASE,
)

# ─────────────────────────────────────────────
# ⑤ 検索意図が薄い・雑談系
# ─────────────────────────────────────────────
THIN_RE = re.compile(
    r'(とは$'
    r'|とは\?'
    r'|って何$'
    r'|の英語$'
    r'|一覧$'
    r'|リスト$'
    r'|まとめ$'
    r'|\d+選$'
    r'|職場.*(うわさ|噂|陰口|悪口|愚痴|チクり|告げ口|嫌がらせ|いじめ|ムカつく|うざい|ウザい)'
    r'|職場.*(恋愛|片思い|付き合い|デート|告白)'
    r'|同僚.*(うわさ|噂|陰口|悪口|愚痴)'
    r'|上司.*(うわさ|噂|陰口|悪口|うざい|ウザい|くそ))',
    re.IGNORECASE,
)

# ─────────────────────────────────────────────
# 必ずキープ（除外しない）
# ─────────────────────────────────────────────
MUST_KEEP_RE = re.compile(
    r'(副業|転職|キャリア|フリーランス|起業|AI|人工知能|Web|プログラミング|エンジニア'
    r'|在宅ワーク|テレワーク|リモートワーク|スキルアップ|副収入|ブログ収益'
    r'|仕事.*AI|AI.*仕事|ChatGPT|生成AI)',
    re.IGNORECASE,
)


def rule_filter(kw: str) -> str:
    """
    'remove_entertainment' / 'remove_foreign' / 'remove_greeting' /
    'remove_local_job' / 'remove_thin' / 'keep' / 'check'
    """
    if MUST_KEEP_RE.search(kw):
        return 'keep'

    if is_foreign(kw):
        return 'remove_foreign'

    if ENTERTAINMENT_RE.search(kw):
        return 'remove_entertainment'

    if GREETING_RE.search(kw):
        return 'remove_greeting'

    if LOCAL_JOB_RE.match(kw):
        return 'remove_local_job'

    if THIN_RE.search(kw):
        return 'remove_thin'

    return 'check'


def claude_classify_batch(keywords: list[str]) -> list[int]:
    """
    副業・転職・キャリア・Web・AI ブログとして
    不要なキーワードの番号を返す（除外すべきインデックス）。
    """
    kw_list = "\n".join(f"[{i}] {kw}" for i, kw in enumerate(keywords))
    prompt = f"""\
以下のキーワードを「副業・転職・キャリア・Web・AIブログ」の観点で評価してください。

## 除外してよいもの（番号を返す）
- エンタメ・ドラマ・アニメ・芸能人関連
- 中国語・韓国語・外国語コンテンツ
- 年賀状・プレゼント・マナー・贈り物など収益化しにくいもの
- 特定の地名単体＋求人/派遣（「大阪 派遣」「新宿 バイト」等）
- 「とは」「英語」「一覧」単体で検索意図が薄いもの
- 職場の恋愛・悪口・噂話などコンテンツ化しにくい雑談

## 残すもの
- 副業・転職・キャリア・フリーランス・Web・AI・プログラミング関連
- 仕事・職場・ビジネス・スキル・収入・働き方 など

## キーワード一覧
{kw_list}

除外すべきキーワードの番号だけをJSON配列で出力。残すものが多ければ空配列[]でOK。
形式: [0, 3, 7]"""

    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # JSON部分だけ抽出
        m = re.search(r'\[[\d,\s]*\]', raw)
        if m:
            return json.loads(m.group())
        return []
    except Exception as e:
        print(f"  [claude] エラー: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  default='/Users/yama/Downloads/filtered_keywords.csv')
    parser.add_argument('--output', default='/Users/yama/Downloads/filtered_keywords2.csv')
    parser.add_argument('--batch-size', type=int, default=60)
    parser.add_argument('--no-claude', action='store_true', help='Claudeをスキップ（高速テスト用）')
    args = parser.parse_args()

    # 読み込み
    with open(args.input, encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))
    header = rows[0]
    data = [{'keyword': r[0], 'volume': int(r[1]) if len(r) > 1 and r[1] else 0,
             'competition': int(r[2]) if len(r) > 2 and r[2] else 0}
            for r in rows[1:] if r and r[0].strip()]

    print(f"[filter2] 入力: {len(data):,}件")

    # ルールベース
    keep = []
    removed = {'foreign': [], 'entertainment': [], 'greeting': [], 'local_job': [], 'thin': []}
    check = []

    for d in data:
        result = rule_filter(d['keyword'])
        if result == 'keep':
            keep.append(d)
        elif result.startswith('remove_'):
            cat = result[len('remove_'):]
            removed[cat].append(d)
        else:
            check.append(d)

    total_removed_rule = sum(len(v) for v in removed.values())
    print(f"[filter2] ルール除外: {total_removed_rule:,}件 "
          f"(外国語:{len(removed['foreign'])} / エンタメ:{len(removed['entertainment'])} / "
          f"挨拶:{len(removed['greeting'])} / 地名求人:{len(removed['local_job'])} / 薄い:{len(removed['thin'])})")
    print(f"[filter2] ルールキープ: {len(keep):,}件 / Claude確認待ち: {len(check):,}件")

    # Claude判定
    keep_claude, removed_claude = [], []
    if check and not args.no_claude:
        total_batches = (len(check) + args.batch_size - 1) // args.batch_size
        print(f"[filter2] Claude判定: {len(check):,}件 ({total_batches}バッチ)")

        for i in range(total_batches):
            batch = check[i * args.batch_size:(i + 1) * args.batch_size]
            kws = [d['keyword'] for d in batch]
            remove_indices = claude_classify_batch(kws)
            remove_set = set(remove_indices)

            for idx, d in enumerate(batch):
                if idx in remove_set:
                    removed_claude.append(d)
                else:
                    keep_claude.append(d)

            if (i + 1) % 10 == 0 or i == total_batches - 1:
                print(f"  [{i+1}/{total_batches}] 除外: {len(removed_claude):,} / キープ: {len(keep_claude):,}")

            if i < total_batches - 1:
                time.sleep(0.3)
    else:
        keep_claude = check  # スキップ時は全キープ

    all_keep = keep + keep_claude
    all_removed = total_removed_rule + len(removed_claude)

    # 出力
    with open(args.output, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['キーワード', '月間検索数', '競合性'])
        for d in sorted(all_keep, key=lambda x: x['volume'], reverse=True):
            writer.writerow([d['keyword'], d['volume'], d['competition']])

    print(f"\n{'='*60}")
    print("【絞り込み結果レポート（第2パス）】")
    print(f"{'='*60}")
    print(f"入力:                 {len(data):,}件")
    print(f"除外（外国語）:       {len(removed['foreign']):,}件")
    print(f"除外（エンタメ）:     {len(removed['entertainment']):,}件")
    print(f"除外（挨拶・贈物）:   {len(removed['greeting']):,}件")
    print(f"除外（地名求人）:     {len(removed['local_job']):,}件")
    print(f"除外（検索意図薄）:   {len(removed['thin']):,}件")
    print(f"除外（Claude判定）:   {len(removed_claude):,}件")
    print(f"---")
    print(f"残存キーワード数:     {len(all_keep):,}件")
    print(f"削除合計:             {all_removed:,}件  ({all_removed/len(data)*100:.1f}%)")
    print(f"出力: {args.output}")

    # 除外サンプル表示
    print("\n【除外サンプル（各カテゴリ上位5件）】")
    for cat, items in removed.items():
        if items:
            print(f"  [{cat}]:", ', '.join(d['keyword'] for d in items[:5]))
    if removed_claude:
        print(f"  [claude]:", ', '.join(d['keyword'] for d in removed_claude[:5]))


if __name__ == '__main__':
    main()
