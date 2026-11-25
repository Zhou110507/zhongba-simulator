'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {Camera}=require('../web/arena-camera');
const table={length:2.54,width:1.27},R=.028575,rad=Math.PI/180;
const screens=[[1440,600],[390,278],[390,844]],zooms=[.65,1,2.1];
const ball=(id,x,y)=>({id,position:{x,y},spec:{radius:R},pocket:null});
const plus=(a,b,d=1)=>a.map((v,i)=>v+b[i]*d),minus=(a,b)=>a.map((v,i)=>v-b[i]);
const scaled=(v,s)=>v.map(x=>x*s),norm=a=>scaled(a,1/Math.hypot(...a));
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
function near(a,b,eps=1e-8){assert.ok(Math.abs(a-b)<eps,`${a} differs from ${b} by ${Math.abs(a-b)}`);}
function shotFrame(c,screen,position,angle){return c.frame(...screen,table,position,{angle_deg:angle},R);}
function basisOf(f){return [...f.eye,...f.forward,...f.right,...f.up,f.lens,f.ortho];}
function sampleSilhouette(f,C,r){
  // Independent world-space construction: points of tangency form a circle in a plane normal
  // to the eye-centre line. Project that circle; no horizontal/vertical image-bound formula is used.
  const toEye=minus(f.eye,C),distance=Math.hypot(...toEye),axis=f.ortho?scaled(f.forward,-1):norm(toEye);
  const circleCenter=plus(C,axis,f.ortho?0:r*r/distance),size=f.ortho?r:r*Math.sqrt(1-(r/distance)**2);
  const u=norm(cross(axis,Math.abs(axis[2])>.9?[1,0,0]:[0,0,1])),v=cross(axis,u);
  const bounds={x0:Infinity,y0:Infinity,x1:-Infinity,y1:-Infinity};
  for(let i=0;i<1024;i++){
    const a=2*Math.PI*i/1024,p=f.project(plus(plus(circleCenter,u,size*Math.cos(a)),v,size*Math.sin(a)));
    bounds.x0=Math.min(bounds.x0,p.x);bounds.x1=Math.max(bounds.x1,p.x);
    bounds.y0=Math.min(bounds.y0,p.y);bounds.y1=Math.max(bounds.y1,p.y);
  }
  return bounds;
}
test('cue-ball framing and straight-sight alignment hold at the table edges and every zoom stop',()=>{
  for(const position of [{x:R,y:R},{x:2.54-R,y:1.27-R},{x:1.27,y:.635}]){
    for(const angle of [0,41,147,225,301])for(const screen of screens)for(const zoom of zooms){
      for(const deltaY of [0,-2000,2000]){
        const camera=new Camera();camera.select('cue');camera.zoom=zoom;
        camera.raise(deltaY,screen[1]);
        const f=shotFrame(camera,screen,position,angle),C=[position.x,position.y,R],white=f.project(C);
        const b=f.projectedSphere(C,R);
        assert.ok(b.x0>0&&b.y0>0&&b.x1<screen[0]&&b.y1<screen[1]);
        near(white.x,screen[0]/2);
        assert.ok(white.y>screen[1]*.55&&white.y<screen[1]*.85);
        let previous=white.y;
        for(const d of [.07,.4,1.1,2.4]){
          const p=f.project([C[0]+d*Math.cos(angle*rad),C[1]+d*Math.sin(angle*rad),R]);
          near(p.x,white.x);assert.ok(p.y<previous);previous=p.y;
        }
      }
    }
  }
});
test('switching cameras preserves each framing; orbit and optical zoom leave the orbit radius fixed',()=>{
  const camera=new Camera(),cue={x:.43,y:.25},screen=[1130,543],frame=()=>shotFrame(camera,screen,cue,17);
  const radius=f=>Math.hypot(f.eye[0]-table.length/2,f.eye[1]-table.width/2)/Math.hypot(f.forward[0],f.forward[1]);
  const d=radius(frame());
  for(const zoom of zooms){camera.zoom=zoom;for(const [x,y] of [[65,10],[-420,160],[610,-88],[0,-240]]){
    camera.orbit(x,y);near(radius(frame()),d);
  }}
  const saved=new Map();
  for(const [mode,zoom] of [['orbit',1.19],['cue',1.61],['top',.74]]){
    camera.select(mode);camera.zoom=zoom;if(mode==='cue')camera.raise(91,543);
    saved.set(mode,basisOf(frame()));
  }
  for(const mode of ['cue','orbit','top','cue']){camera.select(mode);assert.deepEqual(basisOf(frame()),saved.get(mode));}
});
test('software sphere bounds agree with the projected tangent contour, including viewport corners',()=>{
  const camera=new Camera(),cue={x:.50,y:.45};
  for(const mode of ['orbit','cue','top'])for(const screen of screens){
    camera.select(mode);
    for(const zoom of [.65,2.1]){
      camera.zoom=zoom;const f=shotFrame(camera,screen,cue,33);
      for(const [sx,sy,depth] of [[-.94,.88,1.1],[.97,-.86,.57],[.0,.0,1.8],[1.05,.09,.48]]){
        const x=(f.ortho||depth/f.lens)*f.aspect*sx,y=(f.ortho||depth/f.lens)*sy;
        const C=plus(plus(plus(f.eye,f.forward,depth),f.right,x),f.up,y),bounds=f.projectedSphere(C,R);
        const expected=sampleSilhouette(f,C,R);
        for(const k of Object.keys(expected))near(bounds[k],expected[k],.003);
      }
      assert.equal(f.projectedSphere(plus(f.eye,f.forward,-.2),R),null);
    }
  }
});
test('a ray chooses the front live ball, accepts thin cuts and leaves open cloth selectable',()=>{
  const camera=new Camera(),cue=ball('cue',.2,.61),front=ball('2',1.16,.61),rear=ball('4',1.27,.61);
  camera.select('cue');camera.raise(-2000,480);
  const sight=shotFrame(camera,[967,480],cue.position,0),rp=sight.project([rear.position.x,rear.position.y,R]);
  assert.equal(sight.hitBall(rp.x,rp.y,[rear,front]),front);
  assert.equal(sight.hitBall(rp.x,rp.y,[{...front,pocket:'side'},rear]),rear);
  for(const mode of ['cue','top','orbit']){
    camera.select(mode);const f=shotFrame(camera,[967,480],cue.position,0),C=[rear.position.x,rear.position.y,R];
    const cut=f.project(plus(C,f.right,R*.96));
    assert.equal(f.hitBall(cut.x,cut.y,[rear]),rear);
    const picked=f.pick(cut.x,cut.y,R);
    near(picked.x,C[0]+f.right[0]*R*.96);near(picked.y,C[1]+f.right[1]*R*.96);
    const open=f.project([1.45,.75,0]);assert.equal(f.hitBall(open.x,open.y,[front,rear]),null);
    const cloth=f.pick(open.x,open.y,0);near(cloth.x,1.45);near(cloth.y,.75);
  }
});
test('a CSS drag at any pixel density has the bearing of a measured lateral move one metre ahead',()=>{
  const c=new Camera();c.select('cue');const position={x:1.1,y:.4},angle=31;
  for(const [w,h] of screens)for(const zoom of zooms){
    c.zoom=zoom;let gain;
    for(const dpr of [1,1.25,2,3]){
      const f=shotFrame(c,[w*dpr,h*dpr],position,angle);
      const ahead=[position.x+Math.cos(angle*rad),position.y+Math.sin(angle*rad),R];
      for(const delta of [-.08,.035]){
        const p=f.project(ahead),point=plus(ahead,f.right,delta),q=f.project(point);
        const bearing=Math.atan2(point[1]-position.y,point[0]-position.x)/rad;
        near(f.aimDrag((q.x-p.x)/dpr,0,w,h),bearing-angle);
      }
      const result=f.aimDrag(9,0,w,h);
      if(gain!==undefined)near(result,gain);gain=result;
      near(f.aimDrag(0,45,w,h),0);
    }
  }
});
