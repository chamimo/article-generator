"""
AIVice カニバリチェック一括実行スクリプト

スプレッドシートの AIM=add のキーワードを全件チェックし、
skip / differentiate / ok を分類して出力する。

列構成（AIVice キーワードシート）:
  A(0): キーワード  B(1): 月間検索数  I(8): AIM  J(9): ステータス
"""
import os
import re
os.environ.setdefault("ARTICLE_SITE", "workup-ai")

from dotenv import load_dotenv
load_dotenv(".env")

from modules.sheets_fetcher import _open_main_worksheet
from modules.cannibal_checker import check_cannibalization

def _is_overseas_kw(kw: str) -> bool:
    """英語長フレーズ・中国語特有表記を含む海外向けKWを判定する。"""
    # 半角英字単語が4つ以上（日本語混じりの「Google AI 広告」等は除外）
    if len(re.findall(r'[a-zA-Z]+', kw)) >= 4:
        return True
    # ひらがな・カタカナを含まない純漢字KW（中国語の可能性が高い）
    has_kana = bool(re.search(r'[ぁ-んァ-ン]', kw))
    has_kanji = bool(re.search(r'[一-鿿]', kw))
    if has_kanji and not has_kana and len(re.findall(r'[a-zA-Z]+', kw)) == 0:
        return True
    return False

print("スプレッドシートからキーワード取得中...")
ws = _open_main_worksheet()
rows = ws.get_all_values()

# AIM=add のキーワードを抽出（列A=キーワード、列I=AIM）
all_kws = []
for r in rows[1:]:
    kw     = r[0].strip() if len(r) > 0 else ""
    aim    = r[8].strip() if len(r) > 8 else ""
    status = r[9].strip() if len(r) > 9 else ""
    if not kw or aim != "add":
        continue
    all_kws.append({"keyword": kw, "status": status})

print(f"チェック対象（AIM=add）: {len(all_kws)}件\n")

results = {"skip": [], "differentiate": [], "ok": [], "overseas": []}

for i, item in enumerate(all_kws, 1):
    kw     = item["keyword"]
    status = item["status"]

    # 海外向けKWは先に除外
    if _is_overseas_kw(kw):
        print(f"[{i}/{len(all_kws)}] [海外KW除外] {kw}")
        results["overseas"].append({"keyword": kw, "similar": [], "note": "英語長フレーズ or 中国語漢字"})
        continue

    print(f"[{i}/{len(all_kws)}] {kw}")
    res = check_cannibalization(kw)
    cs  = res["status"]
    results[cs].append({
        "keyword": kw,
        "similar": res["similar_titles"],
        "note": res.get("differentiation_note", ""),
        "sheet_status": status,
    })

# ── 結果出力 ──
print("\n" + "="*60)
print(f"【カニバリチェック結果】")
print(f"  skip          : {len(results['skip'])}件（生成不要・既存と被り）")
print(f"  differentiate : {len(results['differentiate'])}件（差別化すれば可）")
print(f"  ok            : {len(results['ok'])}件（そのまま生成可）")
print(f"  overseas除外   : {len(results['overseas'])}件（英語長KW・中国語KW）")
print("="*60)

if results["skip"]:
    print(f"\n🔴 SKIP（{len(results['skip'])}件）— 既存記事と被りあり、生成不要")
    for r in results["skip"]:
        print(f"  ・{r['keyword']}")
        for s in r["similar"][:2]:
            print(f"      → 類似: {s[:50]}")

if results["differentiate"]:
    print(f"\n🟡 DIFFERENTIATE（{len(results['differentiate'])}件）— 差別化すれば生成可")
    for r in results["differentiate"]:
        print(f"  ・{r['keyword']}")
        for s in r["similar"][:1]:
            print(f"      → 類似: {s[:50]}")

if results["ok"]:
    print(f"\n🟢 OK（{len(results['ok'])}件）— そのまま生成可")
    for r in results["ok"]:
        print(f"  ・{r['keyword']}")

if results["overseas"]:
    print(f"\n⚪ 海外向けKW除外（{len(results['overseas'])}件）— スプレッドシートから削除推奨")
    for r in results["overseas"]:
        print(f"  ・{r['keyword']}")
