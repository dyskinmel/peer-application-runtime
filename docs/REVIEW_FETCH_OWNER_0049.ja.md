# 独立レビュー依頼: owner fetch 0049

このファイルは依頼文であり、独立レビュー済みという証拠ではありません。
基準00.46 `dce6fdb25b770f9e4c0ab1fd7980e8963ee872cb`、候補はrelease/STATUS.jsonに固定。

## 優先確認
- default-readonly grantとcaller権限の分離、scope/stream/接続世代/revisionの再検査。
- proposal TTL/current local view、root/targetに結合したcreate-only plan receipt、元SHA外部保持と全体巻戻しの限界。
- Futureとworkerの寿命、重複cancel/EOF/close、同期fsyncの後の取消し、close timeout後の所有参照。
- TSのgetter/extra/矛盾progress/旧sequence、入力不正で元SHAを変更しないこと、close中fetchのunknown状態。
- 既存rendererのdraft/IME/画面scope、destroyした借用clientの扱い。ブラウザー・native・PKIは未確認。
- applyを公開しないこと。既存揮発latch/inquireをdurable exactly-onceと扱わないこと。

## 再現
`python3 tools/check_fetch_owner.py`（79件）、`python3 examples/fetch_owner_demo.py`（3process）、主要旧checkers、必要なfull workflow。
独立したディレクトリで実行し、ソースとtoolchainを固定。元の.harnessを新環境の合格として流用しない。
返却: machine-readable result、command/exit/log/actual case identities、Critical/Importantなら再現器、未確認範囲。自己レビューを独立レビューに置換しない。
