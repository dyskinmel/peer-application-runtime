# 21 — 性能・規模・長期運用の検証計画

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 高品質を測る条件

以下は**設計目標と試験workload**であり実測値でも性能保証でもない。hard protocol bounds、運用上のsoft budget、製品で公表するqualified envelopeを分離する。数値の達成状況はOS/build/CPU/RAM/storage/network/thermal/loadを持つrecordで初めて表現できる。

| lane | workload候補 | 主なtarget |
|---|---|---|
| L-small | 2 editors、1,000 docs各4 KiB、1 change ≤4 KiB、native SSD、RTT≤20ms | local commit p95≤25ms/p99≤100ms、active peer可視化p95≤500ms |
| L-team | 64 memberships、8 concurrent writers、10,000 docs、20 changes/sec、RTT100ms/loss1% | steady-state可視化p95≤2s、30分負荷後にqueueが収束 |
| L-scale | 256 memberships、16 concurrent writers、100,000 metadata records | 中断/再開、bounded RAM、fairness、full catalogの時間/bytesを報告 |
| L-history | 1 doc 100,000 changes、30/90日offline相当のsynthetic履歴 | native peak working set512MiBを初期予算、超過はpause/split案、データ破壊禁止 |
| L-mobile | 実機 foreground/resume、10,000 local docs、Wi-Fi/cellular切替 | warm openでlocal一覧p95≤250ms、typing feedbackp95≤50ms |
| L-recovery | 1 GiB logical dataの多数Blob、20 MiB/s測定経路、8GiB RAM | end-to-end取得・検証・再構築時間を分離、peak memoryと増幅率を測定 |

各laneのhardwareはG8開始時に固定する。今は特定端末で達成した値ではない。Blob単体上限256MiBとaggregate1GiBは矛盾しない。100,000件はmetadata索引の試験であり全本文を常駐させない。

## 2. 最も重要な守る順序

データの正しさ・認可・local durabilityを削って速度を出さない。負荷超過時は、contributionの新規受付減→repair減→blob延期→interactiveのbackpressureという順で反応する。controlと復旧用の最低予算を確保し、過負荷でもstatus query/cancel/export-planが飢餓しない。

合格は単なる平均改善でなく、latency分布、resource slope、commit loss数、authorized operation-set完全性、recovery成功率を併記する。lock contention、CPU crypto、CRDT decode、SQLite sync、network waitを分解して測定する。

## 3. 長期・障害試験

RCのnative Keeper laneは7日連続soakを初期release条件にする。毎日network flap、peer churn、disk pressureを入れ、最終日にclean restoreを行う。期間は実行記録から測る。仮想時計7日を現実の7日soakとして数えない。モバイルは24時間のsleep/resume実機campaignを別に行う。

2/8/64/256 participant profileで、partition、reorder、loss、bandwidth cap、clock skew、重複、slow peer、private-but-malicious peerを分離して試す。シミュレーションは構造的raceを探す証拠であり、実回線のNAT成功率の代用にしない。

## 4. SLOの扱い

decentralized peer population全体に一律99.99% uptimeを約束しない。community Keeper運用者は、自分のpeer reachability、直近のroot取得検査、resource予約、repair lagをSLIにできる。取得可能なauth/key/sourceと容量がある条件下でのみRTOを測る。RPO=0はlocal acknowledged commitに対する**定義済み障害範囲**に限る。元端末喪失前に複製されていないデータのRPOを0と呼ばない。

## 5. regression policy

baselineはsame workload/hardware class/configで比較する。RCはp95/peak memoryの10%以上の悪化を要レビューとし、自動失格とは別に原因を記録。安全性修正の必要な費用を隠すためbaselineを勝手に更新しない。単発の外れ値と持続的な悪化はraw seriesで判断する。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-PERF-001"></a>
### PAR-PERF-001 — 性能の前提
**MUST:** benchmarkにhardware/OS/profile/workload/network/母数と分布を記録し、目標を実測と表現しない。
受け入れ: `AT-PERF-001` / 最初の必須gate: `G8`。

<a id="PAR-PERF-002"></a>
### PAR-PERF-002 — 正しさ優先
**MUST:** 負荷試験中もACK済みoperationの完全性とauth invariantsを検査する。
受け入れ: `AT-PERF-002` / 最初の必須gate: `G8`。

<a id="PAR-PERF-003"></a>
### PAR-PERF-003 — 規模の表示
**MUST:** 対応規模を検証profileごとに公開し、membershipとconcurrent connectionsを分ける。
受け入れ: `AT-PERF-003` / 最初の必須gate: `G11`。

<a id="PAR-PERF-004"></a>
### PAR-PERF-004 — 長期soak
**MUST:** 指定soakの実時間、障害注入、終端のfresh restoreを記録する。
受け入れ: `AT-PERF-004` / 最初の必須gate: `G8`。

<a id="PAR-PERF-005"></a>
### PAR-PERF-005 — 条件付き可用性
**MUST:** uptime/RTO/RPOに対象データ・障害・source/key availabilityの条件を明記する。
受け入れ: `AT-PERF-005` / 最初の必須gate: `G11`。
