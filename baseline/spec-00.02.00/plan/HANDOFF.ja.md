# 次の実装者／AIエージェントへの引継ぎ

## いま存在するもの

仕様25分野、MUST索引、正/負試験契約、CDDL候補、API宣言、保存DDL、UI fixture/tokens、gateと作業単位、仕様支援検査器。製品のRust workspaceやアプリは存在しない。candidate source pathを実在fileと誤認しない。

## 読み込む最小context

START_HERE→spec01/02→自分のWP→そのWPのspec→関連requirement/test ID→OPEN_DECISIONSの該当項目。全履歴を毎回読まず、範囲と不変条件を先に固定する。仕様を変更する場合は理由/影響/互換/再試験をADRへ書く。

## 環境gate

OS/architecture、Rust/cargo、node/tsc、Python、C compiler、network制限、実機/エミュレータの有無をprobeして保存する。ないtoolのtestをPASSにしない。依存を取得できない場合、machine contracts/fixturesを前進させても実ビルド済みと扱わない。secretはlog・ZIPに入れない。

## 作業cycle

固定baselineのdigest→対応acceptanceを実行可能testへ変換→意図した失敗の確認→最小実装→正/負test→diffとscope review→checkpoint→関連gate再評価。既存の不確実な結果を再利用する場合はsource/spec/toolchain一致を先に確認する。

## checkpoint

checkpointはversion、source tree digest、spec digest、lock digest、WP、completed requirements、実行済み/未実行test、raw evidence参照、未解決blocker、次の一手、必要外部条件、変更可能pathを含む。生成時点のfile集合のhashを保存する。再開はdigestと前提を確認してからで、途中まで読んだ物語の続きから無条件に実行しない。

source未作成の本版はcheckpointにsource_tree=null、implementation=NOT_STARTEDを明記する。nullを0commitや仮SHAで埋めない。

## 実装前のレビュー必須項目

G0のOD-01〜04を優先。APIに残るserver-side RPC effect transaction等を具体化するときは、そのbindingが本当に原子性を提供できるかを実装probeする。protocol意味に変更があればdraft/profile digestを更新し、別実装者が旧仕様を読んで互換だと思わないようにする。

## 後工程

M1達成後はG4/G5/G6の実環境を段階的に追加。実機・外部review・soakがこの環境で実施不能でもsource/specを保存してNOT_RUN/BLOCKEDのまま引き渡す。本番qualifiedの表示だけは外部証拠なしで前倒ししない。
