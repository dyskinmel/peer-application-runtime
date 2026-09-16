# 独立レビュー依頼: 00.50 durable application intent

レビューは今回未実施です。作者による検査/targeted mutationを独立reviewと呼びません。
基準0049 c40f07272a9ebfb965c937690b673bdfba043949。差分の `product/wp09/par_application_intent/`、既存DocumentApplier/FetchApplicationControllerとの接続を確認してください。

重要点: DISPATCH永続化より前にapply/nonceへ入らないこと。DISPATCH以後の不在/例外/旧receipt/別IDから再実行が起きないこと。再起動後の既知pinと実event照合、部分eventの停止、retireの現在認可/元ledger再照合。1writer/所有権/資源上限とhost fault、権限/入力/世代変化の境界。coordinatorがprivate APIを使う結合と将来変更時の回帰リスク。

`tools/check_application_intent.py`と`examples/durable_application_demo.py`を実行し、合成positive coreと実SQLite/SIGKILLを区別してください。owner apply wireは未公開。実core/物理電源断/OS安全領域/同一UIDの悪意隔離/全体巻戻しの保証はしません。
返却: 検証したHEAD、実コマンド/終了code/件数、Critical/Importantの再現器、未検証境界、独立性宣言。実行していないPASSを記入しないでください。
