# BLOB-MANIFEST-LOCAL — 00.10.00

**実行可能なlocal candidate**。平文fileから予約済みnonceを使ってchunkを暗号化し、全体manifestを作り、既存の認可付きBlobStoreへ接続します。暗号・nonce・authorityは前の実装を再利用します。新しい自作暗号方式やAutomerge代替は追加しません。

## API
`FileWriter(store, certificate, epoch_secret, signing_seed, local_secret, *, observer=None, random_source=None, max_jobs=16)`。
`random_source`は公開固定fixture/衝突試験用。実用で固定randomを渡さないこと。通常は既存cryptographic randomness。

```python
staged = writer.stage(operation_id, change_header, opaque_change, local_cache,
                      source_path, name="photo.jpg", media_type="image/jpeg")
# STAGED: この端末の暗号化artifact生成完了。文書保存/remote replicaではない。
receipt = writer.commit(staged, change_header, opaque_change, local_cache)
# 既存schema3に署名された添付集合を原子的に確定。CRDT applyはpending。
info = export_file(store, receipt.envelope_id, epoch_secret, new_output_path)
# info.complete: 全chunkの認証・順序・長さ・全体hashを確認してから公開。
```

例の変数はアプリが提供する値です。動作する公開fixtureデモは `python3 examples/file_demo.py`。
`writer.write(...)` はstage+commitの便宜API。`load_staged(operation_id)` は生成済みartifactの再検証。`artifacts(handle)` はboundedなsealed attachment tuple。`inspect_file(store,eid,secret)` は出力を作らず全体を読む検証です。

## 再開
生成前にregular fileをchunk-readしてsize/hashを計算する。生成時に再読して一致を確認するので入力が途中で変われば拒否。再試行は同じop/header/payload/cache/name/MIME/contentが必要。別内容なら新しいoperation。
途中停止後はStoreをopenし、必要な認可の鍵/seedを再有効化して同じ`stage`を実行。完成済みchunkは署名とは別にAEAD/context/nonce記録を再確認して再利用し、未完成chunkのみ新しいnonceで生成します。`manifest.cbor`があるのにchunkが欠落した状態は破損として拒否します。
commit応答紛失は同じhandleで再照会し、既存receiptを返します。stageは完了したがsourceが消えた場合でも、handleを再読み込みしてcommit可能です。restoreされたStoreはwriterが無効なままですがcommitted fileをexportできます。

## 状態とエラー
`STAGED` ≠ DB commit ≠ remote保管確認 ≠ full-file verified ≠ document apply。
主要code: FILE_OPERATION_CONFLICT / FILE_HANDLE_INVALID / FILE_INCOMPLETE / FILE_CHUNK_SET / FILE_HASH_MISMATCH / FILE_SOURCE_CHANGED / FILE_NONCE_RECORD_MISSING / FILE_STAGE_BUDGET / FILE_COMMIT_OUTCOME_UNKNOWN / FILE_EXPORT_OUTCOME_UNKNOWN。
既存Store/crypto/authのcodeも保持します。plain filesystem exceptionを統一する範囲はまだ全APIで完全ではなく、同UID/private APIの敵対利用を保証しません。

## 明示的なcandidate範囲
7MiB/file、256KiB/chunk、empty file可、manifest32KiB、filename255 UTF-8 bytes、MIME127 ASCII chars、default16 staging jobs。sourceはStore外のregular file、outputもStore外の新しいpathのみ。filenameにpath separatorや制御文字を許可せず、MIMEをcontent安全性認定には使いません。
生成はbounded reads、commitは既存8MiB batchに接続するのでsealed dataをbounded tupleへまとめます。256MiBの製品要求やunbounded streamingは未達。自動GC・staging retirementは未実装で、枠不足は明示エラー。既存dataを削除して進めません。

## Tests / environment
`python3 tools/check_file.py`、または `--suite manifest|pipeline|faults`。165件:50/57/58、うち40 subprocess SIGKILL。公開合成dataのみ。Linuxでのローカル実証、physical power lossではありません。
Python3.11+、POSIX、SQLite、pinned libsodium。現hostの旧SQLite/libsodiumは使い捨て実験の明示opt-inのみ。本番認定せず、provider binaryも配布しません。別hostはg0-crypto READMEのpin手順で再測定。
[設計判断](../../docs/decisions/ADR-FILE-0010.ja.md) / [次の復元集合](../../plan/NEXT_RECOVERY_CLOSURE.ja.md)
