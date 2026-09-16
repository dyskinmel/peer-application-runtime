# G0-CRYPTO-LOCAL — 00.06.00

**候補実装／使い捨て試験専用。製品ランタイムでもセキュリティ認定でもない。**

## 実装範囲
Python標準ctypesからhash固定のlibsodiumを呼び、Ed25519、X25519、XChaCha20-Poly1305、ChaCha20-Poly1305を使用する。HKDF-SHA256とRFC9180 base-mode単発HPKEを組み合わせ、署名付き変更、sealed block、証明書、authority署名付きepoch key packageを構築する。primitiveの自作やsuiteの代用はない。ただしHPKE組合せコード自体は今回作成した未監査の実験実装である。

Native: libsodium1.0.18。Node22.16.0/OpenSSL側を別コード経路とし、RFC既知値・64種類のHPKE・64種類のEd署名を照合する。XChaChaには第二実装がなく、draft既知値＋改変拒否＋保存統合で検査する。同一作成者の二経路であり独立レビューではない。

## 再実行
```sh
python3 tools/check_crypto.py
python3 tools/check_crypto.py --suite primitives
python3 tools/check_crypto.py --suite hpke
python3 tools/check_crypto.py --suite objects
python3 tools/check_crypto.py --suite store
python3 tools/check_crypto.py --suite interop
python3 examples/crypto_workflow.py --include-wire --include-store
python3 examples/crypto_demo.py
```
実体はpolicy/crypto-provider.jsonで指定。ネットワーク、pip/npm、site-packages追加、APIキーは不要。OS側libsodiumは必要で配布には含めない。通常constructorは旧版を拒否する。試験は公開テスト鍵と`allow_legacy_experiment=True`を明示して実行。SQLiteも既知修正未確認のためテスト内だけ`allow_unpatched_sqlite=True`を明示する。通常製品アプリをこの設定で運用してはならない。

## 別ホスト・修正版を採用する手順
信頼できる入手経路で保守されたlibsodiumを用意し、インストールした実ファイルの絶対path、実version、SHA256を確認する。pinを書き換える前後の値と入手元を記録し、新しいsource候補としてcommitする。同じversion名だけで旧証拠を再利用しない。候補pin更新後にdoctor、全suite、full workflowを実行する。自動ダウンロード・自動pin更新はしない。初期pinに一致しないhostではFAIL/CAPABILITY_MISSINGが正常な応答である。

## API境界
`objects.open_change`は期待する全headerとsignerを受け取り、外側型・canonical・context・署名・AEAD・平文長を確認する。Automerge change hashや内側actor、membership、失効を確認したとは扱わない。証明書の署名確認だけで入会を認めない。

`objects.open_package`には認証済みcontrolから得たauthority、期待context、package ID集合とtrusted rootを渡す。入力packageのrootをその場で計算してtrusted引数へ渡すだけでは認可にならない。完全なcontrol log検証は次工程であり、ここでは呼び出し元が信頼境界を担う。

低レベルseal_change/seal_blockは予約済みnonceを受け取る部品。アプリが任意にnonceを再利用してよいAPIではない。永続書込みは`CryptoStoreWriter`を使う。HPKEはsingle-shotのみで、再送は保存済みpackageを再利用する運用が必要。鍵packageの永続outbox統合は未実装。

## 保存との接続
`CryptoStoreWriter.commit(op,header,payload,cache)`は入口で可変headerを複製する。用途別local subkeyでHMAC intentを作り、保存済みならenvelope/cache/receiptを復号検証して同じ結果を返す。乱数・sealを再実行しない。未保存なら実key identityごとにnonceを別transactionで永続予約し、content、cache、receiptを別用途で暗号化した後、既存Storeへ原子的に保存する。contentの予約のみconsumed_byをcommitへ結び、他の発行記録も永久に重複拒否集合へ残す。

予約後に停止した場合は旧nonceを使い直さず新しい予約を作る。commit後応答が失われた場合は同じop/inputを照会する。6境界のSIGKILL試験は実プロセス終了であり、物理電源断ではない。復元Storeは旧generationを使って復号できるが、書込み禁止のまま。rekey/actor更新による再活性化は未実装。

## 限界・未解決
- 古いlibsodiumのpoint-validity関数は使わない。Sのcanonical確認＋crypto_sign_verify_detachedと拒否例は実施したが、prime-subgroup全体の独立確認は未達。
- 本番鍵保管、Python immutable bytesの完全消去、swap/dump保護、FS/PCS、同権限攻撃耐性は保証しない。
- native fingerprintはpin画像とctypes拡張を識別する。全native依存closureを証明するものではない。
- sealed blockのwire IDはtyped `H(block-id,[bytes])`。旧Storeのfile locatorはraw SHA256。両者の対応表は未統合であり、今回のCryptoStoreWriterは添付Blobを受け取らない。
- AppIdは既存Storeと共通な小文字reverse-domain subsetに制限する。正規化はしない。baseline全域のcase policyはG0 closureで確認する。
- CRDT payload/cacheは試験用バイト列。意味的に正しいAutomerge編集の証明ではない。
- 署名付きpackageのcontrol chain、鍵ローテーション、署名付きsnapshot、Keeper復旧、native Rust、実機は未完了。

公式primitive既知値は[SOURCES.md](SOURCES.md)。PAR composed-candidate.jsonは同一作成者が今回一度生成し固定した回帰vectorであり、外部認定済みKATではない。通常試験で期待値を再生成しない。
