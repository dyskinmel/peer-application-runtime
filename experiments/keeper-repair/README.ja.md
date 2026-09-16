# KeeperRepair — 00.14.00 / 局所候補

目的: 既知の署名付きinventory内の欠落・破損objectを置換し、未解放leaseの保管品質を回復する。Keeperは内容を復号しない。実network/native/CRDT/Production Readyを認定しない。

## API
`KeeperRepair(root, provider, signing_seed, authority, quota_bytes=..., allow_unpatched_sqlite=False, migrate_v2=False)` は KeeperGC を継承する。new DBはKeeper schema3。既存schema2は明示`migrate_v2=True`のみ移行。v1は既存GC経路で先にv2へ移行。SQLite/libsodium旧版の拒否条件は不変。

`make_request(provider, subject_seed, cap, lease, generation, index_id, sorted_object_ids, nonce)` で要求を署名する。既存capの`put`許可とlease ownerであることが必要。別署名domainなので通常のput要求を修復要求として使えない。

`mark_repair(lease, cap, request)` は署名intentを先に永続化し、job_idを返す。`repair(lease, replacements, cap, request)` は{object_id: bytes}の正確な集合を検査し、mark/stage/replace/fsync/commitを実行する。署名付きの過去のbyte観測を返す。未受信の初期アップロードには従来のputを使い、修復はsealedで未releaseのleaseだけ。

`verify_result(provider, result, keeper_public, expected_request=request)` は観測の署名・要求との結合を検証。`TARGET_BYTES_VERIFIED` は記録時に指定対象を検証した意味。`all_bytes_observed`はその時点の全体バイト集合確認であり、今も健全であること、保管期限の更新、受信者の復号、CRDT適用を示さない。同じ要求を再実行しても過去の同じ結果を返す。新しい損傷には新しいnonceの要求を作る。

`make_cancel(provider, subject_seed, current_cap, lease, job_id, nonce)` と `cancel_repair` はrelease権限とownerを要求する。古いauthorityで開始したprepared jobも、新しい有効な許可で中止できる。中止は修復済みの正しいbyteを元の破損へ戻さない。stageを片付けてから独立stage予約枠を解除する。

## 正確な状態
job: prepared → done、または prepared → aborting → aborted。
leaseのstate、generation、seconds、receipt、chargeには修復が書き込まない。
prepared/abortingはGCとrenewを停止する。releaseは可能だが修復は停止する。中止完了後、従来GCの全条件を満たす場合だけGCできる。read pinはmarkと置換を阻止する。
`EXPIRED_RETAINED`と`UNKNOWN_RETAINED`の修復は可能だが期限は延ばさない。

## 耐障害の順序
署名intent永続化 → 一時fileへ検証済みbytes → fsync → target/stage再確認 → atomic replace → 両directory fsync → byte再確認 → stored_objectsと観測を同一SQLite transactionで確定。
再開はphase文字列だけでなく実file hashから判断。一時fileはjob専用の`repair-staging/<job>/<oid>.part`。未知file/linkは削除しない。COMMIT後の応答紛失はOUTCOME_UNKNOWNで、同じ要求の照会で既存結果を返す。

## 上限と残る制約
- 1要求最大128object、全pending合計32 MiBの独立staging予約、監査job最大256。未解放payloadの元quotaは二重予約しない。stage quotaは監査DB/WALを含む総disk capではない。
- 1 Keeper lifetime writer lock、同一threadの同期API、同一instance reader pin。OS user敵対操作/跨processのstream pin/物理電源断は未検証。
- 破損・欠落したleaseを先にreleaseした場合は修復しない。既存GCも破損を拒否するため、専用の回収承認拡張が必要。勝手に復活・破損データ削除で逃げない。
- abortingの途中でauthorityが再び変わる場合の再束縛は未実装。旧許可での続行を拒否する。
- parentディレクトリ丸ごとの敵対差替えや、整合したDB全体の巻き戻しの検知ではない。
- `replacements`は上限付きのメモリー上map。提供元からの取得・retry/backoff・常時repair schedulerは未実装。

## 実行
```sh
python3 tools/check_keeper_repair.py
python3 examples/keeper_repair_demo.py
python3 examples/keeper_repair_workflow.py --only KEEPER-REPAIR-LOCAL
```
全12レーンはSTART_HERE参照。公開・合成fixtureのみで試験する。
