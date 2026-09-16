# ADR-0018 — 世代閉鎖を先に確定し、terminal操作記録だけを集約

状態: 実装・局所試験済みの候補。baseline00.02.00は不変。

## 判断
TTLやtombstoneの件数を理由に旧操作を削除すると、遅延したbeginが新規要求として復活し得る。現在のauthority issuerが連番・乱数・前回の整理receiptへ結び付けた世代を発行し、subjectは全操作をその世代に署名する。異なる世代へ同じinnerを意図的に包み直すには、新しいsubject署名と現在のcapabilityが必要であり、単なる旧署名のreplayではない。

旧profileを改造しない。schema3の新root、schema2 live、外側のgeneration gatewayというcompositionを採用する。privateサービスへの接続は次工程。

## 閉鎖と整理
全stageがKeeperへの確認済み引渡しか、完了済みretirementであることを確認。未開始bindingも未確定として阻止する。監査の生bytesを先に残し、そのdigestとissuer承認を持つCLOSED境界をfsyncする。その後だけlive記録を限定削除する。署名済みarchiveが欠けたら再起動で拒否。CLOSEDは不可逆なadmission barrierであり、整理途中にauthorityが変わっても対象拡張なしで既承認cleanupを続行できる。新世代開始には現authorityを要求する。

記録枠の返却と物理ディスク空き容量を分離。監査archiveを保持する。begin時に将来のaudit worst-caseを予約し、quota満杯で閉鎖も不能になる状態を回避する。上限後のaudit pruningは別契約。

## 実装中の修正
- 既存codecの1MiB hard limitに16MiB監査全体を入れる案は不適合。signed bounded CBOR headerと長さ既知のbody列というlocal framed containerへ分離。既存wire制約は不変。
- beginのcapacity/lease拒否より先にbindingを作る候補を負例で検出。事前検査へ変更。
- binding同期後に停止してcapabilityが失効すると、再開だけでは行き詰まる。現issuerのretirement許可と元subject署名で、未開始の空originをmaterializeして中止できる経路を追加。
- destination put確認は既存DBの`stored_objects.oid`で照合。旧スキーマを推測しない。

## 安全境界
file fsyncとdirectory fsyncの両方を使用する。SIGKILL試験はプロセス故障であり物理電源断試験ではない。整合した全状態rollbackは外部pinがなければ検出不能。archive内のinodeはその保存領域内の限定cleanup用であり、未検証のクロスホスト復元へ自動的に適用しない。

参照(2026-09-06確認): Python os documentation https://docs.python.org/3/library/os.html 、Linux fsync(2) https://man7.org/linux/man-pages/man2/fsync.2.html 、SQLite atomic commit https://www.sqlite.org/atomiccommit.html 。これらの確認はPAR全体の正しさ・暗号監査を代替しない。
