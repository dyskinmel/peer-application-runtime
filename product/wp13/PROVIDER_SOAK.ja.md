# ローカルprovider反復検証 00.54.00

## 範囲
Linux/Python 3.11以上/Nodeの既存ownerとembeddingを再利用する診断用実装です。1segment内で同じNode/Python processを維持し、140round（各20回）を既定とします。100回以上を実時間で実行する小規模反復であり、7日Keeper/24時間mobile、100,000 records、実通信・実機性能の認定ではありません。元G8条件は不変です。

## 操作と所有
seed付きの均等順序でobserve、元IDinquire、権限拒否、取消し、期限、close失敗、切断を実行します。初期fixtureだけが既存の合成SQLite/Inbox/journal/anchorとcaller original/markerを作成します。測定中はREAD_ONLY、core=Noneで、prepare/dispatch/ACK/slot削除をしません。各roundでSQLite論理dumpとInboxのhash、journal pin、nonce/ledger件数、caller全ファイルを検査します。

private socketpairを事前生成し双方へ渡すため、新しいlistener/公開endpointはありません。未使用FD集合を別計数し、raw FDからその数だけを控除します。予約FDが消失した場合は検査失敗で、任意のFDを控除してリークを隠しません。参加者数2、同時channel1、round最大256であり、同時256接続の試験ではありません。

7回のwarmup後をsegment基準として、毎回のfd/task/owner channel/inflight/pending/Node active resource種別/RSS/heap/external/解放時間を記録します。Python taskにはactorのmainも含みます。Node active resourcesはevent loopを保つ種別であり、全Promise/objectの列挙ではありません。FD/task/active resource増分、未完了処理、64MiB RSS増分、2秒の解放診断予算超過はFAILです。後二者はこの有限プロファイルの診断値で、製品SLOや厳密RAM保証ではありません。

CPU/model/core/affinity、host-visible RAM、kernel、Python/Node/native library情報、source hashと実行binaryを記録します。これはcontainer quota/hardware認定や完全な依存attestationではありません。RSSはallocator/JIT/GC/共有page等の影響を受けるので、増分だけでリーク不存在/存在を断定しません。

## Faultの意味
取消し・切断はownerが待機処理へ入ったbarrier後に発火します。期限はクライアントの実deadline callbackを、そのbarrier後に試験側から呼びます。製品上限を変更せず、実時間で指定期限を待った証明とは分けます。close-failureは実channelを閉じた後にprovider errorを返し、CLEANUP_UNCONFIRMEDと再attach拒否を確認します。応答喪失・native非協力コードの強制sandboxではありません。

## 再開記録
`Campaign`は私有directory・flock・canonical hash chain・file/directory fsyncを使い、source/config/選択したtoolchain属性に固定します。BEGIN/RESULT/SEAL/ABORTを上書きせず保存します。

- 最初のFAILはterminalで、同じcampaignの後続roundや成功するまでの再試行は禁止。
- BEGIN中の停止はINTERRUPTED。結果のみ残り子process終了未確認ならUNSEALED。どちらも自動再実行しない。
- round境界で明示stopし、双方exit0と後始末を確認してSEALしたPARTIALだけ、次のidentityから明示resumeできる。
- 全roundが成功でも終了確認前はPASSにしない。子の異常終了/warmup失敗もABORTとして保持する。
- source/config/toolchain変更、既知pinより短い履歴、破損や途中fileは拒否。外部summaryを書換えても判定に使わない。

各segmentには別PID/基準を持たせ、分割140回を同一process連続140回と呼びません。同じUIDの悪意や全履歴・外部pinの同時巻戻し、証拠の署名認証は保証しません。

## Provider共通契約
Python `pin_conformance(create,reopen,initial,advanced)` は既存PinStoreに対してCAS/再open/後退拒否/同sequence差替え/冪等を検査します。Node `callerConformance(factory,original)` はsave/readback/reopen/原意図競合/marker/二度目dispatch拒否を検査します。使い捨てnamespaceだけを渡してください。既存ユーザーslotへ実行する道具ではありません。

missing providerはBLOCKEDで検査0。memory/平文への暗黙fallback無し。offline例外を期待した拒否と誤認しません。これらは有限contract suiteでありOS保護/任意providerの安全性証明ではありません。connection factoryは実ownerと既存embeddingを使う同一process driverに接続し、caller/pinのような任意factory向けstandalone適合APIは今回の範囲外です。

## 実行
```
python3 tools/check_provider_soak.py
python3 tools/run_provider_soak.py --output /private/new-soak --rounds 140 --seed 5400
# 合意したround境界でのみstop/resume。再開は同じsource/Python実体で。
python3 tools/run_provider_soak.py --output /private/segmented --rounds 140 --seed 5401 --stop-after 70
python3 tools/run_provider_soak.py --output /private/segmented --rounds 140 --seed 5401 --resume
```
exit0=PASS、2=sealed PARTIAL、1=FAIL/INTERRUPTED/UNSEALED、78=missing capabilityです。通常のcorrupt/binding errorはtracebackと非0で停止し、結果file不在をPASSにしません。campaignはdiagnostic出力であり製品の自動retryではありません。
