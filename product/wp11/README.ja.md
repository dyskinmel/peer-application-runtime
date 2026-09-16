# 共有ノート — 00.30.00 ローカル候補

実装済み: 既存Presenter、DOM renderer、入力・確認ダイアログ、明示的に保存・復元する暗号化私有下書き、Nodeの原子的なファイル保存アダプター、IndexedDB候補。
実証済みの範囲: Node上の暗号化・CAS・別プロセス読み込み・強制終了復旧と、オフラインChromium上の画面・操作。HTTPでのアプリ配信、実originのIndexedDB、実OS IME、スクリーンリーダーは未検証。

## 読み始め
- [ルートの実行手順](../../START_HERE.ja.md)
- [下書きの契約と制約](PERSISTENCE.ja.md)
- [前版Presenterの詳しい契約](../../docs/history/WP11_README_0028.ja.md)

`src/`がTypeScript正本。`lib/`は同梱生成JSと型宣言。追加npm依存不要。
`app/`に描画用HTML/CSS/ES module。`adapters/file-draft-store.mjs`はNode/POSIX port。

## 変わらない境界
ローカルの編集バッファ、暗号化私有コピー、共有コミット、他端末の保管、復旧、CRDT適用を分離する。下書き保存に成功しても共有保存・複製完了を表示しない。
`prepareCommand()`は未実行の要求を返す。実runtimeが現在の認可・対象・版・操作IDを再検証する必要がある。共有effectはこのデモへ接続していない。

## 確認
```sh
python3 tools/check_reference_presenter.py
python3 tools/check_private_draft.py
node examples/private_draft_demo.mjs
python3 tools/check_reference_browser.py --output /tmp/par-browser
```
Browser試験はPlaywright/Chromiumの明示的な別環境。H0の依存隔離を緩めない。オフラインNode-host bridgeは試験専用であり、ブラウザーのIndexedDB実証ではない。

## 実装の区切り
鍵はデータと別に利用者/hostが提供する。DBに保存しない。鍵紛失時の復旧、OS keychain、共有同期、Automerge、書き込み可能な復旧、全store巻戻し防止、独立した暗号レビューは未完了。
