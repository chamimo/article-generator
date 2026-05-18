#!/usr/bin/env python3
"""
GSC分析 → リライト提案シート記入スクリプト

使い方:
    python rewrite_analysis.py workup-ai        # AIVice（最大20件）
    python rewrite_analysis.py hataraku         # はた楽ナビ
    python rewrite_analysis.py workup-ai 30     # 最大30件まで提案

処理内容:
    1. Google Search Consoleから過去90日のデータを取得
    2. リライト候補をスコアリング
    3. Claude APIでリライト提案テキストを生成
    4. 各ブログのスプレッドシート「リライト提案」シートに記入

実行後はスプレッドシートを確認し、ステータスを「未確認→依頼予定」に変更してください。
リライト実行は Claude Code に「○○をリライトして」と指示してください。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from modules.rewrite_analyzer import run_analysis

if __name__ == "__main__":
    blog_name    = sys.argv[1] if len(sys.argv) > 1 else "workup-ai"
    max_proposals = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    run_analysis(blog_name, max_proposals=max_proposals)
