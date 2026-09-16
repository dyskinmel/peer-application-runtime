# 00.49 私有owner fetchポート

承認元 `plan/NEXT_FETCH_OWNER_PORT_0046.ja.md`。基準は00.46.00です。
00.47/48の差分は回収できず、今回その実装/テストを流用していません。

## 構成と許可
trusted embeddingが、既に接続されたAF_UNIX stream fd、root FetchPlan、Source/Store/Inbox、targets、現在接続世代、取消し協調ReadSession factory、事前作成した私有0700 plan directoryを渡します。
`serve_fetch_connected(owner,socket,allow_fetch=False)`は既存Event framingを別profile `par-owner-fetch-0049`で再利用します。public listener、path入力、discovery、鍵発行はありません。
既定grantはobserve/inquire/close。明示grantでpropose/accept/resume/fetch/validateが使えます。channel1/worker1/cache1、request64KiB/response1.5MiB、proposal TTL30秒、plan directory最大128entry。無限queue/自動GCはありません。
JSONに権限名を書くことはgrantではありません。full pin（scope/plan/target/保存先世代/接続世代/stream）とexpectedRevisionを照合し、現在authorityとlocal viewを再確認します。

## 状態と安全な再開
observeはネットワークを呼びません。proposeは既存need/haveのみ。acceptはproposal/local viewを再検査し、create-only planとroot/target結合metadataをfsyncしてから返します。取得は別の明示fetchです。
前のstageではownerは未確定apply intentを揮発保持するため、**applyをポートに公開しません**。元controllerへのinquireは可能ですが、applicationがなければINQUIRY_FAILEDであり不在/成功ではありません。
accept前にTS callerがplan SHAを覚え、成功応答喪失や取消し後も保持します。ホスト再起動後はcallerが同じroot/target/bindingを安全に復元し、新しいstream pinを渡して明示observe→resume(original SHA)を行います。
resumeはroot/target結合receipt、plan bytesの外部SHA、現在権限/世代、実Inboxを再検査・同期します。保存済みcandidateを再取得しません。送信provider再起動でsnapshotが変われば既存STALE_VIEWを維持し、明示の再提案・新計画が必要です。
SHA自体とbootstrap pinはcallerが安全に保持する責務があります。receiptは署名ではなく同一ユーザーの悪意コードや全体巻戻しを検出するoracleではありません。識別metadataは0700/0600私有ファイル内であり暗号化DBではありません。

## 取消し・資源
caller Futureとworker Taskを分離。cancel/EOF/closeは一度のEvent通知で、後始末を繰り返しTask.cancelしません。絶対deadlineを使用し、同期fsync完了後もcancel/deadlineを再確認します。期限切れはrollbackではありません。
closeは最大2秒の協調drain後、残るworker参照とcleanupComplete=falseを保持します。残留中は同じownerへ新規channelを開けず、Storeを閉じてはいけません。協調しないfactoryや同一process攻撃をOS隔離しません。

## SDKと参照画面
`FetchOwnerClient`は既存FetchReadBindingで実観測を検証し、旧sequence/context/矛盾progressを拒否します。自動再送/再接続/ACKなし。close中のmutating requestもresumeRequiredを保持します。
`ConnectedFetchChannel`は接続済みfdのframingのみ。`mountReference(...,{fetchOwner:client})`は同scopeの取得panelを併設し、textarea/IME/private draft/shared stateを置換しません。mount時に通信をせず、destroyは借りたclientを閉じません。UI内のcloseは明示的な利用者操作です。
NodeのDOM契約検査と本当のブラウザー検証は別です。今回のブラウザー/real origin/OS UI transportは未確認。

## 検証と限界
`python3 tools/check_fetch_owner.py`。owner27/hardening8/process6/Node37/types1、計79。processはNode→Python owner→TLS providerで、3階層の2round取得、accept/fsync直後SIGKILL、offline resume、stalled TLSのcancel/deadlineを実測します。
元保存形式・Event/ACK protocol・実コアblocked・G0–G11は変更しません。独立レビュー/公開network/製品PKI/native/実ブラウザーは未認定。型/単体PASSから本番合格を導きません。
