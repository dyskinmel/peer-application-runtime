# Keeper upload — 00.16.00 / ローカル候補

## この実装の意味
Linuxの私有AF_UNIX上で、既存schema3 KeeperRepairへ別processからreserve/put/sealを届ける。旧read serviceのprofile・allowlist・ソースは変更しない。2つのlistenerは同じowner threadでpollされ、同じKeeperを共有する。internet通信や新しい暗号protocolの認定ではない。

## 契約
profile `keeper-upload-local-v1`、許可操作はbegin/chunk/progress/reserve/put/sealだけ。renew/release/GC/repair/authority更新・任意methodは受け付けない。親directory0700、socket0600、同UID SO_PEERCRED、既知Keeper public keyと接続ごとの署名challengeを継承する。追加の経路暗号化はなく、同UID任意コードに対する秘密鍵隔離ではない。

stable commandはversion/profile/action/operation ID/capability/inner Keeper call/lease/payloadをsubject署名へ結合する。接続ごとのrequestはそのcommandとfresh helloへ別に署名する。同じ操作を再試行するときcommandは保存・再利用し、helloだけを新しくする。外側のchallengeを永続idempotency keyにしない。

indexもobjectも要求64KiBに入り切るとは仮定しない。beginはkind/ID/全長/SHA-256を宣言、chunkはtoken/offset/最大32KiBデータ、progressは確認済みoffset・prefix hash・destinationへhandoff済みかを返す。indexはreserve capabilityで事前認可、objectはlease owner・inventory・署名付きput callに事前結合する。indexは全体署名検証前にも上限付きstageへ置かれるが、正常なleaseとしては数えない。

## 容量と永続化
`Spool(keeper, root, max_bytes=16*1024*1024, max_records=1024)`。通常rootはKeeper配下`incoming-upload/`。作成済みdirectoryは所有者0700、fileは所有者0600・単一hardlinkを要求し、再開・操作時にも検査する。既存LIMITSと起動設定が違えば拒否。これは協調ownerの私有領域向けで、同UIDによるpath競合の完全防御ではない。

beginは許可確認→一時容量予約→空payload fsync→metaをatomic replace+directory fsync。chunkはpayload write/flush/fsync→認可再確認→offset/hash metadata fsync→応答。再起動は署名済みbeginと実ファイルから検証。未確認tailのみtruncateし、確認済みprefixの欠落・改変は正常として自動修復しない。完全一致の再送のみ受理し、gap/重なり/差替えは拒否する。

handoffはKeeperのreserve/putを先に確定→stageのcommitted recordをfsync→一時payload unlink+directory fsync。別journal間のatomic transactionを主張しない。中断時はKeeperの既存idempotencyで照合する。sealはKeeper全データ再検査と永続receiptを再利用し、重複で期限・generation・quotaを増やさない。commit後の一時cleanup失敗はOUTCOME_UNKNOWNで、再openして同じcommandを再照会する。

記録済みcommittedのprogressは過去のhandoff観測で、現在の全payloadの健全性ではない。再put/再seal/取得側検証で現在のデータを確認する。整合したDB/journal全体の巻戻し防御ではない。

staging容量は未完stageの宣言payload合計。DB/WAL/署名metadata/transient duplicateを含むOS全体の物理quotaではない。宛先確定後もoperation tombstoneを残すため、1024 recordsに達すると新規beginを拒否。失効した未完stageも保持・課金したままで、自動expiry/削除はない。次の明示的なretirement契約が必要。未完leaseの容量解除も別契約。

## API
Client(path, provider, keeper_public, subject_seed, capability, timeout=...)。
`begin(kind, oid, raw, operation, lease=None, call=None)`→token/progress。
`chunk(token, offset, bytes, lease=None)`、`progress(token, lease=None)`。
`stream(token, raw, lease=None)`は進捗hashを確認し不足分を送るが、例外時に自動再試行しない。
`reserve(token,index,pin,seconds,operation)`、`upload_object(lease,oid,raw,operation)`、`seal(lease,operation)`。
`upload_bundle(index,pin,objects,seconds,operation)`は上限付き一式を先に検査し、root operationから各段階の安定IDを導出する。再試行は同じroot operation・同じ内容で呼ぶ。入力の差替えは拒否。
送信後の切断はOUTCOME_UNKNOWN。生commandのexecuteによる再送も可能。相手が行っていないと断定して新nonceで重複予約しない。

## 起動
既存schema3 KeeperDB、正しいhost設定、署名seed用inherited fdを用意する。旧fixture opt-inは使い捨て公開データだけ。
```
python3 tools/keeper_upload_host.py --root PRIVATE_KEEPER_DIR \
  --socket PRIVATE_DIR/read.sock --upload-socket PRIVATE_DIR/write.sock \
  --host-config PUBLIC_CONFIG.cbor --key-fd INHERITED_FD
```
設定形式は`tools/keeper_upload_host.py`と既存service READMEに従う。サンプルの語は実パス/fd番号へ置換する。秘密鍵をargv・host設定・ログへ書かない。自動新規DB作成/移行/stale socket削除なし。SIGKILL後はそれぞれのsocket identityとinactive owner lockを確認して、既存の明示recover_staleで回復する。

## 検証と境界
```
python3 tools/check_keeper_upload.py --suite contract
python3 tools/check_keeper_upload.py --suite spool
python3 tools/check_keeper_upload.py --suite service
python3 tools/check_keeper_upload.py --suite faults
python3 examples/keeper_upload_demo.py
```
111 tests、31 real SIGKILL cases（spool29/service2）。通常fixtureの一部objectは64KiB超。70000byteの不正indexも分割受信はできるがreserveを拒否。別donor processのupload後、元DB/平文を除去し別recipient processで既存read IPCから復旧する。
I/O deadlineは絶対socket期限で、同期的なSQLite/fsync/cryptoを強制preemptしない。各listener最大32接続で2つを同時運用。許可変更後に返せない結果は再照会対象になり得る。世界全体の最新authority発見・自動修復・CRDT適用・writable recovery・native/public transport・独立reviewは未実証。
