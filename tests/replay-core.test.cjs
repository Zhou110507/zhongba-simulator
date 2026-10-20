const {test}=require('node:test');
const assert=require('node:assert/strict');
const {unpack,segmentIndex,stateAt,paintTrail,paintBurst,TrailLayer}=require('../web/replay-core.js');
const ball={id:'cue',position:{x:1,y:2},velocity:{x:2,y:3},omega:{x:1,y:2,z:3},spec:{radius:.028575},pocket:null};
const motion={acceleration:{x:-.2,y:.3},angular_acceleration:{x:1,y:-1,z:-1}};
const segment=(start,end)=>({start,end,balls:[ball],motion:[motion]});
test('binary search is right-continuous across thousands of motion events',()=>{
 const segments=Array.from({length:2000},(_,i)=>segment(i/100,(i+1)/100));
 for(let i=0;i<1999;i++){assert.equal(segmentIndex(segments,i/100),i);assert.equal(segmentIndex(segments,i/100+.001),i);}
 const result={segments,duration:20,final:[{id:'done'}]};
 assert.deepEqual(stateAt(result,20),result.final);
 const value=stateAt(result,1.005)[0];assert.ok(Math.abs(value.position.x-(1+2*.005-.1*.005**2))<1e-12);
});
test('trail Bezier matches the analytic path even with transverse acceleration',()=>{
 let start,control,end;const ctx={beginPath(){},moveTo(x,y){start=[x,y];},quadraticCurveTo(x,y,a,b){control=[x,y];end=[a,b];},stroke(){}};
 paintTrail(ctx,segment(0,2),2,{X:x=>x,Y:y=>y},()=> 'white');
 for(const u of [0,.1,.5,.9,1])for(let axis=0;axis<2;axis++){
  const coordinate=axis?'y':'x',actual=(1-u)**2*start[axis]+2*(1-u)*u*control[axis]+u*u*end[axis],t=2*u;
  assert.ok(Math.abs(actual-(ball.position[coordinate]+ball.velocity[coordinate]*t+.5*motion.acceleration[coordinate]*t*t))<1e-12);
 }
});
test('cached trail visits completed history once and rebuilds correctly after seeking backwards',()=>{
 let paints=0,clears=0;const result={segments:Array.from({length:1000},(_,i)=>segment(i*.01,(i+1)*.01))};
 const ctx={clearRect(){clears++;}},canvas={width:1600,height:900,getContext(){return ctx;}},target={drawImage(){}};
 const layer=new TrailLayer(result,canvas,()=>paints++);
 for(let frame=0;frame<=600;frame++)layer.render(target,frame/60);
 assert.ok(paints<=1601,paints);assert.equal(layer.completed,1000);
 const done=paints;for(let frame=0;frame<100;frame++)layer.render(target,10);
 assert.equal(paints,done);layer.render(target,.5);assert.equal(clears,1);assert.equal(layer.completed,50);
 layer.render(target,10);assert.equal(layer.completed,1000);
});

test('numeric playback restores every physical value and analytic sample exactly',()=>{
 const packed={detail:'playback-v2',initial:[ball],final:[ball],duration:1,segments:[[0,1,[[1,2,2,3,1,2,3,null]],[['sliding',-.2,.3,1,-1,-1]]]]};
 const full=unpack(packed);assert.deepEqual(full.segments[0].balls[0],ball);
 assert.deepEqual(full.segments[0].motion[0],{phase:'sliding',...motion});
 assert.deepEqual(stateAt(full,.5),stateAt({segments:[segment(0,1)],duration:1},.5));
 assert.equal(unpack(full),full);
});

test('a thousand contact microsteps become a bounded pixel path and one stroke',()=>{
 let strokes=0;const points=[];
 const ctx={beginPath(){},moveTo(x,y){points.push([x,y]);},lineTo(x,y){points.push([x,y]);},stroke(){strokes++;}};
 const segments=Array.from({length:1000},(_,i)=>({start:i*2e-6,end:(i+1)*2e-6,balls:[{...ball,position:{x:1+2*i*2e-6,y:2},velocity:{x:2,y:0}}],motion:[{phase:'elastic_contact',acceleration:{x:0,y:0}}]}));
 paintBurst(ctx,segments,0,1000,{scale:500,X:x=>x*500,Y:y=>y*500},()=> 'white');
 assert.equal(strokes,1);assert.ok(points.length<=10);assert.ok(Math.abs(points.at(-1)[0]-502)<1e-10);
 for(let i=1;i<points.length-1;i++)assert.ok(points[i][0]-points[i-1][0]<.253);
});
