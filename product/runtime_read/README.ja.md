# 認可付きStoreの観測アダプター（00.31候補）

既に所有プロセスが開いている `AuthorityStore` と、信頼済みの app/space/document/device とローカルreceipt鍵を受け取る。秘密鍵・パス・任意SQLを外部要求から受け付けない。現在の機能はデータの読み取りと自己操作の結果照会だけ。

```python
from product.runtime_read import StoreObserver
observer = StoreObserver(owned_store, app_id=app_id, space_id=space_id,
    document_id=document_id, device_id=device_id, local_secret=local_receipt_key)
report = observer.observe(operation_id)  # operation_idは16 bytes、本文不要
observer.close()  # owned_storeは閉じない。Pythonの秘密消去保証ではない。
```

アダプターの前にStoreを新しくopenする行為は別処理である。既存Store.openはfence更新や認可の再確認状態への移行をするため、本APIが読み取り専用だからといってopenまで無変更とは主張しない。

## 確認するもの
実Storeの全体audit、既知の署名付き認可履歴とコミット結合、固定doc/device、操作ID、ローカルreceiptとcacheのAEAD、receiptが持つcache hashを照合する。署名secret/epoch content secretや元本文は不要。cacheの平文は比較のためだけに扱い、表示へは出力しない。
読み取り前後のDB変更カウンター・data_version・schema_version・認可Pin・状態を比較。協調する単一所有者が前提であり、攻撃者が全領域を巻き戻した場合の保証や分散スナップショットではない。

## 意味と非保証
- `OBSERVED_COMMITTED`: 指定した自己のローカル操作が保存済みで、receipt/cache/signatureが照合できた。共有への適用・同期完了を意味しない。
- `NOT_OBSERVED`: この範囲で確認されていない。失敗、取消し、世界全体で存在しないという意味ではない。別文書/別deviceのIDも同じ結果。
- `NOT_QUERIED`: 操作IDが未指定。nonce発行済みだけではcommitとしない。
- `text=null`, `innerValidated=false`, `applied=false`: opaque changeを文書として描画しない。
- network/replicationは未観測。offlineや複製待ちとは推定しない。
- JSONは観測の搬送形式であり、単独の暗号証明・権限ではない。Pinとportは信頼済みホストから渡す。

返却はsequence付きのimmutable-candidate観測。再起動したobserverは新stream、別Storeは別generation。自動的に旧画面のstreamを新しいものへ置換しない。過去の自己操作照会は現在の共有write許可とは別。権限変更後も旧receiptを確認できるが、新しい変更を書けることにはならない。

## TypeScriptと画面
`RuntimeBinding` は固定Pinでscope/device/storeGeneration/streamを確認する。strict形検査、古いsequence拒否、同じtokenで異なる内容の拒否、同時呼出し拒否、close後の応答破棄を行う。`execute()`は`inspect-operation`のみ実データへ照会し、他の操作ではportを呼ばない。照会エラーは古い操作の失敗確定ではない。

```ts
const binding = new RuntimeBinding(trustedPin, initialOwnerObservation, ownerPort);
const view = mountReference(element, binding.current, {
  effectPort: intent => binding.execute(intent)
});
view.update(await binding.refresh()); // 明示的に観測更新。失敗を黙殺して成功扱いしない。
```

同梱の `owner_worker.py` / browser `expose_function` は合成データ試験用。製品transportとして公開しない。既存アプリのport/IPCへ統合する境界を提供するのであり、新しい認証なしネットワークを追加していない。
