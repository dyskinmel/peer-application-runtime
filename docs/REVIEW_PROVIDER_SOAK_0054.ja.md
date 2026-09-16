# 独立レビュー依頼: WP13 local provider soak

対象はrelease/STATUSのsource HEADを固定し、0053からの差分を確認してください。この同一contextの自己検査は独立レビューではありません。
重点: first-failure terminal、BEGIN/RESULT/SEALの終了証拠、壊れた履歴や別sourceの拒否、予約FD控除の正しさ、実漏れの検出、fixtureの明示、保存状態の完全性、host/cgroupとRSSの表現、provider missing/応答喪失の分類。
再現: check_provider_soak.py、run_provider_soak.pyの140roundとstop/resume、test_process内の実FD/task leak、test_campaign内のSIGKILL2地点、test_providersのflock保持者SIGKILL。
G8・7日・24h・OS鍵保管・全体rollback・public IP・CRDTに昇格させないでください。Critical/Importantは再現器と対象commit、実行結果、未実行項目を返してください。
