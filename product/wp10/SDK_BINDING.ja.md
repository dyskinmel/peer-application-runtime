# イベントSDK接続 — 00.38.00候補

`src/`がTypeScript正本、`lib/`が同梱生成物。追加npm依存なし。`sdk.py`は既存EventJournalを所有する同一スレッドのアダプター。新しいネットワークプロトコル/公開サービスではありません。UIと共有文書の保存・CRDT状態は変更しません。

## 所有者が注入するポート

`EventSubscription.connect(port, expectedContext, options)`。expectedContextは信頼したホストから、別途固定します。app/Space/stream/epoch/schema/issuer/consumer/journal generationを必須とし、以後全応答と照合。JSONやschemaDigest自身を署名の証拠とは扱いません。Python所有者が各poll/ackで実DB・暗号・認可を検査します。SDK内で認可を発行しません。

ポートはopen/poll/ack/cursorRead/cancel/waitに限定します。`EventOwnerPort`の同期呼出しをto_threadへ渡してはいけません。新しい購読は新しいadapter/sessionとし、古いtokenを再利用しません。Native/FFI/ブラウザーの実transport接続は未実装です。

## batch単位のAsyncIterable

```ts
import {EventSubscription} from './product/wp10/lib/index.js';
const subscription = await EventSubscription.connect(ownerPort, trustedContext, {
  expectedCursor: separatelyRetainedCursor, limit: 16, byteLimit: 262144, signal
});
try {
  for await (const delivery of subscription) {
    for (const event of delivery.events) await processIdempotently(event.eventId, event.payload);
    const cursor = await delivery.ack(); // 処理後に明示。next/returnはackしない
    await retainCursorOutsideJournal(cursor);
  }
} finally { await subscription.close(); }
```

上の関数・ポートは利用するホストが提供する契約であり、製品が外部side effectとackを原子的に行う例ではありません。実行可能な合成データのデモは`node examples/event_binding_demo.mjs`です。

`poll()`は空ならnullを返す。空=終端/削除/オフラインではありません。`next()`は空ならhostのwaitを待ち、再pollします。waitは取りこぼさない非同期通知をhostが実装し、abortに協調します。即座の偽wakeでも25msの最小間隔を入れ、microtaskの無限busy loopを防ぎます。データをyieldした後はprefetchせず、未ackのままnextするとACK_REQUIRED。手動pollの再呼出しはhostで再検証した同じbatchを返します。

一つのbatchだけが未確認。最大32件、ネイティブpayload最大512KiB、一イベント16KiB。デコード済み応答の構造にも上限。通信前のフレーム上限はhost transportの責任で、このポートは任意の巨大objectの生成をOSで防ぐものではありません。同時poll/next/ack/checkpointはBUSY。callbackの正常終了・for-awaitの次反復・break/例外を受信確認に変換しません。

## 正確な整数・不変の入力

u64/i64とsequence/cursor/revisionは境界ではcanonical decimal string。JavaScript利用側の整数はbigint。Numberへ変換しません。バイト列は境界/イベントpayloadではhex。提供するevents/payload/parentsは不変、snapshotのUint8Arrayは入力・出力でcopyします。型宣言とruntimeの型・配列・descriptor・上限検査を両方行います。custom prototype/accessorを拒否しますが、同一JSプロセスの敵対的Proxyやコードへのサンドボックスではありません。

## ack、取消し、結果不明

ack結果は同じcontext/session、配信終端event、正確なposition、revisionの増分と照合。ack呼出し後の例外・取消し・不正応答はACK_OUTCOME_UNKNOWNで以後の配送を停止します。永続cursorが進んだ可能性があるため、自動ack再試行はしません。closeして新しいポートへ再接続し、最後に検証したcursorをexpectedCursorとして照合します。前のpinより先なら再開でき、後退・同じ位置で内容変更なら拒否。既処理のイベントが再配送された場合はevent IDで重複を扱ってください。

AbortSignal/return/closeで新しい配信を止め、遅れて返る値を破棄します。Promiseが解決した後でも、呼出し元へ返す直前に取消しを再確認します。ack中の取消しはcursorが進まなかった証拠ではありません。既配信の本文や利用側のside effectは巻き戻せません。

closeは独立した期限付きcleanupを試み、ackはしません。hostが拒否/期限超過した場合CANCEL_OUTCOME_UNKNOWN。既定1000ms、設定10〜10000ms。late-openも検証したsessionをcleanupします。タイマー/abort listenerは完了時に解除。native同期処理そのものを強制停止する保証はありません。終了結果も確認してhost側資源を管理してください。

## 最新snapshotは別API

`LatestSnapshots`はvolatile capacity=1。`publish(revision, bytes)`を受け、遅い利用側には最新を返す。revisionの後退、同revisionの異内容を拒否。ackや永続cursorはありません。最新値への集約をdurableイベントの欠落に転用しません。presenceは以前の揮発性hintのままで、今回は新しいネットワーク接続を追加していません。

## 検証範囲と再開

`python3 tools/check_event_binding.py`はPython所有者、Node契約、型契約、実SQLiteを持つ別Pythonプロセスとの統合を実行。テスト用stdin/stdout bridgeは公開・合成鍵のみ、同じprocess groupで動作し、製品transportではありません。応答紛失・ownerのSIGKILL（ack前/ack COMMIT後）・再起動・認可変更を試験。物理電源断、実CRDT、native SDK、実ブラウザー、ネットワーク配信、GC、鍵管理、本番資格は未実証。

旧EventJournalコードと永続形式は変更せず、ackと外部処理、認可DBとイベントDBが別トランザクションである制約を維持します。REG-0033の過去の通信間欠失敗と、過去証跡457件の欠損も未解消です。
