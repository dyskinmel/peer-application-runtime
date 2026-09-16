# コマンド

基本形: `python3 tools/harness.py [--root PATH] COMMAND`。--rootはCOMMANDより前です。

| command | 操作 |
|---|---|
| doctor | ローカルtoolのpath/version/hash、OS/architecture/Python/SQLiteを測定し`.harness/environment.json`へ保存 |
| validate | baseline exact file setと全要件対応を照合 |
| next / status | 現sourceで有効なrunを再検証し、ready/blocked/externalを分ける |
| context TASK --text | taskに必要な小contextを出力。--max-bytesで上限指定 |
| begin TASK | 新しい作業sessionを固定。外部taskは実行不可 |
| run SESSION | 登録済みcheckのみ同期実行。空登録は拒否 |
| verify RUN | ログやstatus文言に依存せず、証拠を再検証 |
| loop SESSION | 次の推奨操作を返す。自動実装や裏での継続はしない |
| checkpoint SESSION --next TEXT | 完了していなくてもWIPのsource・guard・環境・run・次の一手をbind |
| resume CHECKPOINT | snapshotとsessionを照合。異なる場合はBLOCKED |
| recover-lock --expected-token TOKEN | lock owner PIDが存在しない場合だけ、観測済みtokenを照合してlockを除去 |

終了code: 0=操作成功、1=run失敗/証拠不適合/resume停止、2=契約・環境・権限の拒否、130=割込み。
JSON stdoutはmachine interface、テストstdout/stderrはrun単位のfileです。

`python3 tools/test_runner.py` は、この公開Alphaに同梱された自己完結型のunittestとwire smokeを直接実行します。内部のplan・knowledge・evidence・handoff資料を必要とする過去の開発テストは公開スイートに含めません。この直接呼び出しはfresh task receiptを生成せず、task完了の代用にはなりません。
`python3 tools/verify_package.py` は配布manifestを検査します。sourceを編集すると配布manifestは一致しなくなりますが、元specの検査は継続できます。

## 00.06.00 / crypto
```sh
python3 tools/check_crypto.py
python3 examples/crypto_workflow.py --include-wire --include-store
python3 examples/crypto_demo.py
python3 tools/harness.py context SPACE-AUTH-LOCAL --text
```
暗号依存はOS libraryの明示pin。ハーネスはcrypto taskに必要なnative実体をworkspaceごとにprobeする。
過去のreceiptは別source/pin/envに流用しない。デモは使い捨て鍵・合成データのみ。

## パッケージ検証の出力先
ZIPとパッケージコマンドの標準出力はソースrootの外へ置く。
```sh
python3 tools/package_release.py --output ../peer-application-runtime-devkit-00.06.00.zip > ../package-report.json
python3 tools/verify_package.py
```
標準出力をsource配下のreport.jsonへredirectすると、manifest生成時に空だったファイルが後から変わり、整合性が壊れる。release evidenceもpayloadなので、配布に入れる最終記録を書き終えてからpackageを作る。ZIP展開後の実行結果はroot外のsidecarへ保存する。これは実行コードの正しさではなく、配布内容の凍結順序に関する条件である。
