// Synthetic input construction only. Production never imports this file or story IDs.
export const COMMANDS=['activate-recovery','add-copy','approve-invite','choose-folder','copy-request','create-space','dismiss','export','export-diagnostics','export-partial','force-stop','import-data','inspect-fork','inspect-operation','open-details','pause-recovery','provide-key','retry-connect','review-conflict','review-contribution','review-invite','review-rebase','review-relay','verify-recovery'];
export function state(){return {
 schemaVersion:1,streamId:'stream-1',sequence:'1',revision:'revision-1',snapshotTime:'2026-09-06T00:00:00.000Z',
 scope:{appId:'org.example.notes',spaceId:'space-1',documentId:'note-1'},surface:'protection',
 capabilities:{host:'linux',storageClass:'native-candidate',durableKeeperEligible:false,keyProtection:'software-encrypted',supportsLocalEffectTransaction:false,background:'persistent-process'},
 supportedCommands:[...COMMANDS],local:{state:'committed',storageClass:'native-candidate',operationId:'op-1',cancellationRequested:false},
 protection:{root:'root-1',goal:2,observations:[],keys:'available',physicalIndependence:'unknown'},
 connection:{state:'offline',peers:0},authority:{state:'ready',controlHead:'head-1',epoch:'1',role:'owner',sharedWriteAllowed:true},
 document:{read:'found',title:'旅行',text:'Hello',frontier:'frontier-1',innerValidated:true,applied:true,conflicts:[],privateDraft:false,knownCatalogComplete:true,missingObjects:'0'},
 recovery:{phase:'idle',received:'0',total:null,recipientValidated:false,keys:'available',missingObjects:'0'},
 rpc:{state:'idle',operationId:null},invite:{phase:'none',role:'editor',targetDevice:null,manualAvailable:true,fileAvailable:true},
 contribution:{state:'disabled',storageBudget:'0',relayBudget:'0',activeLeases:0},presence:'unknown',diagnostic:null,previews:[],
 evidence:{kind:'synthetic',references:['synthetic:test']}
};}
export function observation(id='peer-1'){return {deviceId:id,manifest:'root-1',byteComplete:true,semanticClosure:'verified',freshness:'fresh',storageClass:'native-candidate',reachable:'unknown',observedAt:'2026-09-06T00:00:00.000Z'};}
export function preview(s,kind,target='target-1'){return {kind,revision:s.revision,scopeKey:JSON.stringify([s.scope.appId,s.scope.spaceId,s.scope.documentId]),target,planDigest:'a'.repeat(64),impact:'This changes the specified target.'};}
export function storyState(row){const s=state();s.surface=row.surface;s.evidence.references=[row.id];
 switch(row.id){
 case 'UI-001':s.surface='workspace';s.scope.documentId=null;s.document.read='absent-local';s.document.applied=false;s.document.innerValidated=false;s.local.state='unknown';break;
 case 'UI-002':break;
 case 'UI-003':s.local.state='pending';break;
 case 'UI-004':s.protection.observations=[observation(),observation('peer-2')];break;
 case 'UI-005':s.protection.observations=[observation(),observation('peer-2')].map(o=>({...o,freshness:'stale'}));break;
 case 'UI-006':s.protection.observations=[{...observation(),semanticClosure:'unknown'}];break;
 case 'UI-007':s.invite.phase='pending';break;
 case 'UI-008':s.invite.phase='review';s.invite.targetDevice='new-device';s.previews=[preview(s,'approve-invite','new-device')];break;
 case 'UI-009':s.invite.phase='stale';break;
 case 'UI-010':s.document.conflicts=[{value:'旅行A',provenance:'peer-a'},{value:'旅行B',provenance:'peer-b'}];break;
 case 'UI-011':s.authority.state='rebase-required';s.authority.sharedWriteAllowed=false;s.document.privateDraft=true;break;
 case 'UI-012':s.authority.state='fork';s.authority.sharedWriteAllowed=false;break;
 case 'UI-013':s.recovery.phase='fetching';s.recovery.received='7';s.recovery.total='10';break;
 case 'UI-014':s.recovery.phase='verifying';s.recovery.received='10';s.recovery.total='10';break;
 case 'UI-015':s.recovery.phase='obtaining-keys';s.recovery.keys='missing';break;
 case 'UI-016':s.recovery.phase='partial';s.recovery.missingObjects='3';break;
 case 'UI-017':s.recovery.phase='review';s.recovery.recipientValidated=true;s.recovery.received='10';s.recovery.total='10';s.previews=[preview(s,'activate-recovery','root-1')];break;
 case 'UI-018':break;
 case 'UI-019':s.contribution.state='review-stop';s.contribution.activeLeases=2;s.previews=[preview(s,'force-stop','space-1')];break;
 case 'UI-020':s.local.state='failed';s.diagnostic='storage-full';break;
 case 'UI-021':s.connection.state='relay-required';break;
 case 'UI-022':s.rpc.state='unknown';s.rpc.operationId='rpc-1';break;
 case 'UI-023':s.capabilities.host='browser';s.capabilities.background='unsupported';s.capabilities.storageClass='browser-best-effort';s.local.storageClass='browser-best-effort';break;
 case 'UI-024':s.presence='unknown';break;
 default:throw new Error('unknown story');
 }return s;}
export function command(s,kind){return {schemaVersion:1,kind,expectedRevision:s.revision,streamId:s.streamId,sequence:s.sequence,scope:s.scope,operationId:'user-op-1',confirmation:null};}
