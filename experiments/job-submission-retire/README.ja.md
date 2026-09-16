# Job submission retirement — 00.25.00 local candidate

## 目的と範囲
`RetiringSubmissions` は既存 `Submissions` の受信/登録を再利用し、登録用payloadだけを明示回収する。job本体、jobの管理承認、Keeper DB、保管期限を変更しない。job取消し、元管理署名の失効、物理空き容量保証、安全な消去ではない。

## 認可
`proposal(descriptor)` は読取り専用の照合材料（Keeper/store/job、descriptor/stage全文hash、payloadの存在/size/hash/dev/inode、直前承認hash）を返す。未知の相手から得たproposalを無条件に承認しない。
`contract.make_request(provider, operator_seed, origin_seed, revision=..., nonce=..., **proposal)` は現在のcontrollerと元descriptor作成者の二つの署名を作る。鍵が同じでも署名domainは別。`retire(request)` は現在のpolicyと両方の署名を検証する。旧鍵を失った場合の万能代理削除は未提供。

## 状態
- INTENT: 元の署名付きstage、正確な対象、両者の承認、登録済みjobの入力digestを署名付きsidecarへ永続化。payloadの予約量は維持。
- PAYLOAD_REMOVED: 対象だけをunlinkし、directory fsync済み。予約量はまだ維持。
- TOMBSTONED: 結果を永続化し、予約量を解除。元stage/sidecarは残る。全ての既存begin/chunk/progress/submit/reconcile/retry入口は旧descriptorを拒否する。

`retirement_status(job_id)` は別の読取りAPI。再起動では監査だけで、unlink、job登録、job選択を実行しない。同じ署名要求は同じ結果へ収束する。結果照合だけの再署名もしない。

## 結果不明と登録済みjob
INFLIGHTは回収拒否。`reconcile_registration(request)` を明示実行して、署名済みjob台帳と入力を照合する。このAPIは登録/再試行を実行しない。既存jobが一致すればREGISTERED、存在しなければRETRY_READYへ観測を保存する。状態が変わるため、改めてproposalと承認を作る。現在の管理署名が失効していても登録を新たに許可するのではなく、元作成者と現在controllerの二者承認で観測だけを行う。

REGISTEREDのpayload削除後は、job台帳のcommand/archiveから元のpayloadを再構成し、全体hash/size/対象状態/intentを照合する。jobの状態がQUEUED→SUCCEEDED/CANCELLEDへ進んでも同じ入力ならよい。jobの欠落・差替えは拒否する。jobは自動選択/取消しされない。

## 再承認
途中でcontroller key/revisionが変わると旧要求では停止。`proposal()` は固定済み対象を返す。元作成者と新controllerが署名し、`rebind(request)`で前の承認hashへ結ぶ。最大8承認、revisionは厳密増加。rebind自体はpayload削除をしない。削除後の段階でも対象を変えず続行できる。

## 形式・容量・互換
CONFIGはschema2。32件/64MiBの既存上限は維持するが、TOMBSTONEDだけはpayload予約sumから除外する。record枠は返さない。sidecarは最大64KiB、8承認、未確認tempは別途上限あり。宣言payloadの予約量と、観測済み削除対象bytesを別で返す。DB/WALやjob内の元archiveは残る。
形式1は`migrate_legacy=True`で明示移行。旧形式の全件検証とCONFIG置換を同じ排他ロック下で行う。旧ホストはschema2を拒否する。`RetiringSubmissionHost`と`tools/keeper_retiring_submit_host.py`はschema2を利用でき、既存登録client/serverをそのまま再利用する。退避/再承認APIをリモート公開する新methodは追加しない。

## 外部Pin
`pin()` と `verify_pin()`/起動時`expected_pin`は既知record集合、descriptor、stage連番、回収段階、承認prefixを照合する。未記録tempから成功を推定しない。Pinと保存領域を同時に巻き戻す行為、同一UIDの任意コード、物理媒体故障に対する保証ではない。

## 実行
```
python3 tools/check_submit_retire.py
python3 examples/submit_retire_demo.py
python3 tools/keeper_retiring_submit_host.py --help
```
82 tests = contract10 + lifecycle13 + audit25 + restart24 + host8 + process2。restart24は全て実子process SIGKILL。旧library実験opt-in、合成鍵、一時dirだけで実行。実機電源断や独立レビューとは異なる。特定のライブラリbinaryは同梱しない。

## 残る境界
受付記録のGC/世代閉鎖、元鍵紛失時の復旧、リモート回収承認、大規模性能、Rust・Automerge・実機検証は別作業。検証不能を理由に無関係なlocal実装を止めない。
