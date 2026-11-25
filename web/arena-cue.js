'use strict';
globalThis.ArenaCue=(()=>{
  const L=CueVisual.length,tip=CueVisual.tipDiameter/2,butt=CueVisual.buttDiameter/2,margin=.00045;
  const cache=new WeakMap(),profiles=[0,.009,.10,.34,.72,1.06,L-tip];
  const radii=profiles.map(s=>tip+(butt-tip)*(s/(L-tip))**.86);
  const radius=s=>{for(let i=1;i<profiles.length;i++)if(s<=profiles[i])return radii[i-1]+(radii[i]-radii[i-1])*(Math.max(0,s)-profiles[i-1])/(profiles[i]-profiles[i-1]);return butt;};
  function pose(cue,shot,elevation){
    const a=shot.angle_deg*Math.PI/180,dx=Math.cos(a),dy=Math.sin(a),ce=Math.cos(elevation),se=Math.sin(elevation);
    const tx=shot.tip_x||0,ty=shot.tip_y||0,front=Math.sqrt(Math.max(0,1-tx*tx-ty*ty)),r=cue.spec.radius;
    const N=[-dx*front+dy*tx,-dy*front-dx*tx,ty],C=[cue.position.x,cue.position.y,r];
    const origin=C.map((v,i)=>v+(r+tip)*N[i]),rear=[-dx*ce,-dy*ce,se];
    return {origin,rear,axis:[dx*ce,dy*ce,-se,-dy,dx,0,dx*se,dy*se,ce],elevation};
  }
  function obstaclePlanes(obstacles){
    if(cache.has(obstacles))return cache.get(obstacles);
    const prepared=obstacles.map(o=>{
      const q=o.points,area=q.reduce((s,a,i)=>{const b=q[(i+1)%q.length];return s+a[0]*b[1]-a[1]*b[0];},0),sign=Math.sign(area);
      const edges=[];
      for(let i=0;i<q.length;i++){
        const a=q[i],b=q[(i+1)%q.length],x=sign*(a[1]-b[1]),y=sign*(b[0]-a[0]),len=Math.hypot(x,y);
        if(len>1e-12)edges.push([x/len,y/len,(x*a[0]+y*a[1])/len]);
      }
      return {...o,edges};
    }).filter(o=>o.edges.length>=3);
    cache.set(obstacles,prepared);return prepared;
  }
  function fromGap(p,g){return p.origin.map((v,i)=>v+g*p.rear[i]);}
  function clear(p,balls,obstacles,lo,hi){
    const O=fromGap(p,lo),v=p.rear;
    const near=balls.filter(b=>!b.pocket).map(b=>({id:b.id,r:b.spec.radius,x:O[0]-b.position.x,y:O[1]-b.position.y,z:O[2]-b.spec.radius}));
    const planes=obstaclePlanes(obstacles),span=hi-lo,limit=profiles.at(-1)+span;
    const end=Math.min(limit,v[2]>0?Math.max(0,(.065-O[2])/v[2]):limit),tx=O[0]+v[0]*end,ty=O[1]+v[1]*end;
    const band=butt+margin,nearby=planes.filter(o=>o.x1>=Math.min(O[0],tx)-band&&o.x0<=Math.max(O[0],tx)+band&&o.y1>=Math.min(O[1],ty)-band&&o.y0<=Math.max(O[1],ty)+band);
    // At any axial station the widest radius swept during withdrawal occurs at its most forward pose.
    for(let j=1;j<=profiles.length;j++){
      const a=profiles[j-1],b=j<profiles.length?profiles[j]:limit;
      if(b<=a)continue;
      const ra=radii[j-1],rb=j<radii.length?radii[j]:butt,k=(rb-ra)/(b-a),offset=ra-k*a;
      const floorZ=Math.min(O[2]+v[2]*a-ra,O[2]+v[2]*b-rb);
      if(floorZ<margin)return false;
      for(const ball of near){
        const extra=ball.id==='cue'?0:margin,R=ball.r+offset+extra,along=ball.x*v[0]+ball.y*v[1]+ball.z*v[2];
        const t=Math.max(a,Math.min(b,(R*k-along)/(1-k*k)));
        const x=ball.x+v[0]*t,y=ball.y+v[1]*t,z=ball.z+v[2]*t;
        if(x*x+y*y+z*z-(R+k*t)**2 < -1e-12)return false;
      }
      if(floorZ>.045+margin||a>end)continue;
      for(const o of nearby){
        if(floorZ>=o.top+margin)continue;
        let start=a,stop=b;
        // Clip against each inward half-plane expanded by the local tapered shaft radius.
        for(const [nx,ny,d] of o.edges){
          const f=nx*O[0]+ny*O[1]-d+offset+margin,slope=nx*v[0]+ny*v[1]+k;
          if(Math.abs(slope)<1e-12){if(f<0){start=Infinity;break;}}
          else if(slope>0)start=Math.max(start,-f/slope);else stop=Math.min(stop,-f/slope);
          if(start>stop)break;
        }
        if(start<=stop&&Math.min(O[2]+(v[2]-k)*start,O[2]+(v[2]-k)*stop)-offset<o.top+margin)return false;
      }
    }
    return true;
  }
  function plan(cue,shot,balls,obstacles){
    const back=CueVisual.timing(shot.cue_speed).back,step=2*Math.PI/180,max=32*Math.PI/180;
    const valid=p=>clear(p,balls,obstacles,0,back);
    for(let a=0;a<=max+1e-10;a+=step){
      let p=pose(cue,shot,a);if(!valid(p))continue;
      if(a>0){
        let lo=a-step,hi=a;for(let j=0;j<8;j++){const mid=(lo+hi)/2;if(valid(pose(cue,shot,mid)))hi=mid;else lo=mid;}
        p=pose(cue,shot,hi);
      }
      return {...p,blocked:false,back};
    }
    return {...pose(cue,shot,0),blocked:true,back};
  }
  function frame(plan,stroke,balls,obstacles){
    function at(g){return {position:fromGap(plan,g),axis:plan.axis};}
    // A real lifted rest position when an oblique strike cannot reach the chosen tip point.
    function rest(){const p=at(Math.max(.055,stroke.gap));p.position[2]=Math.max(.103,p.position[2]);return p;}
    if(plan.blocked)return rest();
    const gap=stroke.gap;
    if(gap>=0&&stroke.phase!=='follow-through')return at(gap);
    // Rebounds and slow shots can leave a live ball in the nominal follow-through.
    // Verify the whole swept interval against the replay frame before advancing.
    if(gap<=0&&clear(plan,balls,obstacles,gap,0))return at(gap);
    if(clear(plan,balls,obstacles,0,0)){
      let lo=gap,hi=0;for(let i=0;i<10;i++){const mid=(lo+hi)/2;if(clear(plan,balls,obstacles,mid,0))hi=mid;else lo=mid;}
      return at(hi);
    }
    for(const retract of [.012,.027,.05,.09,.16,plan.back])if(clear(plan,balls,obstacles,retract,retract))return at(retract);
    return rest();
  }
  // Grain follows the turned timber. The same cylindrical texture feeds both renderers.
  let texture;
  function woodTexture(){
    if(texture)return texture;
    const width=1024,height=128,bytes=new Uint8Array(width*height*3);
    for(let y=0;y<height;y++){
      const angle=2*Math.PI*(y+.5)/height,cy=Math.cos(angle),sy=Math.sin(angle);
      for(let x=0;x<width;x++){
        const s=L*(x+.5)/width,r=radius(s),u=cy*r,v=sy*r;
        // Eccentric annual rings intersect a slightly wandering longitudinal grain axis.
        const sweep=.019+.005*Math.sin(s*3.6+.4)+.0025*Math.sin(s*8.3);
        const ring=Math.hypot(u+sweep,v+.003*Math.sin(s*4.4))/.00185;
        const late=(.5+.5*Math.cos(2*Math.PI*ring))**5;
        const fiber=(.5+.5*Math.sin(2*Math.PI*(3.8*ring+.36*Math.sin(s*12+sy)+.4*sy)))**9;
        const variation=3.8*Math.sin(ring*2.14+s*.7)-21*late-8*fiber;
        const splice=1.00+.255*(.5+.5*Math.cos(angle*4+.32))**.67;
        const sap=s<splice,base=sap?[212,178,125]:[102,67,44],i=3*(y*width+x);
        const vein= !sap&&s-splice<.0025?13:0;
        for(let c=0;c<3;c++)bytes[i+c]=Math.round(base[c]+variation*(sap?1:.58)+vein);
      }
    }
    texture={width,height,bytes};return texture;
  }
  function mesh(Mesh){
    const m=new Mesh(),segments=40,ring=(x,r)=>Array.from({length:segments},(_,i)=>{const t=2*Math.PI*i/segments;return [-x,r*Math.cos(t),r*Math.sin(t)];});
    const stations=[];
    for(let i=0;i<=7;i++){const a=i*Math.PI/14;stations.push({s:-tip*Math.cos(a),r:tip*Math.sin(a)});}
    for(const s of [.003,.012,...profiles.slice(2,-1),L-tip-.01,L-tip])stations.push({s,r:radius(s)});
    for(let j=1;j<stations.length;j++){
      const a=stations[j-1],b=stations[j],A=ring(a.s,a.r),B=ring(b.s,b.r),mat=b.s<=.003?4:b.s<=.012?3:b.s>L-tip-.009?10:11;
      const col=mat===4?[.29,.37,.34]:mat===3?[.65,.54,.32]:mat===10?[.15,.13,.11]:[1,1,1];
      const norm=(v,s)=>s<=0?ArenaMath.unit(v):ArenaMath.unit([.007,v[1]/Math.max(.00001,radius(s)),v[2]/Math.max(.00001,radius(s))]);
      for(let i=0;i<segments;i++){const k=(i+1)%segments;for(const [v,s] of [[A[i],a.s],[A[k],a.s],[B[k],b.s],[A[i],a.s],[B[k],b.s],[B[i],b.s]])m.data.push(...v,...norm(v,s),...col,mat);}
    }
    const end=stations.at(-1),back=ring(end.s,end.r);
    for(let i=0;i<segments;i++)m.tri([-end.s,0,0],back[i],back[(i+1)%segments],[.12,.105,.09],10,[-1,0,0]);
    return m;
  }
  return {length:L,tip,radius,profiles,clear,plan,frame,woodTexture,mesh};
})();
