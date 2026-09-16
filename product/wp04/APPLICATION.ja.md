# 文書適用候補 — 00.35.00

L-WP04/V-WP04の局所実装。実Automerge3.4.1は未取得・未実行。通常経路は実coreを要求し、明示的な試験用代替では`CANDIDATE_ONLY`, `innerValidated=false`, `applied=false`を維持する。実core用コードも候補で、版/API不一致の修正が必要となり得る。画面の共有書き込みは有効化しない。

## 何を同時に保存するか
`ApplicationStore`は既存BlobStoreのDBへschema4を明示的に追加する。`document_inputs`（署名付き暗号化入力と証明書）、`document_apply_events`（AEADで結合した入力集合/認可/結果/暗号化本文）、`document_frontiers`（文書の到達点）、`document_apply_nonces`の使用リンクを同じSQLiteトランザクションで確定する。既存の`envelopes.state=pending`は**受理記録**として変更しない。受理と文書適用を別表にするADRは`docs/decisions/ADR-0035-document-application.ja.md`参照。

`DocumentApplier.prepare()`は既存入力と新規対象の正確な因果集合を収集し、actor/連番/依存/暗号を検査する。前回までの入力は保持し、同じ文書・同じepochでのみ単調に増える。現行入力は現在の作成者権限も確認する。履歴の矛盾を多数決や時刻で解決しない。

coreレポートには入力ハッシュ・engine識別子・正確な適用集合・heads・未解決依存ゼロ・限定noteスキーマを要求する。内側本文は暗号化する。nonce発行は暗号化前に別トランザクションで永続化し、適用失敗後に再利用しない。元の共有鍵とは別の、呼び出し元が保持する32バイト私有鍵から導出する。鍵は保存しない。

`commit()`は同じDBのwriter fence、認可状態、epoch、文書版、外部入力の全バイト、core識別を再確認する。入力/イベント/到達点/nonceリンクを保存し、COMMIT直前に再確認する。準備チケットは同じ所有プロセス/スレッド/インスタンス内でのみ有効。外部から受け取った辞書や「検証済み」フラグを適用許可にしない。

## 失敗・再試行
- 同じ操作ID・同じ対象・同じ期待版は過去結果へ収束する。再暗号化/core再実行/nonce増加なし。違う入力は拒否。
- COMMIT前の失敗ではロールバック。COMMIT試行後の不明は`APPLICATION_OUTCOME_UNKNOWN`となり、このapplierを再利用しない。Store/台帳を再読み込みし、操作IDで明示照会する。自動実行しない。
- `read()`は現在のローカル読取権限を要求する。全履歴のAEADを検証し、読み取り前後のDB変更情報・認可・到達点を照合する。revocation観測中に古い本文を返さない。
- 再起動では認可を再活性化するまで本文を返さない。外部で保持したPinで既知履歴の欠落を検出できるが、PinとDBをまとめたrollback防止ではない。
- snapshotは復元前の構造・認可検証と復元後のread-onlyを維持。`audit()`単体は本文AEAD/core再適用を証明しない。本文検証には正しい私有鍵が必要。

## バージョンと資源
schema3からの`ApplicationStore.migrate_v3()`は明示的操作。元の署名付きpendingデータを変更しない。旧BlobStoreはschema4を拒否する。新規schema4 Storeと既存実験は別領域で使用する。

上限: 因果集合128変更/4 MiB、外部プール256記録/8 MiB、暗号化前note JSON262144バイト、アプリ適用64イベント（DB全体）、nonce予約512（DB全体）、論理保存予算16 MiB。前版の実験上限を製品上限へ転記しない。履歴のGC、未使用nonce予約の回収、cross-epoch再適用、文書圧縮は未実装。複数準備チケットは同じ期待版で作れるが、確定できるのは一つだけ。

## 検証方法
```
python3 tools/check_document_apply.py
python3 examples/document_apply_demo.py
python3 tools/check_document_apply_real.py
```
最初の二つは公開合成変更＋明示的テスト用coreで、実署名/暗号/SQLite/プロセス停止を検証する。実core不在の最後のコマンドはBLOCKED/exit78/実行0。実配布物を確認できた環境では`--manifest /absolute/pinned.json --allow-legacy-test-libraries`で実coreの同一DB適用/再起動probeを実行する。旧ライブラリ許可は使い捨て公開fixture専用で、本番許可ではない。

## 限界
これは本番Rust実装、CRDT実証、UI共有保存、インターネット通信、独立レビューではない。Node子プロセスのtimeout/heapはOS sandboxやWASM fuel制限ではない。stdout上限は回収後の検査で、敵対的な無制限出力を隔離する仕組みではない。実core/ローカル所有者は信頼済みコードが前提。SIGKILL試験は電源断・媒体故障試験ではない。外部入力の全件走査と過去本文の復号を行うため、大規模性能は認定していない。
