# ADR-WIRE-0002 — transcript/pagingの実験契約

状態: CANDIDATE、00.04.00内のローカル実験。暗号プロトコルとして未承認・未凍結。
baseline spec05 §7にbindingすべき要素はあるが、具体的bytesが未定義のため、次の候補で試験する。

## Transcriptの正確な形
I/Rはtransportのinitiator/responderで固定し、通信に含まれた自己申告roleで入替えない。
全HELLO frame bytes（4-byte長を含む）をcanonical検査してからhashする。

```
T = C({0:1, 1:AppId, 2:selected_wire, 3:selected_suite, 4:profile_digest,
       5:SHA256(raw_hello_I), 6:SHA256(raw_hello_R),
       7:nonce_I, 8:nonce_R, 9:transport_peer_I, 10:transport_peer_R,
       11:"initiator", 12:"responder"})
signing_bytes(role) = D("session-auth", [T, role])
AUTH.body[0] = SHA256(signing_bytes(role))
AUTH.body[1] = Ed25519.Sign(device_signing_key, signing_bytes(role))
candidate_session_id = SHA256(D("session-id", [T]))
```

D/Cはbaseline spec05の定義。raw digestはnonce、certificate、offer集合、request IDを含む。
候補版はwire=`par/1-draft-2`, suite=1、双方のexpected profile一致のみを許可する。
peer IDsはtransportが認証した値と照合し、同peerまたは同nonceのreflectionを拒否する。
各署名にsigner roleを含め、一方のAUTHを他方へ反射しても同じ署名対象にならない。

## 今回実装しないもの
Certificate/Ed25519 strict verify、鍵所有の検証、Space proof、control chain、membership、
AEAD、nonce永続管理、network接続、完全なSession状態機械。Transcriptは常にauthenticated=false。
candidate_session_idを得ただけで認証済みSessionを作ってはならない。
ReplayWindowは認証後に使うbounded local補助filterのみ。restart/TTL後まで世界的にreplayを防ぐものではない。

## InventoryWalk
対象Space、snapshot tokenを開始時にpin。呼出側が要求時cursorを渡し、前pageのnext cursorとの一致を検査する。
pageのtoken/space不一致、cursor反復、重複object、不正page、resource超過では全体をINVALIDATEDにし、
「存在しない」や「全同期済み」に変換しない。done到達時もPEER_SNAPSHOT_COMPLETEでありglobal completeではない。
page取得messageとrequest ID→cursor束縛は未確定。helperはtransportの代わりではない。

## profile
`experiments/g0-wire/profile.json`はbaseline CDDL/registry/limits、ADR-0001/0002のSHA256リストを
固定順でC(["PAR-EXPERIMENT-PROFILE",1,[[path,digest]...]])化したhashを含む。
この識別子は今回の実験の比較用であり、baseline配布ZIP hashや安定版protocol IDを装わない。
