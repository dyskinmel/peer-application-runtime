# BLOB-STORE-LOCAL — typed attachments / schema3 / bounded incoming spool

`00.09.00` はPython/POSIXの**契約実証用candidate**。ネイティブRust、Automerge、Keeper network、本番暗号レビューは未実施。

## できること
- `Attachment(typed_id, header_bytes, sealed_bytes)`のID・header・context・AEADを既存libsodiumで検証。raw SHA-256 file locatorとPAR domain-separated IDを別々に保持。
- `BlobWriter.write(op, header, opaque_payload, cache, attachments=(...))` はordered attachment descriptorsを暗号化前のidempotency inputへ結ぶ。文書payload自体は変更しない。
- 署名付きsidecarはapp/Space/epoch/document/envelope ID/ordered descriptorsを結ぶ。署名者は既存authority proofのcertificateで検証する。public keyの自己申告は信頼しない。
- file fsync/rename/directory fsync後、alias・ordered references・sidecar・auth proofを同じSQLite transactionに保存。認可はBEGIN後とCOMMIT前に照合。応答紛失は同じ操作IDで照会。
- schema2→3は `BlobStore.migrate_v2` を明示的に呼ぶ。署名/整合性が有効で既存raw blockがないDBのみ移行。non-Blob commitは保持。旧raw blocksの自動信頼はしない。
- backup/restoreの段階で一覧署名・file bytes・全参照集合を再検査。復元先はread-onlyのまま。
- `IncomingQueue` は私有spoolへの局所的な分割受信。offset/hashを永続化し、ack済み部分の改変は拒否。未ack tailだけ切り捨てて続行。明示discardはStoreを削除しない。

## 実行
```sh
python3 tools/check_blob_store.py
python3 examples/blob_store_demo.py
python3 examples/blob_store_workflow.py --only BLOB-STORE-LOCAL
```
全レーンは `python3 examples/blob_store_workflow.py`。`--only` は短いtool呼出しでの分割実行用。`--resume-summary` は保存された各レーンのrun/checkpointを再検証し、未実行をPASSにしない。

Python 3.11以上、SQLite 3.37以上、POSIX、`policy/crypto-provider.json`に一致するlibsodiumが必要。全体回帰にはNodeも必要。実際に確認したhostはrelease evidence参照。旧版SQLite/libsodiumの通常利用拒否は維持し、試験/デモはpublic synthetic dataの使い捨て実験でのみ明示許可する。ライブラリbinaryは配布しない。追加pip/npm依存はない。

## APIと境界
`BlobStore`は `AuthorityStore` のAPIを継承し、`.attachments(envelope_id)`、`.read_attachment(envelope_id,position,epoch_secret)`、`.orphan_report()` を追加する。ローカル保存物の再読出しでありremote read認可APIではない。過去に受け取った秘密鍵を失効で回収するとは言わない。

`BlobWriter`は**暗号化済みblockのimport/attach**を扱う。呼び出し元が過去にnonceを再利用していないことを証明するAPIではない。fresh plaintextファイルをchunk化・nonce予約・暗号化して作る高位APIは次工程。試験の固定nonceは固定の公開テスト鍵だけに使う。

`read_attachment`はAEADを再検証する。全体auditは鍵をDBに保存せず、署名・hash・structure・referenceの一致を確認する。audit合格は全blockのAEAD再検証やfile全体の完全性、Automerge applyを意味しない。状態は常に`pending`。

新しい署名一覧はADRのcandidate sidecarで、元wire formatの一部として認定されていない。今後送信処理が追加される際は、一覧必須・不足時停止を先に仕様化する。元仕様85 filesとschema1/2は不変。

rootはprivateな単一cooperative writer用。永続DB全体の敵対的巻戻し、same-UID攻撃、悪意あるprovider、ハードウェア鍵保管、実停電・媒体故障、native/browser対応は保証しない。完全なStore auditは現在保守的な全件検査で、スケール最適化前。

## 上限と未実装
1 request 128 blocks / 合計8 MiB sealed bytes。whole-file manifestの順序・個数/全体hash、cross-epoch wrap、reader/lease/recovery pin付きGCは未実装。Store孤立blockは観測レポートだけ、勝手に削除しない。private spoolのunackデータとStore retentionを混同しない。

## 検証
`bindings`, `commit`, `recovery`, `incoming`, `faults`を分割実行。固定seedやpublic fixturesのみ。43件のowned-child SIGKILL（multi-block、DB移行、backup、incoming/discard含む）は物理電源断試験ではない。独立レビューはNOT_RUN。
