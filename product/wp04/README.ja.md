# 共有変更の実core接続候補 — 00.32.00

**契約・実Storeとの境界は検証済み。実Automerge3.4.1の実行は未確認。**
この版はG0-ACTORやWP04全体の合格ではない。コアを模倣したmergeは作っていない。
`tests/product/shared-document/test_writer.py`のContractPortは意図的な合成検査器であり、その結果は常に `innerValidated=false / applied=false`。通常のSharedWriterはこの代替を拒否し、nonceも発行しない。

## 接続と保証の境界
1. ChangeInputで既存署名形式を厳密に読み、actorをSpace/epoch/document/device/actor-generationから導出する。
2. 認可付きStoreを監査し、署名済みheaderが宣言する因果的依存を取得する。証明書、元の認可履歴、署名、暗号、内外IDを再検証する。
3. 重複・欠落・循環・別文書・余分な依存・actor/sequence分岐を拒否し、正確な集合だけをcoreへ渡す。
4. 独立Nodeプロセスに渡す実装とパッケージを全バイトで固定する。コアのmetadataと外側headerのactor/seq/deps/inner hashを照合し、missing depsなし、一変更だけの適用と集合を要求する。
5. 承認済み候補だけを既存AuthenticatedWriterへ渡す。nonce発行→暗号化→保存時の認可再確認を維持。保存状態はpending。テスト用previewを適用済み文書へ変換しない。
6. 同じ操作IDの再試行では署名・暗号化済みの保存結果を照合する。別の入力は拒否し、成功応答が失われても盲目的に二重保存しない。

公開鍵やmanifestを誰でも偽造できないという保証ではない。パッケージ、検査ポート、所有プロセスを信頼する。別のプロセスへ分けてもOS sandboxや敵対的プラグイン隔離にはならない。WASMの全資源をNode heap設定だけで制限したとも主張しない。

## すぐ実行できる検査（実coreは不要）
```sh
python3 tools/check_shared_document.py
python3 examples/shared_document_demo.py
```
正常な合成reportを許可するのは公開試験用の明示オプションだけ。実SQLiteと既存libsodiumで保存・再試行は試すが、CRDT意味検査の成功には数えない。

## 実ライブラリを正当に取得できる環境での手順
実パッケージは同梱していない。公式配布元・版・MIT license・公開ハッシュと取得経路を確認した展開済みpackageを、リポジトリ外の信頼する私有領域へ置く。install/postinstall等のスクリプトはこのツールでは実行しない。
```sh
node tools/automerge_artifact.mjs inspect /absolute/reviewed/package
node tools/automerge_artifact.mjs pin /absolute/reviewed/package /absolute/new-core.json REVIEWED_TREE_DIGEST
node tools/automerge_artifact.mjs verify /absolute/new-core.json
python3 tools/check_automerge_real.py --manifest /absolute/new-core.json --allow-legacy-test-libraries
```
`REVIEWED_TREE_DIGEST`はinspectが示した全ファイル集合のhashを取得元と照合したもの。単に自己計算したhashだけでは発行元の真正性は証明しない。pinは既存ファイルを上書きしない。manifestはローカル絶対パスを持ち、再配布可能な普遍的証明ではない。

最後の実験は公開テスト鍵、使い捨てDB、旧SQLite/libsodiumの明示許可を使う。機密データや本番鍵を渡してはいけない。manifestなしは `BLOCKED / exit 78`。実core試験14件と実Store結合probeは、契約試験のPASS数に含めない。

## 実coreアダプターの未確認事項
- 3.4.1のinspectChangeはsemi-stable API。今後の版で同じ構造と仮定しない。
- raw single-change chunkだけを受け付ける。圧縮change、文書container、連結データは拒否する。coreが圧縮出力した場合も未対応エラーとなる。
- titleはImmutableString、bodyは一つの既存text object。複数のbody object競合やroot変更、rich text等は未対応として拒否。
- text spliceの位置単位を実coreでprobeしてからUnicode scalarから変換する。実probe未実行。
- cloneにはactorを明示し、生成結果のactorと一変更であることを確認する。previewは独立scratch文書であり本番DBの適用済み状態ではない。
- 最大128依存、合計4MiB、一変更512KiB、decoded ops4096。全件検査と子プロセス起動の性能は未測定。スケール上限を凍結しない。
- coreで拒否・取得不能・変更検知・時間切れの場合、共有UIは無効のまま。通常の共有保存の成功は捏造しない。

## 再開時
`plan/NEXT_ACTUAL_CORE_0032.ja.md` を読む。実probeが通るまでは本物のmerge/Automerge相互運用・G0の合格を記録しない。

## 00.33追加: 受信待機
`INBOX.ja.md`の受信箱を追加。既存core/writerコードは変更せず、独立したincoming bytesの永続化・依存待機を先行。70局所試験は実coreの実証ではない。
