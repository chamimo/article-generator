"""
接続テストスクリプト: .envの設定確認 + WordPress接続テスト
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def check_env():
    print("=" * 50)
    print("【.env 設定確認】")
    print("=" * 50)

    checks = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "WP_URL":            os.getenv("WP_URL", ""),
        "WP_USERNAME":       os.getenv("WP_USERNAME", ""),
        "WP_APP_PASSWORD":   os.getenv("WP_APP_PASSWORD", ""),
        "GOOGLE_SHEETS_ID":  os.getenv("GOOGLE_SHEETS_ID", ""),
    }

    all_ok = True
    for key, val in checks.items():
        if not val or val.startswith("your_") or "xxxx" in val:
            print(f"  [NG] {key}: 未設定")
            all_ok = False
        else:
            masked = val[:6] + "..." + val[-4:] if len(val) > 12 else "****"
            print(f"  [OK] {key}: {masked}")

    return all_ok


def test_wordpress():
    import requests
    from requests.auth import HTTPBasicAuth

    wp_url      = os.getenv("WP_URL", "").rstrip("/")
    wp_user     = os.getenv("WP_USERNAME", "")
    wp_password = os.getenv("WP_APP_PASSWORD", "")

    print("\n" + "=" * 50)
    print("【WordPress 接続テスト】")
    print("=" * 50)

    # 1. REST API エンドポイント疎通確認
    api_url = f"{wp_url}/wp-json/wp/v2"
    print(f"\n[1] REST API エンドポイント確認: {api_url}")
    try:
        r = requests.get(f"{wp_url}/wp-json/", timeout=10)
        if r.status_code == 200:
            print(f"  [OK] サイトへの接続成功 (HTTP {r.status_code})")
        else:
            print(f"  [NG] HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"  [NG] 接続エラー: {e}")
        return False

    # 2. 認証テスト（/wp-json/wp/v2/users/me）
    print(f"\n[2] 認証テスト (ユーザー: {wp_user})")
    try:
        r = requests.get(
            f"{wp_url}/wp-json/wp/v2/users/me",
            auth=HTTPBasicAuth(wp_user, wp_password),
            timeout=10,
        )
        if r.status_code == 200:
            user_data = r.json()
            print(f"  [OK] 認証成功")
            print(f"       ユーザーID  : {user_data.get('id')}")
            print(f"       表示名      : {user_data.get('name')}")
            print(f"       ロール      : {user_data.get('roles', [])}")
        elif r.status_code == 401:
            print(f"  [NG] 認証失敗 (401): ユーザー名またはアプリケーションパスワードが違います")
            return False
        elif r.status_code == 403:
            print(f"  [NG] 権限エラー (403): このユーザーには投稿権限がありません")
            return False
        else:
            print(f"  [NG] HTTP {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  [NG] エラー: {e}")
        return False

    # 3. カテゴリ確認
    print(f"\n[3] カテゴリ確認")
    try:
        r = requests.get(
            f"{wp_url}/wp-json/wp/v2/categories",
            auth=HTTPBasicAuth(wp_user, wp_password),
            timeout=10,
        )
        if r.status_code == 200:
            cats = r.json()
            print(f"  [OK] カテゴリ一覧 ({len(cats)}件):")
            for c in cats[:5]:
                print(f"       ID:{c['id']} 「{c['name']}」")
            if len(cats) > 5:
                print(f"       ... 他{len(cats)-5}件")
        else:
            print(f"  [NG] HTTP {r.status_code}")
    except Exception as e:
        print(f"  [WARN] カテゴリ取得失敗: {e}")

    # 4. 投稿権限確認（下書き一覧取得）
    print(f"\n[4] 投稿権限確認")
    try:
        r = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts?status=draft&per_page=1",
            auth=HTTPBasicAuth(wp_user, wp_password),
            timeout=10,
        )
        if r.status_code == 200:
            print(f"  [OK] 下書きの読み取り権限あり")
        else:
            print(f"  [WARN] HTTP {r.status_code} (投稿権限がない可能性)")
    except Exception as e:
        print(f"  [WARN] {e}")

    return True


if __name__ == "__main__":
    env_ok = check_env()
    if not env_ok:
        print("\n[ERROR] 未設定の項目があります。.envを確認してください。")
        sys.exit(1)

    wp_ok = test_wordpress()

    print("\n" + "=" * 50)
    if wp_ok:
        print("接続テスト: 成功  WordPress投稿の準備ができています。")
    else:
        print("接続テスト: 失敗  上記のエラーを確認してください。")
    print("=" * 50)
