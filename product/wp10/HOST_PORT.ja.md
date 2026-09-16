# 00.39 所有者イベントホストと私有接続

L-WP10の部分実装。EventJournalと既存SDKの明示ack・再配送・正確な整数の契約を変更しない。
ローカル実ソケットによる候補であり、公開プロトコル、OSネイティブSDK、本番認定ではない。

## 実装の構成
`host.py`のEventHostは、既に開いたEventJournalを実行中のasyncioループへ接続する。DB・鍵・認可を別スレッドへ渡さない。
`transport.py`のserve_connectedは、所有者が接続済みのAF_UNIX/SOCK_STREAMとconsumer IDを渡す入口。listenerは作らない。
`src/host-port.ts`のGenerationEventPortは既存OwnerEventPortへ変換する。`node/channel.mjs`は注入された接続済みDuplexへ、上限付きフレームを送受信する。
データ用の標準入出力workerを製品transportへコピーしていない。統合試験では子プロセスの専用fd3を実ソケットとして使う。stdoutは公開fixtureの起動情報だけ。

## 信頼境界
接続fdの所持とconsumerへの対応付けは、信頼済みembeddingの責任。任意のネットワーク接続・未認証接続を渡してはいけない。
接続の追加暗号化や相手の署名認証は提供しない。復号したイベント値が私有IPCを通る。保存時暗号・権限検査とは別の境界である。
contextとhostIdの固定は取り違え拒否であり、受信JSONだけの暗号的証明ではない。同一ユーザーの敵対的コード、fd漏洩、whole-store rollbackは防がない。
この層の公開操作はopen/poll/ack/cursor/cancel/waitだけ。publishは所有者APIのままで、接続クライアントへ公開しない。

## 空pollと通知待ちの競合
1. pollの前に、観測済みの通知番号を取得する。
2. 空pollなら、その取得前の番号を結果へ付ける。poll後に新しいイベントを観測しても、番号を新しい値へすり替えない。
3. SDKは最後の空pollのticketだけをwaitへ渡す。途中のcursor照会で上書きしない。
4. waitはsession/incarnation/最後のticketを検証し、番号が進んでいれば即座にhintを返す。
5. 同じならwaiterを登録してから再観測する。登録と最終確認の間にawaitはない。
6. 所有者publish/notifyで起こす。直接のjournal操作や認可変化も、待機者がいる間だけ監査付きheartbeatで検出する。
7. deadlineによるwakeも単なるhintであり、イベントの存在・不存在・適用・ackを意味しない。SDKは再pollして検証する。

通知番号は揮発性u64、hostIdは起動ごとに新規。永続cursorや署名済みイベントIDとは別。再起動後は新しいport/sessionと、別途保管した検証済みcursorを使用する。

## 有界処理と取消し
通常要求はattach単位で同時1件。待機も要求枠として数えるが、dispatchを塞がない。全体既定32件/要求のserialized bytes 256 KiB。上限なら同期的に拒否し、空きを待つ無制限のpromiseを作らない。
取消し要求には各接続1枠を別に確保する。通常要求の予算が満杯でもcleanup可能。閉鎖時はqueue/waiter/session/payload参照を解放し、cursor/eventは残す。
1 turnで既定4要求を処理して次のturnへ譲る。FIFOの通常要求と優先cleanupを分離。永続処理中の同期I/O・暗号計算そのものの強制中断は保証しない。
queued/waiting Futureの取消しは未開始のdispatchを止める。開始済みackのCOMMITは巻き戻らず、既存SDKがACK_OUTCOME_UNKNOWNとして扱う。
終了通知は接続taskへ伝え、idle接続も閉じる。journalと認可Storeのcloseはembeddingが全接続taskの終了後に行う。

## 既定の上限
|対象|値|
|---|---:|
|attach接続数|16（設定上限64）|
|通常要求|32（設定上限128）|
|通常要求の入力合計|262144 bytes|
|cleanup|接続あたり1枠、通常予算とは別|
|接続内inflight|2|
|出力キュー|3フレーム＋送信中1フレーム|
|要求フレーム|65536 bytes|
|応答フレーム|1500000 bytes|
|wait hint期限|2秒|
|wait監査heartbeat|0.25秒、waiterがある時のみ|
|read/write期限|各5秒、フレーム全体。設定最大60秒|

OSソケットバッファ、JSON解析中の一時割当、複数フレームの生成、DBなどを含めたプロセス全RSS上限ではない。応答サイズは既存16KiB本文・最大32件の型付きbase64表現も収まるよう別設定。
idle read期限はクライアントが処理に時間を使っている間も進む。期限を過ぎるとsessionを閉じ、未確認バッチは再接続で再配送する。自動再接続/自動ack/暗黙のlease延長は行わない。

## 利用の骨格（既存Storeは所有者側で明示初期化）
```python
host = EventHost(opened_journal)
connection_task = asyncio.create_task(serve_connected(host, connected_unix_socket, fixed_consumer_id))
# この同じloop/threadだけで host.publish(...) / notify() を呼ぶ。
# 終了:
host.close()
await connection_task
opened_journal.close()
```
Node側は`ConnectedEventChannel(connectedSocket, {expectedContext})`のreadyを待ち、得たhostIdでGenerationEventPortを作り、既存EventSubscriptionへ渡す。fdとcontextを自己申告ネットワークから取得しない。

## 実行と証拠
`python3 tools/check_event_host.py`は85検査。Python owner27/socket10/hardening9、Node世代16/channel16、実所有者プロセス6、型1。
SIGKILLは未確認の再配送・ack COMMIT後の応答紛失の2ケース。fork拒否も実行。物理電源断や実ブラウザー/nativeの代わりではない。
`node examples/event_host_demo.mjs`は公開合成鍵の実SQLite/専用fdデモ。利用者DB・秘密鍵・外部ネットワークへアクセスしない。

所有者に返す空poll ticketと内部の照合用ticketは別のコピー。返却値の変更で内部チェックポイントを変更させない。

## 00.40での補足
この文書の購読operation集合は変更しません。owner APIのlocal publish/operation-ID照会は、別能力のcommand portに追加されています。`COMMAND_PORT.ja.md`参照。取得/ACK用channelにpublish権限が追加されたわけではありません。
