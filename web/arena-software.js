'use strict';
(function(root){
 const {dot,sub,add,mul,cross,unit}=ArenaMath;
 const light=unit([-.36,.22,.91]);
 function polygon(g,pts,col,seam=false){
   if(pts.some(p=>!p))return;g.beginPath();g.moveTo(pts[0].x,pts[0].y);
   for(let i=1;i<pts.length;i++)g.lineTo(pts[i].x,pts[i].y);g.closePath();g.fillStyle=col;g.fill();
   if(seam){g.strokeStyle=col;g.lineWidth=.5;g.stroke();}
 }
 function faces(mesh){
   const a=mesh.data,output=[],shared=new Map();
   function vertex(j){
     const key=a[j]+','+a[j+1]+','+a[j+2];let p=shared.get(key);
     if(!p){p=a.slice(j,j+3);shared.set(key,p);}return p;
   }
   for(let i=0;i<a.length;i+=30){
     const mat=a[i+9];if(mat===6)continue;
     const points=[i,i+10,i+20].map(vertex),normal=a.slice(i+3,i+6),shade=.54+.49*Math.max(0,dot(normal,light))+.065*Math.max(0,dot(normal,[.5,-.7,.45]));
     const rgb=a.slice(i+6,i+9).map(v=>Math.round(v*255*shade));
     const height=Math.max(...points.map(p=>p[2]));
     output.push({points,normal,mat,center:mul(add(add(points[0],points[1]),points[2]),1/3),color:rgb,
       layer:height<-.23?0:height<0?1:mat===8?2:mat===1?3:mat===10?5:4});
   }
   const groups=new Map();
   for(const face of output){
     const [x,y,z]=face.center,key=Math.floor(x/.15)+','+Math.floor(y/.15)+','+Math.floor(z/.12);
     let group=groups.get(key);
     if(!group){group={lo:[Infinity,Infinity,Infinity],hi:[-Infinity,-Infinity,-Infinity]};groups.set(key,group);}
     face.group=group;
     for(const p of face.points)for(let k=0;k<3;k++){group.lo[k]=Math.min(group.lo[k],p[k]);group.hi[k]=Math.max(group.hi[k],p[k]);}
   }
   for(const group of groups.values()){
     group.center=group.lo.map((v,k)=>(v+group.hi[k])*.5);group.half=group.lo.map((v,k)=>(group.hi[k]-v)*.5);
   }
   return {triangles:output,groups:[...groups.values()]};
 }
 // Clip triangles crossing the eye plane. Interpolate attributes with reciprocal depth.
 function cameraVertex(f,p,v){
   const dx=p[0]-f.eye[0],dy=p[1]-f.eye[1],dz=p[2]-f.eye[2],d=dx*f.forward[0]+dy*f.forward[1]+dz*f.forward[2];
   const projected=d>=.034?f.project(p):null;
   return {p,v,d,x:projected?.x||0,y:projected?.y||0,q:f.ortho?1:1/d};
 }
 function triangle(f,a,b,c,fragment,span){
   const bx=b.x-a.x,by=b.y-a.y,cx=c.x-a.x,cy=c.y-a.y,det=bx*cy-by*cx;
   if(Math.abs(det)<1e-7)return;
   // At a pixel-centre scanline cover only the actual triangle span. Bounding-box
   // iteration can visit a screenful of empty pixels for one long, thin slate wedge.
   let top=a,mid=b,bot=c;
   if(top.y>mid.y)[top,mid]=[mid,top];if(mid.y>bot.y)[mid,bot]=[bot,mid];if(top.y>mid.y)[top,mid]=[mid,top];
   const y0=Math.max(0,Math.ceil(top.y-.5)),y1=Math.min(f.height-1,Math.floor(bot.y-.5));
   if(y0>y1)return;
   const long=(bot.x-top.x)/(bot.y-top.y),upper=mid.y===top.y?0:(mid.x-top.x)/(mid.y-top.y);
   const lower=bot.y===mid.y?0:(bot.x-mid.x)/(bot.y-mid.y),du=cy/det,dv=-by/det;
   for(let y=y0;y<=y1;y++){
     const yc=y+.5,pxA=top.x+(yc-top.y)*long,pxB=yc<mid.y?top.x+(yc-top.y)*upper:mid.x+(yc-mid.y)*lower;
     const x0=Math.max(0,Math.ceil(Math.min(pxA,pxB)-.500001)),x1=Math.min(f.width-1,Math.floor(Math.max(pxA,pxB)-.499999));
     if(x0>x1)continue;
     if(span){span(y,x0,x1);continue;}
     let u=((x0+.5-a.x)*cy-(yc-a.y)*cx)/det,v=(bx*(yc-a.y)-by*(x0+.5-a.x))/det;
     for(let i=y*f.width+x0,last=y*f.width+x1;i<=last;i++,u+=du,v+=dv){
       const w=1-u-v,scale=f.ortho?1:1/(w*a.q+u*b.q+v*c.q);
       fragment(i,f.ortho?w*a.d+u*b.d+v*c.d:scale,a.v,b.v,c.v,w*a.q*scale,u*b.q*scale,v*c.q*scale);
     }
   }
 }
 function raster(f,vertices,fragment,span){
   const [a,b,c]=vertices;
   if(a.d>=.034&&b.d>=.034&&c.d>=.034){triangle(f,a,b,c,fragment,span);return;}
   if(a.d<.034&&b.d<.034&&c.d<.034)return;
   const clipped=[];
   for(let j=0;j<3;j++){
     const a=vertices[j],b=vertices[(j+1)%3];if(a.d>=.034)clipped.push(a);
     if((a.d>=.034)!==(b.d>=.034)){
       const t=(.034-a.d)/(b.d-a.d),p=a.p.map((x,k)=>x+(b.p[k]-x)*t);
       const projected=f.project(p);
       clipped.push({p,x:projected.x,y:projected.y,d:.034,q:f.ortho?1:1/.034,v:a.v.map((x,k)=>x+(b.v[k]-x)*t)});
     }
   }
   for(let i=1;i<clipped.length-1;i++)triangle(f,clipped[0],clipped[i],clipped[i+1],fragment,span);
 }
 // A horizontal tabletop with a level horizon has a constant optical depth on each scanline.
 // Camera samples remain full resolution. Reuse that plane intersection across adjoining slate wedges.
 function frustumPlanes(f){
   const planes=[{n:f.forward,min:.034}];
   for(const [axis,span] of [[f.right,f.aspect],[f.up,1]])for(const sign of [-1,1]){
     const normal=axis.map((x,i)=>sign*x+(f.ortho?0:f.forward[i]*span/f.lens));
     planes.push({n:normal,min:f.ortho?-f.ortho*span:0});
   }
   return planes;
 }
 function visibleGroup(group,f,planes){
   const d=sub(group.center,f.eye),h=group.half;
   for(const {n,min} of planes)if(dot(d,n)+h[0]*Math.abs(n[0])+h[1]*Math.abs(n[1])+h[2]*Math.abs(n[2])<min)return false;
   return true;
 }
 function planeRows(f,z){
   const rows=[],scale=2/f.height*(f.ortho||1/f.lens),sx=(.5-f.width/2)*scale;
   return y=>{
     if(rows[y])return rows[y];
     const sy=(f.height/2-y-.5)*scale;
     const depth=f.ortho?(z-f.eye[2]-sy*f.up[2])/f.forward[2]:(z-f.eye[2])/(f.forward[2]+sy*f.up[2]);
     const k=f.ortho?1:depth,dx=f.right[0]*scale*k,dy=f.right[1]*scale*k;
     const x=f.eye[0]+f.forward[0]*depth+(f.up[0]*sy+f.right[0]*sx)*k,y0=f.eye[1]+f.forward[1]*depth+(f.up[1]*sy+f.right[1]*sx)*k;
     return rows[y]={x,y:y0,dx,dy,depth};
   };
 }
 function clothLight(table){
   const density=180,width=Math.ceil((table.length+.4)*density),height=Math.ceil((table.width+.4)*density),data=new Float32Array(width*height);
   for(let j=0;j<height;j++)for(let i=0;i<width;i++){
     const x=(i+.5)/density-.2,y=(j+.5)/density-.2,edge=Math.min(x,table.length-x,y,table.width-y);
     data[j*width+i]=(1.14-.30*Math.hypot((x/table.length-.5)*.85,y/table.width-.5))*(.94+.06*Math.min(1,Math.max(0,edge/.055)));
   }
   return {density,width,data};
 }
 function colorRamp(color){
   const ramp=new Uint32Array(320);
   for(let i=0;i<ramp.length;i++){
     const rgb=color.map(n=>Math.min(255,Math.round(n*i/218)));ramp[i]=(255<<24)|(rgb[2]<<16)|(rgb[1]<<8)|rgb[0];
   }
   return ramp;
 }
 function segment(g,f,a,b,c,width=1){
   const p=f.project(a),q=f.project(b);if(!p||!q)return;
   g.beginPath();g.moveTo(p.x,p.y);g.lineTo(q.x,q.y);g.strokeStyle=c;g.lineWidth=width;g.stroke();
 }
 function lines(g,f,data,count){for(let i=0;i<count*10;i+=20){const col=[6,7,8].map(j=>Math.round(data[i+j]*255));segment(g,f,data.slice(i,i+3),data.slice(i+10,i+13),'rgb('+col.join(',')+')');}}
 function rotate(q,p){const v=q.slice(0,3);return add(p,mul(cross(v,add(cross(v,p),mul(p,q[3]))),2));}
 class SoftwareRenderer{
   constructor(canvas){this.g=canvas.getContext('2d');this.layer=document.createElement('canvas');this.sprites=new Map();this.cue=ArenaRenderer.cueMesh().data;}
   background(f,config){
     if(this.model!==config.model_signature){this.modelMesh=faces(ArenaRenderer.tableMesh(config));this.clothLight=clothLight(config.model.table);
       const ramps=new Map();for(const face of this.modelMesh.triangles){
         const id=face.color.join();if(!ramps.has(id))ramps.set(id,colorRamp(face.color));face.ramp=ramps.get(id);
       }
       this.model=config.model_signature;this.key='';}
     const key=[f.width,f.height,...f.eye,...f.forward,f.lens,f.ortho].join();if(key===this.key)return;this.key=key;
     const l=this.layer;l.width=f.width;l.height=f.height;const g=l.getContext('2d');
     const grad=g.createRadialGradient(f.width*.49,f.height*.35,0,f.width*.5,f.height*.5,.8*f.width);grad.addColorStop(0,'#404d43');grad.addColorStop(.65,'#28332c');grad.addColorStop(1,'#131e19');g.fillStyle=grad;g.fillRect(0,0,l.width,l.height);
     for(let j=-12;j<=15;j++){segment(g,f,[j*.46,-8,-.83],[j*.46,8,-.83],'#63736921');segment(g,f,[-8,j*.46,-.83],[8,j*.46,-.83],'#63736919');}
     const image=g.getImageData(0,0,l.width,l.height),data=image.data,rgba=new Uint32Array(data.buffer,data.byteOffset,data.length/4);
     this.tableDepth=new Float32Array(l.width*l.height);this.tableDepth.fill(Infinity);
     this.foreDepth=new Float32Array(this.tableDepth.length);
     const finish=ArenaTable.finishes(),{length:L,width:W}=config.model.table;
     const cloth=this.clothLight,grain=finish.bytes,rawDepth=this.tableDepth;
     const clothFreq=128/.097;
     function feltSpan(y,x0,x1){
       const row=clothRows(y),d=row.depth,dx=row.dx,dy=row.dy;
       let wx=row.x+x0*dx,wy=row.y+x0*dy;
       for(let i=y*f.width+x0,last=y*f.width+x1;i<=last;i++,wx+=dx,wy+=dy){
         if(d>=rawDepth[i])continue;
         const tex=3*((Math.floor(wy*clothFreq)&127)*128+(Math.floor(wx*clothFreq)&127));
         const illum=cloth.data[(Math.floor((wy+.2)*cloth.density))*cloth.width+Math.floor((wx+.2)*cloth.density)];
         rgba[i]=feltRamp[Math.round(grain[tex]*illum)];rawDepth[i]=d;
       }
     }
     const clothRows=planeRows(f,0);let feltRamp;
     function swatch(row,x,y){
       const ix=Math.floor(x*128)&127,iy=Math.floor(y*128)&127;
       return finish.bytes[3*((row*128+iy)*128+ix)]/218;
     }
     const frustum=frustumPlanes(f);
     for(const group of this.modelMesh.groups)group.visible=visibleGroup(group,f,frustum);
     const stamp=(this.projectionStamp||0)+1;this.projectionStamp=stamp;
     for(const face of this.modelMesh.triangles){
       if(!face.group.visible)continue;
       const n=face.normal,center=face.center;
       if(n[0]*(f.eye[0]-center[0])+n[1]*(f.eye[1]-center[1])+n[2]*(f.eye[2]-center[2])<-.001)continue;
       const color=face.color;
       const end=Math.min(face.center[0],L-face.center[0])<Math.min(face.center[1],W-face.center[1]);
       const flat=Math.abs(face.normal[2])>.65,mat=face.mat,vertices=face.points.map(p=>{
         if(p.stamp!==stamp){p.screen=cameraVertex(f,p,p);p.stamp=stamp;}return p.screen;
       });
       if(mat===1&&Math.abs(f.right[2])<1e-12){feltRamp=face.ramp;raster(f,vertices,null,feltSpan);continue;}
       raster(f,vertices,(i,depth,a,b,c,u,v,w)=>{
         if(depth>=this.tableDepth[i])return;this.tableDepth[i]=depth;
         const x=u*a[0]+v*b[0]+w*c[0],y=u*a[1]+v*b[1]+w*c[1],z=u*a[2]+v*b[2]+w*c[2];
         let light=1;
         if(mat===1){const edge=Math.min(x,L-x,y,W-y);
           light=(1.14-.30*Math.hypot((x/L-.5)*.85,y/W-.5))*(.94+.06*Math.min(1,Math.max(0,edge/.055)))*swatch(0,x/.097,y/.097);}
         else if(mat===10)light=swatch(0,(x+z*.85)/.097,(y+z*.85)/.097);
         else if(mat===2)light=swatch(1,(end?y:x)/.78,(flat?(end?x:y):z)/.062);
         else if(mat===4)light=swatch(2,(x+z*.8)/.057,(y+z*.8)/.057);
         const k=i*4;data[k]=color[0]*light;data[k+1]=color[1]*light;data[k+2]=color[2]*light;
       });
     }
     g.putImageData(image,0,0);
   }
   sprite(b,q,f){
     const num=Number(b.id)||0,axes=v=>[dot(v,f.right),dot(v,f.up),-dot(v,f.forward)];
     const pole=axes(rotate(q,[0,-.64,.768375])),band=axes(rotate(q,[0,.768375,.64])),lv=axes(light),half=unit(add(lv,[0,0,1]));
     const key=[...pole,...band,...lv].map(v=>Math.round(v*60)).join(),old=this.sprites.get(b.id);if(old?.key===key)return old;
     const c=old?.c||document.createElement('canvas');c.width=c.height=64;const g=c.getContext('2d'),pixels=g.createImageData(64,64);
     const h=ArenaRenderer.palette[num?(num-1)%8+1:0],tint=[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)),ivory=[246,240,217];
     for(let j=0;j<64;j++)for(let i=0;i<64;i++){
       let x=(i+.5)/32-1,y=1-(j+.5)/32;const d=x*x+y*y;
       if(d>1){const t=1/Math.sqrt(d);x*=t;y*=t;}
       const n=[x,y,Math.sqrt(Math.max(0,1-d))],label=Math.abs(dot(n,pole))>.85;
       const col=(num&&label)||(num>8&&Math.abs(dot(n,band))>.53)?ivory:tint;
       const shade=.48+.55*Math.max(0,dot(n,lv)),shine=105*Math.max(0,dot(n,half))**40,k=(j*64+i)*4;
       for(let ch=0;ch<3;ch++)pixels.data[k+ch]=col[ch]*shade+shine;
       pixels.data[k+3]=255;
     }
     g.putImageData(pixels,0,0);
     if(num&&Math.abs(pole[2])>.33){const side=Math.sign(pole[2]);g.save();g.translate(32+pole[0]*side*29,32-pole[1]*side*29);g.scale(.86,Math.max(.5,Math.abs(pole[2])));g.fillStyle='#18231e';g.textAlign='center';g.textBaseline='middle';g.font='bold 20px Arial';g.fillText(num,0,1);g.restore();}
     const sprite={key,c,pixels:g.getImageData(0,0,64,64).data};this.sprites.set(b.id,sprite);return sprite;
   }
   render(f,s){
     this.background(f,s.config);const g=this.g;g.drawImage(this.layer,0,0);
     if(s.trace)lines(g,f,s.trace.data,s.trace.count);const markings=ArenaRenderer.marks(s);lines(g,f,markings,markings.length/10);
     const objects=[];this.foreDepth.set(this.tableDepth);
     s.balls.forEach((b,i)=>{if(b.pocket)return;const r=b.spec.radius,{x,y}=b.position,center=[x,y,r],q=f.project(center);if(!q)return;
       const pts=Array.from({length:24},(_,j)=>f.project([x+.003+1.2*r*Math.cos(j*Math.PI/12),y-.003+1.16*r*Math.sin(j*Math.PI/12),.001]));
       polygon(g,pts,'#10271d65');objects.push({b,i,r,q,center});
     });
     const frame=g.getImageData(0,0,f.width,f.height),data=frame.data,depth=this.foreDepth;
     function paint(i,z,r,g,b,a){
       if(z>depth[i]+1e-7||a<=0)return;
       const k=i*4;data[k]+=a*(r-data[k]);data[k+1]+=a*(g-data[k+1]);data[k+2]+=a*(b-data[k+2]);depth[i]=z;
     }
     for(const {b,i,r,q,center} of objects){
       // The visible hemisphere points at the eye for this particular ball, including
       // at the edges of a wide display. Its silhouette comes from ray/sphere tangency.
       const view=f.ortho?mul(f.forward,-1):unit(sub(f.eye,center)),right=unit(cross(f.up,view)),up=cross(view,right);
       const sprite=this.sprite(b,s.rotations?.[i]||ArenaMath.identity,{right,up,forward:mul(view,-1)}).pixels;
       const axes=v=>[dot(f.right,v),dot(f.up,v),dot(f.forward,v)],sr=axes(right),su=axes(up);
       const offset=sub(center,f.eye),X=dot(offset,f.right),Y=dot(offset,f.up),Z=q.depth;
       const fac=f.height*.5*(f.ortho?1/f.ortho:f.lens),bounds=f.projectedSphere(center,r);
       if(!bounds)continue;
       const edgeBand=4*r*(f.ortho?1:Z)/fac;
       for(let y=Math.max(0,Math.floor(bounds.y0));y<=Math.min(f.height-1,Math.ceil(bounds.y1));y++)for(let x=Math.max(0,Math.floor(bounds.x0));x<=Math.min(f.width-1,Math.ceil(bounds.x1));x++){
         const dx=(x+.5-f.width/2)/fac,dy=(f.height/2-y-.5)/fac;
         const ax=f.ortho?X-dx:X,ay=f.ortho?Y-dy:Y,rx=f.ortho?0:dx,ry=f.ortho?0:dy;
         const A=rx*rx+ry*ry+1,B=ax*rx+ay*ry+Z,C=ax*ax+ay*ay+Z*Z-r*r,disc=B*B-A*C;
         let alpha=1;
         if(disc<edgeBand){
           const gradient=f.ortho?2*Math.hypot(ax,ay)/fac:2*Math.hypot(B*ax-rx*C,B*ay-ry*C)/fac;
           alpha=Math.min(1,.5+disc/Math.max(gradient,1e-12));if(alpha<=0)continue;
         }
         const z=(B-Math.sqrt(Math.max(0,disc)))/A;
         const u=(rx*z-ax)/r,v=(ry*z-ay)/r,nz=(z-Z)/r;
         const nx=sr[0]*u+sr[1]*v+sr[2]*nz,ny=su[0]*u+su[1]*v+su[2]*nz;
         const sx=Math.max(0,Math.min(63,Math.floor(32+nx*31.8))),sy=Math.max(0,Math.min(63,Math.floor(32-ny*31.8))),k=4*(sy*64+sx);
         paint(y*f.width+x,z,sprite[k],sprite[k+1],sprite[k+2],alpha);
       }
     }
     if(s.cuePose){
       const {position,axis}=s.cuePose,grain=ArenaCue.woodTexture(),m=this.cue;
       const transform=(p,translate)=>[0,1,2].map(k=>(translate?position[k]:0)+axis[k]*p[0]+axis[k+3]*p[1]+axis[k+6]*p[2]);
       for(let i=0;i<m.length;i+=30){
         const verts=[i,i+10,i+20],local=verts.map(j=>m.slice(j,j+3)),world=local.map(p=>transform(p,true));
         const normals=verts.map(j=>transform(m.slice(j+3,j+6),false));
         if(normals.every((n,j)=>dot(n,sub(f.eye,world[j]))<0))continue;
         const attr=local.map((p,j)=>[...p,.55+.50*Math.max(0,dot(normals[j],light))]);
         const mat=m[i+9],color=m.slice(i+6,i+9).map(c=>255*c);
         raster(f,world.map((p,j)=>cameraVertex(f,p,attr[j])),(idx,z,a,b,c,u,v,w)=>{
           if(z>depth[idx]+1e-7)return;
           const blend=k=>u*a[k]+v*b[k]+w*c[k],shade=blend(3);
           if(mat!==11){paint(idx,z,color[0]*shade,color[1]*shade,color[2]*shade,s.stroke.alpha);return;}
           const angle=Math.atan2(blend(2),blend(1))/(2*Math.PI);
           const tx=Math.max(0,Math.min(grain.width-1,Math.floor(-blend(0)/ArenaCue.length*grain.width)));
           const ty=Math.floor((angle-Math.floor(angle))*grain.height),j=3*(ty*grain.width+tx),p=grain.bytes;
           paint(idx,z,p[j]*shade,p[j+1]*shade,p[j+2]*shade,s.stroke.alpha);
         });
       }
     }
     g.putImageData(frame,0,0);
   }
 }
 root.ArenaSoftware=SoftwareRenderer;
})(globalThis);
