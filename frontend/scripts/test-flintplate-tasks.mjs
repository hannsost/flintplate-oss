// Pure contracts only; no API, DB or browser. Run from the integrated frontend.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
const require=createRequire(`${process.cwd()}/package.json`),ts=require('typescript');
async function module(api,identityApi=()=>{throw Error("Unexpected identity request");}){const source=await fs.readFile(new URL('../lib/flintplate-tasks.ts',import.meta.url),'utf8');const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;const exports={};new Function('require','exports',code)(name=>{assert.equal(name,'./flintplate');return{venueApi:api,api:identityApi};},exports);return exports;}
const p=await module(()=>{throw Error('Unexpected API');});
const task={id:'a',venue_id:'v',assigned_to:'staff',priority:'medium',due_at:null,status:'open',created_at:'2026-09-13T10:00:00Z'};
assert.deepEqual(p.taskActions(task,'staff',false),['start','done']);
const emailPrincipal='worker@example.test',userUuid='abcde123-1234-4567-890a-123456789abc';
const identityModule=await module(()=>{throw Error('Unexpected venue request');},async path=>{assert.equal(path,'/users/me');return{id:userUuid,tenant_id:'tenant'};});
const ownTask={...task,assigned_to:userUuid};
assert.deepEqual(p.taskActions(ownTask,emailPrincipal,false),[], 'An email claim is never an assignment UUID.');
const authoritativeId=await identityModule.taskUserId('tenant',()=>true);
assert.equal(authoritativeId,userUuid);
assert.deepEqual(p.taskActions(ownTask,authoritativeId,false),['start','done'], 'Authoritative own UUID enables employee actions.');
let releaseIdentity,stillCurrent=true;
const late=await module(()=>{throw Error('Unexpected venue request');},()=>new Promise(resolve=>{releaseIdentity=resolve;}));
const pendingIdentity=late.taskUserId('tenant',()=>stillCurrent);stillCurrent=false;releaseIdentity({id:userUuid,tenant_id:'tenant'});
assert.equal(await pendingIdentity,null,'A late identity response must not restore actions after account switch.');
await assert.rejects(identityModule.taskUserId('other-tenant',()=>true),/Aufgabenberechtigung/);

assert.deepEqual(p.taskActions(task,'other',false),[]);
assert.deepEqual(p.taskActions(task,'manager',true),['edit','reassign','cancel']);
assert.deepEqual(p.taskActions({...task,status:'done'},'staff',false),[]);
assert.deepEqual(p.taskActions({...task,status:'done'},'manager',true),['reopen']);
assert.equal([task,{...task,id:'old',priority:'urgent',created_at:'2020-01-01'}].sort(p.compareTasks)[0].id,'old');
let calls=0;
const paged=await module(async(_venue,path)=>{calls++;if(calls===1)return{items:[task],has_more:true,next_before:'a'};assert.match(path,/before=a/);return{items:[{...task,id:'old',priority:'urgent'}],has_more:false,next_before:null};});
assert.deepEqual((await paged.openTasks('v',true)).map(row=>row.id),['old','a']);
const broken=await module(async()=>({items:[task],has_more:true,next_before:'a'}));await assert.rejects(broken.openTasks('v',true),/vollständig|unvollständig/);
const wrong=await module(async()=>({items:[{...task,venue_id:'foreign'}],has_more:false,next_before:null}));await assert.rejects(wrong.openTasks('v',true),/vollständig/);
console.log('Task API identity/email separation, late-response protection, permissions and pagination passed.');
