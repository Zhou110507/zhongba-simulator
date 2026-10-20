// Counts work on an actual solver record. This is not a simulated FPS claim.
const fs=require('node:fs'),path=require('node:path');
const {TrailLayer,paintTrail}=require('../web/replay-core.js');
const source=path.join(__dirname,'../artifacts/performance/after-shot.json');
if(!fs.existsSync(source))throw Error('Create artifacts/performance/after-shot.json from a shot response first.');
const result=JSON.parse(fs.readFileSync(source,'utf8')).result;
let oldVertices=0,newCurves=0;
const ctx={clearRect(){},beginPath(){},moveTo(){},quadraticCurveTo(){newCurves++;},stroke(){}},
 canvas={width:1600,height:900,getContext(){return ctx;}},target={...ctx,drawImage(){}},map={X:x=>x,Y:y=>y};
const layer=new TrailLayer(result,canvas,(c,s,dt)=>paintTrail(c,s,dt,map,()=> 'white'));
const frames=Math.ceil(result.duration*60);
for(let frame=0;frame<=frames;frame++){
 const time=Math.min(result.duration,frame/60);
 for(const segment of result.segments){if(segment.start>time)break;const dt=Math.min(segment.end,time)-segment.start;
  for(const ball of segment.balls)if(!ball.pocket&&Math.hypot(ball.velocity.x,ball.velocity.y)!==0)oldVertices+=Math.max(2,Math.ceil(dt*70))+1;
 }
 layer.render(target,time);
}
const report={frames,segments:result.segments.length,legacy_trail_vertices:oldVertices,cached_bezier_curves:newCurves,
 ratio:oldVertices/newCurves,scope:'Operation counts on identical motion; not wall-clock GPU/FPS measurement'};
fs.writeFileSync(path.join(__dirname,'../artifacts/performance/render.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
