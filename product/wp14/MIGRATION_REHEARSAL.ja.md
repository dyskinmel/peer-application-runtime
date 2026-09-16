# 00.57.00 local migration rehearsal 契約

状態: **LOCAL CANDIDATE / Python 3.11+・SQLite・POSIX限定**。基準は00.56.00 native/provider handoff。実装は `product/wp14/par_migration/`、固定profileは `migration-profile.json`、設計判断は `docs/decisions/ADR-LOCAL-MIGRATION-REHEARSAL-0057.ja.md`。

## 目的

元generationを一切書き換えず、read-only plan、readback済みbackup、論理検証済みshadow、同一filesystem上のgeneration publish、fsync済み`ACTIVE.json`置換を通じて、途中停止後も **旧generationまたは完全検証済みtarget generationのどちらかだけ**を読めるlocal migration意味論を固定する。

これは製品migrationの資格認定ではない。Rust/native build、実Keychain、端末filesystem durability、物理電源断、実CRDT意味移行、G9、独立レビューは別gateである。

## store layout

```text
store-root/
  ACTIVE.json
  generations/
    <source>/store.sqlite
    <target>/MANIFEST.json + store.sqlite   # 検証後だけpublish
  .migration.lock                           # cooperating writer lease
work-root/
  <migration-id>/
    PLAN.json
    JOURNAL.json
    backup/MANIFEST.json + store.sqlite
    shadow/                                 # publish前だけ存在
```

`ACTIVE.json`はgeneration、store SHA-256、store versionを厳格に結ぶ。unknown version、downgrade、pointer/hash/schema不一致、WAL/SHM/journal残存はfail closedとする。

## 一方向state machine

1. **PLANNED** — immutable/read-only SQLite openでwire/suite/schema/store/SDK/UI version、exact schema、logical inventory、seed/frontier digest、source digest、必要容量を固定する。plannerはstore/work rootを作成・更新せずsocketも使用しない。
2. **BACKUP_VERIFIED** — owned temporary directoryへcopyし、file/directory fsync、size/hash/schema/inventory manifest、別open readbackを完了する。symlink、余分なfile、途中copy、plan/source差替えを拒否する。
3. **SHADOW_BUILT / SHADOW_VERIFIED** — backupからtarget schemaを新規構築し、operation ledger、outbox、未反映draft、signed bytes、approved seed、source frontierを明示copyする。logical/hash/schemaの三重検証を通す。
4. **PUBLISHED** — 検証済みshadowだけを同一filesystemの`generations/<target>`へrenameし、directoryをfsyncする。
5. **ACTIVATED** — pointer temporary fileをwrite+fsyncし、`os.replace`後にstore rootをfsyncする。旧generationは自動削除しない。

journalは進捗補助であり、再開の唯一の根拠ではない。resumeはsource、backup、shadow/published target、manifest、pointerを毎回再検証して収束する。

## unknown mandatory codec

未知のmandatory codecを持つsigned dataはbytesを変更せず保持し、targetでは次を固定する。

- `status=UPGRADE_REQUIRED`
- `applied=0`
- `ack_state=BLOCKED`
- `resigned=0`

unknown fieldの除去、再encode、再署名、applied ACK、自動再送は行わない。

## crash / mutant oracle

実子processを次の6境界で`SIGKILL`し、親processがcold reopenしてresumeする。

- `backup.before_copy`
- `backup.after_copy`
- `shadow.after_rows`
- `verify.after_shadow`
- `switch.before_replace`
- `switch.after_replace`

加えて、壊れたshadow、outbox欠落、signed bytes変更、source digest変更、unknown codecの再署名/ACK化、cross-device publish、invalid pointerを拒否する。45 caseのexact inventoryは `policy/migration-rehearsal-*-inventory.json` に固定する。

## 実行

```bash
python3 tools/harness.py doctor
python3 tools/harness.py validate
python3 tools/check_migration_rehearsal.py
python3 examples/migration_rehearsal_demo.py
python3 examples/event_host_workflow.py --only V-WP14
```

checkerのPASSは `LOCAL_PYTHON_SQLITE_POSIX_MIGRATION_REHEARSAL_ONLY` に限る。timeout、missing capability、実行0件、古いreceiptをPASSへ変換しない。

## 現在の境界

- `.migration.lock`はcooperating local writerの排他であり、製品native writer fenceではない。
- `SIGKILL`は媒体障害・kernel/fs bug・物理電源断の代替ではない。
- target v2はrehearsal用の明示copy schemaであり、実Automerge/CRDT converterではない。
- old generation retention/secure erase、運用UI、operator approval、rollback policy、容量回収は未実装。
- Rust/Cargo、Apple/Android secure storage、実デバイス、公開network、G9、production readinessを主張しない。
