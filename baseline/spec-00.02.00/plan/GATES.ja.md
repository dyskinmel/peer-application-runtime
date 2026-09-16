# G0–G11 — 本番到達までの合格条件

本表は実行計画とrelease判断の契約。現在すべてNOT_RUN。後段の完了で前段の失敗を上書きしない。G4/G7の設計作業は初日から並行し、番号順にsecurityを後回しにしない。

## G0 — Specification & compatibility closure
前提: なし。仕様baselineを固定。責任: 当該領域実装者＋独立reviewer。

試験/成果: 厳密CDDL/codec corpusを独立codecで照合；PAR全体crypto vectorsとstrict reject一致；実際のdependency/toolchain lock；Automerge actor/seq/deps検証probe。

出口: par/coreまだ未実装でも契約に実装不可能な箇所が無い；全MUSTにacceptance contract、全critical未決事項に判定結果。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G1 — Local integrity
前提: G0。責任: 当該領域実装者＋独立reviewer。

試験/成果: 暗号化storeとledger/outbox原子的commit；各commit境界fault injection；same operation IDの結果照会；restart/corruption/ENOSPCの区別。

出口: ACK済み集合がprocess-crash後に残る；対象OS durability classの前提記録。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G2 — Two-peer convergence
前提: G1。責任: 当該領域実装者＋独立reviewer。

試験/成果: 正規招待/権限/epoch/key/seed；offline concurrent edits→reconnect；conflict/invalid actor/late epoch試験；NATを介さない実process通信。

出口: identical有効operation集合→identical状態；auth前のprivate一覧なし。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G3 — Three-peer durability / M1
前提: G2。責任: 当該領域実装者＋独立reviewer。

試験/成果: opaque Cのbyte-complete receipt；A/B停止とB2 fresh restore；復旧secret別保管・事前admission；partial/false receipt/lease reboot/closure欠損。

出口: operation集合/frontier/Blob/conflicts/tombstones一致；Cに平文keyなし、未認可Dは取得/復号できない；外部dependency遮断で同じ結果。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G4 — Hostile input & network
前提: G2。責任: 当該領域実装者＋独立reviewer。

試験/成果: drop/duplicate/reorder/replay；signed malformed/actor fork/control fork；aggregate quota/decode bounds；import/control/parser negative corpus。

出口: 侵害入力で共有状態が不正に進まない；攻撃者以外のSpaceに進捗余地あり。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G5 — Real Internet
前提: G3, G4。責任: 当該領域実装者＋独立reviewer。

試験/成果: IPv4/IPv6/CGNAT/UDP-blocked/relay；network change/reconnect；relay ingress capability quota；participant-only egress trace。

出口: 失敗経路はtyped reason、隠れたfallbackなし；claimed transport組合せの実環境記録。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G6 — Platforms & UI contracts
前提: G3, G4。責任: 当該領域実装者＋独立reviewer。

試験/成果: nativeOS/Swift/Kotlin個別lifecycle；Browser limited profile/storage；24状態UI galleryとa11y；Polish変更でcommand trace不変。

出口: public matrixと実機証拠一致；typed bindings/Unicode/FFI/threadingが同じ意味。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G7 — Security assurance closure
前提: G3, G4。責任: 当該領域実装者＋独立reviewer。

試験/成果: design + implementation independent review；各input fuzz campaign/replay；全Critical/High/未分類を閉包；修正後のindependent retest。

出口: 作者の自己評価だけでは通過不可；対象source/spec/featureのscope固定。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G8 — Scale/resources/soak
前提: G3, G4, G5。責任: 当該領域実装者＋独立reviewer。

試験/成果: 2/8/64/256profile benchmarks；7日Keeper soak+fresh restore；24時間mobile resume campaign；latency/CPU/RAM/bandwidth/disk分布。

出口: correctnessとbounded resourceを同時達成；未達targetはscope/性能公表へ反映、実測に偽装しない。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G9 — Upgrade and disaster recovery
前提: G3, G4。責任: 当該領域実装者＋独立reviewer。

試験/成果: store migration全境界crash；schema/epoch migrationとdraft保持；正常authority rotation；古いbackup/損傷DB/partial salvage。

出口: raw downgradeでデータ喪失なし；元store保全と新store検証を実証。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G10 — OSS release candidate
前提: G5, G6, G7, G8, G9。責任: 当該領域実装者＋独立reviewer。

試験/成果: signed artifacts/SBOM/licenses/provenance；clean-install quickstart；interop/export compatibility；保守窓口/release鍵/模擬advisory。

出口: 同一RC sourceに累積gate evidence；英文公開情報とsupported matrix完成。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## G11 — Production-qualified profile
前提: G10。責任: 当該領域実装者＋独立reviewer。

試験/成果: 全claim→最新evidence binding；project-owned service outage演習；known risk/support policy公開；release artifact readback検証。

出口: 対象profileの全必須要件PASS；未解決Critical/High/未分類なし；NOT_RUNを除外したように装わない。

証跡: source/spec/fixture/platform/toolchain、実行command、raw observations、result、review記録。該当しないplatformは承認されたprofile除外として記録し、別platformの合格を転用しない。

## 停止・再開

FAILは修正と再実行でのみ閉じる。BLOCKEDは前提不足の原因/解消手順/影響範囲を記録する。未実行をSKIPで隠さない。source/spec/lockが変わったgateはSTALEとして再評価し、旧evidenceはhistoryへ残す。実装者がverifierを変更したときはverifierの負例も独立確認する。
