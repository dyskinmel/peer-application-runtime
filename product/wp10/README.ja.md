# ローカルイベント・購読 00.37.00

**部分的なSDK候補。実ネットワーク、Swift/Kotlin/Rust、実機、本番資格は未確認。**
既存のAuthorityStoreを所有するプロセスが使う独立部品です。新しいwire protocolではありません。

## 三種類のデータを混ぜない

|種類|保持|配送|取消し|
|---|---|---|---|
|EventJournal|暗号化した不変イベントをSQLiteへ保存|確認(ack)前は同じイベントを再配送。イベントはcoalesceしない|購読停止は記録を削除せず、既に実行した利用側副作用も戻さない|
|LatestSnapshot|メモリー内の最新1件|初期値または最新revisionへまとめる。所有者がdispatch()を呼ぶ|close後のcallbackを止める。実行中callbackは強制停止できない|
|PresenceHints|起動中だけのhint|TTLと認証済みsession/sequenceで評価。再起動後は空|期限切れは最近の状態不明であり、オフラインの証明ではない|

## 暗号化イベント

`EventJournal.create/open(root, owner, certificate, sign_seed, local_secret, app_id, space_id, stream_id, epoch, schema, ...)` は一つのアプリ/Space/stream/共有世代/作成端末に固定します。既存認可のreadを確認して開き、publishは現在のwriteを必要とします。Keeper-onlyは読めません。公開鍵を現在のmembershipと端末証明書へ結び付けます。

payloadは最大16フィールドのexactスキーマ（text/uint64/int64/bool/bytes）。同じevent schemaを変更して開き直せません。浮動小数点、null、任意のネスト、孤立サロゲート、未知fieldは拒否します。符号付き整数は局所形式内のzigzag unsigned表現を使い、元のCBOR wire subsetは変更しません。`Event.payload`はimmutableな型付きCBOR bytesであり、`decode_payload`は呼出側だけの新しいmapを返します。

nonceの発行を先に永続化し、その後XChaCha20-Poly1305で暗号化、端末鍵で署名します。イベントとローカル到着順のtailを同じトランザクションで保存。署名に加え、journal内の連結記録・nonce発行履歴・subscriber cursorをlocal secretによるMACで検査します。秘密鍵、local secret、平文payloadはDBへ保存しません。App/Space/stream、操作ID、証明書、サイズ・アクセス形態などのメタデータは隠しません。

既存の認可DBとは別DBです。**認可履歴との跨DB原子性や外部副作用の原子性はありません。** 協調する単一所有者の同一スレッドで、現在の権限・世代・fencingを処理前/確定直前に再確認します。別DBでの認可変更を並行して許可する運用は対象外です。これは認可付き文書の既存コミット経路を置き換えません。

## 再試行・取消し

`publish(operation_id, payload, parents=(), cancelled=...)`。同じID/入力/親集合には同じ保存結果、差替えはOPERATION_CONFLICT。親はこのstreamに既に存在するID（最大16）。因果親の不足はDEPENDENCIES_PENDING。順序はこのjournalのローカル順であり、ネットワーク全体の順序ではありません。remote eventのingest/署名プロトコルは未実装です。

確定前の取消しはCANCELLED。nonce発行後の取消しでもnonceを再利用しません。確定後はLOCAL_EVENT_COMMITTEDにcancellation_requestedを付け、記録は消しません。COMMITを試みた後の例外はEVENT_OUTCOME_UNKNOWN、journalはJOURNAL_UNCERTAINとして閉じ直し・操作ID照会が必要です。自動再試行しません。保存後の読取検査が失敗しても正常なreceiptを返しません。

## pull購読とat-least-once

`subscribe(consumer_id)` → `poll(limit=16, byte_limit=262144)` → 利用側の処理 → `ack(batch.token)`。

pollは永続cursorを進めません。未ackは一つの上限付きbatchとして保持し、繰返しpollは同じbatchを返します。ackを失うと再配送され得るため、利用側はevent IDで重複排除してください。**exactly-onceの副作用を保証しません。** 保持されたjournalに再接続でき、利用側が処理後にのみackすることがat-least-onceの条件です。

ack tokenはstream/consumer/所有セッション/基準cursor/配信終端/観測認可に結び付けます。別consumer・改変・古い接続のackを拒否。再起動後の未ackは再pollが必要です。直近ackの同一tokenは冪等ですが、認可変更・古い他のackは拒否します。購読cancelは冪等で永続cursor/イベントを削除しません。

`cursor()`を信頼する場所へ別保管し、再接続時の`expected_cursor`へ渡せます。既知cursorの消失/後退を拒否しますが、Pinを含む全体巻戻しは防ぎません。GCは存在せず、必要行の欠落は破損であって正常なCURSOR_EXPIREDではありません。将来の明示GCはCURSOR_EXPIREDと復旧経路を別途定義し、黙って先へ飛ばしてはいけません。

## 上限と保存ポート

既定1024イベント/8MiB暗号レコード、4096nonce予約、64consumer。poll最大32件/512KiB、1payload16KiB。上限到達はRESOURCE_LIMIT、最初の1件がbyte windowより大きいとEVENT_EXCEEDS_WINDOW。勝手なdrop/consumer削除/履歴GCなし。全体ディスク容量（SQLiteページ・journal・監査一時割当）は論理予算と別です。

新しいDBはDELETE rollback journalとsynchronous FULL。既存認可StoreのSQLite設定を変更しません。古い暗号ライブラリは公開・合成データに限定する明示許可が必要。SIGKILL試験は物理電源断の代わりではありません。同一OSユーザーの敵対的操作、全保存物巻戻し、鍵紛失・鍵rotation、跨世代移行、独立監査は未対応です。

OS側のpath/権限/単一writerとinodeを確認しますが、OS sandboxではありません。監査は上限付きの全件復号/署名検査で、定数時間ではありません。鍵の参照を解放してもPythonの安全なメモリー消去は保証しません。スキーマは新規journal用schema1で、既存製品DBへ自動移行しません。

## SnapshotとPresenceの所有条件

Snapshot callbackへの入力はimmutable bytesと正確なu64 revision。capacity=1、callback例外はCALLBACK_FAILEDとして隔離。実行中callbackからcloseしても呼出しは巻き戻しません。認可はgeneric channelで発行せず、hostが必要な失効/非表示snapshotをpublishする責任を持ちます。

Presenceのsessionは信頼したtransportがactivateします。外部hintだけでsessionを切り替えません。同一sequenceの再送はTTLを延長しません。最大TTL60秒、peer既定128、payload4KiB。時計の逆行・不正値はCLOCK_UNCERTAINとして保持値を信用せず停止します。実ネットワークの認証やユーザー全体のonline数は提供しません。

## 検証

`python3 tools/check_events.py` と `python3 examples/events_demo.py`。
実SQLite/署名/AEAD/認可、プロセスkill、cursor、backpressure、snapshot、presenceを検査します。実Automergeを必要とせず、その成功をCRDT/G6へ転記しません。

## 00.38 SDK接続
TypeScriptの型付き購読と所有者adapterは[SDK_BINDING.ja.md](SDK_BINDING.ja.md)へ分離しました。上記の永続イベント本体と保存形式は変更しません。

## 00.40 型付き発行と結果照会
[COMMAND_PORT.ja.md](COMMAND_PORT.ja.md)に、ownerが明示許可する専用private command channelを追加しました。local-committedとoutcome-unknownを区別し、再接続・元operation-ID照会は明示操作です。保存形式・購読operation集合・ACKは変えません。`node examples/event_host_demo.mjs --commands`で実行できます。
