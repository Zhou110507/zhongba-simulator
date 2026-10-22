'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');

function harness(){
  const nodes=new Map(),scheduled=new Set(),calls=[],responses=new Map();
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
    setTimeout(fn,ms){if(ms===600||ms===750){const task={fn,ms};scheduled.add(task);return task;}return setImmediate(fn);},
    clearTimeout(task){scheduled.delete(task);},
    api:async(path,data)=>{calls.push({path,data});if(hook)await hook(path,data);
      if(responses.has(path))return structuredClone(responses.get(path));
      return path.endsWith('/start')?{id:'job',status:'running'}:
        path.endsWith('/status')?{id:'job',status:'found',analysis:structuredClone(analysis)}:{revision:1};},
  };
  vm.createContext(c);vm.runInContext(fs.readFileSync('web/ai-opponent.js','utf8'),c);
  return {flow:c.window.AIOpponent,$,ctx,calls,scheduled,setRules:v=>rules=v,
    setHook:f=>hook=f,setResponse:(path,value)=>responses.set(path,value),setAnalysis:value=>Object.assign(analysis,value),accepted:()=>accepted};
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

test('route explains side spin, rail count and actual jaw-assisted entry',async()=>{
  const h=harness();h.setAnalysis({model:'short-runout-value-v3',evaluations:100,elapsed:1,
    requested_depth:3,verified_depth:3,horizon_complete:true,
    routes:[{clear_verified:false,reasons:['比较进球与走位代价'],steps:[{
      target:'1',pocket:'top-right',cue_final:{x:1,y:.6},
      shot:{cue_speed:2.5,tip_x:-.25,tip_y:.3},cue_cushions:4,clean_pot:false,
      cue_jaw_contacts:1,human_margin:{pot_passed:4,leaf_passed:3,checked:4},
      cut_degrees:25,distance_mm:600,object_distance_mm:400,human:{notes:[]}}]}]});
  await h.flow.think();
  const text=h.$('ai-routes').children[0].children[1].children[0].textContent;
  assert.match(text,/左塞 0.25 R/);assert.match(text,/白球 4 库/);assert.match(text,/碰袋角后入袋/);
  assert.match(text,/白球碰袋角 1 次，已计入高风险走位代价/);
  assert.match(text,/4\/4 项进球，3\/4 项保留舒服续接/);
  assert.match(h.$('ai-status').textContent,/前瞻 3\/3 杆（已满足）/);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
});

test('prefetched next job waits for replay and is consumed without a second start',async()=>{
  const h=harness();await h.flow.think();
  h.setResponse('/api/ai/execute',{result:{},rule_committed:true,
    prefetch:{id:'next-job',status:'found',game_id:'match',revision:1,cache_hit:true}});
  h.setHook(async path=>{if(path.endsWith('/execute'))h.ctx.idle=false;});
  await h.$('ai-execute').onclick();
  assert.equal(h.calls.find(c=>c.path.endsWith('/execute')).data.prefetch,true);
  const starts=h.calls.filter(c=>c.path.endsWith('/start')).length;
  await h.flow.think();assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,starts);
  h.ctx.game.revision=1;h.ctx.idle=true;
  await h.flow.think();
  assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,starts);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/status')).at(-1).data.id,'next-job');
});

test('human-shot replay can precompute AI but cannot execute before ball stop',async()=>{
  const h=harness();h.ctx.game.turn=0;h.ctx.idle=false;
  await h.flow.precompute({...h.ctx.game,turn:1,revision:1});
  assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,1);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
  await h.flow.think();assert.equal(h.calls.some(c=>c.path.endsWith('/status')),false);
  h.ctx.game.turn=1;h.ctx.game.revision=1;h.ctx.idle=true;
  await h.flow.think();
  assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,1);
});

test('late human-shot prefetch is cancelled when the user leaves the match',async()=>{
  const h=harness();h.ctx.idle=false;
  h.setHook(async path=>{if(path.endsWith('/start')){h.flow.cancelForChange();h.setRules(false);}});
  await h.flow.precompute({...h.ctx.game,revision:1});
  assert.equal(h.calls.filter(c=>c.path.endsWith('/cancel')).length,1);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
});

test('late prefetch does not cancel the same job already adopted by a normal think',async()=>{
  const h=harness();h.ctx.game.turn=0;h.ctx.idle=false;
  let release,entered=0;const gate=new Promise(resolve=>release=resolve);
  h.setHook(async path=>{if(path.endsWith('/start')&&++entered===1)await gate;});
  const pending=h.flow.precompute({...h.ctx.game,turn:1,revision:1});
  await new Promise(resolve=>setImmediate(resolve));
  h.ctx.game.turn=1;h.ctx.game.revision=1;h.ctx.idle=true;
  await h.flow.think();release();await pending;
  assert.equal(h.calls.some(c=>c.path.endsWith('/cancel')),false);
});

function rollingRoute(targets){return {clear_verified:false,reasons:[],steps:targets.map(target=>({
  target,pocket:'top-right',cue_final:{x:1,y:.6},shot:{cue_speed:1.,tip_x:0,tip_y:0},
  cut_degrees:20,distance_mm:500,object_distance_mm:400,human:{notes:[]}}))};}

test('two-shot prefix waits for the third verified shot without another start',async()=>{
  const h=harness();h.setAnalysis({routes:[rollingRoute(['2','3'])],evaluations:0,elapsed:0,
    rolling:{target:3,remaining:2,extending:true,exhausted:false}});
  await h.flow.think();assert.equal(h.$('ai-execute').disabled,true);
  await h.$('ai-execute').onclick();assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
  assert.match(h.$('ai-status').textContent,/后台继续补算/);
  const task=[...h.scheduled].find(t=>t.ms===750);assert.ok(task);
  h.setAnalysis({routes:[rollingRoute(['2','3','4'])],extended_steps:1,extension_evaluations:50,
    rolling:{target:3,remaining:3,extending:false,exhausted:false}});
  await task.fn();
  assert.equal(h.$('ai-routes').children[0].children[1].children.length,3);
  assert.match(h.$('ai-status').textContent,/队尾新增 1 杆/);
  assert.equal(h.$('ai-execute').disabled,false);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,1);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
});

test('automatic play cannot overtake a slow suffix and executes once when the queue fills',async()=>{
  const h=harness();h.$('ai-auto').checked=true;
  const waiting={routes:[rollingRoute(['2','3'])],evaluations:0,elapsed:0,
    execution_gate:{kind:'offense',available:2,required:3,ready:false,waiting:true},
    rolling:{target:3,remaining:2,extending:true,exhausted:false}};
  h.setAnalysis(waiting);await h.flow.think();
  await new Promise(resolve=>setImmediate(resolve));
  for(let i=0;i<3;i++){
    const task=[...h.scheduled].find(t=>t.ms===750);assert.ok(task);h.scheduled.delete(task);await task.fn();
    h.flow.refresh();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(h.$('ai-execute').disabled,true);
    assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
  }
  assert.match(h.$('ai-status').textContent,/等待队尾补算，暂不出杆/);
  const task=[...h.scheduled].find(t=>t.ms===750);h.scheduled.delete(task);
  h.setAnalysis({routes:[rollingRoute(['2','3','4'])],
    execution_gate:{kind:'offense',available:3,required:3,ready:true},
    rolling:{target:3,remaining:3,extending:false,exhausted:false}});
  await task.fn();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.calls.filter(c=>c.path.endsWith('/execute')).length,1);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,1);
});

test('pausing automatic play during the wait preserves the filled plan without shooting',async()=>{
  const h=harness();h.$('ai-auto').checked=true;
  h.setAnalysis({routes:[rollingRoute(['2','3'])],
    execution_gate:{kind:'offense',ready:false,available:2,required:3},
    rolling:{target:3,remaining:2,extending:true}});
  await h.flow.think();h.flow.pause();
  const task=[...h.scheduled].find(t=>t.ms===750);h.scheduled.delete(task);
  h.setAnalysis({routes:[rollingRoute(['2','3','4'])],
    execution_gate:{kind:'offense',ready:true,available:3,required:3},
    rolling:{target:3,remaining:3,extending:false}});
  await task.fn();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.$('ai-execute').disabled,false);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/start')).length,1);
});

test('a verified finish with fewer than three strokes is executable but an exhausted partial route is not',async()=>{
  const h=harness();const finish=rollingRoute(['2','8']);finish.clear_verified=true;
  h.setAnalysis({routes:[finish],execution_gate:{kind:'offense',ready:true,required:2,available:2}});
  await h.flow.think();assert.equal(h.$('ai-execute').disabled,false);
  const q=harness();q.$('ai-auto').checked=true;
  q.setAnalysis({routes:[rollingRoute(['2','3'])],
    execution_gate:{kind:'offense',ready:false,required:3,available:2,blocked:true},
    rolling:{target:3,remaining:2,extending:false,exhausted:true}});
  await q.flow.think();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(q.$('ai-execute').disabled,true);
  assert.match(q.$('ai-status').textContent,/未找到足够续接/);
  assert.equal(q.calls.some(c=>c.path.endsWith('/execute')),false);
  assert.equal([...q.scheduled].some(t=>t.ms===750),false);
});

test('late rolling status cannot restore a plan after the layout changes',async()=>{
  const h=harness();h.setAnalysis({routes:[rollingRoute(['2','3'])],evaluations:0,elapsed:0,
    rolling:{target:3,remaining:2,extending:true}});
  await h.flow.think();
  const task=[...h.scheduled].find(t=>t.ms===750);assert.ok(task);
  let release;const gate=new Promise(resolve=>release=resolve);
  h.setHook(async path=>{if(path.endsWith('/status'))await gate;});
  const pending=task.fn();h.flow.cancelForChange();h.ctx.game.revision++;
  release();await pending;
  assert.equal(h.$('ai-routes').children.length,0);
  assert.equal(h.calls.some(c=>c.path.endsWith('/execute')),false);
});

test('tactical fallback does not keep polling for a nonexistent offensive queue',async()=>{
  const h=harness();h.setAnalysis({routes:[],tactic:'safety',
    rolling:{target:3,remaining:0,extending:false,exhausted:false}});
  await h.flow.think();
  assert.equal(h.$('ai-execute').disabled,false);
  assert.equal([...h.scheduled].some(t=>t.ms===750),false);
});

test('execution record distinguishes ideal plan from actual motor error',()=>{
  const h=harness();
  assert.match(h.flow.executionText({level:'expert'}),/无额外出杆误差/);
  const text=h.flow.executionText({level:'novice',label:'入门',
    planned_shot:{angle_deg:10,cue_speed:2},actual_shot:{angle_deg:10.2,cue_speed:1.9},
    angle_error_deg:.2,speed_error_fraction:-.05});
  assert.match(text,/计划方向 10.000/);assert.match(text,/实际方向 10.200/);assert.match(text,/-5.00%/);
});
