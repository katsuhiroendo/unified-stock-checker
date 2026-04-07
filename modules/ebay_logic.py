import os
import csv
import time
import random
import datetime
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# プロジェクトルートの .env を読み込む
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

class EbayStockChecker:
    def __init__(self, dry_run=True, auto_relist=False, max_workers=8):
        self.dry_run = dry_run
        self.auto_relist = auto_relist
        self.max_workers = max_workers
        self.data_dir = os.path.join(BASE_DIR, "data", "ebay")
        self.log_dir = os.path.join(BASE_DIR, "logs")
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        self.items_csv = os.path.join(self.data_dir, "items.csv")
        self.ended_items_csv = os.path.join(self.data_dir, "ended_items.csv")
        self.relisted_log = os.path.join(self.data_dir, "relisted_log.txt")
        self.oos_report = os.path.join(self.data_dir, "oos_report.txt")

    # ==========================================
    # 在庫判定ロジック (check_all.py から移植)
    # ==========================================
    async def check_mercari(self, page, page_text):
        if "この商品は売り切れました" in page_text or "この商品は販売終了しました" in page_text:
            return "在庫なし", "テキスト演出"
        try:
            if await page.locator('[aria-label="売り切れ"]').count() > 0: return "在庫なし", "aria-label"
            if await page.locator("mer-sticker").count() > 0: return "在庫なし", "mer-sticker"
        except: pass
        return "在庫あり", ""

    async def check_yahoo_auctions(self, page, page_text):
        keywords = ["このオークションは終了しています", "オークションは終了しました", "落札済み"]
        for kw in keywords:
            if kw in page_text: return "在庫なし", f"テキスト「{kw}」"
        return "在庫あり", ""

    async def check_yahoo_fleamarket(self, page, page_text):
        keywords = ["この商品は販売終了しました", "売れました", "販売終了", "コピーして出品する"]
        for kw in keywords:
            if kw in page_text: return "在庫なし", f"テキスト「{kw}」"
        return "在庫あり", ""

    async def check_rakuma(self, page, page_text):
        if "この商品は売り切れました" in page_text: return "在庫なし", "テキスト演出"
        return "在庫あり", ""

    async def check_item(self, page, url, item_id=""):
        if not url.startswith("http"): url = "https://" + url
        
        # paypayne.jp (短縮URL) をフルURLに変換して解決エラーを回避
        if "paypayne.jp/" in url:
            if "/i/" in url:
                item_code = url.split("/i/")[-1].split("?")[0]
                url = f"https://paypayfleamarket.yahoo.co.jp/item/{item_code}"
            elif "/item/" in url:
                item_code = url.split("/item/")[-1].split("?")[0]
                url = f"https://paypayfleamarket.yahoo.co.jp/item/{item_code}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(500)
            page_text = await page.locator("body").inner_text()
            
            if "auctions.yahoo.co.jp" in url: return await self.check_yahoo_auctions(page, page_text)
            elif "paypayfleamarket.yahoo.co.jp" in url or "paypayne.jp" in url: return await self.check_yahoo_fleamarket(page, page_text)
            elif "fril.jp" in url or "rakuma.rakuten.co.jp" in url: return await self.check_rakuma(page, page_text)
            elif "mercari.com" in url or "jp.mercari.com" in url: return await self.check_mercari(page, page_text)
            else: return await self.check_mercari(page, page_text)
        except Exception as e:
            return "判定不能", f"Error: {e}"

    # ==========================================
    # eBay API 連携
    # ==========================================
    def end_ebay_item(self, ebay_id):
        if self.dry_run: return True
        try:
            from ebaysdk.trading import Connection as Trading
            api = Trading(config_file=None, appid=os.getenv("EBAY_APP_ID"), devid=os.getenv("EBAY_DEV_ID"), certid=os.getenv("EBAY_CERT_ID"), token=os.getenv("EBAY_TOKEN"), siteid="0")
            api.execute("EndItem", {"ItemID": ebay_id, "EndingReason": "LostOrBroken"})
            return True
        except: return False

    def relist_ebay_item(self, ebay_id):
        if self.dry_run: return True, "DRY_RUN_ID"
        try:
            from ebaysdk.trading import Connection as Trading
            api = Trading(config_file=None, appid=os.getenv("EBAY_APP_ID"), devid=os.getenv("EBAY_DEV_ID"), certid=os.getenv("EBAY_CERT_ID"), token=os.getenv("EBAY_TOKEN"), siteid="0")
            res = api.execute("RelistItem", {"Item": {"ItemID": ebay_id}})
            if res.reply.Ack in ("Success", "Warning"): return True, res.reply.ItemID
            return False, None
        except: return False, None

    def get_already_relisted_ids(self):
        relisted = set()
        if os.path.exists(self.relisted_log):
            with open(self.relisted_log, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if parts: relisted.add(parts[0])
        return relisted

    def record_relisted(self, old_id, new_id, url):
        with open(self.relisted_log, "a", encoding="utf-8") as f:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{old_id},{new_id},{url},{now}\n")

    def sync_ebay_data(self):
        """Phase 1: Sync"""
        try:
            from ebaysdk.trading import Connection as Trading
            api = Trading(config_file=None, appid=os.getenv("EBAY_APP_ID"), devid=os.getenv("EBAY_DEV_ID"), certid=os.getenv("EBAY_CERT_ID"), token=os.getenv("EBAY_TOKEN"), siteid="0")
            now = datetime.datetime.utcnow()
            
            # Active items pagination logic
            active_list = []
            valid_domains = [
                "mercari.com", "jp.mercari.com", 
                "auctions.yahoo.co.jp", "paypayfleamarket.yahoo.co.jp", "paypayne.jp",
                "fril.jp", "rakuma.rakuten.co.jp",
                "amazon.co.jp", "rakuten.co.jp", "shopping.yahoo.co.jp"
            ]
            
            page_num = 1
            while True:
                req = {
                    "EndTimeFrom": now.strftime('%Y-%m-%dT%H:%M:%S.000Z'), 
                    "EndTimeTo": (now + timedelta(days=119)).strftime('%Y-%m-%dT%H:%M:%S.000Z'), 
                    "Pagination": {"EntriesPerPage": 200, "PageNumber": page_num}, 
                    "DetailLevel": "ReturnAll"
                }
                res = api.execute("GetSellerList", req)
                if res.reply.Ack == "Failure":
                    raise Exception(f"eBay API Error: {res.reply.Errors.ShortMessage}")
                page_items = res.reply.get("ItemArray", {}).get("Item", [])
                if not isinstance(page_items, list): page_items = [page_items]
                
                if not page_items:
                    break
                
                for item in page_items:
                    sku = item.get("SKU")
                    if item.get("SellingStatus", {}).get("ListingStatus") == "Active" and sku:
                        if any(dom in sku for dom in valid_domains):
                            active_list.append((item.get("ItemID"), sku if sku.startswith("http") else "https://" + sku))
                
                total_pages = int(res.reply.get("PaginationResult", {}).get("TotalNumberOfPages", 1))
                if page_num >= total_pages:
                    break
                page_num += 1
            
            with open(self.items_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["ebay_id", "supplier_url", "status"])
                writer.writerows([(eid, url, "在庫あり") for eid, url in active_list])

            # Ended items pagination logic
            ended_list = []
            page_num_e = 1
            while True:
                req_e = {
                    "EndTimeFrom": (now - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S.000Z'), 
                    "EndTimeTo": now.strftime('%Y-%m-%dT%H:%M:%S.000Z'), 
                    "Pagination": {"EntriesPerPage": 200, "PageNumber": page_num_e}, 
                    "DetailLevel": "ReturnAll"
                }
                res_e = api.execute("GetSellerList", req_e)
                if res_e.reply.Ack == "Failure":
                    raise Exception(f"eBay API Error (Ended): {res_e.reply.Errors.ShortMessage}")
                items_e = res_e.reply.get("ItemArray", {}).get("Item", [])
                if not isinstance(items_e, list): items_e = [items_e]
                
                if not items_e:
                    break
                    
                for item in items_e:
                    sku = item.get("SKU") or ""
                    if item.get("SellingStatus", {}).get("ListingStatus") in ("Ended", "Completed") and "http" in sku:
                        ended_list.append((item.get("ItemID"), sku))
                
                total_pages_e = int(res_e.reply.get("PaginationResult", {}).get("TotalNumberOfPages", 1))
                if page_num_e >= total_pages_e:
                    break
                page_num_e += 1
            
            with open(self.ended_items_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["item_id", "supplier_url", "status"])
                writer.writerows([(eid, url, "在庫なし") for eid, url in ended_list])
            return True, "Success"
        except Exception as e:
            error_msg = str(e)
            if "21916013" in error_msg or "Token has been revoked" in error_msg:
                error_msg = "eBayトークンが失効しています。.envファイルを更新してください。"
            print(f"Sync error: {error_msg}")
            return False, error_msg

    async def run_stock_check_batch(self, items, check_revival=False, callback=None):
        results = []
        concurrency = 12
        semaphore = asyncio.Semaphore(concurrency)
        processed_count = 0
        total_items = len(items)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", 
                locale="ja-JP"
            )

            async def fetch_item(ebay_id, url):
                nonlocal processed_count
                async with semaphore:
                    page = await context.new_page()
                    try:
                        status, reason = await self.check_item(page, url, ebay_id)
                        res_item = {"ebay_id": ebay_id, "url": url, "status": status, "reason": reason}
                        results.append(res_item)
                        processed_count += 1
                        if callback:
                            callback(res_item, processed_count, total_items)
                        return res_item
                    finally:
                        await page.close()

            tasks = [fetch_item(eid, url) for eid, url in items]
            await asyncio.gather(*tasks)
            await browser.close()
        return results

    def run_full_process(self, cli_mode=True):
        """CLI向けの一括処理"""
        print("Phase 1: 同期中...")
        self.sync_ebay_data()
        
        active_items = []
        try:
            with open(self.items_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader: active_items.append((row["ebay_id"], row["supplier_url"]))
        except: pass

        all_results = []
        if active_items:
            print(f"Phase 2: {len(active_items)} 件の在庫チェック中...")
            all_results.extend(asyncio.run(self.run_stock_check_batch(active_items, False)))
        
        # Endeditems
        ended_items = []
        already = self.get_already_relisted_ids()
        try:
            with open(self.ended_items_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    eid, url = row["item_id"], row["supplier_url"]
                    if eid not in already: ended_items.append((eid, url))
        except: pass

        if ended_items:
            print(f"Phase 3: {len(ended_items)} 件の復活チェック中...")
            revival_res = asyncio.run(self.run_stock_check_batch(ended_items, True))
            for r in revival_res:
                if r["status"] == "在庫あり":
                    print(f"✨ 復活検知: {r['ebay_id']}")
                    if self.auto_relist:
                        success, new_id = self.relist_ebay_item(r["ebay_id"])
                        if success: self.record_relisted(r["ebay_id"], new_id, r["url"])
                    elif cli_mode:
                        ans = input(f"再出品しますか？(y/n): ").lower()
                        if ans == 'y':
                            success, new_id = self.relist_ebay_item(r["ebay_id"])
                            if success: self.record_relisted(r["ebay_id"], new_id, r["url"])
            all_results.extend(revival_res)
        
        return all_results

    def apply_csv_changes_to_ebay(self):
        """
        data/ebay/items.csv と ended_items.csv の内容を読み取り、
        現在の CSV の状態を eBay 上に反映させる（手動反映用）。
        """
        import csv
        updated_count = 0
        
        # 1. 出品中アイテムの在庫チェック & 取り下げ
        if os.path.exists(self.items_csv):
            with open(self.items_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ebay_id = row.get("ebay_id")
                    status = row.get("status") # "在庫あり" or "在庫なし"
                    if not ebay_id or not status: continue
                    
                    if status == "在庫なし":
                        print(f"Ending item: {ebay_id}")
                        success = self.end_ebay_item(ebay_id)
                        if success: updated_count += 1

        # 2. 終了済みアイテムの再出品（CSVで「在庫あり」に書き換えられている場合）
        if os.path.exists(self.ended_items_csv):
            ended_rows = []
            with open(self.ended_items_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                ended_rows = list(reader)

            remaining_ended = []
            already = self.get_already_relisted_ids()
            
            for row in ended_rows:
                ebay_id = row.get("item_id") or row.get("ebay_id")
                status = row.get("status")
                url = row.get("supplier_url")
                
                if not ebay_id: continue

                if status == "在庫あり" and ebay_id not in already:
                    print(f"Relisting item: {ebay_id}")
                    success, new_id = self.relist_ebay_item(ebay_id)
                    if success:
                        if not self.dry_run:
                            self.record_relisted(ebay_id, new_id, url)
                        updated_count += 1
                        continue # 成功した場合は ended_items から除外
                remaining_ended.append(row)
            
            # ended_items.csv を更新（再出品されたものを除く / dry_run時は更新しない）
            if not self.dry_run and updated_count > 0:
                with open(self.ended_items_csv, mode="w", encoding="utf-8", newline="") as f:
                    if ended_rows:
                        writer = csv.DictWriter(f, fieldnames=ended_rows[0].keys())
                        writer.writeheader()
                        writer.writerows(remaining_ended)

        return updated_count
    def save_gui_changes(self, edited_results):
        """
        GUIの st.data_editor から返されたデータを CSV に反映させる。
        edited_results: [{'ID': '...', '在庫あり': True, ...}, ...]
        """
        # ID -> status / URL のマップを作成
        id_to_status = {}
        id_to_url = {}
        for r in edited_results:
            id_val = str(r["ID"])
            status_str = "在庫あり" if r.get("在庫あり") else "在庫なし"
            id_to_status[id_val] = status_str
            if r.get("販売サイト"):
                id_to_url[id_val] = r["販売サイト"]

        # items.csv を更新
        if os.path.exists(self.items_csv):
            rows = []
            with open(self.items_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    eid = row.get("ebay_id")
                    if eid in id_to_status:
                        row["status"] = id_to_status[eid]
                    if eid in id_to_url:
                        row["supplier_url"] = id_to_url[eid]
                    rows.append(row)
            
            with open(self.items_csv, "w", encoding="utf-8", newline="") as f:
                if rows:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)

        # ended_items.csv を更新
        if os.path.exists(self.ended_items_csv):
            rows = []
            with open(self.ended_items_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    eid = row.get("item_id") or row.get("ebay_id")
                    if eid in id_to_status:
                        row["status"] = id_to_status[eid]
                    if eid in id_to_url:
                        row["supplier_url"] = id_to_url[eid]
                    rows.append(row)
            
            with open(self.ended_items_csv, "w", encoding="utf-8", newline="") as f:
                if rows:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
        
        return len(id_to_status)
