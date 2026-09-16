import type {CommandContext,CommandOperation,EventCommandChannel} from '../lib/index.js';
/** The socket is a trusted preconnected Node Duplex. It is not authenticated here. */
export class ConnectedCommandChannel implements EventCommandChannel {
 constructor(socket:unknown,options:{expectedContext:CommandContext;requestTimeoutMs?:number;helloTimeoutMs?:number});
 readonly ready:Promise<Readonly<{hostId:string;context:CommandContext}>>;
 request(operation:CommandOperation,args:unknown,signal:AbortSignal):Promise<unknown>;
 stats():Readonly<{closed:boolean;inflight:number;bufferedBytes:number}>;
 close():Promise<void>;
}
