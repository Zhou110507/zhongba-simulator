const {test}=require('node:test');
const assert=require('node:assert/strict');
const {contactGuide}=require('../web/shot-guide.js');
const ball=(id,x,y)=>({id,position:{x,y},spec:{radius:.03}});
const base=()=>({status:'stopped',initial:[ball('cue',0,0),ball('1',1,0)],final:[ball('cue',.4,0)],events:[]});
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
