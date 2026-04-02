"""
Step 5: Pollinations.aiでアイキャッチ画像を生成
"""
import time
import requests
from urllib.parse import quote

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 630


def generate_image(prompt: str, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> bytes:
    """
    Pollinations.aiでプロンプトから画像を生成し、バイト列で返す。
    """
    # ネガティブ要素をプロンプトに追加して品質向上
    full_prompt = (
        f"{prompt}, professional blog header, high quality, modern design, "
        "clean background, no watermark, no text overlay"
    )
    encoded = quote(full_prompt)
    url = f"{POLLINATIONS_BASE}/{encoded}?width={width}&height={height}&nologo=true&model=flux"

    print(f"[image_generator] 画像生成中 (Pollinations.ai)...")

    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type:
                raise ValueError(f"画像以外のレスポンス: {content_type}")
            print(f"[image_generator] 完了 ({len(resp.content) // 1024}KB)")
            return resp.content
        except Exception as e:
            if attempt < 2:
                print(f"[image_generator] リトライ {attempt + 1}/3: {e}")
                time.sleep(5)
            else:
                raise RuntimeError(f"Pollinations.ai画像生成失敗: {e}") from e
