# 06 — Wire format・状態遷移・上限

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. protocol version

本版はwire draft `par/1-draft-2`。公開の固定標準や既存v1との互換ではない。最初の実装はexact profile digestの一致を要求し、G0でfreeze後にmajor/minor互換規則を有効化する。

frameは4-byte big-endian body length＋1個のCBOR map。bodyは1,048,576 bytes以下。0-length、末尾の余分なCBOR item、途中EOFを拒否。長さを読む前にbody用allocationを行わない。header/body readにdeadlineとpeer別budgetを設ける。

RFC 8949 §4.2.1を基に、最短整数、有限長、UTF-8厳密検証、integer-key map順、重複key拒否を課す。protocol headerでfloat/tag/undefinedは禁止。NULを含む識別子、invalid UTF-8、未知のcritical fieldは拒否。[S09]

## 2. frame common fields

| key | 型 | 内容 |
|---|---|---|
| 0 | uint | protocol major、候補値1 |
| 1 | uint | message code |
| 2 | bstr(16) | request ID。相手の応答は同じ値 |
| 3 | bstr(32)またはnull | SpaceId。HELLO/AUTHおよび認証前ERRORのみnull可 |
| 4 | map | message別body |
| 5 | uint | flags。候補版は0のみ |

msg codesは `protocol/registry.json`、完全な型は `protocol/par-v1.cddl`。仕様外fieldは候補版でrejectする。future optional fieldは登録済みextension containerに限定する。古い実装が未知fieldを消して再署名してはならない。

## 3. 上限を分離する

`protocol/limits.json`がcandidate hard limitsの機械可読正本。frame 1 MiB、envelope 768 KiB、1 changeのplain bytes 512 KiB、block plain 256 KiB、deps 128、heads 256、inventory page 128 KiB。1つの大きいbaselineはchunkに分割する。

文書の見かけ上の4 MiB soft limitを、合流した合法changeのarrival-dependent拒否に使わない。profile外のresourceは`resource-blocked`とし、無効署名等の`invalid`と区別する。上限値は調整候補であり性能実測値ではない。

## 4. session状態

```text
new → transport-secure → hello-exchanged → app-authenticated
    → space-proof-checked → control-sync → epoch-ready
    → inventory-sync → fetching → applying → caught-up-with-peer
```

認証前はHELLO/AUTH/ERROR以外を受け付けない。Space認可前のCONTROL_GETは、提示されたpin/proofを検証し、認可されたbootstrap範囲にだけ返す。全Space列挙は禁止。Space grantはsession、role、known control headに結ぶ。

新controlがdataより先に必要。未知epochはbounded待機。forkや無権限では共有stateを進めない。restartでは新session nonceとrequest IDsを生成し、durable operation IDは維持する。

## 5. message family

| family | 主要操作 | 契約 |
|---|---|---|
| handshake | HELLO、AUTH | 両方向challengeとnegotiation署名 |
| space/control | SPACE_OPEN、SPACE_ACCEPT、CONTROL_GET/PAGE | 認可・head・epochの確認 |
| sync | HAVE、NEED、CHANGE、APPLY_RESULT | causal dataと適用結果 |
| object | MANIFEST_GET、BLOCK_GET、BLOCK_DATA | scope内のhash指名取得 |
| retain | RETAIN_OFFER/ACCEPT/COMMIT/RECEIPT/RELEASE | 容量予約とroot全体の保管 |
| activity | PRESENCE | TTL付きhintのみ |
| execution | RPC_CALL/RESULT/CANCEL | 同梱handlerのみ、取消しはbest effort |
| error | ERROR | typed code、phase、retry hint、機密なし |

GETは同じrequest IDでも別sessionなら新しいtransport操作。同じdurable operation IDとinput digestでの意味的再試行は受け側台帳で判断する。期限は受信monotonic clockで開始し、送信者wall clockを信用しない。

## 6. flow controlと公平性

peerあたり同期stream 4、native既定active connections 16。優先順位はcontrol→interactive changes→recovery→blob→repair。各優先度内でもSpace公平性を設け、特定Spaceの大量blobで他Spaceの保存通知を塞がない。creditを超える送信は停止・接続切断対象。

各inventory pageにはsnapshot token、cursor、doneを持つ。更新中のcatalogをページ走査する場合、tokenが変われば再走査し、前回の不完全一覧を「全件同期完了」としない。

## 7. 適合判定

CDDLは形の定義であり、署名、依存解決、認可の安全性を証明しない。[S10] 本packageの構造検査もCDDL conformance実行とは別。canonical/reject fixturesと別codec間比較、各messageのstate-invalid試験をG0/G4で実施する。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-WIRE-001"></a>
### PAR-WIRE-001 — framing
**MUST:** length、UTF-8、canonical encoding、map key、trailing bytesを検証してからtyped messageを受理する。
受け入れ: `AT-WIRE-001` / 最初の必須gate: `G0`。

<a id="PAR-WIRE-002"></a>
### PAR-WIRE-002 — 認証順序
**MUST:** session stateに合わないmessageと未認可Spaceの一覧要求を拒否する。
受け入れ: `AT-WIRE-002` / 最初の必須gate: `G2`。

<a id="PAR-WIRE-003"></a>
### PAR-WIRE-003 — negotiation束縛
**MUST:** version/suite/両nonce/両peer/roleを認証transcriptに含める。
受け入れ: `AT-WIRE-003` / 最初の必須gate: `G0`。

<a id="PAR-WIRE-004"></a>
### PAR-WIRE-004 — bounded入力
**MUST:** frame/envelope/依存数等のhard limitsをallocationと展開の前後で検査する。
受け入れ: `AT-WIRE-004` / 最初の必須gate: `G4`。

<a id="PAR-WIRE-005"></a>
### PAR-WIRE-005 — paging整合
**MUST:** inventoryにsnapshot tokenと完了境界を持たせ、途中変更時のcoverageを未完として返す。
受け入れ: `AT-WIRE-005` / 最初の必須gate: `G2`。

<a id="PAR-WIRE-006"></a>
### PAR-WIRE-006 — 互換拒否
**MUST:** 未freeze版はprofile digest一致を要求し、未知の意味を持つdataを適用・再署名しない。
受け入れ: `AT-WIRE-006` / 最初の必須gate: `G0`。
