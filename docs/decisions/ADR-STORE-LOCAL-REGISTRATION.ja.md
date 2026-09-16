# G0-STORE-LOCAL の登録（00.05.00）

元G0-STORE/OD-04と、今回のローカル実験を別taskへ分ける。
LOCALはPython/SQLite/POSIX、core/blocks/faults/recoveryの4checkの実際のtest ID集合を照合する。
全G0〜G11はNOT_RUN。元149要件の責任taskは変えない。親G0-STOREは未登録の追加検証/native/crypto統合を残す。
新規テスト・policy・H0の変更は前sessionを再利用せず、最終candidateでfresh sessionを作る。
source/context/doctor/ログ/結果/nonce/case集合を照合する。生ログはreleaseへ保存するが、配布時にactive .harnessは含めない。
