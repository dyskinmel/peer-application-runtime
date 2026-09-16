# 私有の管理ジョブ制御 / 00.23.00

`host-job-control-local-v1` はLinuxの別の私有Unix socketを使い、事前登録済みjobのstatus/select/cancel/reconcile/retryだけを受け付ける局所候補。既存read/upload/scheduler/job実装を改変せず合成する。新規job payload・任意method・shell・URLは受け付けず、管理承認を生成しない。

## 信頼と鍵
信頼済みのoperatorがcontroller公開鍵と正整数revisionを明示設定する。これはSpace管理鍵ではなく「すでに承認済みjobを操作する運用鍵」。job本体の署名・認可・対象検査はManagementJobsが再度行う。UIDだけでは制御を許可しない。
Keeper署名helloはKeeper/store/controller/revision/boot/challenge/deadline/limitsに結合。controllerは安定intentとhelloへのwrapperを別domainで署名。Keeperはhello+requestに結合した応答を署名する。各接続1要求。再接続は新helloだがintent/operation IDは同じものを使う。
`Controller.replace_controller(public_or_none, newer_revision)`は信頼済みowner thread専用API。状態を署名・永続化し、旧接続の未送信応答と旧intentを拒否する。再起動の設定は保存済み最終public/revisionと一致必須。control IPCで鍵を追加/失効できない。送信済みbytesは回収不能。

## 状態と再試行
statusは永続operation枠を消費せず、現job状態/host活動数/照合Pinを返す。select/cancel/reconcile/retryは128件までの署名付き受付記録へ保存。
1. INFLIGHTを同期してからschedulerへdispatch。
2. 受付結果を保存。ACCEPTEDは「control操作の受付」でありjob成功ではない。
3. 同じID+同じintentは過去の受付結果と現在のjob状態を返す。ID差し替えはCONTROL_CONFLICT。
4. INFLIGHTのまま再起動した要求はOUTCOME_UNKNOWN。自動dispatchしない。job statusを確認し、新しい明示操作で照合/再試行する。
5. 応答を失った後の再接続でも同じintentを送る。CLIはmutationに必ず--operation-idを要求する。

selectionはschedulerのメモリー状態なので、ACCEPTED後に再起動しても自動再選択されない。歴史的ACCEPTEDと現在QUEUEDの組合せは矛盾ではない。cancelは署名権限の失効でも他の操作のundoでもない。
制御受付記録・job journal・管理対象は別の永続化境界。exactly-onceや単一transactionを主張しない。保存結果不明・内容不整合なら受付を止め、再open/照合を要求する。処理開始後に表示用データの生成が失敗しても「拒否」と偽らず結果不明を返す。

## event loop
`ControlledHost` は control poll →既存ScheduledHost.tick→control poll の順で動作。同じ所有threadで全状態変更を行う。control接続はdata drainに数えない。dataの両selectorとKeeper reader pinsは既存BoundActivityが実測する。制御だけが接続中でも自己待機せず、dataが活動中ならeffectを始めない。
同期的な署名/DB/管理処理中は同じthreadのcontrolも止まる。即時cancel、preemption、固定応答時間の保証はしない。

## 上限
control接続既定4/最大8、要求16 KiB、応答64 KiB、hello4 KiB、単一intent2 KiB。固定I/O期限50ms〜30s、既定5s。1pollに受理する接続数も制限。記録128件、各8KiB、policy更新32件、未確認temp合計16KiB。記録の自動GCはなし。枠が満杯でもstatus/重複照会は可能だが、新規mutationは拒否。論理上限はfilesystem/RSS全体の上限ではない。

## Pinと再開
statusにjobs_pinとcontrol_pinをhexのCBORとして返す。別の信頼する場所へ保存し、再open時にexpected_jobs_pin/expected_control_pinを渡せる。CLIは--jobs-pin-file/--control-pin-fileで0600のCBOR fileを読み込む。
既知job/operationの消失、terminal結果の差し替え、既知policy履歴からの巻き戻りを拒否。Pinなしの再起動で整合した全領域rollbackを完全検出するものではなく、Pinも同時にrollbackされた場合は対象外。

## コマンド
```
python3 tools/check_job_control.py
python3 examples/job_control_demo.py
python3 tools/keeper_control_host.py --help
python3 tools/keeper_control_client.py --help
```
hostは既存私有config/DB/schema3 spool/jobsを必要とする。自動移行しない。controller public/revisionに秘密はなく、Keeper/owner秘密鍵はそれぞれFDから読み込む。legacy libsodium許可は明示フラグのみ。ソケットを自動探索しない。

## 検証と限界
88試験: contract20/lifecycle24/socket17/restart16/hardening11。5 SIGKILL境界。実別processのhost/client、dataとの併走、復旧、UID・署名・key revocation・最大長・重複ID・capacity・Pin・再署名禁止を含む。自己レビューであり独立第三者レビューではない。
署名の公開テストseedは合成資料。local IPCでtransport暗号は追加していない。同一UID任意code、物理power-loss、Windows/macOS、Rust/Automerge、本番SLA・資格は未検証。復旧は依然read-only/applied=false。UIは型付き状態を返すだけで画面はない。
