/**
 * ブログ管理 - Google Apps Script
 * スプレッドシート: ブログ自動生成横展開
 * - 「新規ブログ追加」シートのフォームから「ブログ管理」シートに行を追加
 * - スプレッドシートを開いたときにボタンを配置
 */

// ── シート名定数 ──────────────────────────────────────────────
const MGMT_SHEET   = "ブログ管理";
const FORM_SHEET   = "新規ブログ追加";

// 「新規ブログ追加」シートの入力行定義（A列ラベル → B列入力値）
const FORM_ROWS = {
  "ブログ名":              2,
  "ディレクトリ名":        3,
  "スプレッドシートID":    4,
  "キーワードシート名":    5,
  "投稿記事一覧シート名":  6,
  "WordPress URL":         7,
  "備考":                  8,
};

// ── ボタン「ブログを追加する」が押されたときの処理 ───────────
function addBlogEntry() {
  const ss        = SpreadsheetApp.getActiveSpreadsheet();
  const formSheet = ss.getSheetByName(FORM_SHEET);
  const mgmtSheet = ss.getSheetByName(MGMT_SHEET);

  if (!formSheet || !mgmtSheet) {
    SpreadsheetApp.getUi().alert("シートが見つかりません。「" + MGMT_SHEET + "」と「" + FORM_SHEET + "」が存在するか確認してください。");
    return;
  }

  // 入力値を取得
  const blogName   = formSheet.getRange("B2").getValue().toString().trim();
  const dirName    = formSheet.getRange("B3").getValue().toString().trim();
  const ssId       = formSheet.getRange("B4").getValue().toString().trim();
  const kwSheet    = formSheet.getRange("B5").getValue().toString().trim();
  const postSheet  = formSheet.getRange("B6").getValue().toString().trim();
  const wpUrl      = formSheet.getRange("B7").getValue().toString().trim();
  const note       = formSheet.getRange("B8").getValue().toString().trim();

  // バリデーション
  const errors = [];
  if (!blogName)   errors.push("ブログ名");
  if (!dirName)    errors.push("ディレクトリ名");
  if (!wpUrl)      errors.push("WordPress URL");

  if (errors.length > 0) {
    SpreadsheetApp.getUi().alert("以下の必須項目が未入力です：\n・" + errors.join("\n・"));
    return;
  }

  // WordPress URL の形式チェック
  if (wpUrl && !wpUrl.startsWith("http")) {
    SpreadsheetApp.getUi().alert("WordPress URL は http:// または https:// で始めてください。");
    return;
  }

  // 重複チェック（ブログ名またはディレクトリ名）
  const lastRow   = mgmtSheet.getLastRow();
  if (lastRow >= 2) {
    const existingData = mgmtSheet.getRange(2, 1, lastRow - 1, 2).getValues();
    for (const row of existingData) {
      if (row[0].toString().trim() === blogName) {
        SpreadsheetApp.getUi().alert("「" + blogName + "」は既にブログ管理に登録されています。");
        return;
      }
      if (row[1].toString().trim() === dirName) {
        SpreadsheetApp.getUi().alert("ディレクトリ名「" + dirName + "」は既に登録されています。");
        return;
      }
    }
  }

  // ブログ管理シートに追記
  const today  = Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd");
  const newRow = [blogName, dirName, ssId, kwSheet, postSheet, wpUrl, "準備中", note];
  mgmtSheet.appendRow(newRow);

  // 追加した行のスタイルを設定（交互背景色）
  const addedRowNum = mgmtSheet.getLastRow();
  const isEven      = (addedRowNum % 2 === 0);
  const bgColor     = isEven ? "#f0f4ff" : "#ffffff";
  mgmtSheet.getRange(addedRowNum, 1, 1, 8).setBackground(bgColor);

  // ステータス列（G列 = 7列目）を色付き
  const statusCell = mgmtSheet.getRange(addedRowNum, 7);
  statusCell.setBackground("#fff2cc").setFontColor("#b45f06").setFontWeight("bold");

  // フォームをクリア
  for (let row = 2; row <= 8; row++) {
    formSheet.getRange("B" + row).clearContent();
  }

  // 完了メッセージ
  SpreadsheetApp.getUi().alert(
    "✅ 登録完了\n\n" +
    "ブログ名：" + blogName + "\n" +
    "ステータス：準備中\n\n" +
    "「ブログ管理」シートを確認してください。"
  );

  // ブログ管理シートに移動
  ss.setActiveSheet(mgmtSheet);
}

// ── スプレッドシートを開いたときにカスタムメニューを追加 ─────
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🗂 ブログ管理")
    .addItem("新規ブログを追加する", "addBlogEntry")
    .addSeparator()
    .addItem("ブログ管理シートを開く", "openMgmtSheet")
    .addToUi();
}

function openMgmtSheet() {
  const ss   = SpreadsheetApp.getActiveSpreadsheet();
  const mgmt = ss.getSheetByName(MGMT_SHEET);
  if (mgmt) ss.setActiveSheet(mgmt);
}

// ── 「新規ブログ追加」シートにボタンを設置する（初回のみ実行）─
function setupFormButton() {
  const ss        = SpreadsheetApp.getActiveSpreadsheet();
  const formSheet = ss.getSheetByName(FORM_SHEET);
  if (!formSheet) {
    SpreadsheetApp.getUi().alert("「" + FORM_SHEET + "」シートが見つかりません。");
    return;
  }

  // 既存の図形を削除
  const drawings = formSheet.getDrawings();
  drawings.forEach(d => d.remove());

  // ボタン（図形）を挿入 → D10:E11 あたりに配置
  const btn = formSheet.newDrawing()
    .setOnClickFunction("addBlogEntry")
    .setPosition(10, 2, 0, 0)   // row=10, col=2 (B列), offsetX=0, offsetY=0
    .build();
  // ※ GAS の図形ボタンはテキストをコードで設定できないため、
  //   挿入後に手動でボタンテキスト「ブログを追加する」を設定してください。
  formSheet.insertDrawing(btn, 10, 2);

  SpreadsheetApp.getUi().alert(
    "ボタンを設置しました。\n\n" +
    "① 設置されたボタン図形を右クリック → 「テキストを編集」\n" +
    "② 「ブログを追加する」と入力してください。\n\n" +
    "または、メニュー「🗂 ブログ管理 > 新規ブログを追加する」からも実行できます。"
  );
}
