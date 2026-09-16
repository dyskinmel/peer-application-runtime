# 実環境での実証は最後にまとめる

Q-NET、Q-PLATFORM、Q-SECURITY、Q-SOAK、Q-RECOVERY、Q-RELEASEを最後のbatchにまとめます。
H0は外部taskを自動実行しません。次段のoperator runnerはこの承認境界を維持する必要があります。

## 前段で作るもの
各scenarioのcode、入力fixture、対象OS/依存、expected result、fault injection、秘密の注入方法、収集すべきraw evidence、失敗時のcleanupを本環境で用意します。
local simulation成功と実機成功は別evidence class。物理停電、実CGNAT、OSの休止、電池、第三者review、signed release再取得をmockで代用して合格にしません。

## local closure
`plan/tasks.json`の現版plan（00.08.00では49 task）を対象集合として固定します。local実装/検証が完了するか、本環境で不可能な項目が理由・必要環境・可逆性・未達保証付きでreviewされた時点で移行を検討します。
H0の`local_execution_closed`は未完了localがゼロという保守的な計算です。blockerの手動承認によるdefer/外部への昇格はH0では未実装であり、falseをtrueへ手編集してはいけません。
環境不足がある間も、独立したUIやrelease tooling等は先行できます。依存が高リスクなら未検証契約をfreezeしません。

## batch実行契約
candidate source/spec/lock/plan digest、各toolとtarget、operator承認、scenario identity setを固定します。
必要な外部環境を実測→read-only probe→scenario→raw evidence→cleanup→独立評価。
一つでも必須条件が未実行/失敗なら、そのprofileはcandidateのまま。途中でsource修正があれば影響する証拠を失効・再実行します。
署名key・公開・外部アカウント操作は個別承認。H0の内部receiptだけでpublicationを認可しません。
