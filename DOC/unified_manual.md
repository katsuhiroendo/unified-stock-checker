# Unified Stock Checker システム 統合マニュアル (v3.0)

本システムは、eBay と Shopee の在庫・出品状況を一つのインターフェースで管理できるツールです。
各プラットフォームの主要ロジックを抽出・整理し、GUI および CLI 両方から操作が可能です。

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

### 1. CLI メニュー
ターミナルから `main.py` を実行します。

```bash
python main.py
```
メニューが表示され、eBay/Shopee の CLI モード、または GUI の起動を選択できます。

### 2. GUI ダッシュボード (Streamlit)
直接起動する場合は以下のコマンドを実行します。

```bash
streamlit run gui.py
```
ブラウザが起動し、サイドバーから eBay と Shopee を切り替えて操作が可能です。

---

## 📂 フォルダ構成

- `main.py`: メインメニュー（CLI/GUI起動）
- `gui.py`: 統合ダッシュボード (Streamlit)
- `modules/`: プラットフォーム別のコアロジック
- `data/`: 出品データやログ（プラットフォーム別にサブフォルダ管理）
  - `ebay/`: items.csv, ended_items.csv, relisted_log.txt
  - `shopee/`: (Shopeeのデータ管理用)
- `logs/`: 実行ログ、スクレイピング履歴
- `Ready_to_Upload/`: Shopeeアップロード用Excelファイルの出力先

---

## 💡 各ツールの特徴

### eBay Stock Checker
- **Phase 1 (Sync)**: eBay API から最新出品を取得。
- **Phase 2 (Active Check)**: 出品中アイテムの在庫確認。
- **Phase 3 (Revival Check)**: 終了済みアイテムの在庫復活確認。

### Shopee Stock Checker
- **Auto DL/UL**: Shopee セラーセンターからデータを自動ダウンロード・アップロード。
- **Scraper Factory**: メルカリ、ヤフオク、ヤフーフリマ、楽天ラクマ、Amazon、ヨドバシ等の高度なスクレイピングに対応。
- **Manual Override**: GUI 上で在庫状態の手動上書きが可能。

---
© 2026 Unified Stock Automation Project
