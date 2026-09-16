# 00.30.00 私有下書き — 共有文書と別の保存契約

## 実装した範囲
`DraftVault`は、注入された32byteの保存鍵と`DraftStoragePort`を使う。本文・元本文・frontier・保留した遠隔変更・選択範囲を暗号化して保存する。鍵をDBへ書かない。暗号が利用できないときに平文へフォールバックしない。

一保存ごとにCSPRNGから32byte saltと12byte IVを作り、HKDF-SHA256（`PAR/private-draft/key/v1`）で専用AES-256鍵を導出し、AES-GCM/128bit tagで暗号化する。profile、scopeに基づくslot、version、operationId、salt、IVをAADへ結合する。これはローカル下書きの候補形式であり、PAR通信暗号スイートの変更や独立監査済み暗号プロトコルではない。salt/IVの乱数品質は注入するWebCrypto実装に依存する。

## 保存・再試行
`prepare(draft, expectedVersion, operationId)`で入力を最初のawait前にコピーし、既存レコードを認証復号してから候補を生成する。`commit(prepared)`はCASで版を検査して公開する。同じpreparedの再試行は同じバイト列に収束し、暗号化をやり直さない。

応答紛失などはDRAFT_WRITE_UNKNOWN。`VaultDraftSession`は不明な操作が残る間、次のsaveを拒否する。`inspect`/`reconcile`で実レコードを読む。確認できないことは未実行の証明ではなく、自動再試行はしない。保持するのは最新headなので、operationIdの全履歴に対する重複排除機構ではない。旧要求はexpectedVersionの不一致で拒否する。

`prepare(null, version, id)`は版を維持する暗号化tombstone。物理ファイルを消してversion=0へ戻さない。全保存領域の巻き戻しは、独立した外部anchorなしには検出できない。

## 二つの保存port
- Node/POSIX: `adapters/file-draft-store.mjs`。私有root、0600ファイル、単一協調writerロック、同一ディレクトリ内のrename、ファイル/ディレクトリfsync。3境界の子プロセスSIGKILLを試験。ロックは勝手に除去せず、死んだPIDと固定記録を確認する`FileDraftStore.recoverLock(root)`を所有者が明示実行する。PIDが再利用されて生存していれば拒否する。ロック自体の書込み途中の破損は自動復旧しない。
- Browser: `openIndexedDbDraftStore()`。getとCASをtransaction内に収め、request successではなくtransaction completeで完了する。strict durabilityを要求するが能力表示は常にbrowser-best-effort。32レコード・論理64MiBまで。実originでの実行はこの環境のURLBlocklistにより未検証。型検査と利用不能時の拒否のみ実証した。

Node portの試験成功を、IndexedDBの実originでの動作確認へ置き換えない。どちらも物理ディスク全体の容量、ブラウザーのeviction、媒体電源断、安全な消去は保証しない。

## 表示と復元
既存`Draft.persisted=false`は揮発性bufferとして維持し、永続コピーのreceiptを別軸で表示する。私有下書きの保存によってlocal shared snapshot・replication・CRDT appliedを更新しない。

復元は利用者の明示確認が必要。入力中のbufferを自動上書きせず、現在のbase/frontier/authorityが違う場合はreview状態にする。再起動後のIME compositionは復活させないが、途中のテキストは保持する。保存中に追加で編集しても、新しいテキストを古い保存結果で置き換えない。

## 鍵と限界
開発画面では利用者が別に保管した64桁hex鍵を入力する。鍵はRAM内だけで、再読込み後は再入力が必要。OSキーストア、password KDF、鍵の回復、同originの敵対的コード防御は未実装。JavaScript内のバッファ上書きを、すべての秘密コピーの安全な消去とは主張しない。真正なhostが返すJSONを前提とした表示であり、JSONのフィールドを暗号学的証拠とは呼ばない。

## 例
```js
const vault = new DraftVault(crypto, storagePort, privateMasterKey, scope);
const before = await vault.load();
const prepared = await vault.prepare(draft, before.version, operationId);
const receipt = await vault.commit(prepared); // sharedSaved=false, replicated=false
```
Browser画面→Nodeファイル保存のQAは、テスト専用bridgeで実I/Oへ接続した。製品のHTTP/RPC transportを追加したわけではない。
