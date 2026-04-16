"""
Step 1-2: ラッコキーワードCSVを読み込み、検索ボリューム50以上でフィルタリング
"""
import os
import pandas as pd
from config import MIN_SEARCH_VOLUME, DATA_DIR, FILTERED_KEYWORDS_CSV


# ラッコキーワードCSVで使われる可能性のある列名のエイリアス
KEYWORD_COL_ALIASES = ["キーワード", "Keyword", "keyword", "検索キーワード"]
VOLUME_COL_ALIASES = [
    "月間検索数", "月間検索ボリューム", "検索ボリューム",
    "Search Volume", "search_volume", "volume", "ボリューム",
]


def _detect_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in df.columns:
            return alias
    return None


def load_and_filter(csv_path: str, min_volume: int = MIN_SEARCH_VOLUME) -> pd.DataFrame:
    """
    ラッコキーワードCSVを読み込み、検索ボリューム >= min_volume のキーワードを返す。
    filtered_keywords.csv も出力する。
    """
    # ラッコキーワードCSVはShift_JISの場合がある
    for enc in ("utf-8-sig", "utf-8", "shift_jis", "cp932"):
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            break
        except (UnicodeDecodeError, Exception):
            continue
    else:
        raise ValueError(f"CSVファイルを読み込めませんでした: {csv_path}")

    keyword_col = _detect_column(df, KEYWORD_COL_ALIASES)
    volume_col = _detect_column(df, VOLUME_COL_ALIASES)

    if keyword_col is None:
        raise ValueError(f"キーワード列が見つかりません。列名: {list(df.columns)}")
    if volume_col is None:
        raise ValueError(f"検索ボリューム列が見つかりません。列名: {list(df.columns)}")

    # 数値に変換（カンマ区切りや文字列対応）
    df[volume_col] = (
        df[volume_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("－", "0", regex=False)
        .str.replace("-", "0", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
        .astype(int)
    )

    filtered = df[df[volume_col] >= min_volume].copy()
    filtered = filtered.rename(columns={keyword_col: "キーワード", volume_col: "検索ボリューム"})
    filtered = filtered[["キーワード", "検索ボリューム"] + [
        c for c in filtered.columns if c not in ("キーワード", "検索ボリューム")
    ]]
    filtered = filtered.sort_values("検索ボリューム", ascending=False).reset_index(drop=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    filtered.to_csv(FILTERED_KEYWORDS_CSV, index=False, encoding="utf-8-sig")

    print(f"[keyword_filter] 元: {len(df)}件 → フィルター後: {len(filtered)}件 (ボリューム≥{min_volume})")
    print(f"[keyword_filter] 出力: {FILTERED_KEYWORDS_CSV}")
    return filtered
