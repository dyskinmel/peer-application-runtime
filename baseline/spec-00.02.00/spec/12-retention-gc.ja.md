# 12 — 履歴・削除・GC・チェックポイント

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 削除の種類

UIとAPIは以下を別commandとする。local cache evictionは再取得可能なcacheの削除。shared tombstoneは以後の共有viewからの削除。forget Spaceは当該端末の鍵とpinを外す操作。retention releaseはKeeperへの解放要求。secure eraseは媒体・OS前提が別なので一般保証しない。

remote peerが保持する過去の平文やcopyを消せるとは言わない。利用者が所有する端末と、他参加者に既に渡したデータの違いを説明する。

## 2. pin roots

GC root集合はactive epoch seed、local committed outbox、ユーザーpin、未完migration/recovery、unexpired/uncertain leases、explicit history retention、export snapshot、quarantined evidence。raw blocksの参照countだけに依存せず、rootからのreachabilityを検証する。

GCはmark/sweep二段階。mark開始時のroot generationを固定し、sweep直前にgenerationの変化と新pinを照合する。新規commitとraceしたら対象を再判定する。削除失敗は記録して再試行し、成功と偽らない。

## 3. causal履歴の圧縮

長期offline writerが戻るため、単に古い日時だからchangeを消す方式は禁止。圧縮はauthorityが採用cutと新baselineを署名し、content epochを更新するcheckpoint。旧cut外変更はrebase候補として残す。

新baselineは同じmaterialized valuesだけでなく、未解決conflictの出典をcarryover manifestに保存する。旧Automerge bytesを新規baselineへ混ぜず、参照・変換の関係を記録する。古い履歴を読む権限と新しいcurrent stateを読む権限を別にする。

## 4. 容量と履歴ポリシー

Spaceごとに`current-only`、`bounded-history`、`pinned-history`を選べるが、失効や保管約束の意味を変えない。bounded-historyの期間は「今の表示viewの履歴の希望」で、依存が必要なblockを無条件に消す期限ではない。

容量不足時の優先はre-download可能cache→期限が確定した未pin retained data→orphan staging。未送信データや唯一のpinコピーを無断で消すことはない。容量が足りないなら書込み・新規保管を拒否し、既存データのexport/移管を案内する。

## 5. tombstoneの保持

同epochの古いupdate再来を防ぐためtombstoneを依存履歴とともに保持する。新epoch baselineのcatalogにも削除・移行の事実を反映する。新DocumentIdでの復元のみ許可するので旧IDの再利用によるresurrectionを避ける。

## 6. 削除確認

remote release ACKは「相手が解放を処理したという表明」。相手が本当に全copyを消した証明ではない。local消去もSSD wear leveling、backup、swap、crash dumpまで常に覆えるとは表示しない。必要ならOS/媒体別のより強い消去profileへ分ける。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-GC-001"></a>
### PAR-GC-001 — 削除の区別
**MUST:** cache eviction、shared delete、forget、retention releaseを別commandと表示にする。
受け入れ: `AT-GC-001` / 最初の必須gate: `G6`。

<a id="PAR-GC-002"></a>
### PAR-GC-002 — GC根保護
**MUST:** active/pinned/outbox/lease/recovery/export/quarantine rootsに到達するblockをGCしない。
受け入れ: `AT-GC-002` / 最初の必須gate: `G3`。

<a id="PAR-GC-003"></a>
### PAR-GC-003 — GC競合
**MUST:** mark/sweep間の新pin・commitをgeneration確認で保護する。
受け入れ: `AT-GC-003` / 最初の必須gate: `G4`。

<a id="PAR-GC-004"></a>
### PAR-GC-004 — 履歴短縮
**MUST:** causal履歴短縮は署名checkpoint/epochとrebase経路を使い、壁時計の古さだけで破棄しない。
受け入れ: `AT-GC-004` / 最初の必須gate: `G9`。

<a id="PAR-GC-005"></a>
### PAR-GC-005 — 秘密の消去境界
**MUST:** remote releaseやlocal key削除を、既配布平文の回収証明と表示しない。
受け入れ: `AT-GC-005` / 最初の必須gate: `G7`。
