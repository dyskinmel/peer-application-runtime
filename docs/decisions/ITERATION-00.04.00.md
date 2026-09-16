# 00.04.00 実装計画とチェックポイント

## 承認された範囲
G0-WIREを中心に、この環境で実行できる通信形式の実験と品質改善を進める。
元仕様00.02.00、H0の保証境界、実環境検証を後段へ置く方針は維持する。
配布は全ソース・元仕様・再開手順・証拠・Git履歴を一つにする。

## この反復の到達点
Python標準ライブラリのstrict CBOR/26-message構造検証、別実装JavaScript codec、
正負corpus、bounded streaming、transcript構築とpagingの候補契約を実装する。
これらはネットワーク認証済みruntimeではない。G0-WIRE-LOCALという限定subtaskに分け、
第三者CDDL適合・Rust予定codec・暗号/actor/storeが未確認のままG0を合格させない。

## 手順（各段でcommitを作成）
1. C0: 00.03.00原本SHAとGit bundleを照合、doctor/H0を再実行、REDテストを先に作る。
2. C1: canonical bytes/閉じたschema/CDDL限定文法の実装。型別の境界と拒否を確認。
3. C2: JSの別codecとのbyte比較、stream切断/長さ/期限、negotiation/pagingの契約試験。
4. C3: checkとexact ID inventoryを別policy変更として登録。fresh sessionでH0とLOCAL試験、checkpoint/resume。
5. C4: doc/knowledge/未解決事項を更新し凍結。fresh copyと実ZIPから再検証し配布。

## 実装境界
`experiments/g0-wire/par_wire/`: codec、CDDL subset、schema、framing、state helpers。
`experiments/g0-wire/oracle.mjs`: shared decoderを持たないJavaScript比較経路。
`tests/product/g0-wire/`:独立したテストmoduleと正負vectors。
`docs/decisions/`:baseline不整合、暫定解釈、実験完了と未完の区別。
H0 registry/task/手順の変更は最後に別commitで行い、以前のreceiptを再利用しない。

## 制約
実測時Rust/cargo/CDDL専用検証器は未発見。NodeとPythonは利用可能。
2つの言語実装を同じ開発者が作るため、独立security review/第三者の適合証拠とは呼ばない。
依存download、model API、公開、外部listenerは今回行わない。
