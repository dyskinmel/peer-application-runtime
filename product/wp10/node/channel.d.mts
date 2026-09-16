import type {EventContext,EventHostChannel,HostOperation} from '../lib/index.js';
/** socket is a trusted preconnected Node Duplex, runtime-validated. No listener. */
export class ConnectedEventChannel implements EventHostChannel {
  constructor(socket:unknown,options:{expectedContext:EventContext;requestTimeoutMs?:number;helloTimeoutMs?:number});
  readonly ready:Promise<Readonly<{hostId:string;context:EventContext}>>;
  request(operation:HostOperation,args:unknown,signal:AbortSignal):Promise<unknown>;
  stats():Readonly<{closed:boolean;inflight:number;bufferedBytes:number}>;
  close():Promise<void>;
}
