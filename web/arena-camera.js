'use strict';
(function(root){
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const add=(a,b)=>a.map((v,i)=>v+b[i]),sub=(a,b)=>a.map((v,i)=>v-b[i]),mul=(a,k)=>a.map(v=>v*k);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const unit=a=>mul(a,1/(Math.hypot(...a)||1)),clamp=(n,lo,hi)=>Math.max(lo,Math.min(hi,n));
  const NEAR=.03, DEG=Math.PI/180;
  const overview={azimuth:-1.92,pitch:.80,fov:27},cueView={back:.98,height:.245,fov:32,screenY:.71};
  function direction(yaw,pitch){
    const forward=[-Math.cos(yaw)*Math.cos(pitch),-Math.sin(yaw)*Math.cos(pitch),-Math.sin(pitch)];
    const right=[-Math.sin(yaw),Math.cos(yaw),0];
    return {forward,right,up:cross(right,forward)};
  }
  // Establish the overview distance once per table/aspect. Orbiting never drives the camera in and out.
  function overviewDistance(table,aspect,lens,top){
    const target=[table.length/2,table.width/2,top?0:-.1];
    const {right,up,forward}=direction(top?-Math.PI/2:overview.azimuth,top?Math.PI/2:overview.pitch);
    let distance=0;
    for(const x of [-.16,table.length+.16])for(const y of [-.16,table.width+.16])for(const z of [-.23,.055]){
      const d=sub([x,y,z],target),extent=lens*Math.max(Math.abs(dot(d,right))/aspect,Math.abs(dot(d,up)));
      distance=Math.max(distance,extent*1.14-(top?0:dot(d,forward)));
    }
    return distance;
  }
  class Camera {
    constructor(){
      this.mode='orbit';this.azimuth=overview.azimuth;this.pitch=overview.pitch;
      this.cueHeight=cueView.height;this.zooms={orbit:1,top:1,cue:1};
    }
    get zoom(){return this.zooms[this.mode];}
    set zoom(value){this.zooms[this.mode]=clamp(value,.65,2.1);}
    select(mode){if(Object.hasOwn(this.zooms,mode))this.mode=mode;}
    orbit(dx,dy){if(this.mode!=='orbit')return;this.azimuth-=dx*.007;this.pitch=clamp(this.pitch+dy*.005,.24,1.48);}
    magnify(factor){this.zoom*=factor;}
    raise(dy,height){if(this.mode==='cue'&&height>0)this.cueHeight=clamp(this.cueHeight+.45*dy/height,.15,.39);}
    frame(width,height,table,cue,shot,radius=.028575){
      const aspect=width/height,top=this.mode==='top',sighting=this.mode==='cue';
      const baseLens=1/Math.tan((sighting?cueView.fov:overview.fov)*DEG/2);
      const lens=baseLens*(top?1:this.zoom);
      const yaw=sighting?shot.angle_deg*DEG+Math.PI:top?-Math.PI/2:this.azimuth;
      let pitch=top?Math.PI/2:this.pitch;
      if(sighting){
        // Keep the eye fixed relative to the cue ball. Tilt the optical axis just enough to
        // keep its centre at the same screen height while changing focal length or eye height.
        const down=Math.atan2(this.cueHeight-radius,cueView.back);
        pitch=down-Math.atan((2*cueView.screenY-1)/lens);
      }
      const {forward,right,up}=direction(yaw,pitch);
      let eye,ortho=0;
      if(sighting){
        eye=[cue.x+cueView.back*Math.cos(yaw),cue.y+cueView.back*Math.sin(yaw),this.cueHeight];
      }else{
        const target=[table.length/2,table.width/2,top?0:-.1],distance=overviewDistance(table,aspect,baseLens,top);
        eye=sub(target,mul(forward,distance));if(top)ortho=distance/(baseLens*this.zoom);
      }
      const project=point=>{
        const d=sub(point,eye),depth=dot(d,forward);if(depth<=NEAR)return null;
        const scale=height/2/(ortho||depth/lens);
        return {x:width/2+dot(d,right)*scale,y:height/2-dot(d,up)*scale,depth};
      };
      function rayAt(x,y){
        const screen=add(mul(right,(2*x/width-1)*aspect),mul(up,1-2*y/height));
        return ortho?{origin:add(eye,mul(screen,ortho)),ray:forward}:{origin:eye,ray:add(forward,mul(screen,1/lens))};
      }
      const pick=(x,y,z=0)=>{
        const {origin,ray}=rayAt(x,y);if(Math.abs(ray[2])<1e-9)return null;
        const t=(z-origin[2])/ray[2];return t>NEAR?{x:origin[0]+t*ray[0],y:origin[1]+t*ray[1]}:null;
      };
      function hitBall(x,y,balls){
        const {origin,ray}=rayAt(x,y),a=dot(ray,ray);let found=null,best=Infinity;
        for(const b of balls){
          if(b.pocket)continue;
          const r=b.spec.radius,to=sub([b.position.x,b.position.y,r],origin),along=dot(ray,to);
          const disc=along*along-a*(dot(to,to)-r*r);if(disc<0)continue;
          const t=(along-Math.sqrt(disc))/a;
          if(t>NEAR&&t<best){found=b;best=t;}
        }
        return found;
      }
      function projectedSphere(center,r){
        const d=sub(center,eye),z=dot(d,forward),X=dot(d,right),Y=dot(d,up);
        if(z+r<=NEAR)return null;
        if(!ortho&&z-r<=NEAR)return {x0:0,x1:width-1,y0:0,y1:height-1};
        const scale=height/2/(ortho||1/lens);
        // Where the rays through each pair of silhouette tangents hit the image plane.
        function range(t){
          if(ortho)return [t-r,t+r];
          const den=z*z-r*r,k=r*Math.sqrt(den+t*t);return [(t*z-k)/den,(t*z+k)/den];
        }
        const [lx,hx]=range(X),[ly,hy]=range(Y);
        return {x0:width/2+lx*scale,x1:width/2+hx*scale,y0:height/2-hy*scale,y1:height/2-ly*scale};
      }
      function aimDrag(dx,dy,cssWidth,cssHeight){
        if(!sighting||!cssWidth||!cssHeight)return 0;
        // Measure one metre down the shot line. At that depth this drag moves the aiming line
        // to the cursor; the angular gain follows the rendered focal length and CSS pixel scale.
        const ahead=[cue.x-Math.cos(yaw),cue.y-Math.sin(yaw),radius],ref=project(ahead);
        const metresPerPixel=2*ref.depth/(lens*height);
        return -Math.atan(dx*width/cssWidth*metresPerPixel)/DEG;
      }
      return {width,height,aspect,eye,right,up,forward,lens,ortho,project,pick,hitBall,projectedSphere,aimDrag};
    }
  }
  const identity=[0,0,0,1];
  function product(a,b){
    return [a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1],a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0],
      a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3],a[3]*b[3]-dot(a,b)];
  }
  function advance(q,omega,accel,dt){
    const v=['x','y','z'].map(k=>(omega[k]+.5*accel[k]*dt)*dt),a=Math.hypot(...v);
    return a<1e-9?q:unit(product([...mul(v,Math.sin(a*.5)/a),Math.cos(a*.5)],q));
  }
  class BallRotation{
    constructor(result){this.result=result;this.starts=[result.initial.map(()=>identity)];}
    step(i,dt){const s=this.result.segments[i];return s.balls.map((b,j)=>advance(this.starts[i][j],b.omega,s.motion[j].angular_acceleration,dt));}
    at(t){
      const seg=this.result.segments;if(!seg.length)return this.starts[0];
      let lo=0,hi=seg.length;while(lo+1<hi){const mid=(lo+hi)>>>1;if(seg[mid].start<=t)lo=mid;else hi=mid;}
      while(this.starts.length<=lo){const i=this.starts.length-1;this.starts.push(this.step(i,seg[i].end-seg[i].start));}
      return this.step(lo,clamp(t-seg[lo].start,0,seg[lo].end-seg[lo].start));
    }
  }
  const api={Camera,BallRotation,identity,add,sub,mul,dot,cross,unit,clamp};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ArenaMath=api;
})(globalThis);
