# ADR-0023: データとは別の所有者用制御経路

## 決定
既存ScheduledHostを変更せず、制御socket・operation journal・clientを合成する。control keyは事前登録jobの運用操作だけを許可し、job本体の管理署名を生成しない。初期操作はstatus/select/cancel/reconcile/retryの5つ。
新規管理payloadの受付を同時に実装すると、close archiveのサイズ/認可/部分受信/監査保存まで別問題が増えるため、本候補では対象外とし次工程へ分離する。

## 正しさと失敗
stable intentとconnection wrapperを分離。nonceだけでidempotencyを実装しない。副作用の前にINFLIGHTを同期し、返却途中の失敗はunknown扱い。受付ackとjob completionは異なる。
再起動はジョブ選択を自動復元しない。署名・known Pin・現在状態の照合をし、明示的な再選択/照合/retryを必要とする。controlのpollはdata drainの外に置くが同じowner順序で実行し、control自体による永続待機を避ける。

## 追加レビューによる修正
1. expected Pinのpolicy revisionでboolとintの等価性を許さない。canonical bytesで照合。
2. mutation実行後のview生成失敗を要求拒否として返さない。CONTROL_OUTCOME_UNKNOWNに分類。
3. ジョブの表示状態とjournal_state/取消可否/照合可否/retry可否を照合。
4. 新規テストのhelper名が既存fixtureのrequestをoverrideした問題は、helperを別名に変更。誤ったREDログを保全し、機能欠如に由来するREDを再取得した。

## 資料
Linux unix(7): https://man7.org/linux/man-pages/man7/unix.7.html
Python3.13 selectors: https://docs.python.org/3.13/library/selectors.html
Python3.13 socket: https://docs.python.org/3.13/library/socket.html
参照日2026-09-06。OS UID/permissionsの性質はLinux private socketに限る。新規protocol・同一操作記録は本実装の候補契約で、これらの資料で全体の安全性が証明されたわけではない。
