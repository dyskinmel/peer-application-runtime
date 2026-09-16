# 04 — Space・認可・鍵更新・所有者移管

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 権限モデル

Spaceは機密性と認可の境界。roleはreader、editor、opaque-keeper。authorityはこれらとは別の制御権で、必要ならreader/editor roleを兼ねる。relay permissionはさらに別の接続capability。AppId一致もaccount共通もSpace内の権限を与えない。

v1では文書/field単位の機密ACLを入れない。異なる秘密共有範囲は別Space。業務承認や残高制約はowner-signed controlとは別のアプリロジック。

## 2. 二つの単調な系列

00.01.00からの重要変更として、`control_sequence`と`content_epoch`を分離する。

| 変更 | control_sequence | content_epoch | baseline |
|---|---|---|---|
| Keeper/Relay権限・quotaの変更 | +1 | 同じ | 不要 |
| 受信・編集membership変更 | +1 | +1 | 採用cutから新規 |
| content schemaの破壊的変更 | +1 | +1 | 明示変換 |
| authorityの正常移管 | +1 | 同じ | 不要 |
| 機密鍵漏洩・履歴圧縮 | +1 | +1 | 明示作成 |

ControlEntryはprevious hash、sequence、content epoch、action、各manifest root、current signer、next authority keyを結ぶ。genesisには最初のauthority keyとidentityを固定する。SpaceIdはgenesisのhashなので正常移管でも変えない。

## 3. 招待

受信者はdevice certificate＋fresh nonceへ自署したJoinRequestを作る。招待者はSpace名、role、受信者fingerprintを別の信頼経路で確認し、authorityがmembershipと必要鍵packageを発行する。QRは接続経路の発見にも使えるが、QRを読んだだけでhostの全権限を与えない。

one-click flowは「requestをownerへ届ける」操作として提供できる。全分断peerで一回だけ消費される匿名bearer tokenを標準にはしない。owner不在時は `approval-pending` とし、利用者のlocalデータを消さない。

## 4. epoch切替のtransaction

1. authorityが検証済みのcut、各Documentのfrontier、blob参照、tombstonesを選ぶ。全世界最新とは呼ばない。
2. 新membershipを作り、fresh epoch keyとpackage-set IDを生成する。
3. 旧CRDTの選択値だけでなく競合値一覧と出典も`conflict carryover`として保存する。未解決競合を黙って一値へ潰さない。
4. 一度だけ生成した新baseline bytesを暗号化保存する。受信peerが同じ値から別々にbaselineを再生成してはならない。[S03]
5. 必要rootを含む署名済みcontrolと各受信者へのHPKE packageを作る。生成順に循環hashを作らない。
6. 受信側は必要control、membership、key、seedが揃い検証できたとき原子的にactive epochを切り替える。

content controlは更新を知った時点で受信authに反映する。seed待ちの間に旧権限の新しい共有writeを継続しない。旧local内容は読める範囲で保持し、新編集はprivate draftへ保存する。

## 5. 古い編集と古い資格

新cutに含まれない旧epoch編集はrebase候補。現在も権限を持つ利用者がdiffを確認し、新epochの自分の操作として再適用する。自動再署名はしない。署名のwall timestampでは「失効前に書いた」を認定しない。

制御更新を知らないpeerは旧規則で動き得る。これを瞬時失効とは宣伝しない。再接続時はcontrol同期をdata適用より先にする。最新controlの隠蔽は検知できない場合があるので`known_control_head`と`freshness`を返す。

## 6. 正常なauthority移管

old authorityがrotation entryのcanonical bodyに署名し、new authorityが同じbodyへ別domain tagでproof of possessionを署名する。各受信者は既存チェーンでoldが有効なこと、sequenceが直後、both signaturesが正しいことを検証。次のentryからnewだけを受け入れる。

これは侵害済みold keyを魔法のように無効化する方法ではない。oldが並行した正当署名でforkを作れば、branchごとに観測が異なり得る。forkを観測したら自動hash選択せず、共有writeを停止してbranch exportと新Space移行へ進む。

## 7. ownerの不在と権限の回復

通常の編集にauthority常駐は不要。参加・除名・epoch更新には制御署名が要る。初期版ではquorum electionや自動leader takeoverを加えない。複数管理者・threshold recoveryを追加する際は、所有権移管、split brain、古いbackupの再出現まで含む別profileで検証する。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-AUTH-001"></a>
### PAR-AUTH-001 — 認可系列
**MUST:** membershipを通常CRDTから分離し、prev hash・sequence・署名を検証する。
受け入れ: `AT-AUTH-001` / 最初の必須gate: `G2`。

<a id="PAR-AUTH-002"></a>
### PAR-AUTH-002 — 系列分離
**MUST:** 保管権限変更だけでcontent epochを不要に再生成せず、read/write membership変更ではepochを更新する。
受け入れ: `AT-AUTH-002` / 最初の必須gate: `G2`。

<a id="PAR-AUTH-003"></a>
### PAR-AUTH-003 — baseline一意性
**MUST:** epoch baselineはauthorityが生成した同一bytesを配布し、競合値の出典も保全する。
受け入れ: `AT-AUTH-003` / 最初の必須gate: `G2`。

<a id="PAR-AUTH-004"></a>
### PAR-AUTH-004 — 失効の順序
**MUST:** 新しいcontent epochを伴うcontrolを観測したら旧epoch共有writeを止め、未確定の編集はprivate draftとして保持する。
受け入れ: `AT-AUTH-004` / 最初の必須gate: `G2`。

<a id="PAR-AUTH-005"></a>
### PAR-AUTH-005 — 正常移管
**MUST:** authority rotationは有効old署名とnew proof of possessionの両方で結び、SpaceIdを保持する。
受け入れ: `AT-AUTH-005` / 最初の必須gate: `G9`。

<a id="PAR-AUTH-006"></a>
### PAR-AUTH-006 — fork隔離
**MUST:** 同じcontrol位置への異なる有効署名を検出したらfork evidenceを保持し、自動勝者選択を行わない。
受け入れ: `AT-AUTH-006` / 最初の必須gate: `G4`。

<a id="PAR-AUTH-007"></a>
### PAR-AUTH-007 — 招待対象
**MUST:** JoinRequestとInviteは対象device鍵・AppId・SpaceId・要求nonceへ束縛する。
受け入れ: `AT-AUTH-007` / 最初の必須gate: `G2`。
