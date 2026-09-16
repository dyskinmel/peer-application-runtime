# 作成時の自己レビュー

これは作者側の文書レビューであり、独立セキュリティ監査ではない。構造validatorが安全性の全問題を発見するとは主張しない。

| 項目 | 発見/是正 | 状態 |
|---|---|---|
| control/epoch条件 | Keeper権限変更とcontent epoch更新を混同しないよう旧epoch write停止条件を限定 | 本文/MUST索引を一致 |
| Presence TTL | outer TTLだけでは署名対象と一致しないためactivity headerへ結合 | CDDL/意味契約を追加 |
| pre-auth ERROR | SpaceId=nullがHELLO/AUTHだけではエラー返却と矛盾。ERROR前認証経路を追加 | 文書/型を修正 |
| control生成順 | 初期SpaceIdを含むpackageとgenesisが循環しない順序を明示 | OBJECTSで定義 |
| storage FK順 | ledgerが未insert envelopeを参照する記述。envelope→ledger→outbox順へ修正 | 本文/DDL整合 |
| API例 | `.documents`と`.docs`、Resultのunwrap、readの状態型が不一致 | 宣言/例/本文を統一、typecheck実行 |
| error names | 文章上の旧名とregistry/型の差 | 安定codeを統一しlocal/RPC unknown写像を明記 |
| event/presence/RPC | message名だけでは暗号/再実行/cursor契約不足 | ACTIVITYと型を追加 |
| UI command | story内のactionがTS unionより多い | command registryに統合 |
| UI forbidden text | 「復元可能性は未確認」が禁止substring「復元可能」に一致 | 表現を曖昧でない文言へ変更 |
| primitive KAT | 公開Ed25519 signatureの転記でhex一文字過多 | RFC原典照合して修正、既存実装のKATで確認 |
| crypto completeness | primitive KATをPAR全体の検証と誤認し得る | 全出力にscope/未検証項目を明記 |
| support状態 | 文書参照数をruntime PASSと混同し得る | NOT_STARTED/NOT_RUNを維持するvalidator負例 |

## 未実施で残すレビュー

OD-01/02/03/04の実library境界、whole-protocol crypto vectors、independent CDDL conformance、組合せ安全性、各OSの物理durability、authority rollbackとgrant失効の実証、全UIflow、性能/soak、外部review。これらが残ることを、完成度やrelease gateで隠さない。
