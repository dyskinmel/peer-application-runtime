# 08 — 同期・因果関係・検証・再開

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 同期の単位

dataはSpace→content epoch→objectで分離。暗号化transportの相手が正しいことと、受信changeが有効であることは別。個々のenvelopeを原著作者の署名で検証し、中継者の署名へ置換しない。

Automerge payloadは1つのchange。外側headerのactor/seq/hash/depsと内側changeを一致させる。複数authorを一つのenvelopeで包んで権限確認を迂回する方式は禁止。[S01]

## 2. 同期手順

1. 相互session認証とSpace proofを確認。
2. known control headsを比較。新controlを取得・検証し必要epoch seedを準備。
3. scoped inventoryを固定tokenでページ取得。
4. local headsと相手headsを比較してNEEDを作る。要求は欠落envelope/change/manifest/blockに限定。
5. changeをbounded quarantineへ受信し、hard limits、署名、cert、membership、AEAD、inner actor、depsを順に検証。
6. dependency closureが揃ったものだけtransactionへ適用。
7. local durable receiptの後でAPPLY_RESULTを返し、snapshotを通知。
8. 相手が広告したfrontierとの一致を確認。新しいhead hintがあれば続ける。

HAVEやpubsubはhintであり唯一の配送経路ではない。再接続時・前景idle時にanti-entropyを行う。初期のforeground間隔は30秒±20% jitter、OS停止中の定時timerは要求しない。

## 3. actorと復旧

actor ID=`H("actor-id", [space, epoch, object, author_device, generation])`。sequenceはそのactorのchange順。prev author envelopeとAutomerge依存を同時検証する。普通の並行actorは競合としてmergeし、同じactor seqへの異なる有効changeはequivocationとして文書を隔離する。

一時的に別branchを観測することはあり得る。全有効change集合が最終的に一致し、非equivocating actorと同じcodec/profileを使う場合に収束を保証する。悪意editorの意味的に合法な内容まで正しいとは主張しない。

## 4. quarantineの3区分

| 区分 | 例 | 動作 |
|---|---|---|
| waiting | dependency/control/seed未着 | budget内保存、取得を試す |
| invalid | signature/schema/actor不正 | applyしない。reasonをredactして記録 |
| resource-blocked | 正当だがlocal budgetに収まらない | invalidと呼ばず別host/profileへの復旧経路 |

依存待ちはpeerごと8 MiB、runtimeで64 MiBを初期値とする。capacity超過はcredit停止または再取得可能な受信途中データを破棄。local committed原本や保管lease済みblockをpressure evictionに使わない。

## 5. 中断と冪等性

transfer request IDと意味的operation IDを分離。再起動後も署名envelope bytesとCommitIdは変えない。重複envelope IDは同じobjectとして扱い、outboxで新changeを作り直さない。受信側のAPPLY_RESULT消失後も同一IDで照会できる。

通信cancelは送信停止であり、既に保存した編集のundoではない。参照UIは「送信を止める」と「変更を取り消す」を別commandにする。

## 6. catalogと完全性

catalogは署名付きobject announcementとtombstonesを保持する。初期小Space profileは認可範囲のcatalog metadata全体を取得し、本文は選択取得可。partial replicationで任意の内容filterの完全性を保証しない。

pagination snapshot token、head集合、対象集合IDを使い、途中で見えない文書がないことをそのpeer viewの範囲で判定する。件数一致だけを完全性判定に使わない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-SYNC-001"></a>
### PAR-SYNC-001 — 内外author一致
**MUST:** 各changeを単一authorとして検証し、inner actor/seq/deps/hashが外側宣言に一致することを要求する。
受け入れ: `AT-SYNC-001` / 最初の必須gate: `G0`。

<a id="PAR-SYNC-002"></a>
### PAR-SYNC-002 — 依存先行
**MUST:** control/epoch/causal depsが揃う前に適用済みACKを返さない。
受け入れ: `AT-SYNC-002` / 最初の必須gate: `G2`。

<a id="PAR-SYNC-003"></a>
### PAR-SYNC-003 — 収束条件
**MUST:** 同じ有効集合・epoch・codecの非equivocating入力でvalues/conflicts/tombstonesが一致する。
受け入れ: `AT-SYNC-003` / 最初の必須gate: `G2`。

<a id="PAR-SYNC-004"></a>
### PAR-SYNC-004 — equivocation
**MUST:** 同actor同sequenceの異なる有効署名を検出した文書は隔離して証拠を保持する。
受け入れ: `AT-SYNC-004` / 最初の必須gate: `G4`。

<a id="PAR-SYNC-005"></a>
### PAR-SYNC-005 — 再開冪等性
**MUST:** restart/retryでCommitIdとenvelope bytesを保ち新しい変更を重複作成しない。
受け入れ: `AT-SYNC-005` / 最初の必須gate: `G2`。

<a id="PAR-SYNC-006"></a>
### PAR-SYNC-006 — 待機容量
**MUST:** quarantineとfetch queueをscope別に制限し、正当データのresource-blockedをinvalidと区別する。
受け入れ: `AT-SYNC-006` / 最初の必須gate: `G4`。
