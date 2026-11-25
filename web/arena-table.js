'use strict';
// All plan coordinates are metres in the simulator's coordinate system.
globalThis.ArenaTable=(()=>{
  const tau=2*Math.PI, xy=p=>[p.x,p.y], move=(a,n,d)=>[a[0]+n[0]*d,a[1]+n[1]*d];
  const unit=(a,b)=>{const x=b[0]-a[0],y=b[1]-a[1],l=Math.hypot(x,y);return [x/l,y/l];};
  const colors={felt:[.073,.42,.31],cushion:[.085,.405,.302],timber:[.31,.197,.135],walnut:[.235,.143,.102],
    welt:[.59,.49,.387],hide:[.746,.658,.54],binding:[.38,.30,.23],iron:[.50,.40,.26],net:[.47,.425,.34],well:[.15,.131,.108]};
  function geometry(config,Mesh){
    const mesh=new Mesh(),obstacles=[],pockets=[],{length:L,width:W}=config.model.table,{surfaces}=config.geometry;
    const rails=surfaces.filter(s=>!s.radius),at=(a,z)=>[...a,z],up=[0,0,1];
    function prism(points,top){
      obstacles.push({points,top,x0:Math.min(...points.map(p=>p[0])),x1:Math.max(...points.map(p=>p[0])),
        y0:Math.min(...points.map(p=>p[1])),y1:Math.max(...points.map(p=>p[1]))});
    }
    function normal(rail){return rail.id.startsWith('bottom')?[0,1]:rail.id.startsWith('top')?[0,-1]:rail.id==='left'?[1,0]:[-1,0];}
    function cushion(path){
      // Distance behind the rubber nose and height. The maximum projection is at the contact height.
      const profile=[[.004,0],[.001,.024],[0,.032],[.0015,.035],[.010,.039],[.032,.042],[.054,.042]];
      for(let j=1;j<path.length;j++){
        const a=path[j-1],b=path[j];
        for(let i=1;i<profile.length;i++){
          const [d,z]=profile[i-1],[e,h]=profile[i],a0=move(a.p,a.n,-d),b0=move(b.p,b.n,-d),a1=move(a.p,a.n,-e),b1=move(b.p,b.n,-e);
          const n=ArenaMath.unit([(a.n[0]+b.n[0])*(h-z)/2,(a.n[1]+b.n[1])*(h-z)/2,e-d]);
          mesh.quad(at(a0,z),at(b0,z),at(b1,h),at(a1,h),colors.cushion,10,n);
          // The first two strips make one solid below the projecting nose, too.
          if(i>=3)prism([a0,b0,b1,a1],Math.max(z,h));
        }
      }
    }
    function box(x,y,z,X,Y,Z,c,mat){mesh.box(x,y,z,X,Y,Z,c,mat);if(Z>0)prism([[x,y],[X,y],[X,Y],[x,Y]],Z);}
    mesh.box(-13,-13,-.84,L+13,W+13,-.83,[.20,.23,.21],6);
    for(const x of [.16,L-.16])for(const y of [.15,W-.15]){
      const rings=[[-.83,.076],[-.807,.083],[-.785,.075],[-.752,.063],[-.62,.054],[-.55,.073],[-.524,.079],[-.505,.072],[-.455,.062],[-.365,.086],[-.19,.09]];
      for(let i=1;i<rings.length;i++){const [z,r]=rings[i],[h,s]=rings[i-1];mesh.tube([x,y,h],[x,y,z],s,r,i===2?colors.iron:colors.walnut,i===2?3:2,20);}
    }
    // Six separately finished apron bays leave the net and its opening genuinely hollow.
    mesh.box(.112,.112,-.215,L-.112,W-.112,-.066,colors.walnut,2);
    function railBay(rail){
      const a=xy(rail.start),b=xy(rail.end),n=normal(rail),along=unit(a,b);
      const pair=(s,t,da,db)=>[move(move(a,along,s),n,-da),move(move(b,along,-t),n,-db)];
      function bay(s,da,db,z,h,c,mat){
        const [a0,b0]=pair(s,s,da,da),[a1,b1]=pair(s,s,db,db),vs=[a0,b0,b1,a1];
        box(Math.min(...vs.map(p=>p[0])),Math.min(...vs.map(p=>p[1])),z,Math.max(...vs.map(p=>p[0])),Math.max(...vs.map(p=>p[1])),h,c,mat);
      }
      bay(.020,.032,.123,-.207,-.043,colors.walnut,2);
      bay(.022,.12,.124,-.184,-.180,colors.iron,3);
      bay(0,.050,.129,-.049,.040,colors.timber,2);
      bay(0,.054,.124,.040,.043,colors.timber,2);
      cushion([{p:a,n},{p:b,n}]);
    }
    rails.forEach(railBay);
    function station(p,jaw){
      const a=xy(jaw.start),mid=xy(p.mouth),endpoints=rails.flatMap(r=>[r.start,r.end].map(q=>({q:xy(q),n:normal(r)})));
      const nearest=endpoints.reduce((best,e)=>Math.hypot(...move(e.q,a,-1))<Math.hypot(...move(best.q,a,-1))?e:best);
      const ni=unit(a,mid),n0=nearest.n,angle=Math.atan2(n0[1],n0[0]),sweep=Math.atan2(n0[0]*ni[1]-n0[1]*ni[0],n0[0]*ni[0]+n0[1]*ni[1]);
      const count=Math.ceil(Math.abs(sweep)*14),arc=[];
      for(let i=0;i<=count;i++){const t=angle+sweep*i/count,n=[Math.cos(t),Math.sin(t)];arc.push({p:move(a,n,jaw.radius),n});}
      const throat=arc[arc.length-1].p,out=xy(p.outward);
      // Rubber ends inside the hide socket. Its inward face matches the outgoing physical jaw.
      arc.push({p:move(throat,out,.0095),n:ni});
      cushion(arc);
      return {throat,rail:nearest,arc};
    }
    function cord(a,b,r,col){ // Open octagonal/diamond cords meet at their actual 3-D nodes.
      const axis=ArenaMath.unit(ArenaMath.sub(b,a)),u=ArenaMath.unit(ArenaMath.cross(axis,Math.abs(axis[2])>.85?[1,0,0]:up)),v=ArenaMath.cross(axis,u);
      const offsets=[u,v,ArenaMath.mul(u,-1),ArenaMath.mul(v,-1)].map(q=>ArenaMath.mul(q,r));
      for(let j=0;j<4;j++){const k=(j+1)%4,add=ArenaMath.add;mesh.quad(add(a,offsets[j]),add(a,offsets[k]),add(b,offsets[k]),add(b,offsets[j]),col,4,ArenaMath.unit(add(offsets[j],offsets[k])));}
    }
    function pocket(p,box2){
      const out=xy(p.outward),tan=xy(p.tangent),mouth=xy(p.mouth),fall=xy(p.fall_center),side=Math.abs(out[0])<.1;
      const point=(d,t)=>move(move(mouth,out,d),tan,t),w=p.half_width,r=p.fall_radius;
      const jaws=surfaces.filter(s=>s.id.startsWith('jaw:'+p.id+':')).map(s=>station(p,s))
        .sort((a,b)=>(a.throat[0]-b.throat[0])*tan[0]+(a.throat[1]-b.throat[1])*tan[1]);
      const front=-.001,base=side?.006:.032,capWidth=w+.0015;
      const basket=point(base+.008,0),D=(basket[0]-fall[0])*out[0]+(basket[1]-fall[1])*out[1];
      // Front lip follows the physical loss-of-support circle; behind it the slate opens into the basket.
      const [x0,y0,x1,y1]=box2,angles=Array.from({length:64},(_,i)=>i*tau/64);
      for(const x of [x0,x1])for(const y of [y0,y1])angles.push((Math.atan2(y-fall[1],x-fall[0])+tau)%tau);
      const ring=angles.sort((a,b)=>a-b).map(t=>{
        const dir=[Math.cos(t),Math.sin(t)],k=dir[0]*out[0]+dir[1]*out[1],perp=Math.sqrt(Math.max(0,1-k*k));
        const wall=r/Math.max(1e-12,perp);
        const dist=k<=0?r:wall*k<=D?wall:D*k+Math.sqrt(Math.max(0,r*r-D*D*perp*perp));
        const tx=Math.abs(dir[0])<1e-10?Infinity:((dir[0]<0?x0:x1)-fall[0])/dir[0],ty=Math.abs(dir[1])<1e-10?Infinity:((dir[1]<0?y0:y1)-fall[1])/dir[1];
        return {edge:at(move(fall,dir,Math.min(tx,ty)),0),rim:at(move(fall,dir,dist),0),under:at(move(fall,dir,dist+.002),-.042)};
      });
      ring.forEach((a,i)=>{const b=ring[(i+1)%ring.length];mesh.quad(a.rim,a.edge,b.edge,b.rim,colors.felt,1,up);
        const towards=unit(a.rim,fall);mesh.quad(a.rim,b.rim,b.under,a.under,colors.well,8,[...towards,0]);});
      // A horseshoe with open front, a lightly rolled inner lip and fitted shoulders meeting each wooden rail.
      const halves=[];
      const outerCorner=[out[0]<0?-.129:L+.129,out[1]<0?-.129:W+.129];
      for(let j=0;j<2;j++){
        const sign=j?1:-1,rail=jaws[j].rail,outerA=move(rail.q,rail.n,-.054),outerB=move(rail.q,rail.n,-.129);
        const extreme=side?move(outerB,tan,-sign*Math.abs((outerB[0]-mouth[0])*tan[0]+(outerB[1]-mouth[1])*tan[1])):outerCorner;
        const guide=(v,t)=>v[0]+(v[1]-v[0])*t;
        const part=[];
        for(let i=0;i<=22;i++){
          const u=i/22,t=Math.max(0,(u-.20)/.80)*Math.PI/2;
          const inside=point(i<5?front+(base-front)*Math.min(1,u/.20):base+capWidth*Math.sin(t),sign*capWidth*Math.cos(t));
          // A softly rounded external corner; the three control pieces have common endpoints.
          const t0=Math.min(1,u/.45),t1=Math.max(0,(u-.45)/.55);
          let outside=[0,1].map(k=>u<.45?guide([outerA[k],outerB[k]],t0):guide([outerB[k],extreme[k]],t1));
          if(!side&&u>=.45){
            const axis=unit(extreme,outerB),other=unit(extreme,move(jaws[1-j].rail.q,jaws[1-j].rail.n,-.129)),rr=.027;
            if(t1<.67){const finish=move(extreme,axis,rr);outside=outerB.map((v,k)=>guide([v,finish[k]],t1/.67));}
            else {const angle=(t1-.67)/.33*Math.PI/4;outside=move(move(extreme,axis,rr*(1-Math.sin(angle))),other,rr*(1-Math.cos(angle)));}
          }
          const inset=v=>inside.map((x,k)=>x+(outside[k]-x)*v);
          part.push({inside,a:at(inside,.030),b:at(inset(.08),.0405),c:at(inset(.16),.0436),d:at(inset(.90),.0436),e:at(outside,.0405),f:at(outside,-.028),st:at(inset(.26),.044)});
        }
        halves.push(part);
        for(let i=1;i<part.length;i++){const a=part[i-1],b=part[i];
          for(const [lo,hi,col] of [['a','b',colors.binding],['b','c',colors.welt],['c','d',colors.hide],['d','e',colors.welt]])mesh.quad(a[lo],b[lo],b[hi],a[hi],col,4,up);
          mesh.quad(a.e,b.e,b.f,a.f,colors.binding,4,[...unit(a.inside,a.e),0]);
          const inn=unit(a.e,a.inside);mesh.quad(a.a,b.a,at(b.inside,-.037),at(a.inside,-.037),colors.well,8,[...inn,0]);
          prism([a.inside,b.inside,b.e.slice(0,2),a.e.slice(0,2)],.0447);
          if(i%2===0)cord(a.st,b.st,.00065,[.84,.72,.53]);
        }
      }
      // Diamond net hangs below the open slate and behind the rail. An interior in shadow gives it depth.
      const node=(row,index)=>{const theta=(index+(row%2)*.5)*tau/12;
        const radius=[r+.004,r+.004,r*.96,r*.85,r*.65,r*.34][row],depth=[-.036,-.068,-.101,-.137,-.171,-.195][row];
        return [...move(move(basket,tan,Math.cos(theta)*radius),out,Math.sin(theta)*radius),depth];};
      // The lower leather liner shades the inside of the open net. Its rim lies below the cut slate.
      const liner=(i,z,scale)=>{const a=i*tau/36;return [...move(move(basket,tan,r*scale*Math.cos(a)),out,r*scale*Math.sin(a)),z];};
      for(let i=0;i<36;i++){
        const a=liner(i,-.041,1.045),b=liner(i+1,-.041,1.045),c=liner(i+1,-.086,.92),d=liner(i,-.086,.92);
        mesh.quad(a,b,c,d,[.115,.098,.078],8,[...unit(a,basket),0]);
        mesh.quad(d,c,liner(i+1,-.113,.84),liner(i,-.113,.84),[.071,.066,.053],8,[...unit(a,basket),0]);
      }
      for(let row=0;row<5;row++)for(let j=0;j<12;j++){const a=node(row,j);
        for(const k of [j,j+(row%2?1:-1)])cord(a,node(row+1,k),.0014,colors.net);}
      for(let j=0;j<12;j++){cord(node(0,j),node(0,j+1),.0023,colors.binding);cord(node(5,j),node(5,j+1),.0018,colors.net);}
      mesh.disk(basket[0],basket[1],-.18,r*.47,[.08,.075,.057],8);
      for(const j of [0,1]){const marker=halves[j][5],p0=marker.d;mesh.disk(p0[0],p0[1],.044,.0025,colors.iron,3);}
      pockets.push({id:p.id,jaws,ring,halves});
    }
    const xs=[-.12,L*.25,L*.75,L+.12],ys=[-.12,W*.5,W+.12];
    for(const p of config.geometry.pockets){const c=p.outward.x<-.1?0:p.outward.x>.1?2:1,row=p.outward.y<0?0:1;
      pocket(p,[xs[c],ys[row],xs[c+1],ys[row+1]]);}
    function sight(x,y,dx,dy){mesh.quad([x-dx,y,.0432],[x,y-dy,.0432],[x+dx,y,.0432],[x,y+dy,.0432],[.86,.80,.65],3,up);}
    for(let k=1;k<8;k++)if(k!==4)for(const y of [-.088,W+.088])sight(L*k/8,y,.008,.003);
    for(let k=1;k<4;k++)for(const x of [-.088,L+.088])sight(x,W*k/4,.003,.008);
    for(const x of [L*.25,L*.75])mesh.disk(x,W/2,.0006,.003,[.8,.78,.65],7);
    return {mesh,obstacles,pockets};
  }
  let cachedFinish;
  function finishes(){
    if(cachedFinish)return cachedFinish;
    // Three seamless 128 x 128 swatches. Transverse walnut fluctuations remain coherent along the board.
    const size=128,bytes=new Uint8Array(size*size*4*3);
    for(let row=0;row<4;row++)for(let y=0;y<size;y++)for(let x=0;x<size;x++){
      const a=x*tau/size,b=y*tau/size;
      let hash=Math.imul(x+1,374761393)^Math.imul(y+1,668265263);
      hash=Math.imul(hash^(hash>>>13),1274126177);const noise=((hash^(hash>>>16))>>>0)/4294967296-.5;
      let value;
      if(row===0)value=1+.044*noise+.009*Math.sin(21*a+8*b)+.008*Math.cos(22*b-7*a);
      else if(row===1){
        const ring=6*b+.87*Math.sin(a)+.48*Math.sin(2*a+b)+.36*Math.sin(3*b);
        value=1+.062*Math.sin(ring)+.047*Math.cos(2*ring+.5*Math.sin(a))-.083*(.5+.5*Math.cos(5*ring))**8+.028*noise;
      }else value=1+.057*noise+.016*Math.sin(3*a+2*b)*Math.cos(4*b-a)+.013*Math.sin(21*b+2*Math.cos(9*a));
      const k=3*((row*size+y)*size+x),c=Math.round(value*218);bytes[k]=bytes[k+1]=bytes[k+2]=c;
    }
    cachedFinish={width:size,height:size*4,bytes};return cachedFinish;
  }
  return {geometry,finishes};
})();
