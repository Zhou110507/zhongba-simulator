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
     const points=[i,i+10,i+20].map(j=>a.slice(j,j+3)),normal=a.slice(i+3,i+6),shade=.55+.48*Math.max(0,dot(normal,light));
     const rgb=a.slice(i+6,i+9).map(v=>Math.round(v*255*shade));
     const height=Math.max(...points.map(p=>p[2]));
     output.push({points,normal,center:mul(add(add(points[0],points[1]),points[2]),1/3),col:'rgb('+rgb.join(',')+')',
       layer:height<-.23?0:height<0?1:mat===8?2:mat===1?3:mat===10?5:4});
   }
   return output;
 }
 function segment(g,f,a,b,c,width=1){
   const p=f.project(a),q=f.project(b);if(!p||!q)return;
   g.beginPath();g.moveTo(p.x,p.y);g.lineTo(q.x,q.y);g.strokeStyle=c;g.lineWidth=width;g.stroke();
 }
 function lines(g,f,data,count){for(let i=0;i<count*10;i+=20){const col=[6,7,8].map(j=>Math.round(data[i+j]*255));segment(g,f,data.slice(i,i+3),data.slice(i+10,i+13),'rgb('+col.join(',')+')');}}
 function rotate(q,p){const v=q.slice(0,3);return add(p,mul(cross(v,add(cross(v,p),mul(p,q[3]))),2));}
 class SoftwareRenderer{
   constructor(canvas){this.g=canvas.getContext('2d');this.layer=document.createElement('canvas');this.sprites=new Map();}
   background(f,config){
     if(this.model!==config.model_signature){this.triangles=faces(ArenaRenderer.tableMesh(config));this.model=config.model_signature;this.key='';}
     const key=[f.width,f.height,...f.eye,...f.forward,f.ortho].join();if(key===this.key)return;this.key=key;
     const l=this.layer;l.width=f.width;l.height=f.height;const g=l.getContext('2d');
     const grad=g.createRadialGradient(f.width*.49,f.height*.35,0,f.width*.5,f.height*.5,.8*f.width);grad.addColorStop(0,'#404d43');grad.addColorStop(.65,'#28332c');grad.addColorStop(1,'#131e19');g.fillStyle=grad;g.fillRect(0,0,l.width,l.height);
     for(let j=-12;j<=15;j++){segment(g,f,[j*.46,-8,-.83],[j*.46,8,-.83],'#63736921');segment(g,f,[-8,j*.46,-.83],[8,j*.46,-.83],'#63736919');}
     const sorted=this.triangles.filter(face=>dot(face.normal,sub(f.eye,face.center))>=-.001).map(face=>({face,depth:dot(sub(face.center,f.eye),f.forward)}))
       .sort((a,b)=>a.face.layer-b.face.layer||b.depth-a.depth);
     for(const {face} of sorted)polygon(g,face.points.map(f.project),face.col,true);
   }
   sprite(b,q,f){
     const num=Number(b.id)||0,axes=v=>[dot(v,f.right),dot(v,f.up),-dot(v,f.forward)];
     const pole=axes(rotate(q,[0,-.64,.768375])),band=axes(rotate(q,[0,.768375,.64])),lv=axes(light),half=unit(add(lv,[0,0,1]));
     const key=[...pole,...band,...lv].map(v=>Math.round(v*60)).join(),old=this.sprites.get(b.id);if(old?.key===key)return old.c;
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
     this.sprites.set(b.id,{key,c});return c;
   }
   render(f,s){
     this.background(f,s.config);const g=this.g;g.drawImage(this.layer,0,0);
     if(s.trace)lines(g,f,s.trace.data,s.trace.count);const markings=ArenaRenderer.marks(s);lines(g,f,markings,markings.length/10);
     const queue=[];
     s.balls.forEach((b,i)=>{if(b.pocket)return;const r=b.spec.radius,{x,y}=b.position,q=f.project([x,y,r]);if(!q)return;
       const rad=r*f.height*.5/(f.ortho||q.depth/f.lens);
       const pts=Array.from({length:24},(_,k)=>f.project([x+.003+1.2*r*Math.cos(k*Math.PI/12),y-.003+1.16*r*Math.sin(k*Math.PI/12),.001]));
       polygon(g,pts,'#10271d65');queue.push({depth:q.depth,draw:()=>g.drawImage(this.sprite(b,s.rotations?.[i]||ArenaMath.identity,f),q.x-rad,q.y-rad,2*rad,2*rad)});
     });
     if(s.stroke&&s.cue&&!s.cue.pocket){
       const {position,axis}=ArenaRenderer.cueParts(s.cue,s.shot,s.stroke),at=t=>sub(position,mul(axis.slice(0,3),t));
       const bands=[[0,'#608079'],[.004,'#c4a978'],[.013,'#dfbf85'],[.92,'#a37d51'],[1.09,'#42332b'],[1.44,'#282924'],[CueVisual.length,null]];
       for(let i=0;i<bands.length-1;i++){
         const [start,col]=bands[i],end=bands[i+1][0],p=f.project(at((start+end)/2));if(!p)continue;
         const w=(CueVisual.tipDiameter+(CueVisual.buttDiameter-CueVisual.tipDiameter)*(start/CueVisual.length)**.78)*f.height*.5/(f.ortho||p.depth/f.lens);
         queue.push({depth:p.depth,draw:()=>{g.globalAlpha=s.stroke.alpha;segment(g,f,at(start),at(end),col,Math.max(1,w));g.globalAlpha=1;}});
       }
     }
     queue.sort((a,b)=>b.depth-a.depth).forEach(obj=>obj.draw());
   }
 }
 root.ArenaSoftware=SoftwareRenderer;
})(globalThis);
