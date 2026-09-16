# 0055 independent review request (NOT_RUN)

基準 e6f4b98d47606cb5adbdb9269970ae15e4048048 に対する resource matrix 差分を独立に検証してください。基準の製品/認定gateを変更していないことも確認対象です。

- FairConnectionPool: peerごとのFIFO/round-robin、同時処理枠がfactory/operation/close全期間を含むこと、queued/started取消し、遅いfactory/close、同一接続の重複所有、close失敗後の資源保持。
- FactoryCheck: 明示BUSY/CANCELLED以外の失敗を合格にしないこと、peer識別/実readprobe/recreate、close失敗とtimeout後の参照保持。これはproviderのOS/暗号認証ではありません。
- MatrixCampaign: 2/8子processの終了vectorとSEAL、source/config/environment固定、bool/int混同、BEGIN中断/UNSEALED/FAILを再実行やPASSへ昇格しないこと。
- runner: 接続先は既存owner actorの独立保存namespace。生FD/予約FD/補正値・task/RSS、SQLite/Inbox/原ID/marker不変。slow peerがある時の実他peer完了とcontrol呼出しの進行。inert queue probeでsocket/factoryが実行されていないこと。

実行: `python3 tools/check_resource_matrix.py`、`python3 tools/run_resource_matrix_controls.py --output /private/path/controls`。
共有出力先の同時使用は禁止。full 30lane/実行sourceの固定/正しいPython実体はSTART_HEREを参照してください。

返却: source HEAD/tree、実コマンド/exitcode、Critical/Importantの最小再現器、未実測範囲。Python private IPCの診断を実public P2Pや7日/24時間G8合格に昇格しないでください。Node/ブラウザーを今回のmatrixで実行したとは扱いません。
