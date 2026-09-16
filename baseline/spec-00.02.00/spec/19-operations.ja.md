# 19 — 運用・診断・プライバシー

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. operatorが答えられる問い

「どのデータがこの端末だけにあるか」「誰からいつ、何のrootの保管確認を受けたか」「現在どの経路を使うか」「なぜ同期できないか」「停止すると何が不足するか」を、平文本文や秘密鍵を収集せず回答可能にする。単一の緑ランプやping応答を耐久性の証拠にしない。

診断には観測時点、local revision、対象Space、根拠object digest、freshness、reason code、対処可能actionを付ける。peer名とIP、SpaceId、document IDも利用状況を漏らすmetadataである。通常ログはセッション内pseudonymを使用し、外部exportは既定redactedとする。

## 2. 診断command契約（製品実装予定）

| command | read/write | 成功の意味 |
|---|---|---|
| `par doctor --local --json` | read-only | 保存領域、鍵参照、profile、時刻不確実性を検査。通信なし |
| `par doctor --connectivity --json` | 明示的なprobe | 設定済み宛先だけに接続して観測。外部ホストの自動追加なし |
| `par protection inspect <root>` | read-only | receipt・復元closure・取得観測を別々に表示 |
| `par export <space> --encrypted` | 新規出力 | 認可範囲のsnapshot export。権限を作らない |
| `par repair plan <store>` | read-only | 元DBを変更しない修復提案と必要な容量 |
| `par repair apply <plan-digest>` | write | 承認済みplanを新領域へ適用、検証後だけ切替 |
| `par contribution pause` | policy write | 新規貢献停止。既存leaseへの影響を返す |

exitは0=指定範囲の検査完了/期待条件成立、2=degradedまたは利用者対応、3=操作失敗、4=前提不足/結果未確定。JSONにもresultとscopeを入れる。repairの実行成功を失われたデータの全復旧と同一視しない。

## 3. ログ・metrics

構造化eventは `{event_version, monotonic_seq, observed_at, component, code, severity, operation_ref, scope_ref, attributes}`。本文、key material、招待secret、復旧kit、平文file名、完全なraw messageは禁止。秘密の値をhash化しただけでは低entropy情報の保護にならないため、必要でなければ保存しない。

metricsはlocal commit latency、outbox oldest age、closure欠損数、active streams、queue bytes、retries、decode budget、consentで分離した貢献bytes、quota拒否理由。平均だけでなく分布と母数を記録する。診断export前にプレビュー・選択・保存先確認を設ける。telemetryは既定offで、無送信構成でも全診断が使える。

## 4. runbook

| 事象 | 最初の安全動作 | 再開条件 |
|---|---|---|
| authority fork | 共有適用・権限発行停止、local read/export維持 | 明示的なfork解決/新Space移行。勝手に高seqを選ばない |
| local corruption | 元領域を保全、read-only診断 | 検証済みclosureで新storeを構成し原子的切替 |
| disk full | commit前に拒否、pending状態を保持 | 空き容量確認、同じoperation IDを再照会してからretry |
| Keeper停止 | receiptを消失と断定しない、freshness低下を表示 | 別の到達可能なsourceから新しい適格peerへ複製 |
| device盗難 | 他の認可済みauthorityから失効、新epoch | 新しいmembership/key到達を確認。旧平文の回収は不能 |
| authority喪失 | 既存read/write方針を維持、制御更新不能を表示 | 確認済みauthority backupまたは新Space移行 |
| 誤削除 | GCを急がずexport/復旧候補を確保 | tombstoneの意味を守り新documentとして復元 |

各runbookは「原データを壊さない第一手」「承認が必要な操作」「結果を検証するoracle」「諦める条件と残存データのexport」を含む。誤操作を回復可能性ゼロへ増幅する自動修復は禁止。

## 5. privacy boundary

暗号化してもpeer同士の接続、転送量、objectサイズ、同一Space内の相関は漏れ得る。membership一覧は認可済み相手だけへ公開するが、opaque Keeperにも保管対象の規模・時点は観測される。匿名通信や法的な全端末消去保証を主張しない。利用者が開示した復号内容のcopy/exportを技術的に取り戻せない。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-OPS-001"></a>
### PAR-OPS-001 — 診断根拠
**MUST:** 保護・同期・接続の診断をscope/root/観測時点/freshnessに結び付ける。
受け入れ: `AT-OPS-001` / 最初の必須gate: `G3`。

<a id="PAR-OPS-002"></a>
### PAR-OPS-002 — 秘密を記録しない
**MUST:** 通常ログと既定診断exportに秘密鍵・平文本文・招待secretを含めない。
受け入れ: `AT-OPS-002` / 最初の必須gate: `G4`。

<a id="PAR-OPS-003"></a>
### PAR-OPS-003 — read-only診断
**MUST:** local doctorとrepair planはDB/鍵/接続設定を変更せず外部通信しない。
受け入れ: `AT-OPS-003` / 最初の必須gate: `G1`。

<a id="PAR-OPS-004"></a>
### PAR-OPS-004 — 修復の安全性
**MUST:** 修復は元領域を保全し、新領域の検証後だけactivateする。
受け入れ: `AT-OPS-004` / 最初の必須gate: `G9`。

<a id="PAR-OPS-005"></a>
### PAR-OPS-005 — 停止の説明
**MUST:** Keeper/Relay停止前に有効lease・進行中転送・不足コピーへの影響を表示する。
受け入れ: `AT-OPS-005` / 最初の必須gate: `G6`。

<a id="PAR-OPS-006"></a>
### PAR-OPS-006 — 無送信観測
**MUST:** telemetryなしでも同じlocal diagnosticsを使え、exportは明示操作に限定する。
受け入れ: `AT-OPS-006` / 最初の必須gate: `G11`。
