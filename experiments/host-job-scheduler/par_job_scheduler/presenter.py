"""Presentation data only; never an authorization or an execution command."""
def present(value):
    messages={'SERVING':'データ受付中','DRAINING':'新規受付を止め、既存接続の終了を待っています','REVIEW_REQUIRED':'管理処理の確認が必要です'}
    return {'message_key':'scheduler.'+value['mode'].lower(),'fallback_ja':messages[value['mode']],
            'active_connections':value['activity']['connections'],'reader_pins':value['activity']['reader_pins'],
            'waiting_reason':value['waiting_reason'] or value['fault'],'determinate_progress':False,
            'forced_cancellation_supported':False,'management_is_synchronous':True,'product_qualified':False}
