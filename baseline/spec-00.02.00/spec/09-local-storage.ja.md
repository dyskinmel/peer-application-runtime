# 09 — ローカル保存・原子性・破損・容量

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 保存の正本

ネイティブはSQLiteをcatalog/commit/outboxの原子性に使用し、本文・change・materialized cacheはlocal keyまたはSpace keyで暗号化する。SQLite自体に暗号化があると誤解させない。平文検索索引、SQL引数ログ、tempファイルに本文を漏らさない。

候補設定は `journal_mode=WAL`、`synchronous=FULL`、`foreign_keys=ON`。接続ごとにreadbackし、要求値が反映されなければ耐久性profileをqualifiedとしない。SQLiteのWAL/FULLはcommitごとの同期を伴うが、実媒体がflushを正しく実装する等の前提を持つ。[S11][S12]

## 2. commit境界

local commandは事前生成した`operation_id`と入力digestを持つ。署名・暗号化・一時的materializationに失敗したら保存前の状態を保持する。

```text
validate command against local causal view
prepare signed immutable envelope bytes
BEGIN IMMEDIATE
  assert current epoch + writer fencing token
  insert encrypted envelope and causal indexes
  insert commit ledger(operation_id, digest, commit_id)
  update actor sequence + materialized-cache reference
  insert outbox entry
COMMIT (FULL)
return CommitReceipt
publish local snapshot
```

callbackは同期的変更記述でありnetwork/random side effectを行わない。local persistedになる前に画面へ楽観表示する場合は`pending-local`を明示する。network送信はcommit完了後。

## 3. outcome unknown

ストレージ層がcommit成否を確定できない場合、`LOCAL_OUTCOME_UNKNOWN`とoperation IDを返す。成功と決め付けず、同じoperation IDのledger照会またはrestart recoveryで判定する。再試行で別IDを作り、同じ変更を二重適用してはならない。

failure envelopeを分ける。process crash、OS crash/power loss、media corruption、媒体喪失、悪意のstorageは異なる試験。SIGKILLを通しただけで電源断耐性を実証したとは呼ばない。

## 4. 外部blockとの整合性

大きいblobはstaging→hash/AEAD確定→ファイルflush→atomic rename→必要なdirectory同期→SQLite参照commitの順。DBが参照する前にblockを永続化する。crashで参照されない完成blockが残ることは許容し、orphan GCで回収する。DB参照だけ存在しblockが未完という成功状態は許さない。

OSによってdirectory flush等の手段が違う。AtomicBlockPublish portで実装し、成功時にstorage classを返す。未検証OSでは候補profileとして表示する。

## 5. schema候補

`protocol/storage-v1.sql`に最小DDLを含む。PKは原則32-byte ID、u64の順序値は8-byte big-endian BLOB。SQLite signed integerの範囲をwire u64と混同しない。全sequence比較は同長BLOBかhostのchecked u64で行う。

commit ledgerとoutboxにはunique operation ID、envelope IDを持たせる。catalog、pinned roots、lease reservations、recovery sessions、migration journalを別tableへ置く。plaintextを汎用JSON columnへ保存しない。

## 6. restartと破損

起動はDB整合性確認、schema version確認、active transaction recovery、blob reference audit、outbox再構成の順。フルblob検査はbackgroundでよいが、使用するblockは取得時に必ずhash/AEADを検証する。

破損を検出したら元ファイルを上書きせずread-only退避。健全block、署名履歴、Keeperから新DBへ再構築し、sourceとの対応manifestを残す。最後にユーザーへ差分と失った範囲を提示する。

## 7. disk fullとbackup

quota不足はwrite admissionで先に推定し、SQLite/OS ENOSPCも扱う。少量のemergency reserveは診断・commit結果保存用に使用し、任意の可用性保証とはしない。未送信localデータ、pin、active leaseを黙って削除しない。

稼働中SQLiteを単純にDBファイルだけcopyする方法はbackup手順にしない。整合snapshot/backup APIとblock rootsを固定し、export側で取得集合をpinする。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-STORE-001"></a>
### PAR-STORE-001 — 原子的保存
**MUST:** commit ledger・actor state・暗号化change・outboxを一つの原子的transactionで保存する。
受け入れ: `AT-STORE-001` / 最初の必須gate: `G1`。

<a id="PAR-STORE-002"></a>
### PAR-STORE-002 — 耐久性設定
**MUST:** 実際のjournal/synchronous/host storage classを確認してからreceiptを発行する。
受け入れ: `AT-STORE-002` / 最初の必須gate: `G1`。

<a id="PAR-STORE-003"></a>
### PAR-STORE-003 — 結果不明
**MUST:** commit成否不明はoperation IDで照会・再開し、新IDによる盲目的再実行をしない。
受け入れ: `AT-STORE-003` / 最初の必須gate: `G1`。

<a id="PAR-STORE-004"></a>
### PAR-STORE-004 — blob公開順
**MUST:** blockの永続化をDB参照公開より先に完了させ、stagingを完成扱いしない。
受け入れ: `AT-STORE-004` / 最初の必須gate: `G3`。

<a id="PAR-STORE-005"></a>
### PAR-STORE-005 — 平文漏洩防止
**MUST:** 本文・索引・cache・temp・SQLログの永続保存は暗号化または非保存にする。
受け入れ: `AT-STORE-005` / 最初の必須gate: `G1`。

<a id="PAR-STORE-006"></a>
### PAR-STORE-006 — 破損復旧
**MUST:** corruption時は元データを保全し、別保存先へ検証付き再構築する。
受け入れ: `AT-STORE-006` / 最初の必須gate: `G9`。
