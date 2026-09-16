# 00.40 — 型付きローカル発行・結果照会

状態: **L-WP10部分実装 / local candidate**。公開API全体、ネイティブ、実CRDT、実機、独立レビューの合格ではありません。
入力authorityは `plan/NEXT_TYPED_EVENT_COMMANDS_0039.ja.md`。保存形式、既存の購読protocol `par-owner-event-host-0039`、明示ACKの意味は変えません。

## 二つの能力を分離する

購読用 `ConnectedEventChannel` は open/poll/ack/cursor/cancel/wait のままです。
新しい `ConnectedCommandChannel` は **publish/inquireだけ**、profileは `par-local-event-commands-0040`、frame envelopeはv1です。
同じEventHost/Journalを信頼したembeddingが選び、別の接続済みAF_UNIX streamを渡します。listener、相手発見、public socket、TLS、権限の遠隔発行はありません。

`serve_commands_connected(..., allow_publish=False)` の既定は照会のみ。発行はownerが明示的にTrueを渡した接続だけが使えます。
許可をJSONで自己申告しても昇格しません。この接続許可はJournalの現在の会員・epoch・署名権限を超えません。reader会員はTrueの接続でもpublishできません。
復号済みイベント本文が私有fdを通ります。fd継承・渡す相手・同一ユーザーの攻撃への保護・鍵の生存期間はembedding責任です。

## データ契約

helloと各要求はprotocol、app/space/stream、epoch、正確なschema/digest、issuer、journalGeneration、authorityを照合します。hostIdは所有者の起動ごとに変わるvolatile identityで、operation IDや永続cursorではありません。
operationIdは呼出側が保持する16-byte lowercase hex。event ID/parentは32-byte lowercase hex、sequenceはcanonical decimal stringです。
入力payloadは `{fieldName:{kind,value}}`。text/boolは厳密型、uint64/int64はdecimal string、bytesは偶数長lowercase hex（空bytes可）。Numberでu64を渡しません。符号・範囲・先行zero・余分なfield・重複parentを拒否します。

要求をキューへ保持する前にコピーし、循環・accessor・custom prototype・不正Unicode等を拒否。これは同一プロセスの悪意あるProxyや任意コードをsandbox化する仕組みではありません。

| 境界 | 既定または固定上限 |
| --- | --- |
| command接続 | 8、設定上限64 |
| 保留要求 | 全体16、接続ごと1 |
| 保留入力の合計JSON bytes | 131,072 |
| 1回のloop処理 | 2要求、同期DBの強制preemptionなし |
| frame | request 65,536 bytes / response 1,500,000 bytes |
| canonical event payload | 16,384 bytes、parent最大16 |
| 接続の出力キュー | 3 frames、framing correlation最大2 |
| TypeScript操作・Node要求の期限 | 各6,000ms、hello3,000ms |
| 所有者のread/write期限 | 各5秒、header+bodyの絶対read期限 |

これは個別キューの上限であって、プロセス全RSSや同期crypto/SQLiteの最大応答時間を保証しません。owner loopを占有する間、到着したcancel frameを割り込ませることはできません。idle接続も期限で閉じます。

## 結果と取消し

`EventCommands.publish()` の運用結果は以下のunionです。入力形式の誤りは `EventBindingError('COMMAND_INPUT_INVALID')` としてPromiseをrejectします。

- `local-committed`: original operationId、eventId、sequence、`replicated:false`、cancellationRequested。**ローカルJournalの確認のみ**。共有文書commit、他端末保管、CRDT適用の成功ではありません。
- `cancelled`: before-send、またはownerが確認したbefore-commit。後者でもnonce予約済みの場合があります。
- `outcome-unknown`: original operationIdとLOCAL_OUTCOME_UNKNOWN。送信後のabort、切断、期限切れ、不正応答、COMMIT後エラーから「未保存」と推測しません。
- `rejected`: stable code。権限・入力・前提違反など。文字列メッセージからretryを決めません。

`inquire(operationId)` はread-only。local-committed / not-found-local / rejected / 送信前cancelを返します。
**not-found-localは照会時点の不在であって、過去の未実行証明や再送許可ではありません**。照会の失敗・不明応答・使用不能Journalをnot-foundへ変換しません。

未知結果/通信失敗を経験したEventCommandsはterminalになり、次の要求をCOMMAND_RECONCILIATION_REQUIREDで拒否します。
closeして信頼した新しい接続に明示rebindし、保持していたoperationIdを照会します。SDKは再接続・照会・publishのいずれも自動実行しません。
同じID/同じ入力は既存receiptを返し、再予約しません。同じID/異なる本文またはparentはOPERATION_CONFLICTです。unknownを消すために新IDへ振り直さないでください。

ownerのnonce予約後cancelではnonceだけを保持しイベントを作りません。COMMIT後cancelでは保存済みイベントを削除しません。
テストは所有者cancel probeと実SIGKILLの両方を使います。probeによる取消しを、別processの同期処理へcancel frameが割り込めた証拠と取り違えません。

## embeddingへの組込み境界

Python側は既に開いたJournalと同じthread/asyncio loopで構成します。以下のjournal/sockは信頼したownerが渡す値で、この例は鍵の生成・接続認証を実装していません。

```python
from product.wp10.host import EventHost
from product.wp10.commands import EventCommandHost
from product.wp10.command_transport import serve_commands_connected

async def serve_owner_commands(journal, sock):
    events = EventHost(journal)
    commands = EventCommandHost(events)
    try:
        await serve_commands_connected(commands, sock, allow_publish=True)
    finally:
        commands.close()
        await commands.wait_closed()
        events.close()
        # Journal/AuthorityStoreは作成したownerが別途closeする。
        # attach以前に失敗したsockも呼出側がcloseする。
        sock.close()
```

TypeScript側のsocket/trustedContextはembeddingが渡します。helloだけを初回のtrust-on-first-use認可に使いません。

```typescript
import {EventCommands} from './product/wp10/lib/index.js';
import {ConnectedCommandChannel} from './product/wp10/node/command-channel.mjs';

const channel = new ConnectedCommandChannel(socket, {expectedContext: trustedContext});
let commands;
try {
  const hello = await channel.ready;
  commands = new EventCommands(channel, hello.context, hello.hostId);
  const result = await commands.publish(retainedTypedInput, {signal});
  // kindごとに表示。unknownでは同じoperationIdを保持し、明示再接続後にinquire。
  // publishやinquireで購読のdelivery.ack()を代行しない。
} finally {
  commands?.close();
  await channel.close();
}
```

ブラウザー・Swift・Kotlin・Rust向けには `EventCommandChannel.request(operation,args,signal): Promise<unknown>` に同じ結果を戻すadapterを実装する境界を用意しました。
そのadapter、origin/permission検査、FFI lifetime、suspend/resume、native compile/実行は今回未実装または未検証です。単なるinterface適合を認証やtarget PASSにしません。

## 実行できる入口

```bash
python3 tools/check_event_host.py
node examples/event_host_demo.mjs
node examples/event_host_demo.mjs --commands
python3 examples/event_host_workflow.py --only V-WP10
```

最後のlaneは同じsource上のH0-SELFTESTが前提です。全順序はSTART_HERE参照。
check_event_hostのcommand-owner/socket/node/channel/integration/types各suiteで分割可能です。
新規91 cases: Python owner30、socket9、Node SDK29、channel10、real Node/Python integration12、type contract1。旧host85 identitiesは変更しません。
Node unit/channelはprotocol opponentであり実storageではありません。integrationは別Python process、realSQLite、専用fd、実SIGKILLを用います。デモのfixtureは公開合成鍵・旧依存の明示実験opt-inです。利用者データでそのまま運用しないでください。

次工程は `plan/NEXT_EVENT_CLIENT_LIFECYCLE_0040.ja.md`。現在の純粋なcommand portを、明示的な再接続/照会/UI lifecycleへ組み込む作業を優先します。
