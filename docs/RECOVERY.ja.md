# 中断・再開とcheckpoint

## 通常の中断
区切りごとに`checkpoint SESSION --next "具体的な次の一手"`。sourceファイル集合、guard、環境、session、run IDを保存します。
再開は`resume CHECKPOINT`。READYでも過去コマンドを再送しません。まず次の一手とprevious_runsを確認します。
未完了の試験や失敗runがあるcheckpointも保存できますが、完了扱いになりません。

## sourceが違う場合
SOURCE_STALEなら自動上書き・merge・rebaseを行いません。Gitで該当候補へ戻すか、diffレビュー後に新sessionへ引き継ぎます。
このsnapshotはsource内容のhashであり、sourceそのもののbackupではありません。working copyとGit commit/bundleを併せて保存してください。
本ZIPの`release/archives/source.bundle`は開発中checkpointを含むGit履歴です。`git clone release/archives/source.bundle recovered-repository`で別directoryに復元できます。
配布ZIP内の元specとbaseline pinを捨てずに保管してください。

## host停止やSIGKILL
started.jsonだけのrunはINCOMPLETE。receiptの欠落から成功を推測しません。
writer.lockが残ったら内容を確認します。owner PIDが存在しないことを確認し、`recover-lock --expected-token <実際のtoken>`。
PID再利用の疑い、権限不足、owner生存なら自動解除しません。他のprojectのprocessをkillしてはいけません。
子processが残っている可能性は、operatorが当該runとのidentityを確認して処置します。H0は無関係なprocessを探索して殺しません。
環境fingerprintが違えばBLOCKED。外部OSで移行する際はfresh doctor/session/runを作ります。

## 配布時
activeな`.harness`は配布しません。`release/evidence`はこの配布を作成した際の過去証拠です。新規展開後の成功と混同しないでください。
