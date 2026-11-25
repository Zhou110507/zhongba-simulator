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
 const models=new WeakMap();
 function table(config){if(!models.has(config))models.set(config,ArenaTable.geometry(config,Mesh));return models.get(config);}
 function tableMesh(config){return table(config).mesh;}
 function sphere(){
   const mesh=new Mesh(),stacks=22,slices=40,point=(i,j)=>{const a=i*Math.PI/stacks,b=j*TAU/slices;return [Math.sin(a)*Math.cos(b),Math.sin(a)*Math.sin(b),Math.cos(a)];};
   for(let i=0;i<stacks;i++)for(let j=0;j<slices;j++){
     const a=point(i,j),b=point(i+1,j),c=point(i+1,j+1),d=point(i,j+1);
     for(const p of [a,b,c,a,c,d])mesh.data.push(...p,...p,1,1,1,ball);
   }
   return mesh;
 }
 function cueMesh(){return ArenaCue.mesh(Mesh);}
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
  'precision highp float;varying vec3 c,n,world,local;varying float mat;uniform vec3 eye,tint;uniform vec2 size;uniform float number,opacity;uniform sampler2D atlas,grain,finish;',
  'float noise(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}',
  'float swatch(float row,vec2 p){return texture2D(finish,vec2(fract(p.x),(row+(fract(p.y)*127.+.5)/128.)*.25)).r*1.16972;}',
  'void main(){vec3 col=c,N=normalize(n),V=normalize(eye-world);float gloss=.03;',
  'if(mat>.5&&mat<1.5){vec2 edge=min(world.xy,size-world.xy);float rail=.94+.06*smoothstep(0.,.055,min(edge.x,edge.y));col*=(1.14-.30*length((world.xy/size-.5)*vec2(.85,1.)))*rail*swatch(0.,world.xy/.097);}',
  'if(mat>1.5&&mat<2.5){bool end=min(world.x,size.x-world.x)<min(world.y,size.y-world.y);float along=end?world.y:world.x;float across=abs(N.z)>.65?(end?world.x:world.y):world.z;col*=swatch(1.,vec2(along/.78,across/.062));gloss=.18;}',
  'if(mat>2.5&&mat<3.5)gloss=.34;',
  'if(mat>10.5){float t=atan(local.z,local.y)/6.2831853;col=texture2D(grain,vec2(clamp(-local.x/1.475,0.,1.),fract(t))).rgb;gloss=.075;}',
  'if(mat>3.5&&mat<4.5){col*=swatch(2.,(world.xy+world.z*.8)/.057);gloss=.08;}',
  'if(mat>9.5&&mat<10.5){col*=swatch(0.,(world.xy+world.z*.85)/.097);}',
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
     this.u=Object.fromEntries('eye right up forward shift basis quat lens aspect ortho tint number opacity atlas grain finish size'.split(' ').map(k=>[k,gl.getUniformLocation(program,k)]));
     this.ball=this.upload(sphere());this.cue=this.upload(cueMesh(dim));
     const disk=new Mesh();disk.disk(0,0,0,1,[1,1,1],shadow);this.shadow=this.upload(disk);
     this.dynamic=gl.createBuffer();this.traces=gl.createBuffer();
     gl.bindTexture(gl.TEXTURE_2D,gl.createTexture());gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,gl.RGB,gl.UNSIGNED_BYTE,atlas());gl.generateMipmap(gl.TEXTURE_2D);
     gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
     gl.uniform1i(this.u.atlas,0);
     const grain=ArenaCue.woodTexture();gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,gl.createTexture());
     gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,grain.width,grain.height,0,gl.RGB,gl.UNSIGNED_BYTE,grain.bytes);
     gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.REPEAT);
     gl.generateMipmap(gl.TEXTURE_2D);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
     gl.uniform1i(this.u.grain,1);
     const finish=ArenaTable.finishes();gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D,gl.createTexture());
     gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,finish.width,finish.height,0,gl.RGB,gl.UNSIGNED_BYTE,finish.bytes);
     gl.generateMipmap(gl.TEXTURE_2D);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
     gl.uniform1i(this.u.finish,2);gl.activeTexture(gl.TEXTURE0);
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
     if(state.cuePose){const v=state.cuePose;this.pose(v.position,v.axis);gl.uniform1f(u.opacity,state.stroke.alpha);this.draw(this.cue);}
   }
 }
 root.ArenaRenderer={Renderer,palette,table,tableMesh,cueMesh,marks};
})(globalThis);
