// Pure local history tests: no browser, storage, API or database writes.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';
const source=await fs.readFile(new URL('../lib/flintplate-order-undo.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const h={};new Function('exports',code)(h);
const key='tenant/email/venue/orders/dine_in/table-a';
const empty={table:'table-a',fulfillment:'dine_in',revision:'r0',requestKey:'key0',cart:[],note:'',pending:null,uncertain:false,warning:''};
const item={id:'dish',name:'Testgericht',price_cents:1000,version:1,allergens:['milk']};
const first={...empty,revision:'r1',cart:[{item,quantity:1}]};
let history=h.recordOrderUndo(h.emptyOrderUndo(),key,empty,first,'Artikel hinzugefügt');
assert.deepEqual(h.orderUndoContent(history,key,first,'r1'),{cart:[],note:''});
const second={...first,revision:'r2',cart:[{item,quantity:2,course:2}]};
history=h.recordOrderUndo(history,key,first,second,'Menge/Gang geändert');
const snapshot=h.orderUndoContent(history,key,second,'r2');
assert.equal(snapshot.cart[0].quantity,1);assert.equal(snapshot.cart[0].course,undefined);
assert.deepEqual(Object.keys(snapshot).sort(),['cart','note'],'Only editable content can return, never target, revision, pending payload or request key.');
snapshot.cart[0].item.allergens.push('nuts');
assert.deepEqual(h.orderUndoContent(history,key,second,'r2').cart[0].item.allergens,['milk'],'Undo snapshots do not share mutable item arrays.');
const undone={...second,...h.orderUndoContent(history,key,second,'r2'),revision:'r3',requestKey:'fresh-key'};
history=h.commitOrderUndo(history,key,'r2','r3');
assert.equal(history.steps.length,1);assert.deepEqual(h.orderUndoContent(history,key,undone,'r3'),{cart:[],note:''});
for(const foreign of ['other-principal','other-endpoint','other-table','takeaway'])assert.equal(h.orderUndoContent(history,foreign,undone,'r3'),null);
assert.equal(h.orderUndoContent(history,key,undone,'foreign-revision'),null);
assert.equal(h.orderUndoContent(history,key,undone,null),null,'A deleted persisted draft cannot be overwritten by undo.');
assert.equal(h.orderUndoContent(history,key,{...undone,revision:'untracked-local-revision'},'untracked-local-revision'),null);
const sending={...undone,revision:'r4',uncertain:true,pending:{request_key:'fresh-key'}};
history=h.rebaseOrderUndo(history,key,'r3','r4');
assert.equal(history.steps.length,1);assert.equal(h.orderUndoContent(history,key,sending,'r4'),null,'Uncertain sends lock every stored undo step.');
const rejected={...sending,revision:'r5',uncertain:false,pending:null};history=h.rebaseOrderUndo(history,key,'r4','r5');
assert.deepEqual(h.orderUndoContent(history,key,rejected,'r5'),{cart:[],note:''},'Known validation failure may restore local editing without restoring an old send payload.');
assert.equal(h.orderUndoContent(h.emptyOrderUndo(),key,rejected,'r5'),null,'Confirmed send or storage/scope failure clears the whole history.');

let before=first, notes=h.emptyOrderUndo();
for(const note of ['o','oh','ohn','ohne']){const after={...before,note,revision:`note-${note}`};notes=h.recordOrderUndo(notes,key,before,after,'Notiz geändert','focus-1');before=after;}
assert.equal(notes.steps.length,1);assert.equal(h.orderUndoContent(notes,key,before,before.revision).note,'','Continuous typing is one undo.');
const focusedAgain={...before,note:'ohne Zwiebeln',revision:'new-focus'};
notes=h.recordOrderUndo(notes,key,before,focusedAgain,'Notiz geändert','focus-2');assert.equal(notes.steps.length,2);
const cleared={...focusedAgain,cart:[],note:'',revision:'cleared'};
notes=h.recordOrderUndo(notes,key,focusedAgain,cleared,'Entwurf geleert');
assert.equal(h.orderUndoContent(notes,key,cleared,'cleared').note,'ohne Zwiebeln');
assert.equal(h.orderUndoContent(notes,key,cleared,'cleared').cart[0].quantity,1);
let bounded=h.emptyOrderUndo();before=empty;
for(let index=0;index<100;index++){const after={...before,note:String(index),revision:`bounded-${index}`};bounded=h.recordOrderUndo(bounded,key,before,after,'Notiz geändert');before=after;}
assert.equal(bounded.steps.length,h.ORDER_UNDO_LIMIT);
assert.equal(h.rebaseOrderUndo(bounded,'new-target',before.revision,'other').steps.length,0);
console.log('Order undo: local content only, scope/revision/deletion guards, uncertainty, note grouping, clear and bounded history passed.');
