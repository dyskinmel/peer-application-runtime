# ADR: 同期成功を作らず、実Storeの自己操作結果を画面へ接続

Status: local candidate; baseline 00.02.00不変。

入力の正本は既に所有された認可付きStore。表示に必要なmetadataと自己操作receiptだけを読み取る。署名秘密鍵や元の本文を照会入力に要求しない。従来CryptoStoreWriterのlocal receipt形式を読むが新暗号方式は作らない。

権限取消しや世代切替は、既に完了した自己のローカル操作照会を「失敗」に変えない。未来のwriteと過去の結果を分離する。文書内の意味/CRDT適用は未確認なので、cacheやopaque changeを本文へ変換しない。

ブラウザーへ渡すPinはホストの信頼境界内で発行する。JSONフラグが正しいだけでは署名の証明ではない。portは外から注入し、既存UIはobserved結果を検査して画面更新する。更新中のIME/下書きと共有保存の表示を分ける。

新たにconnection `unknown` と copies `not-observed` を追加。ネットワーク観測がないのにoffline/複製待ちと表示していた意味の過剰推定を避ける。未接続操作の理由は辞書から表示し、内部reason keyをそのまま画面へ出さない。

実Automergeの再probeは不在/registry DNS failure。自作mergeを代わりにしない。型/観測/照会を先行し、次のG0-ACTORは実ライブラリでの変更意味検査に限定する。
