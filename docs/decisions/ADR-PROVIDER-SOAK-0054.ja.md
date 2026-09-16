# ADR — source結合したローカル反復証拠

承認された0053次工程を、persistent Node/Python private fdと独立V-WP13 partial scopeで実装します。元L-WP13依存、G8、7日/24hの基準は変更しません。
読み取りだけを繰り返し、製品の署名/認可/暗号化保存/nonce/元ID/markerを変更しません。fixture gateは試験actor内に置き、本体にtest-only sleepやbackdoorを追加しません。
round結果と終了確認を別recordにし、最初の失敗や未確定を保存します。途中境界の明示再開のみ許可。暖機/segment基準/予約FDは別計数し、過去の成功だけを現在の合格へ流用しません。
RSSとactive resourceの計測限界、単一channelと限定round、任意connection factoryの適合API未提供、native/長期認定未実施を契約に明記します。
