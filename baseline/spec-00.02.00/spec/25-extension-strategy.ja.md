# 25 — 拡張余地と領域内の高い到達目標

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. coreを小さくすることと、志を小さくすることは別

最初のprofileの上限は検証対象であり、将来の絶対上限ではない。目標は、参加者主権、優れたoffline体験、安全な協調、復旧しやすさ、簡単な組込みを損なわずに規模と用途を広げること。機能の数だけで品質を測らず、別実装の相互運用と作者不在での継続可能性も品質に含める。

| 拡張候補 | 再利用できるcore | 解かなければならない契約 | 入口の実験 |
|---|---|---|---|
| Large Space / hierarchical catalog | scoped IDs、inventory、quota | subspace秘匿、shard選択、offline権限、query coverage | 1,000/10,000 membershipのmetadata/鍵更新費用 |
| large-media / erasure coding | sealed blocks、recovery roots | fragment不可用性、再構成oracle、修復帯域、GC | 大fileの中断resumeと複数故障復元 |
| public signed feeds | signatures、immutable event、cache | 公開metadata、撤回、spam budget、配信費用 | read-only feedの署名/削除表示 |
| threshold authority | control chain、co-signatures | 署名者membership、key recovery、分断時停止、fork | 固定n-of-mのcontrol承認モデル。BFT consensusとは区別 |
| MLS security profile | transport、Space UI、epoch adapter | FS/PCSとarchive/recoveryの相互作用、state失効、multi-device | RFC9420準拠実装の文書/復旧適合[S08] |
| deterministic tasks | registered RPC、resource budgets | input secrecy、出力検証、retry、side effects、provider trust | pure bounded jobの重複実行比較 |
| stronger transactions | scoped auth、typed errors | 誰が順序を決めるか、quorum、分断時availability | 指定coordinatorの予約APIから測定 |
| fully local discovery | discovery port、invite | OS permissions、到達範囲、物理proximityと本人性の差 | QR/LANと近接transportを独立比較 |

## 2. extensionの互換境界

extensionはversioned manifest、capability ID、privacy/transport dependency、resource class、threat model、acceptance suiteを持つ。必須extensionを理解しないpeerは明示拒否。将来拡張のため、今のwireへ「任意JSONを実行する」穴を入れない。無検証codeを取得するplugin managerは設けない。

## 3. 実験を採用する基準

実験には仮説、比較対象、固定workload、測定、失敗条件、coreへの侵襲、migration、ユーザー理解を含む。採用するかをgateで判断し、基盤全体を二つのtransport/CRDT stackへ同時に引き裂かない。高速な接続であっても既定public relay依存を消せない構成はParticipants Onlyの代替としない。

実験未達を理由に取り返しのつかない既存データを放棄することはない。利用者が選ぶprofileと明示migrationで切り替える。各拡張にもProduction Ready証拠を必要とし、core1.0合格を自動継承しない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-EXT-001"></a>
### PAR-EXT-001 — 拡張の分離
**MUST:** extensionにcapability/threat/resource/migration/test契約を持たせcore保証を黙って変更しない。
受け入れ: `AT-EXT-001` / 最初の必須gate: `G10`。

<a id="PAR-EXT-002"></a>
### PAR-EXT-002 — 上限の扱い
**MUST:** 現profileの検証上限を将来の絶対上限とせず、拡大時は独立workloadで再認定する。
受け入れ: `AT-EXT-002` / 最初の必須gate: `G8`。

<a id="PAR-EXT-003"></a>
### PAR-EXT-003 — 暗号拡張
**MUST:** 強化暗号profileは復旧/保存との保証衝突と互換migrationを明示する。
受け入れ: `AT-EXT-003` / 最初の必須gate: `G7`。

<a id="PAR-EXT-004"></a>
### PAR-EXT-004 — 実験の評価
**MUST:** 代替技術の採否を依存性/性能/安全性/実装費用の証拠付きADRにする。
受け入れ: `AT-EXT-004` / 最初の必須gate: `G0`。
