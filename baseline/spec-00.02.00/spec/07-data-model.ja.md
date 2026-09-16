# 07 — 文書・スキーマ・検索・イベント・RPC

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 型とschema

Spaceはimmutable SchemaManifestをcontent hashで固定する。field typeはregister、text、list、map、counter、blob-ref。null/absentを区別し、opaque JSON全置換を共同編集textと同一に扱わない。decimal値は正規化済みdecimal stringで表現し、binary floatを金額の契約に使わない。

正当な操作の判定は、署名者、declared causal dependencies、固定schemaに基づく。受信側の「今見えている全体状態」をvalidation入力にすると配送順で受理集合が変わり得るため、そうしない。

## 2. hard validityとsoft policy

hard validityはencoding、署名、権限、actor/seq、dependency relation、許可されたfield/operation type、change単体のbytes/ops上限。soft policyは文書の長さ、現時点の見た目、業務ルール、端末容量。

各peerで有効だった同時追加をmergeすると、推奨文書サイズを超えることがある。この場合、片方の操作を到着順で捨てず `policy-conflicted` または `resource-blocked` を返す。raw履歴を保ち、より大きいprofile/端末で開く、分割、新checkpointという解決経路を提供する。

counterは整数の操作。選んだCRDT実装の数値範囲を越えたときに暗黙wrap・float変換をしない。deterministic overflow状態として履歴を保ち、表示・再構成の契約を共通fixtureで固定する。

## 3. 文書lifecycle

`unknown-local → known-unfetched → materialized → tombstoned`を区別。隔離、rebase候補、resource-blockedは別軸。文書IDは乱数で、同じタイトルが二つあってよい。文書の一意名はアプリが別途解決する。

同一epochの有効DocumentTombstoneは同時updateより優先。tombstoneのfield編集は禁止。復元は新DocumentIdを作り、元IDとの由来だけ記録する。要素削除と文書全体の削除は別操作。

## 4. text、カーソル、undo

外部SDKのindex指定は`unicode-scalar`と対象frontierを必須にする。UTF-16 code unitやgrapheme数からの変換はbinding側の明示adapter。孤立surrogate、scalar途中のindexを拒否。実際のAutomerge bindingにはencoding差があるため跨言語fixtureを必須にする。[S22]

継続的な共同編集にはopaque stable cursorを優先し、remote change後のselectionを再解決する。UIのIME変換中はcomposition bufferを保持し、remote更新で未確定文字を消さない。undoはlocal intentionに対する新しいCRDT操作で、他者の履歴をrollbackしない。

## 5. queryと購読

queryはローカルに認可・materialize済みのview。returnはrows、epoch、frontier、coverage、conflicts、pagination tokenを含む。未同期をnot-foundに変換しない。全文検索はnativeでは暗号化cacheからメモリー索引を構築、必要なpersisted indexはlocal keyで保護する。

document subscribeはsnapshotの最新値通知でcoalesce可。イベントログ用途には使わない。機密scopeが異なるSpaceを跨ぐ検索は利用者が読めるSpace集合に対してのみローカル合成する。

## 6. Durable Events / Presence

Eventはschemaで検証した不変payload、stream ID、event ID、causal parentsを持つ。少なくとも一回配送を実現する条件は、保持中のeventへ再接続できること。cursorより古い履歴が意図的にGCされていれば`CURSOR_EXPIRED`とrebase/export経路を返し、無言で先へ飛ばさない。

PresenceはTTLとboot/sessionに結び付く非永続hint。再接続時に過去presenceを再生しない。TTLを過ぎた相手は「最近の状態不明」。ユーザー全体の正確なonline数とは扱わない。

## 7. RPC

RPCはpeerとhandler versionを明示。handler登録と提供同意を分離し、input/output/schema、CPU/memory/time budgets、effect class（pure/local-idempotent/external）を宣言する。

呼び出しIDはcaller/Space/handler version/input digestへ結ぶ。異なるinputでの再利用はreject。結果とlocal side effectを同一AtomicStoreへcommitできるhandlerだけ、ローカル範囲のdedup保証を持つ。外部副作用は別systemの契約。timeoutとcancelは結果不明を返し得る。任意コード、shell、汎用proxy、暗黙のfilesystem権限を含めない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-DATA-001"></a>
### PAR-DATA-001 — 受理の決定性
**MUST:** change validityを宣言された依存状態とimmutable schemaで評価し、配送順で正当な操作を捨てない。
受け入れ: `AT-DATA-001` / 最初の必須gate: `G2`。

<a id="PAR-DATA-002"></a>
### PAR-DATA-002 — 競合の露出
**MUST:** registerの競合値・由来とsoft policy違反を返し、暗黙の業務的正解を選ばない。
受け入れ: `AT-DATA-002` / 最初の必須gate: `G2`。

<a id="PAR-DATA-003"></a>
### PAR-DATA-003 — 文書削除
**MUST:** 同epochの有効tombstoneを文書全体へ適用し、復元は新IDとする。
受け入れ: `AT-DATA-003` / 最初の必須gate: `G2`。

<a id="PAR-DATA-004"></a>
### PAR-DATA-004 — 文字位置
**MUST:** text indexの単位とfrontierを明示し、binding差をfixtureで検証する。
受け入れ: `AT-DATA-004` / 最初の必須gate: `G6`。

<a id="PAR-DATA-005"></a>
### PAR-DATA-005 — 検索範囲
**MUST:** queryはcoverage/frontierを返し、同期不能を全体の不存在と扱わない。
受け入れ: `AT-DATA-005` / 最初の必須gate: `G2`。

<a id="PAR-DATA-006"></a>
### PAR-DATA-006 — イベント再開
**MUST:** durable cursorの再配送・期限切れを明示し、presenceを永続eventとして再配送しない。
受け入れ: `AT-DATA-006` / 最初の必須gate: `G3`。

<a id="PAR-DATA-007"></a>
### PAR-DATA-007 — RPC副作用
**MUST:** 同一requestとinput digestを束縛し、結果不明を成功/失敗確定へ変換しない。
受け入れ: `AT-DATA-007` / 最初の必須gate: `G3`。
