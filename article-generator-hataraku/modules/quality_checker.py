"""
quality_checker.py
記事のSEO・AIO・E-E-A-T品質を下書き保存前にチェックし、
不足点と改善案を箇条書きで返すモジュール。
NGが3件以上の場合はメール通知を送信する。
"""
from __future__ import annotations
import os
import re
import smtplib
import textwrap
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

# メール送信のNG件数しきい値
_MAIL_NG_THRESHOLD = 3


# ────────────────────────────────────────────────────────────
# 内部ユーティリティ
# ────────────────────────────────────────────────────────────
def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _plain_text(content: str) -> str:
    """Gutenbergコメントとタグを除去した本文テキストを返す。"""
    text = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    return _strip_tags(text)


# ────────────────────────────────────────────────────────────
# 各チェック関数
# ────────────────────────────────────────────────────────────

def _check_definition(content: str, keyword: str) -> tuple[bool, str]:
    """冒頭 p ブロックに「○○とは〜」定義文があるか。"""
    first_p = re.search(r"<p>(.*?)</p>", content, re.DOTALL)
    if not first_p:
        return False, "冒頭にpブロックが見つかりません。定義文（「○○とは〜」形式）を追加してください。"
    first_text = _strip_tags(first_p.group(1))
    if "とは" in first_text:
        return True, ""
    kw_short = keyword.split()[0] if keyword else ""
    return False, (
        f"冒頭段落に定義文が見つかりません。"
        f"「{kw_short}とは、○○です。」形式の定義文を最初の文として追加してください。"
    )


def _check_h2_conclusion_first(content: str) -> tuple[bool, str]:
    """各H2直後にpブロックがあるか（結論ファースト）。"""
    h2_blocks = re.findall(
        r"<!-- wp:heading[^>]*-->.*?<h2[^>]*>.*?</h2>.*?<!-- /wp:heading -->(.*?)(?=<!-- wp:heading|$)",
        content, re.DOTALL,
    )
    missing = 0
    for block in h2_blocks:
        # H2の直後に100字以上のpブロックがあるか
        m = re.search(r"<p>(.*?)</p>", block, re.DOTALL)
        if not m or len(_strip_tags(m.group(1)).strip()) < 50:
            missing += 1
    if missing == 0:
        return True, ""
    return False, (
        f"{missing}個のH2冒頭に結論要約段落が不足しています。"
        "各H2の直後に「このセクションで何がわかるか」を1〜2文で先出しするpブロックを追加してください。"
    )


def _check_faq(content: str) -> tuple[bool, str]:
    """FAQブロックが存在し、5問以上・各回答200字以上か。"""
    if "wp:loos/faq" not in content and "faq_q" not in content:
        return False, "FAQセクションがありません。5〜7問・各回答200字以上のFAQを記事末尾に追加してください。"
    items = re.findall(
        r'<h4[^>]*class="faq_q"[^>]*>(.*?)</h4>\s*<div[^>]*class="faq_a"[^>]*>(.*?)</div>',
        content, re.DOTALL | re.IGNORECASE,
    )
    if len(items) < 5:
        return False, f"FAQが{len(items)}問しかありません（最低5問必要）。問数を増やしてください。"
    short = [i for i, (q, a) in enumerate(items, 1) if len(_strip_tags(a).strip()) < 200]
    if short:
        return False, f"FAQ {short} 番の回答が200字未満です。各回答を200字以上に充実させてください。"
    return True, ""


def _check_comparison_table(content: str) -> tuple[bool, str]:
    """比較表（wp:table）が1箇所以上あるか。"""
    count = len(re.findall(r"<!-- wp:table", content))
    if count == 0:
        return False, "比較表（wp:tableブロック）がありません。ツール・プラン・対象者などを比較する表を1箇所以上追加してください。"
    return True, ""


def _check_testimonials(content: str) -> tuple[bool, str]:
    """一人称体験談が2〜3箇所あるか。"""
    patterns = [
        r"実際に(使|試|確認|検証|調べ)",
        r"(使って|試して)(みた|みたところ|みると)",
        r"(感じたのは|感じました|感じたこと)",
        r"私(が|は|の)(実際|試|使)",
        r"(経験|体験)(して|した|から)",
        r"(触って|さわって)みた",
    ]
    count = sum(
        bool(re.search(p, _plain_text(content)))
        for p in patterns
    )
    if count < 2:
        return False, (
            f"一人称体験談が{count}箇所しかありません（2〜3箇所必要）。"
            "「実際に使ってみたところ〜」「試してみて感じたのは〜」など自然な体験文を2〜3箇所追加してください。"
        )
    return True, ""


def _check_vague_expressions(content: str) -> tuple[bool, str]:
    """曖昧・逃げ表現がないか。"""
    vague = [
        "諸説あります", "諸説ございます",
        "場合によります", "場合によっては一概に",
        "一概に言えません", "一概には言えません",
        "かもしれません。", "でしょうか。",
        "〜と言われています。", "とも言われています",
    ]
    found = [v for v in vague if v in content]
    if found:
        return False, (
            f"曖昧表現が{len(found)}箇所あります（{', '.join(found[:3])}）。"
            "断言文（「〜です」「〜が必要です」）に書き換えてください。"
        )
    return True, ""


def _check_external_sources(content: str) -> tuple[bool, str]:
    """信頼できる外部ソースへのリンクがあるか。"""
    trusted_domains = [
        "google.com", "mhlw.go.jp", "go.jp", "wikipedia.org",
        "nikkei.com", "itmedia.co.jp", "techcrunch.com",
        "openai.com", "anthropic.com", "microsoft.com",
    ]
    links = re.findall(r'href="(https?://[^"]+)"', content)
    external = [l for l in links if not any(d in l for d in ["workup-ai.com", "hataraku-navi.com",
        "ys-trend.com", "kaerudoko.com", "hapipo8.com", "hida-no-omoide.com", "web-study1.com"])]
    has_trusted = any(any(d in l for d in trusted_domains) for l in external)
    if not external:
        return False, "外部リンクが1つもありません。信頼性の高いソース（公式サイト・官公庁・大手メディア等）へのリンクを1〜3件追加してください。"
    if not has_trusted:
        return None, "外部リンクはありますが、Google公式・官公庁など信頼性の高いソースへの言及があるとE-E-A-Tが向上します。"  # type: ignore[return-value]
    return True, ""


def _check_keyword_density(content: str, keyword: str) -> tuple[bool, str]:
    """キーワードが不自然に詰め込まれていないか（2〜4%目安）。"""
    if not keyword:
        return True, ""
    plain = _plain_text(content)
    total_chars = len(plain)
    if total_chars == 0:
        return True, ""
    kw_count = plain.count(keyword)
    density = kw_count / total_chars * 100
    if density > 5:
        return False, (
            f"キーワード「{keyword}」の出現頻度が高すぎます（{kw_count}回 / {density:.1f}%）。"
            "自然な日本語の流れを優先し、同義語・関連語に言い換えてください。"
        )
    return True, ""


def _check_paragraph_length(content: str) -> tuple[bool, str]:
    """段落が長すぎないか（スマホ可読性）。"""
    paragraphs = re.findall(r"<p>(.*?)</p>", content, re.DOTALL)
    long_paras = [
        len(_strip_tags(p).strip())
        for p in paragraphs
        if len(_strip_tags(p).strip()) > 250
    ]
    if len(long_paras) > 3:
        return False, (
            f"{len(long_paras)}箇所の段落が250字超えています。"
            "スマホ読みやすさのため、1段落は120〜200字を目安に分割してください。"
        )
    return True, ""


def _check_meta_description(article: dict) -> tuple[bool, str]:
    """メタディスクリプションが80〜120字あるか。"""
    desc = article.get("meta_description") or article.get("seo_description") or ""
    desc = desc.strip()
    if not desc:
        return False, "メタディスクリプションがありません。キーワード・得られるメリット・数字を含む80〜120字の文章を設定してください。"
    if len(desc) < 80:
        return False, f"メタディスクリプションが短すぎます（{len(desc)}字）。80〜120字に拡充してください。"
    if len(desc) > 140:
        return False, f"メタディスクリプションが長すぎます（{len(desc)}字）。120字以内に収めてください。"
    return True, ""


def _check_title_keyword(article: dict, keyword: str) -> tuple[bool, str]:
    """タイトルにメインキーワードが含まれているか。"""
    title = article.get("title", "")
    kw_parts = keyword.split() if keyword else []
    if not kw_parts:
        return True, ""
    # キーワードの主要単語（最初の2語）がタイトルに含まれるか
    main_kw = kw_parts[0]
    if main_kw.lower() not in title.lower():
        return False, (
            f"タイトルにメインキーワード「{main_kw}」が含まれていません。"
            "タイトル前半にキーワードを自然に組み込んでください。"
        )
    return True, ""


def _check_cta(content: str) -> tuple[bool, str]:
    """CV導線（CTA・比較・ボタンブロック）があるか。"""
    has_cta = bool(re.search(
        r"(wp:loos/btn|wp:button|wp:buttons|登録|無料で|今すぐ|申し込|始めて|試して)",
        content,
    ))
    if not has_cta:
        return None, "CTA（ボタン・登録誘導・比較表への誘導）が見当たりません。読者を次のアクションに導くCTAを1〜2箇所追加するとCV率が向上します。"  # type: ignore[return-value]
    return True, ""


# ────────────────────────────────────────────────────────────
# メイン関数
# ────────────────────────────────────────────────────────────

def check_article_quality(article: dict, keyword: str = "") -> list[str]:
    """
    記事の品質チェックを行い、不足点の改善案リストを返す。
    空リストなら全項目クリア。

    Parameters
    ----------
    article : dict
        generate_article() が返す記事辞書 (title, content, meta_description など)
    keyword : str
        メインキーワード文字列

    Returns
    -------
    list[str]
        不足点・改善案の箇条書きリスト。空なら全項目OK。
    """
    content = article.get("content", "")
    issues: list[str] = []

    checks = [
        ("□ 冒頭定義文",         _check_definition(content, keyword)),
        ("□ H2結論ファースト",   _check_h2_conclusion_first(content)),
        ("□ FAQセクション",      _check_faq(content)),
        ("□ 比較表",             _check_comparison_table(content)),
        ("□ 一人称体験談",       _check_testimonials(content)),
        ("□ 曖昧表現チェック",   _check_vague_expressions(content)),
        ("□ 外部ソースリンク",   _check_external_sources(content)),
        ("□ KW詰め込み",         _check_keyword_density(content, keyword)),
        ("□ 段落の長さ",         _check_paragraph_length(content)),
        ("□ メタディスクリプション", _check_meta_description(article)),
        ("□ タイトルKW",         _check_title_keyword(article, keyword)),
        ("□ CV導線",             _check_cta(content)),
    ]

    for label, (result, message) in checks:
        if result is True:
            pass  # OK
        elif result is False:
            issues.append(f"❌ {label}: {message}")
        else:  # None = 警告（推奨改善）
            issues.append(f"⚠️  {label}: {message}")

    return issues


def _load_mail_config() -> dict | None:
    """
    .env からメール設定を読み込む。
    必須項目が未設定の場合は None を返す。
    """
    # dotenv がなくても動くよう os.environ から直接取得
    cfg = {
        "mail_from":     os.environ.get("MAIL_FROM", "").strip(),
        "mail_to":       os.environ.get("MAIL_TO", "").strip(),
        "smtp_host":     os.environ.get("SMTP_HOST", "smtp.gmail.com").strip(),
        "smtp_port":     int(os.environ.get("SMTP_PORT", "587")),
        "smtp_user":     os.environ.get("SMTP_USER", "").strip(),
        "smtp_password": os.environ.get("SMTP_PASSWORD", "").strip(),
    }
    # 必須項目チェック
    if not all([cfg["mail_from"], cfg["mail_to"], cfg["smtp_user"], cfg["smtp_password"]]):
        return None
    return cfg


def _send_quality_alert(
    article: dict,
    issues: list[str],
    post_id: int | None = None,
    edit_url: str = "",
    logger=None,
) -> None:
    """
    NGが _MAIL_NG_THRESHOLD 件以上のときにメール通知を送信する。
    送信失敗しても例外を伝播させない。
    """
    ng_count = sum(1 for i in issues if i.startswith("❌"))
    if ng_count < _MAIL_NG_THRESHOLD:
        return

    _log  = logger.info    if logger else print
    _warn = logger.warning if logger else print

    # .env 読み込み（未設定ならスキップ）
    cfg = _load_mail_config()
    if not cfg:
        _warn("[quality] メール設定が未設定のため通知をスキップします（.envにMAIL_FROM等を設定してください）")
        return

    title    = article.get("title", "（タイトル不明）")
    now_str  = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    # ── 件名 ──────────────────────────────
    subject = f"【品質NG】{title}（{ng_count}件）"

    # ── 本文 ──────────────────────────────
    issues_text = "\n".join(f"  {i}" for i in issues)
    body = textwrap.dedent(f"""\
        品質チェックでNGが {ng_count} 件検出されました。
        下書き保存は完了していますが、公開前に以下を修正してください。

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        記事タイトル : {title}
        記事ID       : {post_id or "（取得前）"}
        チェック日時 : {now_str}
        編集URL      : {edit_url or "（投稿後に確認）"}
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        ■ NG・警告項目一覧

        {issues_text}

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ※ このメールは article-generator から自動送信されています。
    """)

    # ── メール送信（TLS） ─────────────────
    try:
        msg = MIMEMultipart()
        msg["From"]    = cfg["mail_from"]
        msg["To"]      = cfg["mail_to"]
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["smtp_user"], cfg["smtp_password"])
            smtp.sendmail(cfg["mail_from"], cfg["mail_to"].split(","), msg.as_string())

        _log(f"[quality] ✉️  品質NGメール送信完了 → {cfg['mail_to']}  件名: {subject}")

    except Exception as e:
        _warn(f"[quality] ✉️  メール送信失敗（チェック・投稿には影響なし）: {e}")


def log_quality_report(
    article: dict,
    keyword: str,
    logger=None,
    post_id: int | None = None,
    edit_url: str = "",
) -> list[str]:
    """
    品質チェックを実行し、結果をログ出力する。
    NGが _MAIL_NG_THRESHOLD 件以上の場合はメール通知も送信する。

    Parameters
    ----------
    article  : generate_article() が返す記事辞書
    keyword  : メインキーワード文字列
    logger   : ロガー（None なら print）
    post_id  : WordPress 投稿ID（投稿後に渡す場合）
    edit_url : WordPress 編集URL（投稿後に渡す場合）
    """
    _log  = logger.info    if logger else print
    _warn = logger.warning if logger else print

    issues = check_article_quality(article, keyword)
    ng_count   = sum(1 for i in issues if i.startswith("❌"))
    warn_count = sum(1 for i in issues if i.startswith("⚠️"))

    if not issues:
        _log(f"[quality] ✅ 品質チェック全項目クリア: 「{article.get('title', '')[:40]}」")
    else:
        _warn(
            f"[quality] 品質チェック: ❌{ng_count}件NG / ⚠️{warn_count}件警告"
            f" / 「{article.get('title', '')[:40]}」"
        )
        for issue in issues:
            _warn(f"[quality]   {issue}")

    # NG が閾値以上ならメール通知（失敗しても続行）
    try:
        _send_quality_alert(article, issues, post_id=post_id, edit_url=edit_url, logger=logger)
    except Exception as e:
        _warn(f"[quality] メール通知エラー（続行）: {e}")

    return issues
