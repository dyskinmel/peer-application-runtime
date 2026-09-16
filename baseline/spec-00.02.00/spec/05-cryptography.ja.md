# 05 — 暗号スイート・署名対象・鍵導出

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 採用するsuite候補

`PAR-C1`はEd25519、SHA-256、HKDF-SHA256、XChaCha20-Poly1305、HPKE base modeの組合せ。HPKEはKEM=0x0020（DHKEM X25519/HKDF-SHA256）、KDF=0x0001、AEAD=0x0003（ChaCha20Poly1305）。HPKE base mode単独を送信者認証と解釈せず、鍵packageにはauthority署名を必須にする。[S04][S05][S06][S07]

暗号primitiveは保守された実装を使用する。自作暗号、非暗号学的乱数、認証失敗後の復号継続は禁止。ここでの組合せは設計候補であって独立レビューを通過したprotocolではない。P0で実装選定とPAR全体のknown-answer corpusを作り、G7で第三者による暗号・認可レビューを閉じる。

## 2. bytesとdomain separation

`C(x)`はPAR制限付きcore deterministic CBOR。可変長文字列を単純連結しない。

```text
D(label, parts) = C(["PAR", 1, label, parts])
H(label, parts) = SHA256(D(label, parts))
S(key, label, parts) = Ed25519.Sign(key, D(label, parts))
```

用途別labelを `protocol/registry.json` に固定する。labelはASCIIで大文字小文字を区別。署名はpure Ed25519でありEd25519phではない。Ed25519のpublic key、signatureの受理基準は選択libraryのstrict verificationを固定し、小位数点・非正規signature等をreject corpusで一致させる。[S05]

AccountId=`H("account-id", [app_id, account_pk])`、DeviceId=`H("device-id", [app_id, device_sign_pk])`、SpaceId=`H("space-id", [genesis_body_bytes])`。signed wrapperの署名自身をhash入力へ循環させない。

## 3. subkey導出

content epochごとに独立な32-byte `epoch_secret`をCSPRNGで作る。

```text
salt = H("epoch-salt", [app_id, space_id, content_epoch])
prk = HKDF-Extract(salt, epoch_secret)
object_key = HKDF-Expand(prk,
    D("object-key", [kind, object_id, key_generation]), 32)
```

`kind`はdocument/event/blob/recovery/seedで別値。新epochに旧epoch secretを流用しない。blob専用鍵を新epochでwrapして旧immutable blobを参照する場合も、旧document keyやepoch secret全体を渡さない。

## 4. change envelope

`header_bytes`はschemaに示す全headerをcanonical CBOR化したbytes。`nonce`は24-byte CSPRNG。

```text
ciphertext = XChaCha20Poly1305.Seal(object_key, nonce,
    aad=D("envelope-aad", [header_bytes]), plaintext=payload)
signature = S(device_sign_key, "envelope-sign", [header_bytes, nonce, ciphertext])
envelope_bytes = C({0:header_bytes, 1:nonce, 2:ciphertext, 3:signature})
envelope_id = H("envelope-id", [envelope_bytes])
```

同じkey/nonceを別の平文に再使用しない。retryは保存済みbytesをそのまま送る。乱数失敗はcommit前に失敗する。発行nonceとobject key generationを記録し、local duplicateを拒否する。他端末との衝突は192-bit CSPRNG前提の残余リスクとして扱い、RNGを脅威モデルに含める。

envelope headerはapp、space、epoch、object、kind、author、actor generation、seq、prev、schema、deps、plain length、CRDT hash、control head、codecを含む。signatureを確認した後もmembershipと内側actorを確認する。

## 5. sealed block

Blob chunk/baseline/recovery descriptorは、型付きblock headerをAADにして同じAEADで保護する。headerはapp/space/epoch/object/kind/chunk_index/key_generation/plain_length。block IDはnonce・AAD・ciphertextを含むcanonical sealed block bytesのhash。

chunk_indexとobject IDを認証するため、別ファイルの同じindexへchunkを差し替えては復号検証が通らない。plain lengthをAEAD後に検査し、ciphertext lengthだけから無制限allocationしない。

## 6. key package生成順

1. 新epoch番号、membership root、seed policy、ランダムpackage-set IDを決定。
2. recipient certificate digest、app/space/epoch/package-set IDからHPKE `info` を作る。
3. HPKE AADはsuite、recipient ID、membership root。暗号化平文はepoch secret＋一致すべきcontext。
4. `enc`、ciphertext、recipient、contextをauthorityが署名。
5. package一覧rootを作り、最後にControlEntryへ結ぶ。

packageのHPKE infoに、これから生成する暗号文を含むcontrol hashを使わない。受信側はcontrolのpackage rootと署名・recipient・membershipの三者を検証してからsecretを有効化する。

## 7. 接続認証

HELLOは両者のnonce、DeviceCertificate、supported version/suiteを含む。選択version、suite、両HELLOのraw digest、両transport peer ID、initiator/responder roleをtranscriptへ含める。downgradeやrole reflectionを検出する。認証済みSessionIdにSpace grantを束縛し、別接続へgrantを再利用しない。

## 8. 鍵漏洩と上限

静的epoch secret方式はforward secrecy/PCSを保証しない。署名鍵漏洩は当該device失効＋epoch更新、authority漏洩はforkリスクを伴うSpace移行、local key漏洩は端末隔離と再暗号化のrunbookへ進む。失効前に読めた不変blobは回収不能。

より強いgroup securityはMLS profileとして別に仕様化する。MLSのFS/PCSは鍵削除とprotocol運用の前提を持ち、archiveからの復旧と同じ保証ではない。[S08] 基本profileを広告でSignal相当と呼ばない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-CRYPTO-001"></a>
### PAR-CRYPTO-001 — suite固定
**MUST:** 暗号suiteとstrict verify基準をprofileへ固定し、未対応suiteをsilent downgradeしない。
受け入れ: `AT-CRYPTO-001` / 最初の必須gate: `G0`。

<a id="PAR-CRYPTO-002"></a>
### PAR-CRYPTO-002 — context結合
**MUST:** 署名・AAD・KDFには型付きdomainとapp/space/epoch/object/recipientを結び付ける。
受け入れ: `AT-CRYPTO-002` / 最初の必須gate: `G0`。

<a id="PAR-CRYPTO-003"></a>
### PAR-CRYPTO-003 — nonce管理
**MUST:** CSPRNG失敗時は書込みを失敗させ、再送では保存済みciphertextを再使用する。
受け入れ: `AT-CRYPTO-003` / 最初の必須gate: `G1`。

<a id="PAR-CRYPTO-004"></a>
### PAR-CRYPTO-004 — package認証
**MUST:** HPKE base packageはauthority署名とcontrol上のrecipient・manifest rootの両方を検証する。
受け入れ: `AT-CRYPTO-004` / 最初の必須gate: `G2`。

<a id="PAR-CRYPTO-005"></a>
### PAR-CRYPTO-005 — 生成順
**MUST:** 自己参照hashを作らず、package-set ID→package→root→controlの順を固定する。
受け入れ: `AT-CRYPTO-005` / 最初の必須gate: `G0`。

<a id="PAR-CRYPTO-006"></a>
### PAR-CRYPTO-006 — 保証境界
**MUST:** 基本profileにFS・PCS・匿名性を主張せず、侵害時の鍵更新・データ退避を公開する。
受け入れ: `AT-CRYPTO-006` / 最初の必須gate: `G7`。
