# 00.01.00 → 00.02.00

原本をhistoryへ保存。新仕様の方が新しいという理由だけで互換を仮定しない。元版は未実装草案のため製品データmigrationは未実施。

| 項目 | 判断/変更 | 意味 |
|---|---|---|
| product境界 | 参加者主権・local-first・完全OSSを維持 | vendor依存ゼロのruntime経路を必須にする |
| control/epoch | sequenceとcontent epochを分離 | Keeper追加だけで文書全体の鍵/seedを再作成しない |
| authority | 正常移管の二署名を追加 | owner key不変を恒久制約にせず、forkは別問題として停止 |
| recovery | 事前認可B2を明示 | opaque Cが勝手に新ユーザー権限を発行する抜け道を除く |
| copy評価 | byte-completeとsemantic closureを分離 | Keeperのreceiptだけでは復元可能と数えない |
| causal validity | deps時点の検証/arrival-independent契約 | soft size超過を到着順の無効判定にしない |
| immutable hashes | seed/package/root/controlの生成順 | 暗号化結果を自分のAADへ参照する循環を避ける |
| lease/clock | reboot時期限不明の安全側保持 | 古いmonotonic期限を流用した不当GCを防ぐ |
| text/bindings | Unicode scalar+frontierを公開 | Swift/JS/Rustの文字offset差を隠さない |
| API | Result/operationID/unknown/cancelを型化 | timeoutを副作用失敗と断定しない |
| UI | headless Presenter/typed Command/tokens | visual polishをdomain/crypto/storageから分離 |
| production | G0–G11、149MUST/試験契約、claim evidence | 文書lintと製品適合を分離 |
| 成果状態 | normative candidate、未freeze | SDK実装・runtime試験・外部監査は0 |

前の発想を無条件に踏襲するのでなく、実装上の矛盾が生じやすい復旧資格・署名生成順・因果的妥当性を優先して見直した。新たな制約には解除条件/拡張経路を併記し、初期検証上限をプロダクトの恒久上限にしない。
