'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {Camera,BallRotation}=require('../web/arena-camera.js');
const table={length:2.54,width:1.27},cue={x:.48,y:.635},shot={angle_deg:0};
function near(a,b){assert.ok(Math.abs(a-b)<1e-9);}
for(const mode of ['orbit','cue','top'])test(mode+' projection inverts clicks on cloth and ball centres',()=>{
  const c=new Camera();c.select(mode);
  for(const [w,h] of [[980,490],[375,310],[650,960]])for(const angle of [0,53,179,271]){
    const f=c.frame(w,h,table,cue,{angle_deg:angle});
    for(const z of [0,.028575]){const p=[cue.x+.08,cue.y+.03,z],q=f.project(p),back=f.pick(q.x,q.y,z);near(back.x,p[0]);near(back.y,p[1]);}
  }
});
test('the default framing includes all corners on desktop and mobile',()=>{
  const c=new Camera();
  for(const [w,h] of [[1050,490],[369,285],[680,1024]])for(const mode of ['orbit','top']){
    c.select(mode);const f=c.frame(w,h,table,cue,shot);
    for(const x of [-.14,table.length+.14])for(const y of [-.14,table.width+.14]){
      const p=f.project([x,y,.05]);assert.ok(p.x>=0&&p.x<=w&&p.y>=0&&p.y<=h);
    }
  }
});
test('time seeking and camera redraws preserve rotation',()=>{
  const b={omega:{x:0,y:2,z:1}},m={angular_acceleration:{x:0,y:0,z:0}};
  const t=new BallRotation({initial:[b],segments:[0,1,2].map(start=>({start,end:start+1,balls:[b],motion:[m]}))});
  const a=t.at(1.23)[0];t.at(2.99);t.at(.21);assert.deepEqual(t.at(1.23)[0],a);near(Math.hypot(...a),1);assert.notDeepEqual(a,[0,0,0,1]);
});
