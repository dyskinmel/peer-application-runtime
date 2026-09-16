# 実装への引継ぎ — 検証可能な作業単位

**状態:** 実装計画案。以下のcandidate pathは将来作成する場所であり、この仕様ZIPに製品ソースが存在するという意味ではない。

**Goal:** 最小の3台backendから、公開できるqualified profileまで、データ保全と認可を段階的に実証する。

**Architecture:** Rust portable core、狭いhost ports、Automerge core、native libp2p、暗号化SQLite/blocks、headless Presenter。正本は各specとGATES。未承認の低レベル補完はADRとG0判定を経る。

各作業は独立review可能なcommit単位へ分割し、実装開始前に対応acceptance contractを実行可能testへ落とす。テストが失敗することを確認→最小実装→合格→関連負例→review→checkpointの順に行う。ここでは未知の製品関数を実装済みとして呼ぶテストコードを大量生成せず、input/output/oracleを固定する。

## WP-01 — Protocol/crypto compatibility spike
Gate: G0。入力: protocol/par-v1.cddl + spec03–08。
候補file境界: `candidate crates/par-protocol/src/{codec,crypto}.rs; tests/vectors/`。
公開/内部interface: canonical_encode / strict_decode / verify_author_bindingの契約。
独立した受け入れ: canonical/reject bytes、HPKE/AEAD/signature組合せKAT、actor extraction。
失敗時: 異codecの不一致は仕様/adapter修正、未検証をPASSにしない。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-02 — Local ledger and crash safety
Gate: G1。入力: WP-01とstorage DDL。
候補file境界: `candidate crates/par-storage/src/{commit,actor,outbox}.rs; tests/faults/`。
公開/内部interface: commit(opId,digest) / lookup(opId) / outbox.resume。
独立した受け入れ: transactionの各write前後でstopしACK集合を再構築。
失敗時: 暗号化/atomicityを省いたtemporary実装を本番扱いしない。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-03 — Identity and Space control
Gate: G2。入力: WP-01–02、spec03–05。
候補file境界: `candidate crates/par-space/src/{membership,control,epoch}.rs`。
公開/内部interface: admit/verify_control/prepare_epoch/activate_epoch。
独立した受け入れ: fake membership、古いcontrol、fork、missing key/seed、別recipient。
失敗時: 承認待ちと未認可を別状態に保持。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-04 — Two-peer signed change sync
Gate: G2。入力: WP-03、spec07–08。
候補file境界: `candidate crates/par-sync/src/{session,inventory,apply}.rs`。
公開/内部interface: open_session / need / accept_change / snapshot。
独立した受け入れ: offline text+scalar conflict、seq fork、dependency待ち。
失敗時: Automerge受理失敗を握りつぶしてJSON同期へ置換しない。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-05 — Immutable blobs and closure builder
Gate: G3。入力: WP-02–04、spec09–12。
候補file境界: `candidate crates/par-replication/src/{closure,inventory,blocks}.rs`。
公開/内部interface: build_closure / audit_closure / publish_block。
独立した受け入れ: 最後のchangeだけの集合を不完全として検出。
失敗時: resource budget超過はroot不完全表示とresumeを残す。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-06 — Keeper retention and receipt
Gate: G3。入力: WP-05。
候補file境界: `candidate apps/par-cli/src/keeper.rs; crates/par-replication/src/lease.rs`。
公開/内部interface: offer/accept/commit/receipt/release。
独立した受け入れ: quota二重予約、partial bytes、reboot期限不明、virtual dishonest keeper。
失敗時: 既存lease保護、強制退出の影響を明示。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-07 — M1 recovery orchestration
Gate: G3。入力: WP-03–06、spec11。
候補file境界: `candidate tests/scenarios/m1_three_peers.rs; apps/shared-notes/`。
公開/内部interface: recover(plan) / resume(journal) / verify / activate。
独立した受け入れ: A/B停止→preauthorized B2がCのみから復元、未認可D拒否。
失敗時: oracle投入をrestore経路と完全分離。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-08 — Adversarial parsing and flow control
Gate: G4。入力: WP-01–07。
候補file境界: `candidate tests/fuzz/; crates/par-runtime/src/budget.rs`。
公開/内部interface: admission budget / quarantine / peer isolation。
独立した受け入れ: invalid UTF8、huge-dep、signed invalid、slow peer。
失敗時: 良性Spaceの進捗もoracleで検査。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-09 — Internet transports and Relay
Gate: G5。入力: WP-06/08、spec13。
候補file境界: `candidate crates/par-transport-libp2p/; tests/internet/`。
公開/内部interface: connect_candidate / reserve_relay / diagnose_route。
独立した受け入れ: CGNAT、blocked UDP、IPv6、network切替、egress deny。
失敗時: 環境依存failureは正確なreasonを記録。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-10 — Idiomatic SDK and host lifecycle
Gate: G6。入力: WP-04/07/08、spec14–16。
候補file境界: `candidate bindings/{swift,kotlin,typescript}/; crates/par-host-*`。
公開/内部interface: SDK declaration→binding ABI→async/Unicode/cancel。
独立した受け入れ: 実OS復帰、browser multi-tab、FFI lifetime。
失敗時: OS未確認laneは明示BLOCKED、native成果を保持。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-11 — Reference app / reusable Presenter / UI
Gate: G6。入力: WP-10、spec17–18、ui assets。
候補file境界: `candidate packages/par-presenter/; packages/par-ui/; apps/shared-notes/`。
公開/内部interface: VM stream / typed command / revision confirm。
独立した受け入れ: 24fixture gallery、keyboard/a11y、theme-only差分。
失敗時: 視覚変更とdomain仕様変更を別レビュー。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-12 — Independent security remediation
Gate: G7。入力: WP-01–11とthreat model。
候補file境界: `candidate tests/security/; docs/security/; evidence/reviews/`。
公開/内部interface: review finding→repro→fix→retest。
独立した受け入れ: crypto/auth/recovery全経路のindependent評価。
失敗時: 未手配reviewをNOT_RUNのまま明示。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-13 — Scale, resource, soak
Gate: G8。入力: WP-09–11、spec21。
候補file境界: `candidate benches/; tests/soak/; evidence/benchmark/`。
公開/内部interface: workload manifest / measured distributions。
独立した受け入れ: 各scaleと7日Keeper/24h mobile。
失敗時: 安全性保証を削ってtarget達成しない。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-14 — Migration and operating tools
Gate: G9。入力: WP-07–10、spec19/22。
候補file境界: `candidate apps/par-cli/src/{doctor,repair,migrate}.rs`。
公開/内部interface: plan/approve/apply/rebuild/activate。
独立した受け入れ: migration途中停止、old backup、corruption。
失敗時: 旧storeとdraftを失わない。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-15 — OSS release engineering
Gate: G10。入力: WP-12–14、spec23–24。
候補file境界: `candidate .github/workflows/; release/; docs/`。
公開/内部interface: source→build→SBOM→sign→verify。
独立した受け入れ: clean install、separate verifier、support演習。
失敗時: 公開/署名key利用はOwnerの実行承認で別操作。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。

## WP-16 — Production claim closure
Gate: G11。入力: 全必須gate。
候補file境界: `candidate release/qualification.json`。
公開/内部interface: claim(profile,scope,evidence)。
独立した受け入れ: external service停止、artifact再取得、全保証照合。
失敗時: 一つでも必須未達ならそのprofileはcandidate維持。

完了記録には変更path・source digest・対応requirement IDs・新規test実装path・実行結果・残るblockerを付ける。scope外のfeatureを空stubで増やすことは完了ではない。
