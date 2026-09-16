# 00.44.00 標準TLS付きread-only transport candidate

## 適用範囲
実在・SHA照合済み00.42.00 (`ee1613d0914fe101f1a6f732387afb8a7418bec5`) の上に実装。
00.43.00のファイルは取得できず、以前の完成報告や検査数を根拠にしない。`docs/recovery/INPUT_0043_NOT_LOCATED.json` を参照。
実装は `par_secure_transport/`。Python 3.11以上、TLS 1.3対応のPython ssl/OpenSSL、POSIXを対象とする。実験のPKI生成だけopenssl CLIが必要。

## 信頼と実際の暗号処理
SSLContext/asyncio/OpenSSLのTLS 1.3を使用し、独自の鍵交換・record暗号・署名方式は実装しない。
双方向CERT_REQUIRED、明示CA、strict X.509検証、SANホスト名、正確なALPN、実際の相手DER証明書のSHA-256 pinを確認する。
TLS 1.2への降格、証明書なし、異なるALPN/CA/pin/接続先名、有効期限外の証明書は拒否。
環境のSSLKEYLOGFILEやシステムroot CAは自動採用しない。TLS session ticketを発行しない。接続は使い切りでsession reuse/0-RTT/再送をしない。

TLS証明書のpinとPAR Device証明書・Space・doc・epoch・schema・head・接続世代の対応表は、**信頼したownerが事前に渡す設定**。
受信した値を自己申告のまま登録する方式ではないが、このモジュールが安全な鍵発行・初回登録・CA配布を実装したわけでもない。
失効リスト/OCSP自動取得・CAローテーション・OS鍵保管・悪意の同一プロセスコードからの隔離は未実装。
公開ネットワーク/製品の認定とは別。試験用の一時EC鍵/CA/証明書は毎回生成・削除し、配布ZIPには収録しない。

## 主なAPIと所有権
- `TLSConfig`: client/server、CA/cert/keyの明示ファイル、相手pin、clientのみserver_hostname。設定ファイルの信頼と保管はowner責務。
- `TLSStream.open(connected_socket, config, limits=..., cancel=...)`: 接続済みsocketの排他的所有権を取り、失敗・取消しでは破棄する。server側もlistenerは開かない。
- `FramedChannel`: network orderのu32長さ＋既存メッセージのbytes。型・長さを検査してから本文を有限読み取り。独自codecではない。
- `PeerBinding`: 事前登録されたTLS pin↔Device/完全scope/世代の不変対応。
- `ReadSession`: 既存 `product/wp04/exchange.py` のSourceと署名処理を再利用。1接続1要求で `request/serve` を実行し、成功/失敗どちらでもclose。
- `TLSNumericDialer` / `TLSAuthenticator`: 既存Connectorへの注入アダプター。前者は数値IPのみ、後者は実TLS情報と現在のPAR read権限を照合する。

NumericDialer自体は宛先許可の代替ではない。必ず既存ConnectorのRouteGrant/全DNS回答検査の後に使う。
実IP成功接続のテストはしていない。Connector統合テストのIP peernameは明示fixtureで、TLS handshake/証明書検証だけが実測である。

## 予算と非同期処理
デフォルトは接続開始からの絶対期限5秒、close期限0.25秒、frame最大1MiB、片方向合計4MiB、各方向frame4件、chunk64KiB。
許容設定上限は `Limits` で固定。chunkの下限4byteは長さheaderを読み書きできる条件。
handshake/DNS・numeric dial（既存Connector側）/read/write/closeの取消しと期限を区別し、進捗によって絶対期限を延長しない。
一方向の重複read/write・frame送受信を拒否する。予算はI/O前に消費する。取消し後に元の接続を再利用しない。
asyncio high-water markはflow controlであり、TLS native bufferを含むRSS上限の証明ではない。非協力的な外部コードの停止保証もない。
closeに失敗した接続をGRACEFULとしない。所有するcloseタスクを必ず回収する。

## 読み取り交換
既存の署名付きhello/request/response、会員権限、Sourceのsnapshot guardを使う。要求Device証明書はTLSに登録されたDeviceと完全一致しなければならない。
アプリ入力は最初のawait前に正規codecでコピーし、署名要求から得たargsで応答を照合する。
TLS pin/現在権限/全scope/接続世代をI/O境界で再検査し、最後のclose await後にも権限と世代を確認してから結果を返す。
`have/need/get` だけを扱い、publish/ACKは拒否。getはENCRYPTED_PENDING_BYTESであり、受信Storeへ保存もCRDT applyもしない。
通信・署名・期限・取消し失敗は不在回答ではない。正常な署名付きnull回答も現在のSourceの観測に限定される。

## 検証と再開
`python3 tools/check_secure_transport.py` で6suiteの90件を実行する。`--list` は実装から実IDを列挙。
openssl CLIがない/対応TLSがない環境は事前検査でexit78/BLOCKED、実行0。SKIPや未実行をPASSへ変換しない。
`python3 examples/secure_transport_demo.py` は2つの実SQLite、別process、socketpair、一時PKIでhave→need→getを行う。
実プロセスのSIGKILLはhandshake後とresponse前の2シナリオ。物理電源断・一般ネットワークの実測ではない。
既存169接続テスト/253Eventテスト/元仕様/operation-ID/nonce/ACK/全G0–G11の状態は維持する。
固定候補で全29local lane、配布ZIPから主要laneを再実行。範囲・結果はrelease/STATUSと各logで確認。
次は `plan/NEXT_SECURE_FETCH_0044.ja.md`。本番認定/独立レビューはNOT_RUN。
