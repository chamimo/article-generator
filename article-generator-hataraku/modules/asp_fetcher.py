"""
ASP案件アフィリリンクをブログ別スプレッドシートから取得する。

読み込み先: 各ブログの candidate_ss_id スプレッドシート内の ASP案件マスターシート
シート名の候補: ["ASP案件マスター", "ASP案件マスター のコピー"]

列構成:
  A列: 案件名
  B列: ブログ名（参考情報。ブログ別SSのため混入チェック用）
  C列: 優先度（S / A / B / C）
  D列: アフィリリンク
  E列: 訴求軸（SEO・CVポイント）
"""
from __future__ import annotations

import logging
from config import GOOGLE_CREDENTIALS_PATH

log = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# 試みるシート名（優先順）
_ASP_SHEET_CANDIDATES = ["ASP案件マスター", "ASP案件マスター のコピー", "ASP案件マスター "]

# 優先度ランク → 数値変換（数値が小さいほど優先）
_PRIORITY_MAP = {"S": 1, "A": 2, "B": 3, "C": 4}


def _priority_value(raw: str) -> int:
    key = raw.strip().upper()
    return _PRIORITY_MAP.get(key, 999)


def fetch_asp_links(
    blog_display_name: str = "",
    ss_id: str = "",
) -> list[dict]:
    """
    ブログ別スプレッドシートの ASP案件マスターシートから案件リストを返す。

    ss_id が空の場合は wp_context.get_candidate_ss_id() を使用する。
    blog_display_name は混入チェック用ログ出力のみに使用（フィルタには使わない）。

    Returns:
        [{"name": str, "url": str, "priority": int, "appeal": str}, ...]
        優先度（C列）昇順でソート済み。
        シートが存在しない場合は空リストを返す。
    """
    # ss_id が空なら wp_context から取得（asp_ss_id → candidate_ss_id の順で優先）
    if not ss_id:
        try:
            from modules import wp_context
            ss_id = wp_context.get_asp_ss_id()
        except Exception as e:
            log.warning(f"[asp_fetcher] ss_id 取得エラー: {e}")
            return []

    if not ss_id:
        log.debug("[asp_fetcher] ss_id が未設定のためスキップ")
        return []

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        log.warning(f"[asp_fetcher] gspread 未インストール: {e}")
        return []

    try:
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
        gc    = gspread.authorize(creds)
        ss    = gc.open_by_key(ss_id)
    except Exception as e:
        log.warning(f"[asp_fetcher] SS接続エラー (id={ss_id[:16]}...): {e}")
        return []

    # シート名を候補順に試す
    ws   = None
    used = ""
    for sheet_name in _ASP_SHEET_CANDIDATES:
        try:
            ws   = ss.worksheet(sheet_name)
            used = sheet_name
            break
        except Exception:
            continue

    if ws is None:
        log.debug(f"[asp_fetcher] ASP案件シートが見つかりません (ss={ss_id[:16]}...) 候補: {_ASP_SHEET_CANDIDATES}")
        return []

    try:
        rows = ws.get_all_values()
    except Exception as e:
        log.warning(f"[asp_fetcher] シート読み込みエラー ({used}): {e}")
        return []

    if len(rows) < 2:
        log.debug(f"[asp_fetcher] 「{used}」にデータがありません")
        return []

    results: list[dict] = []
    for row in rows[1:]:  # ヘッダー除外
        def cell(i: int) -> str:
            return row[i].strip() if i < len(row) else ""

        name   = cell(0)  # A列: 案件名
        blog   = cell(1)  # B列: ブログ名（ログ用）
        pri    = cell(2)  # C列: 優先度
        url    = cell(3)  # D列: アフィリリンク
        appeal = cell(4)  # E列: 訴求軸

        if not name or not url:
            continue

        results.append({
            "name":     name,
            "url":      url,
            "priority": _priority_value(pri),
            "appeal":   appeal,
            "blog":     blog,   # 混入チェック用（内部のみ）
        })

    results.sort(key=lambda x: x["priority"])

    # ── 混入チェック: B列のブログ名が複数種類ある場合は警告 ──
    if blog_display_name:
        other_blogs = {
            r["blog"] for r in results
            if r["blog"] and r["blog"] != blog_display_name
        }
        if other_blogs:
            log.warning(
                f"[asp_fetcher] ⚠️  混入検知: 「{used}」に別ブログの案件が含まれています "
                f"→ {other_blogs}（{blog_display_name} のSSを確認してください）"
            )

    print(f"[asp_fetcher] {blog_display_name or ss_id[:16]} / 「{used}」: {len(results)}件")
    for r in results[:8]:
        pri_label = next((k for k, v in _PRIORITY_MAP.items() if v == r["priority"]), str(r["priority"]))
        print(f"[asp_fetcher]   [{pri_label}] {r['name']} → {r['url'][:50]}"
              + (f" / {r['appeal'][:30]}" if r["appeal"] else ""))

    return results


def to_asp_dict(asp_list: list[dict]) -> dict[str, str]:
    """fetch_asp_links() の返り値を {案件名: URL} に変換する。"""
    return {item["name"]: item["url"] for item in asp_list}


def build_asp_prompt_section(asp_list: list[dict]) -> str:
    """
    fetch_asp_links() の返り値からシステムプロンプト用のASP案件セクションを生成する。
    """
    if not asp_list:
        return ""

    lines = [
        "",
        "## ASP案件リスト（このブログ専用・優先順位順）",
        "以下の案件が記事テーマと自然に合う場合、アフィリリンクを挿入してください。",
        "- 優先度が高い（S > A > B > C）案件から検討する",
        "- 1記事につき最大2〜3案件まで",
        "- リンク形式: <a href=\"{URL}\" target=\"_blank\" rel=\"noopener noreferrer\">{案件名}</a>",
        "- 記事テーマと関連しない案件は挿入しないこと（無理に詰め込まない）",
        "",
    ]
    for i, item in enumerate(asp_list, 1):
        pri_label = next((k for k, v in _PRIORITY_MAP.items() if v == item["priority"]), "?")
        line = f"{i}. 【{item['name']}】[{pri_label}] {item['url']}"
        if item.get("appeal"):
            line += f"\n   訴求軸: {item['appeal']}"
        lines.append(line)

    return "\n".join(lines)
