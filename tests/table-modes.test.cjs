'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');

async function harness(){
  const nodes=new Map();
  function element(){return {value:'0',children:[],disabled:false,hidden:false,dataset:{},style:{},classList:{toggle(){}},setAttribute(){},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;},querySelectorAll(){return [];}};}
  const $=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const ball={id:'cue',pocket:null,position:{x:.3,y:.635}};
  const scene={balls:[ball],shot:{cue_speed:4,tip_x:0,tip_y:0}};
  const config={presets:[{id:'free',scene}],model:{table:{length:2.54,width:1.27}}};
  const game={id:'test-match',revision:0,phase:'playing',rack_number:1,turn:0,is_break:true,scores:[0,0],groups:[null,null],scene,ball_in_hand:'head',needs_placement:false,gap_mm:.2};
  let setCount=0;const requests=[];
  const c={window:{},document:{createElement:element,querySelector:element,querySelectorAll:()=>[]},localStorage:{getItem(){return null;},setItem(){}},$,config,scene,record:null,fired:false,time:0,busy:false,mode:'aim',pending:null,playing:false,STORAGE:'free',clone:structuredClone,
    active:b=>b.pocket==null,cueBall:()=>c.scene.balls[0],color:()=>'',textRule(){},announce:message=>c.message=message,draw(){},refreshSelection(){},refreshUI(){c.window.TableModes?.refresh();},populateEvents(){},
    invalidate(){c.record=null;c.fired=false;c.time=0;c.playing=false;},
    setScene(value){setCount++;c.invalidate();c.scene=structuredClone(value);},
    startReplay(){c.fired=true;c.playing=true;c.time=0;},
    api:async(path,data)=>{requests.push({path,data});return path==='/api/rules/config'?config:structuredClone(game);},
  };
  vm.createContext(c);vm.runInContext(fs.readFileSync('web/table-modes.js','utf8'),c);await Promise.resolve();await $('rules-mode').onclick();
  return {c,$,game,flow:c.window.TableModes,requests,count:()=>setCount};
}

for(const phase of ['playing','choice','finished'])test('committed shot automatically reaches '+phase+' with no apply action',async()=>{
  const {c,$,game,flow,count,requests}=await harness(),n=count(),calls=requests.length;
  const after={...game,revision:1,turn:1,phase,is_break:false,chooser:1,choices:[],winner:1,last_decision:{outcome:'本杆已判定',fouls:[],clauses:[]}};
  c.record={complete:true,rule_committed:true,game_after:after,result:{duration:3}};c.fired=true;c.time=3;
  assert.equal(flow.finish(),true);assert.equal(count(),n+1);assert.equal(c.fired,false);
  assert.equal(requests.length,calls);assert.equal($('next').hidden,true);
  assert.equal($('rule-turn').textContent.includes('玩家 2'),true);
  assert.equal(flow.finish(),false);assert.equal(count(),n+1);
});

test('ordinary foul automatically enters ball-in-hand placement; replay cannot reapply it',async()=>{
  const {c,$,game,flow,count}=await harness();
  const after={...game,revision:1,turn:1,is_break:false,ball_in_hand:'all',needs_placement:true,last_decision:{outcome:'对手全台自由球',fouls:['白球落袋'],clauses:[]}};
  c.record={complete:true,rule_committed:true,game_after:after,result:{duration:2}};c.fired=true;c.time=2;
  flow.finish();assert.equal(c.pending,'cue');assert.equal(c.mode,'edit');assert.equal($('last-shot').disabled,false);
  const n=count();$('last-shot').onclick();assert.equal(c.fired,true);c.time=2;flow.finish();assert.equal(count(),n);
  assert.equal($('before').textContent,'返回当前球台');assert.equal(flow.before(),true);assert.equal(count(),n+1);
  assert.equal(c.pending,'cue');assert.equal($('rule-turn').textContent,'第 1 局 · 玩家 2击球');
});

test('preview or incomplete computation never advances the match',async()=>{
  const {c,game,flow,count}=await harness();const n=count();
  for(const record of [{complete:true,rule_committed:false},{complete:false,rule_committed:false},{complete:false,rule_committed:true}]){
    c.record={...record,game_after:game,result:{duration:1}};c.fired=true;c.time=1;
    assert.equal(flow.finish(),false);assert.equal(count(),n);
  }
});

test('rules never render trails, and returning to free preserves its checkbox preference',async()=>{
  const {flow,$}=await harness();$('trails').checked=true;flow.refresh();
  assert.equal(flow.showTrails(),false);assert.equal($('trails-control').hidden,true);
  assert.equal($('trails').disabled,true);assert.equal($('trails').checked,true);
  await $('free-mode').onclick();assert.equal(flow.showTrails(),true);
  assert.equal($('trails-control').hidden,false);assert.equal($('trails').disabled,false);
  $('trails').checked=false;await $('rules-mode').onclick();assert.equal(flow.showTrails(),false);
  await $('free-mode').onclick();assert.equal(flow.showTrails(),false);assert.equal($('trails').checked,false);
});

test('practice and planner tabs preserve the same layout, shot and preview',async()=>{
  const {c,$,flow,count}=await harness();await $('free-mode').onclick();
  c.scene.shot={angle_deg:32,cue_speed:1.7,tip_x:.1,tip_y:-.3};c.record={complete:true,result:{duration:2}};
  const n=count(),scene=structuredClone(c.scene),preview=c.record;
  await $('planner-mode').onclick();assert.equal(flow.isPlanner(),true);assert.equal($('shot-settings').hidden,true);
  assert.equal(count(),n);assert.deepEqual(c.scene,scene);assert.equal(c.record,preview);
  await $('free-mode').onclick();assert.equal(flow.isPlanner(),false);assert.equal($('shot-settings').hidden,false);
  assert.equal(count(),n);assert.deepEqual(c.scene,scene);assert.equal(c.record,preview);
});

test('custom AI layout creates a new setup and enables editing without unlocking formal games',async()=>{
  const {c,$,flow,game,requests}=await harness();
  assert.equal($('selected-ball').disabled,true);
  let payload;
  c.api=async(path,data)=>{
    payload=data;requests.push({path,data});
    return {...game,id:'custom-match',phase:'setup',scenario:'ai_custom',ai_player:1,groups:['stripe','solid'],is_break:false,ball_in_hand:null};
  };
  // The real renderer first restores the generic controls, then applies mode locks.
  c.refreshUI=()=>{for(const id of ['selected-ball','ball-x','ball-y','add','remove','undo','import'])$(id).disabled=flow.locksAction();flow.refresh();};
  await $('ai-custom').onclick();
  assert.equal(payload.scenario,'ai_custom');assert.deepEqual(payload.scene,game.scene);
  assert.equal(flow.isSetup(),true);assert.equal(flow.locksAction(),false);
  assert.equal($('selected-ball').disabled,false);assert.equal($('ball-x').disabled,false);
  assert.equal($('add').disabled,false);assert.equal($('import').disabled,false);
  assert.equal($('shoot').disabled,true);assert.equal($('ai-finish-setup').hidden,false);
  assert.equal(flow.exportRules(),false);
});
