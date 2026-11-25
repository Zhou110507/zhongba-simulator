'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
global.window=global;global.ArenaMath=require('../web/arena-camera');
for(const module of ['cue-visual','arena-table','arena-cue','arena-renderer'])require('../web/'+module);
const configs=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c',
  "from billiards.play import PlayService;import json;print(json.dumps([PlayService().config(),PlayService(table_profile='cbsa_2017').config()]))"],{encoding:'utf8',maxBuffer:8e6}));
const {dot,sub,cross,add,mul}=ArenaMath;
const near=(a,b,e=1e-7)=>assert.ok(Math.abs(a-b)<e,`expected ${a} within ${e} of ${b}`);
function intersections(mesh,O,D,material){
  const data=mesh.data,hit=[];
  for(let i=0;i<data.length;i+=30){
    if(data[i+9]!==material)continue;
    const a=data.slice(i,i+3),ab=sub(data.slice(i+10,i+13),a),ac=sub(data.slice(i+20,i+23),a);
    const h=cross(D,ac),det=dot(ab,h);if(Math.abs(det)<1e-12)continue;
    const t=sub(O,a),u=dot(t,h)/det,q=cross(t,ab),v=dot(D,q)/det,s=dot(ac,q)/det;
    if(u>=-1e-8&&v>=-1e-8&&u+v<=1+1e-8&&s>1e-7)hit.push(s);
  }
  return hit.sort((a,b)=>a-b);
}
for(const c of configs)test('actual mesh widths, rounded jaw seams and open shelf on '+c.model_signature,()=>{
  const t=ArenaRenderer.table(c);assert.equal(t.pockets.length,6);
  for(const pocket of c.geometry.pockets){
    const {x,y}=pocket.mouth,o=[pocket.outward.x,pocket.outward.y,0],across=[pocket.tangent.x,pocket.tangent.y,0];
    // Measure the rendered nose, separately on both sides, in a transverse section 4 mm behind the throat.
    const station=add([x,y,.032],mul(o,.004)),side=Math.abs(o[0])<.1,expected=side?.086:.084;
    const left=intersections(t.mesh,station,across,10)[0],right=intersections(t.mesh,station,mul(across,-1),10)[0];
    near(left,expected/2);near(right,expected/2);
    const f=[pocket.fall_center.x,pocket.fall_center.y,0],r=pocket.fall_radius;
    const clothAt=p=>intersections(t.mesh,[p[0],p[1],.1],[0,0,-1],1).length>0;
    assert.ok(clothAt(add(f,mul(o,-r-.0002))));assert.ok(!clothAt(add(f,mul(o,-r+.0002))));
    assert.equal(intersections(t.mesh,[x,y,.15],[0,0,-1],4).filter(s=>s<.15).length,0,'open front, no leather bridge');
    for(const jaw of t.pockets.find(s=>s.id===pocket.id).jaws){
      near(Math.hypot(jaw.arc[0].p[0]-jaw.rail.q[0],jaw.arc[0].p[1]-jaw.rail.q[1]),0);
      near(dot([...jaw.arc[0].n,0],[...jaw.rail.n,0]),1);
      assert.ok(jaw.arc.length>=12); // rounded outline with an actual tangency station
    }
  }
});
const R=.028575,ball=(id,x,y)=>({id,position:{x,y},spec:{radius:R},pocket:null});
const shot=(angle,tx=0,ty=0,speed=2.6)=>({angle_deg:angle,tip_x:tx,tip_y:ty,cue_speed:speed});
const obstacles=ArenaRenderer.table(configs[1]).obstacles;
function checkShaft(position,axis,balls){
  const rear=mul(axis.slice(0,3),-1);
  for(let i=0;i<=860;i++){
    const s=(ArenaCue.length-ArenaCue.tip)*i/860,p=add(position,mul(rear,s)),r=ArenaCue.radius(s);
    assert.ok(p[2]-r>=-1e-7);
    for(const b of balls)if(!b.pocket){
      const C=[b.position.x,b.position.y,b.spec.radius];
      assert.ok(Math.hypot(...sub(p,C))-r-b.spec.radius>=-1e-7,'shaft / '+b.id);
    }
  }
}
test('full swept taper clears near rails and object balls while reaching the selected point',()=>{
  for(const [qx,qy,angle,tx,ty,object] of [
    [.07,.64,0,0,0],[1.61,.073,90,.25,.1],[1.05,.68,15,0,.21,[.84,.62]],
    [.09,.08,49,-.3,.19],[2.46,.67,180,.15,0],[1.24,1.18,268,0,.25],[1.27,.08,90,0,.14],
  ]){
    const cue=ball('cue',qx,qy),s=shot(angle,tx,ty),balls=[cue];if(object)balls.push(ball('1',...object));
    const p=ArenaCue.plan(cue,s,balls,obstacles);assert.ok(!p.blocked);assert.ok(p.elevation>0);
    near(Math.hypot(...sub(p.origin,[qx,qy,R])),R+ArenaCue.tip);
    for(const elapsed of [0,430,830,925,1180,1380,1453,CueVisual.pose(0,s.cue_speed).impact]){
      const stroke=CueVisual.pose(elapsed,s.cue_speed),v=ArenaCue.frame(p,stroke,balls,obstacles);
      checkShaft(v.position,v.axis,balls);
      // Independently test every surface vertex of the transformed shaft against the modelled solids.
      const rear=mul(v.axis.slice(0,3),-1);
      for(let s=0;s<ArenaCue.length;s+=.003){
        const P=add(v.position,mul(rear,s)),r=ArenaCue.radius(s);
        if(P[2]-r>.045)continue;
        for(const o of obstacles){
          if(P[0]<o.x0-r||P[0]>o.x1+r||P[1]<o.y0-r||P[1]>o.y1+r)continue;
          for(let i=0;i<16;i++){
            const theta=i*Math.PI/8,V=add(P,add(mul(v.axis.slice(3,6),r*Math.cos(theta)),mul(v.axis.slice(6,9),r*Math.sin(theta))));
            if(V[2]>=o.top)continue;
            const sides=o.points.map((a,k)=>{const b=o.points[(k+1)%o.points.length];return (b[0]-a[0])*(V[1]-a[1])-(b[1]-a[1])*(V[0]-a[0]);});
            assert.ok(sides.some(z=>z<0)&&sides.some(z=>z>0),'shaft inside fitted table part');
          }
        }
      }
    }
  }
});
test('frozen rear blocker displays a raised safe rest and a new direction opens a stroke',()=>{
  const cue=ball('cue',1.30,.60),blocker=ball('7',1.30-2*R-.0001,.60),balls=[cue,blocker],p=ArenaCue.plan(cue,shot(0),balls,obstacles);
  assert.ok(p.blocked);const v=ArenaCue.frame(p,{gap:.018},balls,obstacles);checkShaft(v.position,v.axis,balls);
  assert.equal(ArenaCue.plan(cue,shot(90),balls,obstacles).blocked,false);
});
test('slow, stopped, rebounding and pocketed live balls bound the follow-through',()=>{
  const cue=ball('cue',1.5,.62),s=shot(0),p=ArenaCue.plan(cue,s,[cue],obstacles);
  for(const progress of [0,.0002,.004,.014,.035,.070,-.004,-.018]){
    const live=ball('cue',1.5+progress,.62),v=ArenaCue.frame(p,{gap:-.053,phase:'follow-through'},[live],obstacles);
    checkShaft(v.position,v.axis,[live]);
    if(progress===.070)assert.ok(v.position[0]>p.origin[0]+.049);
    if(!progress)near(v.position[0],p.origin[0],.0001);
  }
  const gone={...cue,pocket:'top-middle'},moving=ball('3',1.26,.62);
  checkShaft(...Object.values(ArenaCue.frame(p,{gap:-.052,phase:'follow-through'},[gone,moving],obstacles)),[moving]);
});
test('continuous cylindrical grain and pointed wood splice share a metric texture',()=>{
  const t=ArenaCue.woodTexture(),sample=(x,y)=>t.bytes[(y*t.width+x)*3],cache=ArenaCue.woodTexture();assert.equal(t,cache);
  let along=0,around=0,seam=0;for(let x=25;x<590;x+=3){for(let y=0;y<t.height;y++){
    along+=Math.abs(sample(x+1,y)-sample(x,y));around+=Math.abs(sample(x,(y+1)%t.height)-sample(x,y));}
    seam+=Math.abs(sample(x,0)-sample(x,t.height-1));}
  assert.ok(around>along*2);assert.ok(seam<around/t.height*3);
  const spliceAt=Math.floor(1.14/ArenaCue.length*t.width),swatches=Array.from({length:t.height},(_,y)=>sample(spliceAt,y));
  assert.ok(Math.min(...swatches)<120&&Math.max(...swatches)>175);
});
