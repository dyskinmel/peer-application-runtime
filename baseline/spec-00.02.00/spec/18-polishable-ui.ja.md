# 18 — Polish可能なUI構造・デザインシステム

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. UIの5層

`Domain → Presenter → Interaction primitives → Components → Theme/Layout`。

Domainは認可・保存・復旧の正本。Presenterはimmutable ViewModelとtyped Commandを供給。Interaction primitivesはfocus/keyboard/selection/confirmの挙動。Componentsは情報の組合せ。Theme/Layoutは色、余白、書体、角丸、動き、配置を扱う。

Polishで変更する範囲を最後の二層へ寄せる。presentation layerからDBやnetworkへ直接アクセスしない。rendererは`vm`と`dispatch(command)`を受け取り、同じfixtureで独立に検討できる。

## 2. view contract

全ViewModelはschema version、revision、snapshot time、data scope、capabilities、actions、pending operation IDsを含む。actionにはenabled、disabled reason、required confirmation、target revisionを持つ。disabled buttonの理由をtooltipだけに隠さない。

状態の優先順位はdomain側の原因codeから決定する。visual themeが`protected`を`success`へ勝手に変換して「未確認」を消すことはできない。コピー数と現在接続数は別field。

## 3. design tokens

primitive→semantic→componentの3段階。primitiveはspacing/type/motion/shape/color scale。semanticはsurface/text/border/focus/critical/warning/information/protection等。component tokenは用途を示すaliasで、全画面に独立hex値を埋め込まない。

DTCG Format 2025.10を交換形式の候補にする。これはDesign Tokens Community Groupの仕様でありW3C標準と誤記しない。[S17] 同梱token seedは暫定値で、ブランドの最終決定でもcontrast合格済みでもない。

`tokens/base.tokens.json`はbrand-neutralな寸法/動き、`tokens/semantic.tokens.json`は暫定の意味付きpalette。light/dark/high-contrast、compact/comfortable、reduced motionを同じsemantic keyで解決する。Web CSS、Swift、Composeへの変換は後続のgeneratorで行う。

## 4. component anatomy

| component | 固定する意味 | Polishで変えてよいもの |
|---|---|---|
| ProtectionStatus | local/retained/freshness/root | badge形、配置、詳細panelの幅 |
| InviteReview | 対象key/role/Space/権限影響 | stepper、文言の長さ、カード表現 |
| RecoveryProgress | fetch/verify/rebuild/activate | progress可視化、余白、animation |
| ConflictInspector | 全競合値と出典、元draftの保持 | split/stack表示、diff装飾 |
| ContributionPanel | consent/上限/強制停止の影響 | slider/数値入力、layout |
| DiagnosticsPanel | redaction/時点/原因code | table/cards、検索、グループ化 |

UI kitのslotでhost固有ヘッダーやnavigationを差し替え可能にする。必須安全情報のslotを空にした場合はconformance違反となる。ブランド変更で保護statusを消せない。

## 5. screen statesとfixture-first

各主要surfaceについてempty/loading/ready/degraded/offline/unauthorized/rebase/fork/storage-full/recovery-partialをfixture化する。`ui/stories.json`は状態、利用可能action、禁止表示を記録する。ネットワークを動かさずにcomponent galleryを表示できる構造。

fixtureはmock backend成功の証拠ではない。UIの描画/interactionを検証する入力であり、同じ状態はintegration traceからも再生して一致させる。

## 6. visual regressionとbehavior regression

reference screenshotsはtheme、locale、viewport、DPR、font environmentを固定する。theme変更PRではスクリーンショット差分とaccessibility tree差分を別レビュー。誤差thresholdで重要文言の欠落を見逃さない。

Polishの完了条件は、domain/crypto/storage/wireを変更せず、同じcommand traceが同じ結果へ達し、required status/confirmationが残り、accessibilityが後退しないこと。必要なdomain変更が見つかれば別PR/ADRへ分離する。

## 7. 応答性

local typingとfocusはnetworkに依存しない。重いdiff、history、graphはvirtualization/workerを使い、UI threadにcryptoや全履歴のdecodeを載せない。animationは状態遷移の意味を補助し、データ保護の達成を先取りしない。

## 8. デザイナーへの引継ぎ

提供物はIA、component anatomy、state matrix、token contract、interaction contract、microcopy catalog、source fixture、accessibility checklist、画面ごとのacceptance criteria。画像モックだけを正本にしない。本packageに最終visual mockやpixel-perfect UI実装は含まない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-DS-001"></a>
### PAR-DS-001 — 層分離
**MUST:** rendererはViewModelとtyped commandにだけ依存し、network/storage/cryptoを直接呼ばない。
受け入れ: `AT-DS-001` / 最初の必須gate: `G6`。

<a id="PAR-DS-002"></a>
### PAR-DS-002 — tokens契約
**MUST:** visual値をprimitive/semantic/component tokenへ分離し、意味付きaliasを保つ。
受け入れ: `AT-DS-002` / 最初の必須gate: `G6`。

<a id="PAR-DS-003"></a>
### PAR-DS-003 — 状態fixture
**MUST:** 主要surfaceの正常/空/失敗/権限/復旧状態をオフラインfixtureで再現する。
受け入れ: `AT-DS-003` / 最初の必須gate: `G6`。

<a id="PAR-DS-004"></a>
### PAR-DS-004 — Polish不変条件
**MUST:** 見た目変更後もcommand意味、保護状態、確認、アクセシビリティを維持する。
受け入れ: `AT-DS-004` / 最初の必須gate: `G6`。

<a id="PAR-DS-005"></a>
### PAR-DS-005 — localeと動き
**MUST:** 文字拡大・RTL・reduced motion・high contrastで同じ操作を提供する。
受け入れ: `AT-DS-005` / 最初の必須gate: `G6`。

<a id="PAR-DS-006"></a>
### PAR-DS-006 — VM鮮度
**MUST:** ViewModelにrevisionとaction可否理由を持ち、古い画面からのcommandは再検証する。
受け入れ: `AT-DS-006` / 最初の必須gate: `G6`。
