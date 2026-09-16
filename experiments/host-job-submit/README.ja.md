# HOST-JOB-SUBMIT-LOCAL / 00.24.00

**稼働中ホストへの登録のみ**を行う局所候補。既存ControlledHostを変更せず第4のUnix socketを追加。要求はcontext/begin/chunk/progress/submit/reconcile/retryだけで、選択・effect・任意メソッドは提供しない。retire/close/compact/openの意味と管理署名検査は既存ManagementJobsが保持する。

## 入力と通信
operator署名descriptorはKeeper/store/operator revision/job ID/対象状態digest/全体size/hashを結合する。payloadはPARJSUB1+header length+CBOR header+archive。closeの最大16MiB archiveは1MiB CBOR frameへ押し込まない。1要求64KiB/断片32KiB/応答16KiB。4同時接続、最大8。私有dir0700/file0600、所有UID、署名を確認。public listenerも経路暗号も追加しない。
contextでpin済みKeeperの署名付き対象digestを取得し、外部署名済みの管理command/archiveをpayloadへする。署名付きcontextはローカル観測であり世界全体の最新性証明ではない。compactの承認は既存署名付き閉鎖記録から検証する。

## 状態契約
RECEIVING → READY → INFLIGHT → REGISTERED。登録後もjobはQUEUEDであり、別のcontrol selectまで実行しない。署名済みの管理許可をcontroller権限で代用しない。
- chunk: payload fsync後に確認済み位置を永続化。重複は同一bytesだけ。gap/overlap/差し替えを拒否。
- READY: 全体size/hashとcontainerを検証できる。管理署名・対象はsubmit前に検証。stage受付時点で管理効果が認可済みとは表示しない。
- INFLIGHT: 永続化後にjob.submit。応答不明は自動再登録しない。reconcileで実jobの入力・元対象を照合し、存在しなければRETRY_READYへ。明示retryが必要。
- REGISTERED: 過去の登録事実。jobは後で選択・成功・取消しされ得る。照会でも実jobとの一致を検証する。再登録でCANCELLEDをQUEUEDへ戻さない。
- 永続化不明は利用を停止して再openする。stage/job journalの単一transaction、 exactly-once effect、取消しの巻戻し保証はない。

## 資源
32段階記録、宣言payload合計64MiB、単一最大16MiB+512KiB+12。jobsは既存32件/64MiB。stage予約はjob枠を保証しない。submit前にjob入力・結果保存の予算を検査する。成功後のstage payloadも保持し、GCはなし。上限到達時は新規beginを拒否、既存progress/reconcileは可能（整合性が保たれている場合）。権限失効したstageは再承認なしには処理しない。再承認APIは未実装。
フレーム期限は同期的なI/Oを強制中断しない。全件/prefixの再読込は有界だが低速になり得る。OS全体のディスク/RSS上限ではない。

## 実行
```
python3 tools/check_job_submit.py
python3 examples/job_submit_demo.py
python3 tools/keeper_submit_host.py --help
python3 tools/keeper_submit_client.py --help
```
ホストは従来のkeeper_control_host引数に --submit-socket と --submissions（独立private dir）を追加。既存Keeper DB、schema3 spool、信頼済みconfig、Keeper鍵FDが必要。既存データの自動移行なし。旧3ソケットのクライアントと併用できるが新登録には新profileが必須。
client: context → prepare（privateファイルへdescriptor生成）→ stage → submit。selectは既存control clientの別操作。job IDとdescriptorを保存して再試行する。payloadを作るAPIは`par_job_submit.protocol.pack_job(action, command, archive)`。commandは外部署名済みのバイト列のみ、パス/URL/コードをサーバーへ渡さない。
鍵FD以外に秘密鍵を渡さず、デモの公開合成seedを本番に使用しない。

## 検証の範囲
103試験: contract18/staging22/lifecycle19/socket19/restart25。11実SIGKILL境界。別process host/client、実監査一覧の多分割、provide元なしの既存復旧、未確認tail、誤署名、スコープ、容量、権限変更、応答不整合、明示retryを検証する。独立レビューではない。
復旧はread-only/applied=false。GUIは未実装。第三者peer間通信、実機、Rust/Automerge、本番資格、外部Pinを含む全体rollbackへの耐性は未確認。
