# ADR-SYNC-INBOX-0033: semantic core未確認でも独立に実証できる受信待機境界

状態：候補。元仕様を変更しない。G0-ACTOR/G2の合格ではない。

実パッケージ取得が今回も名前解決で失敗したため、00.32に計画した依存待機・再送・資源上限を先行する。単純文字列mergeやcore成功の捏造はしない。

受信箱はアプリStoreとは独立の、暗号化されたimmutable record集合。単一scope、単一所有者と、既知の認可・鍵で受信前に検証する。ファイル同期後のpending bytes応答と、scratch semantic検証と、永続適用を分離する。新しい暗号方式や意味のあるapply flagを作らない。

状態は毎回実記録と現在の認可から再導出する。閉鎖/失効時に旧データを削除しない。未確認coreを理由に入力を永久無効化しない。外側の有効署名が衝突した時は保守的に隔離し、通常容量が満杯でも一対の証拠だけ残せる予約枠を持つ。

局所受信箱とapplication Storeをまたぐ原子的更新はない。後続のremote commit/materializationでは、receipt token、同じenvelope ID、現在の認可、scope/epochを同一確定境界へ結び付ける必要がある。Inboxはその完了を約束しない。

追加レビューで実Storeとのauthor-slot比較、検査中のrecord改変、最後のcallback後の認可変更、core実行不能と不正入力の区別を是正した。Pinは外部保持の期待集合であり、それ自体が署名付きのネットワーク証明ではない。
