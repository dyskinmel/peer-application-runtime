# 00.51: 適用意図の外部チェックポイント境界

## 範囲
`PinStore` はtrusted ownerが選ぶ一つのbinding専用のload/advance portです。loadはmissing/corruptを初期値へ変換せず、advance(expected,value)はdurable compare-and-swapです。戻り値や型はproviderの独立した信頼性証明ではありません。
`LocalPinStore` は標準ライブラリ/POSIXで動作するローカルアダプターです。**OS安全領域、暗号化、hardware monotonic counter、同一UIDの敵対コードや全volume rollbackへの防御ではありません。** journalとは別のowner管理0700 directoryに0600 filesを置きます。同じfilesystem全体を巻き戻せば両方失われる限界があります。

## 永続境界
一つのPID/threadがexclusive flockを保持します。明示createとopenを分離し、missing storeをopenで初期化しません。current pinとexpectedの一致、同じmetadata、sequence非減少、同じsequenceで同じdigestを要求します。変更はpending fileをfsyncしてatomic replace、directory fsyncの後だけ成功です。部分pendingは保持し、openをPIN_STORE_UNCERTAINで拒否。暗黙の切詰め/削除/再初期化はありません。
同じpinの確認はdisk writeを増やしません。開いた後のpath/lease/permission変更、既知pinの消失/書換えは拒否します。

`IntentJournal.open_anchored` は外部pinを基準に既存のjournal全chainを検証/再同期します。journalがそのpinより先へ進んでいれば、実bytesの検証後に外部pinを進めてからhandleを返します。journalがpinより短い/別digestなら停止します。未知のtailやpinも含む巻戻しの万能検出ではありません。

各appendはjournalのfile+directory同期→外部pinのCASとreadback→呼出元への復帰の順です。DISPATCHの外部pin保存が失敗/不明ならhandleをpoisonし、既存DocumentApplier/nonceへ進みません。外部pin更新後の応答喪失も停止して明示reopenし、DISPATCHは元ID照会だけで回復します。PREPAREDの明示abandonとOBSERVEDの現在ledger再照会後retireは従来契約のままです。
`AnchoredApplication` はanchorなしのjournalを拒否するPython capabilityです。旧`DurableApplication`は0050互換として残し、既存0049 wireとUIにapplyは追加しません。同一processの別APIによる迂回をsandbox化するものではありません。

## 検証の分類
- PinStore/JournalとSQLiteは実物。相互ロック、同期失敗、pin mismatch、応答喪失、6地点の子process SIGKILLを検証します。
- 正常applyは既存の明示合成materializerを使うtransaction契約検査。実Automergeの成功、public transport、物理電源断とは呼びません。
- 外部pinのOS安全保管、既存ownerへのversioned操作接続、Node/UI、PKI、独立reviewは後続です。

## 実装環境
Python >=3.11、POSIX、既存SQLite/libsodium。追加runtime dependencyなし。デモ: `python3 examples/anchored_application_demo.py`。
