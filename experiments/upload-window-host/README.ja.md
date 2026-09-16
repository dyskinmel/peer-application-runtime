# 世代管理対応の私有Keeperホスト / 00.19.00

Linux private AF_UNIX candidate。正式PAR wire/libp2pではない。旧read/uploadのソース・プロファイルは変更しない。
本レーンは署名済みの受付世代を理解する専用client/serverで、ReplaySpool.executeを唯一の書き込み入口とする。

## 通信と保証範囲
- HELLOはKeeper key、store ID、window digest/sequence/phase、起動nonce、接続challenge、期限とフレーム上限を署名。
- クライアントは別途信頼したKeeper公開鍵・store ID・署名済みwindowをpinする。HELLOだけで新世代を信用しない。
- executeのbegin/chunk/progress/reserve/put/sealだけを許す。retire/rebind/open/close/compact/exportはデータsocketに存在しない。
- 要求は安定したwindow付き署名commandを、接続challengeへ追加署名。新しい接続と新しい操作を混同しない。
- 新旧profileの自動変換・downgrade・fallbackはしない。閉鎖済みwindowは記録整理後も拒否。
- 書き込み後・応答送信中もgatewayのstampを照合。権限やwindowが変われば残りの送信を中止。送信済みbytesの回収は保証しない。
- 1接続1要求、request 64 KiB、response 1 MiB、chunk 32 KiB。既定8接続/5秒、上限32接続/30秒。
- ソケットの絶対期限は同期DB・暗号処理・監査走査をプリエンプトしない。上限付きでも履歴が増えると遅くなる。
- クライアントは再試行しない。送信後の切断はOUTCOME_UNKNOWN。安定IDを保って利用側が確認・再試行する。
- upload_bundle補助APIはwindow digestを操作ID名前空間へ結合し、新世代で古いKeeper操作IDを再利用しない。

## ホスト構成（CBOR integer-key map / version 1）
0=1, 1=profile, 2=Keeper公開鍵, 3=既知Authority, 4=Keeper quota bytes,
5=max leases, 6=max operations, 7=store ID, 8=最小既知window Pin,
9=spool quota bytes, 10=max records, 11=archive total bytes, 12=max windows。
型・未知field・上限・Pinとの整合性を検証。ファイル600、親private領域700。
署名済みwindowはspoolに存在し、Keeper DB/schema3 spoolを事前初期化しておく。
ホストは新規DB/世代を自動生成せず、旧schemaを移行しない。秘密鍵は32-byte FD、argv/env/configには入れない。
ホストconfigのAuthorityは信頼済み管理者が検証したsnapshotであり、ネットワーク上の最新履歴を探索しない。

## 動作例
`python3 tools/check_window_host.py` / `python3 examples/window_host_demo.py`
`tools/keeper_window_host.py --help`、`tools/upload_window_admin.py --help`にCLI契約がある。
ライブ鍵の生成・暗号provider導入をデモに任せない。デモは公開された合成試験鍵のみ。
既存本番DBを使用しない。修正版依存関係/実機/独立レビューは未完了。

## ローカル管理経路
ホストを終了し、所有lock解放を確認してからadmin CLIを実行する。実行中ホストへの管理接続はない。
管理者が別途署名したcommand/close/openをファイルで渡す。管理者秘密鍵はCLIへ渡さない。
retire/rebindは元所有者と現在の管理権限に署名で結び付いたwrapperのみ。inspect/export/compactには余分な入力を許さない。
exportは最大16 MiBの監査データをファイルへ出力。closeはその正確な集合へ管理者が署名した承認とarchiveを検査。
compactは永続化された閉鎖承認を使い、openは次世代の署名済みgrantを要求。
結果は指定された新規privateファイルへ同期して公開。既存出力は操作前に拒否し上書きしない。
操作後の出力失敗はmay_have_executed=true。新出力先で同じ安定要求を再試行し、状態を照合する。
Pinは観測結果であり、別の信頼経路へ保存しない限りrollback耐性を生まない。

## 制約
同じ所有スレッド/協調する同一OSユーザーを前提。追加経路暗号化、ネットワーク管理、live authority同期、OS安全消去なし。
Keeper本体のcapabilityとretentionは既存契約を維持。admin中止でKeeperの保管済み本体は消さない。
監査archiveは保持し64 MiB/64window上限を維持。全件照合は性能ボトルネック候補。
旧spoolからの自動移行なし。復旧はread-onlyでinner_validated/applied/writable=false。
テストは独立第三者監査ではない。製品G0–G11はNOT_RUN。
