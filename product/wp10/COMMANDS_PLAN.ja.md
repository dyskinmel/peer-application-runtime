# L-WP10 typed local event commands — 00.40.00 実装計画

Authority: `plan/NEXT_TYPED_EVENT_COMMANDS_0039.ja.md`、`HOST_PORT.ja.md`、利用者の継続実装承認。
Base: `ec3224f95d7d4b91486d83cc898857e1163f2466`。隔離branch: `work/0040-typed-event-commands`。

## 固定する設計
既存購読のoperation集合・保存形式を変えず、同じEventHost/Journalへ独立したcommand mailboxを合成する。
信頼済みembeddingが接続ごとにpublish許可を明示付与する。既定は照会のみ。JSONに権限を自己申告しても昇格しない。
command専用protocol `par-local-event-commands-0040`、exact context、operation ID、typed payload、入力上限を持つ。
TypeScriptはdecimal string/typed fieldを検査し、local-committed / cancelled / outcome-unknown / rejectedを別の結果型にする。
送信後のabort/切断/不正応答は結果不明。照会の失敗はnot-found-localに変換しない。not-found-localは観測時点の不在のみ。
公開listener、remote ingest、自動ACK、自動retry、GC、共有commit、ネイティブ認定を追加しない。

## 作業と受入
- [x] CP1: Python所有者のRED。publish/inquire、権限、型、予算、送信前/nonce後/commit後取消し、通知、再接続を実DBで検査。
- [x] CP2: 同一owner loop上のcommand mailboxと独立IPCを実装。既存85検査で購読境界の回帰を検査。
- [x] CP3: TypeScript/NodeのRED→型付きSDK・専用channel。入力copy、正確なu64/i64、応答照合、取消し、期限、無再送を検査。
- [x] CP4: 別Python所有者process + Node + 専用fdの実SQLite統合。nonce後/COMMIT後kill、再起動照会、同ID差替え拒否、publish→wake→明示ACK。
- [ ] CP5: 追加case identityを登録し、fresh H0と全28laneを再実行。独立レビューではなく同一実装者の局所検証。
- [ ] CP6: ソース/完全Git履歴/全保持歴史/新証拠/再開案内を単一ZIP化し、SHA、manifest、復元試験を記録。

## 検証の区別
同期SQLite/暗号処理に対するリモートcancelの強制割込みは保証しない。nonce後取消しは既存の所有者cancel probeで検証し、別processではnonce後停止と再起動も検査する。
テスト/検証器/登録はguarded入力。変更後の旧receiptは無効化し、新candidateでH0から再検証する。
実装checkpointはGit commitと保存ログで残す。検証receiptと同一視しない。元仕様85ファイル、67tasks/149requirements/16WPの重みは不変。

## CP4までの実測
Python command owner 30、private socket 9、Node command SDK 29、Node channel 10、real Node/Python owner integration 12、TypeScript negative/positive contract 1。計91。旧owner host 85も回帰PASS。CP5/CP6の最終結果は、sourceを変更しない配布領域 `release/STATUS.json` と `release/evidence/0040/` に記録。

## 追加登録の扱い
CP1–4はL-WP10 allowed_paths内の実装と試験。CP5でpolicy/check inventories・task context・agent entryを追加登録し、旧検査・閾値・要件owner・baseline・gateは変更しない。guarded入力が変わるため、旧H0や旧receiptを流用せず候補freeze後に全レーンをfresh実行する。CP5/6の未チェックは実装計画freeze時の状態で、完了は上記配布証拠が正本。
