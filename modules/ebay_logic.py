import os
import csv
import time
import random
import datetime
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright
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
    def check_mercari(self, page, page_text):
        if "この商品は売り切れました" in page_text or "この商品は販売終了しました" in page_text:
            return "在庫なし", "テキスト演出"
        try:
            if page.locator('[aria-label="売り切れ"]').count() > 0: return "在庫なし", "aria-label"
            if page.locator("mer-sticker").count() > 0: return "在庫なし", "mer-sticker"
        except: pass
        return "在庫あり", ""

    def check_yahoo_auctions(self, page, page_text):
        keywords = ["このオークションは終了しています", "オークションは終了しました", "落札済み"]
        for kw in keywords:
            if kw in page_text: return "在庫なし", f"テキスト「{kw}」"
        return "在庫あり", ""

    def check_yahoo_fleamarket(self, page, page_text):
        keywords = ["この商品は販売終了しました", "売れました", "販売終了", "コピーして出品する"]
        for kw in keywords:
            if kw in page_text: return "在庫なし", f"テキスト「{kw}」"
        return "在庫あり", ""

    def check_rakuma(self, page, page_text):
        if "この商品は売り切れました" in page_text: return "在庫なし", "テキスト演出"
        return "在庫あり", ""

    def check_item(self, page, url, item_id=""):
        if not url.startswith("http"): url = "https://" + url
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(500)
            page_text = page.locator("body").inner_text()
            
            if "auctions.yahoo.co.jp" in url: return self.check_yahoo_auctions(page, page_text)
            elif "paypayfleamarket.yahoo.co.jp" in url: return self.check_yahoo_fleamarket(page, page_text)
            elif "fril.jp" in url: return self.check_rakuma(page, page_text)
            elif "mercari.com" in url: return self.check_mercari(page, page_text)
            else: return self.check_mercari(page, page_text)
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
            
            # Active
            req = {"EndTimeFrom": now.strftime('%Y-%m-%dT%H:%M:%S.000Z'), "EndTimeTo": (now + timedelta(days=119)).strftime('%Y-%m-%dT%H:%M:%S.000Z'), "Pagination": {"EntriesPerPage": 200, "PageNumber": 1}, "DetailLevel": "ReturnAll"}
            res = api.execute("GetSellerList", req)
            items = res.reply.get("ItemArray", {}).get("Item", [])
            if not isinstance(items, list): items = [items]
            
            valid_domains = ["mercari.com", "auctions.yahoo.co.jp", "paypayfleamarket.yahoo.co.jp", "fril.jp", "amazon.co.jp"]
            active_list = []
            for item in items:
                sku = item.get("SKU")
                if item.get("SellingStatus", {}).get("ListingStatus") == "Active" and sku:
                    if any(dom in sku for dom in valid_domains):
                        active_list.append((item.get("ItemID"), sku if sku.startswith("http") else "https://" + sku))
            
            with open(self.items_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["ebay_id", "supplier_url"])
                writer.writerows(active_list)

            # Ended
            req_e = {"EndTimeFrom": (now - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S.000Z'), "EndTimeTo": now.strftime('%Y-%m-%dT%H:%M:%S.000Z'), "Pagination": {"EntriesPerPage": 200, "PageNumber": 1}, "DetailLevel": "ReturnAll"}
            res_e = api.execute("GetSellerList", req_e)
            items_e = res_e.reply.get("ItemArray", {}).get("Item", [])
            if not isinstance(items_e, list): items_e = [items_e]
            
            ended_list = []
            for item in items_e:
                sku = item.get("SKU") or ""
                if item.get("SellingStatus", {}).get("ListingStatus") in ("Ended", "Completed") and "http" in sku:
                    ended_list.append((item.get("ItemID"), sku))
            
            with open(self.ended_items_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["item_id", "supplier_url"])
                writer.writerows(ended_list)
            return True
        except Exception as e:
            print(f"Sync error: {e}")
            return False

    def run_stock_check_batch(self, items, check_revival=False, callback=None):
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", locale="ja-JP")
            page = context.new_page()
            for idx, (ebay_id, url) in enumerate(items, 1):
                status, reason = self.check_item(page, url, ebay_id)
                res_item = {"ebay_id": ebay_id, "url": url, "status": status, "reason": reason}
                results.append(res_item)
                
                if callback: callback(res_item, idx, len(items))
                
                if not check_revival and status == "在庫なし":
                    self.end_ebay_item(ebay_id)
                
                if idx < len(items): time.sleep(random.uniform(1.0, 2.0))
            browser.close()
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
            chunk_size = (len(active_items) + self.max_workers - 1) // self.max_workers
            chunks = [active_items[i:i + chunk_size] for i in range(0, len(active_items), chunk_size)]
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self.run_stock_check_batch, chunk, False) for chunk in chunks]
                for future in as_completed(futures): all_results.extend(future.result())
        
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
            revival_res = self.run_stock_check_batch(ended_items, True)
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
