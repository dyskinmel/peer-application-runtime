# Upload replay window — 00.18.00 / 局所候補

## 目的と状態
issuer署名付き世代を全操作の外側署名へ結び付け、世代の閉鎖を同期してからterminalの操作記録を集約する。旧begin/chunk/retire/sealを再送しても、新しい世代へ流入させない。`ReplaySpool`は同じ所有スレッドで`RetiringSpool`を包む。旧spool/IPC/hostのコードは変更していない。

製品プロトコル、ネイティブ実装、実機、CRDT適用、第三者レビューは未認定。全状態の整合した巻戻しを、同じ保存領域だけで検出したとはしない。

## API
- `ReplaySpool(keeper, root, store_id, max_bytes=16MiB, max_records=1024, max_archive_bytes=64MiB, max_windows=64, expected_pin=None)`。新規の私有root専用。legacy rootを自動移行しない。
- `make_window(provider, issuer_seed, authority, keeper_public, store_id, sequence, nonce, previous_receipt_digest)` → issuer署名付き開始承認。初回sequence=1、previous=None。
- `spool.open_window(grant)` → 初回又はCLEANED後の厳密な次の世代。nonce再利用・連番飛越し・別の前回receiptは拒否。
- `wrap_command(provider, subject_seed, window_grant, kind, inner_command)`。kindはexecute/retire/rebindのみ。innerは既存APIで作った署名付き要求。全体を現在の世代へ再署名する。旧要求を書き換えて世代だけ付け替えることはできない。
- `spool.execute(envelope)` / `stamp(envelope)`。ホストは必ずこのgatewayを通す。内部のschema2 spoolを直接呼んではいけない。
- `spool.export_archive()` → 全recordがconfirmed handoff又はTOMBSTONEDのときだけ、完全な監査exportを生成。未開始bindingも未確定扱い。
- `approve_close(provider, issuer_seed, current_authority, window_grant, archive, operation_id)` → 正確なexport digestに対する閉鎖承認。
- `spool.close_window(approval, archive)` → archiveとCLOSED境界を同期。この後は旧世代の全commandを拒否する。
- `spool.compact()` → すでに承認された固定対象の記録整理を続行。CLEANEDを同期して初めてactive record枠を返す。再実行は保存済みreceiptを検証して返し、再署名しない。
- `spool.pin()` / `verify_pin(pin)` → 既知の開始・閉鎖情報を、別の信頼領域へ保管して照合するための値。ネットワークから受け取ったpinだけを自己認証の根にはしない。

`make_window`はadmissionの世代を定義するだけで、データ書込み権限を新しく与えない。内部capability/retirement grantと現在のKeeper authority検証も必要。

## 永続化の順序
1. beginの世代署名をbindingsへ保存する前に、capability、lease状態、payload予算、記録数、将来必要なaudit容量を検査。
2. bindingを同期した後、既存spoolのbeginを実行。ここで停止した未開始bindingは、同じ要求の再試行又は現在のretirement許可で解決する。失効した旧upload許可で強制再開しない。
3. terminalの`.cbor/.retirement/.bound`の正確な集合、bytes、hash、サイズ、device/inodeを監査archiveへ保存し、同期する。
4. issuer承認とarchive digestを含むKeeper署名付きSTATEをCLOSEDへ更新・同期する。
5. 対象名・内容・identityを再照合して、metadataとbindingだけをunlink。関連directoryをfsyncする。
6. すべての対象がないことを確認し、CLEANED receiptをSTATEへ保存・同期。active record枠を返す。
7. 次の世代は、前回receipt digestに結び付いた新しいissuer承認で開く。自動移行やTTLは使わない。

CLOSED以後の整理は、すでに確定した明示的承認の残作業である。authority更新によって対象を拡張せず、同じ固定対象だけをcompactで処理する。再起動は署名・archive・残存対象を検査するが、保留中の整理を自動実行しない。新しい世代の承認には現在のauthorityを要求する。

## 容量と監査
active操作記録は整理し再利用するが、元bytes・署名・承認・結果を集約したarchiveと、小さい世代履歴を保持する。物理データ全消去、DBページ縮小、無制限運用を意味しない。

archive形式は`PARWA1\0 + u32 header_length + signed canonical-CBOR header + entry bytes`。CBOR headerは900000 bytes以下であり、既存wireの1MiB制約を緩めていない。1archive16MiB、合計64MiB、世代64。archiveには秘密鍵を格納しないが、権限や対象を示すメタデータがあるため私有領域に置く。

begin時に将来の最悪サイズを予約する。各stageについて`outer_length + inner_length + 131072 + 4096` bytesをaudit余裕として計算する。このため1024というrecord上限の前にaudit予算で受付を止めることがある。未確定stageを解決して世代を閉じれば、次の世代でactive枠を再利用できる。audit合計や世代上限に達した場合は停止し、自動的な監査削除はしない。

## 既存サービスと移行
新規root markerはschema3、内部liveは既存schema2。旧schema1/schema2ホストに新rootを渡すと拒否する。既存のアップロードサービスはこのgatewayに対応していないため、未対応hostのままliveへ直接接続しない。旧rootは保持し、既存の中止/確定手順で解決する。in-place importやcross-profile replay除外は未実装。

## 試験と範囲
`python3 tools/check_upload_window.py`。118試験: 契約18、ライフサイクル21、監査33、障害36、追加堅牢化10。28の実子process SIGKILL。署名改変、旧世代再送、正確な監査集合、予算拒否、authority変更、未開始bindingの中止、外部pin、再開、Keeper不変を試験する。600の合成terminal stageを持つ1MiB超の正しいarchiveも検査するが、600件を本番サービスで処理できるという性能認定ではない。

## 非保証
同UIDの敵対的コード・DB/STATE/archive一式のrollback・媒体故障・安全な消去・ネットワーク上の最新性・原子性のないファイルシステムは保証しない。フック後の再照合は協調的ownerモデル用で、無限のTOCTOU競合を封じるOS sandboxではない。I/O異常はOUTCOME_UNKNOWN又は明示的fail-stopで再openが必要。実測環境の旧SQLite/libsodiumは合成実験だけのopt-inであり、本番認定していない。
