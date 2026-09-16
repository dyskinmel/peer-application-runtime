# ADR-BLOB-STORE-0002 — durable incoming spool, explicit retirement, no automatic Store GC

Status: candidate / 00.09.00. 同UID敵対コード/OS sandboxではない。

1 transferはcallerが指定したtyped ID・canonical block header・sealed byte長に固定する。private spoolにPOSIX lifetime writer lockを持つ。16件/8 MiBが既定予約上限、絶対32件/8 MiB、1 block上限は既存Storeの266240 bytes。ファイル名はランダム32桁hexのみ。ネットワーク実装もglobal discoveryも含まない。

追加データ→flush/fsync→prefix hashとoffsetを書いたmetadataのfsync/rename→directory fsyncが終わってからack offsetを返す。response lossはunknownとして再openを要求する。再openでmetadata未確定のtailをtruncateし、ack済みprefixの欠落・hash不一致は拒否。metadataのhashは発行者認証ではない。

全bytesを受信してもfinish時のtyped ID/header/context/AEAD検査までは候補を返さない。検査済みでもStore reference、retention receipt、CRDT applyではない。finishの返り値を通常のBlobWriterへ渡し、改めて現在認可を確認する。

spoolの明示discardはmetadata削除を先に同期し、partを削除する。中断後に残るmetadataなしpartは、このprivate spoolでだけ破棄可能。Store公開済みのfileは別copyなので変更しない。Store orphan処理はdry-run reportのみ。active reader、lease、recovery rootの完全なpin機構ができるまで自動GCを実装しない。

署名付きattachment sidecarはfile全体のmanifestではない。chunk総数、順序、全体長の意味検証・fresh plaintext→nonce ledger→sealed block作成・復元writerの鍵更新は次の独立local taskへ残す。
