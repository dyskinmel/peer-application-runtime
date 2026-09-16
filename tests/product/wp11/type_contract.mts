import {COMMANDS, present,prepareCommand,prepareDraftCommit,createDraft,reduceDraft} from '../../../product/wp11/src/index.js';
import type {Command,CommandKind,NoteState,NoteViewModel,Intent,DraftEvent} from '../../../product/wp11/src/index.js';
import type {UiCommandKind as BaselineCommandKind} from '../../../baseline/spec-00.02.00/api/par-contracts.js';
const all:readonly BaselineCommandKind[]=COMMANDS;
declare const state:NoteState;
declare const command:Command;
const vm:NoteViewModel=present(state);
const intent:Intent=prepareCommand(state,command);
const effect:false=intent.effectExecuted;
const draft=createDraft('text','frontier');
reduceDraft(draft,{type:'input',text:'next',anchor:4,focus:4});
const splice=prepareDraftCommit(state,draft,'operation');
// @ts-expect-error runtime gates not implemented by this Presenter
const completed:true=splice.effectExecuted;
// @ts-expect-error arbitrary code is not an available UI command
const shell:CommandKind='execute-shell';
// @ts-expect-error ViewModel is immutable
vm.document.text='mutate';
// @ts-expect-error decimal u64 may not be a Number
const wrong:Command={...command,sequence:9007199254740992};
// @ts-expect-error composition must not commit a document
const unexpected:DraftEvent={type:'commit'};
// @ts-expect-error all capability fields must be specified
const missing:NoteState={schemaVersion:1};
void [all,vm,intent,effect,completed,shell,wrong,unexpected,missing];
