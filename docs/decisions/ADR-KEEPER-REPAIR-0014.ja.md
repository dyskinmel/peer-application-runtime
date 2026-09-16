# ADR-KEEPER-REPAIR-0014 — explicit sealed-object repair
状態: 局所実装候補。元仕様・wire freezeを変更しない。独立レビュー未実施。

採用: inventoryが示すIDは変えず、未解放sealed leaseのownerがput権限で別domainの修復要求を署名する。対象集合・世代・index・nonceを固定。要求ごとの署名intent、別staging quota、置換後の署名byte観測を使う。retention receiptを再発行しない。

比較: 通常putに暗黙上書きを追加すると初期uploadとrepairが混ざり、過去の成功応答の意味も変わる。自動修復はprovider信頼・retry・資源予算の追加設計が必要。別adapterによる明示APIを選んだ。

保護: lifetime single writer、instance pins、GCとpending jobの排他。cancelは新しいcurrent grantで開始できるが、発行済みjobの書換えはしない。repair済みbyteをcancelで破損へ戻さない。phase=doneの結果は過去の観測で現在の健康度を表さない。

レビューで検出: stage検証後のcallbackによる差替えで、間違ったbyteが一度targetへ公開される。公開直前のstage再検証を追加し、target不変の負例を保存。ただし同一OS権限の敵への完全な競合防止とは主張しない。

明示的負債: released damaged leaseを従来GCで回収できない、aborting後の再authority更新、全件監査費用、metadata cap、128対象/32MiB stage。本番256MiB file目標や元仕様の拡張範囲を縮小する決定ではない。

参考は experiments/keeper-repair/SOURCES.md。実証はSIGKILLでありpower-cutではない。
