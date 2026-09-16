# 00.41 — 明示的なイベントクライアント・ライフサイクル

状態: local candidate。入力authorityは `plan/NEXT_EVENT_CLIENT_LIFECYCLE_0040.ja.md` と今回のOwner承認。
既存command/subscription wire、永続形式、共有commit、認可規則、製品gateを変更しない。

## APIと境界

`EventCommandClient(expectedContext, {requestTimeoutMs?, cleanupTimeoutMs?})` は同一context専用。
`rebind(channel, observedContext, hostId)` はhello済みの信頼した所有者接続を**明示的に**受け取る。
接続の発見/作成/認証はembedding側。contextはapp/space/stream/epoch/schema/issuer/journalGeneration/authorityの完全一致。
別authorityやgenerationへの暗黙移行は禁止。変更には別clientと別の明示的な承認が必要。
成功したrebindだけがchannel所有権を移す。失敗したrebindのcandidateはcallerがcloseする。
同じchannel objectの再利用は拒否。hostIdは同じ所有者への新しい接続でも同じになり得るため、client自身の単調generationでも応答を区別する。

`publish(input,{signal?})` は一件のimmutable入力を保持してから送信。元operation ID/元入力は呼出側も保持する。
結果不明が残る間は同じID・新しいIDとも発行を拒否する。同じIDの異なる入力も拒否。
`restoreUnknown(input)` は再起動後にcallerが保持した元入力を一件復元するだけで、ネットワークもDBも書かない。
入力の永続性・真正性・秘密管理はcallerの既存境界。新しい平文pending DB/ログ/自動ID生成は追加しない。
`inquire(operationId,{signal?})` は保持している元IDの照会だけ。rebindとinquireは別操作。
not-found-localは現在の照会結果で、未実行証明でも再送許可でもない。照会失敗や取消しと不在を分ける。
既に得たlocal receiptと異なるevent/sequence、または不在は矛盾として拒否し、過去receiptを消さない。
その過去receiptは現在の可用性、共有文書COMMIT、remote protectionの証明ではない。

## 競合と資源

一件の実行中操作、保留入力一件、現接続一件。接続世代と操作tokenを両方照合する。
rebind/closeは古い操作をabortし、遅延応答は新状態へ反映しない。古いpublishの戻り値も保守的にunknown。
旧照会はCLIENT_SUPERSEDED。再bindはcancel前処理の完了や同期DBへの割込みを意味しない。
closeはterminalかつ冪等。待機操作を解放しchannel.closeを一度だけ呼ぶ。
async closeは退役接続最大4件＋最終close時の現接続1件まで、cleanupTimeoutMs（既定1000、10〜60000）で待機を区切る。
cleanup失敗/期限超過は記録し新接続受付を停止する。実リソース解放済みとは報告しない。
返されたPromiseのrejectionは観測する。caller abort listenerはretire時に即時・一度だけ解放し、通常完了時はfinallyで解放する。timerも解放する。
この境界は同一process内の任意コード、悪意のProxy、非協力的なnative side effectをsandbox化しない。

## 表示

`current`はcontext、revision、bindingGeneration、connection、operation、requiresInquiry、過去local receipt、cleanup状態のimmutable snapshot。
本文やparentは含まない。`view` は別の型付き表示モデルで、sharedCommit/remoteProtection/automaticRetryは常にfalse。
原文note、私有draft、既存のshared document observationへmergeしない。ブラウザー/native表示の実機認定ではない。

## 実装検証計画

- [x] CP1: 旧世代/close/abort/context変更/元ID/不在・失敗/資源制限のRED testsを保存。
- [x] CP2: state machine、copy/validation共通化、typed projectionを実装しunit/typesをGREEN。
- [x] CP3: 既存実Python ownerとSQLite再起動/実SIGKILL、異なるhost、明示ACKを検証。
- [x] CP4: 検査identityを加算登録。旧176件、67tasks/149requirements/16WP重みを保持。
- [ ] CP5: 固定candidateで全28laneを検証しcheckpoint/resumeを照合。
- [ ] CP6: 完全source/history/evidenceを00.41 ZIPへ格納し別展開先で再検証。

元85仕様ファイル、REG-0033未確定、457過去証跡欠損を維持。未実行はPASSへ変えない。
CP5以後の結果は固定sourceに書き戻さずrelease/STATUSと証跡へ保存する。
