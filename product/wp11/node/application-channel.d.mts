import type {ApplicationContext,ApplicationOwnerPort,ApplicationOwnerOperation} from '../lib/application-owner.js';
export class ConnectedApplicationChannel implements ApplicationOwnerPort {
 constructor(socket:unknown,options:{expectedContext:ApplicationContext;requestTimeoutMs?:number;helloTimeoutMs?:number});
 readonly ready:Promise<{hostId:string;context:ApplicationContext}>;
 request(operation:ApplicationOwnerOperation,args:unknown,signal:AbortSignal):Promise<unknown>;
 stats():{closed:boolean;inflight:number;bufferedBytes:number};
 close():Promise<void>;
}
