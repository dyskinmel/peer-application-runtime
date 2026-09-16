# ADR-STORE-0002 — 障害実験からの品質修正

状態: 00.05.00自己点検済み候補。独立レビューNOT_RUN。

## 検出した問題と修正
1. actor/cacheは「残っている行」を検査するだけでは行の欠落・古い値を見逃す。commit ledgerと明示commit_orderから期待集合を再導出し、実集合を照合する。
2. metadataのschema_version/profileだけは変更可能。sqlite_schemaの実table/index/trigger/view定義を、baseline+overlayから構築した期待集合と照合する。未知schemaの復元ではUPDATEの前に停止する。
3. 既存のcontent-addressed blockは、前writerがrename後/dirsync前に停止したorphanかもしれない。hashが一致してもfile/dir syncを再実行してから参照commitする。
4. observer経由のpending/operation lookupはtransaction途中の値を漏らし得る。再入を拒否し、committed内部照会だけをprivate経路へ分ける。
5. snapshot/restoreのrename後の失敗は「確実に失敗」と言えない。SNAPSHOT_OUTCOME_UNKNOWNとして、destinationの整合確認を案内する。存在するdestinationに盲目的上書きをしない。
6. H0はSQLite version文字列に加えてsource ID、compile options、Python SQLite extension hash、Linuxで観測可能なloaded libsqlite3 hashをbindする。SQLiteを使わないtaskにそのprobeを強制しない。

## 原因と証跡
追加テストがREDになったことをrelease/evidence/00.05.00/red-review.log、red-sqlite-probe.log等へ保存。修正後に元試験と合わせて実行。
APIは機密bytesやSQL parametersをerror messageに含めない。独立した署名検証や媒体保証を足したとは解釈しない。

## Backup failure cleanup
実際のbackup target connectionを使い、backup後のjournal設定に失敗を注入するとcloseされないことを
負例で再現した。Connection context managerを明示try/finally closeへ置き換え、成功/失敗の両方でcloseする。
同じsourceは引き続きaudit可能で、未完成snapshotは公開しない。
