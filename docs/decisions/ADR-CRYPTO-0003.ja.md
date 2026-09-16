# ADR-CRYPTO-0003 — 入力所有権・native実体・残るlocator境界

00.06.00 / candidate / self-review only。

## 入力snapshot
observer境界で呼び出し元がheaderのcontrol/depsを変更する負例を作ると、元の実装はHMAC intentと保存headerを食い違わせた。入口のcanonical encode/decodeでnested mutable inputを所有するよう修正。保存時とreceipt再検証時の入力を一つに固定する。一般的な任意スレッド安全性を認定するものではない。

## 環境とpin
harness.doctor.probeにはworkspace rootを明示できるようにした。sodiumを使うtaskだけ、そのrootのpolicy pinを読み、file hash一致後に隔離Python子processでversion/ctypes拡張を観測する。未要求のtaskへ依存を混入しない。default doctorは利用可否を表示する。pinの書換えはguard変更でありfresh candidateが必要。環境fingerprintはtrust anchorそのものではない。

## 局所の残債
Storeはopaque filesystem locatorとしてraw SHA256を使う一方、PAR wireのsealed-block IDはtyped domain hashである。envelope IDは一致しており今回の文書commitを結合したが、添付block locator対応は未結合。wire IDをraw SHAへ勝手に変更しない。将来のadapterはtyped ID検証→raw locatorの対応を原子的に保存して照合するか、store候補profileを移行する。受入れ: mismatch/corrupt mapping/GC/backupで誤対象を返さないこと。

## Gate
crypto実験の成功でOD-01やG0全体を閉じない。native修正版、strict rejection corpus、権限state、Automerge actor、key lifecycle、外部レビューの残りを追跡する。
