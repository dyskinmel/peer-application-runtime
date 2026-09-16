# ADR-0016 — Separate bounded private upload plane

状態: 00.16.00の局所実験候補。元仕様を凍結・変更しない。

read profileはそのまま保持し、別domain/別listener/別allowlistへmutationを配置する。公開前提や単一巨大requestへ変更しない。作業の許可pathは計画段階の`experiments/keeper-service-upload/`から実体`experiments/keeper-upload/`へレビュー付き更新。検査基準・test inventoryを新セッションで再固定する。

既存Blob incoming spoolは異なる意味のheaderを必要とするため、偽のBlob headerを作って再利用せず、filesystem helpersとack-before-offset規則を再利用した専用journalを作る。このコードは独立監査済みとは言わない。

安定した署名commandと接続freshnessを別にする。indexはcapability index IDと予約scopeへ結合してからstageし、全署名の検証はreserveで行う。objectは署名付きput callと既知inventoryへ結合。保持期間やcapacityの更新を外側接続のnonceで再実行しない。

Keeper commit→stage committed→一時data cleanupの順序を選ぶ。二つの永続域の原子性は主張せず、宛先の同一内容・同一操作の照合で回復する。prefixが確認済みなら欠損を隠さない。fsync後auth変更ならack metadataを進めず、再open時に未確認tailだけを除去する。

検証で、既存0700でないstage directory/0600でない記録を受け付ける問題を確認し、明示拒否へ修正（4負例）。型不正のclient helperが内部TypeErrorを漏らす問題も入力時点で拒否。sealed後も全uploadの同一再試行を認めるが、新しいobject stage作成を認めない。

残課題: 未完stageのcurrent authority下での明示retirement、operation tombstoneの上限と安全な圧縮、未seal leaseの容量解除、kernel blocking latency、native transport。許可失効を理由にデータを勝手に消さない。この版はlocal-only synthetic evidence、製品要件合格ではない。
