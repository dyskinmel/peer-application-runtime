# 有限接続matrix — 00.55.00 candidate

`FairConnectionPool`は信頼したembeddingが明示供給したfactoryとread-only操作を使う、単一event-loop/PID/threadの診断用スケジューラー。既存product schedulerや接続APIの置換ではない。wire、認可、保存、nonce、ACK、適用形式を変更しない。

参加者を固定（最大8）、peer毎FIFOとpeer間round-robin、global枠（最大8）と待ち行列（最大64）、peer毎待ち（最大8）、pool生涯4096submissionを制限。IDは生涯再使用不可。factory中とclose中も同じslotを占有。status/cancelはqueueへ投入せず同期実行し、取消しの到着を遅いpeerの終了待ちにしない。

取消し/期限前に開始していなければfactoryを呼ばない。開始後は取消しをEvent通知し、caller結果と資源回収を分離。遅いfactory/operation/closeを繰り返しTask.cancelしない。失敗したcloseの参照を保持して新admissionを拒否する。全slotを非協力providerが保持したとき進捗を保証しない。同期処理をpreemptせず同一UIDの悪意をsandbox化しない。

`check_factory`は明示された使い捨て接続factoryに対する限定的な生成・二重所有拒否・再生成・close・事前取消しの契約検査。missingはBLOCKED/0、暗黙fallbackなし。限定PASSを認証/暗号/OS保護の認定へ昇格しない。遅い生成/生成失敗/close失敗の注入はpoolの別unit/control検査として記録する。

実matrixはPython driver+2/8個の独立owner process/Store namespace。参加者数と同時枠を別々に記録。AF_UNIX private fdと既存所有者protocolを使用し、試験clientはPython。Node/browser/TLS/公開P2P topology/実Automergeは本matrixの証拠でない。
各batchの完了、子process終了、保存状態のdigest不変を確認する。RSSは診断値、資源成長は検出可能性をtest controlで確認する。7日/24h/G8は未認定のまま。

公式API参照（2026-09-09参照）: Python3.13 asyncio-task.html のwait/shield/cancellation、asyncio-sync.htmlのEvent。asyncio.waitは期限でpendingをcancelしないため、workerの参照と終了確認を所有側で維持する。
https://docs.python.org/3.13/library/asyncio-task.html
https://docs.python.org/3.13/library/asyncio-sync.html
