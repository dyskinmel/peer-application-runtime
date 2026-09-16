# 20 — 脅威モデル・安全性評価・検証責務

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 信頼境界

安全性対象は、暗号化保存、正当な編集の認可、同一署名operationの同一性、資源制限、正確な保証表示、更新/復旧時の権限維持。端末OSの完全侵害、正規readerによる平文再配布、authority自身の悪意ある正規決定、全networkの永続遮断は防げると主張しない。それでも検出できるfork・不正形式・署名不一致・虚偽保管は隔離・観測する。

| actor/境界 | 攻撃例 | 検査と残余リスク |
|---|---|---|
| unauthenticated network | 大量接続、巨大frame、replay | pre-auth quota/timeout、transcript、allocation前上限。回線自体の飽和は残る |
| authorized editor | actor詐称、sequence fork、病的CRDT | inner/outer検証、因果依存検証、隔離、work budget。有効だが悪意ある文章は防がない |
| opaque Keeper | 嘘のreceipt、欠損、古いroot | scope署名、root閉包、実取得、freshness。保管の未来保証はできない |
| Relay | traffic観測、遅延、切断 | E2EE、時間制限、代替経路。通信metadata秘匿ではない |
| UI/host | XSS、誤ったconfirm、secret logging | narrow ports、revision guard、redaction、CSP。browser origin侵害は鍵利用を許し得る[S21] |
| contributor/build | 悪意ある依存・release差替え | review、pin、provenance、署名、独立再ビルド[S18] |
| storage/clock | rollback、clone、bitflip、clock巻戻り | actor再生成、known-head pin、hash、期限不確実状態。全履歴喪失後の世界最新性は不明 |

## 2. 攻撃面を減らす境界

未認可処理は短い形式検査とcrypto/transport認証のみ。privateSpace存在確認を返さず、同じclassのerrorへ正規化する。RPCはregistered handlerかつpayload schema許可済み。ネットワークから任意URL fetch、shell、module installを起動しない。parserはbinary limitに加え、展開量・依存深度・aggregate object数の予算を持つ。

危険な同期/復旧入力は可能なhostでprocess隔離する。単一スレッドのtimeoutだけで暴走parserを強制停止できるとは保証しない。iOS等の隔離制約があるprofileでは、前処理、bounded parser、差分fuzz、memory/timeの実機測定をrelease条件にする。

## 3. assurance workstreams

A: protocol design review — auth/epoch/crypto transcript/rollback/recovery。B: implementation review — unsafe/FFI、key lifetime、DB原子性、browser origin。C: fuzz — frame/CDDL boundary、CBOR、Automerge adapter、export、membership/epoch model。D: property/model — convergent valid operation sets、no authorization bypass、GC reachability、receipt≠semantic restore。E: operational adversarial trials — stolen kit、partial restore、untrusted relay/keeper、signed malicious editor。

全fuzz targetは入力上限、oracle、seed corpus、artifact retention、timeout/crash分類を記録する。release candidateでは各外部入力targetに累計24 CPU-hour以上という**初期campaign最低条件案**を設定する。実行時間やcoverageの数値だけを十分性の証明にしない。未解決crash/hang、sanitizer error、unbounded amplificationはrelease blocker。

## 4. レビューの受入れ

独立reviewerは設計/実装作者以外。第三者が利用可能な予算・契約は未手配であり実施済みとしない。scopeはcommit、spec digest、suite/feature flags、平台、攻撃者modelで固定。findingごとに再現、重大度、修正差分、negative regression、独立retestを残す。修正により影響する既存gateは再実行する。

公表した保証を破るCritical/Highおよび未分類security findingは、対応するprofileのreleaseを停止。Medium/Lowもowner、期限、残余リスク、公開範囲を記録する。単に分類を下げたりscopeから消すことで合格にしない。NIST SSDFのfinal文書を工程の参考にするが認証取得と称さない。[S20]

## 5. security disclosure

公開SECURITY.mdにsupported releases、private報告先、受領確認目標、緊急回避策、advisory、CVE取得を含む手順を置く。提案目標は3営業日以内の受領確認、7日以内の一次評価。運営体制が目標を維持できることをG10で確認し、未整備の窓口を公開済みとしない。PoCの秘密や利用者データをpublic issueへ誘導しない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-SEC-001"></a>
### PAR-SEC-001 — 脅威の網羅
**MUST:** 各trust boundaryに攻撃、制御、残余リスク、検証IDを対応付ける。
受け入れ: `AT-SEC-001` / 最初の必須gate: `G0`。

<a id="PAR-SEC-002"></a>
### PAR-SEC-002 — 悪意あるeditor
**MUST:** 署名が有効でもactor/deps/seq/schemaと資源境界を検証する。
受け入れ: `AT-SEC-002` / 最初の必須gate: `G4`。

<a id="PAR-SEC-003"></a>
### PAR-SEC-003 — fuzz evidence
**MUST:** 公開入力ごとのfuzzとモデル試験をsource/corpus/toolchainへbindingする。
受け入れ: `AT-SEC-003` / 最初の必須gate: `G7`。

<a id="PAR-SEC-004"></a>
### PAR-SEC-004 — 独立review
**MUST:** 公開profileのcrypto/auth/recoveryは独立reviewと修正retestを必要とする。
受け入れ: `AT-SEC-004` / 最初の必須gate: `G7`。

<a id="PAR-SEC-005"></a>
### PAR-SEC-005 — 未解決リスク
**MUST:** Critical/High/未分類security findingがある対象profileをreleaseしない。
受け入れ: `AT-SEC-005` / 最初の必須gate: `G11`。

<a id="PAR-SEC-006"></a>
### PAR-SEC-006 — disclosure
**MUST:** 稼働するprivate報告窓口とsupported versionsを公開し運用演習する。
受け入れ: `AT-SEC-006` / 最初の必須gate: `G10`。
