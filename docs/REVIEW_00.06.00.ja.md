# 00.06.00 — 自己点検と未完了条件

独立reviewerは起動していない。同一作成者によるコード読解、負例、実行結果の点検である。

| 対象 | 発見・対応 | 判定 |
|---|---|---|
| crypto input ownership | headerが処理中に変更されintentと署名が不一致。再現負例→canonical snapshot→再試験 | 修正・局所検証 |
| library pin型 | bool schema/int version/候補後半の不正pathを拒否する負例→providerとprobeを厳格化 | 修正・局所検証 |
| native dependency | site-packages追加をせず絶対path/hash/versionをprobe。未知画像をloadしない | 局所検証 |
| nonce retry | crash前の予約をburn、commit後はsaved bytes。6境界SIGKILLと改変receipt/cacheを拒否 | 局所検証 |
| old library | point-validity修正未適用。該当関数なし、明示実験flag。patched native未取得 | 未解決・本番不可 |
| signature strictness | 既知値、S<L、低位数/改変拒否。ただし完全な独立subgroup corpusではない | OD-01未完 |
| HPKE authority | external trust contextとrootを要求。full controlログはない | 認可統合未完 |
| sealed Blob locator | typed wire hashとStore raw locatorの対応未実装 | 添付Blob統合前に対応 |
| portable runtime | Rust/Automerge/OS keystoreなし | 未実行を保持 |

H0は同一OS権限者からの完全な改竄防止装置ではない。公開keys fixture以外の秘密をログ/ZIPへ入れない。
