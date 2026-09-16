# ADR-0055: 有限の多接続診断と個別終了確認

Status: USER-APPROVED LOCAL IMPLEMENTATION CANDIDATE / NOT PRODUCT QUALIFICATION
承認元: `plan/NEXT_RESOURCE_MATRIX_0054.ja.md` を進めるというOwner指示。

元0054の2process固定SEALを多processへ流用しない。MatrixCampaignは既存のappend-only/fsync/lock/pin機構を再利用するが、新しいmanifest profile、cell設定、参加者数に一致する終了code配列を要求する。BEGIN中の停止/未SEAL/失敗はそのまま残し、成功までretryしない。新しいコードと実行環境で過去のreceiptを合格へ借用しない。
FairConnectionPoolは試験の有限admission/lifetime管理。productの自動接続機能ではない。FactoryCheckは使い捨てfactoryの限定conformanceであり、暗号認証/OS保護の認定ではない。
2/8個の独立owner/Store namespaceをPythonクライアントから検査する。Nodeの既存検査は維持し、このmatrixをNode/Python多者間のwire互換性として主張しない。キューの公平性は解放可能な枠の選択順で、全枠を非協力providerが占める場合の進捗は保証しない。
全仕様/元G8/7日/24h/SDK/鍵保管/保存形式/nonce/公開listenerの条件は変更しない。
