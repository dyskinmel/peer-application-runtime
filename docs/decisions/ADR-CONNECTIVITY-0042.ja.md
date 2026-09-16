# ADR-CONNECTIVITY-0042 — owner-injected local connectivity boundary
状態: ユーザー承認済み次工程に対する実装候補。独立レビュー未実施。

00.41のEvent Clientをこれ以上拡張せずWP09へ移る。基準仕様を変更せず、pure policy/controllerとnative Python adapterを独立実装する。
比較: 既存private IPCを外部公開する案は認証/egress境界がないため採用しない。libp2p全体を未コンパイルで一括移植する案は修正面積が大きいため後続へ回す。
採用: typed owner grant→bounded resolver→数値target→dial→peer/Space認証port。実行不能なQUIC/Noise/relay/WSSは未実装のまま明記し、安全な失敗を返す。
L-WP06はKeeperの既存private host/session実装を持ち、L-WP08の境界検査はwire/Store/認可checkerに存在するが、full L-WP06/08の認定ではない。
本policy sliceはそれらのauthorityやstorageへ依存しないため、V-WP09でH0依存のpartial検証を登録する。元L-WP09とV-WP09 full_scope依存・Rust/Cargo要件は保持する。
詳細契約: product/wp09/CONNECTIVITY.ja.md。現状のレビュー権限はlocal self-reviewで、独立認定や製品仕様凍結ではない。
