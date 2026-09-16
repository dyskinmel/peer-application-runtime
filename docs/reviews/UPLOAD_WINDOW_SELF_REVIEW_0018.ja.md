# 00.18.00 自己レビューと判定境界

これは同じ作成者によるレビューであり、独立評価ではない。

## 確認と修正
- 正式なREDはred-contract-2で確認。最初の実行にはfixtureのstage名衝突があり、その例外を製品の意図した失敗とは数えない。
- 監査archiveが既存wire codecの1MiB上限を超えることを確認し、wire上限を緩めずlocal framingを分離した。600件の合成terminal記録の正当な1MiB超archiveを試験。
- 受付拒否後のbinding漏れを再現し、payload/record/lease/audit予算を永続化前に検証するよう修正。境界直前にも再確認する。
- begin ACK前のbindingだけが残り、upload権限が失効したケースへ、現在の限定的な中止許可で解決する経路を追加。Keeperは変更しない。
- archiveの欠落、署名済みだが不整合な集合、すり替え、途中削除、外部pinと旧要求拒否を正/負試験で確認。
- 28ケースの所有する子プロセスへのSIGKILLはpower-loss/媒体故障の試験と別に記録。
- H0の既存版番号・次作業の期待値のみ新しい作業集合へ更新。既存コンポーネントの非保証・未認定範囲を維持。

## 意図的に残す境界
新規schema3 rootの協調単一owner用であり、old rootのin-place移行、未対応IPC host、公開ネットワーク、秘密管理、同UIDの敵対的コード、unpinned full-store rollbackへの耐性は主張しない。CLOSEDは既にcommitした固定metadata整理の承認であり、その後に権限が変わっても同じ集合のcompactだけを完了できる。新世代のgrantには現在issuerを要求する。

active record枠を解放しても監査bytesはarchiveへ移る。64世代/64MiBの上限を外さず、先に将来archive予算を予約する。物理空き容量や無期限運用を約束しない。

## 証拠
新規118件とH0265件の候補試験を実施。最終sourceおよび完成ZIPの全16レーンの結果、正確なcase ID集合、source/environment digestはrelease/STATUS.json、release/evidence/00.18.00、ZIP外のverification.jsonで確認する。実行されていない実機・独立レビュー・製品Gateを昇格しない。

最終の追加負例で、正当な署名を持つarchiveのgeneration=Trueと、CLEANED receiptのfalse欄=0を受理するPythonの型比較の緩さを確認。strict-types-redで2件失敗を記録し、整数/真偽値の厳密検証を追加した。前の全16レーンPASSは旧sourceとして保存し、修正後の全レーンを改めて実行する。
