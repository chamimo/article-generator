"""
キーワード絞り込みスクリプト

ラッコKWシートのCSVから副業・転職・キャリア・Web・AI関連キーワードを抽出する。

Usage:
    python3 filter_keywords.py --input "path/to/file.csv" --output filtered_keywords.csv
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict

import anthropic

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
os.environ.setdefault("ARTICLE_SITE", "workup-ai")
from config import ANTHROPIC_API_KEY

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── 明らかにキープするキーワード（ルールベース）──
KEEP_PATTERNS = [
    r'転職', r'副業', r'仕事', r'職場', r'キャリア', r'就職', r'採用', r'求人',
    r'派遣', r'アルバイト', r'パート', r'給料', r'年収', r'スキル', r'資格',
    r'フリーランス', r'起業', r'ビジネス', r'エンジニア', r'デザイナ', r'プログラム',
    r'リモート', r'テレワーク', r'在宅.?ワーク', r'在宅.?勤務', r'業務', r'労働',
    r'残業', r'有給', r'面接', r'履歴書', r'職歴', r'職種', r'業種', r'正社員',
    r'契約社員', r'SES', r'ハラスメント', r'パワハラ', r'モラハラ', r'退職',
    r'転勤', r'昇給', r'ボーナス', r'賞与', r'上司', r'同僚', r'部下', r'社員',
    r'会社員', r'サラリーマン', r'ワークライフ', r'研修', r'社会保険',
    r'\bAI\b', r'人工知能', r'ChatGPT', r'機械学習', r'深層学習',
    r'\bIT\b', r'Web', r'DX', r'システム開発', r'アプリ開発', r'クラウド',
    r'プログラミング', r'Python', r'JavaScript', r'HTML', r'CSS',
    r'フルスタック', r'バックエンド', r'フロントエンド', r'インフラ',
    r'マーケティング', r'SEO', r'ライター', r'コンサル', r'マネジメント',
    r'人事', r'労務', r'経理', r'営業', r'事務', r'秘書',
    r'メンタル', r'うつ', r'ストレス', r'燃え尽き', r'バーンアウト',
    r'働き方', r'自己啓発', r'スキルアップ', r'資格取得', r'TOEIC', r'英語.*仕事',
    r'副収入', r'投資.*副業', r'ブログ.*収益', r'アフィリエイト',
]

# ── 明らかに無関係なパターン（ルールベース除外）──
REMOVE_PATTERNS = [
    # 中国語・韓国語のコンテンツタイトル（漢字が多すぎる）
    r'[^\u3000-\u9FFF\uFF00-\uFFEF\u0020-\u007E\u3040-\u309F\u30A0-\u30FF]{4,}',
    # 明らかな食品・料理
    r'^(レシピ|料理|食べ物|グルメ|ランチ|ディナー|スイーツ|カフェ)',
    # 明らかな観光・旅行（就職文脈なし）
    r'^(観光|旅行|旅館|ホテル|温泉|絶景|ツアー)',
    # ゲーム・アニメ（IT・ゲーム業界文脈なし）
    r'^(攻略|ガチャ|キャラ|漫画|アニメ|映画|ドラマ|アイドル)',
    # ファッション・美容
    r'^(コーデ|メイク|スキンケア|ダイエット|ファッション)',
    # 地名のみ（求人文脈なし）
    r'^[\u4E00-\u9FFF]{2,4}[\s　](駅|市|区|町|村|県|府|道|都)[\s　]',
    # 明らかな中国語文字列
    r'[\u4E00-\u9FFF]{5,}',
]

KEEP_RE   = [re.compile(p) for p in KEEP_PATTERNS]
REMOVE_RE = [re.compile(p) for p in REMOVE_PATTERNS]


def rule_classify(kw: str) -> str:
    """ルールベースで 'keep' / 'remove' / 'unknown' を返す。"""
    if not kw or not kw.strip():
        return 'remove'

    # 明らかにキープ
    for pat in KEEP_RE:
        if pat.search(kw):
            return 'keep'

    # 明らかに除外
    for pat in REMOVE_RE:
        if pat.search(kw):
            return 'remove'

    return 'unknown'


def claude_classify_batch(keywords: list[str]) -> dict[str, bool]:
    """
    Claude Haiku で keywords を一括判定。
    副業・転職・キャリア・Web・AI ブログに関連があれば True。
    Returns: {keyword: bool}
    """
    kw_list = "\n".join(f"[{i}] {kw}" for i, kw in enumerate(keywords))
    prompt = (
        "以下のキーワードが「副業・転職・キャリア・Web・AIブログ」のコンテンツとして関連するか判定してください。\n\n"
        "## 関連とみなすもの\n"
        "- 副業・在宅ワーク・フリーランス・起業\n"
        "- 転職・就職・キャリア・仕事・職場・労働\n"
        "- IT・Web・AI・プログラミング・デジタルスキル\n"
        "- ビジネス・マーケティング・収入・スキルアップ\n"
        "- 職場の人間関係・メンタルヘルス（仕事文脈）\n\n"
        "## 無関係とみなすもの\n"
        "- 純粋な趣味・エンタメ・食事・観光\n"
        "- 日本語ではない（中国語・韓国語等）コンテンツ\n"
        "- 明らかに上記と無関係なもの\n\n"
        f"## キーワード一覧\n{kw_list}\n\n"
        "関連するキーワードの番号だけをJSON配列で出力してください。例: [0, 2, 5]"
    )

    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r'```[a-z]*\n?', '', raw).strip().strip('`').strip()
        indices: list[int] = json.loads(raw)
        return {kw: (i in indices) for i, kw in enumerate(keywords)}
    except Exception as e:
        print(f"  [claude_batch] エラー: {e}")
        # フォールバック: 全部キープ
        return {kw: True for kw in keywords}


def normalize(kw: str) -> str:
    """重複チェック用に正規化（全角→半角、空白除去、小文字化）。"""
    kw = kw.strip()
    kw = kw.replace('\u3000', ' ')   # 全角スペース
    kw = kw.lower()
    # 全角英数 → 半角
    result = ''
    for c in kw:
        if '\uff01' <= c <= '\uff5e':
            result += chr(ord(c) - 0xfee0)
        else:
            result += c
    return re.sub(r'\s+', ' ', result).strip()


def deduplicate(keywords: list[dict]) -> list[dict]:
    """
    正規化後の文字列が同じものを重複とみなし、代表1件を残す。
    検索ボリューム降順で代表を選ぶ。
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for kw in keywords:
        key = normalize(kw['keyword'])
        groups[key].append(kw)

    result = []
    dedup_count = 0
    for key, group in groups.items():
        group_sorted = sorted(group, key=lambda x: x['volume'], reverse=True)
        result.append(group_sorted[0])
        dedup_count += len(group) - 1

    return result, dedup_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True, help='入力CSVパス')
    parser.add_argument('--output', default='filtered_keywords.csv', help='出力CSVパス')
    parser.add_argument('--batch-size', type=int, default=80,
                        help='Claude API 1回あたりの処理件数')
    args = parser.parse_args()

    # ── 1. CSV 読み込み ──
    print(f"[filter] CSV読み込み: {args.input}")
    rows = []
    with open(args.input, encoding='utf-8') as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    header = all_rows[0] if all_rows else []
    data_rows = all_rows[1:]

    # キーワード列を検出（"キーワード" ヘッダーの列 or 最初の非空列）
    kw_col = next((i for i, h in enumerate(header) if 'キーワード' in h), 3)
    vol_col = next((i for i, h in enumerate(header) if '月間検索数' in h or 'Search Volume' in h), 5)
    comp_col = next((i for i, h in enumerate(header) if '競合性' in h), 7)

    print(f"[filter] 列検出: キーワード={kw_col+1}, 月間検索数={vol_col+1}, 競合性={comp_col+1}")
    print(f"[filter] 総行数: {len(data_rows):,}")

    for r in data_rows:
        kw = r[kw_col].strip() if kw_col < len(r) else ''
        if not kw:
            continue
        try:
            vol = int(float(r[vol_col])) if vol_col < len(r) and r[vol_col] not in ('', 'null') else 0
        except ValueError:
            vol = 0
        try:
            comp = int(float(r[comp_col])) if comp_col < len(r) and r[comp_col] not in ('', 'null') else 0
        except ValueError:
            comp = 0
        rows.append({'keyword': kw, 'volume': vol, 'competition': comp, 'raw': r})

    print(f"[filter] 有効キーワード: {len(rows):,}件")

    # ── 2. ルールベースフィルター ──
    keep_rule, remove_rule, unknown = [], [], []
    for kw_dict in rows:
        result = rule_classify(kw_dict['keyword'])
        if result == 'keep':
            keep_rule.append(kw_dict)
        elif result == 'remove':
            remove_rule.append(kw_dict)
        else:
            unknown.append(kw_dict)

    print(f"[filter] ルール判定 → キープ: {len(keep_rule):,} / 除外: {len(remove_rule):,} / 不明: {len(unknown):,}")

    # ── 3. Claude バッチ判定（unknownのみ）──
    keep_claude = []
    remove_claude = []

    if unknown:
        print(f"[filter] Claude判定開始: {len(unknown):,}件 (batch={args.batch_size})")
        total_batches = (len(unknown) + args.batch_size - 1) // args.batch_size

        for batch_i in range(total_batches):
            batch = unknown[batch_i * args.batch_size: (batch_i + 1) * args.batch_size]
            kws = [d['keyword'] for d in batch]
            result_map = claude_classify_batch(kws)

            for d in batch:
                if result_map.get(d['keyword'], True):
                    keep_claude.append(d)
                else:
                    remove_claude.append(d)

            print(f"  [{batch_i+1}/{total_batches}] キープ追加: {sum(1 for v in result_map.values() if v)}")

            if batch_i < total_batches - 1:
                time.sleep(0.5)

    all_kept = keep_rule + keep_claude
    print(f"\n[filter] Claude判定後 → 累計キープ: {len(all_kept):,} / 除外追加: {len(remove_claude):,}")

    # ── 4. 重複除去 ──
    deduped, dedup_count = deduplicate(all_kept)
    print(f"[filter] 重複除去: {dedup_count:,}件削除 → {len(deduped):,}件")

    # ── 5. 出力 ──
    output_path = args.output
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['キーワード', '月間検索数', '競合性'])
        for d in sorted(deduped, key=lambda x: x['volume'], reverse=True):
            writer.writerow([d['keyword'], d['volume'], d['competition']])

    print(f"\n{'='*60}")
    print("【絞り込み結果レポート】")
    print(f"{'='*60}")
    print(f"入力キーワード数:         {len(rows):,}件")
    print(f"ルールでキープ:           {len(keep_rule):,}件")
    print(f"ルールで除外:             {len(remove_rule):,}件")
    print(f"Claudeでキープ:           {len(keep_claude):,}件")
    print(f"Claudeで除外:             {len(remove_claude):,}件")
    print(f"重複除去:                 {dedup_count:,}件")
    print(f"---")
    print(f"最終残存キーワード数:     {len(deduped):,}件")
    print(f"削除合計:                 {len(rows) - len(deduped):,}件")
    print(f"出力ファイル:             {output_path}")

    return output_path


if __name__ == '__main__':
    main()
