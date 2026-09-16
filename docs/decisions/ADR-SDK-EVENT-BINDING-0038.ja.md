# ADR 0038: 確認付きイベントbatchと最新snapshotを分離する

状態: 実装候補。本番/全SDKの資格ではない。元仕様は変更しない。

- JavaScriptはAsyncIterableIterator<Delivery>。Deliveryは順序付きeventsと明示ack()を持つ。batchを受け取っただけではcursorを進めない。未ackでnextを呼ぶとACK_REQUIRED。pollの再呼出しはホストで再認可して同じbatchを返す。for-awaitからbreakしても確認はしない。
- contextはapp/Space/stream/epoch/schema/issuer/consumer/journal generationを所有者が別途固定。sessionはopen応答で固定し、以後変更不可。u64/i64は境界でcanonical decimal、利用側ではbigint。bytesはhexとしてimmutableに渡す。
- ackは送信後例外・取消し・不正応答ならACK_OUTCOME_UNKNOWN。自動再試行なし。古いsession tokenは破棄し、最後に検証したcursorをpinして再接続。poll/ack/closeの結果を取り違えない。
- close/AbortSignalは配信を直ちに止め、未処理応答を破棄する。ホストの取消し応答を期限内に待つが、同期native処理を強制停止できない。late-open時の購読cleanupも試みる。既配信の本文/side effectは取り消せない。
- 最新snapshotはrevisionを持つメモリー内capacity=1。イベントとは別クラス。連番が飛んでも最新への集約であってイベント欠損ではない。TTL/presenceの永続化なし。
- Python EventOwnerPortは同じEventJournalを所有するスレッドで呼ぶ。pollごとに既存の署名/暗号/認可を検査、ackは元の永続cursor処理を使う。fixture IPCは公開・合成データ用試験だけで製品transportではない。

参照（2026-09-07取得、API契約確認）: MDN AsyncIterator https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/AsyncIterator ; AbortSignal https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal 。Abort listenerは成功/失敗/取消しの全出口で解放。実Automerge https://github.com/automerge/automerge/releases の取得確認は別gate。
