# KEEPER-SERVICE-LOCAL — 00.15.00

既存schema3 KeeperRepairを所有するLinux processに、private pathname Unix-domain socket経由で読み取り要求を送る候補。Python/nativeライブラリの局所実装であり、PAR v1 wire/Noise/libp2pの相互運用やproduction-readyを認定しない。

## 使える操作
`Client.fetch(lease, oid)`、`status(lease)`、`receipt(lease)`、`challenge(lease, nonce)`。署名capabilityとsubject所持証明を既存Keeperへ渡す。状態確認もexact lease/index scope内だけ。index、Pin、capabilityは別途信頼した経路で受け取る。単なるhash所持を取得権限にしない。
`RemoteProvider(client, lease, index, pin)`は既存Inboxへのport。指定indexのkind/size/object IDを受信側でも照合する。
GET/statusの成功は、その時点のローカル観測であり、将来保持、別host到達性、global latest authority、CRDT applyを保証しない。receiptは過去の署名確認で、callerは別Pinと既存`verify_receipt`でも検証する。

## 確認方法
```sh
python3 tools/check_keeper_service.py
python3 examples/keeper_service_demo.py
python3 examples/keeper_service_workflow.py --only KEEPER-SERVICE-LOCAL
```
最後のworkflowには前段レーンのfresh evidenceが必要。全順序はSTART_HERE参照。デモは公開合成鍵と一時領域だけを使用し、ネットワーク外部通信は行わない。OSのlibsodiumはpolicyに一致する実体を必要とし、旧版の本番拒否は維持する。

## ホストと鍵
`tools/keeper_service_host.py`は既存schema3 Keeper DBだけを開く。新規DB生成、migration、信頼情報の自動発見はしない。
公開のhost-configはcanonical CBOR `{0:1,1:[app,space,head,sequence,epoch,issuer],2:quota_bytes,3:max_leases,4:max_operations}`。既知authorityと設定は既存DBと一致しなければ停止する。key-fdは32 byte signing seedのみを含む入力でEOFが必要。seedをargv/host-config/logへ置かない。
```sh
python3 tools/keeper_service_host.py --root /private/keeper --socket /private/ipc/keeper.sock \
  --host-config /private/host.cbor --key-fd 0 < /private/keeper-seed.bin
```
これは利用者が準備した保護済みファイルを渡す書式例で、ファイルや鍵をこのkitが自動生成するわけではない。Python内のkey/copyをhardware keystore相当に保護するとは保証しない。旧imageで公開合成fixtureのみ動かす場合に限り`--allow-unpatched-sqlite --allow-legacy-sodium`を明示。通常起動では拒否する。

## 接続と相互の識別
Linux AF_UNIX pathnameのみ。直近の親dirは同UID・0700、socketは0600。symlink/abstract/relative/長すぎるpathを拒否。双方でSO_PEERCREDにより同UIDを確認し、アプリ権限は別の署名capabilityで検査する。
acceptごとにKeeper署名のhello（profile、Keeper public key、process nonce、connection nonce、総I/O期限、サイズ上限）を送る。要求はhello全体のdigest、capability、既存署名call、method、lease、payloadにsubject署名。応答もhello/request digestにKeeper署名。全てdomain分離し、未知field/非正規CBORを拒否する。
クライアントはKeeper public keyを事前pinする。外側request署名検証は権限付与ではなく、実dispatch時に既存Keeperがcurrent known authorityを照合する。一接続一要求で終了し、古い要求を別helloへ転用できない。同接続に余分なrequestを送っても二つ目は実行しない（全ての後送trailing byteの検出を保証するわけではない）。
通信内容の追加E2EE/forward secrecyは導入していない。contentは既存E2EE、metadataはローカルOS権限に依存。同UID敵対コード・rootを隔離するものではない。

## 処理と資源の境界
single owner threadでselect。worker thread/任意module/任意URL/shell dispatchなし。read-only methodsのみ、reserve/put/seal/renew/release/GC/repair/authority更新は非公開。
request最大64KiB、response最大1MiB、objectは既存900000bytes上限。最大8接続（設定上限32）、OS backlogも同じ値。request input＋response bufferはconnection上限に比例してbounded。暗号・backendの一時copy等を含むprocess RSS全体の厳密な上限を主張しない。
acceptから応答完了までの絶対I/O期限は既定5000ms（50〜30000ms）。1 byteずつ進んでも延長しない。slow clientをselectorで待ち、他connectionの処理を妨げない。OS backlogの厳密件数はkernel実装にも依存。既存store/署名の同期呼び出しをdeadlineで強制preemptすることはできない。

## 読み取りと権限変化
GETは既存reader contextを取得し、bounded bytesを読み、送信完了/切断までpinを保持する。host側GC/repairは同じpinで拒否される。secretやFD/pathは貸し出さない。
各send前にknown authorityとlease generation/stateを再確認する。release/authority更新/uncertainがあれば残りのresponseを送らず閉じる。すでにsocket/kernel bufferへ渡したbyteを回収することはできない。完全な署名responseを受け取るまでclientはpayloadを返さない。
statusは既存の局所状態を列挙型として検証し、必要項目の欠落やproduct-qualified/network reachabilityの虚偽昇格を拒否する。UIはこの状態を別Presenterで表示できるが、実UIの実装は今回行っていない。

## 切断と再開
送信開始後のtimeout/切断は`OUTCOME_UNKNOWN`。read-onlyなので永続mutationのexactly-onceを主張しない。自動再接続/再試行なし。呼び出し側が新connectionでGETを再要求でき、Inboxはdiskのobject hashから不足集合を再計算する。object内offset再開ではない。
ホストSIGTERMはloop停止後に自身のsocketのみ削除。SIGKILL後はsocketが残る。起動時に自動削除しない。
明示復旧は`socket_identity(path)`のdev/inoを外で確認して`recover_stale(path, expected_identity)`へ渡す。同じendpoint lockを取得し、connectがECONNREFUSEDであることとinodeが不変なことを確認した場合だけsocket entryを取り除く。active owner/未知状態/置換は拒否する。Keeperデータや任意directoryは削除しない。

## 検証と未完了
118 service tests: contract46/lifecycle23/recovery12/faults28/hardening9。server6箇所＋recipient1箇所の実SIGKILL。提供元DBと元平文を除去後、別Keeper/別recipient processで復旧・中断再開し、実ファイル一致を確認。
同作成者の自己試験であり独立レビューではない。Linux/private IPCのみ。実internet/NAT/mobile/native Rust/Automerge/書込可能復旧/物理電源断は未実証。既存provider/security留保を継承する。
次は`plan/NEXT_KEEPER_SERVICE_UPLOAD.ja.md`。read-only契約を壊さず、署名予約/分割upload/保管確認のmutation planeを別に実装する。
