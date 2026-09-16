# 任意の実験適用画面と寿命管理 — 00.53.00

## Authority / scope
`plan/NEXT_APPLICATION_EMBEDDING_0052.ja.md` の任意画面接続です。元の `ApplicationOwnerClient`、`LocalCallerIntent`、Python `ApplicationOwner` / `AnchoredApplication` を再利用します。書込みownerのjournal/PinStore/controller寿命は既存owner processが保持し、今回はrendererへそれらの任意pathや鍵を渡しません。Python適用・SQLite/nonce・owner wireの形式は不変です。

## 構成
`ApplicationEmbedding(context, store, targets, {localExperiment:true})` に信頼した私有portを `attach(context,port)` で明示供給します。既定のlocalExperimentはfalseで、書込み操作は無効です。contextは完全一致のownerKeyへ固定し、新streamだけを明示attachできます。別scope/authority/世代への移行は新bindingと明示診断の責務です。失敗したattachはport所有権を取得しないため呼出側が解放します。

`mountReference(root,note,{applicationEmbedding:binding})` はscope/epoch/controlHeadと単一view leaseをDOM変更前に確認します。optionなしでは追加UIも通信もありません。mount/locale/updateはprepareやdispatchをせず、editor/draft/IMEを再生成しません。authority更新ではbindingをinvalidateし接続を解放します。`applicationCleanup()` が非同期後始末の結果を返します。

## 明示操作
1. caller original slotを `restore` で読み込むか、利用者が供給した元ID・期待revisionと固定targetsを `stage` で私有保存/readbackする。自動ID生成・別IDへの差替えはしない。
2. `observe` して現在の権限・journal状態を確認する。
3. 保存済みoriginalから `prepare` する。下位clientでも保存/readbackを再確認する。
4. UIは対象・元ID・現在snapshotに結合した確認チェックを要求し、その後だけ `dispatch` を許す。retire/abandonも新しい確認が必要。snapshot/locale変化で確認は失効する。
5. 結果不明は元IDで明示 `inquire`。marker・原記録を削除せず、復元後の不在/照会失敗で再送を許可しない。

APIでもlocalExperiment、元ID/targetsと保存状態を確認します。UIの確認は信頼境界の代替ではなく、実認可は既存ownerが行います。期待revisionの現行プロファイル上限は63で変更していません。

## cancel / detach / cleanup
caller store、wire request、embedding actionの未完了数を数えます。cancelは処理へ通知し、保存や同期DB自体の強制中断を保証しません。保存待ち中の取消しでも保存済みの可能性を消さず、UNCERTAIN/元IDを保持します。

画面destroy/detachは一度だけcancel/closeし、保存記録は残します。未完了store/request/action、close失敗・期限切れはCLEANUP_UNCONFIRMEDとして所有参照を保持し、再attachを拒否します。遅い協調処理が完了した場合の `checkCleanup()` は明示確認であり、closeの再試行や強制Task取消しをしません。非協力providerや同一processの悪意をsandbox化する機能ではありません。close自体が失敗した場合は自動解除せず診断が必要です。

## ビルド
単独WP11出力からもrendererをimport可能にするため、application-ownerが使う厳格なplain-data copierをWP11の `owner-data.ts` へ局所化しました。WP10の対応アルゴリズム（getter/余剰prototype/cycle/depth/node/byte制限）を維持し、外側への相対依存をなくします。compiler readbackと既存owner/fetch-owner検査で確認します。

## 実行範囲と非主張
NodeのDOM契約doubleと実Node→private Python owner→SQLite/外部pin検査は別です。前者は画面ロジック、後者は実通信と永続化の証拠ですが、いずれも実ブラウザーの証拠ではありません。肯定的な適用は公開合成materializerを明示使用します。実Automerge、製品PKI、OS-safe storage、全体rollback防止、物理電源断、独立監査、本番適用を認定しません。

ブラウザー補助検査はページ読込み前に管理ポリシーでBLOCKEDになった記録を保持します。origin/security flagを迂回せず、既存blockedな評価をPASSへ変換しません。local metadataは暗号化されず、caller store/owner pinを独立保護する責務はembedding所有者に残ります。

復元の前段と下位client内の再読込の間にoriginal/markerが変化した場合も拒否します。全provider loadを同じ単調検査へ通し、二回目だけ違う有効レコードを返す事例をREDから修正しました。
