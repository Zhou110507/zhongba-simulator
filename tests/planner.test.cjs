'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');

async function harness({deferStart=false}={}){
  const nodes=new Map();
  function element(tag='div'){
    return {tag,value:'',children:[],disabled:false,hidden:false,dataset:{},style:{},checked:false,options:[],
      append(...v){this.children.push(...v);},
      replaceChildren(...v){this.children=v;if(this.tag==='select'){this.options=v;this.value=v[0]?.value||'';}},
      querySelectorAll(selector){const all=this.children.flatMap(c=>[c,...c.querySelectorAll(selector)]);return all.filter(c=>selector==='button'&&c.tag==='button');}};
  }
  const $=id=>{if(!nodes.has(id))nodes.set(id,element(id==='plan-target'?'select':'div'));return nodes.get(id);};
  for(const [id,v] of Object.entries({'plan-x':'700','plan-y':'600','plan-radius':'60','plan-banks':'2','plan-seconds':'12'}))$(id).value=v;
  const calls=[];let resolveStart,rules=false,previews=0;
  const scene={model_signature:'model-a',balls:[{id:'cue',position:{x:.5,y:.5},pocket:null},{id:'1',position:{x:1,y:.5},pocket:null}],shot:{angle_deg:0,cue_speed:1,tip_x:0,tip_y:0}};
  const answer={shot:{angle_deg:1,cue_speed:2,tip_x:0,tip_y:-.4},inside:true,error_m:.01,cue_final:{x:.7,y:.6},target_pocket:null,cue_cushions:0,cue_ball_contacts:1,verified:true,launch_speed:1.8,perturbations:null};
  const result={status:'found',solutions:[answer],evaluations:20,elapsed:1,model_signature:'model-a'};
  const c={window:{TableModes:{isRules:()=>rules}},document:{createElement:element},$,scene:structuredClone(scene),config:{limits:{max_cue_speed:5}},busy:false,fired:false,record:null,cachedKey:'',ctx:{},pocketNames:{},clone:structuredClone,
    active:b=>b.pocket==null,cueBall:()=>c.scene.balls[0],locked:()=>c.fired,draw(){},
    setTimeout(){return 1;},clearTimeout(){},
    setScene(next){c.scene=next;c.window.ShotPlanner.refresh();},calculate:async()=>{previews++;c.record={complete:true};c.cachedKey=JSON.stringify(c.scene);},
    api:async(path,data)=>{calls.push({path,data});if(path.endsWith('/start'))return deferStart?await new Promise(r=>resolveStart=r):{id:'job-a'};if(path.endsWith('/status'))return {id:'job-a',status:'found',result};return {};},
  };
  vm.createContext(c);vm.runInContext(fs.readFileSync('web/planner.js','utf8'),c);await Promise.resolve();
  return {c,$,calls,flow:c.window.ShotPlanner,answer,resolve:v=>resolveStart(v),rules:v=>rules=v,previews:()=>previews};
}

test('late start response after a layout edit is cancelled and never polled',async()=>{
  const h=await harness({deferStart:true});const pending=h.$('plan-start').onclick();
  h.c.scene.balls[0].position.x=.6;h.flow.refresh();h.resolve({id:'late-job'});await pending;
  assert.ok(h.calls.some(v=>v.path==='/api/plan/cancel'&&v.data.id==='late-job'));
  assert.equal(h.calls.some(v=>v.path==='/api/plan/status'),false);
  assert.equal(h.$('plan-results').children.length,0);
});

test('applying a verified solution preserves every ball and calls normal preview',async()=>{
  const h=await harness();await h.$('plan-start').onclick();await Promise.resolve();
  const balls=structuredClone(h.c.scene.balls),card=h.$('plan-results').children[0];
  assert.ok(card);await card.children.find(v=>v.tag==='button').onclick();
  assert.deepEqual(h.c.scene.balls,balls);assert.deepEqual(h.c.scene.shot,h.answer.shot);assert.equal(h.previews(),1);
});

test('goal edits and subsequent layout edits invalidate recommendation controls',async()=>{
  const h=await harness();await h.$('plan-start').onclick();await Promise.resolve();
  assert.equal(h.$('plan-results').children.length,1);
  h.$('plan-radius').value='80';h.$('plan-radius').onchange();assert.equal(h.$('plan-results').children.length,0);
  await h.$('plan-start').onclick();await Promise.resolve();assert.equal(h.$('plan-results').children.length,1);
  h.c.scene.balls[1].position.y=.6;h.flow.refresh();assert.equal(h.$('plan-results').children.length,0);
});

test('entering rule mode cancels a pending start and hides free planner',async()=>{
  const h=await harness({deferStart:true}),pending=h.$('plan-start').onclick();h.rules(true);h.flow.refresh();
  assert.equal(h.$('planner-panel').hidden,true);h.resolve({id:'late-job'});await pending;
  assert.ok(h.calls.some(v=>v.path==='/api/plan/cancel'&&v.data.id==='late-job'));
});
