import {FetchReadBinding, type FetchPin, type FetchObservation,
        presentFetchObservation, mountFetchStatus} from '../../../product/wp11/lib/fetch-observation.js';
declare const pin:FetchPin;
declare const observation:FetchObservation;
declare const root:HTMLElement;
const binding=new FetchReadBinding(pin,{observe:async()=>observation});
const panel=presentFetchObservation(observation,'ja');
const mounted=mountFetchStatus(root,binding,'en');
void mounted.refresh();mounted.setLocale('ja');mounted.destroy();
// @ts-expect-error Observations cannot become application claims.
observation.applied=true;
// @ts-expect-error A candidate panel cannot be a shared commit receipt.
const committed:true=panel.sharedCommit;
// @ts-expect-error The binding does not expose a write command.
binding.apply('implicit');
// @ts-expect-error Pinned context is immutable.
pin.scope.documentId='changed';
// @ts-expect-error A caller cannot edit freshness state.
binding.current.status='CURRENT';
// @ts-expect-error Unsupported locale is not silently accepted.
mounted.setLocale('es');
