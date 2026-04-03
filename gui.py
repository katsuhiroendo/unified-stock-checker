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

from shopee_logic import ShopeeStockChecker, auto_upload_shopee, ShopeeLoginRequiredError
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
</style>
""", unsafe_allow_html=True)

st.title("📦 Unified Stock Checker Dashboard")
st.markdown("---")

# セッション状態の初期化
if "results" not in st.session_state: st.session_state.results = []
if "summary" not in st.session_state: st.session_state.summary = None
if "output_path" not in st.session_state: st.session_state.output_path = None
if "is_running" not in st.session_state: st.session_state.is_running = False
if "platform" not in st.session_state: st.session_state.platform = "Shopee"

# サイドバー
with st.sidebar:
    st.header("⚙️ 設定")
    platform = st.selectbox("対象プラットフォームを選択", ["Shopee", "eBay"], key="platform_select")
    st.session_state.platform = platform
    
    st.markdown("---")
    headless = st.checkbox("ヘッドレスモード (ブラウザを表示しない)", value=True)
    
    # Shopee仕様のチェックボックス復元
    skip_price_update = True
    if platform == "Shopee":
        skip_price_update = st.checkbox(
            "在庫の更新のみ（価格情報を更新しない）", 
            value=True, 
            help="このチェックを入れると、サイト上の価格に関わらず、在庫の有無(0 or 1)だけを同期します。"
        )
    else:
        dry_run = st.checkbox("DRY RUN (テストモード)", value=True, help="eBayでの取り下げや出品を実際に行わずシミュレーションのみ行います。")
        auto_relist = st.checkbox("在庫復活時に自動再出品", value=False)
        
    st.markdown("---")
    if st.button("🔌 アプリを終了する"):
        st.warning("プログラムを停止しました。")
        os._exit(0)

# メイン画面
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader(f"🚀 {platform} 操作")
    start_button = st.button(f"在庫チェックを開始", disabled=st.session_state.is_running)

# 実行中の進捗表示用プレースホルダー
progress_bar = st.empty()
status_text = st.empty()

# メトリクス表示
m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m1, m2, m3, m4 = m_col1.empty(), m_col2.empty(), m_col3.empty(), m_col4.empty()

# 実行ロジック
if start_button:
    st.session_state.is_running = True
    st.session_state.results = []
    st.session_state.output_path = None
    
    if platform == "Shopee":
        checker = ShopeeStockChecker(headless=headless)
        def gui_callback(text, current, total, results=None):
            status_text.markdown(f"**ステータス:** {text}")
            if total > 0: progress_bar.progress(current / total)
            if results:
                st.session_state.results = results
                in_stock = len([r for r in results if r["result"].get("status") == "IN_STOCK"])
                sold_out = len([r for r in results if r["result"].get("status") == "SOLD_OUT"])
                unknown = len([r for r in results if r["result"].get("status") == "UNKNOWN"])
                m1.metric("トータル", len(results)); m2.metric("在庫あり", in_stock); m3.metric("在庫無し", sold_out, delta_color="inverse"); m4.metric("判定不能", unknown, delta_color="off")

        try:
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            path, summary, page = loop.run_until_complete(checker.run_full_cycle(gui_callback, skip_price_update=skip_price_update))
            st.session_state.summary = summary; st.session_state.output_path = path; st.balloons()
        except ShopeeLoginRequiredError:
            st.error("🔒 Shopeeへのログインが必要です。")
            st.info("💡 **解決方法:** \n1. 左メニューの「ヘッドレスモード」の**チェックを外します**。\n2. 再度「在庫チェックを開始」を押し、表示されたブラウザ画面で手動ログインしてください。")
        except Exception as e:
            st.error(f"エラー: {e}")
        finally: st.session_state.is_running = False

    elif platform == "eBay":
        checker = EbayStockChecker(dry_run=dry_run, auto_relist=auto_relist)
        status_text.markdown("**ステータス:** eBay同期 & チェック中...")
        
        try:
            checker.sync_ebay_data()
            import csv
            items = []
            with open(checker.items_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f); items = [(r["ebay_id"], r["supplier_url"]) for r in reader]
            
            def ebay_gui_callback(res, current, total):
                progress_bar.progress(current/total)
                status_text.markdown(f"**進捗:** {current}/{total} | ID: {res['ebay_id']}")
                res_data = {"row_num": current, "display_id": res["ebay_id"], "result": {"status": "IN_STOCK" if res["status"]=="在庫あり" else "SOLD_OUT" if res["status"]=="在庫なし" else "UNKNOWN", "url": res["url"], "price": 0, "is_fleamarket": True}}
                st.session_state.results.append(res_data)
                r_list = st.session_state.results
                m1.metric("トータル", total); m2.metric("在庫あり", len([x for x in r_list if x["result"]["status"]=="IN_STOCK"])); m3.metric("在庫無し", len([x for x in r_list if x["result"]["status"]=="SOLD_OUT"]), delta_color="inverse")
            
            results = checker.run_stock_check_batch(items, callback=ebay_gui_callback)
            st.success("eBayチェック完了！")
            st.balloons()
        except Exception as e: st.error(f"エラー: {e}")
        finally: st.session_state.is_running = False

# 実行結果リスト表示
if st.session_state.results:
    st.markdown("---")
    st.subheader(f"📋 {platform} 実行結果リスト")
    st.info("💡 「在庫あり」ボタンを切り替えてから、下の反映ボタンを押してください。")
    
    data = []
    for r in st.session_state.results:
        res = r["result"]
        data.append({
            "row_num": r.get("row_num"),
            "is_fleamarket": res.get("is_fleamarket", False),
            "ID": r["display_id"],
            "在庫あり": (res["status"] == "IN_STOCK"),
            "仕入価格": res.get("price", 0),
            "出品価格(直接)": 0,
            "販売サイト": urlparse(res["url"]).netloc,
            "URL": res["url"],
            "_status": res["status"]
        })
    df = pd.DataFrame(data)
    
    filter_status = st.multiselect("表示するステータスを選択", ["IN_STOCK", "SOLD_OUT", "UNKNOWN"], default=["SOLD_OUT", "UNKNOWN"])
    display_df = df[df["_status"].isin(filter_status)] if filter_status else df
    
    edited_df = st.data_editor(
        display_df,
        column_config={
            "row_num": None, "is_fleamarket": None, "_status": None,
            "ID": st.column_config.TextColumn("ID", disabled=True),
            "在庫あり": st.column_config.CheckboxColumn("在庫あり"),
            "仕入価格": st.column_config.NumberColumn("仕入価格", disabled=skip_price_update),
            "出品価格(直接)": st.column_config.NumberColumn("出品価格(直接)", disabled=skip_price_update),
            "販売サイト": st.column_config.TextColumn("販売サイト", disabled=True),
            "URL": st.column_config.LinkColumn("商品ページを開く", disabled=True)
        },
        use_container_width=True, hide_index=True, key="results_editor"
    )

    # 反映・アップロードセクションの完全復元
    if platform == "Shopee" and st.session_state.output_path:
        st.markdown("---")
        st.subheader("✅ 最終反映・Shopeeアップロード")
        col_up1, col_up2 = st.columns(2)
        
        with col_up1:
            if st.button("🚀 修正を反映してShopeeへアップロード！", type="primary"):
                with st.spinner("反映中..."):
                    try:
                        checker = ShopeeStockChecker(headless=headless)
                        wb = load_workbook(st.session_state.output_path)
                        ws = wb.active
                        final_excel_path, stats = checker.save_manual_results(
                            wb, ws, edited_df.to_dict('records'), skip_price_update=skip_price_update
                        )
                        
                        async def upload_flow():
                            from playwright.async_api import async_playwright
                            async with async_playwright() as p:
                                browser = await p.chromium.launch_persistent_context(
                                    user_data_dir=checker.user_data_dir,
                                    headless=checker.headless,
                                    args=["--disable-blink-features=AutomationControlled"]
                                )
                                up_page = browser.pages[0] if browser.pages else await browser.new_page()
                                success = await auto_upload_shopee(up_page, final_excel_path)
                                await browser.close()
                                return success
                        
                        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                        success = loop.run_until_complete(upload_flow())

                        if success:
                            st.success(f"🎉 アップロード成功！ {stats['updated']} 件のデータを反映しました。")
                            st.balloons()
                        else:
                            st.error("❌ アップロードに失敗しました。セッション切れの可能性があります。")
                    except Exception as e:
                        st.error(f"エラー: {e}")

        with col_up2:
            if st.button("💾 修正をExcelに保存のみ実行"):
                try:
                    checker = ShopeeStockChecker()
                    wb = load_workbook(st.session_state.output_path)
                    ws = wb.active
                    final_excel_path, stats = checker.save_manual_results(
                        wb, ws, edited_df.to_dict('records'), skip_price_update=skip_price_update
                    )
                    st.success(f"💾 Excelを更新しました: {os.path.basename(final_excel_path)}")
                except Exception as e:
                    st.error(f"エラー: {e}")
