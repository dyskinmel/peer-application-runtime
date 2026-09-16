# 00.12.00 self-review and release boundaries

独立した第三者reviewは未実施。この文書は実装者の自己レビューです。

## 修正した再現可能な問題
- 保管確認の世代を進めた後、過去renewal operation行が欠けても再openを許した。現在はreservation一件、receipt世代1..Nの連続集合、seal一件、release状態、現在receiptと操作応答の一致を検査する。DB全体の整合した巻き戻し検出ではない。
- 同じ要求の再試行で、改変されたcached receiptを検証せず返した。署名・grant・request・lease・現在のreceiptとの対応を再検証して返す。
- SQLITE_FULL試験の初期入力が既存の空きpageに収まり故障を発生させなかった。実page上限で正規予約を続け、SQLITE_FULLを実測してfailed transactionの行・容量不変を確認する試験へ修正。
- fsync故障試験は初期directory作成で故障していた。対象directoryを先に作り、ファイル公開の実fsync境界へ注入するよう修正。

## 登録・進捗期待値の更新
Keeper候補を追加し、KEEPER-GC-LOCALを計画に登録したため全tasksは52→53。旧recovery登録試験のKeeper未実装期待値を候補実装へ変更。旧Store登録試験の正確なtask件数を53へ変更。149要件の一意ownerと製品gate未昇格のassertionは維持。既存テストを削除・skip・件数だけで成功にする変更はない。H0へ12件のKeeper登録試験を追加。

## 保留と保護条件
public fixtureのみの実験。providerの通常拒否は維持。Keeperは内容を復号せず、current authorityはtrusted host由来。失効はknown-head更新であり、wallclock期限のないcapabilityやexact read replayを秘密にしない。失敗した未ack更新の永続記憶は保証しない。no auto-GC/no quota refund/no native or CRDT qualification。reopenは構造・署名・対応を検査し、全現在バイトはreceipt/renew/read/observation時に確認する。

## 配布で確認すること
各local laneの正確なテスト集合、source/guard/environment/log/checkpoint、baseline85files、tasks53/requirements149、fresh bundle、fresh ZIP、前後manifest一致、zip再生成一致。確認結果はrelease/STATUS.jsonおよび外側verification sidecarへ、実行後に記録する。
