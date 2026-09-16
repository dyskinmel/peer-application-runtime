# 03 — ID・鍵保管・端末復旧

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. IDと鍵の用途

AppIdはASCII reverse-domain形式1〜128 bytes。labelはUTF-8表示値でありIDと分離する。AccountIdはアプリ専用account root public key、DeviceIdはdevice signing keyからdomain-separated hashを得る。TransportPeerIdは通信経路の認証IDでDeviceIdとは別。

Account root、device Ed25519 signing key、device X25519 HPKE recipient key、transport key、local storage wrapping key、Space authority keyは分ける。Ed25519→X25519の暗黙変換や全アプリ共通account keyを既定にしない。ID導出と正確なbytesは `06-wire`、`protocol/par-v1.cddl`。

## 2. 証明書

DeviceCertificateはAppId、account public key、device signing/HPKE public keys、serial、formatをaccount rootが署名したもの。certificateは端末鍵の結合を証明するがSpace権限は付与しない。membershipに証明書digestを固定し、同じDeviceIdでHPKE keyだけを入れ替えない。certificateの再発行は新しいadmissionを要する。

TLS/Noiseが認証したtransport peerとDeviceIdの結合は接続ごとのnonce署名で確認する。offline証明書だけを使って現在の接続相手と同一と判断しない。

## 3. 鍵保護の等級

`software-encrypted`、`os-protected`、`hardware-wrapped`、`hardware-nonexportable`を別表示する。特定OSにKeychain/Keystoreがあることから、選んだ全暗号suiteがhardware内で動作すると推測しない。headless Keeperもlocal storage keyの保護方式を起動前に選ぶ。

ブラウザーの同一origin内で実行する悪意scriptは鍵・平文に到達し得る脅威として扱う。nonextractable keyを使うだけでXSSから安全とは表示しない。[S21] Web専用のCSP、依存scriptの固定、unsafe HTML排除はplatform gate。

## 4. バックアップを3種類に分ける

| 種類 | 含むもの | 含まないもの |
|---|---|---|
| Data Export | control、暗号化blocks、manifests、key packages | 平文の秘密鍵 |
| Device Recovery Kit | 事前認可された受信ID、復旧に必要な秘密材料を暗号化 | 自動的なowner権限 |
| Authority Backup | authority秘密鍵と既知control head、危険の説明 | 世界最新headの保証 |

Recovery Kitは32-byte CSPRNG recovery secretでAEAD暗号化し、secretと同じdata ZIPへ無断同梱しない。暗記しやすい弱いpasswordだけへの依存は既定外。印刷・QRは利用者の明示操作とする。

同じdeviceのcloneはold actorのsequenceを再使用し得る。復旧後の編集には新actor generationを必ず生成する。cloneが他に存在しないことは暗号だけで証明できないため、通常運用では新device enrollment＋旧device失効を推奨する。

## 5. 新しい端末は勝手に参加できない

A/B停止後にCから復旧するB2は、事前にmembershipへ認可され、対応するkey packageと復旧秘密材料が準備されている必要がある。あるいは、稼働中のauthorityがその時点で新しい端末を認可する。

**データを保管しているCが、authority不在のまま任意の新deviceへ権限を発行することは禁止。** この区別を最初の3台成功条件にも組み込む。

## 6. authority backupの古さ

古いauthority backupを復元しても、既存Spaceへの制御writeを自動再開しない。正当な稼働authorityからの移管、または既存チェーンとの明示的な復旧手順が必要。最新headを確認する相手が全て停止している場合、最新状態は判定不能。local read/exportは保持し、新Spaceへ移す選択肢を示す。

署名鍵を失い復旧材料もなく、他の受信者にも平文がないデータは復号できない。鍵をなくしたこととネットワークがないことを異なるエラーにする。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-ID-001"></a>
### PAR-ID-001 — 鍵用途分離
**MUST:** account/device/transport/HPKE/local/authority鍵を目的別に管理し、証明書とmembershipの両方を認可時に確認する。
受け入れ: `AT-ID-001` / 最初の必須gate: `G0`。

<a id="PAR-ID-002"></a>
### PAR-ID-002 — 保護等級
**MUST:** 実測・設定したkey protection classを返し、未検証hardware対応を表示しない。
受け入れ: `AT-ID-002` / 最初の必須gate: `G6`。

<a id="PAR-ID-003"></a>
### PAR-ID-003 — 復旧世代
**MUST:** clone/import後のwriterは新actor generationを使い、過去sequenceを再利用しない。
受け入れ: `AT-ID-003` / 最初の必須gate: `G1`。

<a id="PAR-ID-004"></a>
### PAR-ID-004 — 復旧資格
**MUST:** authority不在の新規環境復旧には、事前に認可された復旧IDと有効なkey packageを要求する。
受け入れ: `AT-ID-004` / 最初の必須gate: `G3`。

<a id="PAR-ID-005"></a>
### PAR-ID-005 — 鍵の分離配布
**MUST:** data exportへ平文復旧秘密を同梱せず、secret表示・印刷・コピーは独立同意とする。
受け入れ: `AT-ID-005` / 最初の必須gate: `G3`。

<a id="PAR-ID-006"></a>
### PAR-ID-006 — 古いauthorityの停止
**MUST:** authority backup復元から既存Spaceのcontrol writeを無条件に再開しない。
受け入れ: `AT-ID-006` / 最初の必須gate: `G9`。
