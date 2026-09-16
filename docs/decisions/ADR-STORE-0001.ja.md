# ADR-STORE-0001 — 保存境界・nonceの先行予約・復元の読み取り専用化

状態: 00.05.00のローカル実験用候補。00.02.00を変更せず、G0/OD-04を閉じない。

## 1. 暗号化前の発行記録
元のNEXT_G0_STOREの「nonce記録もcommitと同じtransaction」は、暗号化後にtransactionがrollbackすると発行を忘れる問題がある。
本候補ではoperation/input intentと(key context,nonce)の予約を先行transactionで永続化する。予約IDを受領した新規呼出しのみが一度だけsealを行える。
同じnonce予約を再要求して再暗号化してはならない。処理中断後は保存済みoperationを照会し、未commitなら同じoperation/inputに新しいnonceを予約する。
commitは予約をenvelopeへ結び付ける。commit失敗でも予約はburnedとして残る。nonce表・intentはこの実験ではGCしない。
Storeはopaque bytesを受けるため、実際に暗号化したか、暗号化が予約後に一度だけ行われたかは検証できない。統合先の責任として残す。

## 2. 可視なcommit
暗号化済みenvelope、ledger、actor sequence、catalog cache、outbox、block参照、nonce消費状態を一つのBEGIN IMMEDIATE/COMMITに入れる。
nonceの先行予約と公開前のorphan blockだけは、そのtransactionの外で存在してよい。
同operation/input/完全なprepared fingerprintの再送は、元のreceiptと元のbytesを返す。入力・ciphertextの差替えは拒否。結果不明はID照会で解決する。

## 3. Hostと故障条件
POSIXの協調writer lockをStore lifetimeで保持し、staging→file fsync→rename→directory fsync→DB参照commitとする。
他の同一ユーザーによるraw SQLite書換えやsymlink競合への完全な封じ込めではない。trusted private directoryを前提に、既知のsymlinkや不正pathは拒否する。
SQLite 3.46.1は公式WAL-reset修正を確認できない。明示的なallow_unpatched_sqliteを要し、診断に残す。ここでの合格は実験データ・process crashのみ。
参照 https://sqlite.org/wal.html#walreset / https://sqlite.org/lang_transaction.html / https://docs.python.org/3.13/library/sqlite3.html 。

## 4. Backupと復元
稼働DBはSQLite backup APIで別destinationへsnapshotする。参照blockは同じwriter lock下で検証/copyし、manifestを最後に書く。
復元は既存destinationへ上書きしない。元DB・元snapshotを変更しない。復元DBにはread-only markerを付け、過去の鍵・nonce・actorを用いた書込みを自動再開しない。
manifest hashは誤破損検出であり署名ではない。改竄者が全manifestを書換えるケースやKeeperからの暗号的検証付き復旧は未実装。
