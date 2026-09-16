# ADR-BLOB-STORE-0001 — immutable typed attachments and signed local sidecar

Status: candidate / 00.09.00 / not independent-reviewed.

旧Storeはraw SHA-256をfile locatorとして使用する。PAR sealed blockはdomain-separated typed IDを持つ。両方を別column・API fieldに持ち、実bytesから再計算し一致した場合だけ対応を公開する。headerはapp/space/epoch/object/kind/index/key-generation/plain-length。Blob専用candidate kind=3、1 batch最大128 blocks/8 MiB sealed bytes。これは無制限入力を避ける試験profileで、製品の恒久上限ではない。

Automerge bytesを解析できないため、payloadに添付参照があることを仮定しない。本文は変更せず、envelope ID・app・Space・epoch・document・順序付きtyped IDとheaderを別のdetached署名一覧へ結ぶ。domain `blob-store-local/attachment-sign` は実験専用。受信/配布protocolはこの一覧を必須にする仕様が凍結されるまで実装済みと称さない。

一覧のheader/IDはdocument暗号化前のidempotency inputにも含める。payloadとcacheが同じでも添付を変更した同一操作IDの再試行は拒否。署名者は既存auth proofのcertificateに基づいて検証し、自称public keyを信用しない。

AEAD、typed ID、headerをprepareで検証。immutable bytesと一覧署名をowner-sealed ticketへ結ぶ。Storeはfile fsync/rename/directory fsync後、認可の再照合・block alias・添付一覧・auth proofを同じDB transactionで確定し、COMMIT直前に再照合する。

schema3は既存schema2に追加。既存schema2の正しい認可付きnon-Blob履歴は移行可。未検証のraw block参照を発見したら自動変換を拒否。以後全commitが「legacy/no attachments」または「signed attachment list」として分類され、欠落一覧を空と取り違えない。

常時信頼するOS/同UIDコードを敵として隔離するものではない。block添付一式の検証はwhole Blobの完全性やCRDT適用、最新認可の世界的証明ではない。
