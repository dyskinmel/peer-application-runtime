# 24 — 適合性・証跡・Production Ready判定

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 二つの品質を混ぜない

仕様の構造が整っていることと、製品が仕様を満たすことは別である。本bundleで実行するlint、JSON参照検査、SQL syntax、TS declaration typecheck、primitive KATは**仕様支援物の検査**。runtime実装、実ネットワーク、CDDL parser、組合せ暗号、実機UIの適合判定ではない。

`catalog/requirements.json`にMUST要件、`catalog/acceptance-tests.json`に正常/異常の受け入れ契約を置く。IDに対する実装pathがnullの間は未実装。文章上のpositive scenarioを実行結果と読み替えない。独立test IDが多いことより、脅威・状態遷移・失敗境界の網羅を重視する。

## 2. traceability chain

`requirement → spec clause → test contract → test implementation → execution → release claim`。

execution manifestはsource tree digest、spec+registry digest、dependency lock、toolchain executable/version、test corpus、platform hardware/OS、input seed、command、環境前提、開始/終了UTCとmonotonic duration、raw log digest、exit code、observation digest、resultを保持する。環境変数/secretは値を記録せず影響する設定のredacted digestを残す。

試験失敗と環境不足は別状態。`PASS / FAIL / BLOCKED / NOT_RUN / NOT_APPLICABLE`を使い、SKIPや空出力をPASSへ昇格しない。NOT_APPLICABLEは承認済みprofileが対象を除外した理由とreviewerが必要。FAILは後続のblockedで上書きしない。

## 3. release gate graph

G0契約/互換性、G1 local integrity、G2 two-peer、G3 opaque Keeperからのfresh recovery、G4 hostile network、G5 real Internet、G6 multihost/UI、G7 security closure、G8 resource/soak、G9 migration、G10 OSS RC、G11 qualified release。

G4/G7の準備は初日から行い、gate番号を安全性の後回しと解釈しない。後段の合格は前段の失敗を消さない。platform依存の結果は分離できるが、nativeだけ合格ならnative profileだけがrelease候補である。詳しい入口/出口/証拠は `plan/GATES.ja.md`。

## 4. M1と本番の違い

M1はG0–G3の条件を3台active構成とfresh authorized restoreで検証する最初の価値。単一processのsimulatorや同じディレクトリを共有する3processだけを実3台試験の証拠にしない。deterministic CIの後にhost隔離または実機で同じoracleを用いる。

M1達成は実用価値の核であるが、internet NAT、mobile resume、長期soak、独立review、upgrade/rollbackを通っていない段階で本番readyと表示しない。

## 5. 改変と再実行

source/spec/fixtureのdigest変更で影響gateをstaleにする。影響不明は保守的に未確認。migration/UIだけという変更でもport境界やclaimに触れれば関係gateを再試験。critical fixが以前のnegative controlを通過しない場合はreviewで原因を確定する。

test runnerにはdeliberate failing fixture、invalid UTF-8、missing dependency、wrong artifact hash、empty selection、malformed evidenceを入れて、検証器自身が失敗を見つけることを確認する。same test pass textを再利用しただけの結果を採用しない。

## 6. claim単位の完成

最終artifactには`qualified_profiles`, `guarantees`, `assumptions`, `exclusions`, `gate_evidence`, `known_risks`, `support_window`を含む。保証ごとに最新evidenceへの参照が必要。preserved old evidenceはhistoryであり現在版のPASSではない。release engineeringの署名がscientific/cryptographic correctnessを代行しない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-QUAL-001"></a>
### PAR-QUAL-001 — 追跡可能性
**MUST:** 全MUST要件に試験契約を対応させ、実装/実行/claimを別状態で管理する。
受け入れ: `AT-QUAL-001` / 最初の必須gate: `G0`。

<a id="PAR-QUAL-002"></a>
### PAR-QUAL-002 — 証跡binding
**MUST:** 実行結果を正確なsource/spec/toolchain/fixture/platformへbindingする。
受け入れ: `AT-QUAL-002` / 最初の必須gate: `G11`。

<a id="PAR-QUAL-003"></a>
### PAR-QUAL-003 — 結果の意味
**MUST:** FAIL/BLOCKED/NOT_RUN/NOT_APPLICABLEをPASSと区別し適用範囲を明記する。
受け入れ: `AT-QUAL-003` / 最初の必須gate: `G10`。

<a id="PAR-QUAL-004"></a>
### PAR-QUAL-004 — 初成功のoracle
**MUST:** M1は暗号/認可/operation集合/復元closure/外部無依存を検証する。
受け入れ: `AT-QUAL-004` / 最初の必須gate: `G3`。

<a id="PAR-QUAL-005"></a>
### PAR-QUAL-005 — 検証器の負例
**MUST:** validator/test runnerへ意図的な失敗入力を与え、偽PASS防止を確認する。
受け入れ: `AT-QUAL-005` / 最初の必須gate: `G0`。

<a id="PAR-QUAL-006"></a>
### PAR-QUAL-006 — claim gate
**MUST:** 全公表保証の累積gateが満たされたprofileだけをproduction-qualifiedとする。
受け入れ: `AT-QUAL-006` / 最初の必須gate: `G11`。
