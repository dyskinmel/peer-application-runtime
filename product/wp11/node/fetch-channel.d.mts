import type {FetchPin} from '../lib/fetch-observation.js';
import type {FetchOwnerOperation,FetchOwnerPort} from '../lib/fetch-owner.js';
export class ConnectedFetchChannel implements FetchOwnerPort {
 constructor(socket:unknown,options:{expectedContext:FetchPin;requestTimeoutMs?:number;helloTimeoutMs?:number});
 readonly ready:Promise<{hostId:string;context:FetchPin}>;
 request(operation:FetchOwnerOperation,args:unknown,signal:AbortSignal):Promise<unknown>;
 stats():{closed:boolean;inflight:number;bufferedBytes:number};
 close():Promise<void>;
}
