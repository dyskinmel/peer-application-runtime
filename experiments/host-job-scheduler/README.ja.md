# HOST-JOB-SCHEDULER-LOCAL / 00.22.00

実際の私有Unixソケットの接続とKeeper reader pinを数え、管理ジョブの開始前に新規受付を止める所有プロセス内の候補実装。管理socketを公開しない。Linux/Python 3.13.5で局所検証した範囲であり、製品・実機・public networkの認定ではない。

## 入口と所有権
`par_job_scheduler.ScheduledHost(keeper, gateway, read_path, upload_path, jobs_root)` が既存の取得server、世代付きupload server、ManagementJobsを所有する。Keeper/ReplaySpoolは借用でcloseしない。PID/threadを固定し、fork後/別thread/再入を拒否する。所有インスタンスは1つ。内部objectへ直接変更を加えられる敵対コードを防ぐsandboxではない。

`submit`は署名済み入力をjob journalへ登録するだけ。既存ジョブは自動選択しない。`schedule(job_id)`で最大1件を選ぶ。`tick(timeout)`は双方のデータserverを交互の順でpollし、管理処理を最大1段階進める。`cancel`はEXECUTING前だけ。`reconcile`は結果を読み照合し、`arm_retry`はRETRY_READYに対する明示的な選択。自動reconcile/retryなし。

## 実測する活動
connection辞書とselector登録のFD集合・object・phase・eventを照合する。hello送信中、要求未完、response送信中を全て数える。片方のendpointがidleでも他方を無視しない。Keeperの実reader pinsは別に数え、socketがなくても処理中のpinがあればeffectを待つ。固定値0を返すcallbackは使用しない。

新規受付pauseはlistenerのselector登録を外す処理。既存connectionはpollし続け、送信完了/切断/期限到達でpinを解放する。OSのlisten backlogへ接続だけが入ることはあるが、pause中はacceptせず要求本文を処理しない。resume後にfresh helloで最新の既知世代を提示する。`connect()`成功だけではアプリへの受理とは言えない。

## 実行と安全な停止
選択時に両listenerをpauseし、monotonic clockによるdrain期限を固定する。前段の入力検査は進められるが、PREPARED/RETRY_READYからeffectへ入るのはconnections=0かつreader_pins=0のときのみ。完全監査・現在の認可とwindow観測を維持し、effectの前には署名検証キャッシュを無効化する。

期限切れはDRAIN_TIMEOUTとして受付停止を維持し、接続を強制終了せず、effectを実行しない。cancel可能なjobは明示cancelできる。途中不明はREVIEW_REQUIREDで停止し、結果照合を待つ。起動時にOUTCOME_UNKNOWN/RETRY_READYがあれば最初からpause。QUEUED/PREPAREDだけなら通常受付可能だが、そのjobを勝手に選択しない。

署名や状態検証が失敗した場合も新規受付を止める。根拠が変わった状態で自動再開しない。同期DB/暗号/effect内部の処理はpreemptできず、effect中に外部threadからpoll/cancelするAPIではない。drain期限は同期処理の終了時刻保証ではない。SIGTERMも同期呼び出しの復帰を待つ。

## ホストCLI
`python3 tools/keeper_scheduled_host.py --help`
既存の私有config、Keeper DB、schema3 spool、read/upload socket、鍵FDに加え`--jobs`を指定する。既定full verification。signaturesは明示opt-inで、起動の完全検証を省かない。
`--run-job ID` / `--reconcile-job ID` / `--retry-job ID` は排他。事前登録したjobを所有者が明示指定するための入口で、任意の新規管理要求をnetworkから受け取らない。無指定で全jobを走らせる動作はない。実行中の新規選択はowner APIから可能だが、外部クライアントからの制御IPCは未実装。

## 上限・表示
接続上限はendpoint毎に既定8・最大32（既定で両方合計16）。socket期限は既定5秒。要求64KiB/応答1MiB/chunk32KiBの旧wireは不変。drain既定10秒、設定0.05〜300秒。tick waitは0〜1秒。job数/履歴/監査上限は既存ManagementJobsを維持する。
`diagnostics`はSERVING/DRAINING/REVIEW_REQUIRED、実接続数、pins、待機理由、観測した最終段階時間を返す。UI Presenterはmessage keyを返し、推測の進捗率・強制取消し可能という表示をしない。実UIの描画試験は未実施。

## 検証と限界
63テスト（契約18、転送14、ライフサイクル14、再起動12、別host5）。7ケースの実SIGKILL、fork所有拒否、提供元なしの別受信者process復旧を含む。各probeは公開・合成鍵と一時dirで実行。物理電源断/媒体故障/第三者監査ではない。管理journalとtargetをまたぐ原子性を称さず、復旧はreadonly/inner_validated=false/applied=falseを維持する。

一次資料: Python 3.13 [selectors](https://docs.python.org/3.13/library/selectors.html)、[socket](https://docs.python.org/3.13/library/socket.html)（2026-09-06確認）。本実装の正しさは資料だけでなく同梱試験で判断する。
