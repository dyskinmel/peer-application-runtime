# 15 — プラットフォーム能力・実機資格

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 機能を偽装しない共通API

APIの意味を共通化しても、OSが許す動作は異なる。`RuntimeCapabilities`はplatform、storage class、key protection、available transports、background modes、role eligibility、known restrictionsを返す。

| profile | 対象 | 本番資格に必要な証拠 |
|---|---|---|
| native-interactive | Linux/macOS/Windows | 実process同期、保存・休止・鍵・更新 |
| native-keeper | Linux/macOS/Windows headless | retention/lease/容量/サービス再起動 |
| native-relay | 到達可能な指定host | ingress認可、帯域制限、実経路 |
| ios-interactive | iPhone/iPad | 実機background/suspend/resume、鍵ロック |
| android-interactive | Android | 実機Doze/App Standby、強制停止、metered |
| browser-interactive | Chromium/Firefox/WebKit | 実browser/native互換、quota、tab lifecycle |

資格は各profile別に付与。native合格でmobile/browserをまとめてPASSにしない。

## 2. OS version policy

正確な最低OS/SDK versionはG6 qualification matrixへ列挙する。候補のAPI存在とshipping supportを区別し、未試験versionの番号を宣伝に固定しない。current stableと直前の主要版を評価対象とする運用方針を提案するが、release時に具体的build番号・deviceを記録する。

初期基盤実装はLinux nativeを主laneにし、macOS/Windowsを同時に契約評価する。OSのない環境で書いたsourceを対応済みとせず、残るlaneをBLOCKED/NOT_RUNで保持する。

## 3. iOS

foreground編集と復帰時同期を核にする。background taskはOSが認めた枠で未完保存・短い同期を進める補助であり、永続relayに使わない。[S13] key vaultがlock中なら暗号化保存・同期の可能範囲を明確にし、平文鍵を保護の弱い場所へfallbackしない。

参照UIはpermissionを必要な操作時に要求。LAN拒否、通知拒否、カメラ拒否でもmanual invitationとlocal編集を提供する。音声/位置情報等の無関係なbackground modeで制約を回避しない。

## 4. Android

Doze/App Standby等でnetwork/jobが遅れることを前提とする。[S14] WorkManager等への委譲は再開可能operationに限る。通常利用のためにbattery optimization除外やforeground service常駐を強制しない。

プロセス停止・boot・lock・充電・meteredを組み合わせて試験する。foregroundの編集と、ユーザーが明示選んだ資源協力を別budgetにする。

## 5. Browser

WASM core＋JS hostで、native-only socket/file/key APIを隔離。IndexedDBのtransaction durabilityとpersistent storageの許可は別情報であり、storage evictionやorigin削除を無視しない。[S15]

multi-tabはtransactional fencingとactor ownershipを確認。page freezeでmonotonic/sessionが変化したら、lease・presence・connectionを再評価する。Web Workerもページ終了後の永続サーバーとは扱わない。

web配布はHTML/JSを取得する経路を必要とする。最初のロード経路まで不要だと称さない。offline配布可能なstatic bundleを提供し、既定でCDN/font/analyticsを外部取得しない。CSP、Trusted Types対応、untrusted text escapingを試験する。

## 6. 通知

APNs/FCMはoptional external-assisted。push hintに本文/秘密を入れず、送信資格情報を利用者の全端末へ配布しない。未配信でもforeground再開で同期できる。即時通知SLOを参加者限定profileへ混入しない。

## 7. packaging

Apple/Windowsの署名、Linux package、browser assetsにはdistribution provenanceを付ける。notarization/store審査とruntime安全性を同一視しない。headless serviceは管理者が指定したdirectory/portだけを使い、root権限を既定要件にしない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-PLAT-001"></a>
### PAR-PLAT-001 — 能力表
**MUST:** platformごとのstorage/crypto/transport/background能力を機械可読にし、非対応を明示する。
受け入れ: `AT-PLAT-001` / 最初の必須gate: `G6`。

<a id="PAR-PLAT-002"></a>
### PAR-PLAT-002 — mobile再開
**MUST:** mobileで常時networkを前提とせず、suspend/restart後に未送信commitから再開する。
受け入れ: `AT-PLAT-002` / 最初の必須gate: `G6`。

<a id="PAR-PLAT-003"></a>
### PAR-PLAT-003 — browser保存
**MUST:** browser transaction完了と保存永続化許可・evictionリスクを分離して返す。
受け入れ: `AT-PLAT-003` / 最初の必須gate: `G6`。

<a id="PAR-PLAT-004"></a>
### PAR-PLAT-004 — 最小権限
**MUST:** LAN/カメラ/通知の拒否時も代替導入とlocal操作を提供し、無関係権限を要求しない。
受け入れ: `AT-PLAT-004` / 最初の必須gate: `G6`。

<a id="PAR-PLAT-005"></a>
### PAR-PLAT-005 — web供給経路
**MUST:** browser assetの配布依存を公開し、defaultで外部script/font/telemetryを読まない。
受け入れ: `AT-PLAT-005` / 最初の必須gate: `G10`。

<a id="PAR-PLAT-006"></a>
### PAR-PLAT-006 — 版別資格
**MUST:** 実際のOS build・device・browser versionをevidenceへ束縛し、support matrixをreleaseごとに更新する。
受け入れ: `AT-PLAT-006` / 最初の必須gate: `G11`。
