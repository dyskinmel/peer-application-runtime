# UIデザイン／Polishの引継ぎ

今回提供するのは見た目の完成稿ではなく、後から見た目を大きく改善してもcoreを書き直さないための契約。最終画面・ブランド・pixel-perfect実装は未作成。

## 基本の情報構造

第一階層は「作業」「共有相手」「保管と復旧」「診断」。ネットワークgraphは診断内の任意の詳細であり、通常の利用者にP2P用語を学ばせない。アプリ本来の作業は常に最初の画面で継続できる。初回から複製や暗号suiteの全設定を要求しない。

参照アプリはshared notes。利用者はofflineで最初の一文字を書ける。共有時に対象と権限を確認し、裏でcontrol/epochを整える。保存表示は利用者が必要とする時だけ詳細を開けるが、未保存・復旧危険・権限変化は隠さない。

## 6つの主要flow

1. **初回:** local準備→ノート作成→local save表示→任意の端末追加。鍵backupの説明は作業を遮らず、共有/保護の節目で促す。
2. **招待:** request生成→別経路で送付→fingerprint/role preview→authority承認→key/seed受信→参加完了。コピーリンクだけで権限が確定したように見せない。
3. **保管役追加:** 保管する対象・容量・通信・電力条件→同意→容量予約→closure転送→receipt→復元可能性検証。進捗内訳を別表示。
4. **競合/rebase:** 元の変更と現在stateを比較→変更の採用案→target revision確認→自分の新操作でapply→元draftの保存位置を表示。
5. **復旧:** 空領域選択→復旧資格→source→fetch→verify→rebuild→差分確認→activate。画面を閉じてもjournalから再開。
6. **停止/退出:** 新規受付停止と即時強制停止を分離→残る保管約束→移管試行→明示停止→不足状態を他peerへ可能なら通知。

## 表現と実装の分離

各画面はPresenterからVMを受け取り、rendererは型付きcommandを返す。重いnetwork・crypto・diffはUI threadで実行しない。native navigation、Web layout、dark theme等を変更してもcommandsとstatusの意味は同一。

focusは遷移前のoriginと戻り先を持つ。modalはescape/戻るを備えるがcommit済み操作を取消したと表示しない。screen-readerへのstatus通知はurgentな失敗以外を乱発しない。progressは取得量/検証済み量/残り未確定を区別する。drag専用操作を作らずkeyboardの同等経路を用意する。文字列伸長・RTL・IME・safe areaを最初からfixtureに含める。

## 後工程でデザイナーが受け取るもの

`stories.json`の24状態、`polish-contract.json`の不変境界、tokensの3層、spec17の文言/アクセシビリティ、spec18のcomponent anatomy。各storyを各themeで表示するgalleryを実装し、その画面をvisual reviewのsourceにする。theme seedは完成paletteではなく、変更のための意味的境界。

## Polishの終了条件

見た目の比較だけでなく、同じaction traceが同じdomain結果になること、危険操作の確認が残ること、disabled理由が読めること、200%文字拡大やkeyboardで完了できることを確認する。必要なdomain変更が見つかった場合はvisual変更と別のレビューへ分ける。WCAG2.2AAを目標とし、実UIがない段階で準拠済みと主張しない。[S16]
