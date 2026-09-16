# ADR-AUTH-0002 — epoch seed bytes と認可判定の境界

00.07.00 / candidate / self-review only。

## Seed manifest候補
baseline CDDLはseed-rootを持つが、全seedを束ねる具体的なbodyを固定していない。本local overlayはcanonical map {0:1,1:app,2:space,3:epoch,4:package-set-id,5:objects,6:cut-envelope-ids}。objectsはObjectId昇順、最大256件。各entry={0:object-id,1:sealed-block-id,2:key-generation,3:plaintext-length,4:SHA256(plaintext)}。1object/1block（seed kind5、chunk0）、合計4MiB以下。cutはID昇順・重複なし・最大256件。大型seed・深いcutには別profile/manifest pagingが必要。

root=H("auth-local/seed-root",[canonical manifest bytes])。control hashはmanifestに含めず生成順の循環を避ける。authorityのcontrolがrootをcommitし、recipientはepoch開始control・最新membership・recipient certificate・authority署名・package root・HPKE context・全seedのhash/AEADを検証する。途中失敗でactive epochを変えない。seedはopaque bytesであり、CRDTの妥当性・競合保全の意味を検証済みとは扱わない。

## 失効と受理
control観測直後はmembership未完でもshared writeを止める。新epoch seed待ちではprivate draftへ退避する判断を返すが、このmodule自体はdraft保存機能を実装しない。受信変更は署名と旧membershipの両方を確認し、旧epochならREBASE_REQUIREDとする。最新epochのpayloadもinner actor/causal closure/Store apply待ちのcandidateであり、APPLY_RESULTを生成してはならない。

## Local permit
認可結果はインスタンスとrevisionへ結び、状態更新後の再利用を拒否。これは同一process内の使用ミス検出であり、Pythonのprivate attributeを敵対コードから保護する仕組みではない。Store commitとの間にcontrolが変わらないatomic integrationは別工程。単独のpermitチェックを分散transactionと呼ばない。
