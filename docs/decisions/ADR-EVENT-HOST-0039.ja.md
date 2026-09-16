# ADR 0039 — 同一所有者ループと条件付き通知

状態: 局所候補。元仕様は変更しない。

## 判断
署名/暗号/認可Storeを所有スレッドに保持するため、worker poolへDBを移さず、有界の協調mailboxを採用。asyncioのキューはthread-safeではないため、PID/thread/loopを検査する。公式仕様は https://docs.python.org/3.13/library/asyncio-queue.html と https://docs.python.org/3.13/library/asyncio-dev.html （2026-09-08 container-clockで参照）。
同期計算はloopを占有する。そのためasync化を性能保証・preemptionと呼ばない。新しい接続口を増やす前に、信頼済みownerの接続済みfdを使う埋込みアダプターとする。

## 却下
空pollの後に通知番号を取得する方式は、poll後のイベントを既に観測したことにして取りこぼす。単なるEvent.clear/waitも同様。毎回のpayload再送・無制限Future生成・callback正常終了の自動ackも採らない。

## 確認した修正
- 空poll後の変更: old ticketを返す負例で再現し是正。
- publish完了後の監査失敗: EVENT_OUTCOME_UNKNOWNへ固定。
- host close後のidle接続: shutdown通知を追加し、期限待ちを解消。
- 新型検査のrunnerが旧型契約を参照していた: 新規H0負例で検出し、new contractに訂正して実行。

## 残る境界
公開transport認証・暗号、native SDK、ブラウザー、remote ingest、共有世代移行、履歴GC、実Automergeは別工程。閉鎖/取消しはCOMMITや利用者の外部効果を取り消さない。

最終自己レビューで、ローカルAPIに返す空poll ticketと内部照合値のaliasを負例で再現。dictコピーで分離した。私有IPCは既にserializeしているためこのaliasを共有しないが、所有者API自体の防御を追加した。
