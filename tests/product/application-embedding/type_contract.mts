import {ApplicationEmbedding,mountApplicationControls,mountReference} from '../../../product/wp11/lib/index.js';
import type {ApplicationContext,CallerIntentStore,ApplicationOwnerPort} from '../../../product/wp11/lib/application-owner.js';
declare const context:ApplicationContext,store:CallerIntentStore,port:ApplicationOwnerPort,root:HTMLElement;
const e=new ApplicationEmbedding(context,store,['0'.repeat(64)],{localExperiment:true});
e.attach(context,port);const p:Promise<void>=e.stage('6f'.repeat(16),0);void p;
const dispose:Promise<void>=e.detach();void dispose;
const panel=mountApplicationControls(root,e,'ja');const done:Promise<void>=panel.cleanup();void done;
// @ts-expect-error a durable store is mandatory
new ApplicationEmbedding(context);
// @ts-expect-error no automatic connection factory
new ApplicationEmbedding(context,store,[],{autoReconnect:true});
// @ts-expect-error scalar revision only
e.stage('id','0');
// @ts-expect-error no new operation ID for inquiry
e.inquire('replacement');
// @ts-expect-error no record removal or reset method
e.reset();
// @ts-expect-error output is immutable
e.current.dispatchAttempted=false;
