# 独立レビュー依頼 — 00.52 anchor付きowner

現状: NOT_RUN。自己検査/targeted mutationは独立レビューの代替ではありません。
基準: 00.51 `69d5cdacba18d6ebe2bbf48d1cbe220291053910`。候補commit/source digestは配布`release/STATUS.json`で固定。
対象: `par_application_owner`、`application-owner.ts`、`application-channel.mjs`、`caller-intent.mjs`、専用testsとchecker。
確認: 既定read-onlyと二重opt-in、full context/元ID/期待revision/intent binding、await中の入力差替え、取消し/close/reattach、caller原意図保存前の送信、dispatch marker同期前の送信、部分保存/結果不明の扱い、異なるreceiptへの降格禁止、同じIDの再dispatch拒否、世代変更、予算。
実Nodeと別Python/SQLiteのprepare/dispatch/COMMIT/retire後SIGKILLを再実行。実core/本番保管/ブラウザーは未認定。肯定coreのfixtureは合成です。
返却: commitに結び付いた判定JSON、実コマンドとexit/log、Critical/Importantの最小再現器、未実行範囲。mainのmerge、所有者の受入認定、製品G0–G11昇格は行わない。
