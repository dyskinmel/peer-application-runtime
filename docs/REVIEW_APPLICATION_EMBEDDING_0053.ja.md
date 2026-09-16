# 独立レビュー依頼 — 00.53.00

Status: NOT_RUN。これは実施済みレビューではありません。
基準は00.52 `66e80e30341ecaef216abd3b06cc3725b11851c2`、対象HEADはrelease/STATUS.json参照。

主対象: product/wp11/src/application-embedding.ts、application-controls.ts、renderer.ts、owner-data.tsと新テスト。
確認する境界: 元ID保存前のprepare禁止、dispatch marker後のdetach/再起動で再送しないこと、完全scope/authority/世代と新streamの区別、単一view/port所有権、同期store直後取消しとpending ownership、close期限/失敗を成功にしないこと、再attach後のdestroy、レビューcheckとcurrent snapshot、draft/IMEの維持。

合成core/DOM doubleを本物のCRDTやbrowserへ昇格しない。既存owner/Store/nonce認可を変更していないことをdiffで確認。局所化したstrict data-copyがgetter/prototype/cycle予算を維持することも確認してください。

再現:
```
python3 tools/check_application_embedding.py
python3 tools/check_application_owner.py
python3 examples/application_embedding_demo.py
```

返却: 固定HEAD/tree、実行コマンド・exit/log、Critical/Importantの最小再現器、未検証領域を分けた判定。自己レビュー/targeted controlsは独立レビューではありません。
