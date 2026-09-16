# RECOVERY-CLOSURE-LOCAL — 00.11.00

状態: **実行可能な局所候補**。実ネットワーク、製品G3、Automerge文書の適用、本番暗号評価ではありません。既存DBのbackupコピーでなく、署名indexと型付きopaque object集合だけで別の認可済みrecipientがread-only viewを作ります。

## 最初の実行
プロジェクトrootで `python3 tools/check_recovery.py`、`python3 examples/recovery_demo.py`。全体は `python3 examples/recovery_workflow.py`。短い実行枠ではSTART_HEREの`--only`を使い、最後に`--resume-summary`で証拠を再照合します。Python3.11+/POSIX/SQLite/OS libsodiumが必要です。既存pinと一致するライブラリを使います。Nodeは全回帰の別経路比較で必要、追加pip/npmやAI APIは不要です。旧版providerのopt-inは公開・合成の使い捨て実験専用です。

## APIとデータ経路
`collect(store, space, roots, grant, issuer_certificate, issuer_signing_seed)` は `Bundle(index, objects)` を返します。rootsは明示したenvelope IDのtuple。Grantには事前発行済みrecipient証明書・鍵配布・package ID集合・seed manifest・seed blocksを渡します。collectorは参加権限を作りません。issuerは現在の既知headでeditorである必要があります。

`Pin(app, space, head, sequence, epoch, recipient_id, certificate_id, roots, index_id)` を**別の信頼経路**からrecipientへ渡します。Keeperが返したindexからこのpinを生成してはいけません。公開デモで同じprocessがpinを作るのは事前に信頼した発行者役を兼ねるためです。世界全体の最新性・全DB rollbackを証明するpinではありません。

`publish_bundle(bundle, opaque_dir)` はopaqueなバイト列だけを公開します。`DirectoryProvider` はそのバイト列を供給するローカルadapterです。ネットワークのGET認可やleaseはまだありません。

`Inbox(root,index,pin)` → `missing()` → `pull(provider,limit=32)` → close/reopen → `finalize(destination,crypto_provider,recipient_secret)`。
部分受信は完全なobject単位。900000 bytes以下の個々のobject内部のpartial offset再開はありません。別のBlob spoolと混同しません。毎回署名対象のinventoryと実在するfile hashを再照合し、進捗booleanを信用しません。providerが一部しか持たなければ、不足リストを返して成功にしません。

`verify_public(bundle,pin,provider)` は署名・履歴・認可・宣言依存・署名付き添付を確認します。鍵を持たない側でこれが通っても意味上の復旧完了ではありません。
`verify(bundle,pin,provider,recipient_secret)` はさらにrecipient鍵配布とseed/envelopeを復号し、添付ファイル全体のサイズ・順序・hashを検証します。
`open_recovery(directory,pin,provider,recipient_secret)` は公開済みの復旧先を毎回再検証してread-only `RecoveryView` を返します。

RecoveryView: `read_change(envelope_id)`、`read_seed(document_id)`、`file_info(envelope_id)`、`export_file(envelope_id,destination)`、`status()`。文書本文/seedはopaque bytesであり、Automerge decoderやschema検証を経ていません。書込み可能なStoreやnonce履歴は移植しません。表示用stateを信用して直接インスタンス化せず、上記verifierから取得してください。same-processのprivate属性改変へ対する隔離ではありません。

## index候補の契約
canonical CBOR outerは`{0: body_bytes, 1: Ed25519_signature}`。domainは`recovery-local/index-sign`。body keyは以下のとおりです。

| key | 内容 |
|---|---|
|0,1|version=1、profile=`recovery-closure-local`|
|2..6|app、Space、known head、control sequence、content epoch|
|7,8|recipient device ID、recipient証明書ID|
|9|sorted explicit envelope roots|
|10..13|public replay、recipient cert、grant、issuer certの転送object ID|
|14|envelope ID順のentry。envelope/author cert/任意sidecar/ordered block object ID|
|15|転送object ID順の`[ID, kind, byte_size]`集合|

転送object IDは`hashed('recovery-local/object',[kind,raw])`。PARのenvelope/block IDおよびStore locatorとは異なり、各verifierで対応を再計算します。grantにはrecipient用package一つとそのepochの全package ID集合を入れ、他recipientのpackage bytesや秘密鍵は転送しません。member/controlの履歴は公開署名replayで保持し、seed一覧・package rootはepoch anchorに結び付けます。

全inventoryの厳密一致、使われないobjectの拒否、重複・型違い・上限・未到達envelopeの拒否を行います。署名headerのpreviousとdependency change hashを辿り、欠落・循環・曖昧hash・別epoch/doc関係を拒否します。**内部Automerge changeと宣言headerの対応は未検証**です。seedのcutが未取得の依存を満たすとは推測しません。

## 状態と安全性
- `BYTES_COMPLETE`: immutable objectが全部そろうだけ。署名・recipient検証の証明ではありません。
- `RECIPIENT_VALIDATED_READ_ONLY`: 指定pinとrecipient鍵で署名・認可・AEAD・ファイル全体を確認した状態。
- `inner_validated=false`, `applied=false`, `writable=false`, `global_latest_proven=false`, `network_verified=false`, `product_qualified=false`を維持します。スキーマIDは署名headerと照合するのみで、アプリの意味検証をしていません。
- 正当な認可更新の永続化結果が不明なsourceは`AUTH_PERSISTENCE_UNCERTAIN`で収集を拒否します。失敗した書込みの記憶をdiskに必ず残せると主張しません。
- finalizeはrecipient verification→private stage→再検証→destination rename→parent fsync→ack。既存destinationは上書きしません。publish後のエラーは`RECOVERY_OUTCOME_UNKNOWN`。別途pinでopenして観測し、勝手に別の成功へ変換しません。
- SIGKILLはprocess crash試験です。電源断/媒体喪失ではありません。private directory/協調writerに限定し、same-UIDによる並行差し替えへの完全防御ではありません。
- 暗号文temporaryは再開時に識別・回収します。公開stageのciphertext debrisが残る場合があります。平文exportは既存部品を使うため、kill後に0600のplaintext temporaryが残り得ます。secure erase/自動Store GCはありません。

## 検証範囲と上限
37 contract +36 pipeline +33 transfer +20 faults =126 tests。10 owned SIGKILL境界と、donor DB/元平文を削除してから新しいrecipient processで復旧する試験を含みます。削除は試験専用TemporaryDirectory内に限定。秘密鍵や個人データを使いません。

index512KiB、各object900000 bytes、最大1024 objects/64 envelopes/32MiB。既存file最大7MiBの制約は維持。collectorのenvelope走査は4096件/32MiBで拒否し、途中打切りを完全索引としません。ただし既存Storeの事前auditは全件走査です。大量履歴の定数メモリー・応答時間を保証しません。v1製品の上限は変更しません。

現在epochのみ。過去epochをまたぐ復旧、writable DB再構築、fresh key/actor rotation、CRDT適用、長期保管receipt、authenticated GET、実ネットワークの可用性、第三者reviewは未完了。metadata（member/関係/サイズ/種類）はopaque providerに見えます。名前/MIME/平文全体hashは既存の暗号化file manifest内です。

`fixtures/closure-current-epoch.json` はこの実装で生成した公開の固定候補値であり、第三者のKATではありません。通常テストで再生成しません。生成器は`tools/generate_recovery_vector.py`で、変更する場合は別候補としてレビュー・全再試験します。

次は [Keeper局所保管](../../plan/NEXT_KEEPER_RETENTION.ja.md)。元のG0/G3は未合格です。
