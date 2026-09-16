# 22 — 互換性・更新・schema/storage移行

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 版は一つではない

spec bundle版00.02.00、wire draft、暗号suite、schema ID、storage schema version、SDK semantic version、UI VM version、release artifact versionを分ける。数字が似ていても互換を推測しない。G0以前はexact profile digest一致のみ。正式wire1.xは双方が理解する必須機能集合が満たされる場合のみ接続する。

| 変更 | 互換処理 |
|---|---|
| SDKの便利関数追加 | wire/storage不変ならminor candidate |
| 新optional message | feature capability negotiationで未対応は使わない |
| signature/AAD/KDF変更 | 新suiteまたはwire major、silent fallback禁止 |
| schema意味変更 | 新schema ID、明示migration、必要なら新epoch |
| DB index/cache追加 | sourceが再構築可能ならlocal migration |
| owner/membership semantics変更 | control featureを必須化、旧peer read-only/upgrade-required |

未知のsigned fieldsを消して再encodeしてはならない。unknown codecはopaque保管を許す場合も「適用済み」としない。信頼するcontrol/schemaが要求するcodecと一致するまでeditorを有効化しない。

## 2. database migration手順

1. writer lease/fence獲得、known store version検査。2. space/keys/blocksのintegrity inventoryを作成。3. 必要空き容量と時間の観測・停止可否を提示。4. 暗号化backupとmanifestを別領域へ作成・readback。5. shadow DBへmigrationしoperation ledger/outboxも移す。6. hash・logical invariants・schemaを検査。7. 新generationへatomic switch。8. 旧storeは明示retentionまで保持。

途中crashは旧store継続または同じjournalから新store構築を再開する。migration開始前のsource digestと違うDBへjournalを流用しない。downgradeして未知storeを強制openする動作は禁止。新形式でwriteした後は、raw binary rollbackではなく対応export/importまたはforward fixを用いる。

## 3. application schema migration

変換はsource schema/frontier/epoch、target schema、converter digest、policyを固定する。pureでdeterministicな変換はsandboxされたアプリ同梱codeで行う。networkから変換codeを取得・実行しない。結果rootを承認して新epoch seedへ結ぶ。

複数peerが同じJSONから独立にCRDT seedを作り別のobject identityを持つことを避ける。authorityが選んだ一つのseed bytesを共有する。失効/移行中の未取り込みdraftは保存し、旧schemaで勝手に新epochへ混ぜない。conflict値・tombstone・原文参照を落とすmigrationはlossyとしてpreviewを要求する。

## 4. interoperability matrix

native各OS、Swift/Kotlin、browser、N/N-1SDK、supported suite、wire feature、store versionを組合せて、capabilityに応じた正/負vectorを実行する。異なるbindingが同じRust coreを使った結果だけを独立protocol実装の一致と呼ばない。G0の独立codec比較、G10の外部conformance runnerでその差を補う。

1.0以降の互換方針案は、wire major内で少なくとも直前minorとの対話を維持し、security理由の拒否には明示advisoryを付ける。古いreleaseを永久に安全なまま維持できるという約束はしない。正確なsupport期間はOSS運営体制にbindingする。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-MIG-001"></a>
### PAR-MIG-001 — version分離
**MUST:** wire/suite/schema/store/SDK/UIのversionを独立識別し互換matrixで判定する。
受け入れ: `AT-MIG-001` / 最初の必須gate: `G0`。

<a id="PAR-MIG-002"></a>
### PAR-MIG-002 — migration原子性
**MUST:** migrationは元storeを保全しshadow検証後にatomic switchする。
受け入れ: `AT-MIG-002` / 最初の必須gate: `G9`。

<a id="PAR-MIG-003"></a>
### PAR-MIG-003 — outbox保持
**MUST:** schema/store migration後もoperation ledger/outboxと未反映draftを保持する。
受け入れ: `AT-MIG-003` / 最初の必須gate: `G9`。

<a id="PAR-MIG-004"></a>
### PAR-MIG-004 — unknown保護
**MUST:** 未知の必須意味を持つsigned dataを適用・再署名せずupgrade-requiredとして扱う。
受け入れ: `AT-MIG-004` / 最初の必須gate: `G4`。

<a id="PAR-MIG-005"></a>
### PAR-MIG-005 — seed共有
**MUST:** schema/epoch migrationに一つの承認済みseed bytesとsource frontierを固定する。
受け入れ: `AT-MIG-005` / 最初の必須gate: `G9`。

<a id="PAR-MIG-006"></a>
### PAR-MIG-006 — 互換証拠
**MUST:** binding互換と独立codec/protocol互換を分けて試験結果を公開する。
受け入れ: `AT-MIG-006` / 最初の必須gate: `G10`。
