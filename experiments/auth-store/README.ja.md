# 認可と暗号化Storeの原子的接続 — 00.08.00

**局所実験の実装。製品のG0合格、CRDT適用、独立暗号監査ではありません。**

## 読み始め
`par_auth_store/store.py` が状態の永続化と比較、`writer.py` が暗号処理、`backend.py` が既存Storeのhook、`audit.py` が履歴・proofの再検証、`schema.sql` が新しい4テーブルです。元の85ファイルの仕様は変更していません。設計理由はdocs/decisionsのADR-AUTH-STORE-0001〜0003を参照してください。

## 実行
リポジトリrootで `python3 tools/check_auth_store.py`。限定実行は `--suite commit|persistence|schema|faults`。全レーンをharnessで実行して再開記録を作るには `python3 examples/auth_store_workflow.py`。デモは `python3 examples/auth_store_demo.py`。

Python 3.11以上/POSIX/SQLite/libsodiumが必要です。検証したのはLinux、Python3.13.5、SQLite3.46.1、libsodium1.0.18です。旧providerは通常APIでは拒否し、合成・公開fixtureの使い捨て実験のみ明示opt-inします。`policy/crypto-provider.json`のパス/hashは別hostで再実測してください。名前やversionだけが一致する別binaryを既検証としません。追加pip/npm package不要。全レーンのwire/crypto比較にはNodeも必要です。

## 基本API
`AuthorityStore.create(...,provider=...)` → `enroll(app,space,genesis)` → `observe(space,control)` → `provide_membership(space,pages)` → `activate(...)`。

`AuthenticatedWriter(store,certificate,epoch_secret,signing_seed,local_secret)` の `prepare(operation_id,header,inner_bytes,cache_bytes)` はnonceを先に発行し、暗号化したBoundWriteを返します。まだcommitではありません。`store.commit(candidate)`で同じtransaction内のhead/epoch/revision/fenceを照合し、認可proofとデータを保存します。`writer.write(...)`はこの二段階をまとめたAPIです。`read_committed`で成功後の応答欠落を照会できます。

## 境界ごとの動作
| 状況 | 結果 |
|---|---|
| reader/Keeperのwrite | 暗号化・nonce発行より前に拒否 |
| prepare後の取消し・head更新・epoch変更 | STALE_DECISION、データ未commit、nonceは消費済み |
| 署名されたfork | forkをDBへ保存し停止 |
| 正当な認可更新の保存失敗 | AUTH_PERSISTENCE_UNCERTAIN。必要更新の再保存まで停止 |
| COMMIT後の応答欠落 | 結果不明。操作IDまたは正当なcontrol再送で照合 |
| 再起動 | 署名から履歴を再検証。鍵/seed再検証前はwrite不可 |
| backup restore | stagingで認可を検証、公開後もread-only |
| 古いschemaのデータありDB | 自動migrationせずLEGACY_DATA_REQUIRES_IMPORT |
| 未観測の新しいcontrol | 最新とは証明できない。known-history保証のみ |

## 成功と未確認を分離
132件の試験契約: commit37、persistence29、schema12、faults54。faultsの49件は独立child processへの実SIGKILL。その他にSQLite lock、SQLITE_FULL、トランザクション途中の認可変更を検証します。実行件数と結果は同梱evidenceで確認し、新hostでは再実行してください。

`auth_commits`を保存したことはAutomergeのinner change適用ではなく、envelope stateはpendingです。添付Blobのtyped IDとStore locatorの接続、Keeper複製、ネットワークpeer認証、Rust adapter、OS鍵保管は未実装。

API非公開部分を直接操作する同一processの敵、SQLite全体の意図的な書換え、hardware rollback、停電・媒体故障への保証はありません。外部known-head pinがない古いDBの復元を「最新」と認定しません。秘密鍵や平文payloadをDBへ保存しませんが、Space/権限メタデータは匿名化されません。

## 同梱profileと再現性
`profile.json`は依存仕様・schema・ADR・主要hookのhashを固定します。policyの4 inventoryは各test IDの完全な集合です。テストや契約を変えたら旧sessionは無効、新candidateとして再実行します。過去実行ログは現在のPASSを意味しません。
