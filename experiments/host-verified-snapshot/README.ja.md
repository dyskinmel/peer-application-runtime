# HOST-VERIFIED-SNAPSHOT-LOCAL / 00.20.00

## 完成した候補の境界
一般的な認可・状態snapshotの再利用ではなく、**同一の公開鍵32byte・署名対象の全bytes・署名64byteが、固定済みproviderで正常検証された事実**だけを、同じ所有process/threadのメモリーで再利用する。旧full検証が既定。明示`signatures`だけが有効。否定結果・秘密鍵・復号平文・鍵導出・認可・parsed recordをcacheしない。

構造・認可・現在の世代・SQL・ファイル一覧/内容・応答送信時の失効検査は従来のまま実行する。cache hitは署名計算一回分の省略であり、データが現在存在する/権限が現在有効という主張ではない。hash-only/mtime-only keyは用いない。上限を超えた正当な署名入力は、実検証へフォールバックして受理の意味を変えない。

## ライフサイクル
- 起動・再openは`full_verification()`内で従来の完全検証を行い、cacheを作らず残さない。
- provider instance、identity、verify callable、process/threadを結び付ける。別所有者では拒否し、provider変更はpoisonして再初期化を必要とする。
- 入力/検証/decryptエラー、明示invalidate、authority/DB/generationの観測変更で破棄。scope値は破棄のヒントであって検証省略の根拠ではない。
- cacheは最大512件・入力bytes合計4MiB・message64KiBまでが既定。LRUで退避。Pythonオブジェクト/RSS全体の上限ではない。統計にmessageやkeyを出さない。
- serialize/deepcopy/fork継承を許さない。古い世代を復活させず、変更要求は引き続きReplaySpoolを通る。

## 起動と測定
```sh
python3 tools/check_host_snapshot.py --suite contract
python3 tools/check_host_snapshot.py --suite io
python3 examples/host_snapshot_demo.py
python3 tools/benchmark_host_snapshot.py --output /tmp/par-benchmark.json
python3 tools/keeper_verified_host.py --help
```
新hostは旧`keeper_window_host.py`と同じ必須引数（root/spool/private config/二つのsocket/key-fd）を取り、`--verification-mode full|signatures`を追加する。既存Keeper DB/schema3と既知の署名済みwindowが必要。自動初期化・移行・世代採用はしない。管理は引き続きhostを停止したoffline CLIだけ。旧read/upload protocol/server/client/management sourceは変更していない。キーはFDから渡し、公開合成fixture以外で旧SQLite/libsodium opt-inを使用しない。

## 今回の共通I/O修正
`par_recovery.transfer.read_file`は、上限+1ではなく**実測size+1**を読み、前後のfd metadataとnamed pathの一致を確認する。これにより小ファイルの16MiB割当てを避け、成長・切詰め・同サイズ書換え・path置換を検出する。mode/ino/dev/size/mtime_ns/ctime_nsは局所race検出であり、crypto hashを代替しない。同一OSユーザーの敵対的コードや、最終check後の任意変更に対する隔離ではない。

## 測定・試験の解釈
`evidence/development/00.20.00/benchmark-initial.json`（共通reader修正前）と`benchmark-bounded-reader.json`（修正後）を同梱。合成32署名の反復と、実ReplaySpoolの閉鎖済み1世代+現世代indexのstampを、同じfixture上でfull/cachedの順を交互にして比較する。各mode12反復。latencyとtracemallocは別測定。入力hashを記録し観測結果を比較する。warm/coldと小データの測定で、ネットワークSLA・一般的な高速化率・RSS全体の上限を主張しない。

108試験（契約29、上限20、既存socket動作14、新しいlive条件15、別process8、故障10、I/O12）。1件のSIGKILL再起動と1件の実fork分離を含む。定義した有効/無効入力に対する自己検証であり、第三者の証明ではない。全件照合自体は残るため、履歴の増加に対する計算量の問題を解消したとはしない。

## 未実証
新しいproviderの本番認定、native/Rust/Automerge、実機・internet、physical power loss、独立review、同一userの悪意ある操作、GC安全性の新規保証はない。新ホストのcacheを既定化する判断も未実施。初回・missの費用、未知入力を大量投入された場合はfullの費用が残る。
