# Event / Presence / RPC — データと再実行の契約

状態は規範候補。messageの形だけで終わらせず、暗号化・配信・副作用の境界を以下に固定する。

## Durable Event

CHANGEはcodec1文書差分、codec2永続イベントを運ぶ。codec2ではchange-headerのkind=event、object=channel ID、actorはdevice+generation+channelに束縛、seqは1から単調増加。prevは同actor直前event envelope ID、depsは因果的に既知のevent envelope IDs、field12はSHA-256(canonical event payload bytes)。payloadは `{0:event_type ASCII<=128,1:schema_digest,2:application_value_bytes<=65536,3:blob_manifest_refs<=128}`。アプリ値はschema固有codecに従い、remote codeではない。

envelopeの署名/AEAD/domainは文書と共通、object-kindをAAD/KDFに含むため文書への置換は拒否。same operation IDの再送は同じevent envelopeを返す。因果依存が不明ならpending、同actor同seq異bytesはfork。wall clockは表示用optional application fieldであり認可/順序の根拠ではない。

ネットワーク上のevent因果順と、ローカルsubscriberのdelivery順を区別する。subscriber cursorは(channel,subscriber,retention generation,local delivery sequence)。local delivery sequenceは同端末storeの単調u64で再起動を跨ぐ。新しく届いた古い時刻のeventにも新delivery sequenceを割り当てる。単一のlast event timestamp/IDをcursorとすると遅延eventを欠落するので禁止。handle成功後のcursor ACK前にcrashすれば再配信可能。GCでcursor前提を失ったらCURSOR_EXPIREDとsnapshot/replay選択を返し、黙って最新位置へ飛ばさない。

## Ephemeral Presence

presenceは`activity-envelope` family=1。channel ID、session ID、sender、counter、epoch、control head、TTLを認証headerへ入れる。外側PRESENCEのTTLと署名対象TTLを一致させ、第三者が延長できないようにする。object key導出のkindにreserved key-context6を使用する。payloadはbounded application hint、counterはsession内単調、replayは捨てる。freshnessは受信monotonic clock＋TTLで決め、wall clockで相手onlineを断定しない。再接続sessionが変わったら古いsession presenceはexpired。

## RPC

rpc request/resultはactivity-envelope family2/3。family2はsender=caller/target=provider、family3は逆。operation ID、handler、input digest、deadline duration、modeをheaderとpayloadで一致させる。key-context7を使用する。Space共有鍵なので同Space readerからも入力を秘密にする契約ではない。participant間の個別機密が必要な場合は別Spaceまたは将来のpairwise profileを要求する。targetが違う署名RPCを実行しない。

`input_digest = SHA-256(C([SpaceId, target_device, handler_id, handler_schema_digest, application_input_bytes, declared_mode]))`。期限は相手への到達時点からmonotonic durationで評価するため、ネットワーク中の厳密なabsolute deadlineを保証しない。

| handler mode | 再送 | ledgerと副作用 |
|---|---|---|
| pure | 同ID/inputで明示retry可 | 結果をcacheできる。外部副作用なしというアプリ責務 |
| local-idempotent | 同ID/inputのみretry可 | PAR管理storeのtransaction内でdedupe/副作用/resultをまとめる |
| external-side-effect | 自動retry不可 | 外部処理結果が不明ならoutcome-unknown。外部APIのexactly-onceを主張しない |

新しいcallbackが単に`idempotent=true`と申告しただけではlocal-idempotentにしない。PARの提供するeffect transaction interfaceに限定する。FFIがそのtransactionを提供できないbindingではmodeをunsupportedとして返す。mode不一致は拒否。raw database handleをhandlerへ渡さず、bound transaction portで副作用を記述する。

取消しは開始前cancelled、実行中request acknowledged、完了済み/不明のtoo-lateを区別する。途中取消しで外部副作用を自動rollbackしたとは言わない。RPC ledgerの保存期限はhandler profileへ明示し、期限後の同IDは安全性確認なしに新実行しない。初期profileは実行記録をSpace内明示GC checkpointまで保持、容量不足なら新規実行を拒否する。

## activity-envelope暗号形式

headerはCDDL activity-header。C(header)を`header_bytes`とする。keyはspec05のHKDFにkind6または7、object_id=channel、key_generationを与えて導出する。AEAD AAD=D(activity-aad,[header_bytes])、署名=S(device key,activity-sign,[header_bytes,nonce,ciphertext])。nonce24は新規CSPRNG。RPC retryは元の署名/暗号bytesを再送し、新sessionで必要なdelivery wrapperだけ再生成する。header SessionIdはpresenceで現在値、RPCではnullとし、永続operationをsession外へ移せる。session認証とgrantは転送ごとに別途必要。

RPC bodyに含めるapplication resultも同じgroup-key境界。operation IDに結び、結果を返したdeviceが指定targetであることを検証する。presence/RPCのpayload合計がframe上限に収まるようRPC application bytesは512KiB未満、overheadを含むbody<=1MiBを最優先する。

activity-header field13はpresenceの署名対象TTLで1〜60秒、RPCではnull。認証sessionのsenderと署名deviceを一致させ、代理転送を許す将来profileでは別のorigin/replay契約を要する。
