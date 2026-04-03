import os
import sys
import asyncio
import subprocess
import time

# 共通モジュールのパスを追加
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, "modules"))

from ebay_logic import EbayStockChecker
from shopee_logic import ShopeeStockChecker

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def run_ebay_cli(checker=None):
    print("\n--- eBay Stock Checker (CLI) ---")
    if not checker:
        checker = EbayStockChecker(dry_run=True, auto_relist=False)
    results = checker.run_full_process(cli_mode=True)
    print(f"\n✅ eBay完了: {len(results)} 件のアイテムを処理しました。")
    return results

async def run_shopee_cli(checker=None):
    print("\n--- Shopee Stock Checker (CLI) ---")
    if not checker:
        checker = ShopeeStockChecker(headless=True)
    
    def cli_progress(text, current, total, results=None):
        if results and len(results) > 0:
            last = results[-1]
            status = last["result"]["status"]
            icon = "📦" if status == "IN_STOCK" else ("❌" if status == "SOLD_OUT" else "⚠️")
            print(f"[Shopee {current}/{total}] {icon} ID: {last['display_id']} | {last['result']['url'][:40]}...")
        else:
            print(f"\n[Shopee] {text}")

    output_path, summary, page = await checker.run_full_cycle(cli_progress)
    print(f"\n📊 --- Shopee 実行リザルト ---\nチェック対象総数: {summary['total']} 件\n ┣ 📦 在庫あり: {summary['in_stock']} 件\n ┣ ❌ 在庫無し: {summary['sold_out']} 件\n ┗ ⚠️ 判定不能: {summary['unknown']} 件\n✅ Excelデータ更新実行数: {summary['updated']} 件\n")
    print(f"💾 保存先: {output_path}")
    return page, output_path

async def run_all_parallel():
    print("\n🚀 [Shopee & eBay] 同時実行を開始します...")
    
    ebay_checker = EbayStockChecker(dry_run=True, auto_relist=False)
    shopee_checker = ShopeeStockChecker(headless=True)
    
    # 並列実行
    shopee_task = asyncio.create_task(run_shopee_cli(shopee_checker))
    ebay_task = asyncio.to_thread(run_ebay_cli, ebay_checker)
    
    await asyncio.gather(shopee_task, ebay_task)
    print("\n🎉 全てのプラットフォームのチェックが完了しました。")

def start_gui():
    print("\nGUI ダッシュボードを起動しています...")
    try:
        subprocess.run(["streamlit", "run", os.path.join(BASE_DIR, "gui.py")], check=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ GUIの起動に失敗しました: {e}")
        input("\nEnterキーを押してメニューに戻る...")

def main_menu():
    while True:
        clear_screen()
        print("==========================================")
        print("    📦 Unified Stock Checker System v3.1")
        print("==========================================")
        print("1. eBay Stock Checker (CLI)")
        print("2. Shopee Stock Checker (CLI)")
        print("3. Run All (Parallel CLI)")
        print("4. GUI Dashboard を起動 (Streamlit)")
        print("q. 終了")
        print("------------------------------------------")
        
        choice = input("選択してください: ").strip().lower()
        
        if choice == '1':
            run_ebay_cli()
            input("\nEnterキーを押してメニューに戻る...")
        elif choice == '2':
            asyncio.run(run_shopee_cli())
            input("\nEnterキーを押してメニューに戻る...")
        elif choice == '3':
            asyncio.run(run_all_parallel())
            input("\nEnterキーを押してメニューに戻る...")
        elif choice == '4':
            start_gui()
        elif choice == 'q':
            print("終了します。")
            break
        else:
            print("無効な選択です。")
            time.sleep(1)

if __name__ == "__main__":
    main_menu()
