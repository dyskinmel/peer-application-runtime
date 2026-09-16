# ADR-LOCAL-MIGRATION-REHEARSAL-0057 — 検証済みshadow generationへのlocal移行

状態: ACCEPTED_LOCAL_CANDIDATE / 2026-09-11

## 文脈

`PAR-MIG-002..005`と`PAR-OPS-003..004`は、元storeを保全し、別領域のbackupをreadbackし、operation ledger/outbox/未反映draftと未知必須codecを保持したshadowを検証してからだけgenerationを切り替えることを要求する。00.56.00はprovider handoffを固定したが、migration atomicityは未実装だった。

現環境はPython/SQLite/POSIXを実行できる一方、Rust/Cargo、実Keychain、物理電源断、G9本番認定を提供しない。したがって本ADRはlocal rehearsalの意味論と障害境界だけを固定し、native/product qualificationを主張しない。

## 決定

### 1. storeとwork領域を分離する

store rootは`ACTIVE.json`と`generations/<generation>/store.sqlite`を持つ。migration work rootはplan、journal、backup、shadowを持ち、active source generation配下へ書き込まない。work rootとstore rootは同一POSIX filesystemであることをswitch前に実測する。

### 2. planはread-only観測から作る

plannerはSQLiteをread-only/immutableで開き、独立したwire/suite/schema/store/SDK/UI version、source generation、DB SHA-256、schema/inventory、seed/frontier digest、必要容量を固定する。WAL/SHM残存、unknown store version、quick_check失敗、容量不足はfail closedとする。plannerはdirectory、DB、pointerを作成・更新せず、外部通信を行わない。

### 3. plan identityとjournal reuseをsource digestへbindingする

canonical plan digestからmigration IDとtarget generationを導出する。journalはatomic JSONとして保存するが、再開判定はjournalのstageだけでなく、source digest、backup manifest、shadow manifest、published generation、ACTIVE pointerを毎回再検証する。source digestが変化したjournalは`SOURCE_DIGEST_MISMATCH`で拒否する。

### 4. backup readbackをshadowの前提にする

backupは一時directoryへcopy・fsyncし、size/hash/schema/inventoryを記したmanifestを作成し、別openでreadbackする。readbackが成立する前はshadowを作らない。途中backupはactive sourceに影響せず、再開時に所有された一時領域だけを破棄して再構築できる。

### 5. shadowは新schemaへ論理copyする

shadow DBはbackupから新規構築する。operation ledger、outbox、未反映draft、signed object、approved seed bytes、source frontierをrow単位でcopyする。converter digestとsource frontier/seed digestはplanおよびtarget metadataへ固定する。

未知のmandatory codecはsigned bytesをbyte-for-byte保持し、`UPGRADE_REQUIRED`、`applied=0`、`ack_state=BLOCKED`、`resigned=0`とする。unknown fieldを削除して再encode・再署名・applied ACKする経路を提供しない。

### 6. 検証済みshadowだけをpublish/activateする

shadow検証はSQLite integrity、exact schema、source/target logical inventory、operation/outbox/draft identity、signed bytes、unknown codec状態、seed/frontier、converter digestを確認する。成功後にmanifestを固定し、shadow directoryを`generations/<target>`へPOSIX renameする。

ACTIVE pointerは一時fileのwrite+fsync、`os.replace`、root directory fsyncで切り替える。旧generationは削除しない。pointer切替後journal更新前に停止しても、再開時はACTIVEとtarget manifestを検証し`ACTIVATED`へ収束する。

### 7. crash oracleを段階ごとに固定する

実processをSIGKILLする境界は、backup前/途中、shadow途中、検証後、switch直前/直後とする。再開後のobservable active generationは元generationまたは検証済みtargetだけであり、壊れたshadow・unverified generationはactiveにならない。

## 非決定・非主張

- Rust/native migration実装、Apple/Android secure storage、native filesystem durabilityは未認定。
- SIGKILLは物理電源断、媒体故障、kernel/fs bugの代替ではない。
- local SQLite candidateはG9 PASS、production readiness、real CRDT semantic migrationを意味しない。
- 共通core/binding結果を独立protocol実装の一致とは呼ばない。
- 旧generationの自動削除、retention期限、secure eraseは本ADRの範囲外。
