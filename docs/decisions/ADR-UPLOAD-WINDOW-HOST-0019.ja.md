# ADR-0019: window付き私有データ経路とoffline管理を分離

Status: ローカル候補、ユーザーの実装継続方針に基づく。製品wireの凍結・第三者承認ではない。

採用: 新PROFILEを作り、Keeper/store/windowのpinを必須とする。旧署名commandはwindow wrapperの内部値としてのみ許し、raw旧commandをremote入口へ通さない。
データsocketはexecute内の6操作限定。ReplaySpool._innerをdispatcherへ渡さない。
信頼済み管理は排他的offline CLI。hostを止め、入力承認を管理者が外で署名し、archiveをファイルで渡す。

代替案: 旧upload profileへ任意管理actionを追加する案は、署名domainと許可の境界を混ぜるため不採用。
別の管理socketを直ちに作る案は、長い監査処理と状態更新の実行budgetが未整備なため次段階へ分離。

成果: signed challenge/responseを現windowへ結合、旧要求の拒否、offline retire/close/compact/open、新世代の実process upload/read recovery。
既存の取得契約と旧hostのバイト列は保持。旧hostは新schemaを理解せず、利用時に新hostを明示選択する。

追加修正: response validatorは空prefix hashと完了時hashも検査し、返却値をコピーする。内部の署名が正しくても矛盾する成功結果を通さない。
-I -Sではscript隣接pathも自動追加されないため、admin入口はローカルtools pathだけを明示する。site packagesやambient PYTHONPATHを有効化しない。

留保: data取得の信頼根はpinと現在の既知Authority。disk/kernel呼び出しをsocket期限で停止できるとはしない。
履歴全件検査の繰り返しが遅い。性能改善には単なるskipでなく検証済みsnapshotの無効化規則/破損検査との分離が必要。
