# 00.08.00 自己レビュー記録

レビュー種別: 同一作成者による差分・異常系・試験レビュー。独立reviewではない。

## 確認した論点
- authority headの確認とdata commitを別DB/別transactionにしていない。Cryptoのnonce発行は巻戻し不可として先行し、候補が失効しても予約を消さない。
- revision/fence/material/stateの照合をtransaction開始後とCOMMIT直前に行う。raw commit APIを無認可で公開しない。同一processの任意コード実行に対する境界とは主張しない。
- signed fork/invalid membershipをエラーだけで捨てず永続化して停止する。不正署名だけでforkを作らない。
- 本文/secret鍵をauthority tableへ保存せず、encrypted material/key fingerprintを保存する。公開権限metadataは匿名化しない。
- 旧DBの移行を明示化し、nonempty legacyに新しい認可を後付けしたことにしない。
- data retryと新規writeを分ける。read-only restoreを通常restartと分ける。
- 旧Store163/crypto173/auth188/wire262の回帰を元ケース集合で再実行した。H0には今回12件の登録検査を追加し、次作業の状態と旧『未統合』断言を変更した。

## 実際に見つけて修正した問題
1. 正当なcontrolの保存失敗後、旧ACTIVEでwriteできた。必要なreplay digestを持つfailure latchを追加し、古いcontrol再送や旧epoch再activationでは解除させない。
2. 上記latchがCOMMIT成功後の応答欠落でも残り、exact retryで回復できなかった。保存済みtarget digestとの一致を条件に再照合を可能にした。
3. 構造的には正しいが認可履歴が無効なsnapshotが公開されてから拒否された。stagingで署名履歴と対応関係を検査してからdestinationを公開するよう変更した。

失敗ログは `release/evidence/00.08.00/development/`。REDの一部は初期の欠落モジュール/登録fileの検出であり、セキュリティ攻撃成功の測定ではない。上記3項目は実際の挙動を再現する試験で確認している。

## 明示した未完了境界
1,024control/900,000-byte material等は局所的入力制限。大きなSpace/材料の性能・GCは未評価。`pending(limit)`は検証済み候補の限定スライスを認可でfilterする補助であり、Space間公平性や完全配送を保証するschedulerではない。後続のBlob/配送queue作業でscopeを別途確定する。

未確認controlをローカル書込み失敗後のcrashから必ず思い出すことは保証しない。入力側のdurable retryが必要。全DBrollbackは外部pinなしには検出不能。Rust/Automerge/OS vault/physical power-loss/新provider認定/独立reviewは未実施。製品gateはNOT_RUNのまま。
