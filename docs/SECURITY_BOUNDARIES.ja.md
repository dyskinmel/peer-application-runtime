# 強制できる境界と、H0では保証しない境界

## H0が実際に拒否するもの
登録外script、shell executable、空check、case欠落/重複/置換、SKIP、timeout、巨大ログ、欠落/変更ログ、不一致nonce、古いsource/environment、guard変更、作業scope逸脱、path traversal、source/state symlink、重複JSON key、non-finite JSON。

## H0の対象外
同一OSユーザーがハーネス・policy・evidence全部を書換える攻撃、外部ネットワークへの物理的遮断、他processの秘密を読めないこと、fork/setsidによる逃走、root権限の封じ込め、独立reviewの人間identity検証。
clean environmentは環境変数漏洩を減らしますが、同じユーザーのfileやOS資格情報をsandboxするわけではありません。
レビュー名を文字列へ記入して独立性を主張することは禁止します。releaseは別権限/別環境での再実行または真正性確認が必要です。

## 運用方針
開発用copy/worktreeはproduction環境と分け、秘密をmountしません。未知のcheckは実行前にレビューし、外部通信が必要な場合もallowlist/OS sandboxを別途用意します。
H0 coreは機械的な安全網であって、悪意あるcodeを安全に実行するrunnerではありません。
インターネットを使う調査、依存導入、外部実験、公開・署名は通常checkと分離します。外部対象の承認を得ていないQ-taskを自動dispatchしません。

## policy変更
現在のsessionをcheckpoint → 独立したdiffレビュー → policy/check/case inventoryを更新 → source/guardを再固定 → 全H0負例と関連回帰を実行 → fresh session。
guard変更を許可するoverrideフラグはありません。ファイル書換え権限自体はOSに委ねています。
