# 00.30 自己レビューと残る境界

独立した第三者レビュー・サブエージェントレビューは未実施。以下は同じ作成者が行った負例と自己レビュー。

## 是正
1. 00.29-resumeの期待ハッシュは一致したが、00.28の全ファイルと再開通知3件だけだった。rendererが配布されていたという過去の記述を採用せず、INPUT_0029_RESUME.jsonへ記録して再実装。
2. offline about:blankではcrypto.randomUUIDがない。操作ID生成はcrypto.getRandomValuesへ変更。fallbackの疑似乱数は使用しない。
3. dialog cancelの直後にfocusを戻すとブラウザーのclose処理に上書きされた。close eventで復帰するよう修正し、Escape後のフォーカスを実ブラウザーで検査。
4. Nodeファイル公開後の一時ファイルcleanup失敗を内部で握り潰す不備。実ファイルによる負例を追加し、成功でなくDRAFT_WRITE_UNKNOWNとして返し、保存済み内容を照合する。
5. registrationの旧版番号・入口文書の期待値を現行化。テストID集合、製品Gate、隔離の規則は緩めない。

## 証拠の区別
Nodeの永続化は実ファイルと別プロセス、3か所のSIGKILLを使用。Browserの一時host bridgeも同じNode実装へ接続するが、試験専用。Webの本物のIndexedDB/HTTP配信の検証ではない。
URLBlocklistを変更していない。rendererはoffline Chromiumで描画。デスクトップ1400×1080、mobile390×844、dark、RTL、文字拡大を検査。実OS IME・screen reader・WCAG認定・他ブラウザーは未実施。

## 未解決
前回報告の一度のアップロード応答待ち失敗は、受領ソース全26レーンでは再現しなかった。失敗時のrenderer/ログを含むソースは今回の入力にないため、原因確定・修正済みとは言わない。
Draftは私有コピーであり、共同編集commitやbackupではない。IndexedDB adapterは実装/型検査のみで、実originのtransactionイベント・quota・durability実証が必要。
鍵紛失・同origin任意コード・保存領域全体の巻戻し・物理電源断・OS keychain・PAR全体暗号監査を保証しない。

## Visual comparison
過去スクリーンショットから白系の編集欄、側方の状態一覧、広い本文、狭幅で積み重ねる構成を維持。入力を大きく保ち、見出し/本文/状態/ボタンの階層、色コントラスト、余白、mobileの横あふれ、stable textarea、確認とfocusを確認。追加した私有下書きパネルは意図した機能拡張。ピクセル一致や実製品全体の完了を主張しない。
