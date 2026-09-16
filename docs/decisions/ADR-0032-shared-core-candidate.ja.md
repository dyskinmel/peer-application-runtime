# ADR-0032 — 実coreの不在を隠さず、共有変更の保存境界を先行

Status: CANDIDATE / actual engine unverified.

00.31の読み取りポートを共有書き込みへ拡張する前に、内側のactor/seq/deps/change hashが外側署名ヘッダーと一致する条件を固定する。実ライブラリは未取得なので実装済み境界と実証済み意味を分離する。

決定: @automerge/automerge3.4.1のAPIに限定した候補loader/probeを作る。実package treeとentryの全byteを固定し、transitive dependencyがあれば拒否。通常のSharedWriterは本物kindだけを受け付ける。合成portは公開試験の明示opt-inに限定し、innerValidated=falseを強制する。既存DBのpendingは維持し、UIを接続しない。

試験で検証するもの: immutable入力、既存domain hashによるactor、厳密な依存集合、実署名/復号/旧認可履歴、nonce前の拒否、保存transactionの現在認可、再試行、source/engine変更。core報告JSONそれ自体はproofではなく、信頼する所有processとbyte-pinnedアダプターの結果。

比較: 別の簡易CRDTでの代用は拒否。ライブラリ取得まで全作業停止も不要。巨大native統合を未検証で有効にするより、狭いnote profileで実core試験を通してから増やす。

留保: 独立review/本物merge/相互運用/OS安全境界/大規模性能/永続materialization未実証。128依存+新changeのapplied setは129を許す。作成cloneには指定actorが必要。圧縮chunkは明示的未対応。artifact取得後の修正余地を残し、規範仕様の正本は改変しない。
