# 16 — 資源制御・負荷・保管の公平性

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 二つの資源予算

自身の編集・閲覧を`interactive budget`、他人の保管・中継・計算を`contribution budget`とする。後者は既定0。自身のlocal保存にまで他人向けquotaを流用して説明不能な失敗を起こさない。

budgetはruntime/Space/peer/operation別。CPUは実時間、memoryはresident/allocator観測、storageは予約＋実使用、bandwidthは送受信別bytesとして計上。通信速度の自己申告だけを信用しない。

## 2. 許可する操作

許可はSpace allowlist、role、保存最大量、転送上限、metered許可、外部電源条件、実行時間帯で構成。pauseはすぐ新規負担を止める。既存leaseへの影響はREP規範に従う。

資源提供をしないユーザーも通常の利用者であり、強制計算や広告的な招待spamを受けない。複製目標未達は率直に示し、参加者に無断でクラウドへ保存しない。

## 3. admissionとbackpressure

大きい操作は開始前に予約し、実使用との差を精算する。予約の重複はoperation IDで排除。操作が上限を越えたらbounded errorを返し、メモリーを積み増し続けない。

個別peerへのrate limitingだけでなく、account/Space/connection群のbudgetも持つ。IDを増やせば資源制限を回避できる仕様にしない。ただし匿名Sybil耐性の全解決とは言わない。

## 4. 公平性と劣化

controlとsmall interactive changesを優先し、大blobはchunk境界でyieldする。pressure順はbackground repair停止→blob並行数削減→新規retain拒否→interactiveの明示backpressure。保存済みデータの無断evictや署名検証の省略で性能を稼がない。

熱/電池/回線条件が悪化したらcontributionをpauseし、停止理由と再開条件を表示。remote peerへ詳細な電池残量を公開する必要はなく、利用可能capacity classだけ伝える。

## 5. quotaの説明

UIにはused/reserved/pinned/lease-protected/reclaimableを分けて表示。「空きを作る」で消える範囲のpreviewを出す。データ量とpeer数から費用ゼロを約束しない。長期保管の物理容量は複製・履歴・修復余裕を含む。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-BUDGET-001"></a>
### PAR-BUDGET-001 — 二予算
**MUST:** interactiveとcontributionを別予算にし、第三者負担を既定0とする。
受け入れ: `AT-BUDGET-001` / 最初の必須gate: `G3`。

<a id="PAR-BUDGET-002"></a>
### PAR-BUDGET-002 — scope制限
**MUST:** runtime/Space/peer/operationの階層quotaを適用し、予約を原子的に管理する。
受け入れ: `AT-BUDGET-002` / 最初の必須gate: `G4`。

<a id="PAR-BUDGET-003"></a>
### PAR-BUDGET-003 — 劣化時公平性
**MUST:** 大blob/repair圧力下でもcontrolとinteractiveを優先し、署名検証を省略しない。
受け入れ: `AT-BUDGET-003` / 最初の必須gate: `G8`。

<a id="PAR-BUDGET-004"></a>
### PAR-BUDGET-004 — 使用量表示
**MUST:** used/reserved/pinned/lease-protected/reclaimableを区別し、削除前に影響を示す。
受け入れ: `AT-BUDGET-004` / 最初の必須gate: `G6`。

<a id="PAR-BUDGET-005"></a>
### PAR-BUDGET-005 — 電力と回線
**MUST:** 条件変更でcontributionをpauseし、再開条件をtyped statusにする。
受け入れ: `AT-BUDGET-005` / 最初の必須gate: `G6`。
