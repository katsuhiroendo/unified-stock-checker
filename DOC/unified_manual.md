# Unified Stock Checker システム 統合マニュアル (v4.0)

本システムは、eBay と Shopee の在庫・出品状況を一つのインターフェースで管理できるツールです。
最新バージョンでは、バックグラウンドでの**完全自動監視機能**が追加されました。

---

## 🛠 準備

### 1. 依存ライブラリのインストール
プロジェクトルートで以下のコマンドを実行してください。

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 環境変数 (.env) の設定
プロジェクトルートに `.env` ファイルを作成し、eBay API の認証情報を設定してください。

```env
EBAY_APP_ID=あなたの_app_id
EBAY_DEV_ID=あなたの_dev_id
EBAY_CERT_ID=あなたの_cert_id
EBAY_TOKEN=あなたの_auth_token
```

---

## 🏃‍♂️ 起動方法

### GUI ダッシュボード (Streamlit)
本システムのメイン操作画面です。

```bash
streamlit run gui.py
```
ブラウザでダッシュボードが開き、サイドバーから各機能へアクセスできます。

---

## 🤖 自動監視モード (Automated Monitoring)

サイドバーの「🤖 自動監視設定」から有効化できます。

### 主な機能
- **定期実行**: 設定した周期（デフォルト4時間）ごとに、eBay と Shopee の在庫を自動でチェックします。
- **リアルタイムログ**: サイドバーの「🛡️ 監視ログ」コンソールに、現在の実行状況がリアルタイムで表示されます。
- **完全自動アクション**:
  - **eBay**: 在庫切れ商品の自動取り下げ、および在庫復活商品の自動再出品を行います。
  - **Shopee**: データの自動ダウンロード、在庫状況（0または1）の更新、および自動アップロードを一気通貫で行います。

### ログの確認
実行結果は以下のファイルにも保存されます。
- `logs/auto_monitor_YYYYMMDD.log`: 自動監視の動作履歴

---

## ⚡ 手動実行・同時実行（Parallel Check）

### GUI での同時実行
- サイドバーの「対象プラットフォーム」で **「All (Shopee & eBay)」** を選択します。
- 実行を開始すると、画面が左右に分割され、進捗を同時に確認できます。

### CLI メニュー
ターミナルから `main.py` を実行することで、CLI モードでの操作も可能です。

---

## 📂 フォルダ構成

- `gui.py`: 統合ダッシュボード (Streamlit) / 自動監視エンジン
- `modules/`: プラットフォーム別のコアロジック
- `data/`: 出品データやチェックポイント
  - `ebay/`: items.csv (出品中), ended_items.csv (終了済み)
  - `shopee/`: (Shopee管理データ)
- `logs/`: 実行ログ、スクレイピング履歴
- `downloads/`: Shopeeから自動ダウンロードされた最新データ
- `Ready_to_Upload/`: Shopeeアップロード用Excelファイルの出力先

---

## 💡 システムの特徴

### eBay 管理
- **Sync/Check/Revival**: API連携による高速な同期と、終了済み商品の復活検知に対応。

### Shopee 管理
- **Auto DL/UL**: セラーセンターへの自動ログイン・データ処理。
- **Scraper Factory**: メルカリ、ヤフオク、ヤフーフリマ、楽天ラクマ、Amazon、ヨドバシ等の高度なスクレイピング。

---
© 2026 Unified Stock Automation Project
