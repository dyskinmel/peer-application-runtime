# ADR-AUTH-STORE-0001 — 同一DBでの認可状態と暗号化commit

状態: 00.08.00の局所実験として採用。製品仕様の凍結・独立レビューではない。

## 判断
認可履歴をデータStoreとは別DBに保存せず、同じSQLiteの `auth_spaces` / `auth_epoch_keys` / `auth_materials` / `auth_commits` に保存する。`spaces` のhead/sequence/epoch/stateも同じtransactionで更新する。通常のwriteは認可を検証してnonceを先に永続発行し、暗号化した後、`BEGIN IMMEDIATE`内でhead/sequence/epoch/revision/material/fenceを比較してから確定する。署名・AEADの重い処理はtransaction外だが、同じインスタンスが作った候補の改変を検出し、commit直前にも比較を繰り返す。

`auth_commits` は変更データ・操作台帳・actor/cache/outboxと同じtransactionで保存し、履歴head、証明書、鍵fingerprint、材料ID、prepared digestを結び付ける。raw Store commitは認可ticketなしでは拒否する。これは協調するlocal writer用のAPI境界であり、同一processで任意コードを実行する攻撃や直接SQLiteを書き換える攻撃を封じるOS境界ではない。

## 版と移行
新adapterの `PRAGMA user_version=2`。既存Storeは1のまま。元DDLの `store_metadata.schema_version=1` CHECKは変更せず、複合schemaのdigestとuser_versionで識別する。旧adapterは2を拒否、新adapterは1を拒否。明示的な `migrate_empty` のみ、データがないことを検査して原子的にDDLと識別値を更新する。データがある旧DBは `LEGACY_DATA_REQUIRES_IMPORT`。署名のない過去データを黙って認可済みへ昇格させない。

## 再試行
既に確定したローカル操作IDの結果照会は、その後の取消しと区別する。署名/暗号/操作入力と認可proofを確認して同じreceiptを返し、nonceを増やさない。未確定の候補は取消し・同世代control更新・再activation・fence変更・process再開で無効になる。成功後の応答欠落は `LOCAL_OUTCOME_UNKNOWN` とし、操作IDで照会する。新規writeを勝手に再実行しない。

## 根拠と留保
SQLiteのtransaction/isolation公式文書を参照（experiments/auth-store/SOURCES.md）。独立した接続のwriter競合、同一接続での途中状態変更、SIGKILL、SQLITE_FULLを試験する。SQLiteの原子性で世界全体の最新認可を証明しない。未観測の失効・物理電源断・OS vault・Rust/Automerge・実ネットワークは対象外。
