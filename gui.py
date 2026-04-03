import streamlit as st
import asyncio
import pandas as pd
import os
import datetime
from urllib.parse import urlparse
import sys
from openpyxl import load_workbook

# 共通モジュールのパスを追加
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, "modules"))

from shopee_logic import ShopeeStockChecker, auto_download_shopee, ShopeeLoginRequiredError
from ebay_logic import EbayStockChecker

# ページ設定
st.set_page_config(
    page_title="Unified Stock Checker Dashboard",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# スタイル設定
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; font-weight: bold; }
    .shopee-btn { background-color: #ee4d2d !important; color: white !important; }
    .ebay-btn { background-color: #0064d2 !important; color: white !important; }
    .all-btn { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

st.title("📦 Unified Stock Checker Dashboard")
st.markdown("---")

# セッション状態の初期化
if "results_shopee" not in st.session_state: st.session_state.results_shopee = []
if "results_ebay" not in st.session_state: st.session_state.results_ebay = []
if "output_path_shopee" not in st.session_state: st.session_state.output_path_shopee = None
if "is_running" not in st.session_state: st.session_state.is_running = False
if "platform" not in st.session_state: st.session_state.platform = "Shopee"

# サイドバー
with st.sidebar:
    st.header("⚙️ 設定")
    platform = st.selectbox("対象プラットフォームを選択", ["Shopee", "eBay", "All (Shopee & eBay)"], key="platform_select")
    st.session_state.platform = platform
    
    st.markdown("---")
    headless = st.checkbox("ヘッドレスモード (ブラウザを表示しない)", value=True)
    
    skip_price_update = True
    if "Shopee" in platform or "All" in platform:
        skip_price_update = st.checkbox(
            "在庫の更新のみ（価格情報を更新しない）", 
            value=True, 
            help="このチェックを入れると、サイト上の価格に関わらず、在庫の有無(0 or 1)だけを同期します。"
        )
    
    if "eBay" in platform or "All" in platform:
        dry_run = st.checkbox("DRY RUN (eBayテストモード)", value=True, help="eBayでの取り下げや出品を実際に行わずシミュレーションのみ行います。")
        auto_relist = st.checkbox("在庫復活時に自動再出品 (eBay)", value=False)
        
    st.markdown("---")
    if st.button("🔌 アプリを終了する"):
        st.warning("プログラムを停止しました。")
        os._exit(0)

# メイン画面 (同時実行時は2カラムレイアウト)
st.subheader(f"🚀 {platform} 操作")
start_button = st.button(f"在庫チェックを開始", disabled=st.session_state.is_running)

# プレースホルダー作成
p_col1, p_col2 = st.columns(2)
with p_col1:
    st.markdown("### Shopee Status")
    shopee_status = st.empty()
    shopee_progress = st.empty()
    sm_col1, sm_col2, sm_col3, sm_col4 = st.columns(4)
    sm1, sm2, sm3, sm4 = sm_col1.empty(), sm_col2.empty(), sm_col3.empty(), sm_col4.empty()

with p_col2:
    st.markdown("### eBay Status")
    ebay_status = st.empty()
    ebay_progress = st.empty()
    em_col1, em_col2, em_col3 = st.columns(3)
    em1, em2, em3 = em_col1.empty(), em_col2.empty(), em_col3.empty()

# 実行ロジック
async def run_shopee(checker, callback):
    try:
        path, summary, page = await checker.run_full_cycle(callback, skip_price_update=skip_price_update)
        st.session_state.output_path_shopee = path
        return True
    except ShopeeLoginRequiredError:
        st.error("🔒 Shopeeへのログインが必要です。ヘッドレスモードをオフにしてログインしてください。")
        return False
    except Exception as e:
        st.error(f"Shopeeエラー: {e}")
        return False

def run_ebay_sync(checker, callback):
    try:
        checker.sync_ebay_data()
        import csv
        items = []
        with open(checker.items_csv, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f); items = [(r["ebay_id"], r["supplier_url"]) for r in reader]
        checker.run_stock_check_batch(items, callback=callback)
        return True
    except Exception as e:
        st.error(f"eBayエラー: {e}")
        return False

if start_button:
    st.session_state.is_running = True
    st.session_state.results_shopee = []
    st.session_state.results_ebay = []
    st.session_state.output_path_shopee = None

    async def start_all():
        tasks = []
        if "Shopee" in platform or "All" in platform:
            shopee_checker = ShopeeStockChecker(headless=headless)
            def shopee_cb(text, cur, tot, res=None):
                shopee_status.markdown(f"**状態:** {text}")
                if tot > 0: shopee_progress.progress(cur/tot)
                if res:
                    st.session_state.results_shopee = res
                    in_s = len([x for x in res if x["result"]["status"]=="IN_STOCK"])
                    sold = len([x for x in res if x["result"]["status"]=="SOLD_OUT"])
                    unkn = len([x for x in res if x["result"]["status"]=="UNKNOWN"])
                    sm1.metric("トータル", len(res)); sm2.metric("在庫あり", in_s); sm3.metric("在庫無し", sold, delta_color="inverse"); sm4.metric("判定不能", unkn)
            tasks.append(run_shopee(shopee_checker, shopee_cb))
        else:
            shopee_status.info("対象外")

        if "eBay" in platform or "All" in platform:
            ebay_checker = EbayStockChecker(dry_run=dry_run, auto_relist=auto_relist)
            def ebay_cb(res, cur, tot):
                ebay_status.markdown(f"**進捗:** {cur}/{tot} | ID: {res['ebay_id']}")
                ebay_progress.progress(cur/tot)
                res_data = {"display_id": res["ebay_id"], "result": {"status": "IN_STOCK" if res["status"]=="在庫あり" else "SOLD_OUT" if res["status"]=="在庫なし" else "UNKNOWN", "url": res["url"], "price": 0}}
                st.session_state.results_ebay.append(res_data)
                r_list = st.session_state.results_ebay
                em1.metric("トータル", tot); em2.metric("在庫あり", len([x for x in r_list if x["result"]["status"]=="IN_STOCK"])); em3.metric("在庫無し", len([x for x in r_list if x["result"]["status"]=="SOLD_OUT"]), delta_color="inverse")
            tasks.append(asyncio.to_thread(run_ebay_sync, ebay_checker, ebay_cb))
        else:
            ebay_status.info("対象外")

        results = await asyncio.gather(*tasks)
        if any(results): st.balloons()
        st.session_state.is_running = False

    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.run_until_complete(start_all())

# 結果リスト表示 (タブ形式で整理)
if st.session_state.results_shopee or st.session_state.results_ebay:
    st.markdown("---")
    res_tab1, res_tab2 = st.tabs(["🛍️ Shopee Results", "🌎 eBay Results"])
    
    with res_tab1:
        if st.session_state.results_shopee:
            data_s = []
            for r in st.session_state.results_shopee:
                res = r["result"]
                data_s.append({"row_num": r.get("row_num"), "ID": r["display_id"], "在庫あり": (res["status"] == "IN_STOCK"), "仕入価格": res.get("price", 0), "販売サイト": urlparse(res["url"]).netloc, "URL": res["url"], "_status": res["status"]})
            df_s = pd.DataFrame(data_s)
            f_status_s = st.multiselect("Shopee表示フィルター", ["IN_STOCK", "SOLD_OUT", "UNKNOWN"], default=["SOLD_OUT", "UNKNOWN"], key="f_s")
            disp_s = df_s[df_s["_status"].isin(f_status_s)] if f_status_s else df_s
            edited_s = st.data_editor(disp_s, column_config={"row_num": None, "_status": None, "ID": st.column_config.TextColumn("ID", disabled=True), "仕入価格": st.column_config.NumberColumn("仕入価格", disabled=skip_price_update), "URL": st.column_config.LinkColumn("商品ページ")}, use_container_width=True, hide_index=True, key="ed_s")
            
            if st.session_state.output_path_shopee:
                if st.button("🚀 Shopeeへアップロード反映", type="primary"):
                    with st.spinner("反映中..."):
                        checker = ShopeeStockChecker(headless=headless)
                        wb = load_workbook(st.session_state.output_path_shopee); ws = wb.active
                        final_path, _ = checker.save_manual_results(wb, ws, edited_s.to_dict('records'), skip_price_update=skip_price_update)
                        async def up():
                            from playwright.async_api import async_playwright
                            async with async_playwright() as p:
                                browser = await p.chromium.launch_persistent_context(user_data_dir=checker.user_data_dir, headless=checker.headless, args=["--disable-blink-features=AutomationControlled"])
                                up_page = browser.pages[0] if browser.pages else await browser.new_page()
                                success = await auto_download_shopee(up_page, final_path) if False else await auto_upload_shopee(up_page, final_path)
                                await browser.close(); return success
                        if asyncio.run(up()): st.success("🎉 Shopeeアップロード完了！")
        else: st.info("Shopeeの実行結果はありません。")

    with res_tab2:
        if st.session_state.results_ebay:
            data_e = [{"ID": r["display_id"], "在庫あり": (r["result"]["status"]=="IN_STOCK"), "URL": r["result"]["url"], "_status": r["result"]["status"]} for r in st.session_state.results_ebay]
            df_e = pd.DataFrame(data_e)
            f_status_e = st.multiselect("eBay表示フィルター", ["IN_STOCK", "SOLD_OUT", "UNKNOWN"], default=["SOLD_OUT", "UNKNOWN"], key="f_e")
            disp_e = df_e[df_e["_status"].isin(f_status_e)] if f_status_e else df_e
            st.data_editor(disp_e, column_config={"_status": None, "ID": st.column_config.TextColumn("ID", disabled=True), "URL": st.column_config.LinkColumn("商品ページ")}, use_container_width=True, hide_index=True, key="ed_e")
            st.info("eBayの反映は在庫チェック実行時に自動（DryRunオフの場合）で行われます。")
        else: st.info("eBayの実行結果はありません。")
