# article-generator-hataraku

全7ブログの記事自動生成システム。`generate_lite.py` をベースに、`blogs/` 配下の設定で各ブログに対応する。

---

## 手動記事生成コマンド（全ブログ）

`article-generator-hataraku/` ディレクトリで実行する。

```bash
./run_daily.sh                # はた楽ナビ (hataraku-navi.com)
./run_daily.sh workup-ai      # AIVice (workup-ai.com)
./run_daily.sh ys-trend       # ワイズトレンド (ys-trend.com)
./run_daily.sh kaerudoko      # どこで売ってるナビ (kaerudoko.com)
./run_daily.sh hapipo8        # 気になることブログ (hapipo8.com)
./run_daily.sh hida-no-omoide # 飛騨の思い出 (hida-no-omoide.com)
./run_daily.sh web-study1     # オンライン学習ナビ (web-study1.com)
```

---

## Cronスケジュール

| 時刻 | 処理 |
|------|------|
| 毎日 03:00 | かにばりチェック（全ブログ） |
| 毎日 04:00 | workup-ai 記事生成 |
| 毎日 04:10 | ys-trend 記事生成 |
| 毎日 04:20 | hapipo8 記事生成 |
| 毎日 04:30 | kaerudoko 記事生成 |
| 毎日 04:50 | hataraku 記事生成 |
| 毎日 05:10 | hida-no-omoide 記事生成 |
| 毎日 05:30 | web-study1 記事生成 |
| 毎日 07:00 | SEO順位同期 |

---

## ディレクトリ構成

```
article-generator-hataraku/
├── generate_lite.py        # メイン記事生成スクリプト
├── run_daily.sh            # 記事生成ラッパー（全ブログ共通）
├── run_kanikabari.sh       # かにばりチェック（週次→毎日 03:00）
├── blogs/                  # ブログ設定
│   ├── hataraku/
│   ├── workup-ai/
│   ├── ys-trend/
│   ├── kaerudoko/
│   ├── hapipo8/
│   ├── hida-no-omoide/
│   └── web-study1/
├── modules/                # 共通モジュール
└── output/                 # ログ・実行結果
```
