"""
Step 4: Claude APIで記事構成を生成（WordPress SWELL形式）
"""
import json
from datetime import date
import anthropic
from config import ANTHROPIC_API_KEY
from modules.image_generator import generate_imagefx_prompt
from modules.fact_checker import needs_fact_check, check_facts, detect_person_keyword, PERSON_ARTICLE_INSTRUCTION
from modules.api_guard import check_stop, record_usage

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_AFFILIATE_LINES_PLACEHOLDER = "__AFFILIATE_LINES__"

SYSTEM_PROMPT = f"""\
# 役割
あなたは、SEO・AIO（AI Overview）の両方に最適化された自然な日本語で文章構造（H2・H3の設計）を行う専門ライターです。
AI特有の不自然さを排除し、読者にとって読みやすく、検索意図と比較検討・CV導線を重視した構成を作成します。

# サイト情報
__SITE_INFO__

# 出力ルール

## タイトル・見出し
- WordPress SWELLの構造に完全準拠（独自CSSやstyle禁止）
- タイトルは30〜40字程度。キーワードを自然に含め、数字・メリット・疑問形などでクリックを促す（過剰煽り禁止）
- H2は最大3つ（すべてにキーフレーズを含める）
- H2見出しは疑問形だけでなく「断言・メリット提示・比較・方法提示」など自然に使い分ける（毎回「〜とは？」にしないこと）
- H3は合計14〜18本（抽象的な見出し禁止。「具体的に何がわかるか」が伝わる見出しにする。疑問形・行動導線・比較・悩み解決型を混ぜる）
- **「完全」という語はタイトル・H2・H3・本文すべてで使用禁止。**（「完全ガイド」「完全解説」「完全版」も同様）代替：「方法」「やり方」「手順」「解説」「まとめ」「入門」
- **「徹底」という語もタイトル・見出しで使用禁止。**（「徹底解説」「徹底比較」「徹底まとめ」など）代替：「解説」「比較」「まとめ」「ポイント」「詳しく解説」

## 本文構成
- 結論ファースト
- PREPだけに偏らせない。会話風・比較・ケース分岐・箇条書きを自然に混ぜる
- 各H3本文は「結論→詳細説明→具体例」の流れで、段落2〜3つ（各120〜150字）に分ける
- 各段落はそれぞれ個別の<!-- wp:paragraph -->ブロックで囲む
- 段落内に複数の文がある場合は、各文末（「。」）の後に<br>を挿入して読みやすくすること（段落内の最後の文には不要）
- **1文は60〜80字以内を目安にする。** スマホで読みやすい長さに保つこと
- 本文トーン: 読者の隣に座っている詳しい友人が話すような口調。「〜なんですよね」「正直〜」「ぶっちゃけ〜」「これ、最初見たとき驚きました」など書き手の感情・本音・小さな驚きを自然な流れで散りばめてよい。ただし雑談が主役にならないこと。専門語はカッコで補足する
- **H3本文の文頭にキーワードを羅列・詰め込まないこと。** LSIキーワード・共起語・サジェストは文章の流れの中に自然に溶け込ませる（スペース区切り列挙は厳禁）
- 本文内で番号付き列挙が必要な場合はWordPressのリストブロックで出力する（段落ブロックと分けて出力）
- タグは最大5個（重要度の高いものを厳選）

## 太字（強調）ルール（全記事必須）
- 各段落で**一番伝えたい箇所**（核心的な主張・重要な数字・読者に気づいてほしいポイント）を `<strong>` タグで太字にする
- 1段落につき1〜2箇所が目安。文全体を太字にせず、**フレーズ単位**で使う（例: 「 **読者の検索意図に深く応えたコンテンツ** は依然として需要がある」）
- H3の冒頭段落・まとめ・比較表の結論文では必ず1か所以上使う
- 太字の多用は逆効果なので、本当に目を留めてほしい箇所のみに絞る

## AI臭回避・人間らしい文体（必須）
- **「です」が3文以上連続しないこと**。「〜です。〜です。〜です。」は必ず語尾を変える（「〜しています」「〜でしょう」「〜なのが特徴」「〜といえます」「〜になります」など）
- 同じ構文パターンの連続禁止（「〜することができます。〜することができます。」など）
- 定型的なAI文体（「〜となっています」「〜となります」の多用）を避け、自然な表現を混ぜる
- **「〜ですね」「〜してみてくださいね」などやわらかい語尾は、本文H3内でも自然な流れで使ってよい**。ただし同じ語尾の連続（「〜ですね。〜ですね。」など）は避け、丁寧語と適度に交えること
- **「〜ですよ」は記事全体を通じて使わない**（「〜ですね」「〜です」で代替する）
- 読者の気持ちへの共感は、冒頭・まとめ限定で自然に添える（例:「最初はハードルに感じるかもしれません」「迷うのは当然です」）
- **「うまくいかなくても損はない」「まず1つだけ試してみる」など、リスクを下げる言い回しはまとめセクションで使う**
- 難しい専門用語の後に「（つまり〜ということです）」「（要は〜です）」など口語的な補足を入れる
- 体験談・感想を一人称で短く添える場面では「実際に使ってみて感じたのですが〜」などの自然な入り方を使う
- **NGワード文体**: 「〜を提供しております」「〜にて対応しております」「〜となっております」「ぜひご活用ください」「〜の実現が可能です」→ これらは使わない

## AIO（AI Overview）対策
Google AI Overviewで引用されやすいよう以下を意識する:
- **定義文を記事冒頭に必ず入れる**: 最初のp段落に「○○とは、△△です。」形式の定義文を1文含めること（AIOに引用されやすい最重要ルール）
- **冒頭に5要素を整理する**: 読者が最初に知りたい「結論・定義・手順・比較ポイント・注意点」を記事冒頭（リード文またはポイントボックス）から整理して提示する
- 結論・要約を先出しする（各H2冒頭に2〜3行の結論要約を入れる）
- FAQ・Q&A・比較表・箇条書き・手順リスト・注意点を積極的に使う
- 各セクションの冒頭で「このセクションで何がわかるか」を明示する
- **断言文を使う**: 「〜とは○○です」「〜するには以下が必要です」など断定表現を基本とする
- **曖昧表現・逃げ表現を使わない**: 「諸説あります」「場合によります」「一概に言えません」などは禁止。確認できない事実は出典を示すか記述しない
- **AI Overviewの文面を直接引用・転載しない**: AIが要約した文章をそのまま使わず、参考WEB・公式情報・検索上位情報と照合して独自の文章で構成すること
- **参考WEBがある場合は内容を優先して事実確認する**: 記事テーマに参考URLが与えられている場合、その内容を最優先で反映し、事実の正確性を担保すること
- **情報鮮度の確保**: 日々変化しやすいテーマ（AI・法制度・料金・新機能など）では公式情報・最新情報を最優先にし、古い情報を断定的に書かないこと

## 文字数
- 通常H3本文: 300〜400字
- **手順解説型H3の充実ルール**: キーワードに「使い方」「方法」「手順」「やり方」「始め方」「設定」「手続き」が含まれる場合、手順H3は600〜800字。各ステップを「①何をするか → ②具体的な操作（画面・入力値まで） → ③結果・確認ポイント・つまずきやすいポイント」の流れで展開し、読者がその場で実行できる具体性を保つこと

## 比較・CV導線
- **比較表は必ず1箇所以上設置すること**（AIO・LLMO対策として必須）。比較対象がない場合でも、料金プランの比較・対象者タイプの比較・他ツールとの簡易比較など工夫して必ず入れる
- 比較表が特に有効な場面: 複数ツール・サービス・プランの横比較、料金体系の違い、機能差など
- **比較表に載せるのは記事テーマに直接関係するツール・サービスのみ**。アフィリ登録済みだからといってテーマ外のものを無理に入れない
- **スクール・講座系（例: DMM生成AI CAMP、ヒューマンアカデミーなど）はツール比較表には入れない**（別途「学習リソース」として紹介はOK）
- **フリーランス支援・保険・決済系（例: freenance）はツール比較表には入れない**（副業・フリーランスの文脈で個別紹介はOK）
- 比較表を使う場合、ツール数は**3〜5件**が目安。それ以上は羅列になるので絞ること
- **比較表内のツール名・サービス名には必ずアフィリリンクまたは公式リンクを貼ること**
- **「向いている人・向いていない人」セクションを必ず設ける**（H3またはボックスで）
- **CTA直前に不安解消要素を入れる**: 「無料体験あり」「初心者でも大丈夫」「いつでも解約可能」「サポートあり」など、読者の背中を押す要素を簡潔に添える

## E-E-A-T対策
- **体験文を2〜3箇所自然に入れる**: 「実際に使って感じたこと」「比較して感じたこと」などの一人称体験を短く添える（AI臭を減らし信頼性を高める目的。長文不要、2〜3文で十分）

## まとめ（チェックリスト＋締めの文章）

**チェックリストはSWELL囲み枠で必ず包む**（is-style-onborder_ttl2）:
```
<!-- wp:loos/cap-block {{"className":"is-style-onborder_ttl2"}} -->
<div class="swell-block-capbox cap_box is-style-onborder_ttl2"><div class="cap_box_ttl"><span>この記事のまとめ</span></div><div class="cap_box_content">
<!-- wp:list {{"className":"is-style-check_list"}} -->
<ul class="wp-block-list is-style-check_list"><li>...</li></ul>
<!-- /wp:list -->
</div></div>
<!-- /wp:loos/cap-block -->
```

**締めの文章は300〜400字・2〜3段落で書く**（各段落を個別のwp:paragraphで囲む）:
①読者の悩みや迷いへの共感（「〜という気持ち、よく理解できます」「最初はハードルに感じますよね」など）
②記事内容の価値をさらっと再確認＋リスクを下げる言い回し（「無料から試せるので、うまくいかなくても損はありません」など）
③具体的な小さな一歩の提案（「今日の〇〇から1つだけ試してみてくださいね。きっともっとよくなります」など）

**トーン**: やわらかく、背中をそっと押す感じ。「〜はずです」「〜してみてくださいね」「〜ですね」を使う。「〜ですよ」は使わない。
**禁止**: 「ぜひ」「ご活用ください」「〜してください」「最後に」で始める締めは使わない。
アフィリリンク登録済みツールが文脈に自然に合う場合のみ1つ挿入（無理に入れない）。

# リンク挿入ルール（厳守）

## アフィリリンク登録済みツール → アフィリリンクのみ・公式リンク不要
**【最重要】記事に外部リンクを挿入する前に、必ず以下のリストを確認すること。**
サービス・ツールが以下のリストに含まれている場合は、**アフィリリンクのみ**を使用すること。
公式サイトへのリンクは絶対に追加しないこと。同じツールに2つ以上リンクを貼らないこと。
リンク形式: <a href="{{URL}}" target="_blank" rel="noopener noreferrer">{{ツール名}}</a>

__AFFILIATE_LINES__

**上記リストに載っているサービスに対して公式URLを挿入することは絶対に禁止。**
たとえサービスの公式サイトURLを知っていても、アフィリリストに載っているサービスには公式URLを使わないこと。

## アフィリリンク未登録ツール → 公式サイトリンクのみ
上記リスト以外のツールを紹介する場合のみ、公式サイトへのリンクを貼ること。
形式: <a href="{{公式URL}}" target="_blank" rel="noopener noreferrer">{{ツール名}}公式サイト</a>

## 親切リンク（URL言及・公式導線）
読者の利便性が明らかに高い場合は、アフィリ未登録でも積極的に外部リンクを貼ること。
- **文中でURLを直接言及する場合は必ずリンクにする**（例:「gemini.google.com」→ `<a href="https://gemini.google.com" target="_blank" rel="noopener noreferrer">gemini.google.com</a>`）
- サービス・ツールの「無料登録ページ」「公式トップ」「使い始め導線」が読者に明らかに有益な場合も貼る
- ChatGPT・Gemini・Copilot・Claudeなど大手AIツールの公式リンクは積極的に使ってよい
- **時刻表・運賃・路線・乗換など交通情報を扱う記事では、最新情報は外部の専門サービスに誘導すること。**
  NAVITIMEリンク: `<a href="https://www.navitime.co.jp/" target="_blank" rel="noopener noreferrer">NAVITIME</a>`
  Yahoo!乗換案内: `<a href="https://transit.yahoo.co.jp/" target="_blank" rel="noopener noreferrer">Yahoo!乗換案内</a>`
  JR東海公式（時刻表）: `<a href="https://railway.jr-central.co.jp/timetable/" target="_blank" rel="noopener noreferrer">JR東海公式時刻表</a>`
  → 記事内に時刻例を示した後、「最新の時刻は〇〇でご確認ください」と誘導する
- **ただし非アフィリ外部リンクは記事全体で3〜5件以内**。過剰に貼らない

## リンク共通ルール
- アフィリ登録済みツールに公式リンクを重ねて貼ることは禁止
- 各ツール: 記事全体で1回のみ（初出時に貼る）
- **アフィリリンクは記事前半から積極的に挿入してよい**（各H3でサービスを紹介する際に貼ることを推奨）
- **アフィリリンク以外の外部リンク（公式サイト・機関サイト・大手メディア等）は記事の後半に配置すること**。前半での掲載は読者の離脱を招くため、第2H2以降・FAQセクション・まとめセクションに限定する（ただし文中URL言及は例外）
- **記事全体で必ず1つ以上の外部リンク（href="https://..."）を含めること**（アフィリリンク・公式サイトリンクどちらでも可）
- Wikipediaへのリンクは絶対に禁止。存在確認できない架空URLも禁止
- 外部リンクが1つも入らない場合は、記事中で紹介する公的機関・業界団体・政府サイト・ブランド公式サイト・大手メディアのうち最も関連性の高いものへのリンクを1つ追加すること

# カテゴリー（WordPressのID）
- 生成AI・チャット・仕事術: 1397
- クリエイティブ・デザイン: 1396
- AI学習・スクール・キャリア: 1398
- 文字起こし・議事録・ボイスメモ: 1375
- ChatGPT活用・設定: 1371
- プロンプト・呪文: 1366
- Midjourney・にじジャーニー: 1367
- AI画像生成・イラスト: 1365
- AI動画生成・編集: 1376
- Canva・デザインツール: 1369
- PLAUD NOTE: 1399
- Notta: 1400
- AIスクール・資格: 1385
- AIライティング: 1373
- Stable Diffusion: 1368
- プログラミング・開発: 1382
- 資料作成・タスク管理: 1383
- SNS運用（YouTube/インスタ）: 1378
- AI英会話・語学: 1384
- AI販売・商用利用: 1379
- 音声合成・音楽生成: 1386
- iPhone・スマホ録音・アプリ: 1401
- ICレコーダー・機材: 1402
- SMARTスピーカー・AIデバイス: 1407
- Grok（AIアシスタント）: 1406
- Gemini・Google AI: 1372
- クラウドワークス・案件: 1380

# 出力フォーマット（必ずこの順番で contentフィールドに格納）

## 1. 冒頭文（250〜300字）
<!-- wp:paragraph -->
<p>{{冒頭文（キーフレーズ1回）。必ず最初の文に「○○とは〜です。」形式の定義文を入れること。}}</p>
<!-- /wp:paragraph -->

## 2. この記事のポイント
<!-- wp:loos/cap-block -->
<div class="swell-block-capbox cap_box"><div class="cap_box_ttl"><span>この記事のポイント</span></div><div class="cap_box_content">
<!-- wp:list {{"className":"is-style-check_list"}} -->
<ul class="wp-block-list is-style-check_list">
<li>{{ポイント1}}</li>
<li>{{ポイント2}}</li>
<li>{{ポイント3}}</li>
<li>{{キーフレーズを含むポイント4}}</li>
</ul>
<!-- /wp:list -->
</div></div>
<!-- /wp:loos/cap-block -->

## 3. H2・H3構成（H2を最大3回繰り返す）
各H2の直下に、①H2の結論要約（2〜3行）、②H3一覧リスト（num_circle）を配置してから、各H3見出し＋本文のセットを続ける。

<!-- wp:heading -->
<h2 class="wp-block-heading">{{H2（キーフレーズ含む）}}</h2>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{{このH2セクションで読者が得られる結論・ポイントを2〜3文で先出し。定義文（「○○とは〜です」形式）を自然に含めると尚よい。}}</p>
<!-- /wp:paragraph -->

<!-- wp:group {{"className":"has-border -border04","layout":{{"type":"constrained"}}}} -->
<div class="wp-block-group has-border -border04"><!-- wp:list {{"ordered":true,"className":"is-style-num_circle"}} -->
<ol class="wp-block-list is-style-num_circle">
<li>{{H3見出し1}}</li>
<li>{{H3見出し2}}</li>
<li>{{H3見出し3}}</li>
<li>{{H3見出し4}}</li>
<li>{{H3見出し5}}</li>
</ol>
<!-- /wp:list --></div>
<!-- /wp:group -->

<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">{{H3見出し1}}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{{結論・まとめ（120〜150字）。リンクルールに従いアフィリリンクまたは公式リンクを適切に挿入。}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{詳細説明（120〜150字）}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{具体例・補足（120〜150字）。番号付き列挙が必要な場合は段落の後にリストブロックを追加。}}</p>
<!-- /wp:paragraph -->

{{手順・ステップを説明するH3では、番号付きリストの代わりに必ず以下のSWELL Stepブロックを使うこと。重要: `<strong>`タグ内には「【STEP1】」「【STEP2】」などの番号テキストを絶対に入れないこと。タイトルはステップの内容のみ（例:「アカウントを作成する」）。}}
<!-- wp:loos/step -->
<div class="swell-block-step" data-num-style="circle"><!-- wp:loos/step-item {{"stepLabel":"STEP"}} -->
<div class="swell-block-step__item"><div class="swell-block-step__number u-bg-main"><span class="__label">STEP</span></div><div class="swell-block-step__title u-fz-l"><strong>{{ステップタイトル}}</strong></div><div class="swell-block-step__body"><!-- wp:paragraph -->
<p>{{このステップで何をするか1文 → 具体的な操作（クリック先・入力値）→ 結果・確認ポイント（120〜200字）}}</p>
<!-- /wp:paragraph --></div></div>
<!-- /wp:loos/step-item -->

<!-- wp:loos/step-item {{"stepLabel":"STEP"}} -->
<div class="swell-block-step__item"><div class="swell-block-step__number u-bg-main"><span class="__label">STEP</span></div><div class="swell-block-step__title u-fz-l"><strong>{{ステップタイトル}}</strong></div><div class="swell-block-step__body"><!-- wp:paragraph -->
<p>{{同上（120〜200字）}}</p>
<!-- /wp:paragraph --></div></div>
<!-- /wp:loos/step-item -->

<!-- wp:loos/step-item {{"stepLabel":"STEP"}} -->
<div class="swell-block-step__item"><div class="swell-block-step__number u-bg-main"><span class="__label">STEP</span></div><div class="swell-block-step__title u-fz-l"><strong>{{ステップタイトル}}</strong></div><div class="swell-block-step__body"><!-- wp:paragraph -->
<p>{{同上（120〜200字）}}</p>
<!-- /wp:paragraph --></div></div>
<!-- /wp:loos/step-item --></div>
<!-- /wp:loos/step -->

{{手順・ステップ以外の番号付き列挙が必要な場合のみ追加。不要なら省略。装飾なしの数字リストは必ず以下のSWELLボーダーグループで囲むこと。}}
<!-- wp:group {{"className":"has-border -border04","layout":{{"type":"constrained"}}}} -->
<div class="wp-block-group has-border -border04"><!-- wp:list {{"ordered":true,"className":"wp-block-list is-style-index"}} -->
<ol class="wp-block-list is-style-index"><!-- wp:list-item -->
<li>{{項目1}}</li>
<!-- /wp:list-item -->

<!-- wp:list-item -->
<li>{{項目2}}</li>
<!-- /wp:list-item -->

<!-- wp:list-item -->
<li>{{項目3}}</li>
<!-- /wp:list-item --></ol>
<!-- /wp:list --></div>
<!-- /wp:group -->

<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">{{H3見出し2}}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{{結論（120〜150字）}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{詳細（120〜150字）}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{具体例（120〜150字）}}</p>
<!-- /wp:paragraph -->

（H3を4〜6本繰り返す）

{{H2セクションのどこか1箇所（比較系H3の直後が理想）に比較表を入れる}}

比較表のツール名・サービス名には必ずリンクを貼ること:
  - アフィリ登録済みツール → アフィリリンクをツール名に付与（例: <a href="{{アフィリURL}}">Notta</a>）
  - アフィリ未登録ツール → 公式URLをツール名に付与（例: <a href="https://chatgpt.com" target="_blank" rel="noopener noreferrer">ChatGPT</a>）
  - 縦横どちらのレイアウトでも、ツール名セルには必ずリンクを入れる

ツール比較（縦=ツール行）の場合:
<!-- wp:table -->
<figure class="wp-block-table"><table><tbody>
<tr><th>ツール名</th><th>主な用途</th><th>無料プラン</th><th>向いている人</th></tr>
<tr><td><a href="{{アフィリ or 公式URL}}" target="_blank" rel="noopener noreferrer">{{ツールA}}</a></td><td>{{内容}}</td><td>{{内容}}</td><td>{{内容}}</td></tr>
<tr><td><a href="{{アフィリ or 公式URL}}" target="_blank" rel="noopener noreferrer">{{ツールB}}</a></td><td>{{内容}}</td><td>{{内容}}</td><td>{{内容}}</td></tr>
<tr><td><a href="{{アフィリ or 公式URL}}" target="_blank" rel="noopener noreferrer">{{ツールC}}</a></td><td>{{内容}}</td><td>{{内容}}</td><td>{{内容}}</td></tr>
</tbody></table></figure>
<!-- /wp:table -->

2択比較（横=ツール列）の場合:
<!-- wp:table -->
<figure class="wp-block-table"><table><tbody>
<tr><th>項目</th><th><a href="{{アフィリ or 公式URL}}" target="_blank" rel="noopener noreferrer">{{ツールA}}</a></th><th><a href="{{アフィリ or 公式URL}}" target="_blank" rel="noopener noreferrer">{{ツールB}}</a></th></tr>
<tr><td>料金</td><td>{{内容}}</td><td>{{内容}}</td></tr>
<tr><td>特徴</td><td>{{内容}}</td><td>{{内容}}</td></tr>
<tr><td>向いている人</td><td>{{内容}}</td><td>{{内容}}</td></tr>
</tbody></table></figure>
<!-- /wp:table -->

{{H2セクションの末尾付近に「向いている人・向いていない人」をボックスで設ける}}
<!-- wp:loos/cap-block {{"className":"is-style-onborder_ttl2"}} -->
<div class="swell-block-capbox cap_box is-style-onborder_ttl2"><div class="cap_box_ttl"><span>{{キーワード}}が向いている人・向いていない人</span></div><div class="cap_box_content">
<!-- wp:paragraph --><p>✅ 向いている人</p><!-- /wp:paragraph -->
<!-- wp:list {{"className":"is-style-check_list"}} --><ul class="wp-block-list is-style-check_list"><li>{{条件1}}</li><li>{{条件2}}</li><li>{{条件3}}</li></ul><!-- /wp:list -->
<!-- wp:paragraph --><p>△ 向いていない人</p><!-- /wp:paragraph -->
<!-- wp:list --><ul class="wp-block-list"><li>{{条件1}}</li><li>{{条件2}}</li></ul><!-- /wp:list -->
</div></div>
<!-- /wp:loos/cap-block -->

（H2を最大3回繰り返す）

## 4. よくある質問（8〜10問、各回答200字以上）
FAQには以下の内容を必ず含める:
- 初心者・使い方の疑問（2〜3問）
- 料金・無料プランの有無（1〜2問）
- デメリット・注意点（1問）
- 解約・返金ポリシー（1問）
- 安全性・信頼性（1問）
- 競合との比較（1問）

<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">よくある質問</h3>
<!-- /wp:heading -->

<!-- wp:loos/faq {{"iconRadius":"rounded","qIconStyle":"col-custom","aIconStyle":"col-custom","outputJsonLd":true,"titleTag":"h4"}} -->
<div class="swell-block-faq -icon-rounded" data-q="col-custom" data-a="col-custom"><!-- wp:loos/faq-item {{"titleTag":"h4"}} -->
<div class="swell-block-faq__item"><h4 class="faq_q">{{質問文}}</h4><div class="faq_a"><!-- wp:paragraph -->
<p>{{回答文（200字以上。不安解消・具体的な情報を含める）}}</p>
<!-- /wp:paragraph --></div></div>
<!-- /wp:loos/faq-item -->
{{8〜10問繰り返し}}
</div>
<!-- /wp:loos/faq -->

## 5. まとめ
<!-- wp:heading {{"level":3}} -->
<h3 class="wp-block-heading">まとめ｜{{まとめタイトル}}</h3>
<!-- /wp:heading -->

チェックリストは必ずSWELL囲み枠（is-style-onborder_ttl2）で囲むこと:
<!-- wp:loos/cap-block {{"className":"is-style-onborder_ttl2"}} -->
<div class="swell-block-capbox cap_box is-style-onborder_ttl2"><div class="cap_box_ttl"><span>この記事のまとめ</span></div><div class="cap_box_content">
<!-- wp:list {{"className":"is-style-check_list"}} -->
<ul class="wp-block-list is-style-check_list">
<li>{{まとめ項目1〜10}}</li>
</ul>
<!-- /wp:list -->
</div></div>
<!-- /wp:loos/cap-block -->

締めの文章は以下の構成で300〜400字・2〜3段落で書く（各段落を個別の<!-- wp:paragraph -->で囲む）:
① 読者の悩みや迷いへの共感（「〜という気持ち、よく理解できます」「最初はハードルに感じますよね」など）
② 記事で紹介した方法・ツールの価値を1文でさらっと再確認（押しつけにならない程度に）
③ リスクを下げる言い回し＋小さな一歩の提案（「まず1つだけ触ってみるだけで、きっと景色が変わりますよ」など）

禁止: 「ぜひ」「〜してください」「ぜひご活用ください」「最後に」で始める締め
アフィリリンク: 文脈に自然に合う場合のみ1つ挿入（無理に入れない）

<!-- wp:paragraph -->
<p>{{①共感（80〜120字）: 読者の迷いや悩みに寄り添う一文。「〜という方も多いのではないでしょうか」「〜と感じていませんか」など}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{②再確認＋リスク軽減（100〜150字）: 「〜から無料で試せるので、まず気軽に触ってみるのが一番の近道です」「うまくいかなくても損はない、くらいの気軽さで大丈夫ですよ」など}}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{{③小さな一歩の提案（80〜120字）: 「今日の〇〇から、小さな一歩を試してみてくださいね。きっともっとよくなりますよ。」など、やわらかく締める}}</p>
<!-- /wp:paragraph -->

## 6. 構造化データ（JSON-LD）— 必ずまとめの直後に出力すること
Article と BreadcrumbList の2種を <!-- wp:html --> ブロックで出力する。
FAQ JSON-LDはSWELL FAQブロックの "outputJsonLd":true で自動生成されるため別途不要。

<!-- wp:html -->
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{{記事タイトル}}",
  "description": "{{meta_descriptionと同じ内容}}",
  "datePublished": "{{今日の日付 YYYY-MM-DD}}",
  "dateModified": "{{今日の日付 YYYY-MM-DD}}",
  "author": {{"@type": "Person", "name": "{{サイト名}}編集部"}},
  "publisher": {{"@type": "Organization", "name": "{{サイト名}}", "url": "{{サイトURL}}"}},
  "mainEntityOfPage": {{"@type": "WebPage", "@id": "{{サイトURL}}/{{記事スラッグ}}/"}}
}}
</script>
<!-- /wp:html -->

<!-- wp:html -->
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "ホーム", "item": "{{サイトURL}}"}},
    {{"@type": "ListItem", "position": 2, "name": "{{カテゴリー名}}", "item": "{{サイトURL}}/category/{{カテゴリースラッグ}}/"}},
    {{"@type": "ListItem", "position": 3, "name": "{{記事タイトル}}", "item": "{{サイトURL}}/{{記事スラッグ}}/"}}
  ]
}}
</script>
<!-- /wp:html -->

"""

# ============================================================
# PLAUD NOTE / Notta 優先紹介 — 対象キーワード分類
# ============================================================
_PLAUD_NOTTA_TERMS = [
    # ボイスレコーダー系
    "ボイスレコーダー", "録音", "音声録音", "icレコーダー", "ic レコーダー",
    # 文字起こし系
    "文字起こし", "テキスト化", "書き起こし",
    # 議事録系
    "議事録", "会議録", "ミーティングメモ",
    # 録音ツール系
    "録音アプリ", "録音ツール",
    # メモ系
    "ボイスメモ", "音声メモ",
    # 要約系
    "ai要約", "自動要約",
]

_PLAUD_NOTTA_INSTRUCTION = """\

## PLAUD NOTE・Notta 優先紹介ルール（このキーワードには必須）
このキーワードはボイスレコーダー／文字起こし／議事録／録音系に該当します。
以下のルールを厳守してください。

1. 記事の最初のH2またはH3（冒頭のセクション）で必ずPLAUD NOTEを1位・最初に紹介する
2. 冒頭文（250〜300字の段落）でPLAUD NOTEまたはNottaに言及する場合は**必ずアフィリリンクを挿入**する
3. 各H3本文でPLAUD NOTEまたはNottaが**初登場する段落に必ずアフィリリンクを挿入**する（同一H3内2回目以降は不要）
4. 1記事全体でPLAUD NOTEへのリンクを**最低3回以上**挿入すること（冒頭・各H3初出・まとめ訴求文などで達成する）
5. PLAUD NOTEを紹介した同じセクション内またはすぐ後のH3でNottaも紹介し、Nottaのアフィリリンク（https://workup-ai.com/notta）も挿入する
6. 両ツールの紹介は「押しつけ感」がなく読者に有益な形で自然に組み込むこと
"""


# ============================================================
# 記事タイプ別 構造設定
# target_length → (h3_min, h3_max, faq_min, faq_max, max_tokens)
# ============================================================
_ARTICLE_STRUCTURE: dict[int, tuple[int, int, int, int, int]] = {
    9000: (14, 18, 8, 10, 32000),  # MONETIZE: 比較・レビュー系・高品質
    6000: ( 8, 12, 5,  7, 28000),  # LONGTAIL: 標準SEO記事
    3000: ( 5,  7, 5,  7, 16000),  # FUTURE / TREND: 短め情報記事
}

def _get_structure(target_length: int) -> tuple[int, int, int, int, int]:
    """target_lengthに最も近い構造設定を返す。"""
    if target_length in _ARTICLE_STRUCTURE:
        return _ARTICLE_STRUCTURE[target_length]
    closest = min(_ARTICLE_STRUCTURE.keys(), key=lambda k: abs(k - target_length))
    return _ARTICLE_STRUCTURE[closest]


def _build_system_prompt(
    h3_min: int, h3_max: int, faq_min: int, faq_max: int,
    asp_links: dict | None = None,
) -> str:
    """
    H3本数・FAQ問数・ブログ固有アフィリリンクに応じてSYSTEM_PROMPTを組み立てる。
    asp_links は {名称: URL} の辞書。None または空の場合は「(なし)」と表示。
    ブログ情報（サイト名・テーマ等）は wp_context から動的に取得する。
    """
    prompt = SYSTEM_PROMPT

    # サイト情報（ブログ固有）を動的に差し込む
    try:
        from modules import wp_context
        meta = wp_context.get_blog_meta()
        display_name = meta.get("display_name", "")
        wp_url       = meta.get("wp_url", wp_context.get_wp_url())
        genre        = meta.get("genre", meta.get("genre_detail", ""))
        target       = meta.get("target", "")
        site_lines = f"- サイト名: {display_name}（{wp_url}）\n- テーマ: {genre}"
        if target:
            site_lines += f"\n- 対象読者: {target}"
    except Exception:
        site_lines = "- （ブログ情報未設定）"
    prompt = prompt.replace("__SITE_INFO__", site_lines)

    # 「向いている人・向いていない人」セクションを除外するブログの場合は削除
    try:
        if not meta.get("fit_unfit_section", True):
            prompt = prompt.replace(
                "- **「向いている人・向いていない人」セクションを必ず設ける**（H3またはボックスで）\n",
                "",
            )
            prompt = prompt.replace(
                '{H2セクションの末尾付近に「向いている人・向いていない人」をボックスで設ける}\n'
                '<!-- wp:loos/cap-block {"className":"is-style-onborder_ttl2"} -->\n'
                '<div class="swell-block-capbox cap_box is-style-onborder_ttl2"><div class="cap_box_ttl"><span>{キーワード}が向いている人・向いていない人</span></div><div class="cap_box_content">\n'
                "<!-- wp:paragraph --><p>✅ 向いている人</p><!-- /wp:paragraph -->\n"
                '<!-- wp:list {"className":"is-style-check_list"} --><ul class="wp-block-list is-style-check_list"><li>{条件1}</li><li>{条件2}</li><li>{条件3}</li></ul><!-- /wp:list -->\n'
                "<!-- wp:paragraph --><p>△ 向いていない人</p><!-- /wp:paragraph -->\n"
                '<!-- wp:list --><ul class="wp-block-list"><li>{条件1}</li><li>{条件2}</li></ul><!-- /wp:list -->\n'
                "</div></div>\n"
                "<!-- /wp:loos/cap-block -->",
                "",
            )
    except Exception:
        pass

    # アフィリリンク（ブログ固有）を動的に差し込む
    if asp_links:
        affiliate_lines = "\n".join(f"- {name}: {url}" for name, url in asp_links.items())
        affiliate_lines += (
            "\n\n**重要**: 比較・おすすめ・ランキング系の記事では、"
            "上記登録済みサービスをすべて記事内で必ず1回以上紹介し、各サービスにアフィリリンクを挿入すること。"
            "各サービスは個別のH3セクションまたは比較表で取り上げること。"
        )
    else:
        affiliate_lines = "（このブログにはアフィリリンク登録なし）"
    prompt = prompt.replace(_AFFILIATE_LINES_PLACEHOLDER, affiliate_lines)

    prompt = prompt.replace(
        "H3は合計14〜18本（抽象語禁止、質問形・行動導線を中心に）",
        f"H3は合計{h3_min}〜{h3_max}本（抽象語禁止、質問形・行動導線を中心に）",
    )
    prompt = prompt.replace(
        "FAQは8〜10問（各回答200字以上）",
        f"FAQは{faq_min}〜{faq_max}問（各回答200字以上）",
    )
    prompt = prompt.replace(
        "## 4. よくある質問（8〜10問、各回答200字以上）",
        f"## 4. よくある質問（{faq_min}〜{faq_max}問、各回答200字以上）",
    )
    prompt = prompt.replace(
        "{8〜10問繰り返し}",
        f"{{{faq_min}〜{faq_max}問繰り返し}}",
    )

    # ブログ固有の追加人格・方針（blog_config.json の extra_system_prompt）
    try:
        extra_system = meta.get("extra_system_prompt", "")
        if extra_system:
            prompt += f"\n\n{extra_system}"
    except Exception:
        pass

    return prompt


_HOWTO_MARKERS = frozenset({
    "使い方", "方法", "手順", "やり方", "始め方", "設定", "手続き",
    "使用方法", "操作方法", "導入方法", "登録方法", "利用方法",
    "how to", "tutorial",
})

def _is_howto_keyword(keyword: str) -> bool:
    """使い方・手順解説型のキーワードかどうかを判定する。"""
    kw_l = keyword.lower()
    return any(m in kw_l for m in _HOWTO_MARKERS)


# アドセンス（情報収集型）記事を示すキーワードマーカー
_ADSENSE_MARKERS = frozenset({
    "時刻表", "運賃", "料金表", "路線図", "乗換", "アクセス方法",
    "とは", "意味", "読み方", "違い", "歴史", "原因", "理由",
    "症状", "特徴", "種類", "一覧", "まとめ", "いつ", "どこ",
    "天気", "気温", "営業時間", "定休日", "地図", "場所",
    "住所", "電話番号", "何時", "予算", "費用", "日数",
})

def _is_adsense_article(keyword: str) -> bool:
    """情報収集型（アドセンス）記事かどうかを判定する。"""
    kw_l = keyword.lower()
    return any(m in kw_l for m in _ADSENSE_MARKERS)


def _build_adsense_instruction(keyword: str) -> str:
    """アドセンス記事向けのアフィリリンク抑制指示を返す。"""
    if not _is_adsense_article(keyword):
        return ""
    print(f"[article_generator] アドセンス記事判定: 「{keyword}」→ アフィリリンク抑制モード")
    return (
        "## 【重要】アドセンス（情報収集）型記事の注意事項\n"
        "このキーワードは情報収集型（Know型）の記事です。読者はサービス購入ではなく情報を求めています。\n"
        "- **アフィリリンクは記事全体で1〜2件以内**に抑えること。しつこい誘導はしない\n"
        "- アフィリリンクは記事の末尾付近（まとめセクション内か直後）にのみ配置する\n"
        "- 本文中のH3セクションにアフィリリンクを積極的に挿入しない\n"
        "- 代わりに、関連するCV記事（比較・おすすめ系）への内部リンクを2〜3件挿入して回遊を促す\n"
        "- 読者の検索意図（情報収集）を最優先で満たすこと。購買誘導より情報提供を重視する\n"
        "- 時刻・料金・営業時間など最新性が必要な情報は、外部の公式サイトや専門サービスへのリンクで誘導する\n"
    )


_INTENT_H3_BODY: dict[str, tuple[str, str] | None] = {
    "PROMPT":   ("150", "250"),
    "NOW":      ("150", "250"),
    "FAQ":      ("200", "300"),
    "LONGTAIL": ("250", "400"),
    "COMP":     ("350", "500"),
    "HOWTO":    None,   # HOWTO は _build_howto_section() が担当
}


def _repair_json_unescaped_quotes(s: str) -> str:
    """JSON文字列値内の未エスケープ二重引用符を状態機械で修復する。"""
    result: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] != '"':
            result.append(s[i])
            i += 1
            continue
        result.append('"')
        i += 1
        while i < n:
            ch = s[i]
            if ch == '\\' and i + 1 < n:
                result.append(ch)
                result.append(s[i + 1])
                i += 2
            elif ch == '"':
                j = i + 1
                while j < n and s[j] in ' \t\n\r':
                    j += 1
                next_ch = s[j] if j < n else ''
                if next_ch in (':',  ',', '}', ']', ''):
                    result.append('"')
                    i += 1
                    break
                else:
                    result.append('\\"')
                    i += 1
            elif ch == '\n':
                result.append('\\n')
                i += 1
            elif ch == '\r':
                result.append('\\r')
                i += 1
            else:
                result.append(ch)
                i += 1
    return ''.join(result)


def _build_compact_constraint_section(intent: str, h3_max: int, faq_max: int) -> str:
    """HOWTO以外の意図カテゴリ向け・文字数・構成の上限制約セクションを返す。"""
    if not intent or intent == "HOWTO":
        return ""
    body = _INTENT_H3_BODY.get(intent)
    if body is None:
        return ""
    code_limit = "1件" if intent in ("PROMPT", "NOW") else "2件"
    prompt_quote_rule = (
        "- テンプレート例文・セリフ・引用はすべて **「」（鍵括弧）** で囲むこと。`\"二重引用符\"` は絶対に使わない（JSON互換のため）\n"
        if intent == "PROMPT" else ""
    )
    return (
        "## 【重要】文字数・構成の上限制約（システムプロンプトより優先）\n"
        f"- **H3は合計{h3_max}本以内**（システムプロンプトの本数より優先。絶対に超えないこと）\n"
        f"- **FAQは{faq_max}問以内**（システムプロンプトの問数より優先）\n"
        "- **記事全体は目標文字数の120%を絶対に超えないこと**\n"
        f"- H3本文は1本あたり**{body[0]}〜{body[1]}字**に収める\n"
        f"- コードサンプルは全体で最大{code_limit}まで\n"
        "- 同じ内容の言い換え・繰り返しは禁止。冗長な前置きや補足は削る\n"
        + prompt_quote_rule
    )


def _build_howto_section(keyword: str) -> str:
    """手順解説型キーワード向けの追加指示セクションを返す。"""
    if not _is_howto_keyword(keyword):
        return ""
    return (
        "## 【重要】手順解説型記事の追加指示（システムプロンプトより優先）\n"
        "このキーワードは「使い方・手順解説型」です。以下のルールを**必ず守り**、簡潔で読みやすい記事を書いてください:\n"
        "\n"
        "### 構成数の上限（厳守）\n"
        "- **H2は最大3つ**（これはシステムプロンプトと同じ）\n"
        "- **H3は合計5〜10本以内**（システムプロンプトの本数より優先。絶対に超えないこと）\n"
        "- **FAQは3〜5問以内**（システムプロンプトの問数より優先）\n"
        "\n"
        "### 文字数の上限（厳守）\n"
        "- **記事全体は目標文字数の120%を絶対に超えないこと**（例: 目標5000字なら最大6000字）\n"
        "- H3本文は1本あたり**200〜350字**に収める（長くなりすぎる原因になるため厳守）\n"
        "- 「概要」「まとめ」「とは」系のH3は150〜200字で構わない\n"
        "\n"
        "### 内容の絞り込み（必須）\n"
        "- **コードサンプルは全体で最大2件まで**。コードは要点のみ、長い実装例は禁止\n"
        "- **同じ内容の言い換えや繰り返しは禁止**（「つまり〜」「換言すれば〜」「要するに〜」で同内容を繰り返さない）\n"
        "- 冗長な前置き・補足・注意書きは削る。1H3で伝えることは1つに絞る\n"
        "- 「初心者でも」「難しそうに見えますが実は」などの不要な前置きを繰り返さない\n"
        "\n"
        "### 手順ブロックのフォーマット\n"
        "- 手順・ステップの列挙には必ずSWELL Stepブロック（<!-- wp:loos/step -->）を使うこと\n"
        "- Stepブロックのタイトル（`<strong>`内）には「【STEP1】」などの番号テキストを絶対に入れないこと（SWELLが自動表示するため）\n"
        "- 各ステップ本文は80〜120字に収める\n"
        "- 手順以外で番号付きリストが必要な場合はSWELLボーダーグループで囲む:\n"
        "  <!-- wp:group {\"className\":\"has-border -border04\",\"layout\":{\"type\":\"constrained\"}} -->\n"
        "  <div class=\"wp-block-group has-border -border04\"><!-- wp:list {\"ordered\":true,\"className\":\"wp-block-list is-style-index\"} -->\n"
        "  <ol class=\"wp-block-list is-style-index\"><li>...</li></ol>\n"
        "  <!-- /wp:list --></div>\n"
        "  <!-- /wp:group -->\n"
        "- SWELL Stepブロックの構造:\n"
        "  <!-- wp:loos/step -->\n"
        "  <div class=\"swell-block-step\" data-num-style=\"circle\"><!-- wp:loos/step-item {\"stepLabel\":\"STEP\"} -->\n"
        "  <div class=\"swell-block-step__item\"><div class=\"swell-block-step__number u-bg-main\"><span class=\"__label\">STEP</span></div>"
        "<div class=\"swell-block-step__title u-fz-l\"><strong>タイトル</strong></div>"
        "<div class=\"swell-block-step__body\"><!-- wp:paragraph -->\n"
        "  <p>本文（80〜120字）</p>\n"
        "  <!-- /wp:paragraph --></div></div>\n"
        "  <!-- /wp:loos/step-item -->\n"
        "  <!-- wp:loos/step-item {\"stepLabel\":\"STEP\"} -->\n"
        "  ... （ステップ数だけ繰り返す）\n"
        "  <!-- /wp:loos/step-item --></div>\n"
        "  <!-- /wp:loos/step -->\n"
        "- 読者がその場でそのまま実行できるレベルの具体性を保つこと（ただし余分な説明は削ること）\n"
    )


def _get_keyword_research(keyword: str) -> dict:
    """
    Claude Haiku でキーワードリサーチを一括生成する。

    Returns:
        {
            "suggest":  ["サジェスト候補", ...],   # 8〜10個
            "paa":      ["PAA質問文", ...],         # 5〜8個
            "longtail": ["ロングテール複合KW", ...] # 8〜10個
        }
    """
    check_stop()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": (
                f"「{keyword}」のSEO記事向けにキーワードリサーチを行ってください。\n"
                "以下のJSONのみ出力してください（```json などのコードブロック記号は不要）：\n"
                '{"suggest":["サジェスト候補8〜10個（Googleサジェスト想定）"],'
                '"paa":["PAA形式の質問文5〜8個（〜とは・〜やり方・〜比較・〜おすすめなど）"],'
                '"longtail":["3〜5語のロングテール複合キーワード8〜10個"]}'
            ),
        }],
    )
    record_usage("claude-haiku-4-5-20251001",
                 msg.usage.input_tokens, msg.usage.output_tokens, f"kw_research:{keyword}")
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        result = json.loads(raw)
        return {
            "suggest":  result.get("suggest", [])[:10],
            "paa":      result.get("paa", [])[:8],
            "longtail": result.get("longtail", [])[:10],
        }
    except Exception:
        return {"suggest": [], "paa": [], "longtail": []}


def _get_lsi_keywords(keyword: str) -> str:
    """
    Claude Haiku でキーワードの共起語・LSIキーワードを生成する。

    Returns:
        「用語1、用語2、...」形式の文字列（プロンプトに直接埋め込む用）
    """
    check_stop()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"「{keyword}」というキーワードの記事でSEO的に重要な共起語・LSIキーワードを"
                f"15個生成してください。"
                f"読者が同時に検索・気にするであろう関連語句を中心に。"
                f"出力は「語句1、語句2、語句3、...」の形式のみ。説明不要。"
            ),
        }],
    )
    record_usage("claude-haiku-4-5-20251001",
                 msg.usage.input_tokens, msg.usage.output_tokens, f"lsi:{keyword}")
    raw = msg.content[0].text.strip()
    return raw.splitlines()[0] if raw else ""


def _needs_plaud_notta(keyword: str) -> bool:
    """キーワードがPLAUD NOTE/Notta優先紹介の対象かどうかを判定する。"""
    kw = keyword.lower()
    return any(term in kw for term in _PLAUD_NOTTA_TERMS)


# ============================================================
# 検索意図タイプ検出・トーン指示
# ============================================================

_INTENT_SYMPATHY_WORDS = [
    "辞めたい", "疲れた", "不安", "悩み", "ストレス", "しんどい", "つらい",
    "迷って", "怖い", "不満", "嫌", "やめたい", "向いていない", "続かない",
    "人間関係", "職場", "パワハラ", "ブラック", "しんどい", "きつい",
]
_INTENT_COMPARISON_WORDS = [
    "比較", "ランキング", "どちら", "どれ", "違い", "選び方", "メリット",
    "デメリット", "向いてる", "まとめ", "一覧", "どこ",
]
_INTENT_PURCHASE_WORDS = [
    "登録", "申し込み", "始め方", "使い方", "料金", "評判", "口コミ",
    "無料", "体験", "試し", "手順", "流れ", "やり方", "方法",
]

_TONE_INSTRUCTIONS: dict[str, str] = {
    "sympathy": """\
## 検索意図タイプ: 共感系（寄り添い調）
このキーワードで検索するユーザーは「誰かにわかってほしい」「背中を押してほしい」という気持ちを持っています。
文体ルール：
- 冒頭や各H3の冒頭で読者の気持ちに共感する一文を入れる（例：「転職活動って、本当に疲れますよね」）
- 「〜という方は多いのではないでしょうか」「〜という状況、よく聞きます」など共感フレーズを自然に使う
- 専門的・事務的な語調は避け、「一緒に考えましょう」「大丈夫です」のような温かみのある言葉を使う
- 失敗談・苦労話を交えて「あなただけじゃない」と感じさせる表現を盛り込む
""",
    "comparison": """\
## 検索意図タイプ: 比較系（客観的・データ重視）
このキーワードで検索するユーザーは「正しい情報で冷静に選びたい」という気持ちを持っています。
文体ルール：
- 感情的な表現を抑え、事実・数字・比較の切り口を中心に構成する
- 「A社は〜、B社は〜という特徴があります」「向いている人・向いていない人」の軸で整理する
- 「〜がベスト」「絶対〜」などの断定は避け、「〜という観点では〜が優れています」という客観表現を使う
- 読者自身が判断できる情報を提供することを最優先に考える
""",
    "purchase": """\
## 検索意図タイプ: 購買直前（背中を押す）
このキーワードで検索するユーザーは「もう少しの後押しがほしい」という段階にいます。
文体ルール：
- 冒頭・まとめで「まず一歩踏み出してみましょう」のような前向きなフレーズを使う
- 「無料だからリスクはない」「最悪うまくいかなくても〜」などハードルを下げる言葉を自然に入れる
- 登録・申し込みの手順を具体的かつ簡潔に説明する
- ベネフィットを最後に改めて強調し「よし、やってみよう」と思えるよう締める
""",
}


def _detect_search_intent(keyword: str) -> str:
    """
    キーワードから検索意図タイプを判定する。
    Returns: 'sympathy' | 'comparison' | 'purchase' | ''
    """
    kw = keyword.lower()
    scores = {
        "sympathy":   sum(1 for w in _INTENT_SYMPATHY_WORDS   if w in kw),
        "comparison": sum(1 for w in _INTENT_COMPARISON_WORDS  if w in kw),
        "purchase":   sum(1 for w in _INTENT_PURCHASE_WORDS    if w in kw),
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else ""


def _build_tone_section(keyword: str) -> str:
    """検索意図に対応したトーン指示文字列を返す。"""
    intent = _detect_search_intent(keyword)
    if not intent:
        return ""
    label = {"sympathy": "共感系", "comparison": "比較系", "purchase": "購買直前"}[intent]
    print(f"[article_generator] 検索意図: {label} → トーン調整")
    return _TONE_INSTRUCTIONS[intent]


def _build_testimonial_section(keyword: str) -> str:
    """EXPERIENCE｜体験談シートから関連体験談を取得してプロンプトセクションを返す。"""
    try:
        from modules import wp_context
        from modules.testimonial_fetcher import build_prompt_section
        from config import GOOGLE_CREDENTIALS_PATH
        ss_id = wp_context.get_experience_ss_id()
        if not ss_id:
            return ""
        blog_name = wp_context.get_blog_name()
        section = build_prompt_section(keyword, blog_name, ss_id, GOOGLE_CREDENTIALS_PATH)
        if section:
            print(f"[article_generator] 体験談: 関連体験談をプロンプトに組み込みました")
        return section
    except Exception as e:
        print(f"[article_generator] 体験談スキップ: {e}")
        return ""


def _build_blog_context_section() -> str:
    """
    wp_contextのblog_metaからブログ専用コンテキストセクションを生成する。
    値が入っている項目のみ出力。全て空の場合は空文字列を返す。
    空欄の項目はClaudeが記事内容から自動判断する。
    """
    try:
        from modules import wp_context
        meta = wp_context.get_blog_meta()
    except Exception:
        return ""

    if not meta:
        return ""

    lines = []
    if meta.get("site_purpose"):
        lines.append(f"【サイトの目的】{meta['site_purpose']}")
    if meta.get("target"):
        lines.append(f"【ターゲット読者】{meta['target']}")
    if meta.get("writing_taste"):
        lines.append(f"【文章のテイスト】{meta['writing_taste']}")
    if meta.get("genre_detail"):
        lines.append(f"【ジャンル】{meta['genre_detail']}")
    if meta.get("search_intent"):
        lines.append(f"【検索意図タイプ】{meta['search_intent']}")

    if not lines:
        return ""

    block = "\n".join(lines)
    return (
        "## ブログのコンテキスト（記事の方向性・文体・読者に合わせて記事を最適化してください）\n"
        f"{block}\n\n"
    )


USER_PROMPT_TEMPLATE = """\
以下のキーワードで記事構成を生成してください。

現在の日付: {current_date}（記事内で年や「今年」「最新」などの表現を使う際は必ずこの年に合わせること）

メインキーワード: {keyword}
月間検索ボリューム: {volume}
{asp_hint_section}{blog_context_section}{blog_persona_section}{related_section}{theme_section}{lsi_section}{keyword_research_section}{sub_keywords_section}{differentiation_section}{fact_check_section}{person_section}{plaud_notta_section}{tone_section}{testimonial_section}{trusted_external_links_section}{ref_urls_section}{forced_title_section}{compact_constraint_section}{howto_section}{adsense_section}
このキーワードで検索するユーザーの検索意図を踏まえ、上記フォーマットに従って出力してください。

## 出力フォーマット（JSON）
以下のJSONのみ返してください。前後に説明文・コードブロック記号は不要です。

{{
  "title": "H1タイトル（30〜40字程度・キーワードを自然に含む・数字やメリット・疑問形でクリックを促す。例：「AIボイスレコーダーアプリiPhoneおすすめ7選！文字起こし・要約まで自動化」）",
  "seo_title": "タイトルタグ（検索結果に表示されるSEOタイトル。28〜32字・キーワードを先頭に・サイト名は不要。例：「AIボイスレコーダーアプリおすすめ7選｜文字起こし自動化」）",
  "meta_description": "メタディスクリプション（80〜120字・キーワードを含み検索意図に沿ったクリックを促す文章。例：「AIボイスレコーダーアプリのおすすめ7選を解説。文字起こし・議事録作成を自動化したい人向けに、機能・価格・使いやすさを徹底比較します。」）",
  "slug": "url-slug-in-english-kebab-case",
  "image_prompt": "アイキャッチ用英語プロンプト（記事テーマを表す画像、no text, professional blog header, high quality）",
  "tags": ["記事テーマに合うタグ1", "タグ2", "タグ3", "タグ4", "タグ5（必ず5つ）"],
  "content": "WordPress SWELL形式の完全なHTML（セクション1〜5をすべて含む。記事データセクションは不要）"
}}
"""


def _build_article(keyword: str, volume: int, differentiation_note: str = "",
                   related_keywords: list[str] | None = None,
                   article_theme: str = "",
                   sub_keywords: list[str] | None = None,
                   enable_fact_check: bool = True,
                   target_length: int = 9000,
                   asp_links: dict | None = None,
                   forced_title: str | None = None,
                   asp_hint: list[str] | None = None,
                   ref_urls: dict | None = None,
                   blog_persona_section: str = "",
                   structure_overrides: dict | None = None) -> dict:
    """
    記事生成の共通処理。Claude APIを呼び出してJSON記事データを返す。

    target_length に応じてH3本数・FAQ問数・max_tokensを動的に切り替える。
      9000 (MONETIZE): H3×14〜18本 / FAQ×8〜10問 / max_tokens=32,000
      6000 (LONGTAIL):  H3×8〜12本  / FAQ×5〜7問  / max_tokens=28,000
      3000 (TREND):     H3×5〜7本   / FAQ×5〜7問  / max_tokens=16,000
    """
    h3_min, h3_max, faq_min, faq_max, max_tokens = _get_structure(target_length)
    if structure_overrides:
        h3_min     = structure_overrides.get("h3_min",     h3_min)
        h3_max     = structure_overrides.get("h3_max",     h3_max)
        faq_min    = structure_overrides.get("faq_min",    faq_min)
        faq_max    = structure_overrides.get("faq_max",    faq_max)
        max_tokens = structure_overrides.get("max_tokens", max_tokens)
    system_prompt = _build_system_prompt(h3_min, h3_max, faq_min, faq_max, asp_links=asp_links)

    use_plaud_notta = _needs_plaud_notta(keyword)
    print(f"[article_generator] 記事構成生成中: 「{keyword}」(vol:{volume})"
          + f" [{target_length:,}字 / H3:{h3_min}〜{h3_max}本 / FAQ:{faq_min}〜{faq_max}問]"
          + (" ※差別化モード" if differentiation_note else "")
          + (" ※PLAUD/Notta優先" if use_plaud_notta else ""))

    # ── 事実確認ステップ（製品・企業情報を含む記事のみ）──
    fact_check_section = ""
    if enable_fact_check and needs_fact_check(keyword):
        print(f"[article_generator] 事実確認中: 「{keyword}」")
        fc = check_facts(keyword, article_theme)
        if fc["verified"] or fc["uncertain"] or fc["warnings"]:
            fact_check_section = fc["prompt_block"] + "\n"
            verified_count  = len(fc["verified"])
            uncertain_count = len(fc["uncertain"])
            warnings_count  = len(fc["warnings"])
            print(f"[article_generator] 事実確認完了: "
                  f"確認済み{verified_count}件 / 不確か{uncertain_count}件 / 注意{warnings_count}件")
            if fc["warnings"]:
                for w in fc["warnings"]:
                    print(f"  ⚠️  {w}")
        else:
            print("[article_generator] 事実確認: 確認情報なし（スキップ）")

    person_section = PERSON_ARTICLE_INSTRUCTION + "\n" if detect_person_keyword(keyword) else ""
    diff_section = f"差別化の方針: {differentiation_note}\n" if differentiation_note else ""
    plaud_notta_section = _PLAUD_NOTTA_INSTRUCTION if use_plaud_notta else ""

    # ブログコンテキスト（管理シートのメタデータ）
    blog_context_section = _build_blog_context_section()

    # 関連キーワード指示
    related_section = ""
    if related_keywords:
        kw_list = "・".join(related_keywords)
        related_section = (
            f"関連キーワード（記事内のH2・H3見出しや本文に自然に含めること）: {kw_list}\n"
        )

    # 記事テーマ指示
    theme_section = f"記事テーマ: {article_theme}\n" if article_theme else ""

    # 共起語・LSIキーワード（Haiku で生成）
    try:
        lsi_words = _get_lsi_keywords(keyword)
        lsi_section = (
            f"共起語・LSIキーワード（H3本文・FAQ・まとめの文脈の中に自然に溶け込ませること。文頭への羅列・スペース区切りの列挙は厳禁）: {lsi_words}\n"
        ) if lsi_words else ""
        if lsi_words:
            print(f"[article_generator] 共起語: {lsi_words[:60]}...")
    except Exception:
        lsi_section = ""

    # スプレッドシートのAIM未判定サブキーワード
    sub_keywords_section = ""
    if sub_keywords:
        # メインKW・関連KWと重複するものを除く
        existing = {keyword.lower()} | {k.lower() for k in (related_keywords or [])}
        candidates = [k for k in sub_keywords if k.lower() not in existing][:50]
        if candidates:
            sub_keywords_section = (
                "スプレッドシートのサブキーワード候補（関連性が高いものだけH3見出し・本文・FAQに自然に活用。"
                "無理に全部入れる必要はなく、関連性が低いものはスキップでOK。不自然な詰め込み禁止）:\n"
                + "・".join(candidates) + "\n"
            )
            print(f"[article_generator] サブKW候補: {len(candidates)}件 ({candidates[0]}〜)")

    # サジェスト・PAA・ロングテールキーワード（Haiku で生成）
    keyword_research_section = ""
    try:
        kw_research = _get_keyword_research(keyword)
        parts = []
        if kw_research["suggest"]:
            parts.append("サジェストキーワード（H3見出しや本文の文脈に自然に溶け込ませる。文頭への羅列・詰め込み禁止）: " + "・".join(kw_research["suggest"]))
        if kw_research["paa"]:
            parts.append("関連質問PAA（FAQの質問文やH3見出しに活用する）: " + "・".join(kw_research["paa"]))
        if kw_research["longtail"]:
            parts.append("ロングテールキーワード（本文中の文脈に自然に溶け込ませる。文頭への羅列・詰め込み禁止）: " + "・".join(kw_research["longtail"]))
        if parts:
            keyword_research_section = "\n".join(parts) + "\n"
            suggest_preview = "・".join(kw_research["suggest"][:3])
            print(f"[article_generator] サジェスト: {suggest_preview}...")
    except Exception:
        pass

    # 検索意図トーン調整
    tone_section = _build_tone_section(keyword)

    # 体験談セクション（スプレッドシートから関連するものを取得）
    testimonial_section = _build_testimonial_section(keyword)

    # 信頼できる外部リンクセクション（ブログ設定で指定がある場合のみ）
    trusted_external_links_section = ""
    try:
        from modules import wp_context as _wpc
        ext_links = _wpc.get_trusted_external_links()
        if ext_links:
            link_lines = "\n".join(
                f"- {item['name']}: {item['url']}" for item in ext_links
            )
            trusted_external_links_section = (
                "## 外部リンク挿入ルール（必須）\n"
                "以下の公式サイト・信頼できる外部リンクのうち、記事テーマに最も自然に合うものを**必ず1件以上**本文中に挿入してください。\n"
                "挿入例：「最新情報や開催時間は<a href=\"URL\" target=\"_blank\" rel=\"noopener noreferrer\">〇〇公式サイト</a>でご確認ください。」\n"
                f"{link_lines}\n"
            )
    except Exception:
        pass

    # 訴求案件指定セクション（スプレッドシートで手動指定された場合のみ）
    asp_hint_section = ""
    if asp_hint:
        hint_lines = []
        for h in asp_hint:
            url = ""
            if asp_links:
                for name, u in asp_links.items():
                    n = name.lower().replace(" ", "").replace("　", "")
                    q = h.lower().replace(" ", "").replace("　", "")
                    if q in n or n in q:
                        url = u
                        break
            hint_lines.append(f"- {h}" + (f": {url}" if url else ""))
        asp_hint_section = (
            "## 訴求案件指定（最優先・必須）\n"
            "以下の案件を記事の中心的な訴求対象として積極的に紹介してください。\n"
            "各H2のメインテーマとして取り上げ、H3でも詳しく解説することを推奨します:\n"
            + "\n".join(hint_lines) + "\n\n"
        )
        print(f"[article_generator] 訴求案件指定: {asp_hint}")

    # タイトル強制指定セクション
    forced_title_section = ""
    if forced_title:
        forced_title_section = (
            f"\n※ タイトルは必ず「{forced_title}」を使用してください。"
            f"このタイトルに合わせた内容・構成で記事を執筆してください。\n"
        )
        print(f"[article_generator] タイトル強制指定: 「{forced_title}」")

    # 参考URLセクション（スプレッドシートで事前に取得済みのURL）
    ref_urls_section = ""
    if ref_urls:
        parts = []
        for key, label in [("web1", "①"), ("web2", "②"), ("web3", "③")]:
            if ref_urls.get(key):
                parts.append(f"- 参考WEB{label}: {ref_urls[key]}")
        if parts:
            ref_urls_section = (
                "## 参考URL（事前調査済み・内部資料）\n"
                "以下のURLは制作用の内部参考資料です。内容を参考に記事の正確性・具体性を高めてください。\n"
                "**重要: 記事本文中に「参考WEB①」「参考URL」などの表現は絶対に使わないこと。これらは非公開の内部資料です。**\n"
                + "\n".join(parts) + "\n"
            )
            filled = [ref_urls.get(k, "") for k in ("web1", "web2", "web3") if ref_urls.get(k)]
            print(f"[article_generator] 参考URL: {len(filled)}件")

    # 手順解説型キーワード向け追加指示
    howto_section = _build_howto_section(keyword)
    if howto_section:
        print(f"[article_generator] 手順解説型モード: 「{keyword}」")

    # 意図カテゴリ別・文字数上限制約セクション（HOWTO以外）
    _intent      = (structure_overrides or {}).get("intent", "")
    _h3_max_ov   = (structure_overrides or {}).get("h3_max", h3_max)
    _faq_max_ov  = (structure_overrides or {}).get("faq_max", faq_max)
    compact_constraint_section = _build_compact_constraint_section(_intent, _h3_max_ov, _faq_max_ov)
    if compact_constraint_section:
        print(f"[article_generator] コンパクト制約モード({_intent}): H3≤{_h3_max_ov} FAQ≤{_faq_max_ov}")

    # アドセンス（情報収集型）記事の判定
    adsense_section = _build_adsense_instruction(keyword)

    check_stop()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        current_date=date.today().strftime("%Y年%m月%d日"),
        keyword=keyword,
        volume=volume,
        asp_hint_section=asp_hint_section,
        blog_context_section=blog_context_section,
        blog_persona_section=blog_persona_section,
        related_section=related_section,
        theme_section=theme_section,
        lsi_section=lsi_section,
        keyword_research_section=keyword_research_section,
        sub_keywords_section=sub_keywords_section,
        differentiation_section=diff_section,
        fact_check_section=fact_check_section,
        person_section=person_section,
        plaud_notta_section=plaud_notta_section,
        tone_section=tone_section,
        testimonial_section=testimonial_section,
        trusted_external_links_section=trusted_external_links_section,
        ref_urls_section=ref_urls_section,
        forced_title_section=forced_title_section,
        compact_constraint_section=compact_constraint_section,
        howto_section=howto_section,
        adsense_section=adsense_section,
    )
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        message = stream.get_final_message()
    record_usage("claude-sonnet-4-6",
                 message.usage.input_tokens, message.usage.output_tokens, f"article:{keyword}")

    # stop_reason チェック: max_tokens に到達した場合はJSONが途切れているので即エラーにする
    if message.stop_reason == "max_tokens":
        raise ValueError(
            f"max_tokens上限（{max_tokens}）に到達しました。JSONが途切れています。"
            f" 出力トークン: {message.usage.output_tokens}"
        )

    raw = message.content[0].text.strip()

    # ```json ... ``` ブロックへの対応
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        import re as _re
        # ① 制御文字（改行・タブ以外）を除去して再試行
        sanitized = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
        try:
            data = json.loads(sanitized)
        except json.JSONDecodeError:
            # ② 未エスケープ二重引用符を状態機械で修復して再試行（PROMPT記事のテンプレ例文対策）
            repaired = _repair_json_unescaped_quotes(sanitized)
            try:
                data = json.loads(repaired)
                print(f"[article_generator] JSON修復成功（未エスケープquote修正）")
            except json.JSONDecodeError as e:
                # ③ それでも失敗した場合は同じプロンプトでAPIを1回リトライ
                print(f"[article_generator] JSON解析失敗（{e}）→ 同一プロンプトでリトライ中...")
                with client.messages.stream(
                    model="claude-sonnet-4-6",
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ) as _retry_stream:
                    retry_msg = _retry_stream.get_final_message()
                record_usage("claude-sonnet-4-6",
                             retry_msg.usage.input_tokens, retry_msg.usage.output_tokens,
                             f"article_retry:{keyword}")
                raw2 = retry_msg.content[0].text.strip()
                if raw2.startswith("```"):
                    lines2 = raw2.split("\n")
                    raw2 = "\n".join(lines2[1:-1] if lines2[-1].strip() == "```" else lines2[1:])
                try:
                    data = json.loads(raw2)
                except json.JSONDecodeError as e2:
                    raise ValueError(f"Claude APIからのJSON解析エラー: {e2}\n---\n{raw[:500]}") from e2

    for key in ("title", "meta_description", "slug", "image_prompt", "content"):
        if key not in data:
            raise ValueError(f"レスポンスに必須キー '{key}' がありません")

    # タイトル強制指定: 生成後に上書き
    if forced_title:
        data["title"] = forced_title

    # seo_title が未生成の場合は title から生成（32字に切り詰め）
    if not data.get("seo_title"):
        data["seo_title"] = data["title"][:32]

    # category_id は wordpress_poster の select_category() で決定するため、ここでは使わない
    data.pop("category_id", None)
    data.pop("category_name", None)

    # タグを最大5個に制限（不足時は空リストのまま → 投稿時にログ警告）
    if isinstance(data.get("tags"), list):
        data["tags"] = [t for t in data["tags"] if t][:5]
    else:
        data["tags"] = []

    data["keyword"] = keyword
    data["volume"] = volume

    # ImageFX プロンプトを生成してdictに追加
    try:
        data["imagefx_prompt"] = generate_imagefx_prompt(keyword, data["title"])
    except Exception as e:
        print(f"[article_generator] ImageFXプロンプト生成スキップ: {e}")
        data["imagefx_prompt"] = ""

    print(
        f"[article_generator] 完了: 「{data['title']}」"
        f" カテゴリ: {data.get('category_name','未設定')}({data.get('category_id','-')})"
        f" タグ: {data['tags']}"
    )
    return data


def generate_article(keyword: str, volume: int, differentiation_note: str = "",
                     sub_keywords: list[str] | None = None,
                     enable_fact_check: bool = True,
                     target_length: int = 9000,
                     article_type: str = "longtail",
                     asp_list: list | None = None,
                     guide_links: dict | None = None,
                     forced_title: str | None = None,
                     asp_hint: list[str] | None = None,
                     ref_urls: dict | None = None,
                     blog_persona_section: str = "",
                     structure_overrides: dict | None = None) -> dict:
    """
    指定キーワードでSEO記事構成を生成し、辞書で返す。

    Args:
        keyword: メインキーワード
        volume: 月間検索ボリューム
        differentiation_note: カニバリ対策の差別化ヒント（空文字列なら通常生成）
        sub_keywords: スプレッドシートのAIM未判定キーワード（任意活用）
        enable_fact_check: 事実確認ステップを実行するか（デフォルト: True）
        target_length: 目標文字数（9000/6000/3000）。H3本数・FAQ問数・max_tokensを自動調整

    Returns:
        {title, meta_description, slug, image_prompt, category_id, category_name,
         content, keyword, volume}
    """
    # asp_list ({name, url, ...}のリスト) → asp_links ({name: url}の辞書) に変換
    asp_links: dict | None = None
    if asp_list:
        asp_links = {item["name"]: item["url"] for item in asp_list if item.get("name") and item.get("url")}

    return _build_article(keyword, volume, differentiation_note,
                          sub_keywords=sub_keywords, enable_fact_check=enable_fact_check,
                          target_length=target_length, asp_links=asp_links,
                          forced_title=forced_title, asp_hint=asp_hint,
                          ref_urls=ref_urls, blog_persona_section=blog_persona_section,
                          structure_overrides=structure_overrides)


def generate_article_from_cluster(cluster: dict, sub_keywords: list[str] | None = None) -> dict:
    """
    keyword_clusters.json の1グループから記事を生成する。

    Args:
        cluster: {
            "group_id": int,
            "main_keyword": str,
            "related_keywords": list[str],
            "article_theme": str,
            "skip": bool,
            "note": str,
        }

    Returns:
        generate_article と同じ形式の dict（cluster情報を追加）
    """
    main_kw = cluster["main_keyword"]
    related = cluster.get("related_keywords", [])
    theme = cluster.get("article_theme", "")
    note = cluster.get("note", "")

    # 関連KWのボリュームは未知なので0
    volume = cluster.get("volume", 0)

    data = _build_article(
        keyword=main_kw,
        volume=volume,
        differentiation_note=note,
        related_keywords=related,
        article_theme=theme,
        sub_keywords=sub_keywords,
    )
    data["group_id"] = cluster.get("group_id")
    data["related_keywords"] = related
    return data
