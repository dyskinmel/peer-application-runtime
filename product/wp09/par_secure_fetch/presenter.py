"""Small UI-facing projection only. No DOM or shared-document state mutation."""
from .persistence import require
from .plan import PROFILE

def present_progress(progress,*,locale='ja'):
    require(locale in('ja','en'),'LOCALE')
    require(type(progress)is dict and progress.get('profile')==PROFILE,'PROGRESS_SCHEMA')
    n=progress.get('total');stored=progress.get('stored');items=progress.get('items')
    require(type(n)is int and 0<=n<=64 and type(stored)is int and 0<=stored<=n,'PROGRESS_SCHEMA')
    require(type(items)is list and len(items)==n,'PROGRESS_SCHEMA')
    unknown=any(row.get('state')=='OUTCOME_UNKNOWN'for row in items)
    state=progress.get('state');require(type(state)is str,'PROGRESS_SCHEMA')
    if locale=='ja':
        msg='保存結果不明。再起動後に再照合してください（文書へ未適用）。'if unknown else f'暗号化候補 {stored}/{n} 件を保存確認。文書へ未適用。'
    else:
        msg='Save outcome unknown; reopen and reconcile. Not applied to document.'if unknown else f'{stored}/{n} encrypted candidates observed stored. Not applied to document.'
    return {'kind':'encrypted-candidate-progress','state':state,'stored':stored,'total':n,'message':msg,
            'applied':False,'localCommitted':False,'replicated':False,'acknowledged':False,'observationOnly':True}
