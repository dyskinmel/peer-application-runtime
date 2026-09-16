# ADR-0021: 管理ジョブは原子操作の仮装ではなく、既存証拠の照合器

状態: 実装済みローカル候補。元規範00.02.00は不変。独立レビュー未実施。

## 選択
同期処理を別threadで実行すると現在の単一writer/thread契約と衝突するため、所有threadの明示stepを選択。4種類のadapterだけを登録し、管理socketは追加しない。署名済み入力と既知authority/windowを固定する。毎回ライブ状態を検査し、署名cacheを認可cacheへ拡大しない。

EXECUTINGの永続化を取消不可境界にする。実処理とjournalは別保存領域なので、結果紛失ではOUTCOME_UNKNOWN。独自job記録だけで成功を認定せず、ターゲットの履歴へ照合する。証拠がない場合も自動再送しない。過去の完了照会は現在の新規操作許可とは別。

## 比較
memory-only queueは中断後にdispatch有無を失うので不採用。任意method dispatchは権限/作用が曖昧になるので不採用。別process workerは将来の候補だが、所有権移管を設計する前には入れない。append-only logは魅力があるが、有限signed envelopeを既存部品で検査する方式から始める。大archive書き直しのI/O費は明示して残す。

## 負例からの修正
- event上限でeffect後の結果を記録できない: 実行前に3event分を確保。
- pollから既知job消失/unknown fileを検出しない: 全操作の入口で有界完全照合。
- version boolとintegerを同じ設定とみなす: canonical bytesで比較。
- persistence exceptionがraw OSError: typed JOB_JOURNAL_UNCERTAIN、poison、reopen。
- 保存領域全体の削除/rollback: 外部Pinを提供。ただし外部Pinも戻された場合は保証外。

## 変更していない境界
既存ReplaySpool/RetiringSpool/Keeper/IPC/暗号sourceを変更しない。cancelは別callerの権限を失効させない。強制killは電源断ではない。live host scheduling未実装、G0〜G11未合格。

参考: Python os.fsync/os.replace、SQLite atomic commit。参照は [資料一覧](../sources/MANAGEMENT_JOBS_SOURCES.md)。ディレクトリ同期が全FS/媒体の耐電源断を自動認定するとはいえない。
