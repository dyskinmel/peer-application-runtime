# 10 — Keeper・復旧集合・lease・自動修復

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 何を保管するか

保管契約はchange単体でなく`RetentionSet`。対象frontierを復元するための暗号化objects、control/genesis、key package、schema、causal履歴、blob/seed manifestsを含む。

三つのrootを区別する。

| root | 読める主体 | 役割 |
|---|---|---|
| semantic recovery root | 読取り権限を持つ端末 | 対象文書frontierと依存関係・鍵参照 |
| inventory root | 認可されたKeeper | 保管すべき全block ID・長さの集合 |
| retention manifest ID | requester/keeper | 上二つとscope/profile/operationを署名で結合 |

inventoryはsorted unique entriesを最大1,024件ずつページ化し、page hashesをrootへ結ぶ。pageは子data refsだけを含み、自分自身や親manifestを参照しない。署名root自体の保管は別の必須条件。全byte集合のdigestは件数だけでなくIDと長さとkindを含む。

## 2. opaque Keeperに分かること

Keeperはhash・length・外側署名・quota・scopeを検証できるが、暗号化Documentの全依存が意味的にそろうかは通常検証できない。

したがって `byte-complete retention` と `authorized recovery-closure-verified` を区別する。requesterの認可済みclosure builderが意味的完全性を確認したmanifestに対して初めて復旧指標を計算する。悪意のrequesterが作った不完全manifestへKeeperが正直にreceiptを出しても「復元可能」と自動昇格しない。

## 3. protocol

1. RETAIN_OFFER: caller、capability、operation ID、manifest、requested duration、total bytes。
2. Keeperはmembership/capability、scope、利用者同意、disk budgetを検証し、重複operationは同じ結果を返す。
3. RETAIN_ACCEPT: reservation ID、accepted duration、missing inventory pages/blocks。
4. scoped BLOCK_GET/transferで欠けたbytesを埋め、hash・lengthを検証。
5. RETAIN_COMMIT: manifest rootとfresh challengeを指定。
6. KeeperがDB/block rootsを永続化してから署名RECEIPTを発行。

receiptはkeeper DeviceId、manifest ID、inventory root、storage class、control head、lease duration、challenge、boot referenceを持つ。partial retentionはpartialと報告しfull receiptを出さない。

## 4. leaseとclock

初期最大lease 7日、reservation timeout 10分、foregroundで残り期間の半分を目安に更新する。時刻は利用者表示用wall clockと期限用monotonicを分離する。requester再起動後はfresh challengeまでreceipt freshnessをunknownに戻す。

Keeper再起動時にmonotonic残期間を確定できなければ、既存leaseを勝手にexpiredとしてevictしない。diskの予約状態を保持し、再確認か利用者の明示的な強制解放が必要。安全な保持が過剰になる場合もdiagnosticsで説明する。悪意のclock・電源断・退会に対する永久保存保証はしない。

## 5. replica selectionと修復

既定はlocal copy＋2 remote receipts。selectionは認可、容量、最近の到達性、電力/回線条件、利用者が登録した障害領域の順で絞り、同順位は安定hashで分散する。DeviceIdの数を物理独立性と同一視しない。

修復は不足確認→source探索→候補予約→必要blocks転送→receipt→古い予約解放。sourceがなければ`unrecoverable-from-reachable-peers`とし、offlineとpermanent lossを断定しない。backoffとjitterで同時repairの輻輳を抑える。

## 6. retrieval auth

hashを知るだけでGETできない。current sessionのSpace grantと、そのcontrol headで許されたretention setを確認する。Keeperは本文に触れず、caller certificateとcapabilityからscopeを検証する。

新controlを知らないKeeperは古いgrantを認め得る。この制限は失効の観測遅延として表示する。コピーされた過去ciphertext/keyまで回収したとは主張しない。resource capabilityは読み取り鍵の代用ではない。

## 7. pauseと退出

pauseは新規offer/renewを止め、既存保管の扱いを説明する。graceful leaveは移管を試すが、利用者には即時停止権がある。強制停止は約束を破る可能性を明示し、reachable peerへbest-effortで通知する。バックグラウンドで利用者を拘束する仕組みは作らない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-REP-001"></a>
### PAR-REP-001 — 完全性の二段階
**MUST:** byte retentionと認可済みsemantic recovery closureを区別し、最後のchangeだけを復旧可能と数えない。
受け入れ: `AT-REP-001` / 最初の必須gate: `G3`。

<a id="PAR-REP-002"></a>
### PAR-REP-002 — receipt永続化
**MUST:** 全対象bytesとmanifestを永続化後にのみfull retention receiptを発行する。
受け入れ: `AT-REP-002` / 最初の必須gate: `G3`。

<a id="PAR-REP-003"></a>
### PAR-REP-003 — lease鮮度
**MUST:** fresh challengeとboot/monotonic状態でreceipt鮮度を管理し、古いreceiptを現在可用性としない。
受け入れ: `AT-REP-003` / 最初の必須gate: `G3`。

<a id="PAR-REP-004"></a>
### PAR-REP-004 — 保管側再起動
**MUST:** lease期限が不明な再起動では、既存予約を安全側へ保持して明示解放または再確認を要する。
受け入れ: `AT-REP-004` / 最初の必須gate: `G3`。

<a id="PAR-REP-005"></a>
### PAR-REP-005 — 冪等予約
**MUST:** 同じoperation IDとdigestのoffer/commitはquotaを二重消費せず、異なるdigestの再利用を拒否する。
受け入れ: `AT-REP-005` / 最初の必須gate: `G3`。

<a id="PAR-REP-006"></a>
### PAR-REP-006 — 認可取得
**MUST:** GETはcontent hash知識だけで許可せず、session/Space/capability/controlのscopeを照合する。
受け入れ: `AT-REP-006` / 最初の必須gate: `G3`。

<a id="PAR-REP-007"></a>
### PAR-REP-007 — 退出の説明
**MUST:** 資源提供者が退出でき、保管約束と移管未完の影響を明示する。
受け入れ: `AT-REP-007` / 最初の必須gate: `G6`。
