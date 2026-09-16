"""Headless presentation contract. No UI, percent guesses or safety decisions."""
def present(status):
    state=status['state']
    messages={'QUEUED':'準備待ち','VALIDATED':'入力検証済み','PREPARED':'実行前・取消し可能',
              'OUTCOME_UNKNOWN':'結果の照合が必要','RETRY_READY':'再実行には明示的な指示が必要',
              'SUCCEEDED':'永続記録との結果照合済み','CANCELLED':'このジョブは実行開始前に取消し済み'}
    return {'message_key':'management.'+state.lower(),'fallback_ja':messages[state],
            'cancel_enabled':status['cancellable'],'reconcile_enabled':status['requires_reconciliation'],
            'retry_enabled':status['explicit_retry_required'],'determinate_progress':False,
            'show_verified_result':status['result_verified'],'waiting':status['waiting_reason'],
            'cancel_is_rollback':False,'product_qualified':False}
