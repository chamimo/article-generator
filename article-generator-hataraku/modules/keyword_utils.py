"""
キーワード解析ユーティリティ

main.py / wordpress_poster.py など複数モジュールから共有するヘルパー。
"""


def detect_parent_keyword(keyword: str) -> str:
    """
    キーワード文字列の先頭1〜2単語を親キーワードとして返す。
    ハードコードなし・動的に判定する。

    ルール:
    - スペースで分割した先頭語が4文字以上 → 先頭1単語を親キーワードとする
    - 先頭語が3文字以下（英略語など）       → 先頭2単語を親キーワードとする
    - 単語が1つしかない場合                 → そのまま返す

    例:
      "aiボイスレコーダー アプリ iphone" → "aiボイスレコーダー"
      "plaud note aiボイスレコーダー"    → "plaud"
      "notta 使い方"                     → "notta"
      "議事録アプリ おすすめ"             → "議事録アプリ"
      "文字起こしツール 比較"             → "文字起こしツール"
      "photodirector 使い方"             → "photodirector"
      "ai 録音 スマホ"                   → "ai 録音"      (ai=2文字 → 2語)
    """
    words = keyword.lower().split()
    if not words:
        return "other"
    first = words[0]
    if len(words) == 1 or len(first) >= 4:
        return first
    # 短い先頭語（3文字以下）は2単語セットを親キーワードとする
    return " ".join(words[:2])
