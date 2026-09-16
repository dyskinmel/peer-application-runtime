# Wire補足 — object生成順・cross-field制約

本書は規範候補。CDDLの構造だけでは表現しない制約を補う。exact draft profileで相互検証してからfreezeする。CDDL parserによる検証は本bundle作成時には実施していない。

## 初期化の非循環性

初期membership entriesはAppId/DeviceId/certificate digest/roleだけから作り、まだSpaceIdを含めない。member page/rootを作る。genesisはそのroot、初期authority、乱数salt、policy digestを含む。SpaceId=H(space-id,[genesis body bytes])を計算した後にepoch1のseed/key packageを作り、sequence1のINIT controlを発行する。sequence0はgenesisを指す概念位置であり通常controlではない。

通常ControlEntryのprevは直前entryのID。最初だけSpaceId。control_id=H(control-id,[canonical control-entry bytes])。rotationの署名自身をbodyへ含めない。新authority proofは同じbodyにauthority-possession domainを使う。

## 署名objectとハッシュの対応

| object | 署名domain/parts | ID domain/parts |
|---|---|---|
| DeviceCertificate | certificate-sign / [body_bytes] | certificate-id / [signed-object bytes] |
| Genesis | genesis-sign / [body_bytes] | space-id / [body_bytes] |
| ControlEntry | control-sign / [body_bytes] | control-id / [control-entry bytes] |
| JoinRequest | join-request / [body_bytes] | request nonceで一意識別 |
| Admission record | admission-sign / [body_bytes] | handshakeでraw bytesへ束縛 |
| KeyPackage | key-package-sign / [body_bytes] | key-package-id / [signed-object bytes] |
| Retention manifest | retention-sign / [body_bytes] | retention-id / [signed-object bytes] |
| Receipt | receipt-sign / [body_bytes] | receipt-id / [signed-object bytes] |
| plaintext RecoveryDescriptor | recovery-sign / [body_bytes] | recovery-id / [signed-object bytes]、外側はsealed block |
| Export manifest | export-manifest-sign / [body_bytes] | export container外部のSHA-256も付ける |

SignedObjectのsigner public keyは、単に入っているだけでは信用しない。certificateではaccount PK、control/packageではそのsequenceのauthority、retentionでは許可済みrequester、receiptでは認可済みKeeperと一致させる。中間者がbodyとsignerを同時に差し替える攻撃をpin/membershipで拒否する。

member page ID = H(member-page-id,[C(page)])、membership root = H(membership-root,[C(ordered page IDs)])。ページはDeviceId byte順で分割し、ページ一覧は**その分割順**（ID hash順ではない）でroot化する。ここでsortedとはDeviceId順のページ順の意味でありhash値の並べ替えではない。重複DeviceIdを拒否する。inventoryはobject ID byte順で同じ規則を使い、H(inventory-page-id,[C(page)])、H(inventory-root,[C(root)])。key packagesはrecipient DeviceId順に並べてH(package-root,[C(package IDs)])。

## cross-field必須規則

- frame SpaceIdと内側の全SpaceId/AppIdが一致する。HELLO/AUTHはnull、認証前ERRORのみnull可。Space認可済みERRORは当該Spaceを使う。
- outer message全体のframe上限が個別array上限より優先する。CDDLの最大件数を全部一度に入れられるとは限らない。制御/manifestの連続pageで転送する。
- roleはreader/editor/opaqueKeeperのいずれか一つ。authority権限は別系列。resource grantは閲覧鍵を与えない。
- Control INITはseq1/epoch1/prev=SpaceId。permission-onlyはseq+1/同epoch/同content roots。content-transition/checkpointはseq+1/epoch+1/新package-setとseed。authority-rotationはseq+1/同epoch/next keyと二署名必須。他のactionにnew-key signatureを付けて意味を混在させない。
- admission ticketは初回control取得の限定的証拠。本人のsession署名とauthority chainを確認し、current membershipを上書きする許可として使わない。失効を知るpeerは拒否する。最大bootstrap proofの超過はexplicit手動/既知peer経路へ戻し、auth検証を省略しない。
- AUTH transcript = D(session-auth,[C(initiator HELLO),C(responder HELLO),selected wire ID,selected suite,initiator transportID,responder transportID,signer role])。roleはASCII `initiator`/`responder`。SessionId=H(session-id,[両HELLO bytes,selected wire ID,selected suite,両transportID])で共通化。device署名者はHELLO certificateと一致。
- SpaceOpen proofはD(space-grant,[SessionId,SpaceId,requestID,admission digest,known head,requested role,challenge])。admission digestはSHA-256(raw signed admission bytes)。SpaceAcceptは同domainで[SessionId,SpaceId,requestID,accepted head,sequence,epoch,grantee DeviceId,role,challenge]をresponder署名。grant digestは同partsへのH(space-grant,parts)。sessionを跨いで再利用不可。
- 文書changeはkind=document、codec1=選定したAutomerge change bytes。depsは内側CRDT change hashesと一致、prevは同actor直前のenvelope ID。最初はseq1/prev=null。同一actor内の分岐は通常の競合でなくequivocation。eventはcodec2で扱い、codec1へ混在させない。
- 未登録のkind/codec組合せはopaque保管可否をprofileで決め、applyは拒否。Durable eventのcanonical payload/同期は `ACTIVITY.ja.md` の別定義を使用する。
- sealed block AAD=D(block-aad,[block_header_bytes])、block_id=H(block-id,[C(sealed-block)])。inventoryはcanonical sealed bytes全体の長さを数える。
- HPKE info=D(key-package-info,[app,space,epoch,package_set_id,recipient_cert_digest])、AAD=D(key-package-aad,[suite,recipient DeviceId,membership root])。package本文のcontextと復号後contextも一致させる。
- Retention bytes/countはunique objectsとlengthから再計算。control/genesis/key/package/schema/inventory各page/semantic descriptorを復元に必要な形で保持する。parent manifestを子inventoryへ循環参照させない。root/descriptor用補助filesはrootの別fieldからpinしreceipt前に永続化する。
- RecoveryDescriptor chainはacyclicで、最大pages/object refsはlocal profile budgetで制御する。同じrootが示すcollectionを途中で置換しない。

## 未freezeの意味

この具体案でも、library選択に依存するAutomerge changeの厳密受理、crypto strictness、全messageのcross-codec vectorsはG0実験で確定する。未決の操作を実装者が勝手に補完し互換版として出荷しない。`review/OPEN_DECISIONS.ja.md`にfreeze前の証拠条件を記録する。

## Recovery Kit

kitにはformat、app、recipient DeviceId、kit ID、random salt32、nonce24、ciphertextを置く。CSPRNG recovery_secret32をHKDF-Extract(salt,secret)、HKDF-Expand(info=D(recovery-kit-aad,[app,recipient,kitID]),32)でkeyへ導出する。同じcontextにformatを足したAADでXChaCha20Poly1305暗号化。plaintextは復旧用device signing/HPKE secretとcertificate、pinned genesis/control、必要root locator。第三者shareやパスワードKDFは本profile外。secretをkit/データarchiveと別経路に保持し、使用後の新actor generationを必須にする。encrypted kitだけを持っていても復号できない。
