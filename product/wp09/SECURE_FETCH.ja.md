# Secure Fetch — 00.45.00

明示取得計画→既存SyncInboxへ暗号化candidate保存→再open/実データ照合。文書適用ではありません。

## API
`FetchPlan(scope, snapshot, descriptors, binding, inbox_generation, max_records=64, max_bytes=8388608)`。
scopeはSourceのapp/Space/document/epoch/schema/authority head全6要素。bindingはownerが登録したPeerBinding（証明書/pin/接続世代）。descriptorはinner-ID/envelope-ID/暗号化envelope長。最大64件・合計8MiB、重複inner/envelope-ID禁止。Inboxのrecord容量（証明書等を含む）は別途既存receiveが強制します。
`plan.save(path)`は0700親/0600ファイルへcreate-only保存、SHA-256を返す。`FetchPlan.load(path, expected_sha256=...)`は外部保持のhashと上限・正規形式を照合。planは暗号化されず、秘密/本文は含まないが識別情報は機微なので私有領域に置きます。既存pathの上書きなし。保存途中失敗のpartial fileは自動削除しません。
`FetchClient(plan, source, current_generation)`は同じowner/thread/Inbox世代のための明示controller。
- `reconcile()`は通信せず実recordを検証・同一bytesの再同期を行う。過去progressを信用して保存済みにしない。同期fsyncを行うため完全なread-only操作ではないが、record追加・新暗号化・nonce発行はしない。
- `fetch_one(index, ReadSession, cancel=...)`は一つのTLS sessionを消費する。FETCH_BUSYで拒否した場合だけsession所有権はcallerのまま。その他の有効ReadSessionは失敗時もcloseする。
- `execute(async_open_session, indices=None, cancel=None, timeout=30)`は明示planの選択された未保存件を順に一回ずつ実行。最初の失敗で停止し、retryしない。次回の明示executeは再照合後、未保存だけを試す。
- `save_checkpoint(path)`はplan digest＋Inbox pinをcreate-only保存。`restore_checkpoint(path, expected_sha256=...)`はpinで既知欠損を確認し、実recordから再導出。成功フラグは保存しない。
- `progress()`は過去の局所観測コピー。`present_progress(..., locale='ja'/'en')`は本文/IDを含まない表示用データ。実renderer/DOM/SDKへの接続は次工程。

## 状態
`NOT_OBSERVED`はこのInboxで未観測であり、相手が持たない証明ではない。`INBOX_STORED`は同期した候補があるという局所観測。`candidateState`で依存不足/READY_FOR_CORE/隔離を区別。
`COMPLETE_PENDING`は計画した候補の保存確認であり、因果集合全体の取得完了や適用成功ではない。
`OUTCOME_UNKNOWN/RECONCILE_REQUIRED`は保存途中の結果不明。Inboxを再openし、新clientで実recordを検証。保存済みを消さない。
取消し/期限超過/世代変更後はSTOPPEDとし、保存済み候補は維持。保存直後に取消しが届いても「未保存」へ戻さない。
provider再起動等でsnapshotが変われば、元planは失敗する。明示have再照会・descriptor比較・新planが必要。暗黙snapshot更新なし。

## 制約
既存ReadSessionの署名/認可、Inboxのouter/inner-ID/namespace/復号/現在権限を再使用。共有Storeへの書込み、CRDT apply、ACK、replication receiptを発行しない。
非協力的なasync factory/native同期処理はOS sandbox化しない。factoryは返すまで資源を所有し、cancelに協力してcleanupする契約。cancel後に返したReadSessionも回収する。同期保存自体はpreemptしないが、終了後の期限超過を成功にしない。
PlanとInbox受入とcheckpointは一つのatomic transactionではない。途中停止は実Inboxから再照合。最新pinと全体を巻戻す攻撃・checkpoint前の欠損は外部trustが必要。SIGKILL試験は物理電源断試験ではない。
このcandidateはPython3.11+/POSIX/ssl TLS1.3。public IP/DNS、製品PKI、ブラウザー/native、実Automerge、独立レビューは別工程。

## 再現
`python3 tools/check_secure_fetch.py` / `python3 examples/secure_fetch_demo.py`。
公開合成鍵・一時PKI・private socketpair・別process・実SQLiteと実Inboxを使用。fixture暗号化payloadは実Automergeではありません。
参照: Python公式 `https://docs.python.org/3.13/library/asyncio-task.html#task-cancellation`、`https://docs.python.org/3.13/library/os.html#os.fsync`。実行環境はdoctorログに固定。
