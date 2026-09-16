# 14 — SDK API・言語境界・開発体験

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 配布単位

Rust crateを中核に、Swift/Kotlin binding、TypeScript wrapper、headless CLI、optional UI kitを提供対象とする。UniFFIはSwift/Kotlinへのbinding候補だが、生成成功を実機動作と同一視しない。[S24] package名の登録・公開は未実施。

`api/par-contracts.d.ts`はTypeScript形式の契約候補。runtime実装ではない。Rust型と外国語型はIDLから生成する方針だが、公開APIの意味・文字位置・u64・取消しを言語別適合試験で確認する。

## 2. 最小の使用体験

起動→Space作成→受信者requestを承認→文書編集→receiptをUIへ渡す。ユーザーはrelay/keeperを設定しなくても単独利用できる。ただしremote durability達成とは表示しない。

型整合を確認する利用例は `api/example-contract.ts`。各操作は `Result<T>` を返すため、成功分岐を確認してから値を扱う。Space上のAPI名は `docs`、作成結果は `document` と `receipt`、文書readは `found/absent-local/waiting-data/tombstoned/quarantined`。複製観測はAsyncIterableであり、単発の同期完了boolではない。

これは将来API例。今回packageに実行可能なPeerRuntimeはない。`operationId`は利用者操作の重複送信を区別するため呼出側で保持する。SDKは安全なID生成helperを提供し、再試行では同じIDを使う。

## 3. 非同期と取消し

`open`はlocal準備だけを待つ。`close`は保存中処理を完了または未確定として記録し、networkの完了を無制限に待たない。キャンセルの意味は`before-commit / after-commit / outcome-unknown`。commit前はCANCELLED、後はCommitReceiptにcancellationRequestedを付けても保存済み内容を残す。不明はLOCAL_OUTCOME_UNKNOWNとoperation ID。保存済み内容の取消しには別のundo commandを必要とする。

subscriptionはimmutable snapshot＋revision ID。通知coalesceを許すが、listener初期値と最新revisionへのcatch-upを保証する。unsubscribeは冪等、実行中callbackの停止保証とは別。UI callbackのthrowでruntimeを壊さない。

## 4. 型

すべてのIDは型付きopaque string、wireでは固定長bytes。u64をJS Numberへ入れずdecimal stringまたはBigInt。key handleは秘密bytesを通常のSDKオブジェクトへ露出させない。bytesはimmutableまたは所有権移譲を明確にし、FFI後に解放済みbufferを参照しない。

read結果はfound/absent-local/waiting-data/tombstoned/quarantinedをdiscriminated unionとし、nullable documentだけで理由を潰さない。statusにepoch/control headと観測時点を付ける。

## 5. エラー

安定code＋phase＋retry class＋operation ID＋commit ID候補＋redacted detailを返す。`retryable=true`の一語ではなく、`none / same-operation / reconnect / user-action / rebase`を区別する。

主要codeはSTORAGE_FULL、KEY_UNAVAILABLE、LOCAL_OUTCOME_UNKNOWN、NO_REACHABLE_PEER、CONTROL_REQUIRED、NOT_AUTHORIZED、EPOCH_REBASE_REQUIRED、CONTROL_FORK、ACTOR_EQUIVOCATION、DEPENDENCIES_PENDING、RESOURCE_BLOCKED、UNSUPPORTED_PROFILE、CURSOR_EXPIRED、RPC_OUTCOME_UNKNOWN。wireのOUTCOME_UNKNOWNはphaseに応じてlocal/RPCへ写像する。文字列の例外メッセージをparseして制御しない。

## 6. manifestと拡張

アプリmanifestはAppId、schemas、使うfeature profile、必要OS permissions、contribution default、support対象を宣言する。permissionを増やす更新はhostが再同意を取る。plugin/adapterはhost process内で実行する以上、単にinterfaceを実装しただけでsandboxedとは言わない。

AI agentやautomationも同じtyped commandを使う。読み取り診断とstate変更を分離し、破壊的操作はpreview plan、対象revision、confirmation tokenを必要とする。ログやpeer本文の命令文を管理コマンドとして実行しない。基本SDKにAI serviceの契約を必要としない。

## 7. 開発者導入の受け入れ

クリーン環境で同梱quickstartのみを読み、クラウド登録なしで二台同期へ進める。CLIに `doctor --local --json`、`protection inspect`、`repair plan/apply` を含める。説明書のコマンドはCIで実行し、実在しないflagを放置しない。失敗時には最初の関係する原因を示し、秘密を送信するsupport bundleを自動作成しない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-SDK-001"></a>
### PAR-SDK-001 — 型付き結果
**MUST:** read/commit/cancel/errorをdiscriminated unionで公開し、u64を損失なく往復する。
受け入れ: `AT-SDK-001` / 最初の必須gate: `G6`。

<a id="PAR-SDK-002"></a>
### PAR-SDK-002 — 取消し境界
**MUST:** cancelはcommit前後と結果不明を区別し、保存済み操作を消さない。
受け入れ: `AT-SDK-002` / 最初の必須gate: `G1`。

<a id="PAR-SDK-003"></a>
### PAR-SDK-003 — 購読契約
**MUST:** snapshot通知はrevision付きでbounded/coalescingとし、unsubscribeは冪等にする。
受け入れ: `AT-SDK-003` / 最初の必須gate: `G6`。

<a id="PAR-SDK-004"></a>
### PAR-SDK-004 — 安全なautomation
**MUST:** 破壊的管理commandにはpreviewと対象revisionの再確認を要する。
受け入れ: `AT-SDK-004` / 最初の必須gate: `G6`。

<a id="PAR-SDK-005"></a>
### PAR-SDK-005 — 導入再現性
**MUST:** 配布したquickstartのコマンドとサンプルをクリーン環境で試験する。
受け入れ: `AT-SDK-005` / 最初の必須gate: `G10`。

<a id="PAR-SDK-006"></a>
### PAR-SDK-006 — binding所有権
**MUST:** FFI/JS境界でbuffer・callback・key handleの生存期間とthread制約を定義する。
受け入れ: `AT-SDK-006` / 最初の必須gate: `G6`。
