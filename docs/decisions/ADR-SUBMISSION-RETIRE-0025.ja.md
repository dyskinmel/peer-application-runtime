# ADR-SUBMISSION-RETIRE-0025: 二者承認・対象固定の登録payload回収

状態: LOCAL CANDIDATE（本番の暗号/プロトコル凍結ではない）。元仕様85filesは不変。

## 採用
登録はジョブ台帳の更新、回収は登録用の重複payloadのunlinkであり、別責務とする。現在のcontroller署名だけで過去の全登録を削除できる機能は作らず、元descriptor作成者の承認も必要とする。同じ鍵の場合も別domain署名。

元stageのバイト列と対象ファイルのhash/size/identityをINTENTへ固定する。unlink→directory同期→結果永続化の順で進め、TOMBSTONED時だけ論理payload予約を返す。stageと署名sidecarは再送拒否の根として維持する。期待ファイルの消失は、署名INTENTが既にある場合だけ中断復旧として扱い、新規要求の確定済みprefix欠損は拒否する。

INFLIGHTの「jobがない」は登録不許可と同義ではない。二者承認の明示照合APIは台帳とpayloadの対応を検査するだけで、submit/retry/selectを呼ばない。REGISTEREDのpayload消去後は台帳から入力を再構成する。target状態も元descriptorと一致させる。

## 互換
旧領域でsidecarを作って旧ホストが無視する方式は却下。形式2へ明示移行し、旧ホストをfail-closedにする。新規ホストは同じ登録wire/serverを再利用できるが、遠隔削除methodは増やさない。基盤の暗号・通信・Storeは変更しない。

## 再承認と停止
current revisionの変化は停止条件。8承認まで固定targetへrebindし、旧/新両方の履歴を検査する。新規の削除範囲を追加できない。元鍵紛失への代理手続と記録compactは未設計として別gateに残す。

## 検証の意味
Linux/Python合成データで正常・負例・実SIGKILL・実Unix socketを確認。物理power-loss、署名付き受領の第三者認定、同一UID任意コード/全体rollbackを保証しない。

## 一次資料（2026-09-06確認）
- https://man7.org/linux/man-pages/man2/fsync.2.html — ファイル同期だけではdirectory entryを同期したことにならない。
- https://sqlite.org/wal.html — 既存環境のSQLite修正確認は別。使用許可を本番保証へ昇格させない。
