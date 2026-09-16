# H0実行・証拠の契約

## 実行モデル
H0はローカルCLIであり、AIや人が呼び出す制御面です。モデルを自律起動するdaemonではありません。外部のGOAL機能に本kitのtask IDとstop条件を渡す運用にも対応できますが、vendor専用APIは実装していません。
一つのrootには一人のwriterを割り当てます。複数エージェントを使う場合は独立copy/worktreeとし、受理は別レビューで行います。

## 状態
PLANNED task → ACTIVE session → VERIFYING run → CANDIDATE_VERIFIED または NEEDS_WORK。
checkpointは検証の合否と独立したWIP保存です。resumeは状態照合だけで、コマンドを再実行しません。
`CANDIDATE_VERIFIED`はfresh receiptに基づくローカル候補の状態であり、独立承認ではありません。

## sourceとguard
source snapshotはファイル名・size・SHA-256の順序付き集合をハッシュします。Git未追跡fileも含み、ZIPの展開先に依存しません。
`.git/.harness/__pycache__/.venv/node_modules/target/dist`等の実行・build生成物、`release/evidence`と`release/archives`等は固定除外です。除外場所のコードをregistered checkのscriptに指定することは禁止します。
完全な入力依存追跡ではありません。チェックが除外出力を入力として読む場合、それを独立inputとしてbindする拡張が必要です。H0のcheckはその前提に依存しません。
policy、plan、harness、tools、tests、baseline、入口文書はguard。session開始後の変更は停止します。登録追加を含め、その変更は別reviewとfresh sessionが必要です。
通常のsource変更はtask.allowed_pathsとpath境界一致で検査します。この検査はファイル書換え防止ではなく、結果の受理拒否です。

## evidence
開始記録を実行前に永続化します。途中で停止してreceiptが無いrunは不完全であり、成功に数えません。
登録check集合を完全一致で確認し、各checkの期待case ID集合もmultiplicity=1で一致させます。件数だけでは比較しません。
実行はPython -I -S -B、shell=False、標準入力無効、秘密環境変数を引き継がない限定env、Python scriptに限ります。任意コマンドをCLI引数から受け取りません。
stdout/stderrは合計byte capで保存し、超過時停止。timeout・欠落result・nonce不一致・SKIP・expected failure・非zero exitをPASSにしません。
Linuxでは自己起動したprocess groupを終了時に掃除します。悪意あるdaemon化やhost停止からの完全封じ込めは保証しません。
証拠の再検証はsource、guard、task、登録check、test集合、実行環境fingerprint、ログとresultのhash、開始記録とのbindingを照合します。
JSON integrityは誤変更の検出であり署名ではありません。同一ユーザーが全fileを書換えられる状況の偽造防止を意味しません。

## budget
既定で1session最大3実行、最大7200秒、1check最大120秒、ログ合計2MiB。check固有timeoutは登録policyで設定します。H0全体の回帰テストは、現ホストでのfull suite実測（約294秒）を有限の余裕内で完走させるため420秒とします。
同じsourceで同じ失敗が2回続けばNO_PROGRESS。task単位のmax_attemptsも適用します。budget増加で失敗を消さず、原因・次の仮説を記録します。
将来の大量試験では実行単位とtimeoutをreviewして変更します。H0は無期限常駐処理を認可しません。

## 保守
全source変更で前の完了evidenceを保守的に失効させます。安全なinput-scope最適化はH1の検証課題であり、現在実装したとは扱いません。
全製品gate評価、暗号署名によるexternal evidence attestation、認証済み役割分離はH0対象外。公称production readinessは常にfalseです。

H0 test runnerはtests/直下のtest_*.pyだけを収集し、tests/product配下の新規RED testを自動収集しません。製品のTDD開始がH0 bootstrapを壊す循環を避け、製品testは別checkとして登録します。

環境identityはtaskのrequired_capabilitiesと実行Pythonに限定して記録し、scopeを明示します。doctorコマンドは全候補toolを別途測定します。無関係なNode/C compilerをPython-only checkの各再検証で起動せず、実際に使うPython executableのhashとOS/SQLite等はその都度照合します。将来のcheckがRust等を呼ぶ場合はrequired_capabilitiesへ必ず追加します。

## 00.05.00 SQLite capability
SQLiteを実際に使うtaskだけrequired_capabilitiesにsqliteを指定する。環境identityはversion文字列だけでなく
source ID、compile options、_sqlite3 extensionのSHAを含み、Linuxでは/proc/self/mapsから見える
libsqlite3のSHAも記録する。他環境で見えないdynamic libraryはEXTENSION_ONLYとして不足範囲を明示する。
posixはOSの実測で判断し、Windowsで保存実験をPASSにしない。SQLiteライブラリの識別は安全性認定ではない。

## 00.15.00 私有IPCの環境条件
KEEPER-SERVICE-LOCALだけ`unix_peercred`を要求する。Linux AF_UNIX socketpairとSO_PEERCREDの同UID照合を実測し、_socketの実装imageを記録する（拡張ならそのfile、builtinならPython実行fileのhashと区別を記録）。POSIXだけを根拠にmacOS等で合格にしない。
試験内部のKeeper/受信者processはharnessが作ったprocess groupを継承する。通常終了時はfixtureが所有PIDを停止・回収し、試験全体のtimeout時は既存harness group cleanupの対象になる。独立sessionへ逃がさない。実環境の長期daemon運用・OS sandboxの証明ではない。


## 00.67.00 Durable Checkpoint Survival

通常の開発サイクルは ZIP 生成を成功条件にしない。優先順位は source commit / checkpoint / evidence / resume metadata / remote-visible branch+tag（利用可能な場合）であり、ZIP は external handoff、offline archive、release candidate、major milestone、disaster recovery、operator明示要求に限定する。

通常の test/impact plan は checkpoint reserve のみを保護し、予算不足時は `DRAIN_AND_CHECKPOINT` とする。`package-budget` / `package` / `emergency-package` は明示的artifact操作として残り、package成功からverification PASSを推論しない。S0/S1は通常loop、S2はimpact/milestone、S3はmilestone/merge/release境界でのみ実行する。
