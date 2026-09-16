# 00.50 適用意図の永続保持・元ID照会

## 境界
`par_application_intent.ApplicationIntent / IntentJournal / DurableApplication` は信頼したPOSIX所有者向けPython APIです。既存FetchApplicationController、DocumentApplier、SQLiteの適用ledgerを再利用し、既存の暗号/nonce/Inbox/文書保存形式は変更しません。0049のowner wireへapplyを追加していません。全製品のexactly-once、インターネット同期、独立監査の合格ではありません。

## 状態と永続化
ApplicationIntentは対象scope、Store/Inbox世代、Device証明書digest、元operation ID、期待revision、対象集合、現在authority/input digest、接続世代をcanonical CBORで固定します。外部保持のJournalPinはmetadata hash、確認済みevent番号、そのhashを持ちます。

`EMPTY → PREPARED → DISPATCHED → OBSERVED → RETIRED`。PREPAREDのみ明示ABANDONできます。DISPATCHEDを同期保存してから既存applyへ一度だけ入ります。再起動、結果不明、失敗、不在回答のいずれもDISPATCHEDの再実行を許可しません。照会は保存済み元ID/targets/期待revisionだけを使用します。coreは照会で呼びません。RETIREは現在権限で同じledger rowを再確認した明示操作で、記録削除ではありません。新しいIDでも活動中意図を乗り越えられず、終了済みIDは再利用できません。

メタデータ/各eventはcreate-only、file fsync、親directory fsync。障害後の生存handleはPOISONEDとして使用禁止。再openは実ファイルを検証・再同期します。空/途中書込のeventはCORRUPTとして停止し、自動切詰め・削除・再送はしません。DISPATCH保存とapply開始の間に停止した場合、行が無くても不実行を断定できず、照会専用で停止する可用性上のコストがあります。

私有0700/0600、nofollow、regular file/所有者/mode/hardlink確認、flockで一協調writer、pid/thread固定。64意図・256event・1event 64KiB。無制限成長やGCは未実装です。同じreceiptの再観測はeventを増やしません。pinが示す既知prefixの欠損/変更は拒否しますが、pinを含む全体巻戻しや未観測tailの消失を検出するoracleではありません。

## 所有者の接続例
```python
binding = DurableApplication.binding(controller)
journal = IntentJournal.create(private_root, binding)
# 外部の安全な保存先にjournal.pin()を保持する責務はembeddingにあります。
r = controller.observe()
coordinator = DurableApplication(journal, controller)
prepared = coordinator.prepare(original_id, expected_revision=0,
                               expected_observation=r['revision'])
# prepare後のpinも外部保存。自動executeはしない。
observed = controller.observe()
result = coordinator.execute(prepared['intentDigest'],
                             expected_observation=observed['revision'])
# 再起動: 同じ対象/Store/Inbox/Deviceで新controllerとJournalPinを用いopen。
# journal.current.digestを使ってinquire。DISPATCHEDのexecute再送は禁止。
```

journalファイルは暗号化されません。本文/秘密鍵は含まずとも対象識別子等は機密メタデータです。OS安全領域、外部pin、初期bindingの信頼性、バックアップ復旧手順はembeddingの責務です。低レベルjournal.observeはreceipt構造/対象を照合するだけで、暗号認証器ではありません。使用経路はDurableApplication→既存DocumentApplier.inquireです。同一UIDの悪意コード、APIの直接迂回、非協力処理をsandbox化する機能ではありません。

## 実測と未実測
70個の専用検査を登録します（journal35、coordinator25、owner-regression1、process9）。8地点で子process自身をSIGKILLし、実SQLite/実ファイルの再openを確認します。positive適用は公開合成materializerによるtransaction契約のみです。fixtureのidentityを意図的に構成し既存内部境界を実行しますが、実Automergeを実行したとはしません。デモもSYNTHETICを明示し、照会時のcore呼出0、ledger不変を検査します。物理電源断、実core、native、公開network、独立reviewは別の未確認項目です。

```bash
python3 tools/check_application_intent.py
python3 examples/durable_application_demo.py
```

## 同時に修正したテストの前提
0049の`test_propose_deadline_reaps_factory`は、50msでfactoryへ入ることを暗黙に仮定し、遅いhostで開始前にdeadlineとなる場合に未生成資源のfinallyを要求していました。計測ではfactory_entered=false、inflight=0でした。既存テストのIDと検査目的は保ち、factory開始を確認して実asyncio deadlineを再設定する決定的検査へ修正しています。別の新規caseは開始前deadlineで資源が作られないことを検査します。製品の期限/安全上限は緩めていません。
