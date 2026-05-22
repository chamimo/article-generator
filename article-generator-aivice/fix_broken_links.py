"""
リンク切れ削除スクリプト

指定した WordPress 記事のリンク切れ（HTTP 4xx/5xx）を検出し、
<a> タグを除去してアンカーテキストのみ残す。
"""
import os
import re
import sys
import time
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

WP_URL      = os.getenv("WP_URL", "https://workup-ai.com").rstrip("/")
WP_USERNAME = os.getenv("WP_USERNAME", "")
WP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")

AUTH    = HTTPBasicAuth(WP_USERNAME, WP_PASSWORD)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; link-checker/1.0)"}

TARGET_URLS = [
    "https://workup-ai.com/midjourney-promotion-code-guide-2025/",
    "https://workup-ai.com/midjourney-web-guide/",
    "https://workup-ai.com/nanobanana-ai-image-google/",
    "https://workup-ai.com/neuro-dive-online-hiyou/",
    "https://workup-ai.com/nijijourney-commercial-use-guide/",
    "https://workup-ai.com/nolang-shouyou-riyou/",
    "https://workup-ai.com/notta-bot-toha/",
    "https://workup-ai.com/notta-free-paid-difference/",
    "https://workup-ai.com/notta-kikensei/",
    "https://workup-ai.com/notta-muryou-jikan-guide/",
    "https://workup-ai.com/notta-troubleshooting-transcription/",
    "https://workup-ai.com/notta_kiken_anzen/",
    "https://workup-ai.com/obsidian-google-drive-sync/",
    "https://workup-ai.com/perplexity-ai-security-guide/",
    "https://workup-ai.com/pixverse-shouyou-riyou/",
    "https://workup-ai.com/plaud-note-device-vs-app-difference/",
    "https://workup-ai.com/plaud-note-pin-pro-hikaku/",
    "https://workup-ai.com/plaud-note-pro-%E6%9C%88%E9%A1%8D/",
    "https://workup-ai.com/plaud-note-pro-hikaku/",
    "https://workup-ai.com/plaud-note-pro-lowest-price/",
    "https://workup-ai.com/plaud-note-pro-review/",
    "https://workup-ai.com/plaud-notta-hikaku/",
    "https://workup-ai.com/plaudnote-tsukaikata/",
    "https://workup-ai.com/powerdirector-muryouban-logo-kesu/",
    "https://workup-ai.com/qanda-ai-shukudai-assistant/",
    "https://workup-ai.com/rork_aiapp_kaihatsu_gaiyou/",
    "https://workup-ai.com/runway-gen-4-ryoukin/",
    "https://workup-ai.com/runway-gen3-shouyou-riyou/",
    "https://workup-ai.com/sns-buzzschool-free-mailcourse/",
    "https://workup-ai.com/stable-diffusion-chara-kotei/",
    "https://workup-ai.com/stable-diffusion-haikei-dake-kaeru/",
    "https://workup-ai.com/stable-diffusion-jissha-prompt-guide/",
    "https://workup-ai.com/stable-diffusion-kao-dake-kaeru-guide/",
    "https://workup-ai.com/stable-diffusion-kyoucho-guide/",
    "https://workup-ai.com/stable-diffusion-pose-dake-kaeru/",
    "https://workup-ai.com/suno-ai-prompt-list/",
    "https://workup-ai.com/tokyo-it-shuroikou-support-ai/",
    "https://workup-ai.com/udio-shouyou-riyou-kigou/",
    "https://workup-ai.com/voicememo-noise-reduction-guid/",
    "https://workup-ai.com/voicememos-transcription-on-ipad-guide/",
]


def url_to_slug(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def get_post_by_slug(slug: str) -> dict | None:
    resp = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts",
        params={"slug": slug, "_fields": "id,slug,content,status", "context": "edit"},
        auth=AUTH,
        timeout=30,
    )
    resp.raise_for_status()
    posts = resp.json()
    return posts[0] if posts else None


def is_broken(href: str) -> bool:
    if not href.startswith("http"):
        return False
    try:
        r = requests.head(href, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code == 405:
            r = requests.get(href, headers=HEADERS, timeout=10, allow_redirects=True)
        return r.status_code >= 400
    except Exception:
        return True


def remove_broken_links(content: str) -> tuple[str, list[str]]:
    """<a href="...">text</a> のうちリンク切れを除去。テキストは残す。"""
    pattern = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    broken_found: list[str] = []
    replacements: list[tuple[str, str]] = []

    for m in pattern.finditer(content):
        href = m.group(1)
        inner = m.group(2)
        if is_broken(href):
            print(f"  [broken] {href}")
            broken_found.append(href)
            replacements.append((m.group(0), inner))
        else:
            print(f"  [ok]     {href}")
        time.sleep(0.3)

    for original, replacement in replacements:
        content = content.replace(original, replacement, 1)

    return content, broken_found


def update_post_content(post_id: int, new_content: str) -> None:
    resp = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=AUTH,
        json={"content": new_content},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"  => 更新完了 (post_id={post_id})")


def process(page_url: str, dry_run: bool = False) -> None:
    slug = url_to_slug(page_url)
    print(f"\n[{slug}]")

    post = get_post_by_slug(slug)
    if not post:
        print("  記事が見つかりません")
        return

    raw_content = post["content"]["raw"]
    new_content, broken = remove_broken_links(raw_content)

    if not broken:
        print("  リンク切れなし")
        return

    print(f"  リンク切れ {len(broken)} 件 → {'(dry-run: 更新スキップ)' if dry_run else '更新します'}")
    if not dry_run:
        update_post_content(post["id"], new_content)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[dry-run モード: WordPress は更新しません]\n")

    for url in TARGET_URLS:
        process(url, dry_run=dry_run)

    print("\n完了")
