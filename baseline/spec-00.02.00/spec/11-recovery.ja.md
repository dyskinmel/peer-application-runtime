# 11 — 初期成功条件・復旧・可搬性

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 最初の成功条件 M1

単なるチャットの往復ではなく、中央サービスなしのbackend最小核を証明する。

| 名前 | 初期状態 |
|---|---|
| A | authority兼editor。ノート作成 |
| B | editor。独立にoffline編集 |
| C | opaque Keeper。閲覧鍵なし |
| B2 | 初期に認可済みの復旧用identity。通常は停止しsecretを別保存 |

A/B/Cは最初の稼働3端末。B2はwriter停止後、空のdata directoryで起動する復旧先。復旧検証時も同時に必要な稼働端末はC/B2だけ。B2の認可とkey packageを準備していない場合に、Cだけで新加入ができたことにしない。

## 2. 手順とoracle

1. 外部egressを遮断し、A/B/Cへの許可経路だけ残す。OS依存通信はPAR process/cgroupの測定と区別する。
2. AがSpaceとノートを作りB、C、B2の役割を確定。B2 key packageをCの復旧集合に含める。
3. A/Bを切断し、text編集、同じscalarへの別値、添付blob、1つのtombstoneを生成する。全operation IDsを保存。
4. A/B再接続でcausal frontier、values、conflicts、tombstonesが一致する。
5. Cへclosureを保管し、byte-complete receiptとA側のsemantic closure auditを確認。
6. A/Bを停止し、データへ到達不能であることを測定。B2は持ち込み禁止のdataを除いた空環境で起動。
7. B2が自分のrecovery secretとCのcontrol/key packages/blocksだけで復元。
8. B2の結果を凍結oracleと比較。本文だけでなく有効operation集合、frontier、添付hash、競合、削除が一致する。
9. Cの通常保存・ログから既知の平文sentinelが得られないことを検査する。
10. 未認可Dと間違ったkeyで同じ操作を試み、復元できないことを確認。

## 3. RecoveryState

`planning → authenticating → fetching-control → obtaining-keys → fetching-blocks → verifying-closure → rebuilding → review → activated`。

各段階にpause/resumeとprogress内訳を持つ。復旧先の既存データを上書きする操作は既定にしない。完了は全必要bytes・署名・AEAD・schema・frontierを検証し、ローカルstorageへcommit後。UIに「100%ダウンロード」と「復旧完了」を混同させない。

再開可能なrecovery journalはtarget root、authorized identity、input/export digest、検証済みblock集合、未解決理由を持つ。別rootに変われば別sessionへ移す。

## 4. 復旧モード

| モード | 必要条件 | 結果 |
|---|---|---|
| 同端末DB再構築 | 鍵が健全、raw blocksが残る | 新DBへindex/materialized viewを再生成 |
| 新端末へ復旧 | 事前認可IDまたは稼働authority、必要secret | 認可範囲だけ復元 |
| 暗号化data import | 公開export形式＋検証可能なkeys | sourceへ触らず新保存先へ復元 |
| 部分サルベージ | 一部blocks/keysのみ | 完全復旧とは別の明示partial export |
| authority危機 | chain確認/正常移管が不可能 | branch保全と新Space移行 |

部分復旧は欠落object一覧と理由を必須にする。関連blobが壊れた場合も本文だけを「全体復元」と呼ばない。

## 5. export形式

`export.json`にはformat version、AppId、SpaceId、選択epoch、control head、profile/codec/suite、root manifests、file inventory digest、作成条件、history範囲を含める。全objectはcontent-addressed pathに置き、relative pathだけ許可。path traversal、symlink、case collision、ZIP bomb、過大宣言をimport前に検査する。

復旧秘密は別bundle。data exportのrecipient key packageは含めるが秘密鍵は入れない。export中のlive更新はsnapshot tokenで切り、追加分は別incremental exportにする。

## 6. 復旧不能の扱い

「鍵がない」「データが足りない」「peerが今いない」「profile不明」「認可がない」を別reasonにする。復元に必要な追加物と既に回収できたものを表示し、何度同じボタンを押しても状況が変わらないときは自動retryを止める。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-REC-001"></a>
### PAR-REC-001 — M1縦断
**MUST:** A/B停止後、事前認可B2がCと別保管の復旧材料だけから完全な対象frontierを復元できる。
受け入れ: `AT-REC-001` / 最初の必須gate: `G3`。

<a id="PAR-REC-002"></a>
### PAR-REC-002 — 鍵なしKeeper
**MUST:** opaque Keeperには閲覧keyを渡さず、通常保存・診断に本文が残らない。
受け入れ: `AT-REC-002` / 最初の必須gate: `G3`。

<a id="PAR-REC-003"></a>
### PAR-REC-003 — 復旧再開
**MUST:** recovery journalをroot・identity・input digestに束縛し、中断後に検証済みblockを再利用する。
受け入れ: `AT-REC-003` / 最初の必須gate: `G3`。

<a id="PAR-REC-004"></a>
### PAR-REC-004 — 完了の条件
**MUST:** download完了ではなく署名・AEAD・dependency・schema・local commit完了でactivatedにする。
受け入れ: `AT-REC-004` / 最初の必須gate: `G3`。

<a id="PAR-REC-005"></a>
### PAR-REC-005 — import防御
**MUST:** export path・総bytes・展開比・重複名を検査し、既存保存先へ無断上書きしない。
受け入れ: `AT-REC-005` / 最初の必須gate: `G9`。

<a id="PAR-REC-006"></a>
### PAR-REC-006 — 部分結果
**MUST:** 部分サルベージは欠落集合を示し、完全復旧や全権限回復と表示しない。
受け入れ: `AT-REC-006` / 最初の必須gate: `G9`。
