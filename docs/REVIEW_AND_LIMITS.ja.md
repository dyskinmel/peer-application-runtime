# Review・完成度と残る制約

## 今回の範囲
H0実装、テスト、全仕様に対応するlocal-first計画、知識の最小ロード、source-bound evidence、再開、配布まで。
00.04.00ではG0-WIRE-LOCALのcodec/構造/候補helper実験を追加。crypto/Automerge、製品runtime、実機、独立レビュー、OSS remote公開は未実施。

## 完成判断
H0の最小契約は、同じ固定candidateで全registered checksが合格し、fresh copyでも再現し、中断再開と負例拒否を観測することで判定します。実測結果はrelease/STATUS.jsonへ。
独立reviewはNOT_RUNです。このsession内のself-reviewや別test processを、第三者レビューと呼びません。

## 後続で強化する項目
- whole-source失効は保守的。大きくなったときだけsoundなinput-scoped再検証へ拡張。
- target toolchainsの厳密lockと実バイナリ検証はG0で設定。H0は存在・version/hashを観測するのみ。
- production gate evaluatorと署名付きexternal attestationはG10/11へ接続する後続実装。
- 外部batchのoperator承認、local blockerのdefer/reclassificationは手続契約のみ。H0に承認を偽装するCLIはない。
- OS sandbox、network deny、secret mounting/permissionsは実行hostの責務。
- macOS/Windows/Python他version上でのH0実行、POSIX以外のprocess tree管理は未検証。
- contextのtoken数・LLMコスト削減率・モデル性能は測定していない。byte予算と必要情報の選択だけが実装済み。

## 自己レビューで修正したもの
最初の要件対応testがexternal WP IDの表記違いを検出し修正。後続の負例がJSON array結果の例外、bool schema_versionの誤受理、同一失敗loopの停止不足を検出し修正しました。元の失敗ログと再試験ログをdelivery evidenceに保存します。

- 追加skill adapterは使い方の補助です。別モデルの圧力試験・自律性の性能測定はNOT_RUN。

- 全体テスト中の時間超過を調査し、hostのambient site初期化が1childあたり約0.8秒を消費していたことを確認。標準ライブラリ限定checkに-Sを追加し、site非読込の回帰試験を追加。試験の省略や成功条件の緩和は行っていません。

- H0の入れ子試験中の全tool反復probeを、taskで使うtoolの実測scopeへ分離。doctorは全候補を測定し、executionは実際のscopeとfingerprintを保存・再照合します。無関係なtoolの省略を測定済みとは表示しません。

## 00.04.00
wire実験の262テスト（Python192/Node比較等70）、H0回帰98件を登録した。
JavaScriptは別コード経路だが同じ作者。独立CDDL validator、予定Rust codec、署名検証は未実施。
parser/semantic/helperを実装したことを、ネットワーク認証・完全同期の実装と呼ばない。
失敗したREDとself-review修正はrelease/evidence/iteration-00.04.00に保存。
H0 guardへtests/を追加し、作業途中のtest弱体化を停止するよう改善した。
