# 02 — 内部構造・責務境界

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 採用案と比較

推奨はRust portable core＋host ports＋headless presenter。通信は当初libp2p、文書はAutomerge core。どちらも交換可能な責務境界を設けるが、同時に複数backendを作らない。native/browserで既存Repoの互換を仮定せず、PARの署名付きchangeを共通形式とする。[S01][S02]

iroh等で接続部分を集約する案はP0の比較対象に残す。全面自作はNAT、暗号、CRDTの検証負担を増やすため採用しない。既存部品で満たせない契約が見つかれば、保証を消すのでなく最小adapterか採用変更をADRで判断する。

## 2. 依存方向

```text
Application / optional UI kit / CLI
        ↓ commands       ↑ immutable views + typed events
Headless presentation / SDK bindings
        ↓
Use cases: edit / join / sync / retain / recover / migrate
        ↓
Domain: identity, authority, documents, replication, resource policy
        ↓ interface only
Ports: AtomicStore, BlockStore, Crypto, KeyVault, Transport,
       Clock, Random, Lifecycle, Budget, Diagnostics
        ↑ implementations
Native host (SQLite/libp2p) / Browser host (IndexedDB/JS transport)
```

portable coreにGUI、socket、filesystem pathname、HTTP client、OS singletonを入れない。clock/random/networkを注入できる構造にし、決定的なシミュレーションを可能にする。これによりUIのPolishとprotocolの再検証を不要に結合しない。

## 3. 所有権・並行性

1 runtime data directoryに1書込みcoordinator。各Spaceのcontrol activationと各Documentのlocal transactionは直列化するが、別文書のparse、署名検証、blob transferはbudget内で並行可。public callbackでdomain lockを保持しない。actorのsequence採番とoutbox保存は同じtransaction。

複数windowは同じruntimeへ接続する。複数processで同じDBを共有する場合はIPC owner modeを使い、無調整の別runtimeによる同じactor利用を拒否する。browser multi-tabはhost内leader lease＋DB transactional fencingを用い、lease期限だけで排他を保証したことにしない。

## 4. 主なportの契約

| Port | 入力→出力 | 禁止 |
|---|---|---|
| AtomicStore | transaction plan→durable receipt/definite abort/unknown | false success、暗黙network |
| BlockStore | bounded bytes→content ref、read verified bytes | 未完blobを完成扱い |
| Crypto | key handle＋typed context→cipher/signature | silent suite downgrade |
| KeyVault | key purpose＋user policy→handle/class | hardware-backedの推測 |
| Transport | approved peer route→authenticated byte stream | 自動の外部endpoint選択 |
| Clock | monotonic duration＋wall display＋boot ID | wall clockを認可順に使用 |
| Budget | scope＋resource estimate→permit/refusal | 無制限queue |
| Diagnostics | typed redacted record→local sink | 本文・秘密を含むログ |

## 5. 障害封じ込め

受信peerのmalformed dataでruntime全体を停止しない。crypto/authに疑義があれば当該Space/Documentを隔離する。正当な無関係Spaceのlocal編集は継続する。未確定の保存を成功扱いしない一方、network停止だけで文書をread-onlyにしない。

重いmaterializationはworker budgetを使う。nativeでは必要に応じ別processのcodec worker、browserではWorkerを使う。timeoutでRustの実行中関数が安全に強制停止できるとは扱わない。

## 6. 初期リポジトリの切り方

最初は `par-contracts`、`par-core`、`par-host-native`、`par-conformance`、`par-cli` の機能単位。core内ではidentity/authority/data/storage/syncをmodule分離する。public typeとportは先に安定させ、必要になった境界だけ独立crateにする。大量の空crateや未使用plugin機構は作らない。

UIは `par-presenter` と各platform component kit、参照アプリに分割。SDK本体にReact/SwiftUI/Compose依存を要求しない。optional hosted toolsやAI診断を加えても基本機能の依存にはしない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-ARCH-001"></a>
### PAR-ARCH-001 — host分離
**MUST:** portable coreはOS・GUI・transport実装へ直接依存せず、Clock/Randomを含む狭いportへ依存する。
受け入れ: `AT-ARCH-001` / 最初の必須gate: `G0`。

<a id="PAR-ARCH-002"></a>
### PAR-ARCH-002 — writer排他
**MUST:** 同じdata directory・actorを同時に複数writerへ割当てない。
受け入れ: `AT-ARCH-002` / 最初の必須gate: `G1`。

<a id="PAR-ARCH-003"></a>
### PAR-ARCH-003 — 再現可能性
**MUST:** 時刻・乱数・配送・保存障害を制御できる試験hostを提供する。
受け入れ: `AT-ARCH-003` / 最初の必須gate: `G0`。

<a id="PAR-ARCH-004"></a>
### PAR-ARCH-004 — callback隔離
**MUST:** callback内でdomain lockを保持せず、queue上限と再入・取消し規則を公開する。
受け入れ: `AT-ARCH-004` / 最初の必須gate: `G1`。

<a id="PAR-ARCH-005"></a>
### PAR-ARCH-005 — 障害局所化
**MUST:** peerの不正入力で別Spaceの健全なlocal保存を止めない。
受け入れ: `AT-ARCH-005` / 最初の必須gate: `G4`。

<a id="PAR-ARCH-006"></a>
### PAR-ARCH-006 — 交換可能なUI
**MUST:** business stateとpermission判定はpresenter/domainへ置き、visual layerはtyped commandとviewだけで操作する。
受け入れ: `AT-ARCH-006` / 最初の必須gate: `G6`。
