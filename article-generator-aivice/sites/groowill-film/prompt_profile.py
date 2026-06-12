"""AIO prompt profile for Groowill corporate film articles."""

AIO_PROFILE = {
    "enabled": True,
    "mode": "groowill_film",
    "audience": "学校ICT・医療機関・業務用端末を管理する法人担当者",
    "conversion_goal": "端末名、型番、台数、希望機能を添えた法人問い合わせ",
    "author_name": "グルーウィル法人フィルム編集部",
    "source_policy": "メーカー公式情報、端末仕様、学校・医療・法人運用に関する一次情報を優先する",
    "reference_label": "出典・参考情報",
    "custom_rules": """
- 個人向けレビューではなく、法人導入の判断材料として書く
- 価格だけでなく、台数、貼付作業、予備在庫、納期、特殊サイズ対応を判断軸にする
- 問い合わせ導線では、端末名・型番・台数・希望機能・利用現場を伝えるよう促す
- 医療・学校ICTの話題では安全性や制度を断定しすぎず、公式情報確認を促す
""",
}
