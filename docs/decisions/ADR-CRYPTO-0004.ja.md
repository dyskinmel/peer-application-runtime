# ADR-CRYPTO-0004 — provider admission boundary と security decision freeze

状態: **candidate / DECISION_REQUIRED / 00.66.00**。G0-CRYPTO、OD-01、Product Qualificationを閉じない。

## 背景
00.65.00 Native Bootstrap Readyのfresh preflightではRust/Cargoが無く、native laneは開始不能。暗号側では本ホストのlibsodium 1.0.18を正確に識別できるが、これは従来どおり`legacy_experiment_only=true`かつ`security_qualified=false`である。現在のlocal KAT/strict reject/HPKE/store統合の成功を、新provider採用やsecurity reviewの代わりにしてはならない。

## 決定
provider選定そのものは凍結し、先に**置換可能なadmission boundary**だけを実装する。

`par_crypto.admission`はproviderの公開identityとprimitive surfaceを検査し、次の二境界だけを返す。

- `EXPERIMENT_ONLY`: legacy、依存closure未完、key protection未検証等を含む。既存の明示opt-in local experimentを越えて昇格しない。
- `REVIEW_CANDIDATE`: maintained、no-fallback、dependency closure complete、key protectionが少なくともsoftware verifiedで、legacyでないproviderを**security reviewへ入れる前段**として受理する。これはsecurity qualificationではない。

provider自身が`security_qualified=true`を宣言しても`native-review`では拒否する。独立security evidenceをprovider objectの自己申告で代替しないためである。runtime discovery、download、upgrade、fallbackはこのboundaryでは一切行わない。

## legacy Sodium candidateの追加metadata
既存provider identityへ、secretを含まない次の情報を追加する。

- provider family
- primitive capability一覧
- auto-fallback有無
- maintenance状態
- key-protection状態
- dependency-closure状態

現在の1.0.18は`LEGACY_VERSION_EXPERIMENT_ONLY`、`PROCESS_MEMORY_UNVERIFIED`、`TARGET_IMAGE_ONLY_NOT_COMPLETE_NATIVE_CLOSURE`のまま。これらをmetadata追加だけで改善扱いしない。

## Security decision packet
`G0_CRYPTO_PROVIDER_DECISION_0066.json`に、providerを固定せず次をmachine-readable化する。

- threat model / trust boundary
- role-separated key lifecycle / restore rule
- RNG/nonce reservation/retry rule
- canonical serializationとmigration条件
- supply-chain/SBOM/maintenance条件
- platform key-protection readback条件
- strict vectors、HPKE interop、store/control/CRDT integration、独立reviewの必要evidence
- irreversibleな判断を止めるstop conditions

候補familyは比較対象を失わないためのresearch queueであり、採用決定ではない。最終provider選定はnative toolchainと最新maintenance/security情報を揃え、Extra High/同等のarchitecture/security reviewで行う。

## 非主張
- libsodium 1.0.18を安全・maintained・production readyとは認定しない。
- Rust provider、HPKE library、platform keystoreの採用を決定しない。
- provider hashだけでpublisher authenticityを証明しない。
- software key protectionをhardware-backedと表示しない。
- local receiptを独立security attestationとして扱わない。

## 次のgate
1. Rust/CargoがあるhostでG0-ACTOR/WIRE/STOREを開始。
2. G0-CRYPTO provider選定時にmaintenance、audit、interop、supply-chain、platform key protectionを最新情報で再確認。
3. 選定providerを`REVIEW_CANDIDATE`境界へ通し、strict vectorsとcross-implementation evidenceをfresh生成。
4. reviewed check registrationとfresh receiptなしにG0-CRYPTOをcompleteへ上げない。
