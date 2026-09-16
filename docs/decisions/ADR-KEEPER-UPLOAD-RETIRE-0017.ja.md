# ADR-KEEPER-UPLOAD-RETIRE-0017 — 未完uploadの回収

状態: 実装・ローカル試験済みの候補。製品wire仕様として未凍結。

## 判断
旧Spoolを直接書き換えず、schema2 RetiringSpoolとして実装する。元metadataは残し、current-authority grantと元subjectの要求を結合したKeeper署名journalを別に持つ。record quotaを再利用すると過去のbeginを新規扱いする危険があるため、本版ではpayload quotaのみ回収する。

## 順序
署名intentを先に同期→対象限定unlink→directory fsync→PAYLOAD_REMOVED同期→TOMBSTONED同期→予約量の再計算。別のcapacity counterを先に増やさず、元stageとterminal journalから導出する。pendingは保守的に予約継続。原子的な削除/SQLite transactionという説明はしない。

## 権限
元beginのsubject以外の代行削除を提供しない。authorityのApp/Spaceを保持し、同じ連番なら同じ内容、新連番ならepoch非減少。current authorityはtrusted hostの検証済みsnapshotであり、自動発見しない。pendingのrebindは同一対象・所有者のまま、厳密に増加したauthorityだけ。初回を含め8件で停止する。

## コストと残存リスク
metadata保持は増える。最大1024 stage、tombstone世代整理は別候補。故障でpendingが残っても自動削除せず、同一署名要求を再実行する。腐敗したprefix/別inodeは手動調査対象。KeeperDBや宛先payloadを変更しないため、宛先に既に存在する予約の解放には別操作が必要。

既存read/uploadの方法集合を変えない。本版のAPIは同じ所有者threadから呼ぶ。旧hostはschema2を拒否し、host移行は明示的に行う。未知の署名・削除対象を推測して続行しない。

## 検証
105試験、20実SIGKILL。監査が新しい署名を作る不要な処理を追加負例で発見し修正。独立レビューではない。物理電源断、whole-store rollback、同UID敵対者への隔離は保証しない。
