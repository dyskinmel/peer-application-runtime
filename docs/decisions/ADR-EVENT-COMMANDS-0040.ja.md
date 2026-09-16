# ADR — 型付きローカル発行は独立した能力とする

状態: 00.40候補。承認された `plan/NEXT_TYPED_EVENT_COMMANDS_0039.ja.md` を実装する局所設計。baselineへの規範変更ではない。

選択: 購読operation集合を増やさず、同じowner/journalへ合成するEventCommandHostと専用protocol/接続を追加する。
framingだけをtrusted wrapperの内側で共有する。JSONでprofileや付与権限を切り替えるdispatcherは設けない。

比較: 既存の購読socketへpublishを追加するとread/ACK利用者の能力が暗黙に増える。新daemonや独立DBを作ると認可・nonce・保存境界を重複実装する。独立したmailboxとfdは既存保存形式を維持し、どちらも避ける。

失敗影響: 同期保存はremote abortでpreemptできず、COMMIT後の通信損失は未保存と区別できない。クライアントは未知結果でterminalとなり、元IDを保持する。再接続・照会・再送は明示操作。ACKに転用しない。

反証: 権限自己申告/reader昇格、same-ID差替え、exact integer違反、queue超過、nonce/COMMIT kill、postcommitエラー、通知とACK混同、late-response/同期port throwをそれぞれ実検査する。プロトコル相手役を使用する単体検査と、実SQLite/別processの統合検査は区別する。

採否条件: 新旧exact case inventory、生成JS/宣言一致、fresh H0と全28lane、source/guard一致。失敗を隠すguard変更は禁止。
当面維持する欠点: local operation結果型はfull SDKのphase/retry-class体系を全実装していない。native/public adapterやUI reconnectの実装は別工程。outcome-unknown再開用の呼出側ID保持が必要。

可逆性: 保存形式は不変。新port未採用のembeddingは従来APIを継続使用できる。将来のnative adapterは同じ小さなtyped interfaceに置換可能。公開transportや鍵取り回しはこの選択から導かない。
