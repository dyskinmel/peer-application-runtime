# G0-STORE-LOCAL — 00.05.00

実行できる保存契約の実験。**本番runtime、暗号ライブラリ、認可済み同期、Keeper、G0/G1/G3/G9の適合実装ではない。**
Python標準sqlite3/POSIX filesystemと、前版のPAR CBORを使用する。Python 3.11以上、SQLite 3.37以上、POSIXが必要。検証環境はLinux/Python3.13.5/SQLite3.46.1。

## 動く範囲
暗号化・署名が済んだと呼出し元が表明するopaque bytesを受け取る。Storeはその暗号的正当性を検証できない。
nonce予約を先に永続化し、実際にsealする直前の一回限りの発行記録として使う。DB本体はenvelope/ledger/actor/cache/outbox/block参照を原子的に保存する。
厳密な再試行、writer fence・epoch・actor sequence比較、送信待ち再開、hash付きBlock公開、診断/audit、整合snapshot、読み取り専用復元、明示orphan GCを実装した。

## 実行
```
python3 tools/check_store.py
python3 examples/store_workflow.py
python3 examples/store_demo.py
```
標準のstore_workflowはPythonのみでH0+STOREを検証する。前版wireのNode照合も含めるには`--include-wire`を付ける。
`store_demo.py`は新しい一時directoryで作成→commit→snapshot→read-only restoreを実行する。既存データへ書き込まない。サンプルbytesはTEST用opaque markerであり実暗号文と称さない。

## APIの核
`Store.create(path, allow_unpatched_sqlite=True)`は、この環境の未修正SQLiteを実験に限り使うことへの明示選択。
既定Falseのままなら既知修正を確認できないversionは拒否する。SQLite WAL-resetの修正範囲は公式資料の確認日現在に固定した候補判定であり、全脆弱性/ベンダーbackportの自動証明ではない。
`Store.open`は欠損DBを新規作成せず、未知schema/破損を拒否する。DBやsnapshotは私有ローカルdirectoryでのみ扱い、ネットワークFSを本番対応にしない。
`reserve_nonce(op,input,key_context,nonce)`→一度だけseal→`PreparedCommit`→`commit(...,fencing_token=...)`。
再送は`lookup_operation(op,input)`で元receipt/bytesを確認する。入力やprepared bytesの差替えはOPERATION_CONFLICT。
`pending(limit=128,after=None)`はID順のページ。`mark_inflight`と`recover_outbox`はoutboxのstorage stateだけを扱い、ネットワーク送信の成功を偽装しない。

## 意図的に残した境界
- 署名、AEAD、鍵保管、plaintext sentinelのE2E漏洩試験は未実装。store自身にencryption機能があるとは言わない。
- `configure_space`/`advance_epoch`は信頼された制御層用のCAS port。受信ControlEntryの認証を実装したものではない。
- process SIGKILL・例外、SQLite max_page_countのSQLITE_FULL、BEGIN lockのBUSY、制約/interruptを試す。物理ENOSPC/電源断/媒体故障全体の代用ではない。
- 同一uidが直接DB/lock/pathを改変する攻撃はOS側の境界が必要。既知symlinkは拒否するが、完全なTOCTOU封じ込めではない。
- `connection`と`observer`はローカル実験・診断用port。製品SDKへraw SQLや任意callbackを公開してはならない。
- 復元snapshotはhash整合性のみ。署名・最新性・権限を証明しない。復元先は書込み禁止。新鍵/新actor generationへの移行が実装されるまでは自動活性化しない。
- nonce intent、commit履歴、outboxを自動削除しない。無制限運用を保証せず、現experimentに総quota/暗号的履歴compactionはない。
- full auditは全保存内容を読む診断用。リアルタイムのincremental監査は後続。prepared入力のblock合計上限は128×266240 bytes、cache4MiB、envelope768KiB。

## ソース境界
`model.py` 型・上限・fingerprint / `store.py` transaction・CAS・outbox /
`fs.py` POSIX publication / `schema.py` 実schema一致 / `recovery.py` audit・snapshot・read-only restore。
元DDLは変更せず、5 tableとcommit orderを加える候補overlayを別fileへ置く。29 tableが存在しても、元24 table全機能が実装されたという意味ではない。
