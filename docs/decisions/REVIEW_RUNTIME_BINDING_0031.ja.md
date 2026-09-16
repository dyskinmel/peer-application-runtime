# 00.31.00 実装者レビュー（独立レビューではない）

## 確認した境界
- 所有Storeを新しく開かず、既存の認可・署名・DB監査を実行した上で観測する。照会中のdump/total_changes不変を試験。
- operation IDの元本文・署名秘密鍵を要求しない。ローカルcacheとreceiptを同じ既存AEAD形式で開き、op/input/commit/generation/cache hashを照合。平文は表示用JSONへ出さない。
- 固定したapp/space/document/device外の操作はNOT_OBSERVED。見つからないことは処理失敗の証拠ではない。
- 別DB世代/別reader streamは明示的な再接続が必要。古いsequenceと、同じtokenで違う内容の観測を拒否。
- 入力・署名・Storeの検証成功と、CRDTへの意味検証/適用を分離。sharedCommit/sync/crdtApplyはfalse。
- 画面側は表示後の状態変化を再検査し、inspect-operationだけをread portへ渡す。共有書き込みはしない。
- 観測していない接続/複製をoffline/waitingとは表示しない。追加のNode負例と実描画検査で修正確認。
- 操作照会と権限更新の前後でもIME中の入力と選択を保持する。テストbridgeは合成ownerだけで、製品用IPCではない。

## 検出と是正
初回ブラウザー検査でテスト側のasync指定漏れを是正。その後に表示側の未翻訳reasonキーと、観測していない複製を待機中とする表示を検出した。後者はNodeの失敗するテストを追加してから修正。現在のブランド版/入口/実験台帳の不一致は既存の登録検査が拒否し、期待値を緩めず00.31へ整合させた。

## 残る境界
読み取り専用はAPIの効果範囲であり、OSの敵対コード隔離ではない。最初に所有Storeを開く処理には既存の世代/fence処理がある。保存領域全体の巻き戻し、JSONの暗号証明性、世界全体の最新性は保証しない。現在の文書投影はpending opaque envelopeのmetadataだけ。大規模監査は未測定、署名/DB監査は同期。実origin IndexedDB/HTTP/実IME/本番transportは未実証。

全体回帰と最終ZIPの照合は、固定ソースへ結び付いたrelease evidenceを正本とする。本レビュー文書自体はテスト成功や第三者承認の証拠ではない。
