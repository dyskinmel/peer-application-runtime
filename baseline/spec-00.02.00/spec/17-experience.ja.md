# 17 — UX・操作flow・状態説明

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. UIを提供する理由

PARはheadless SDKが本体だが、開発者が毎回「保存できたか」「なぜつながらないか」を一から設計すると保証の意味が崩れやすい。そこでoptional componentsとしてConnectionStatus、ProtectionStatus、InviteFlow、RecoveryWizard、ContributionPanel、ConflictInspector、DiagnosticsPanelを提供する。

UI kitを使わないアプリも許容するが、同じ状態契約とアクセシビリティ要件を実装する。デザインの統一を強要せず、意味の一貫性を守る。

## 2. 情報階層

最上位は利用者の作業。ネットワークgraphは通常画面の主役にしない。日常表示は「この端末に保存済み」「2台で保管確認」「接続待ち」程度。詳細panelでコピー場所、最終確認、経路、権限head、不足理由へ段階的に開ける。

保存statusとセキュリティstatusを一つの信号灯へ潰さない。例えば、local保存は成功だが権限更新待ち、2コピーあるが現在接続不能、browser保存で永続化未許可を表示できる。

## 3. 基本画面

| surface | 主な内容 | 常に必要な操作 |
|---|---|---|
| Onboarding | ローカル開始、既存Space参加 | アカウント登録なしで開始、後で設定 |
| Workspace | 文書/添付/共同編集 | 保存status、同期詳細、競合への入口 |
| Connection | peer、direct/relay、失敗原因 | 再試行、手動route、設定確認 |
| Protection | copies、freshness、recovery checkpoint | Keeper追加、復旧確認、export |
| Invite | 相手fingerprint、Space、role | 確認、取消し、manual code/file |
| Conflict | 並行値・出典・diff | 選択、統合、保留、private保存 |
| Recovery | plan、keys、download、verify | 一時停止、再開、部分export |
| Contribution | 容量・帯域・電源・対象Space | pause、graceful leave、force stop |
| Security | devices、known control、key状態 | 失効、移管、backup、branch export |
| Diagnostics | redacted原因・経路・revision | ローカルexport、共有前preview |

## 4. 初回導入flow

Local start → 文書を一つ作る → 「ほかの端末と共有」 → 相手JoinRequestをQR/fileで受け取る → fingerprint/roleを確認 → Space承認 → 接続 → 保存/複製の違いを短く提示。

QR読取りを唯一の経路にしない。カメラ拒否・視覚制約ではfile/manual codeで同じsecurity確認ができる。fingerprintを色や絵だけで伝えない。認可発行者不在はpending画面にし、失敗したように何度も招待を作らせない。

## 5. 状態別microcopy

| status | 推奨日本語 | 避ける表現 |
|---|---|---|
| local committed / no peers | この端末に保存済み。ほかの端末への複製待ちです。 | 保存失敗、完全バックアップ済み |
| retained + stale | 2台の保管記録があります。現在の状態は未確認です。 | 安全です、現在2台オンライン |
| seed pending | 共有権限の更新を確認しました。新しいデータを取得しています。 | 同期済み |
| rebase required | 共有状態が更新されました。未共有の編集を確認してください。 | 編集を破棄しました |
| recovery verify | データを検証しています。復旧はまだ完了していません。 | 完了100% |
| missing key | 復号に必要な復旧キーがありません。データ自体は保持されています。 | データがありません |
| control fork | 共有権限の履歴に不一致があります。新しい共有を停止しました。 | ネットワークエラー |

文言はlocale catalogへ分離し、logicはmessage keyから逆算しない。

## 6. 操作安全性

失効、Space削除、鍵export、authority移管、強制Keeper停止にはpreviewと具体的対象を示す。confirmation tokenはplan digestと対象revisionへ結ぶ。画面を開いてから状態が変われば再preview。単なる「本当によろしいですか」で重要影響を隠さない。

rebaseでは元のprivate編集を保持し、選択したdiffだけ新epochへ適用。authority不在をUIで迂回しない。undoは可能範囲を表示し、鍵漏洩やremote配布を取り消せたと誤解させない。

## 7. 国際化・アクセシビリティ

webの目標はWCAG 2.2 AA。追加でfocus visibility、十分なtouch target、reduced motionを明示設計する。AA target sizeの基準とより大きい推奨値を混同しない。[S16] nativeは各OSのaccessibility tree、VoiceOver/TalkBack、keyboard/switch access、dynamic textを試験。

色だけで状態を示さない。screen readerへstatus更新を毎文字通知せず重要遷移をcoalesceする。RTL、200%文字拡大、狭幅、長い日本語/ドイツ語、IME、ハイコントラストに耐える。network graphには同じ内容のtable/list表示を必ず用意。

## 8. UXの検証目標

初回利用者が説明書を読まずにlocalノートを作れる、誘導のみで招待と復旧へ進めることをユーザビリティ試験で測る。目標値はPERF/QAのcandidateであり、未実施の成功率を出さない。終了後には「どこに保存されているか」を本人の言葉で説明できるかを確認する。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-UX-001"></a>
### PAR-UX-001 — 状態の独立表示
**MUST:** local保存・remote保管・現在接続・認可・復旧進捗を独立した意味で表示する。
受け入れ: `AT-UX-001` / 最初の必須gate: `G6`。

<a id="PAR-UX-002"></a>
### PAR-UX-002 — 段階的開示
**MUST:** 通常画面では作業を優先し、詳細panelで根拠・時点・原因に到達できる。
受け入れ: `AT-UX-002` / 最初の必須gate: `G6`。

<a id="PAR-UX-003"></a>
### PAR-UX-003 — 導入の代替経路
**MUST:** QR以外のmanual/file flowを用意し、権限拒否やauthority不在でもlocal作業を保つ。
受け入れ: `AT-UX-003` / 最初の必須gate: `G6`。

<a id="PAR-UX-004"></a>
### PAR-UX-004 — 破壊操作の確認
**MUST:** 破壊的・機密操作は影響previewをplan digestとrevisionに結び、変更時は再確認する。
受け入れ: `AT-UX-004` / 最初の必須gate: `G6`。

<a id="PAR-UX-005"></a>
### PAR-UX-005 — アクセシビリティ
**MUST:** 意味的ラベル・keyboard・拡大・RTL・reduced motionを提供し、webはWCAG 2.2 AAをqualification対象とする。
受け入れ: `AT-UX-005` / 最初の必須gate: `G6`。

<a id="PAR-UX-006"></a>
### PAR-UX-006 — 編集意図の保全
**MUST:** IME・selection・private draft・rebase/undoをremote更新で無断消去しない。
受け入れ: `AT-UX-006` / 最初の必須gate: `G6`。

<a id="PAR-UX-007"></a>
### PAR-UX-007 — 真の完了
**MUST:** download率・receipt数だけで復旧/全体保護の完了を表示しない。
受け入れ: `AT-UX-007` / 最初の必須gate: `G3`。
