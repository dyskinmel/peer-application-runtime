# Keeper GC — ローカル候補 / 00.13.00

## 目的・境界
既存Keeperのreleaseは依然として削除命令ではない。新しい`KeeperGC`は、署名された専用GC要求によって明示解放済みleaseだけを回収する。expired/unknown aloneでは実行しない。元製品仕様・プロトコルは未凍結、G0〜G11は未認定。

## API
```python
from par_keeper_gc import KeeperGC, make_request, verify_result
# 認可済み合成fixtureによる完全な実行例は examples/keeper_gc_demo.py。
target = keeper.gc_target(lease_id)   # trusted-host診断。ネットワークendpointではない
request = make_request(provider, caller_seed, release_capability, lease_id,
                       target['generation'], target['release_id'], operation_nonce)
keeper.mark(lease_id, release_capability, request)  # この時点では削除も容量返却もしない
receipt = keeper.collect(lease_id, release_capability, request)
result = verify_result(provider, receipt, keeper_public_key, request)
```
`collect`はmarkも実施する。同じ署名要求を再送すると同じreceiptを返す。別nonce/別capabilityへ置換不可。作業IDはkeeper・caller・nonceを結合し、leaseごとに一つのGC job。release capabilityだけでは不十分で、専用domainの署名要求が必要。

## schema・移行
Keeper schema1を既定では拒否。`KeeperGC(..., migrate_v1=True)`は旧Keeperで実スキーマと署名・操作履歴を検査してから、同じDB transactionでgc_jobs追加・metadata profile更新・user_version=2を確定する。旧Keeperはschema2を拒否。移行前のバックアップを保持すること。自動rollbackやデータの信頼昇格はない。Doc Storeのschema3とは別DB。

## 状態と永続化
`RELEASED_RETAINED` → `GC_PENDING` → `RECLAIMED`。
markは正確な対象一覧、mark時に存在する物理ファイル集合、index、generation、release操作、known authority、要求をKeeper署名で結ぶ。各fileはlease固有directoryに存在し、共有dedupしない。
scan時にunknown名、symlink、hardlink、型/サイズ/hash違いを拒否し、再帰削除しない。ack済みfileがmark前に欠けるなら停止。mark後はintentにあるfileだけをunlinkし、directory fsync→rmdir→親directory fsync→DB finishの順。中断後に既に消えたfileは同じintentの範囲で処理を再開できる。元の集合を都合よく作り直さない。
finishでstored_objectsの対象参照を外し、署名resultとcreditを一緒に確定する。ACK喪失は`OUTCOME_UNKNOWN`。同じrequestで照会/再試行。再試行時も署名・ledger・namespaceを検証する。

## 容量の意味
予約はindex長+宣言された全objectサイズ。GC完了後にobject予約分だけを返す。index・署名・operations・tombstoneはDBに残るためindex分は返さない。
`reservation_released_bytes`は取消し済み予約量、`unlinked_payload_bytes`はmarkで存在を確認し今回のunlink処理が対象にした量（中断再開を含む）。未受信objectの予約取消しを物理削除量へ加算しない。filesystem空き容量、SQLiteページ解放、安全消去を保証しない。
既存lease/operation履歴を残したままactive lease slotを再利用する。最大GC jobs256・既存operation上限4096（設定により異なる）。metadata compactionは未実装。完了したGC領域にファイル/ディレクトリが再出現した場合、再試行・予約・診断・openで拒否。未知ファイルを消して帳尻を合わせない。

## reader / recovery pin
`with keeper.reader(lease, object_id, cap, get_call) as reader:`でleaseを保護。`reader.read()`は現在の権限を毎回確認し、release後は読めないがcontext終了までGCを止める。入れ子pinも最後まで保持。close/再起動後に古いReaderを利用できない。
単一インスタンス/単一thread/協調writerのlifetime flockが前提で、raw fd/pathをpeerへ貸さない。プロセスを跨ぐ長期stream/readerは未対応。GCに必要なpinを永続化していないのはこの条件による。PID時刻だけで外部reader死亡と推測する設計ではない。same-UID敵対的raceは保証しない。

## authorityと未解決
mark/collectのたびに現在のknown authorityと署名grantを検証。mark後にauthorityが変わると旧jobは停止してpayload/予約を保持する。新authorityへ再承認するAPIは未実装。保管者自身が最新membershipを発見するものではない。全DB巻き戻し、untrusted OS、物理電源断、実network/native/第三者reviewは未検証。

旧SQLite/libsodiumの本番拒否は維持。公開・合成データ用の明示opt-inでのみ本環境の実験を行った。依存binaryは配布しない。

## 検証
`python3 tools/check_keeper_gc.py`、または`--suite contract|lifecycle|audit|faults`。独立第三者reviewではない。22件の実子プロセスSIGKILLを含む。全レーンは`examples/keeper_gc_workflow.py --only TASK`で分割実行。
