import {ProviderLifetime,type NativeProviderPort,type ProviderDescriptor} from '../../../product/wp14/node/provider-lifetime.mjs';
declare const descriptor:ProviderDescriptor,port:NativeProviderPort;
const s=new ProviderLifetime(descriptor,port,descriptor.epoch);
const status:{cleanupConfirmed:boolean;closed:boolean}=s.status();
const observed:unknown=await s.observe();
const inquiry:unknown=await s.inquire('ab'.repeat(16));
const closed:boolean=await s.close();
void status;void observed;void inquiry;void closed;
