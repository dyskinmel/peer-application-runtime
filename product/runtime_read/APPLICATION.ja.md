# schema4文書観測 — 00.36.00候補

実Automergeは未取得・実行0件。今回の検査は実SQLite/署名/暗号と、明示的な合成materializerによる契約試験。実coreを名乗る試験ポートも正例の契約検査専用であり、CRDTの動作証拠ではない。

## 利用境界
`ApplicationObserver(application, expected_engine=None)`は、既に所有者が開いたschema4の`DocumentApplier`を借りる。Storeをネットワーク要求ごとに開かない。migration/書込み/nonce発行/署名/同期/GC/自動再試行は一切呼ばない。所有者プロセス/スレッド、scope、Store世代、読取証明書、観測streamを固定する。

`observe(operation_id=None)`は文書の最新到達点と自己の過去適用操作の照会を別々に返す。操作ID未指定はNOT_QUERIED、該当する自己操作が未観測ならNOT_OBSERVED。この状態は失敗/取消し/全世界の不存在を意味しない。別証明書の操作結果は返さない。

## 検証と本文の非開示
- 既存Store監査、適用履歴/nonce/到達点の構造検査、暗号化された全適用イベントのAEADを確認。
- 最新集合の元の暗号化入力・証明書・署名・歴史的認可・actor/依存関係を読み直し、元の決定的な順序でcore requestを再構成。そのdigestを保存時と照合する。
- `candidate`は常にCANDIDATE_ONLY、note=null、innerValidated=false、applied=false。内部で認証用に復号しても本文をJSONへ含めない。
- `core-validated`というラベルだけでは本文を出さない。ownerから別途渡したexpected_engineの全項目と現在のcore.identityを照合し、全入力を再materializeする。正確なheads/入力集合/返却契約と暗号化保存本文が一致した場合だけVALIDATED_LOCAL_VIEW。
- core不在/実行不能はCORE_RECHECK_REQUIREDで本文を非開示。不正report/異なる実装/本文不一致は読取失敗。恒久的な検証成功cacheは追加しない。
- 前後のDB変更情報、writer fence、認可行digest、到達点を照合。以前観測した到達点が消えたら拒否。再起動越しの既知到達点は既存DocumentApplierのexpected_pinで明示する。

## 表示と操作結果の違い
EMPTYはこのscopeの適用イベント未観測であり削除済みではない。OBSERVED_CANDIDATE/OBSERVED_APPLICATION_RECORDは適用イベントの存在を示すだけで、編集保存・外部保管・最新文書・読取継続権限を保証しない。

`application-observation.ts`は厳密な型検査、固定Pin、増加sequence/文書revision、同一revisionの不変digest、既知の操作結果不変性を検査する。任意のJSONは暗号証拠ではない。Pinとportを信頼済みownerが渡す必要がある。

`projectApplicationObservation`は既存NoteStateへ変換するがsharedWriteAllowed=false、local.state=unknownを維持。適用イベントを共有commit receiptへ変換しない。私有下書きも更新しない。

`ApplicationReadBinding.refresh(op)`は取得開始時・失敗時に公開する本文/競合を消し、close後の応答を捨てる。候補や未検証本文を画面へ返さない。元の私有下書きや別画面にコピー済みの文字列まで消すAPIではない。JS文字列の安全なメモリー消去も保証しない。

## UI接続例（ホスト側が責任を持つ）
```ts
const binding = new ApplicationReadBinding(trustedPin, firstObservation, ownerPort);
const view = mountReference(container, binding.current);
const request = binding.refresh(originalApplyOperationId);
view.update(binding.current); // 待機中のshared bodyをただちに非表示にする
try { view.update(await request); }
catch { view.update(binding.current); } // 失敗を成功表示へ変換しない
```

今回の試験は型/Presenter契約まで。rendererのソース・画面デザインは未変更。実ブラウザーでの再描画は再実行していない。共有書込みAPIは提供しない。

## 信頼と資源
expected_engineは保存metadataから自動採用しない。任意の同一プロセス実装は偽装できるため、これはsandbox/ハードウェアattestationではない。Nodeに分けてもWASM fuel meterではない。既存schema4の上限を引き継ぐ（適用64、入力128、note256KiB、旧SQLite/libsodiumは合成実験のみ）。全件復号/再検査は同期、性能上限や即時取消しを保証しない。

## 実行
`python3 tools/check_application_observation.py`（Python39 + Node57 = 96）
`python3 examples/application_observation_demo.py`
`node examples/application_observation_demo.mjs`
実Automergeがない環境でポートの名前だけをactualへ変更して運用してはいけない。
