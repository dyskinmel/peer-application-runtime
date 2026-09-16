# 所有プロセス内の管理ジョブ / 00.21.00

候補 `host-management-jobs-local-v1`。実装済みの管理処理を、進捗・取消し境界・再照合がある有限ジョブにする。管理IPC・自律background worker・実機認定ではない。旧ホストの管理CLIを置き換えず、同じthreadの `ReplaySpool` を使う明示APIを提供する。

## 使うもの
`ManagementJobs(gateway, private_root, activity=callback)`。rootはKeeper・ReplaySpoolのrootから独立した所有者専用directoryで、重複・包含・symlinkを拒否する。同じPID/threadのみ。callbackは信頼済みホストが報告するactive connection数(integer)で、実装未指定なら実行を拒否する。Keeperのreader pinも独立に確認する。

`submit(job_id, action=..., command=..., archive=...)` で署名済み入力と現在のauthority/windowを固定する。32-byte job IDの同じ入力は再照合、異なる入力はJOB_CONFLICT。同じ署名済み意図に別job IDを与える要求はJOB_ALIAS。取扱いは `retire`, `close`, `compact`, `open` のみで、任意関数名・shell・URLは実行しない。

- retire: 既存の世代付き中止要求を渡す。元の所有者と管理者が署名する権限を流用・省略しない。
- close: 管理者署名のclose requestと正確な監査archiveを渡す。
- compact: 既に永続化されたCLOSED記録を根拠に整理する。新しい承認を勝手に発行しない。
- open: 管理者が署名した次世代grantを渡す。

`step(id)`は一段だけ進める。`poll/list`はpayloadを含めず状態を返す。`cancel`は副作用開始前だけ。`reconcile`はターゲットの永続証拠を読み直し、`retry`はその後の明示操作。`result`は照合済み結果のbytesのみを返す。公開鍵・署名・監査archiveはjournalにあるが、秘密鍵・復号本文はない。

## 状態と意味
| 状態 | 次の操作 | 取消し |
|---|---|---|
| QUEUED | 入力を再検証してVALIDATED | 可 |
| VALIDATED | 入力を再検証してPREPARED | 可 |
| PREPARED | 活動数とreader pinが0ならEXECUTINGを永続化 | 可 |
| EXECUTING | この印の後に既存同期処理を一回dispatch | 不可 |
| OUTCOME_UNKNOWN | 明示reconcileで実ターゲットを照合 | 不可 |
| RETRY_READY | 現在の権限・対象が一致すれば明示retry | 不可 |
| SUCCEEDED | 保存した結果と現在読み出せる歴史証拠を再照合 | 不可 |
| CANCELLED | このjobはdispatchしない | 重複取消しは同じ結果 |

EXECUTINGは保守的な境界で、実際の変更がまだ起きていない場合もある。再起動ではOUTCOME_UNKNOWNとして表示し、constructorで操作を再実行しない。処理がなかったら取消し成功と見せるのではなく、再試行には明示的な指示を要求する。取消しは署名済み権限の失効でも、他のcallerによる操作のundoでもない。

一つのeffect step内の既存管理処理は同期・全件実行のまま。途中で並行poll/cancelできる保証や、長いfsyncをpreemptする保証はない。safe pointで次のstepを選べるだけ。activity callbackの正しさはホスト側の責任であり、本候補はまだlive event loopへ接続していない。

## 永続化と照合
Keeperが署名するjob headerに、ID、操作、入力hash、authority、window/pin、状態遷移履歴を結び付ける。close archiveはheaderのhash/sizeに結び付けた別bodyとし、既存1MiB CBOR wire上限を緩めない。

私有temp → file fsync → replace → directory fsyncの順に1つのjournalを更新する。EXECUTINGをこの手順で確認してからターゲットを操作する。ターゲットとjob記録は別の永続化領域であり、両者をまたぐ原子性・一般的なexactly-onceは主張しない。

照合ではopen/close/compactの履歴、retireのtombstone・署名結果(整理後はretained archive)を既存検査器で検証する。過去の成功を返すだけのために再署名しない。後に権限が変わっても、成功済みの歴史的事実を読むことと新しい変更は別。ただし証拠が欠けたらSUCCEEDEDの結果を無条件に返さない。

journalの保存結果不明時は `JOB_JOURNAL_UNCERTAIN` としてmanagerをpoisonする。ターゲットがpoisonした場合も、内部フラグを解除して強行せず、gatewayを再openして実記録を再検証する。通常の例外では自分が作成したtempだけをbest-effortで片付ける。強制停止後に残った未確認tempは、再起動時に勝手に採用/削除せず、有限の予算内で残す。

## 外部に保管する照合Pin
`pin()`を信頼する別の場所へ保存できる。既知job ID・履歴revision・prefix hashを含む。再open時 `expected_pin` を指定すると、既知jobの消失、古いrevisionへの戻り、不一致を拒否する。新しい正当な履歴は許可する。

同じプロセス中は既知ファイル集合を継続照合する。外部Pinなしでは、全jobファイル削除や保存領域全体の整合したrollbackを再起動後に必ず検出するとはいえない。Pinと領域を同時にrollbackされる状況は対象外。

## 上限と資源
32 jobs、論理保存予算64MiB、1job 32履歴events、archive16MiB。各effect前にEXECUTING/結果/失敗の記録余地を先に確保する。上限で新しい変更を始めてから結果を書けなくなることを避ける。

署名header最大512KiB。1ファイルの最大はheader+archive+12byte framing。未確認tempは最大2ファイル分の別budget。論理budgetは物理ディスク・RSSの総上限ではない。各transitionではarchiveを含む有界journal全体を書き直す。圧縮・削除・GCや無制限の継続運用は未実装。古いjobは自動削除しない。

## UIをPolishする境界
`presenter.present(status)`はmessage_key、日本語fallback、cancel/reconcile/retryの有効性、待ち理由、確定済み結果の表示可否を返す。見た目を含まず、percentageも推測しない。取消しがrollbackではないことを明示する。表示部品は差し替え可能だが、認可・状態はこの表示関数で決定しない。実UIの描画/アクセシビリティ試験は未実施。

## 検証と再開
```
python3 tools/check_management_jobs.py
python3 examples/management_jobs_demo.py
python3 examples/management_jobs_workflow.py --only HOST-MANAGEMENT-JOBS-LOCAL
```
107実試験、うち25SIGKILLケース。contract18 / lifecycle22 / audit27 / faults32 / integration8。誤ったhistory budget、正当に署名された型違い、既知ファイル欠落、古いPin、所有thread/process違い、warm署名cache使用中の権限変更、既存reader pin、結果紛失、再署名禁止を含む。試験は公開合成鍵とtempだけを使用。

## 残す境界
Linux/Python局所候補。patched native dependencies、Automerge意味検証、Rust、実機、独立review、physical power loss、同一OSユーザーの敵対的コードは未検証。既存ホストの管理はまだ停止を伴うCLI。次は [HOST-JOB-SCHEDULER-LOCAL](../../plan/NEXT_HOST_JOB_SCHEDULER.ja.md)。
