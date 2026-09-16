# ADR-0015 — private process boundary before public networking

採用候補。00.14.00のKeeper/GC/repair保存形式は変更しない。Linux private UDSの別profileを追加し、既存26 messageやlibp2p authとの互換を称さない。

1. Single owner: Keeperのthread制約を維持。selector readinessで小さなread/writeを行う。slow peerの待ち時間は他peerへ波及しないが、同期storage/署名のCPU/I/Oはpreemptしない。
2. 相互pin: OS UIDだけでアプリIDを認定しない。固定Keeper public keyとconnection固有hello、subject署名request、Keeper署名responseを結合。既存capabilityはDBのcurrent authorityへ照合。
3. GET pin: socketへ最後のbyteを渡すか切断するまで既存instance pinを保持。送信前のknown authority/lease版再確認で権限変更を検出。既送信byteは回収不能。
4. Read-only scope: arbitrary dispatchなし。管理操作を同一APIへ安易に増やさない。client切断は永続operation成功とは別。最初はretry-safe readとInbox object resumeのみ。
5. Endpoint: private0700/0600・flock・同UID。stale socketはoperatorが期待inodeを明示して回復。自動rmやPIDだけの削除判断なし。
6. 子process: テストprocessはharnessのgroupを継承。fixtureが所有PIDを回収し、harness timeoutでもgroup cleanup可能。detached test daemonを作らない。
7. 完成度: authenticated private IPC request/responseは実装したが、製品のnetwork session・transport暗号・原本G0〜G11の合格とは分ける。

自己レビューで、拒否したpeer credentialがpoll全体を停止する不備と、不完全/未知statusを成功として受け取る不備を再現して修正した。_socketがbuiltinのhostでは拡張fileがないため、doctorはbuiltinを明記しPython実行imageを測定する。測定不能をPASSにしない。
