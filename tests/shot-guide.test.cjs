const {test}=require('node:test');
const assert=require('node:assert/strict');
const {contactGuide,aimDirection,instantGuide}=require('../web/shot-guide.js');
const ball=(id,x,y)=>({id,position:{x,y},spec:{radius:.03}});
const base=()=>({status:'stopped',initial:[ball('cue',0,0),ball('1',1,0)],final:[ball('cue',.4,0)],events:[]});

test('direction remains available for every angle before any async result exists',()=>{
 for(const angle of [0,.5,45,90,180,270,359.9]){
  const cue=ball('cue',.5,.6),line=aimDirection(cue,angle,{length:2.54,width:1.26});
  const dx=line.end.x-.5,dy=line.end.y-.6;
  assert.ok(Number.isFinite(dx)&&Number.isFinite(dy)&&Math.hypot(dx,dy)>.5);
  assert.ok(Math.abs(dx*Math.sin(angle*Math.PI/180)-dy*Math.cos(angle*Math.PI/180))<1e-10);
  assert.equal(line.radius,undefined);assert.equal(line.contact,undefined);
 }
});
test('uses recorded CCD centre, with the contact point distinct from the ghost centre',()=>{
 const result=base();result.events=[{kind:'ball_ball',actors:['cue','1'],time:.7,before:[ball('cue',.94,0),ball('1',1,0)]}];
 const guide=contactGuide(result);assert.deepEqual(guide.center,{x:.94,y:0});assert.ok(Math.abs(guide.contact.x-.97)<1e-12);assert.equal(guide.radius,.03);
});
test('a short shot ends at its actual stop without a fabricated target ghost',()=>{
 const guide=contactGuide(base());assert.equal(guide.kind,'stop');assert.deepEqual(guide.center,{x:.4,y:0});assert.equal(guide.contact,null);
});
test('a cushion before a ball takes precedence and exposes the actual cushion contact',()=>{
 const result=base();result.events=[{kind:'ball_cushion',actors:['cue'],detail:'top',time:.2,before:[ball('cue',.2,.97)]},{kind:'ball_ball',actors:['cue','1'],time:.7,before:[ball('cue',.94,0),ball('1',1,0)]}];
 const guide=contactGuide(result,{surfaces:[{id:'top',start:{x:0,y:1},end:{x:1,y:1},radius:0}]});assert.equal(guide.kind,'ball_cushion');assert.deepEqual(guide.contact,{x:.2,y:1});
});
test('crossing a pocket plane is not mislabeled as a ball collision',()=>{
 const result=base();result.events=[{kind:'ball_pocket',actors:['cue'],time:.5,before:[ball('cue',1.2,-.08)]}];assert.equal(contactGuide(result).kind,'ball_pocket');
});

const instantModel={cue:{effective_mass:.5,restitution:.75},physics:{gravity:9.81,sliding_friction:.18,rolling_friction:.007},table:{length:2.54,width:1.26}};
const instantScene=speed=>({balls:[{...ball('cue',.2,.6),spec:{radius:.028575,mass:.163}},{...ball('1',1.2,.6),spec:{radius:.028575,mass:.163}}],shot:{angle_deg:0,cue_speed:speed,tip_x:0,tip_y:0}});
test('moving onto a target immediately returns a tangible ghost before the engine responds',()=>{
 const guide=instantGuide(instantScene(2),instantModel,{surfaces:[],pockets:[]});
 assert.equal(guide.kind,'ball_ball');assert.equal(guide.provisional,true);
 assert.ok(Math.abs(guide.center.x-(1.2-.05715))<1e-10);
 assert.ok(Math.abs(guide.contact.x-(1.2-.028575))<1e-10);
});
test('instant ghost respects stopping distance at low power',()=>{
 const guide=instantGuide(instantScene(.05),instantModel,{surfaces:[],pockets:[]});
 assert.equal(guide.kind,'stop');assert.ok(guide.center.x<.3);assert.equal(guide.contact,null);
});
test('instant ghost does not target a ball through a cushion',()=>{
 const guide=instantGuide(instantScene(2),instantModel,{surfaces:[{id:'wall',start:{x:.8,y:0},end:{x:.8,y:1.26},radius:0}],pockets:[]});
 assert.equal(guide.kind,'ball_cushion');assert.ok(Math.abs(guide.center.x-(.8-.028575))<1e-10);assert.ok(Math.abs(guide.contact.x-.8)<1e-10);
});
