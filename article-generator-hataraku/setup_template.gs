/**
 * 新ブログ用スプレッドシート雛形セットアップ
 * 実行方法: Apps Script エディタで setupTemplate() を選択して▶実行
 */
function setupTemplate() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // ── 色定義 ──
  var HEADER_BG   = '#4385F5';
  var YELLOW_BG   = '#FFFF99';
  var GRAY_BG     = '#CCCCCC';
  var ORANGE_BG   = '#FFCC99';

  // ── シート1: キーワード ──────────────────────────────────────────
  var kwSheet = ss.getSheets()[0];
  kwSheet.setName('キーワード');

  var kwHeaders = [
    'キーワード','SEO難易度','月間検索数','CPC（$）','競合性',
    'キーワード','allintitle','intitle','Q&Aサイト','',
    '無料ブログ','','TikTok','','Instagram','','エックス','',
    'Facebook','','aim','投稿ステータス','投稿日','記事URL',
    '投稿ID','使用サブKW','メモ'
  ];
  kwSheet.getRange(1, 1, 1, kwHeaders.length).setValues([kwHeaders]);

  // ヘッダー書式
  var kwHeaderRange = kwSheet.getRange(1, 1, 1, kwHeaders.length);
  kwHeaderRange.setBackground(HEADER_BG)
               .setFontColor('#FFFFFF')
               .setFontWeight('bold');

  // 列幅
  kwSheet.setColumnWidth(1, 250);   // キーワード
  kwSheet.setColumnWidth(2, 80);    // SEO難易度
  kwSheet.setColumnWidth(3, 90);    // 月間検索数
  kwSheet.setColumnWidth(4, 70);    // CPC
  kwSheet.setColumnWidth(5, 60);    // 競合性
  kwSheet.setColumnWidth(6, 200);   // キーワード2
  kwSheet.setColumnWidth(7, 80);    // allintitle
  kwSheet.setColumnWidth(8, 70);    // intitle
  kwSheet.setColumnWidth(21, 50);   // aim
  kwSheet.setColumnWidth(22, 90);   // 投稿ステータス
  kwSheet.setColumnWidth(23, 80);   // 投稿日
  kwSheet.setColumnWidth(24, 220);  // 記事URL
  kwSheet.setColumnWidth(25, 70);   // 投稿ID
  kwSheet.setColumnWidth(26, 300);  // 使用サブKW
  kwSheet.setColumnWidth(27, 200);  // メモ

  // 行・列固定
  kwSheet.setFrozenRows(1);
  kwSheet.setFrozenColumns(1);

  // ── シート2: 投稿記事一覧 ────────────────────────────────────────
  var artSheet = ss.insertSheet('投稿記事一覧');
  var artHeaders = [
    '投稿日','公開日','記事タイトル','URL','WP投稿ID',
    'メインKW','関連KW','使用サブKW','カテゴリー','タグ',
    '文字数（目安）','アイキャッチURL','ステータス'
  ];
  artSheet.getRange(1, 1, 1, artHeaders.length).setValues([artHeaders]);
  artSheet.getRange(1, 1, 1, artHeaders.length)
    .setBackground(HEADER_BG).setFontColor('#FFFFFF').setFontWeight('bold');

  artSheet.setColumnWidth(1, 90);   // 投稿日
  artSheet.setColumnWidth(2, 90);   // 公開日
  artSheet.setColumnWidth(3, 300);  // 記事タイトル
  artSheet.setColumnWidth(4, 250);  // URL
  artSheet.setColumnWidth(5, 80);   // WP投稿ID
  artSheet.setColumnWidth(6, 200);  // メインKW
  artSheet.setColumnWidth(7, 250);  // 関連KW
  artSheet.setColumnWidth(8, 250);  // 使用サブKW
  artSheet.setColumnWidth(9, 150);  // カテゴリー
  artSheet.setColumnWidth(10, 200); // タグ
  artSheet.setColumnWidth(11, 90);  // 文字数
  artSheet.setColumnWidth(12, 250); // アイキャッチURL
  artSheet.setColumnWidth(13, 80);  // ステータス

  artSheet.setFrozenRows(1);

  // ── シート3: 凡例 ──────────────────────────────────────────────
  var legSheet = ss.insertSheet('凡例');
  var legData = [
    ['背景色', 'ステータス', '説明'],
    ['白（デフォルト）', '未処理', 'まだAIM判定されていないキーワード'],
    ['薄いイエロー', '生成待ち', 'AIM判定済み・記事生成待ち'],
    ['薄いグレー', '投稿済み', '記事生成・WP投稿完了'],
    ['薄いオレンジ', 'カニバリスキップ', '既存記事と内容が重複するためスキップ'],
    ['', '', ''],
    ['追加情報', '', ''],
    ['キーワード列', 'メインキーワード', ''],
    ['AIM列', '「aim」と入力するとシステムが処理対象として認識', ''],
    ['メモ列', 'カニバリ理由・差別化メモが自動記入される', ''],
    ['投稿日・URL・ID', '投稿後に自動記入される', ''],
  ];
  legSheet.getRange(1, 1, legData.length, 3).setValues(legData);

  // ヘッダー
  legSheet.getRange(1, 1, 1, 3)
    .setBackground(HEADER_BG).setFontColor('#FFFFFF').setFontWeight('bold');
  // 色行
  legSheet.getRange(3, 1, 1, 3).setBackground(YELLOW_BG);  // 生成待ち
  legSheet.getRange(4, 1, 1, 3).setBackground(GRAY_BG);    // 投稿済み
  legSheet.getRange(5, 1, 1, 3).setBackground(ORANGE_BG);  // カニバリスキップ

  legSheet.setColumnWidth(1, 150);
  legSheet.setColumnWidth(2, 250);
  legSheet.setColumnWidth(3, 350);

  // ── シート4: 順位トラッキング ────────────────────────────────────
  var trkSheet = ss.insertSheet('順位トラッキング');
  var trkHeaders = ['キーワード', '記事URL', '記事タイトル'];
  trkSheet.getRange(1, 1, 1, trkHeaders.length).setValues([trkHeaders]);
  trkSheet.getRange(1, 1, 1, trkHeaders.length)
    .setBackground(HEADER_BG).setFontColor('#FFFFFF').setFontWeight('bold');

  trkSheet.setColumnWidth(1, 200);  // キーワード
  trkSheet.setColumnWidth(2, 200);  // 記事URL
  trkSheet.setColumnWidth(3, 250);  // 記事タイトル

  trkSheet.setFrozenRows(1);
  trkSheet.setFrozenColumns(3);

  // ── 不要なシートを削除（元のコピーデータ）──
  // キーワードシート以外の既存シートをクリア（テンプレートシートは保持）
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    var name = sheets[i].getName();
    if (name !== 'キーワード' && name !== '投稿記事一覧' && name !== '凡例' && name !== '順位トラッキング') {
      ss.deleteSheet(sheets[i]);
    }
  }

  // キーワードシートのデータ行をクリア（ヘッダー以外）
  var lastRow = kwSheet.getLastRow();
  if (lastRow > 1) {
    kwSheet.getRange(2, 1, lastRow - 1, kwSheet.getLastColumn()).clearContent();
  }
  // 投稿記事一覧もクリア
  var artLastRow = artSheet.getLastRow();
  if (artLastRow > 1) {
    artSheet.getRange(2, 1, artLastRow - 1, artSheet.getLastColumn()).clearContent();
  }

  SpreadsheetApp.getUi().alert('✅ テンプレートのセットアップ完了！\n\n4つのシートが作成されました:\n・キーワード\n・投稿記事一覧\n・凡例\n・順位トラッキング');
}
