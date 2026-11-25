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
   const a=mesh.data,output=[];
   for(let i=0;i<a.length;i+=30){
     const mat=a[i+9];if(mat===6)continue;
     const points=[i,i+10,i+20].map(j=>a.slice(j,j+3)),normal=a.slice(i+3,i+6),shade=.54+.49*Math.max(0,dot(normal,light))+.065*Math.max(0,dot(normal,[.5,-.7,.45]));
     const rgb=a.slice(i+6,i+9).map(v=>Math.round(v*255*shade));
     const height=Math.max(...points.map(p=>p[2]));
     output.push({points,normal,mat,center:mul(add(add(points[0],points[1]),points[2]),1/3),color:rgb,
       layer:height<-.23?0:height<0?1:mat===8?2:mat===1?3:mat===10?5:4});
   }
   return output;
 }
 // Clip triangles crossing the eye plane. Interpolate attributes with reciprocal depth.
 function raster(f,points,attributes,fragment){
   const depths=points.map(p=>dot(sub(p,f.eye),f.forward));
   if(depths.every(d=>d<.034))return;
   let vertices=points.map((p,i)=>({p,d:depths[i],v:attributes?.[i]}));
   if(depths.some(d=>d<.034)){
     const clipped=[];
     for(let j=0;j<3;j++){
       const a=vertices[j],b=vertices[(j+1)%3];if(a.d>=.034)clipped.push(a);
       if((a.d>=.034)!==(b.d>=.034)){const t=(.034-a.d)/(b.d-a.d);clipped.push({p:a.p.map((x,k)=>x+(b.p[k]-x)*t),d:.034,v:a.v?.map((x,k)=>x+(b.v[k]-x)*t)});}
     }
     vertices=clipped;
   }
   const screen=vertices.map(a=>({...f.project(a.p),q:f.ortho?1:1/a.d,v:a.v,d:a.d}));
   for(let j=1;j<screen.length-1;j++){
     const [a,b,c]=[screen[0],screen[j],screen[j+1]],bx=b.x-a.x,by=b.y-a.y,cx=c.x-a.x,cy=c.y-a.y,det=bx*cy-by*cx;
     if(Math.abs(det)<1e-7)continue;
     const x0=Math.max(0,Math.ceil(Math.min(a.x,b.x,c.x)-.5)),x1=Math.min(f.width-1,Math.floor(Math.max(a.x,b.x,c.x)-.5));
     const y0=Math.max(0,Math.ceil(Math.min(a.y,b.y,c.y)-.5)),y1=Math.min(f.height-1,Math.floor(Math.max(a.y,b.y,c.y)-.5));
     for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
       const px=x+.5-a.x,py=y+.5-a.y,u=(px*cy-py*cx)/det,v=(bx*py-by*px)/det,w=1-u-v;
       if(Math.min(u,v,w)<-1e-8)continue;
       const scale=1/(w*a.q+u*b.q+v*c.q),depth=f.ortho?w*a.d+u*b.d+v*c.d:scale;
       fragment(y*f.width+x,depth,a.v,b.v,c.v,w*a.q*scale,u*b.q*scale,v*c.q*scale);
     }
   }
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
     if(this.model!==config.model_signature){this.triangles=faces(ArenaRenderer.tableMesh(config));this.model=config.model_signature;this.key='';}
     const key=[f.width,f.height,...f.eye,...f.forward,f.ortho].join();if(key===this.key)return;this.key=key;
     const l=this.layer;l.width=f.width;l.height=f.height;const g=l.getContext('2d');
     const grad=g.createRadialGradient(f.width*.49,f.height*.35,0,f.width*.5,f.height*.5,.8*f.width);grad.addColorStop(0,'#404d43');grad.addColorStop(.65,'#28332c');grad.addColorStop(1,'#131e19');g.fillStyle=grad;g.fillRect(0,0,l.width,l.height);
     for(let j=-12;j<=15;j++){segment(g,f,[j*.46,-8,-.83],[j*.46,8,-.83],'#63736921');segment(g,f,[-8,j*.46,-.83],[8,j*.46,-.83],'#63736919');}
     const image=g.getImageData(0,0,l.width,l.height),data=image.data;
     this.tableDepth=new Float32Array(l.width*l.height);this.tableDepth.fill(Infinity);
     this.foreDepth=new Float32Array(this.tableDepth.length);
     const finish=ArenaTable.finishes(),{length:L,width:W}=config.model.table;
     function swatch(row,x,y){
       const ix=(Math.floor(x*128)%128+128)%128,iy=(Math.floor(y*128)%128+128)%128;
       return finish.bytes[3*((row*128+iy)*128+ix)]/218;
     }
     for(const face of this.triangles){
       if(dot(face.normal,sub(f.eye,face.center))<-.001)continue;
       const color=face.color;
       const end=Math.min(face.center[0],L-face.center[0])<Math.min(face.center[1],W-face.center[1]);
       const flat=Math.abs(face.normal[2])>.65,mat=face.mat;
       raster(f,face.points,face.points,(i,depth,a,b,c,u,v,w)=>{
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
       const x=(i+.5)/32-1,y=1-(j+.5)/32,d=x*x+y*y;if(d>=1)continue;
       const n=[x,y,Math.sqrt(1-d)],label=Math.abs(dot(n,pole))>.85;
       const col=(num&&label)||(num>8&&Math.abs(dot(n,band))>.53)?ivory:tint;
       const shade=.48+.55*Math.max(0,dot(n,lv)),shine=105*Math.max(0,dot(n,half))**40,k=(j*64+i)*4;
       for(let ch=0;ch<3;ch++)pixels.data[k+ch]=col[ch]*shade+shine;
       pixels.data[k+3]=Math.min(255,(1-Math.sqrt(d))*32*255);
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
       const rad=r*f.height*.5/(f.ortho||q.depth/f.lens);
       const pts=Array.from({length:24},(_,j)=>f.project([x+.003+1.2*r*Math.cos(j*Math.PI/12),y-.003+1.16*r*Math.sin(j*Math.PI/12),.001]));
       polygon(g,pts,'#10271d65');objects.push({b,i,r,q,rad,center});
     });
     const frame=g.getImageData(0,0,f.width,f.height),data=frame.data,depth=this.foreDepth;
     function paint(i,z,r,g,b,a){
       if(z>depth[i]+1e-7||a<=0)return;
       const k=i*4;data[k]+=a*(r-data[k]);data[k+1]+=a*(g-data[k+1]);data[k+2]+=a*(b-data[k+2]);depth[i]=z;
     }
     for(const {b,i,r,q,rad,center} of objects){
       const sprite=this.sprite(b,s.rotations?.[i]||ArenaMath.identity,f).pixels;
       const offset=sub(center,f.eye),X=dot(offset,f.right),Y=dot(offset,f.up),Z=q.depth;
       const fac=f.height*.5*(f.ortho?1/f.ortho:f.lens),extent=rad*(f.ortho?1:1.25);
       for(let y=Math.max(0,Math.floor(q.y-extent));y<=Math.min(f.height-1,Math.ceil(q.y+extent));y++)for(let x=Math.max(0,Math.floor(q.x-extent));x<=Math.min(f.width-1,Math.ceil(q.x+extent));x++){
         const dx=(x+.5-f.width/2)/fac,dy=(f.height/2-y-.5)/fac;
         const ax=f.ortho?X-dx:X,ay=f.ortho?Y-dy:Y,rx=f.ortho?0:dx,ry=f.ortho?0:dy;
         const A=rx*rx+ry*ry+1,B=ax*rx+ay*ry+Z,C=ax*ax+ay*ay+Z*Z-r*r,disc=B*B-A*C;
         if(disc<0)continue;const z=(B-Math.sqrt(disc))/A;
         const nx=(rx*z-ax)/r,ny=(ry*z-ay)/r;
         const sx=Math.max(0,Math.min(63,Math.floor(32+nx*31.8))),sy=Math.max(0,Math.min(63,Math.floor(32-ny*31.8))),k=4*(sy*64+sx);
         paint(y*f.width+x,z,sprite[k],sprite[k+1],sprite[k+2],sprite[k+3]/255);
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
         raster(f,world,attr,(idx,z,a,b,c,u,v,w)=>{
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
