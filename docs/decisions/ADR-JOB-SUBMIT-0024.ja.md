# ADR-0024: 登録を選択・実行から分離した私有ジョブ受付

## 決定
ControlledHostの3経路は変更せず、第4の私有socketを合成する。control keyは「登録してよい運用者」を示し、Space管理者の署名を代行しない。登録対象は既存retire/close/compact/openのみ。大きなcommand/archiveは署名付きdescriptorでhash/size/job ID/対象状態/受信者を固定し、32KiB断片で受信する。
contextはkeeper署名付き応答として現在の対象digestを返す。クライアントは別途信頼したKeeper/store/controller revisionをpinする。このdigestは世界全体の最新性を証明せず、知っているローカル状態への明示的束縛である。

## 永続化と再試行
確認済みprefixはpayload fsync・ディレクトリ同期の後で署名付きstage記録へ保存。未確認tailは明示chunk時にだけ切り戻せる。確認済みの破損は拒否。
登録は入力・現在対象・管理承認・job journal予算を確認し、INFLIGHTを同期してからManagementJobs.submitを呼ぶ。REGISTEREDはjob登録済みであり管理効果の完了ではない。初期状態はQUEUEDでselectは呼ばない。
INFLIGHT後の応答紛失はreconcileが実jobの入力・元対象digestを照合する。未登録ならRETRY_READYを返し、retryを明示要求。再起動・progressは自動dispatchしない。既存jobがCANCELLED/SUCCEEDEDでも、再登録で初期化しない。
2つのjournalをまたぐ原子性は主張しない。署名付きstageを持っていても、REGISTEREDは実jobの存在・入力との一致を改めて確認する。

## 予算と限界
32 stage/64MiB宣言payload、1payload最大16MiB+512KiB+12、job側32件/64MiBを維持。stageの予約はjob枠の予約保証ではない。job予算はsubmit直前・実submit双方で確認する。他の登録で枠が尽きたら新しいjobを作らず拒否。
受信済みpayloadとreceiptは保持し、GC/失効後の再承認/秘密の消去は未提供。署名済み管理資料に秘密鍵を含めてはならない。物理ディスク全体/RSS/無期限運用の上限を保証する数値ではない。
上限内の全件監査とprefix再読込を行うので大きな入力の性能最適化は別課題。1段階の同期I/Oをソケットdeadlineで強制停止しない。

## レビューで修正した問題
- 応答型の取り違えでKeyErrorを返し、またcontext応答のcontroller revisionをhelloと照合していなかった。負例→strict response bindingへ修正。
- 登録開始前のfsync失敗が生のOSErrorになっていた。SUBMIT_JOURNAL_UNCERTAINとして停止・再openを要求。
- client.stageが不正な進捗応答で無進捗ループ/飛び越しを許す。各ackを送信した断片長と厳密照合しSUBMIT_PROGRESSで停止。

## 外部資料と出典の限界
Python os: https://docs.python.org/3/library/os.html
SQLite WAL: https://www.sqlite.org/wal.html
参照日2026-09-06。OS APIの説明を参照しただけで本候補の安全性が認定されるわけではない。Linux合成データでの局所試験のみ。既存SQLite/libsodiumの旧版許可は実験限定。Rust/Automerge/実機/独立監査は未実施。
