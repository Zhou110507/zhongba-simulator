'use strict';
(function(root){
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const add=(a,b)=>a.map((v,i)=>v+b[i]),sub=(a,b)=>a.map((v,i)=>v-b[i]),mul=(a,k)=>a.map(v=>v*k);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const unit=a=>mul(a,1/(Math.hypot(...a)||1)),clamp=(n,lo,hi)=>Math.max(lo,Math.min(hi,n));
  // Coordinates are the simulation's metres, with +z above the cloth.
  class Camera {
    constructor(){this.mode='orbit';this.azimuth=-1.92;this.pitch=.72;this.zoom=1;}
    select(mode){if(['orbit','cue','top'].includes(mode)){this.mode=mode;this.zoom=1;}}
    orbit(dx,dy){this.mode='orbit';this.azimuth-=dx*.007;this.pitch=clamp(this.pitch+dy*.005,.24,1.48);}
    magnify(factor){this.zoom=clamp(this.zoom*factor,.65,2.1);}
    frame(width,height,table,cue,shot){
      const aspect=width/height,top=this.mode==='top';
      const yaw=this.mode==='cue'?shot.angle_deg*Math.PI/180+Math.PI:top?-Math.PI/2:this.azimuth;
      const pitch=this.mode==='cue'?.265:top?Math.PI/2:this.pitch;
      const backward=[Math.cos(yaw)*Math.cos(pitch),Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch)];
      const right=[-Math.sin(yaw),Math.cos(yaw),0],forward=mul(backward,-1),up=cross(right,forward),lens=1/Math.tan(35*Math.PI/360);
      let target=[table.length/2,table.width/2,top?0:-.1],distance=0;
      if(this.mode==='cue'){
        target=[cue.x-.33*Math.cos(yaw),cue.y-.33*Math.sin(yaw),.048];distance=Math.max(1.22,.85/aspect);
      }else{
        // Fit all cabinet corners horizontally and vertically before zoom.
        for(const x of [-.16,table.length+.16])for(const y of [-.16,table.width+.16])for(const z of [-.23,.055]){
          const d=sub([x,y,z],target);
          const extent=Math.max(Math.abs(dot(d,right))*lens/aspect,Math.abs(dot(d,up))*lens);
          distance=Math.max(distance,extent*1.14-(top?0:dot(d,forward)));
        }
      }
      distance/=this.zoom;
      const eye=add(target,mul(backward,distance)),ortho=top?distance/lens:0;
      const project=point=>{
        const d=sub(point,eye),depth=dot(d,forward);if(depth<=.03)return null;
        const scale=height/2/(ortho||depth/lens);
        return {x:width/2+dot(d,right)*scale,y:height/2-dot(d,up)*scale,depth};
      };
      const pick=(x,y,z=0)=>{
        const side=add(mul(right,(2*x/width-1)*aspect),mul(up,1-2*y/height));
        const origin=ortho?add(eye,mul(side,ortho)):eye,ray=ortho?forward:add(forward,mul(side,1/lens));
        if(Math.abs(ray[2])<1e-8)return null;
        const t=(z-origin[2])/ray[2];return t>.03?{x:origin[0]+t*ray[0],y:origin[1]+t*ray[1]}:null;
      };
      return {width,height,aspect,eye,right,up,forward,lens,ortho,project,pick};
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
