# 00.46 有限の依存取得計画・明示検証・型付き状態表示

これはLOCAL候補であり、全依存の自動発見、実Automerge、一般公開P2P、製品認定ではありません。
承認元 `plan/NEXT_FETCH_APPLICATION_BRIDGE_0045.ja.md`、決定 `docs/decisions/ADR-FETCH-BRIDGE-0046.ja.md`。

## 所有者側API

`product.wp09.par_secure_fetch.dependencies.DependencyPlanner(source, binding, current_generation)`。
sourceは既存の厳格なSource、bindingは所有者が登録した相手Device・TLS pin・scope・世代、factoryは認証済みReadSessionを渡す信頼した協調的関数です。

```python
proposal = await DependencyPlanner(source, binding, current_generation).build(
    target_envelope_ids, open_authenticated_session,
    max_records=64, max_bytes=8 * 1024 * 1024,
    page_size=16, max_queries=32, timeout=30, cancel=cancel_event)
# ここまで get / receive / apply は呼ばれない。
# 利用側がproposalを確認し、別の明示操作で承認する。
plan = proposal.accept(source, current_generation)
if plan is not None:
    plan_sha = plan.save(private_new_plan_path)  # create-only。外部へSHAを安全に保持。
    # 実行も別の明示操作。保存成功は文書適用ではない。
    await FetchClient(plan, source, current_generation).execute(open_indexed_session)
```

targetsは既にInboxへ保存された候補のenvelope IDです。未取得rootは拒否します。
暗号化された未取得payloadの深い依存はdescriptorだけでは分からないため、現在判明した不足部分だけを提案します。
previous envelopeのinner IDが不明なら有限have一覧を走査します。欠損、循環/隔離状態、予算超過、ページ矛盾、local/remote snapshot変化では停止します。
NO_FETCH_REQUIREDは「現在の観測で不足がない」だけです。意味論的妥当性や世界全体の最新状態の証明ではありません。
提案は揮発的。再起動後は再照会・新提案が必要。承認済みFetchPlanとInboxの復旧は00.45の外部SHA/pinを使います。

## 明示的な検証と適用の接続

```python
from product.runtime_read.fetch import FetchApplicationController
controller = FetchApplicationController(plan, source, target_envelope_ids,
    current_generation, core=None, application=None)
view = controller.observe()  # 読取のみ
checked = controller.validate(expected_revision=view['revision'])
# 実コアなしは CORE_BLOCKED / CORE_UNAVAILABLE。保存済み候補は失われない。
```

applicationに既存DocumentApplierを渡した場合だけ、`apply(operation_id, expected_revision=..., expected_observation=...)` を明示的に委譲できます。
controller自身は文書表やnonceを書きません。試験用doubleを許可したApplierは接続拒否。
試験には合成materializerで既存SQLite transactionを走らせる13件の独立contract groupがありますが、実Automergeではありません。

委譲に入った後の取消し・例外は保守的にOUTCOME_UNKNOWN。元のIDと期待revisionを保持し、同じ意図へのinquireだけを受理します。
照会失敗・NOT_OBSERVEDは再送許可にしません。元意図の保存記録を観測するまで新applyを拒否します。
この未確定意図のlatchはcontroller内で揮発的です。利用側は元ID・対象・期待revisionを安全に保持し、新controllerの初回操作をinquireにしてください。
独立の暗号化pending-command保管やプロセス越しの書込command portは未実装です。新controller生成を安全な再送許可と解釈しないでください。

## 型付き状態パネル

`product/wp11/src/fetch-observation.ts`（配布JSとd.tsはlib/）。
`FetchReadBinding(pin, {observe: async () => ownerObservation})`、`mountFetchStatus(statusRoot, binding, 'ja')`。
取得候補専用のrootへマウントし、shared editorやdraftへ混ぜないでください。DOM更新はtextContentだけです。
完全scope・plan/targets digest・Store/Inbox/接続世代・stream・sequence・JSON digestを検査し、待機中は旧表示を隠します。
新refresh/close後の旧応答、既知operation記録と矛盾する応答、未知fieldやgetterは拒否します。
SHAは整合性であり、信頼できない送信者を認証するものではありません。認証したowner portはembeddingが渡します。
公開command transportの実装や、既存画面への完全組込みではなく、呼出し可能な独立DOMコンポーネントです。
Nodeの小さなDOM代替で構造/lifecycleを検査しており、実browser・レイアウト・スクリーンリーダー検証は未実施です。

## 実行・中断

`python3 tools/check_fetch_bridge.py` は109登録結果（planner27/controller19/process6/synthetic-application13/node43/types1）。
`python3 examples/fetch_bridge_demo.py` は実privateTLS・別process・3階層逆順取得を行い、候補数1→2→3、offline明示検証CORE_UNAVAILABLEを確認。
新しいprocess suiteは4つの保存地点でSIGKILLします。物理電源断ではありません。
factoryは取消しに協調する必要があり、同一processの悪意コードや停止しないnative処理をsandbox化しません。
同期DB/fsyncを割り込んで止めず、戻った後の期限超過/取消しを成功にしない契約です。
このbridgeの全局所観測でapplied/localCommitted/acknowledged等はfalse（この表示では認定しない）。実適用記録は専用operation欄で区別し、共有状態は既存ApplicationObserverで再確認します。
