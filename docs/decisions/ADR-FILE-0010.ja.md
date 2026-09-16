# ADR-FILE-0010 — Whole-file candidate / durable seal journal / publication

状態: LOCAL_CANDIDATE。00.10.00で実装・自己検証。独立レビュー・protocol freeze・本番gateではない。

## 判断
既存schema3/署名付きattachment sidecarを変更しない。添付の先頭は暗号化されたwhole-file manifest、残りは順序付きencrypted chunkとする。文書change自体は不透明なまま、ここにAutomerge互換の自己流構造を追加しない。
manifest-objectはfile-objectとは別のdomain hash。manifestにはApp/Space/epoch/file ID/key generation/合計長/chunk size/plain SHA-256/filename/MIME/順序付きtyped IDとblock headerを含める。filename、MIME、平文hashはencrypted bytesからしか得られない。

## Nonceとintent
署名対象のdocument操作IDとは別のHMAC domainで内部seal operationを導出する。両方とも同じStoreのpermanent issued-nonce ledgerを利用する。intentはheader、payload/cache digest、全体hash/size/metadataをlocal keyでHMACした値。失敗・再起動でもnonceを巻き戻さない。chunkごとにreserve→seal→fsync→immutable publication→dirsync。完全なartifactを再利用する場合はAEAD、context、input、nonceの発行記録を再照合する。

## Journalとbackup
`staging/files/<derived-op>/` は暗号化intent・sealed chunk・sealed manifestのみ。平文sourceをコピーしない。partial writeは暗号文だけで、再試行はこの名前空間の未ack `.part`のみを削除する。ack済みartifactが壊れた場合、勝手に別ciphertextで作り直さない。
生成途中のjournalはdocument commitではなく、既存backupにも含まれない。commitされたfileは署名済みsidecarとmanifest/chunksだけから検証・復元できる。未commit journalの独立backup/移動/GCは次の設計対象。

## Authority
新しいstage slotは有効なwrite権限を確認してから確保する（追加負例で旧順序の漏れを修正）。commitは元のBlobWriterの認可ticket・原子的参照保存を再利用する。生成後にauthority headが変われば古いheaderのcommitは拒否。完了済み結果の再照会は新しいwriteではない。

## 全体検証と出力
manifestのcount/order/size/contextと実attachment集合を完全一致で照合し、AEADと全体SHAを確認する。平文exportは呼出側の明示path。metadataをpathとして解釈せず、既存targetを上書きしない。mode0600のtemp→全体検証→fsync→same-directory hardlink(no-clobber)→dirsync→temp削除。公開後の失敗はOUTCOME_UNKNOWN。SIGKILLでは未公開temp plaintextが残る可能性がある。OS同UID隔離・secure eraseではない。

## Limits / portability
candidate 7MiB/file、256KiB/chunk、default16 staging jobs。既存8MiBのatomic attachment batchへ安全に収まる値。製品仕様の256MiBや将来拡張の上限を下げたのではない。read/sealはchunk単位だがcommit/reverification adapterは最大batchをメモリー化する。任意サイズのconstant-memory pipelineを実証したとは言わない。
POSIX regular filesとhardlink/fsync、cooperating writer lockを前提とする。root以外の任意敵対的同UIDプロセス、DB全体のrollback、電源断・媒体故障、nativeやmobileは未実証。

## 進捗に伴う登録試験の更新
00.09.00の登録試験にある「ファイル全体は未実装」「次のmanifest作業はPLANNED」「50作業」は旧版の進捗値です。今回の実装後は、旧Blob部品のprofileがwhole-file非対応であることは引き続き検査し、全体の到達点はfile専用profileで検査します。次工程は未実装RECOVERY-CLOSURE-LOCAL、作業総数51へ更新しました。元仕様149要件、全製品Gate未認定、旧部品151件の試験集合は維持し、試験を減らして成功させていません。
