# Local connectivity candidate 00.42.00

承認済み `plan/NEXT_LOCAL_CONNECTIVITY_0041.ja.md` の実装境界。基準仕様13/PAR-NET-001..006は変更しない。

## 信頼境界
RouteGrantはtrusted ownerがsource + expected peer + canonical endpoint + CIDRを明示登録する。初期grant集合は空、egressはfalse。
候補中のsource文字列そのものを認証証拠にしない。ownerが信頼できる出所からCandidateを構築する責務がある。同一processの悪意コードはsandbox化しない。
接続先許可はpeer/Space認証ではない。resolver、dialer、authenticatorは別のowner-injected port。公開listener、STUN/TURN、DHT、UPnP、環境proxy、自動fallbackは追加しない。

## 宛先・DNS
明示port付き tcp/quic/wss のauthority-only候補をparseする。path/query/fragment/credentials/percent/zone/非ASCII/曖昧IPv4表記は拒否。
IPv4-mapped IPv6はIPv4へ正規化。通常IPv6はcompressed lowercase。DNSはASCII label、完全名・resolver ID・有限alias許可を固定する。
resolver返却の全addressを検査し、一つでも禁止ならその候補全体を拒否。CNAMEの未許可hop/循環/予算超過を拒否。返却を別名へ再解決せず検証済み数値IPだけをdialerへ渡す。
CIDRはgrant単位。local例外は明示allow_localとCIDR両方が必要。loopback/RFC1918/ULAは例外対象だが、link-local/metadata/multicast/unspecified/translation/特殊用途は本候補で拒否。
特殊用途prefixはIANA registry（2025-10-09更新、2026-09-08確認）を保守的に扱う。globally reachable=trueの特殊用途も本候補では拒否する。汎用の全アドレス分類器を称さない。

## 接続ライフサイクル
明示connectで与えた有限候補だけを順番に試す。grant、入力、重複、数・総文字数・解決address・試行回数・inflight・保持接続を制限する。
各callの総deadlineをresolver/dial/auth全体で共有。世代変更/close/取消しは待機へ通知し、遅い結果は新世代へ採用しない。meteredはuser/backgroundを別にowner許可。
portが取消しを無視した場合は未終了taskを追跡し、新規admission予算に含める。遅れて返った接続はcloseする。close失敗は記録して追加admissionを止める。OSや非協力コードの強制停止を保証しない。
peernameの数値IP/portをdial前のtargetと照合し、その後authenticatorが返したpeer ID/Space scopeを照合する。path表示は接続の観測だけを使い、設定だけでdirect/relayedにしない。
local-fixtureはlocal-fixtureのまま返す。実handshakeは実装せず、authenticatorの結果を暗号的に検証する責務はembeddingに残る。
保存/outbox/元operation IDを変更せず、EventCommandClient.publishを呼ばない。connectはmessage再送ではない。

## TCP adapter
NumericTcpDialerは数値IPへだけconnectしDNS/HTTP/proxy/redirectを行わない。生TCPだけで、Noise/TLS/libp2p/relayの実装ではない。
SocketConnectionは一回/合計I/O予算と片方向一件のinflightを守る。closeは所有socketを解放する。暗号やPAR認証を自作しない。
AF_INETの実dialは今回未実測。I/OはAF_UNIX socketpairで実測し、数値tupleの配線は制御されたloopで検査する。実インターネット適合とは区別する。

## 検証と登録
既存L-WP09のfull依存は変更しない。V-WP09の元依存/capabilityをfull_scope_*へ保持し、active check_scopeをこのPython local候補へ明示限定する。
67tasks/149requirements/16WP/全G0..G11のNOT_RUNを保持。新local PASSで全NET要件完了/独立review/native/public適合へ昇格しない。

## 外部参照（実装判断の根拠）
- https://www.iana.org/assignments/iana-ipv4-special-registry/
- https://www.iana.org/assignments/iana-ipv6-special-registry/
- https://docs.python.org/3/library/ipaddress.html
- https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html
- https://docs.python.org/3.13/library/asyncio-eventloop.html#asyncio.loop.sock_connect
- https://docs.python.org/3.13/library/asyncio-task.html#asyncio.timeout
Python 3.11以上/POSIXを対象とする。標準SelectorEventLoopでの数値IP fast pathを前提とし、任意の第三者event loopでDNSがないことを無条件保証しない。
Runtimeはこれらをfetchしない。source更新は新候補でテストし直す。

## 00.42 self-review修正
接続portの返却とwatcher解放の間のTask.cancelで接続所有を失う経路、close失敗時に接続参照を落とす経路、未開始I/O coroutineの未await警告、十六進IPv4風DNS表記を、それぞれREDから修正。
cleanup_completeはactive接続を含む全所有資源が解放され、失敗記録がない場合だけtrue。失敗資源は保持し、新規admissionを停止する。自動close retryは行わない。
過去H0の「現在の次工程」文字列だけをL-WP10からL-WP09へ更新（6ファイル/8assertion）。既存test identity/件数/安全条件は削除しない。H0に新しい登録検査8件を追加。AGENTSの4000byte上限は維持。
