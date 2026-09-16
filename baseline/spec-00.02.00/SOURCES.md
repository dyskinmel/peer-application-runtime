# 一次資料と設計判断の境界

調査確認日: 2026-09-05。以下は公開一次資料。全文の複製ではなく、設計で参照した目的とリンクを記す。本文の[Sxx]はこの一覧に対応する。採用数値・MUST・gate・UI構造はPARの提案であり、参照元がPARを認定した意味ではない。

## S01 — Automerge — core / concepts / conflicts
CRDT文書/競合の既存機構。PARの認可・復旧・署名wrapperは本仕様の新規設計。

- https://github.com/automerge/automerge
- https://automerge.org/docs/reference/concepts/
- https://automerge.org/docs/reference/documents/conflicts/

## S02 — libp2p — hole punching
到達性確認とrelay-assisted hole punching。任意NATでの成功保証としない。

- https://libp2p.io/docs/hole-punching/

## S03 — Automerge — Modeling Data
共通初期履歴/identityの注意。epoch seedを一度作り配布する設計への参照。

- https://automerge.org/docs/cookbook/modeling-data/

## S04 — RFC 9180 — HPKE
HPKE algorithms/encoding。base modeの採用と外部署名の組合せはPAR側責務。

- https://www.rfc-editor.org/rfc/rfc9180.html

## S05 — RFC 8032 — EdDSA
Ed25519と公開known-answer vector。strict受理の実装一致は別試験。

- https://www.rfc-editor.org/rfc/rfc8032.html

## S06 — RFC 5869 — HKDF
HKDF-SHA256と公開known-answer vector。

- https://www.rfc-editor.org/rfc/rfc5869.html

## S07 — libsodium — XChaCha20-Poly1305
24-byte nonce型AEAD。暗号primitive仕様とPAR組合せレビューは別。

- https://libsodium.gitbook.io/doc/secret-key_cryptography/aead/chacha20-poly1305/xchacha20-poly1305_construction

## S08 — RFC 9420 — Messaging Layer Security
将来のgroup security profile。基本PARでMLS/FS/PCSを実装済みとしない。

- https://www.rfc-editor.org/rfc/rfc9420.html

## S09 — RFC 8949 — CBOR
core deterministic encodingに独自の制限subsetを重ねる。

- https://www.rfc-editor.org/rfc/rfc8949.html

## S10 — RFC 8610 — CDDL
構造記述言語。署名/認可/意味的検証は表現外の追加契約。

- https://www.rfc-editor.org/rfc/rfc8610.html

## S11 — SQLite — WAL and PRAGMA
WAL/FULLと接続設定。flush実装/媒体前提を別記。

- https://www.sqlite.org/wal.html
- https://sqlite.org/pragma.html

## S12 — SQLite — Atomic Commit
crash/durable filesystem前提。プロセス停止と電源断を区別。

- https://sqlite.org/atomiccommit.html

## S13 — Apple — Background Execution
mobile lifecycle制約。具体的OS上のqualificationは未実施。

- https://developer.apple.com/documentation/uikit/extending-your-app-s-background-execution-time
- https://developer.apple.com/documentation/backgroundtasks

## S14 — Android — Doze and App Standby
background/network制約。常時サーバーとしてスマートフォンを扱わない。

- https://developer.android.com/training/monitoring-device-state/doze-standby

## S15 — W3C — Indexed Database API
transaction API。ブラウザー保存の永続性保証はhost仕様/実機で分離。

- https://www.w3.org/TR/IndexedDB/

## S16 — W3C — WCAG 2.2
Web UIのAA目標。nativeは相当するOS accessibilityも試験。準拠認定未実施。

- https://www.w3.org/TR/WCAG22/

## S17 — DTCG — Format Module 2025.10
stable community specification。W3C Standardではない。

- https://www.designtokens.org/TR/2025.10/format/

## S18 — SLSA v1.2
build provenance/release工程の参照。SLSA level取得を主張しない。

- https://slsa.dev/spec/v1.2/
- https://slsa.dev/spec/v1.2/build-requirements

## S19 — The Update Framework
更新のrollback/freeze/root鍵脅威。auto-updateは任意host機能。

- https://theupdateframework.io/docs/security/
- https://github.com/theupdateframework/specification/blob/master/tuf-spec.md

## S20 — NIST SP 800-218 — SSDF 1.1 final
final版を工程参考とする。revision draftを最終標準と扱わない。

- https://csrc.nist.gov/pubs/sp/800/218/final
- https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

## S21 — W3C — Web Cryptography Level 2
脅威モデルを参照。draft文書のstatusと、script origin侵害の限界を区別。

- https://www.w3.org/TR/webcrypto-2/

## S22 — Automerge Swift — TextEncoding
UTF-8/UTF-16/Unicode scalarのindex差。PAR公開offset契約は明示化。

- https://automerge.org/automerge-swift/documentation/automerge/textencoding/
- https://unicode.org/faq/utf_bom.html

## S23 — Apache License 2.0
推奨ライセンス。第三者依存の条件は別確認。

- https://www.apache.org/licenses/LICENSE-2.0

## S24 — Mozilla — UniFFI
Swift/Kotlin binding選択肢。runtime/lifecycleの適合証明ではない。

- https://mozilla.github.io/uniffi-rs/latest/

## S25 — libp2p — WebRTC browser connectivity
browserとnative transportの差を考慮。全組合せの実接続は未実施。

- https://libp2p.io/docs/webrtc-browser-connectivity/

## 既存仕様の扱い

基準: peer-application-runtime-spec-00.01.00.zip。SHA-256: `397320e761e095c9758f2ebc904db3264c464729f947a570b4b4fffc6181b579`。今回の元になった仕様であり、実装コードや動作証拠ではない。原本はhistory内にそのまま保存する。

ライセンス本文は環境の標準Apache-2.0全文を収録し、公式公開本文を参照した。出所情報を含む資料/SBOMの製品公開前レビューはG10。
