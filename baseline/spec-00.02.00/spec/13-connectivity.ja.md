# 13 — 発見・NAT・Relay・接続ポリシー

版 **00.02.00** / 2026-09-05 / **規範候補・未凍結**

正本の位置付けと優先規則は [仕様案内](../START_HERE.ja.md)。本書の規範要件は `catalog/requirements.json`、受け入れ契約は `catalog/acceptance-tests.json` に対応する。

## 1. 接続戦略

known peer cache→明示招待のroute→許可されたLAN discovery→指定Discovery Helper→指定Relayの順で候補を作る。優先順位は利用者policyで変更可能。routeは候補でありtrustではない。接続後にpeer identityとSpace資格を検証する。

libp2pはhole punching、AutoNAT、Relay等を提供するが、任意のCGNAT/firewallを必ず通過するわけではない。[S02] 経路がなければlocal-onlyとして継続し、relay追加・LAN・後で再接続の具体的選択肢を示す。

## 2. nativeとbrowser

nativeはQUICとTCP/Noise/Yamux、Relay v2。browserはJS transport adapterのWebRTCまたは明示WSS経路。nativeのUDP APIがWASM browserで使えると仮定しない。browser-to-browser WebRTCもsignaling/relay等の経路条件を検証する。[S25]

optional external-assistedではSTUN/TURN/relay/notificationのendpoint・管理主体・帯域負担をmanifestへ記録する。初期listは空。TLS certificateの取得・更新やDNSも、利用構成ごとの運用依存として公開する。

## 3. discovery privacy

LAN discoveryはSpace名、文書名、account IDのbroadcastをしない。アプリ用service typeと短寿命接続nonce程度に抑える。ただしアプリ利用やIPの露出は残る。LAN permission拒否でも手動招待を使える。

global DHTへprivate Space membershipを広告しない。将来public feedを載せる場合もpublic namespaceとprivate namespaceを分離する。

## 4. relay admissionの難所

relayのreservation時点ではPARのend-to-end Space streamはまだできていない。したがってアプリ層で後から認証するだけでopen relay防止が済むとは扱わない。

参加者Relayはlibp2p relay reservationのconnection gaterに、owner認可のtransport peer ID＋resource grantを事前登録する。内側PAR認証でさらにDeviceId/Spaceを確認する。capability bootstrapは既存の認可経路または署名済み手動enrollmentで行う。callerが任意宛先へproxyできる機能は作らない。

## 5. route validation

peerが広告した宛先へ無条件dialすると、第三者hostやローカル管理APIへのアクセスを誘導され得る。scheme/port/length/宛先範囲を検証し、loopback/link-local/metadata endpoint等は明示LAN・local設定以外で拒否。DNS利用は解決後addressにもpolicyを適用し、redirectや多段解決で迂回させない。

UPnPやルータ設定変更は明示許可なしに行わない。接続診断のactive probeも利用者の承認した相手・範囲だけへ送る。

## 6. ネットワーク切替

Wi-Fi→cellular、IPv4/IPv6、sleep/wake、VPN変更はroute再評価を行う。socket維持を前提とせず、durable outboxから再接続できる。meteredへの切替時は利用者編集の送信と他人のblob/relay負担を分けて制御する。

exponential backoffは初期1秒、上限60秒、±20% jitterを候補とし、明示ユーザー操作はbudget内で前倒し可能。no routeを短周期で無限再試行しない。

## 7. 検証matrix

LAN、同一router、異なるNAT、CGNAT模擬、UDP blocked、TCP only、IPv6 only、dual stack、explicit relay、relayなし、DNS不達、route切替。各結果をdirect/relayed/unreachableで公開し、NATの名前から到達性を推測しない。emulator/network namespaceと実ネットワークは別evidence。

## 規範要件と受け入れ契約

以下のMUSTは本候補仕様内の必須契約。採用候補であり、実装済み・検証済みという意味ではない。詳細な手順・前提は本書本文と対応する試験契約を併読する。

<a id="PAR-NET-001"></a>
### PAR-NET-001 — 明示経路
**MUST:** 接続候補は設定された参加者・許可されたdiscoveryから生成し、無断の公開サービスへfallbackしない。
受け入れ: `AT-NET-001` / 最初の必須gate: `G5`。

<a id="PAR-NET-002"></a>
### PAR-NET-002 — 到達性観測
**MUST:** direct/relayed/unreachableを実際の経路に基づき報告する。
受け入れ: `AT-NET-002` / 最初の必須gate: `G5`。

<a id="PAR-NET-003"></a>
### PAR-NET-003 — relay入口認可
**MUST:** Relay reservation段階でtransport peerとresource grantを制限し、内側Space認可も行う。
受け入れ: `AT-NET-003` / 最初の必須gate: `G4`。

<a id="PAR-NET-004"></a>
### PAR-NET-004 — dial宛先防御
**MUST:** 広告されたrouteにscheme/address範囲policyを適用し、任意proxyやSSRF相当の経路を開かない。
受け入れ: `AT-NET-004` / 最初の必須gate: `G4`。

<a id="PAR-NET-005"></a>
### PAR-NET-005 — 回線切替
**MUST:** ネットワーク変更とmetered制約で接続を再評価し、durable outboxを保つ。
受け入れ: `AT-NET-005` / 最初の必須gate: `G6`。

<a id="PAR-NET-006"></a>
### PAR-NET-006 — 発見の最小化
**MUST:** private Space名・membership・文書名をLAN/global discoveryへ公開しない。
受け入れ: `AT-NET-006` / 最初の必須gate: `G5`。
