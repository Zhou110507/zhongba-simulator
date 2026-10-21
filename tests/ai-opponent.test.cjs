'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');

function harness(){
  const nodes=new Map(),scheduled=new Set(),calls=[];
  const element=()=>({children:[],checked:false,disabled:false,hidden:false,textContent:'',className:'',
    append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});
  const $=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const ctx={game:{id:'match',revision:0,turn:1,ai_player:1,phase:'playing'},idle:true};
  let rules=true,accepted=0,hook=null;
  const analysis={status:'found',model:'short-runout-value-v1',routes:[],
    action:{action:'place',x:.4,y:.6},message:'AI 自由球摆放'};
  const c={window:{TableModes:{aiContext:()=>structuredClone(ctx),isRules:()=>rules,acceptAI:()=>accepted++}},
    $,document:{createElement:element},pocketNames:{},Blob:class{},URL:{},
    refreshUI(){c.window.AIOpponent?.refresh();},
    setTimeout(fn,ms){if(ms===600){const task={fn};scheduled.add(task);return task;}return setImmediate(fn);},
    clearTimeout(task){scheduled.delete(task);},
    api:async(path,data)=>{calls.push({path,data});if(hook)await hook(path,data);
      return path.endsWith('/start')?{id:'job',status:'running'}:
        path.endsWith('/status')?{id:'job',status:'found',analysis:structuredClone(analysis)}:{revision:1};},
  };
  vm.createContext(c);vm.runInContext(fs.readFileSync('web/ai-opponent.js','utf8'),c);
  return {flow:c.window.AIOpponent,$,ctx,calls,scheduled,setRules:v=>rules=v,
    setHook:f=>hook=f,accepted:()=>accepted};
}

test('AI is opt-in and does not lock practice or local two-player controls',()=>{
  const h=harness();h.ctx.game.ai_player=null;h.flow.refresh();
  assert.equal(h.flow.ownsTurn(),false);assert.equal(h.$('ai-think').disabled,true);
  assert.equal(h.scheduled.size,0);
  h.ctx.game.ai_player=1;h.setRules(false);h.flow.refresh();
  assert.equal(h.flow.ownsTurn(),false);assert.equal(h.$('ai-panel').hidden,true);
});

test('setup never schedules AI or locks the layout editor',()=>{
  const h=harness();h.ctx.game.phase='setup';h.$('ai-auto').checked=true;h.flow.refresh();
  assert.equal(h.flow.ownsTurn(),false);assert.equal(h.scheduled.size,0);
  assert.equal(h.$('ai-think').disabled,true);
  assert.match(h.$('ai-status').textContent,/摆好/);
});

test('thinking returns a plan without committing; execution is a separate action',async()=>{
  const h=harness();await h.$('ai-think').onclick();
  assert.equal(h.accepted(),0);assert.equal(h.$('ai-execute').disabled,false);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
  await h.$('ai-execute').onclick();assert.equal(h.accepted(),1);
  assert.equal(h.$('ai-execute').disabled,true);
});

test('late planning responses cannot execute after switching mode or game revision',async()=>{
  const h=harness();h.setHook(async path=>{if(path.endsWith('/start'))h.ctx.game.revision=1;});
  await h.$('ai-think').onclick();
  assert.equal(h.$('ai-execute').disabled,true);assert.equal(h.accepted(),0);
  const q=harness();q.setHook(async path=>{if(path.endsWith('/start'))q.flow.cancelForChange();});
  await q.$('ai-think').onclick();
  assert.equal(q.calls.some(c=>c.path.endsWith('/cancel')),true);assert.equal(q.accepted(),0);
});

test('automatic play schedules once per revision and can be paused before a stroke',()=>{
  const h=harness();h.$('ai-auto').checked=true;
  h.flow.refresh();h.flow.refresh();h.flow.refresh();assert.equal(h.scheduled.size,1);
  h.flow.pause();assert.equal(h.scheduled.size,0);assert.equal(h.$('ai-auto').checked,false);
});
