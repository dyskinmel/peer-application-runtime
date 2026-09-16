# Fresh independent reviewer向け依頼

対象: release/STATUS.jsonにあるsource commit/tree/digestのH0 candidate。
現在の第三者レビュー状態はNOT_RUN。本依頼書の存在は実施証拠ではありません。

履歴会話を判断根拠にせず、SPEC/AGENTS/PLANSとH0設計から再導出してください。
元仕様85ファイルの完全一致、149要件と43tasksの対応、実装/検証/本番依存の分離を確認。
登録checkとcase identity集合、artifact改変、stale source/environment、missing result、skip、timeout、scope/guard変更、checkpoint/restartの負例を再実行。
同一ユーザーの偽造、OS sandbox、network deny、独立approvalの非保証が隠されていないことを確認。
H0のPASSを製品G0〜G11へ誤って昇格していないこと、将来のproduct RED testがH0 bootstrapへ混入しないことを確認。

成果: 再現手順・file/line・severity・source bindingを持つfindingsと、実行/未実行の区別。
本レビューでproduct実装・policy変更・公開・外部環境の操作は許可していません。
