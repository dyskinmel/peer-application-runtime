# ADR-CRYPTO-0001 — Native primitiveと局所暗号契約（候補）

状態: candidate / same-author review only / 00.06.00。baselineの置換ではない。

## 採用
PAR-C1はEd25519・SHA256・HKDF-SHA256・XChaCha20Poly1305・HPKE base(32,1,3)。Python ctypesは明示pinの実体hashを確認したlibsodiumを使う。HPKEはRFC9180の組合せを実験として実装する（保守されたHPKE製品の採用を完了したのではない）。Node標準cryptoはEd/X25519/ChaCha/HKDF比較経路。暗号primitiveは自作しない。

Strict Ed局所profileはS<Lとcrypto_sign_verify_detachedを要求する。crypto_core_ed25519_is_valid_pointは既知の修正が未適用のため呼ばない。prime-subgroup全体の独立確認は未達と明記し、低位数/非正規入力の拒否corpusを試験する。未知suite/labelにfallbackしない。実環境に同じpinが無ければfail closed。配布にnative library binaryは含めない。

HPKE single-shotのみ。ephemeral seedは呼出しごとにOS CSPRNGから採り、公式KAT用determinismはtest用経路に限定する。stateful stream/PSK/Auth/Exportは対象外。HPKE base単体はauthorityの証明ではない。

## Contextの具体化
D(label,parts)=C(["PAR",1,label,parts])、署名/鍵導出はbaselineどおり。
block AAD=D("block-aad",[header_bytes])、block ID=H("block-id",[sealed_bytes])。
HPKE info=D("key-package-info",[app,space,epoch,setID,certificate_digest]); AAD=D("key-package-aad",[1,recipient,membership_root])。
package signed bodyはschemaのkey-package-body。outer signed-objectのsignerは外部から渡されるtrusted authorityと一致必須。
package-set root候補=H("package-root",[sorted(package_object_hashes)])、hash=H("key-package-id",[signed_bytes])。重複ID/空集合を拒否し1024件上限。これはcontrol log全体の認可検証の代わりではない。

## 保証境界
鍵と平文はPython immutable bytesに存在し完全zeroizationを主張しない。C bufferは可能な範囲で消去するがmemory dump/swap保護ではない。provider hashは実体識別であって発行者認証ではない。OS同権限攻撃・native library依存closure完全識別・FS/PCS・第三者reviewは未達。
certificateの署名確認はmembershipや失効確認ではない。envelopeのvalid signature/AEADはAutomerge hashや内側actor検証ではない。trusted expected contextを呼出し側が供給する。APIはこれをverified member等のbooleanへ変換しない。

## 環境発見
公式1.0.21 release notesにcore point validity修正あり。本環境は1.0.18、ネットワーク名前解決と明示downloadが失敗し新版sourceを取得できなかった。旧版はallow_legacy_experiment=Trueを明示した使い捨てtest keyでのみ呼出し、通常constructorは拒否する。修正関数を回避してもライブラリ全体のセキュリティ確認完了とはしない。
