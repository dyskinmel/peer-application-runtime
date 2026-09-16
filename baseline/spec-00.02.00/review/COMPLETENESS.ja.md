# 仕様の完成度 — 00.02.00

## 結論

**最初の成功条件から本番運用・OSS公開までを一貫して扱う、詳細な規範候補仕様を作成した段階。** 企画の説明だけではなく、実装境界、入出力、失敗の意味、UI契約、受け入れ条件、release判断へ分解されている。別実装で相互運用できる凍結protocol、実測済み性能、完成SDKではない。

## 数えられる完成範囲

| 対象 | 今回の内容 | 状態 |
|---|---:|---|
| 領域別詳細仕様 | 25文書 | 全25領域に候補本文とMUSTあり |
| 追跡するMUST要件 | 149件 | spec clauseと受け入れ契約に対応 |
| 製品acceptance contract | 149件 | 正常149/異常149のシナリオ、実行0 |
| wire message registry | 26種類 | CDDL型・frame discriminant候補あり |
| production gate | G0–G11の12段階 | 入口/出口/依存/証跡を定義、実行0 |
| 実装work package | 16件 | 対象file境界/入出力/独立oracle/停止条件 |
| UI semantic fixture | 24状態 | 状態・action・禁止表示。実UI未作成 |
| token seed | 51 tokens | base/semantic/component、theme分離 |
| freeze前の実験/レビュー | 11件 | gate/担当role/終了条件/未達方針あり |

149/149の参照がそろうことは**管理するMUSTの追跡網羅率**であり、製品保証を証明した割合ではない。見落とした要件がないこと、暗号が安全なこと、実装が正しいことは別レビュー・試験で判断する。

## 成熟度

L0=アイデア、L1=構造と到達点、L2=具体的な規範候補/試験契約、L3=実装probeと独立codecで凍結、L4=対象profileの本番証拠閉包。

**本仕様全体はL2。** wire/API/SQL等の支援物には構文や型の確認を加えたが、それだけでL3/G0全体に昇格させない。成熟度の4段階を線形の工数率へ換算しないため、根拠の薄い「95%完成」のような単一比率は使用しない。

| 領域 | 詳細化の到達点 | 残ること |
|---|---|---|
| 製品/architecture/保証 | 不変条件・提供範囲・役割・portsを記述 | 実装で不要な境界/不足境界を検証 |
| identity/auth/crypto | 鍵分離、control/epoch、移管、AAD/KDF/署名対象候補 | composed vectors、strictness、独立review |
| wire/data/sync | CDDL、code、limits、causal妥当性、state machine | CDDL parser/別codec/Automerge adapter実行 |
| storage/replication/recovery | transaction、closure、lease、GC、M1 oracle | 実ストア障害・電源断class・fresh restore |
| SDK/platform | typed Result/取消し/Unicode/host能力 | 実binding/OS最低版/実機lifecycle |
| UX/Polish | 画面構造・状態・部品・tokens・不変条件 | visual選定、component実装、利用者/a11y試験 |
| production/OSS | security/soak/migration/release/support gate | 実測・独立担当・運用演習・公開 |

## 今回実行した検査の意味

`evidence/`に実際の構造検査、validator負例、SQLite DDL/constraint、TypeScript型、公開primitive KATの結果を保存する。これらは仕様資料と支援物の検査。製品acceptance149件、実ネットワーク、端末・UI、独立暗号レビュー、全PAR crypto vectorsはNOT_RUN。

本packageに含むPythonは仕様支援検査であり、PARランタイム実装量へ加算しない。製品実装0、製品runtime試験0、独立security review0、公開repo/registry release0。

## 次の最短経路

仕様の説明をさらに際限なく増やすより、WP-01/OD-01〜04で曖昧さとlibrary境界を実測し、wire/crypto/storageをfreezeする。その後G1→G2→G3のM1を実装する。以後のgate/拡張はこの体系に沿って更新する。

## 実行結果の要約

仕様構造検査: PASS。検証器自身のbaseline＋負例13件: PASS。SQLite候補24tableの構文と4種類のconstraint拒否: PASS。TypeScript宣言/例のstrict型検査: PASS。公開primitiveの6確認: PASS。wireサンプル11件はhex形式と正例frame長だけ確認。CDDL parser適合、PAR暗号組合せ、製品runtime、実機UIは未実施。rawログはevidence/EXECUTION_SUMMARY.jsonから辿れる。
