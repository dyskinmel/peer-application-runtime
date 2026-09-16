# 00.46: 有限の依存frontier計画と明示validation/application境界

承認元: `plan/NEXT_FETCH_APPLICATION_BRIDGE_0045.ja.md` と00.45後のOwner継続承認。
不変baseline、wire、Store形式、full-scope依存、製品gateは変更しない。

## 決定
- 暗号化payload未取得の先の依存集合はhave/need descriptorだけからは導けない。現在Inboxで検証できる不足frontierだけを一計画にする。深い依存は取得後の明示再検証・再計画。自動反復/再送なし。
- DependencyPlannerは既存Source/ReadSessionを使う。全scope/Inbox世代/接続世代/local snapshotを固定し、needとhaveの全応答を単一remote snapshotに照合。pageの順序・重複・総量・欠損を拒否する。計画中にget/receive/applyしない。
- Proposalのacceptは元local snapshotが現在も同じことを再確認。承認後のFetchPlanは既存のcreate-only保存/external SHAを使う。Proposal自体は揮発的で、再起動後の自動承認はしない。
- FetchApplicationControllerは既存SyncInbox.inspect/validateおよびDocumentApplier.apply/inquireのowner側境界。計画digest・targets digest・全scope・Store/Inbox世代・stream/sequenceで観測を固定。明示commandは最後に提示したrevisionと現在local snapshotが一致する場合だけ。
- default core=None。contract-test-doubleは製品controllerで受理しない。適用はoptionalの既存DocumentApplierへ明示operation IDで委譲し、nonce/transaction/履歴を再実装しない。applyの結果不明は元IDを保持し、自動再実行しない。
- 新しいTypeScript読取bindingと小さな独立status rendererを追加。本文/draft/shared-commit/remote-protectionへ転記しない。raw JSONは所有者認証の代替ではない。旧stream/plan/sequence、close後/新refresh後の応答を拒否。

## 予算と制約
1回targets<=64、plan<=64records/8MiB、catalog<=128、page<=16、queries<=32、総deadline<=120秒、JSON観測<=256KiB。
同期署名/DB/fsyncはpreemptしない。session factoryはtrusted/cancel協調が必要。取消しはfinallyで所有資源を回収し、CancelledErrorを成功に変換しない。
https://docs.python.org/3/library/asyncio-task.html#task-cancellation (参照日2026-09-08)

## 非主張
実Automerge未導入、public IP/DNS/PKI/実browser/native/物理電源断/独立レビューは別gate。契約double・Node DOM fixtureは実CRDT/実browser合格ではない。
