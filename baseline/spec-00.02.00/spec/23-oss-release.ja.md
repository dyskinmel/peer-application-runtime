# 23 — 完全OSS・供給網・公開と維持

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 公開範囲と独立性

core、SDK、protocol、schema、tests、Keeper/Relay、診断/復旧CLI、UI kit、reference appを同じ公開原則で扱う。E2EE/backup/export/self-hostingの核心を非公開版へ隔離しない。production runtimeにproject-owned account/API key/license serverを要求しない。ブランド・ドメイン・署名鍵とprotocol互換は分け、forkが異なる名前で動くことを妨げない。

Apache-2.0を本プロジェクトの推奨ライセンスとする。[S23] 本仕様bundleには同ライセンス本文を収録する。引用/第三者仕様や依存ライブラリの権利を再許諾したと主張しない。製品名は仮称で商標調査未実施。貢献受付はDCO等の権限確認を候補とし、不要な全面著作権譲渡を要求しない。

## 2. build/release

依存lock・toolchain・feature flagsを固定し、clean environmentからsource→binary→packageの出所を記録する。署名は誰がどのartifactに署名したかを示し、ソフトウェアの正しさを証明するものではない。SBOM、license inventory、NOTICE、source archive、checksums、署名、provenance、対応platform matrixをreleaseごとに公開する。

SLSA v1.2のbuild provenance要件を参考に、最初は実施したcontrolsを個別に開示する。未評価のSLSA levelを取得済みと表示しない。[S18] 依存脆弱性scanはlockとDB更新時刻を保存し、severityだけでなく実際に該当するfeature/pathを評価する。

自動update機構はcoreの必須条件でなくhost責務。提供する場合はroot/update権限分離、threshold、expiry、rollback/freeze対策、root rotation、offline検証を仕様化する。TUFはこれらの脅威への参照設計になる。[S19] 既定offline runtimeにupdate checkのネットワーク通信を埋め込まない。

## 3. release channels

`experimental`は未freeze wireと互換破壊を許すがexportを残す。`alpha`は最初の機能統合、`beta`は機能scope固定とmigration rehearsal、`rc`は同一source/toolchain上の全gate閉包、`stable`はqualified profileに限定する。すべての公開packageにmaturity badgeとknown limitsを入れる。

1.0で必須にするのはnative core＋Keeper/Relay、Swift/Kotlinのinteractive、DX/docs/復旧/セキュリティ。Browserは独立profileの合格範囲だけをclaimする。Browser全機能未達をnative合格に紛れ込ませない。正式scopeを小さく見せるため実装済みの危険なpathを隠すこともしない。

## 4. governanceと保守

RFC提案→public議論→maintainer決定→ADR→compatibility test→release noteの経路を設ける。crypto/wire/authの変更には領域reviewerを必要とし、一人の作者だけでmerge/releaseを完結させない。最初に複数maintainerを確保できない場合はその事実を公開し、stable gateは未充足とする。

support policyの候補は現行stableと直前minorを最低12か月の範囲で保守すること。ただし実際の開始日・対象版・responsible maintainer・emergency手順をG10で固定して初めて対外約束する。project shutdown時もsource/spec/export formatとself-hosting手順が残るよう、複数mirrorとoffline docsを用意する。

## 5. 初心者の受け入れ

release artifactだけを入手した新規環境で、cloud登録なしの2台編集、Keeper追加、診断、backup、fresh restore、uninstallを実施する。READMEのcommandはCIで実行し、secretや巨大build cacheをZIPに含めない。英文protocol/spec要約と日本語導入手順を公開前に整備する。本版の詳細本文は日本語草案であり英文正本完成とは扱わない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-OSS-001"></a>
### PAR-OSS-001 — 全機能OSS
**MUST:** 利用に必須なSDK/keeper/relay/auth/export/診断のsourceとprotocolを公開対象にする。
受け入れ: `AT-OSS-001` / 最初の必須gate: `G11`。

<a id="PAR-OSS-002"></a>
### PAR-OSS-002 — artifact provenance
**MUST:** releaseをsource/toolchain/lock/feature flagsと署名・SBOMへ結び付ける。
受け入れ: `AT-OSS-002` / 最初の必須gate: `G10`。

<a id="PAR-OSS-003"></a>
### PAR-OSS-003 — update trust
**MUST:** 更新を提供する場合はroot/rollback/freeze/expiry検証を持ち、core起動と分離する。
受け入れ: `AT-OSS-003` / 最初の必須gate: `G10`。

<a id="PAR-OSS-004"></a>
### PAR-OSS-004 — 公開claim
**MUST:** channel/qualified platform/未検証feature/known limitationsをartifactへ同梱する。
受け入れ: `AT-OSS-004` / 最初の必須gate: `G11`。

<a id="PAR-OSS-005"></a>
### PAR-OSS-005 — 保守体制
**MUST:** security/crypto reviewとrelease承認に独立担当と公開support policyを持つ。
受け入れ: `AT-OSS-005` / 最初の必須gate: `G10`。

<a id="PAR-OSS-006"></a>
### PAR-OSS-006 — 導入再現
**MUST:** 新規環境で文書の導入/backup/restore/uninstall手順を実行する。
受け入れ: `AT-OSS-006` / 最初の必須gate: `G10`。
