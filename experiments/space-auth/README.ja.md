# SPACE-AUTH-LOCAL — 00.07.00

署名付き制御履歴、認可済みmembership、共有世代の有効化、受信前検査を接続する**単一スレッド所有のローカル候補実装**。実際のlibsodium署名/HPKE/AEADと、前段のstrict CBORを使う。ネットワーク、Rust、本番用authority journal、Automerge適用は含まない。

## 実行

```sh
python3 tools/check_auth.py
python3 examples/auth_demo.py
python3 examples/auth_workflow.py --include-wire --include-store
```

Python3.11以上と `policy/crypto-provider.json` に一致するOS libsodiumを必要とする。vectors群はNodeも使用する。全workflowは前段Store検査のためPOSIX/SQLiteも必要。pip/npm、クラウド接続、APIキーは不要。ライブラリ本体は同梱しない。旧版ライブラリの明示experiment opt-inは**公開・合成の使い捨てfixtureに限る**。別ホストの設定方法は [crypto README](../g0-crypto/README.ja.md) を参照し、pinを変えたら新候補として再検証する。

## APIの入口と不変条件

`AuthorityState(provider, expected_app, expected_space, genesis)` は外部でピン留めされたSpaceIdを必要とする。受信したgenesisに書かれたSpaceIdをそのまま信頼根に使ってはならない。

`observe(control_bytes)` はschema、署名、前方連結、sequence、共有世代、authority rotationの新鍵所持証明を検証する。新しい先端を観測した後、そのmembership proofが未取得なら旧状態で共有操作しない。署名が正しい2つの競合を見つけたら両方を保存して停止する。世界全体の最新状態を証明するAPIではない。

`provide_membership(pages)` は全pageを照合する。DeviceId、certificate digest、roleを束ね、authorityがコミットしたrootとの一致を必要とする。保管役だけの変更は同epochでよい。reader/editorの集合・権限変更は新epochを要求する。

`activate(certificate, recipient_secret, package, package_ids, manifest, seeds)` は現在のmembership、epoch開始点のauthorityとmember rootに結ばれた鍵配布、完全なseed集合、各AEADとhashを全て確認してからメモリー上の有効状態を切り替える。同epochの異鍵や、観測済みの別epochで使った鍵の再利用は拒否する。seedは**opaque bytesでありCRDTの意味は未検証**。これはproductionのepoch適用完了を意味しない。

`authorize(certificate, operation)` と `validate_permit(permit)` は現在のhead/revisionに結び付くメモリー内の判断。`read`はreader/editor、`write`はeditor、`retain`はopaque keeperのみ。permitのフィールド書き換えはローカルHMAC sealで検出するが、同じPythonプロセスで任意コードを動かせる敵への境界ではない。

`receive_change(...)` は署名・歴史的なauthor権限・現在の権限・epoch/対象/スキーマ・AEADを検査する。正当な旧epochの変更はREBASE_REQUIREDへ分ける。返す候補は `inner_validated=False, applied=False`。保存/CRDT適用ACKや業務上の受理を返さない。適用直前にpermitを再確認するだけではDBの原子性にはならない。

`create_join/verify_join/issue_admission/verify_admission` は鍵所持の証明と**制御データ取得に限定された**認可材料を扱う。ネットワークのrate limiterやone-time invite台帳は未実装。admissionだけでmembershipや閲覧権限を与えない。

## 履歴の再読み込み

`export_public_replay` は署名済みcontrolとmembershipページだけを出力する。秘密鍵、共有鍵、ACTIVEフラグを保存しない。`restore_public_replay` に別に保管したexpected digest/head/minimum sequenceを渡し、署名と状態遷移を最初から再検証する。復元直後は鍵の再検証が必要。正当に署名されたfork/無効membershipも停止状態のまま再現する。

exportは最新性の証明、暗号化バックアップ、耐クラッシュjournalではない。期待hash/headをexport内の値から採用してはならない。信頼する高水位記録を失えばrollback防止は保証できない。membershipなどのメタデータは露出するため、実運用で転送・保管するなら別途保護が必要。

## 暫定契約と試験

- [ADR-AUTH-0001](../../docs/decisions/ADR-AUTH-0001.ja.md): page/root、遷移、認可、fork停止。
- [ADR-AUTH-0002](../../docs/decisions/ADR-AUTH-0002.ja.md): cycleを作らないopaque seed manifestと受信前検査。
- [ADR-AUTH-0003](../../docs/decisions/ADR-AUTH-0003.ja.md): 自己レビューで再現・修正した事項。
- `fixtures/authority-candidate.json`: 公開合成fixture。通常試験では固定bytesを読む。`tools/generate_auth_vectors.py`は明示的な再生成専用で、testsから呼ばない。
- Python側のsignature/domainとNode側のcodec/OpenSSLを照合。同じ作成者による別コード経路であり独立監査ではない。
- 188個のtest ID。128 checkpoint遷移、64 keeper変更、64 signature変異は各test内部の入力数であり別test件数には加算しない。

## 残る境界

Storeのcommitと認可の原子更新は未結合。DBを開くだけでこのstateを信用したり、古いpermitでcommitしてはいけない。次は [AUTH-STORE-LOCAL](../../plan/NEXT_AUTH_STORE.ja.md)。新epochのsecret check履歴も現状メモリー内だけで、再起動後の再利用検出/鍵更新には永続設計が必要。OS鍵保護、Python鍵の確実な消去、署名の全strict corpus、完全な暗号監査、Rust/Automerge、実通信、UI/実機は未実証。local成功でG0/G2を昇格しない。
