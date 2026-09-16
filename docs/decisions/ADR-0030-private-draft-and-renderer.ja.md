# ADR-0030: 画面を再構築し、私有下書きを共有保存から分離する

状態: local candidate / 独立レビュー未実施。

00.29-resumeは通知3件を除き00.28と完全一致し、報告されたrendererは含まれなかった。コードを復元できたとは主張せず、既存のpure Presenterから再実装した。過去のブラウザー49検査は今回の証拠に使わない。

Rendererはstable textareaと純粋Presenterを使い、DOM再構築でIME・selection・下書きを失わせない。確認内容と最新snapshotを操作時に再検査し、実行portがないときは無効理由を表示する。署名/暗号/CASは描画へ入れず別の私有draft portへ隔離。共有書込み・CRDTの未実装を隠さない。

私有下書きは既存PARのnonce台帳へ偽装せず、scope-boundの別形式。WebCrypto/HKDF/AES-GCMで1保存ごとの鍵を導出する。Nodeは実保存・子プロセスで検証可能。browser IDBはadapterを実装しても実origin検証を未実施のまま明記する。新たなネットワークサービス・管理socket・shell権限は追加しない。

画面の参照は前回提示されたdesktop/mobile screenshot。私有draftパネルを追加したためピクセル同一とはしない。目視確認: 見出し・sidebar/editorの配置・文字サイズ・明暗色・状態と非接続理由・狭幅のreflowを確認する。フォントファイル・遠隔画像・外部scriptは配布しない。

判明した不備: about:blankではcrypto.randomUUIDがなく、getRandomValuesからoperation IDを作るよう修正。dialog cancelのmicrotaskはnative focus restoreより先だったため、closeイベントでフォーカスを戻す。どちらもpolicy変更で回避しない。
