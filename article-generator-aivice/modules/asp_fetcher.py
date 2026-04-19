"""
ASP案件アフィリリンクをスプレッドシートから取得する。

アフィリURLシート構成:
  A列: 案件名
  B列: ブログ名（例: はた楽ナビ, AIVICE）
  C列: 優先順位（数字が小さいほど優先）
  D列: アフィリリンク

ASP案件マスターシート（オプション）:
  A列: 案件名
  I列: 訴求軸1
  J列: 訴求軸2
"""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_PATH

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
_AFFILI_SHEET_NAME = "アフィリURL"
_MASTER_SHEET_NAME = "ASP案件マスター"


def fetch_asp_links(blog_display_name: str, ss_id: str) -> list[dict]:
    """
    アフィリURLシートから対象ブログのASP案件を優先順位順で返す。

    B列のブログ名が blog_display_name に部分一致する行を抽出する。
    ASP案件マスターシートが存在すれば I・J列の訴求軸も付加する。

    Args:
        blog_display_name : ブログの表示名（例: "はた楽ナビ", "AIVICE"）
        ss_id             : スプレッドシートID

    Returns:
        [{"name": str, "url": str, "priority": int, "appeal": str}, ...]
        優先順位（C列）昇順でソート済み。
    """
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    try:
        ss = gc.open_by_key(ss_id)
    except Exception as e:
        print(f"[asp_fetcher] スプレッドシート接続エラー (id={ss_id[:12]}...): {e}")
        return []

    # ── アフィリURLシートを読み込む ──────────────────────────────────
    try:
        ws = ss.worksheet(_AFFILI_SHEET_NAME)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[asp_fetcher] 「{_AFFILI_SHEET_NAME}」シート読み込みエラー: {e}")
        return []

    if len(rows) < 2:
        print(f"[asp_fetcher] 「{_AFFILI_SHEET_NAME}」シートにデータがありません")
        return []

    data_rows = rows[1:]  # ヘッダー除外
    blog_lower = blog_display_name.lower()
    results: list[dict] = []

    for row in data_rows:
        def cell(i: int) -> str:
            return row[i].strip() if i < len(row) else ""

        name     = cell(0)   # A列: 案件名
        blog     = cell(1)   # B列: ブログ名
        pri_raw  = cell(2)   # C列: 優先順位
        url      = cell(3)   # D列: アフィリリンク

        if not name or not url:
            continue

        # ブログ名フィルタ（B列が空なら全ブログ共通と見なす）
        if blog:
            if blog_lower not in blog.lower() and blog.lower() not in blog_lower:
                continue

        try:
            priority = int(pri_raw) if pri_raw else 999
        except ValueError:
            priority = 999

        results.append({"name": name, "url": url, "priority": priority, "appeal": ""})

    # ── ASP案件マスターシートから訴求軸を補完（オプション）──────────
    try:
        master_ws = ss.worksheet(_MASTER_SHEET_NAME)
        master_rows = master_ws.get_all_values()
        if len(master_rows) >= 2:
            appeal_map: dict[str, str] = {}
            for mrow in master_rows[1:]:
                def mcell(i: int) -> str:
                    return mrow[i].strip() if i < len(mrow) else ""
                mname   = mcell(0)   # A列: 案件名
                appeal1 = mcell(8)   # I列: 訴求軸1
                appeal2 = mcell(9)   # J列: 訴求軸2
                if mname:
                    parts = [p for p in [appeal1, appeal2] if p]
                    appeal_map[mname] = "・".join(parts)
            for item in results:
                if item["name"] in appeal_map:
                    item["appeal"] = appeal_map[item["name"]]
            if appeal_map:
                print(f"[asp_fetcher] 訴求軸補完: {sum(1 for r in results if r['appeal'])}件")
    except Exception:
        pass  # マスターシートがなければスキップ

    # ── 優先順位でソート ────────────────────────────────────────────
    results.sort(key=lambda x: x["priority"])

    print(f"[asp_fetcher] {blog_display_name} 向けASP案件: {len(results)}件")
    for r in results[:8]:
        print(f"[asp_fetcher]   [{r['priority']}] {r['name']} → {r['url'][:50]}"
              + (f" / {r['appeal'][:30]}" if r['appeal'] else ""))

    return results


def to_asp_dict(asp_list: list[dict]) -> dict[str, str]:
    """
    fetch_asp_links() の返り値を {案件名: URL} の辞書に変換する。
    internal_linker など従来インターフェースとの互換用。
    """
    return {item["name"]: item["url"] for item in asp_list}


def build_asp_prompt_section(asp_list: list[dict]) -> str:
    """
    fetch_asp_links() の返り値からシステムプロンプト用のASP案件セクションを生成する。

    生成されるセクションは article_generator._build_system_prompt() に追記される。
    """
    if not asp_list:
        return ""

    lines = [
        "",
        "## ASP案件リスト（このブログ専用・優先順位順）",
        "以下の案件が記事テーマと自然に合う場合、アフィリリンクを挿入してください。",
        "- 優先順位が高い（番号が小さい）案件から検討する",
        "- 1記事につき最大2〜3案件まで",
        "- リンク形式: <a href=\"{URL}\" target=\"_blank\" rel=\"noopener noreferrer\">{案件名}</a>",
        "- 記事テーマと関連しない案件は挿入しないこと（無理に詰め込まない）",
        "",
    ]
    for i, item in enumerate(asp_list, 1):
        line = f"{i}. 【{item['name']}】 {item['url']}"
        if item.get("appeal"):
            line += f"\n   訴求軸: {item['appeal']}"
        lines.append(line)

    return "\n".join(lines)
