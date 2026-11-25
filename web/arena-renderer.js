'use strict';
(function(root){
 const {add,sub,mul,cross,unit}=ArenaMath,TAU=2*Math.PI;
 const palette=['#fcf5e2','#e3ac19','#2057bd','#c93738','#8051a6','#e77521','#137556','#882c43','#171d21'];
 const rgb=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255);
 const cloth=1,wood=2,metal=3,leather=4,ball=5,floor=6,ink=7,well=8,shadow=9,rubber=10;
 class Mesh{
   constructor(){this.data=[];}
   tri(a,b,c,col,mat,n=unit(cross(sub(b,a),sub(c,a)))){for(const v of [a,b,c])this.data.push(...v,...n,...col,mat);}
   quad(a,b,c,d,col,mat,n){this.tri(a,b,c,col,mat,n);this.tri(a,c,d,col,mat,n);}
   box(x,y,z,X,Y,Z,col,mat){
     const a=[x,y,z],b=[X,y,z],c=[X,Y,z],d=[x,Y,z],e=[x,y,Z],f=[X,y,Z],g=[X,Y,Z],h=[x,Y,Z];
     this.quad(e,f,g,h,col,mat,[0,0,1]);this.quad(a,b,f,e,col,mat,[0,-1,0]);this.quad(b,c,g,f,col,mat,[1,0,0]);
     this.quad(c,d,h,g,col,mat,[0,1,0]);this.quad(d,a,e,h,col,mat,[-1,0,0]);this.quad(a,d,c,b,col,mat,[0,0,-1]);
   }
   tube(a,b,r0,r1,col,mat,steps=24){
     const axis=unit(sub(b,a)),u=unit(cross(axis,Math.abs(axis[2])>.9?[0,1,0]:[0,0,1])),v=cross(axis,u);
     const normal=k=>add(mul(u,Math.cos(TAU*k/steps)),mul(v,Math.sin(TAU*k/steps)));
     for(let i=0;i<steps;i++){
       const n=normal(i),m=normal(i+1),p=add(a,mul(n,r0)),q=add(a,mul(m,r0)),r=add(b,mul(m,r1)),s=add(b,mul(n,r1));
       for(const [vertex,side] of [[p,n],[q,m],[r,m],[p,n],[r,m],[s,n]])this.data.push(...vertex,...side,...col,mat);
       this.tri(a,q,p,col,mat,mul(axis,-1));this.tri(b,s,r,col,mat,axis);
     }
   }
   disk(x,y,z,r,col,mat){
     const p=i=>[x+r*Math.cos(i*TAU/48),y+r*Math.sin(i*TAU/48),z];
     for(let i=0;i<48;i++)this.tri([x,y,z],p(i),p(i+1),col,mat,[0,0,1]);
   }
 }
 // Tile the slate into six rectangular patches, each with a round aperture.
 // The outer ring includes each rectangle corner so adjacent patches meet.
 function pocketPatch(mesh,p,box){
   const {x,y}=p.fall_center,r=p.fall_radius,[x0,y0,x1,y1]=box;
   const angles=Array.from({length:48},(_,i)=>i*TAU/48);
   for(const X of [x0,x1])for(const Y of [y0,y1])angles.push((Math.atan2(Y-y,X-x)+TAU)%TAU);
   angles.sort((a,b)=>a-b);
   const ring=angles.map(a=>{
     const dx=Math.cos(a),dy=Math.sin(a);
     const tx=Math.abs(dx)<1e-9?Infinity:((dx<0?x0:x1)-x)/dx,ty=Math.abs(dy)<1e-9?Infinity:((dy<0?y0:y1)-y)/dy;
     const d=Math.min(tx,ty);
     return {edge:[x+d*dx,y+d*dy,0],rim:[x+r*dx,y+r*dy,0],bottom:[x+r*.80*dx,y+r*.8*dy,-.085]};
   });
   for(let i=0;i<ring.length;i++){
     const a=ring[i],b=ring[(i+1)%ring.length];
     mesh.quad(a.rim,a.edge,b.edge,b.rim,rgb('#168668'),cloth,[0,0,1]);
     mesh.quad(a.rim,b.rim,b.bottom,a.bottom,rgb('#202923'),well);
   }
   mesh.disk(x,y,-.085,r*.81,rgb('#091110'),well);
 }
 function tableMesh(config){
   const mesh=new Mesh(),{length:l,width:w}=config.model.table;
   const timber=rgb('#76513b'),gold=rgb('#b69b60'),dark=rgb('#242825'),green=rgb('#1f735b'),ivory=rgb('#eee3c1');
   mesh.box(-13,-13,-.84,l+13,w+13,-.83,rgb('#333b36'),floor);
   for(const x of [.13,l-.13])for(const y of [.09,w-.09]){
     const rings=[[-.83,.078],[-.806,.090],[-.78,.083],[-.76,.065],[-.63,.054],[-.55,.072],[-.53,.086],[-.50,.080],[-.48,.068],[-.39,.091],[-.35,.099],[-.18,.096]];
     for(let i=1;i<rings.length;i++){const [z,r]=rings[i],[a,b]=rings[i-1],brass=i===2||i===7;mesh.tube([x,y,a],[x,y,z],b,r,brass?gold:timber,brass?metal:wood);}
   }
   mesh.box(-.115,-.107,-.225,l+.115,w+.107,-.092,timber,wood);
   mesh.box(-.118,-.11,-.202,l+.118,w+.11,-.197,gold,metal);
   for(const y of [-.11,w+.11])for(let i=0;i<3;i++){
     const x=.09+i*l/3;mesh.box(x,y-.001,-.168,x+l/3-.18,y+.001,-.121,rgb('#503629'),wood);
   }
   const rim=(x,y,X,Y)=>{
     mesh.box(x,y,-.10,X,Y,.01,dark,leather);mesh.box(x,y,-.054,X,Y,-.05,gold,metal);mesh.box(x,y,.012,X,Y,.048,timber,wood);
   };
   for(const y of [-.136,w+.052])for(const [x,X] of [[.060,l/2-.08],[l/2+.08,l-.060]])rim(x,y,X,y+.084);
   for(const x of [-.14,l+.052])rim(x,.06,x+.088,w-.06);
   const xs=[-.096,l*.25,l*.75,l+.096],ys=[-.096,w*.5,w+.096];
   for(const p of config.geometry.pockets){
     const col=p.outward.x<-.1?0:p.outward.x>.1?2:1,row=p.outward.y<0?0:1;
     pocketPatch(mesh,p,[xs[col],ys[row],xs[col+1],ys[row+1]]);
     const x=col===1?l/2:col===0?-.08:l+.08,y=row===0?-.105:w+.105;
     const hw=col===1?.087:.060;
     mesh.box(x-hw,y-.025,.01,x+hw,y+.025,.052,rgb('#ab915e'),metal);
   }
   for(const rail of config.geometry.surfaces){
     const a=rail.start,b=rail.end;
     if(rail.radius){
       const angle=Math.atan2(b.y-a.y,b.x-a.x),outline=[];
       for(const [p,start] of [[b,angle-Math.PI/2],[a,angle+Math.PI/2]])for(let i=0;i<=12;i++){
         const t=start+Math.PI*i/12;outline.push([p.x+rail.radius*Math.cos(t),p.y+rail.radius*Math.sin(t)]);
       }
       const center=[(a.x+b.x)/2,(a.y+b.y)/2,.036];
       outline.forEach((p,i)=>{const q=outline[(i+1)%outline.length];mesh.tri(center,[...p,.036],[...q,.036],green,rubber,[0,0,1]);mesh.quad([...p,.001],[...q,.001],[...q,.036],[...p,.036],green,rubber);});
     }else{
       const out=rail.id.startsWith('bottom')?[0,-1]:rail.id.startsWith('top')?[0,1]:rail.id==='left'?[-1,0]:[1,0];
       const edge=(p,d,z)=>[p.x+d*out[0],p.y+d*out[1],z];
       mesh.quad(edge(a,0,.033),edge(b,0,.033),edge(b,.058,.046),edge(a,.058,.046),green,rubber,[-out[0]*.22,-out[1]*.22,.975]);
       mesh.quad(edge(a,.003,0),edge(b,.003,0),edge(b,0,.033),edge(a,0,.033),green,rubber,[-out[0],-out[1],0]);
     }
   }
   function sight(x,y,dx,dy){mesh.quad([x-dx,y,.049],[x,y-dy,.049],[x+dx,y,.049],[x,y+dy,.049],ivory,metal,[0,0,1]);}
   for(let k=1;k<8;k++)if(k!==4)for(const y of [-.09,w+.09])sight(l*k/8,y,.009,.004);
   for(let k=1;k<4;k++)for(const x of [-.09,l+.09])sight(x,w*k/4,.004,.009);
   for(const x of [l*.25,l*.75])mesh.disk(x,w/2,.001,.003,ivory,ink);
   return mesh;
 }
 function sphere(){
   const mesh=new Mesh(),stacks=22,slices=40,point=(i,j)=>{const a=i*Math.PI/stacks,b=j*TAU/slices;return [Math.sin(a)*Math.cos(b),Math.sin(a)*Math.sin(b),Math.cos(a)];};
   for(let i=0;i<stacks;i++)for(let j=0;j<slices;j++){
     const a=point(i,j),b=point(i+1,j),c=point(i+1,j+1),d=point(i,j+1);
     for(const p of [a,b,c,a,c,d])mesh.data.push(...p,...p,1,1,1,ball);
   }
   return mesh;
 }
 function cueParts(cue,shot,stroke){
   const a=shot.angle_deg*Math.PI/180,dx=Math.cos(a),dy=Math.sin(a),r=cue.spec.radius;
   const gap=r*Math.sqrt(Math.max(0,1-shot.tip_x**2-shot.tip_y**2))+stroke.gap,side=r*shot.tip_x;
   return {position:[cue.position.x-dx*gap+dy*side,cue.position.y-dy*gap-dx*side,r*(1+shot.tip_y)],axis:[dx,dy,0,-dy,dx,0,0,0,1]};
 }
 function cueMesh(dim){
   const mesh=new Mesh(),l=dim.length,tip=dim.tipDiameter/2,butt=dim.buttDiameter/2;
   const bands=[[0,'#607a72'],[.004,'#c6ab80'],[.013,'#deb97e'],[.91,'#a68151'],[1.08,'#46392e'],[1.12,'#b09c68'],[1.126,'#392e28'],[l-.014,'#222724'],[l,null]];
   const radius=t=>tip+(butt-tip)*(t/l)**.78;
   for(let i=0;i<bands.length-1;i++){const [x,col]=bands[i],end=bands[i+1][0];mesh.tube([-x,0,0],[-end,0,0],radius(x),radius(end),rgb(col),i===1||i===5?metal:wood,24);}
   return mesh;
 }
 function marks(state){
   const data=[],seg=(a,b,c)=>{for(const v of [a,b])data.push(...v,0,0,1,...c,ink);};
   const ring=(p,r,z,col)=>{const v=i=>[p.x+r*Math.cos(i*TAU/48),p.y+r*Math.sin(i*TAU/48),z];for(let i=0;i<48;i++)seg(v(i),v(i+1),col);};
   if(state.head){const w=state.config.model.table.width;for(let y=.012;y<w;y+=.043)seg([.635,y,.001],[.635,Math.min(w,y+.023),.001],[.70,.79,.67]);}
   const g=state.guide;
   if(g){const p=g.start,q=g.center,dx=q.x-p.x,dy=q.y-p.y,len=Math.hypot(dx,dy);
     for(let d=.035;d<len;d+=.037){const e=Math.min(d+.023,len);seg([p.x+dx*d/len,p.y+dy*d/len,g.radius],[p.x+dx*e/len,p.y+dy*e/len,g.radius],[.85,.9,.76]);}
     ring(q,['ball_ball','ball_cushion'].includes(g.kind)?g.radius:.008,.002,[.81,.92,.75]);
     if(g.target)seg([q.x,q.y,g.radius],[g.target.x,g.target.y,g.radius],[.69,.87,.71]);
   }
   const b=state.balls.find(b=>b.id===state.selected&&!b.pocket);if(b)ring(b.position,b.spec.radius*1.23,.002,[.95,.78,.43]);return data;
 }
 const vertex=[
  'attribute vec3 pos,normal,color;attribute float material;uniform vec3 eye,right,up,forward,shift;uniform mat3 basis;uniform vec4 quat;uniform float lens,aspect,ortho;',
  'varying vec3 c,n,world,local;varying float mat;',
  'vec3 rot(vec3 p){return p+2.*cross(quat.xyz,cross(quat.xyz,p)+quat.w*p);}',
  'void main(){world=basis*rot(pos)+shift;n=normalize(basis*rot(normal));local=pos;c=color;mat=material;vec3 d=world-eye;float depth=dot(d,forward);vec2 fly=vec2(dot(d,right)/aspect,dot(d,up));',
  'if(ortho>0.)gl_Position=vec4(fly/ortho,2.*(depth-.025)/39.975-1.,1.);else gl_Position=vec4(fly*lens,1.001251*depth-.050031,depth);}'
 ].join('\n');
 const fragment=[
  'precision highp float;varying vec3 c,n,world,local;varying float mat;uniform vec3 eye,tint;uniform vec2 size;uniform float number,opacity;uniform sampler2D atlas;',
  'float noise(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}',
  'void main(){vec3 col=c,N=normalize(n),V=normalize(eye-world);float gloss=.03;',
  'if(mat>.5&&mat<1.5){col*=1.13-.30*length((world.xy/size-.5)*vec2(.85,1.));col+=.008*(noise(floor(world.xy*1400.))-.5);}',
  'if(mat>1.5&&mat<2.5){float across=abs(N.z)>.7?(abs(world.x-size.x*.5)>size.x*.5?world.x:world.y):world.z;col*=.95+.075*sin(across*825.+3.1*sin((world.x+world.y)*7.));gloss=.14;}',
  'if(mat>2.5&&mat<3.5)gloss=.38;',
  'if(mat>4.5&&mat<5.5){vec3 p=normalize(local),pole=vec3(0.,-.64,.768375),band=vec3(0.,.768375,.64);float side=dot(p,pole);col=tint;',
  'if(number>8.5)col=mix(col,vec3(.96,.93,.84),smoothstep(.51,.55,abs(dot(p,band))));',
  'if(number>.5&&abs(side)>.85){vec2 uv=vec2(p.x*sign(side),-dot(p,band))/.99+.5;vec2 cell=vec2(mod(number,4.),floor(number/4.));col=mix(col,texture2D(atlas,(cell+clamp(uv,.01,.99))/4.).rgb,smoothstep(.85,.88,abs(side)));}',
  'if(number<.5&&(abs(p.x)>.985||abs(p.y)>.985||abs(p.z)>.985))col=vec3(.68,.14,.12);gloss=.50;}',
  'if(mat>5.5&&mat<6.5){vec2 tile=world.xy*vec2(2.5,3.6);tile.x+=.5*mod(floor(tile.y),2.);vec2 e=min(fract(tile),1.-fract(tile));vec2 dst=max(abs(world.xy-size*.5)-size*.47,vec2(0.));col*=mix(.36,.90,smoothstep(.02,.7,length(dst)))*(.8+.2*smoothstep(0.,.016,min(e.x,e.y)));}',
  'if(mat>6.5&&mat<7.5){gl_FragColor=vec4(col,opacity);return;}if(mat>8.5&&mat<9.5){gl_FragColor=vec4(.01,.04,.025,.58*(1.-smoothstep(.1,1.,length(local.xy))));return;}',
  'vec3 L=normalize(vec3(-.36,.22,.91)),H=normalize(L+V);vec3 outCol=col*(.54+.49*max(0.,dot(N,L))+.08*max(0.,dot(N,normalize(vec3(.5,-.7,.45)))))+gloss*pow(max(0.,dot(N,H)),48.)*vec3(1.,.94,.81);',
  'if(mat>4.5&&mat<5.5){vec3 R=reflect(-V,N);outCol+=vec3(.5,.57,.52)*smoothstep(.64,.71,R.z)*smoothstep(.95,.99,1.-abs(R.y-.22))*(1.-smoothstep(.57,.67,abs(R.x)));}',
  'if(mat>5.5&&mat<6.5)outCol=mix(outCol,vec3(.064,.079,.076),smoothstep(2.,8.,length(world.xy-size*.5)));gl_FragColor=vec4(outCol,opacity);}'
 ].join('\n');
 function atlas(){
   const c=document.createElement('canvas');c.width=c.height=512;const g=c.getContext('2d');g.fillStyle='#f6efd9';g.fillRect(0,0,512,512);
   g.fillStyle='#18211e';g.textAlign='center';g.textBaseline='middle';g.font='bold 72px Arial';
   for(let n=1;n<=15;n++)g.fillText(String(n),(n%4+.5)*128,(Math.floor(n/4)+.52)*128);return c;
 }
 const I=[1,0,0,0,1,0,0,0,1],Q=[0,0,0,1];
 class Renderer{
   constructor(canvas,dim){
     const gl=canvas.getContext('webgl',{alpha:false,antialias:true,powerPreference:'low-power'});if(!gl)throw Error('WebGL unavailable');
     const program=gl.createProgram();this.gl=gl;
     for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]){
       const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));gl.attachShader(program,s);
     }
     gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
     this.a=['pos','normal','color','material'].map(k=>gl.getAttribLocation(program,k));this.a.forEach(i=>gl.enableVertexAttribArray(i));
     this.u=Object.fromEntries('eye right up forward shift basis quat lens aspect ortho tint number opacity atlas size'.split(' ').map(k=>[k,gl.getUniformLocation(program,k)]));
     this.ball=this.upload(sphere());this.cue=this.upload(cueMesh(dim));
     const disk=new Mesh();disk.disk(0,0,0,1,[1,1,1],shadow);this.shadow=this.upload(disk);
     this.dynamic=gl.createBuffer();this.traces=gl.createBuffer();
     gl.bindTexture(gl.TEXTURE_2D,gl.createTexture());gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,gl.RGB,gl.UNSIGNED_BYTE,atlas());gl.generateMipmap(gl.TEXTURE_2D);
     gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
     gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
   }
   upload(m){const gl=this.gl,buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(m.data),gl.STATIC_DRAW);return {buffer,count:m.data.length/10};}
   bind(buffer){const gl=this.gl;gl.bindBuffer(gl.ARRAY_BUFFER,buffer);this.a.forEach((idx,i)=>gl.vertexAttribPointer(idx,i===3?1:3,gl.FLOAT,false,40,i*12));}
   pose(p=[0,0,0],b=I,q=Q){const gl=this.gl,u=this.u;gl.uniform3fv(u.shift,p);gl.uniformMatrix3fv(u.basis,false,b);gl.uniform4fv(u.quat,q);}
   draw(m){this.bind(m.buffer);this.gl.drawArrays(this.gl.TRIANGLES,0,m.count);}
   render(f,state){
     const gl=this.gl,u=this.u,{config,balls,rotations,trace}=state,t=config.model.table;
     if(this.model!==config.model_signature){if(this.table)gl.deleteBuffer(this.table.buffer);this.table=this.upload(tableMesh(config));this.model=config.model_signature;gl.uniform2f(u.size,t.length,t.width);}
     gl.viewport(0,0,gl.canvas.width,gl.canvas.height);gl.clearColor(.065,.08,.075,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
     for(const k of ['eye','right','up','forward'])gl.uniform3fv(u[k],f[k]);for(const k of ['lens','aspect','ortho'])gl.uniform1f(u[k],f[k]);
     this.pose();gl.uniform1f(u.opacity,1);this.draw(this.table);
     if(trace?.count){if(trace.data!==this.traceData){gl.bindBuffer(gl.ARRAY_BUFFER,this.traces);gl.bufferData(gl.ARRAY_BUFFER,trace.data,gl.STATIC_DRAW);this.traceData=trace.data;}this.bind(this.traces);gl.drawArrays(gl.LINES,0,trace.count);}
     const guide=marks(state);
     if(guide.length){this.bind(this.dynamic);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(guide),gl.DYNAMIC_DRAW);gl.drawArrays(gl.LINES,0,guide.length/10);}
     this.bind(this.shadow.buffer);gl.depthMask(false);
     for(const b of balls)if(!b.pocket){const r=b.spec.radius;this.pose([b.position.x+.003,b.position.y-.003,.0008],[r*1.40,0,0,0,r*1.24,0,0,0,1]);gl.drawArrays(gl.TRIANGLES,0,this.shadow.count);}
     gl.depthMask(true);this.bind(this.ball.buffer);
     balls.forEach((b,i)=>{if(b.pocket)return;const r=b.spec.radius,num=Number(b.id)||0;
       this.pose([b.position.x,b.position.y,r],[r,0,0,0,r,0,0,0,r],rotations?.[i]||Q);
       gl.uniform3fv(u.tint,rgb(palette[num?(num-1)%8+1:0]));gl.uniform1f(u.number,num);gl.drawArrays(gl.TRIANGLES,0,this.ball.count);});
     if(state.stroke&&state.cue&&!state.cue.pocket){const v=cueParts(state.cue,state.shot,state.stroke);this.pose(v.position,v.axis);gl.uniform1f(u.opacity,state.stroke.alpha);this.draw(this.cue);}
   }
 }
 root.ArenaRenderer={Renderer,palette,tableMesh,cueMesh,cueParts,marks};
})(globalThis);
