"""
Step 3: GoogleスプレッドシートからAIM判定キーワードを自動取得

シート構造（独走_AIM判定まとめ）:
  C列(3): キーワード
  E列(5): 月間検索数
  W列(23): aim
"""
import gspread
from google.oauth2.service_account import Credentials
from config import (
    GOOGLE_SHEETS_ID,
    GOOGLE_CREDENTIALS_PATH,
    AIM_POSITIVE_VALUES,
    MIN_SEARCH_VOLUME,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _find_col_index(header_row: list[str], candidates: list[str]) -> int | None:
    """ヘッダー行から列名を検索し、0始まりインデックスを返す。"""
    for name in candidates:
        for i, h in enumerate(header_row):
            if str(h).strip() == name:
                return i
    return None


def get_aim_keywords(sheet_name: str | None = None, worksheet_index: int = 0) -> list[dict]:
    """
    スプレッドシートからAIM判定あり かつ 検索ボリューム≥MIN_SEARCH_VOLUME のキーワードを返す。

    Returns:
        [{"キーワード": "xxx", "検索ボリューム": 100}, ...]
    """
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)

    ws = spreadsheet.worksheet(sheet_name) if sheet_name else spreadsheet.get_worksheet(worksheet_index)

    # ヘッダー重複があるため get_all_values() で生データ取得
    all_values = ws.get_all_values()
    if not all_values:
        print(f"[sheets_fetcher] シート「{ws.title}」にデータがありません")
        return []

    header = all_values[0]
    rows = all_values[1:]
    print(f"[sheets_fetcher] シート「{ws.title}」: {len(rows)}行 取得")

    # 列インデックスを動的に検出
    kw_idx = _find_col_index(header, ["キーワード", "Keyword", "keyword"])
    vol_idx = _find_col_index(header, ["月間検索数", "月間検索ボリューム", "検索ボリューム", "Search Volume"])
    aim_idx = _find_col_index(header, ["aim", "AIM", "AIM判定", "aim判定"])

    # 検出できない場合は既知の固定インデックスにフォールバック（C=2, E=4, W=22）
    if kw_idx is None:
        kw_idx = 2
        print(f"[sheets_fetcher] キーワード列を自動検出できず → 列{kw_idx + 1}(C列)を使用")
    if vol_idx is None:
        vol_idx = 4
        print(f"[sheets_fetcher] 検索ボリューム列を自動検出できず → 列{vol_idx + 1}(E列)を使用")
    if aim_idx is None:
        aim_idx = 22
        print(f"[sheets_fetcher] AIM列を自動検出できず → 列{aim_idx + 1}(W列)を使用")

    print(f"[sheets_fetcher] 使用列: キーワード={kw_idx+1}, ボリューム={vol_idx+1}, AIM={aim_idx+1}")

    aim_keywords = []
    for row in rows:
        def cell(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        keyword = cell(kw_idx)
        aim_val = cell(aim_idx)
        volume_raw = (
            cell(vol_idx)
            .replace(",", "")
            .replace("－", "0")
            .replace("-", "0")
        )

        if not keyword:
            continue

        try:
            volume = int(float(volume_raw)) if volume_raw else 0
        except ValueError:
            volume = 0

        # AIM='aim' のキーワードはボリューム条件を無視して採用
        if aim_val in AIM_POSITIVE_VALUES:
            aim_keywords.append({"キーワード": keyword, "検索ボリューム": volume})

    print(f"[sheets_fetcher] AIM判定キーワード: {len(aim_keywords)}件 (ボリューム条件: AIMありは無条件採用)")
    return aim_keywords


def get_non_aim_keywords(sheet_name: str | None = None, worksheet_index: int = 0) -> list[str]:
    """
    AIM列が空（未判定）のキーワードをサブキーワード候補として返す。

    Returns:
        ["キーワード1", "キーワード2", ...]  ※重複除去・最大300件
    """
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)

    ws = spreadsheet.worksheet(sheet_name) if sheet_name else spreadsheet.get_worksheet(worksheet_index)
    all_values = ws.get_all_values()
    if not all_values:
        return []

    header = all_values[0]
    rows = all_values[1:]

    kw_idx  = _find_col_index(header, ["キーワード", "Keyword", "keyword"])
    aim_idx = _find_col_index(header, ["aim", "AIM", "AIM判定", "aim判定"])
    if kw_idx is None:
        kw_idx = 2
    if aim_idx is None:
        aim_idx = 22

    non_aim: list[str] = []
    seen: set[str] = set()
    for row in rows:
        def cell(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        keyword = cell(kw_idx)
        aim_val = cell(aim_idx)

        if not keyword:
            continue
        if aim_val:  # AIM列に何か入っていれば対象外
            continue
        if keyword in seen:
            continue
        seen.add(keyword)
        non_aim.append(keyword)
        if len(non_aim) >= 300:
            break

    print(f"[sheets_fetcher] サブキーワード候補（AIM未判定）: {len(non_aim)}件")
    return non_aim
