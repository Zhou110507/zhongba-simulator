'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(){
  const calls=[],gradient={addColorStop(){}};
  const g=new Proxy({createLinearGradient:()=>gradient},{get(o,k){return k in o?o[k]:(...args)=>calls.push([k,...args]);}});
  const c={window:{},document:{createElement:()=>({getContext:()=>g})}};
  vm.createContext(c);vm.runInContext(fs.readFileSync('web/cue-visual.js','utf8'),c);
  return {cue:c.window.CueVisual,g,calls};
}

test('cue and taper use world metres at different table scales, without shortening to fit',()=>{
  const {cue,g,calls}=harness(),ball={position:{x:1.5,y:.6},spec:{radius:.028575}},shot={angle_deg:0,tip_x:0,tip_y:0};
  for(const scale of [250,560]){
    cue.draw(g,{scale,X:x=>x*scale,Y:y=>-y*scale},ball,shot);
    const draw=calls.filter(c=>c[0]==='drawImage').at(-1);
    assert.equal(draw[8],1.475*scale);assert.equal(draw[9],76/1600*scale);
  }
  assert.equal(cue.tipDiameter,.00975);assert.equal(cue.buttDiameter,.029);
});

test('selected right-side tip offset matches the physical cue orientation',()=>{
  const {cue,g,calls}=harness();cue.draw(g,{scale:1000,X:x=>x*1000,Y:y=>-y*1000},
    {position:{x:1,y:.6},spec:{radius:.028575}},{angle_deg:0,tip_x:.25,tip_y:0},{gap:0});
  const translate=calls.find(c=>c[0]==='translate');assert.ok(translate[2]>-600);
});

for(const speed of [.25,1.1,3.2,5])test(`balls stay still until tip contact, with one continuous replay clock at ${speed} m/s`,()=>{
  const {cue}=harness(),state=cue.begin(speed),impact=cue.pose(0,speed).impact;
  let replay=0;
  for(let i=0;i<Math.floor(impact/10);i++){
    const frame=cue.advance(state,.01);replay+=frame.replayDelta;
    assert.equal(replay,0);assert.ok(frame.gap>=0);
  }
  const contact=cue.pose(impact,speed);assert.equal(contact.phase,'follow-through');assert.ok(Math.abs(contact.gap)<1e-12);
  for(let i=0;i<50;i++)replay+=cue.advance(state,.01).replayDelta;
  assert.ok(Math.abs(replay-(state.elapsed-impact)/1000)<1e-9);
  assert.ok(cue.pose(state.elapsed,speed).finished);
});

test('actual app tick pauses the cue and physical clock together and completes once',()=>{
  const {cue}=harness();let finished=0;
  const source=fs.readFileSync('web/app.js','utf8');
  const c={CueVisual:cue,cueStroke:cue.begin(2),playing:true,record:{result:{duration:1}},
    time:0,lastFrame:0,animationFrame:0,lastUiFrame:0,$:()=>({value:'1'}),
    requestAnimationFrame:()=>1,refreshUI(){},draw(){},announce(){},
    reportFinish(){finished++;c.playing=false;}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function requestFrame()'),source.indexOf('async function boot()')),c);
  c.tick(100);c.tick(200);assert.equal(c.time,0);const held=c.cueStroke.elapsed;
  c.playing=false;c.tick(500);assert.equal(c.cueStroke.elapsed,held);assert.equal(c.time,0);
  c.playing=true;
  for(let now=600;now<5000;now+=100)c.tick(now);
  assert.equal(c.time,1);assert.equal(finished,1);assert.equal(c.cueStroke,null);
});

test('changing the scene cancels an in-progress cue without finishing the old shot',()=>{
  const {cue}=harness(),source=fs.readFileSync('web/app.js','utf8');
  const c={cueStroke:cue.begin(2),clearTimeout(){},launchTimer:null,guideController:null,
    guideRecord:null,guideKey:'old',revision:4,requestNumber:3,requestController:null,busy:false,
    record:{},trailSource:null,trailLayer:null,cachedKey:'old',fired:true,playing:true,time:0,
    finishedAnnounced:false,eventRows:[],$:()=>({textContent:''})};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function invalidate()'),source.indexOf('function syncShotControls()')),c);
  c.invalidate();assert.equal(c.cueStroke,null);assert.equal(c.playing,false);
  assert.equal(c.fired,false);assert.equal(c.record,null);assert.equal(c.revision,5);
});
