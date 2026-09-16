# ADR — 00.20.00: exact signature reuse and measured bounded reads

状態: ローカル候補。一般的な状態cacheの導入は採用していない。

## 判断
全ての変更・disk mutationを完全に列挙したという仮定へ依存するstate cacheより、数学的に同じ署名入力の成功を再利用する狭い境界を先行する。署名が有効な事実と、現在許可される事実を分ける。全live checkを維持し、startupはcold、既定はfull。新CLIだけで明示opt-inし、旧protocol/hostを残す。

## 追加発見
shared readerが実ファイルより大きなlimit+1を要求し、16MiBの監査limitを小ファイルにも割り当てていた。まず12件の負例/正常系を追加し、うち5件のREDを観測。実size+1とfd/path前後照合で修正した。この修正に伴いkeeper-retentionのpinned-input、根拠を持つ知識カードを更新。元の85file規範baselineと旧測定ログは不変。
foreign-threadのobserve拒否でもexcept節がcacheをclearする問題を別のREDで検出し、所有threadだけが破棄できるよう修正。cached successから他threadが処理を認可される問題ではなかったが、所有権契約に違反していた。

## 保存される主張
default full、暗号primitive自体の置換なし、signature keyは全tuple、否定結果/秘密/認可をcacheしない。ファイルmetadataは変更検出だけ。process再起動・forkにはcacheを持ち越さない。結果比較とverifier回数・latency・traced allocationの測定は合成local workloadだけ。

## 残る負債
CBOR decode、schema/authority/control chain/ファイル全件走査は残る。policy上の依存hashは起動時に固定するが、同一OSユーザーの任意native code注入はscope外。署名済み本文そのものをcache keyとして短期間メモリーに保持するため、扱う本文が平文の場合そのメモリー保持期間は延びる（disk/exportしない）。現ホストの監査・wire bytesのみを主対象とし、秘密データにはこのAPIを使わない。

## 次
管理jobを段階化する前に管理権限・idempotency・cancel可能点を別契約へ固定。cacheを管理許可の根にしない。real-device/native qualificationを待たず独立作業を進めるが、製品gateはNOT_RUNのまま。

監視実行: 一括108試験が外側90秒の時間枠で中断したため、そのログを`interrupted-all-snapshot.log`として保存。成功扱いにせず、登録された7つの試験群を個別の期限で実行する。今版は結果の集計前に、全18レーンの正確な試験集合とsource/environmentをハーネスで再照合する。
