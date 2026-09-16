# 管理台帳の寿命管理 — 00.27.00候補

**実台帳の非破壊的な棚卸し + 独立した純粋モデル**。共通GC、実データ移行、署名済み世代承認の発行器ではない。

## なぜ実データを削除しないか
ManagementJobs、Controllerの受付台帳、RetiringSubmissionsには、それぞれ32/128/32件の上限がある。登録済みstageや受理済みcontrolはjobを参照し、jobは署名済み入力・効果証拠を保持する。CANCELLED/SUCCEEDEDだけを見てjobを消すと、旧要求の再送と登録済み入力の検証を壊す。
既存三入口には共通の再送世代がなく、既存readerはarchiveからjobを解決できない。この四つの移行条件（jobs/control/submissions/archive_resolver）は実棚卸しで必ずfalse。全件が終端でも`real_deletion_allowed=false`、`MIGRATION_REQUIRED`となる。

## 読み取りadapter
`collect_inventory(retiring_submissions, expected_pins=None)`は、既に排他的に開いている同じ所有process/threadの三台帳を使う。接続中・読み取り保護中・ジョブ選択中・fault中は拒否する。独自socket、独自DB、認可キャッシュは追加しない。
既存のaudit/read/pollによって署名と入力・結果の対応を再検証する。SUCCEEDEDは実行結果の根拠も照合する。前後のPin、controller policy、backend context、活動状態を比較し、途中の変化を拒否する。未確認の`.tmp`があれば自動修復せず拒否する。
これは協調する同一所有者内の整合性検査であり、敵対的writerとの原子的snapshotや同一OSユーザーに対する隔離を保証しない。既に開くまでの初期化は呼び出し元の責任で、collector自身はclose/compact/retire/reconcileを呼ばず、新しい署名を作らない。

出力はID・状態・ハッシュ・参照・サイズのみ。秘密鍵、署名済みコマンド本文、監査本文、ローカルパスを出さない。IDと参照関係はメタデータなので公開前に取り扱いを確認する。
**JSONには署名済み原文は含まれない。`LIVE_READONLY`という文字列だけは信頼根にならない。** 外部から渡されたJSONを読み直しても「元台帳の署名を再検証した」とは扱わない。

## 純粋モデル
`LifecycleModel`は`MODEL_FIXTURE`だけを受け付ける。世代付き要求は既に署名検証済み、全入口に永続fenceあり、archive resolver移行済み、という仮定を入力に明示して試す。これらの本番機能を提供するものではない。

| 遷移 | 模型上の条件 |
|---|---|
| OPEN → CLOSED | 全件終端、予約量0、参照完備、現在controller、正確なsnapshot/履歴digestに一致、archive予算内 |
| CLOSED → ARCHIVED | 閉鎖した集合を正確に保持し、digestを照合 |
| ARCHIVED → COMPACTED | archiveと閉鎖対象の一致を確認して、メモリー内の格納場所を変更 |
| COMPACTED → OPEN | 同じcontrollerの明示操作で次世代へ。閉鎖済み世代は再受付しない |

ARCHIVEDは格納場所であってjob stateではない。ACCEPTED/CANCELLED/SUCCEEDEDを変更しない。archived jobへのcontrol/submission参照も元の入力と状態へ解決する。新世代でも同じIDや、別IDに付け替えた同じjob intentを拒否する。
実装はcopy-on-writeで、拒否された遷移は元モデルを変えない。checkpointは初期状態とイベントのJSON。再読み込みはイベントを再生して状態を再計算するだけで、実ファイル・ジョブへ副作用を与えない。別保管のPinで既知prefixを検査する。Pinとcheckpointの同時巻き戻しは対象外。暗号署名や耐電源断性のあるjournalではない。

## 上限とサイズの意味
JSON/checkpoint 2 MiB、現世代512record、外部anchor1024、1record最大16参照、256イベント・64世代。archive見積合計64 MiB。上限は試験用候補であり性能実測の上限ではない。
`storage_bytes`は今回読んだ記録と残るpayloadの見積。実移行archiveには署名済み原文・必要な証拠・索引がさらに必要で、見積は容量予約・物理空き容量・安全消去の保証ではない。模型のarchiveはハッシュ付きメタデータだけで、本物の復旧archiveの代わりではない。

## 実行
```
python3 tools/check_record_lifecycle.py
python3 examples/record_lifecycle_demo.py
python3 examples/record_lifecycle_demo.py --export /tmp/par-lifecycle-inventory.json
python3 tools/record_lifecycle.py /tmp/par-lifecycle-inventory.json
```
デモだけは既存の合成テスト用ホストを一時領域へ初期化する。入力元ファイルが診断前後で不変であることを確認する。exportは新規ファイル専用で上書きしない。解析CLIは標準Pythonだけで動き、記録を削除する機能はない。実台帳collectorとデモは既存のSQLite/libsodium/私有IPCテスト条件を引き継ぐ。

## UI契約
Presenterはledger別件数、未完数、予約量、阻害理由、参照確認とexportだけを返す。削除ボタン・推測の進捗率・「バックアップ済み」表示は作らない。実UIの描画・アクセシビリティ試験は未実施。
