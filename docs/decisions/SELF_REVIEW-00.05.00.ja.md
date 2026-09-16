# 00.05.00 self-review — independent review NOT_RUN

## 修正した項目（tests first）
- settings readback失敗時のSQLITE_INTERRUPTを公開エラーへ正規化。
- actor/cache行の欠落と古い値をcommit履歴から導出して検知。
- schemaのversion/profile自己申告だけに頼らず、実sqlite_schemaをbaseline+overlayと照合。
- 参照なしblockの再利用でfileと親directoryを再同期してからDB参照を公開。
- observer内で未commit状態をpublic readへ見せない。pendingをcursor/limit付きにする。
- snapshot publish後の失敗はOUTCOME_UNKNOWN。出力が存在し得るのにdefinite abortとしない。
- backup設定失敗時にも実target connectionをcloseする。
- H0でSQLite source ID/compile options/実装file hashを記録。見えていない動的依存を明示。

- 統合実行で、testsのimportlib.utilを通常起動時の副作用importへ依存していた点を検知。
  -I/-S隔離を緩めず、明示importへ修正し同条件で再実行する。

## 意図した制限
APIはtrusted local inputsを受けるcandidate。署名やenvelope内容とmetadataの暗号検証は未実装。
テスト内sealed bytesは暗号化を実証しない。raw connectionは実験で故障を注入するため公開しており製品SDKには出さない。
nonce予約を使って暗号呼出しが一度だけ行われたことをstore単体で検知できない。G0-CRYPTOが必要。
不正な同UIDコード/ファイル差替えrace/外部SQLite clientをOS隔離するものではない。
復元先で操作禁止するread_only_restoreはAPI guardであり、攻撃者がraw DBを書換えることを防がない。
構造auditは全履歴を走査するローカルoracleで、大規模環境の性能保証ではない。
SQLite3.46.1未patch、native/macOS/Windows/mobile/browser、物理電源断、Keeper補完復旧は未認定。

## 公開判定
G0-STORE-LOCALだけfresh executionで確認。G0とOD-04、製品受入試験、本番profileの合格を主張しない。
モデルによるfresh independent reviewer、暗号レビュー、外部運用者の承認は実行していない。
