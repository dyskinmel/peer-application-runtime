# ADR 0044 — 実在00.42基準からのTLS付き読取接続候補

状態: ローカル候補。Owner承認済みの通信暗号化・相手認証と読み取り経路の実装範囲。基準仕様や本番プロトコルの変更ではない。

00.43の配布ファイル/HEAD/検証結果は現在取得できない。過去回答を実装証拠とせず、00.42 `ee1613d0914fe101f1a6f732387afb8a7418bec5`から新規に実装する。復元したとの主張はしない。

## 選択
TLSを自作せずPython ssl/OpenSSLとasyncioのTLS driverを使用。接続済みsocketの所有を受け取り、TLS 1.3のみ、相互CERT_REQUIRED、明示CA、clientのDNS名確認、固定ALPNと双方のDER証明書SHA-256 pinを要求する。system CAや環境SSLKEYLOGFILEを採用しない。製品PKI/自動鍵発行/公開listener/DNS探索を実装しない。

X.509鍵の所持確認はTLSで実施する。X.509証明書とPAR Device certificateの対応は別のtrusted owner enrollmentを入力にする。このenrollmentの安全な配布/rotation、CA失効管理は未実装。署名済み要求のDevice certificateがTLSのenrollmentと同一であること、現在の会員read権限、完全scope、network generationを毎要求/送信chunkで確認する。TLSだけでSpace参加権限は発生しない。

既存`product/wp04/exchange.py`のEd25519 hello/request/responseとSourceを再使用する。既存wire profile/上限/認可を変更せず一接続一要求、have/need/getのみ。取得は暗号化pending bytesであり、受信Storeへ自動取り込み/CRDT適用/ACK/書込はしない。証明書本文・秘密鍵・payloadをログに出さない。バージョン/cipher名/有限の検証結果は測定ログに記録する。

## 制限
Python >=3.11/POSIX、明示有限deadline、frame長/件数/plaintext予算、同時read/write制限。asyncioのbuffer limitはflow-control目標でありnative TLS内部も含めた厳密なRSS上限ではない。CPU/同期DB/同一process悪意コードのpreemption/sandboxではない。
期限/取消し/途中EOF/失効/別scope/旧世代/署名不正は成功にも不存在にも変換しない。送信済みbytesを取り戻せない。再接続は新しいinstanceを明示生成し、自動再送しない。

試験は一時的な合成CA/証明書、AF_UNIX socketpair、別process、実SQLiteを使用する。実IP dial/インターネット/NAT/libp2p/QUIC/Noise/Relay/ブラウザー/nativeの合格ではない。恒久鍵/ユーザー鍵は使用しない。全G0–G11/独立監査は未認定。

## 参照（2026-09-08確認）
- Python 3.13 ssl: https://docs.python.org/3.13/library/ssl.html （CERT_REQUIRED、check_hostname、TLSVersion、SSLKEYLOGFILE）
- OpenSSL verification: https://docs.openssl.org/3.5/man3/SSL_get_verify_result/ （検証結果と証明書存在は別）
- TLS 1.3: https://www.rfc-editor.org/rfc/rfc8446.html （標準のTLS使用、独自handshakeではない）
