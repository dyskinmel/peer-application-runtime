# ADR — Explicit local Keeper reclamation

状態: 実装・ローカル検証済み候補。元仕様の凍結／製品qualificationではない。

## 選択
schema2 subclassと小さなschema/容量hookを選ぶ。旧Keeperをコピーして別の署名検証・保存意味へ分岐させない。schema1正常動作は既存138testsで回帰確認。新しいGC署名domainによって従来releaseと区別する。

協調single writer・同期バイト列readという現実のAPIに合わせて、reader pinはinstance scoped contextに限定する。別processのraw fdを使ったstreamingは提供しない。期限・boot不明を削除理由にしない。

ファイル削除とSQLite creditを一つのatomic transactionだと称さず、署名intent→idempotent unlink/fsync→atomic accounting/resultに分ける。署名requestだけでは物理配置が完全一致する保証にならないため、mark/再開時の列挙・内容照合を追加する。

## 見つけた不備と修正
- tests helperが親のrequestをoverrideしてsetUpを壊した。名前をgc_requestに分離し、setup ERRORをRED成果に数えず、feature未実装による34 FAILを確認。
- 最初のGCではdone後にnamespaceが再出現しても同一process retry/新規予約/診断が通った。3 REDで再現し、署名jobと物理namespaceの再検査をその経路にも追加した。元レシートの改変やcredit差替も拒否。
- SQLite FULL試験は通常pageに空きが残りFAIL injectionが成立しなかった。small-pageの実DBを初期化し、実際にoverflow pageが必要になる条件でmax_page_countを制限した。エラーをmockした証拠へ置換しない。
- marked credit改変はgc auditより先のSQLite quick_checkで拒否される。期待するコードをCORRUPT_STOREとし、拒否条件は弱めなかった。

## 残余リスク
正当に署名されたGC要求の後でローカルauthority更新が発生すると旧jobは止まる。再承認APIは別設計。metadataのindex/署名/operation/tombstoneは残り、reserved metadata分は返さない。データ機密消去・filesystem free量・全DBrollback防止・敵対的sameUID raceは保証しない。
- make_requestのmalformed capabilityがKeyErrorを漏らしていた。専用負例で再現し、署名前にcapability_shapeを検査してCONTRACT_SCHEMAへ統一した。

## 今回の観測
基本34件→fault/audit追加→不具合負例を含む88件。内訳 contract15/lifecycle20/audit21/faults32、owned SIGKILL22（mark5/sweep7/finish5/migration5）。本数はローカル試験契約であり、製品Gateの合格数ではない。
