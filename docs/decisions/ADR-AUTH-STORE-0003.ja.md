# ADR-AUTH-STORE-0003 — 認可付き保存はCRDT適用ではない

今回のwriteは実際の署名・暗号化・認可・原子的保存を行うが、inner changeとcacheは合成のopaque bytesである。Automerge actor/inner依存/seed semanticsは未確認。envelopes.stateは必ず `pending` にし、`applied`、production-qualified、G0合格を返さない。fixtureを本番CRDTの実装と扱わない。

状態識別、APIの引数、スキーマは局所実験のcandidate。新規Rust crate/SDKを作成したとは主張しない。public API越しでないraw SQLite/private object mutationは信頼境界外。scopeは単一thread・協調する単一local writer・観測済み認可履歴。署名された制御履歴のcapacityは前実験と同じく1,024件。暗号化activation材料は1セット900,000 bytes、1 Space 1,024セットまでをこの実験の防御的上限とする。製品の能力上限や目標をこの値へ縮小しない。

実験合格は `AUTH-STORE-LOCAL` のみへ結び付ける。149個の製品requirementは元の作業単位が所有したままで、本実験はrelated_requirementsとして参照する。独立review、修正版provider、実機/ネットワーク、物理fault、native bindingの証拠は後段に必要。
