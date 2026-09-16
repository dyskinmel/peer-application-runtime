# G0-WIRE-LOCALの別登録（00.04.00）

登録変更は実装sessionの外で行い、case集合/スクリプト/必要toolを固定してからfresh sessionを開始する。
同一作者によるself-reviewであり、独立reviewではない。

## 変更
- Python check 192 cases、Node比較check 70 casesを別登録（合計262）。
- H0 inventoryは98 casesへ更新。通常のharness runnerは製品REDをbootstrapへ混入しない。
- 元G0-WIREの完了条件は変更せず、部分成果を新しいG0-WIRE-LOCALへ分離。
- full G0-WIREはlocal subtaskを依存とし、予定Rust codec比較にはrustc/cargoを要求する。
- G0-STORE/CRYPTOは独立したまま。全44task/149要件の責任範囲は維持。
- 全G0〜G11はgate評価NOT_RUN、独立reviewNOT_RUN、runtimeNOT_STARTED。

## 評価上の注意
LOCALチェックの完了は親OD-02解決ではない。認証順序の全状態試験、native比較、
独立CDDL checker、crypto compositionが残る。本文と型の相違はADR-WIRE-0001/0002へ記録。
完全な型/署名/復旧を実装せず、ID一覧をPASSで埋めるcheckは登録していない。

## 今回のsource上の完了判定
H0-SELFTEST → G0-WIRE-LOCAL → verify → checkpoint → resumeを、
final candidateとclean copyの両方で再実行する。final ZIPの展開後も同じ手順を実行する。
raw result/nonce/log/source/tool identitiesはrelease/evidenceへ保全し、active .harnessは配布しない。
