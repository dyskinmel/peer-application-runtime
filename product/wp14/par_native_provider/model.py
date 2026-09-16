"""Strict provider capability descriptors for the 00.56 native handoff.

Descriptors are claims about an injected implementation, not evidence that an OS
provider was built or qualified.  In particular, source-authored native adapters
remain BUILD_NOT_RUN/DEVICE_UNVERIFIED until measured on that platform.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

PROFILE='par-native-provider-handoff-0056'
_STATUSES={'AVAILABLE','INJECTED_REQUIRED','SOURCE_AUTHORED_BUILD_NOT_RUN','INTERFACE_ONLY'}
_PROTECTION={'LOCAL_UNPROTECTED','UNVERIFIED','OS_PROTECTED'}
_NATIVE_BUILD={'NOT_APPLICABLE','BUILD_NOT_RUN','BUILD_VERIFIED'}
_CAPS=('pinStore','callerIntentStore','connectionFactory')
_VERSION_KEYS=('handoff','wire','suite','store','sdk','ui')

def _bool(v):
    if type(v) is not bool: raise ValueError('MANIFEST_BOOL')
    return v

def _text(v,code,pattern=r'[A-Za-z0-9_.:-]{1,96}'):
    if type(v) is not str or re.fullmatch(pattern,v) is None: raise ValueError(code)
    return v

def _epoch(v): return _text(v,'PROVIDER_EPOCH',r'[0-9a-f]{32}')

@dataclass(frozen=True)
class Capability:
    status:str
    factory_supplied:bool
    atomicity:str
    cancellation:str
    resume:str
    epoch_bound:bool
    def to_dict(self):
        return {'status':self.status,'factorySupplied':self.factory_supplied,'atomicity':self.atomicity,
                'cancellation':self.cancellation,'resume':self.resume,'epochBound':self.epoch_bound}
    @classmethod
    def from_dict(cls,v):
        if type(v) is not dict or set(v)!={'status','factorySupplied','atomicity','cancellation','resume','epochBound'}:raise ValueError('CAPABILITY_FIELDS')
        status=_text(v['status'],'CAPABILITY_STATUS')
        if status not in _STATUSES:raise ValueError('CAPABILITY_STATUS')
        supplied=_bool(v['factorySupplied'])
        if status=='AVAILABLE' and not supplied:raise ValueError('CAPABILITY_FACTORY')
        return cls(status,supplied,_text(v['atomicity'],'CAPABILITY_ATOMICITY'),_text(v['cancellation'],'CAPABILITY_CANCELLATION'),_text(v['resume'],'CAPABILITY_RESUME'),_bool(v['epochBound']))

@dataclass(frozen=True)
class ProviderDescriptor:
    profile:str
    provider_id:str
    provider_version:str
    platform:str
    epoch:str
    protection:str
    os_protection_proven:bool
    rollback_protection_proven:bool
    native_build:str
    versions:dict[str,str]
    capabilities:dict[str,Capability]
    product_qualified:bool=False
    def to_dict(self):
        return {'profile':self.profile,'providerId':self.provider_id,'providerVersion':self.provider_version,
                'platform':self.platform,'epoch':self.epoch,'protection':self.protection,
                'osProtectionProven':self.os_protection_proven,'rollbackProtectionProven':self.rollback_protection_proven,
                'nativeBuild':self.native_build,'versions':dict(self.versions),
                'capabilities':{k:self.capabilities[k].to_dict() for k in _CAPS},'productQualified':self.product_qualified}
    @classmethod
    def from_dict(cls,v):
        fields={'profile','providerId','providerVersion','platform','epoch','protection','osProtectionProven','rollbackProtectionProven','nativeBuild','versions','capabilities','productQualified'}
        if type(v) is not dict or set(v)!=fields:raise ValueError('MANIFEST_FIELDS')
        if v['profile']!=PROFILE:raise ValueError('MANIFEST_PROFILE')
        protection=_text(v['protection'],'PROTECTION_CLASS')
        if protection not in _PROTECTION:raise ValueError('PROTECTION_CLASS')
        native=_text(v['nativeBuild'],'NATIVE_BUILD')
        if native not in _NATIVE_BUILD:raise ValueError('NATIVE_BUILD')
        os_proven=_bool(v['osProtectionProven']);rollback=_bool(v['rollbackProtectionProven']);qualified=_bool(v['productQualified'])
        if native!='BUILD_VERIFIED' and os_proven:raise ValueError('PROTECTION_UNVERIFIED')
        if protection!='OS_PROTECTED' and os_proven:raise ValueError('PROTECTION_UNVERIFIED')
        if rollback and not os_proven:raise ValueError('ROLLBACK_UNVERIFIED')
        if qualified:raise ValueError('PRODUCT_QUALIFICATION_FORBIDDEN')
        versions=v['versions']
        if type(versions)is not dict or set(versions)!=set(_VERSION_KEYS):raise ValueError('VERSION_FIELDS')
        versions={k:_text(versions[k],'VERSION_VALUE',r'[A-Za-z0-9_.:-]{1,64}') for k in _VERSION_KEYS}
        caps=v['capabilities']
        if type(caps)is not dict or set(caps)!=set(_CAPS):raise ValueError('CAPABILITY_NAMES')
        caps={k:Capability.from_dict(caps[k]) for k in _CAPS}
        return cls(PROFILE,_text(v['providerId'],'PROVIDER_ID'),_text(v['providerVersion'],'PROVIDER_VERSION'),
                   _text(v['platform'],'PROVIDER_PLATFORM'),_epoch(v['epoch']),protection,os_proven,rollback,native,versions,caps,False)

def _versions():
    # These identifiers are deliberately independent. Numeric similarity never grants compatibility.
    return {'handoff':'0056','wire':'draft-2','suite':'local-synthetic','store':'local-v1','sdk':'0055','ui':'0053'}

def experimental_posix_descriptor(*,epoch:str):
    raw={'profile':PROFILE,'providerId':'experimental-posix-local','providerVersion':'0056','platform':'posix-local',
         'epoch':_epoch(epoch),'protection':'LOCAL_UNPROTECTED','osProtectionProven':False,'rollbackProtectionProven':False,
         'nativeBuild':'NOT_APPLICABLE','versions':_versions(),'productQualified':False,
         'capabilities':{
            'pinStore':{'status':'AVAILABLE','factorySupplied':True,'atomicity':'DURABLE_CAS_LOCAL_FS','cancellation':'NOT_APPLICABLE','resume':'REOPEN_AND_READBACK','epochBound':True},
            'callerIntentStore':{'status':'AVAILABLE','factorySupplied':True,'atomicity':'CREATE_ONLY_LOCAL_FS','cancellation':'NOT_APPLICABLE','resume':'REOPEN_AND_READBACK','epochBound':True},
            'connectionFactory':{'status':'INJECTED_REQUIRED','factorySupplied':False,'atomicity':'NOT_APPLICABLE','cancellation':'COOPERATIVE_EVENT','resume':'NEW_CONNECTION_REQUIRED','epochBound':True}}}
    return ProviderDescriptor.from_dict(raw)

def apple_source_descriptor(*,epoch:str):
    raw={'profile':PROFILE,'providerId':'apple-keychain-source-candidate','providerVersion':'0056','platform':'apple-security-framework',
         'epoch':_epoch(epoch),'protection':'UNVERIFIED','osProtectionProven':False,'rollbackProtectionProven':False,
         'nativeBuild':'BUILD_NOT_RUN','versions':_versions(),'productQualified':False,
         'capabilities':{
            'pinStore':{'status':'INTERFACE_ONLY','factorySupplied':False,'atomicity':'CAS_NOT_IMPLEMENTED','cancellation':'NOT_APPLICABLE','resume':'UNVERIFIED','epochBound':True},
            'callerIntentStore':{'status':'SOURCE_AUTHORED_BUILD_NOT_RUN','factorySupplied':False,'atomicity':'CREATE_ONLY_KEYCHAIN_CANDIDATE','cancellation':'NOT_APPLICABLE','resume':'UNVERIFIED','epochBound':True},
            'connectionFactory':{'status':'INTERFACE_ONLY','factorySupplied':False,'atomicity':'NOT_APPLICABLE','cancellation':'COOPERATIVE','resume':'NEW_CONNECTION_REQUIRED','epochBound':True}}}
    return ProviderDescriptor.from_dict(raw)
