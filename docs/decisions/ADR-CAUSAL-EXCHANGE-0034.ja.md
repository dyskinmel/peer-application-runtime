# ADR — read-only causal exchange as a bounded local candidate

状態: 00.34.00候補。baseline/spec-00.02.00は変更しない。対象L-WP04/V-WP04、G0/G2の合格ではない。

実Automergeを再取得できないため、NEXT_CAUSAL_SYNC_0033の代替経路を実装。独自mergeやapplied ACKを作らず、既存暗号化受信箱へ不足分を明示的に取り込む。HAVE/NEED/GETだけを私有socketに公開し、remote mutationを増やさない。

既存Endpoint/frame/peer_uidを再利用するが、Keeperのretain capabilityやservice public-key pinを、共有文書のread権限へ流用しない。現在のmembership certificateを毎要求で検証する。

公開鍵/正確なscope/known control headは呼び出し元が信頼するpin。snapshotは局所集合と保存世代・認可revisionに結合し、変更時には再照会を要求。過去のsnapshotに基づくGETを黙って最新集合へ読み替えない。

検証で二つの応答契約不足を検出: 異なるinner IDが同じenvelopeを指すsigned HAVE、別文書を指すsigned GET。受信箱での再検査を残した上で、client返却前にも拒否するよう強化。正常署名は内容・scopeの正しさを意味しない。

同じOSユーザー内の試験・明示的な所有プロセスが境界。実際のコンテンツは暗号化されるが、ここは経路暗号化プロトコルではない。公開ネットワークへ露出しない。
