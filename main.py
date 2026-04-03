import os
import sys
import asyncio
import subprocess

# 共通モジュールのパスを追加
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, "modules"))

from ebay_logic import EbayStockChecker
from shopee_logic import ShopeeStockChecker

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def run_ebay_cli():
    print("\n--- eBay Stock Checker (CLI) ---")
    checker = EbayStockChecker(dry_run=True, auto_relist=False)
    results = checker.run_full_process(cli_mode=True)
    print(f"\n✅ 完了: {len(results)} 件のアイテムを処理しました。")
    input("\nEnterキーを押してメニューに戻る...")

async def run_shopee_cli():
    print("\n--- Shopee Stock Checker (CLI) ---")
    checker = ShopeeStockChecker(headless=True)
    
    def cli_progress(text, current, total, results=None):
        if results and len(results) > 0:
            last = results[-1]
            status = last["result"]["status"]
            icon = "📦" if status == "IN_STOCK" else ("❌" if status == "SOLD_OUT" else "⚠️")
            print(f"[{current}/{total}] {icon} ID: {last['display_id']} | {last['result']['url'][:50]}...")
        else:
            print(f"\n{text}")

    output_path, summary, page = await checker.run_full_cycle(cli_progress)
    print(f"\n📊 --- 実行リザルト ---\nチェック対象総数: {summary['total']} 件\n ┣ 📦 在庫あり: {summary['in_stock']} 件\n ┣ ❌ 在庫無し: {summary['sold_out']} 件\n ┗ ⚠️ 判定不能: {summary['unknown']} 件\n✅ Excelデータ更新実行数: {summary['updated']} 件\n")
    print(f"💾 保存先: {output_path}")
    
    ans = input("Shopeeへ自動アップロードを実行しますか？ (y/n): ")
    if ans.strip().lower() == 'y':
        from shopee_logic import auto_upload_shopee
        success = await auto_upload_shopee(page, output_path)
        if success: print("🎉 アップロード完了！")
        else: print("❌ アップロード失敗。")
    
    await page.context.browser.close()
    input("\nEnterキーを押してメニューに戻る...")

def start_gui():
    print("\nGUI ダッシュボードを起動しています...")
    # gui.py を streamlit で実行
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
        print("    📦 Unified Stock Checker System v3.0")
        print("==========================================")
        print("1. eBay Stock Checker (CLI)")
        print("2. Shopee Stock Checker (CLI)")
        print("3. GUI Dashboard を起動 (Streamlit)")
        print("q. 終了")
        print("------------------------------------------")
        
        choice = input("選択してください: ").strip().lower()
        
        if choice == '1':
            run_ebay_cli()
        elif choice == '2':
            asyncio.run(run_shopee_cli())
        elif choice == '3':
            start_gui()
        elif choice == 'q':
            print("終了します。")
            break
        else:
            print("無効な選択です。")
            time.sleep(1)

if __name__ == "__main__":
    import time
    main_menu()
