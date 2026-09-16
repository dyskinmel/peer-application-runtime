# 受信待機データの同期Inbox — 00.33.00

**実署名・暗号・AuthorityStoreを使った、暗号化入力の永続的な待機と再検査。実CRDTではない。**

一つのapp/Space/document/epoch/schemaに限定する。受信するのは、既知の制御履歴と現在の許可で検証できる署名付き暗号化changeと証明書。未知の制御情報・鍵は別の経路で先に取得する。本APIは権限を発行せず、未知の相手の平文や未知epochを無制限に保存しない。内部の変更データはopaqueのまま保持する。

## API
- `SyncInbox.create(root, owner, app_id=..., space_id=..., document_id=..., epoch=..., schema_id=...)`：私有の新領域を作成。
- `SyncInbox.open(..., expected_pin=...)`：既知のscope・任意の外部Pin・全recordを再検査。
- `receive(envelope, certificate)`：署名・認可・暗号・対象を検査し、同期済みrecordにだけPENDING_BYTESを返す。
- `inspect(envelope_id)`：現在の認可と実データから状態を導出。古いREADYフラグをディスクから信用しない。
- `needed(limit=16)`：不足するinner hashを重複なし・固定順で返す。自動通信はしない。直前envelope IDの不足はinspectの別項目に返す。
- `validate(envelope_id, core, allow_contract_double=False)`：明示的に署名済みの依存集合をコアへ渡す。通常はテスト代替を拒否。実core不在はCORE_BLOCKED。
- `pin()` / `usage()` / `close()`：既知recordの集合照合、使用量の再計算、所有者による終了。

## 状態と保証
`PENDING_BYTES`は、この受信箱のファイルを同期したという局所観測。application StoreのlocalCommitted、文書適用、保管サービスのreceiptではない。

`WAITING_DEPENDENCIES` → `READY_FOR_CORE`は配送順から独立した候補の準備状態。依存元は同じ受信箱、または実AuthorityStoreの署名付きデータ。正確な因果集合・直前envelope・actor/sequenceを照合し、循環・欠落・別scope・曖昧なinner IDを検出する。

`QUARANTINED`では、同じactor/sequenceまたはinner IDに対する異なる有効署名を含む暗号化recordを保持する。実Storeとの衝突も照合する。無効署名だけで文書を凍結しない。coreによる内側の意味検証がないため、これは外側の署名に基づく保守的な隔離であり、Automerge equivocationの認定ではない。

`REBASE_REQUIRED` / `WAITING_AUTHORITY`は現在の共有世代・鍵・認可に合わせて毎回導出する。権限変更を理由に保存済みデータを自動削除しない。

`CORE_BLOCKED`はライブラリ不在・実装変更・実行不能など。`CORE_REJECTED`はcore reportの不整合など。いずれも受信recordを消さず、結果をappliedとしない。テスト代替を明示許可した場合は`CONTRACT_CHECKED / innerValidated=false / applied=false`。実coreの署名付き実装を選んだ経路も、scratch検証でありapplication Storeへの適用ではない。real pathは今回未実行。

## 永続化と再開
recordは`{version, signed encrypted envelope, certificate}`だけ。平文、復号鍵、core previewや「適用済み」フラグは保存しない。ファイル同期→同一FSのrename→record/stagingディレクトリ同期の後だけ受付応答。公開後に失敗した場合はINBOX_OUTCOME_UNKNOWNとして再openを要求し、同じIDの再送で実ファイルと照合する。ack紛失後の再受信でも再暗号化・新規nonce・別変更を作らない。

lifetime flock、PID/thread所有者、再入拒否、700/600の私有領域を使う。知らないファイル、symlink、hardlink、改変を拒否。通常稼働中に既知recordが消えれば拒否。再起動後の既知欠損検出には別途保管したPinを渡す。Pinも含む全体巻き戻しは検出できない。atomic renameは物理電源断保証ではない。

起動時・照会時に過去の検証結果や署名成功だけを根拠にREADYへ昇格しない。コア呼び出し前後に実装identity、owner状態、受信recordの全バイトを照合する。

## 上限・未実装
通常64record・8MiB。認証済みの衝突証拠に限り追加1record・800KiBを予約する。三つ目以降を無制限に受け付けない。容量不足はRESOURCE_BLOCKEDであり、変更の意味的無効ではない。自動evictionなし。未コミットのstaging残骸は64件・8MiB以内で保持し、上限では受付停止する。孤児回収APIは今回含めない。

これは保管中のバイト量の上限であり物理ディスク全体のquotaではない。依存128件＋候補1件、合計4MiBなど既存core契約を維持する。全件照合は上限付きだが、高速・定数メモリーと認定していない。

実インターネット、無権限のraw fetch、適用済みACK、共有Storeへのremote commit、実Automerge、文書のmaterialization、削除・自動再試行は未実装。UIは変更せず共有書き込み無効のまま。

## 実行
```
python3 tools/check_sync_inbox.py
python3 examples/sync_inbox_demo.py
```
公開試験鍵・opaque synthetic inner payloadと実libsodium/SQLiteを使う。core代替試験は実CRDT件数に入れない。既存の旧ライブラリ許可条件は変更していない。
