# KEEPER-RETENTION-LOCAL — 00.12.00

実行可能なPython/POSIX/SQLite候補。ネットワークサービス、製品G3、独立レビューではない。Keeperはcontent keyやrecipient復号鍵を受け取らない。

## 今回の契約
`Keeper`は新しいprivate rootとkeeper.sqliteを使用する。既存Storeのスキーマは変更しない。容量提供は`quota_bytes`による明示設定で、無断で他人の保存を始めない。

- `Authority`: trusted hostが署名付き制御履歴を検証した後に渡す既知のapp/Space/head/sequence/epoch/issuer。payloadが名乗るownerを信用しない。`update_authority`はtrusted local host専用で、受信者endpointではない。
- `issue_capability`: authority署名の非委譲トークン。Keeper public key、subject署名鍵、exact recovery index ID、許可するmethod、最大lease秒数を固定。
- `make_call`: subjectの所持証明。capability ID、method、lease、operation nonce、payload digestを署名。
- `reserve`: exact index/Pin/期間に対する容量予約。operation nonceはsubject内で一意。同一要求は同じleaseへ戻り、差替えは拒否。
- `put`: listed objectのkind/ID/sizeを検証し、ファイルfsync→directory fsync→DB記録後に応答。途中の孤立ファイルは次の同一PUTで照合して再利用する。
- `seal`: exact inventory全件の実データを再検査し、署名receiptとgeneration、冪等応答を同じSQLite transactionに保存。COMMIT後だけ返す。
- `receipt`: 過去に発行した署名確認を取得。ただし今回の読み直しで欠落/改変が見つかれば返さない。古い確認自体は現在のnetwork reachabilityを保証しない。
- `fetch`: 毎回capability+proof+current known authority+exact inventoryを確認。hashを知るだけでは取得できない。
- `renew`: 全バイト再確認後に新generation。重複要求で期限を繰り返し延長しない。同bootで以前の約束を短縮する更新は拒否。
- `release`: reservation所有subjectの明示権限が必要。GET/renewを停止し、バイトとquotaは保留。自動削除・capacity refundは行わない。
- `challenge`: nonceに結合した署名付きの現在の局所観測。単なるKeeper署名であり、不正なKeeperが嘘をつかないこと、遠隔の現在可用性、recipientの復旧は証明しない。
- `AuthorizedProvider`: 既存recovery Inboxへつなぐ同期callable。socketは開かない。

## 状態
`AWAITING_OBJECTS` → `BYTES_COMPLETE_UNSEALED` → `RETAINED_ACTIVE`。
期限経過は`EXPIRED_RETAINED`、boot違い/時計逆行は`UNKNOWN_RETAINED`、明示releaseは`RELEASED_RETAINED`。欠落/改変は`DEGRADED`。いずれも自動的に消去しない。

`recipient_validated=false`、`product_qualified=false`を保持。長期保管の善意、Sybil耐性、グローバル最新head、CRDT意味検証を主張しない。

## 実行
```sh
python3 tools/check_keeper.py
python3 examples/keeper_demo.py
python3 examples/keeper_workflow.py --only KEEPER-RETENTION-LOCAL
```
最後のworkflowには既存依存レーンのfresh検証が必要。全順序はSTART_HEREを参照。

## 依存と再起動
既存の`policy/crypto-provider.json`でlibsodium実体を固定。Python3.11+ / SQLite3.37+ / POSIXが候補条件であり、実測はrelease evidenceを参照。現ホストの旧SQLite/libsodiumは通常拒否。test/demoは公開合成データだけに明示opt-inする。別ホストはprovider pinをレビューしてから新規証拠を作る。修正バイナリは同梱しない。

同rootの協調writerはlifetime flockで一つに制限。threadをまたぐ呼び出しとobserverからの再入は禁止。readerにはメソッドの間だけロック下でコピーしたbounded bytesを返し、長寿命stream/reader pinはまだ持たない。

LinuxではCLOCK_BOOTTIMEとkernel boot IDを結合。利用できなければprocess sessionとmonotonicを使い、再起動でunknownとなる。UTC時計は認可や破壊的削除に使わない。信頼できる時計や物理電源断の実証ではない。

## 限界
最大closure32MiB/1024objects、index512KiB、1object900000bytes。payload quota最大512MiB、lease既定32（上限256）、冪等mutation記録既定4096（上限65536）、期間最大86400秒。index+listed object bytesを各leaseへ全額予約しcross-lease dedupしない。SQLite metadata/WAL/一時ファイルなどを含む厳密なディスク全体quotaではなく、件数上限とOS領域制限を別に設ける。期限切れやreleaseでもquotaを返さないため、GC未実装段階では容量を使い切ると受付を拒否する。

lease時計の高水位はcommit時に保存するが、すべての未確認観測を耐rollbackに記録する機構ではない。authority保存の結果が不明ならinstanceを停止し、hostが既知headとDBの耐久状態を照合するまで再開しない。プロセス停止後に未保存の権限変更を自動で記憶するとは保証しない。

同一OSユーザーの悪意あるDB/ファイル置換、完全なDB巻戻し、native memory内の秘密鍵保護は別の境界。例外時のprivate ciphertext一時ファイルを自動回収しない。全件再検査のCPU/メモリーはboundedだが大規模負荷試験は未実施。

Capabilityはwall-clock expiryを持たず既知authority版で失効する。leaseの期間とは別。read署名のexact replayは同scopeの読み取りのみで、ネットワーク全体のanti-replayやsession freshnessではない。更新したauthorityから、明示的に旧closureの読み取りを再委譲することはできる。

## 検証の質
138試験、うち40実子プロセスSIGKILL境界。受信者復旧はdonor DB/元ファイルを除去し、別プロセスで検証する。固定receiptはSELF_GENERATED PUBLIC CANDIDATEであり、独立KATではない。通常試験は固定ファイルを更新しない。保管者が署名しても嘘をつけないことや、生産環境の保証を与えるものではない。
