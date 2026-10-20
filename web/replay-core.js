'use strict';
(function(root){
  function unpack(result){
    if(result.detail!=='playback-v2')return result;
    return {...result,detail:'playback-expanded-v2',segments:result.segments.map(([start,end,balls,motions])=>({start,end,
      balls:balls.map(([x,y,vx,vy,wx,wy,wz,pocket],i)=>({id:result.initial[i].id,spec:result.initial[i].spec,position:{x,y},velocity:{x:vx,y:vy},omega:{x:wx,y:wy,z:wz},pocket})),
      motion:motions.map(([phase,ax,ay,wx,wy,wz])=>({phase,acceleration:{x:ax,y:ay},angular_acceleration:{x:wx,y:wy,z:wz}}))}))};
  }
  function segmentIndex(segments,time){
    let lo=0,hi=segments.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(segments[mid].start<=time)lo=mid+1;else hi=mid;}
    return Math.max(0,lo-1);
  }
  function evaluate(ball,motion,dt){
    return {...ball,position:{x:ball.position.x+ball.velocity.x*dt+.5*motion.acceleration.x*dt*dt,y:ball.position.y+ball.velocity.y*dt+.5*motion.acceleration.y*dt*dt},
      velocity:{x:ball.velocity.x+motion.acceleration.x*dt,y:ball.velocity.y+motion.acceleration.y*dt},
      omega:{x:ball.omega.x+motion.angular_acceleration.x*dt,y:ball.omega.y+motion.angular_acceleration.y*dt,z:ball.omega.z+motion.angular_acceleration.z*dt}};
  }
  function stateAt(result,time){
    if(time>=result.duration||!result.segments.length)return result.final;
    const segment=result.segments[segmentIndex(result.segments,time)];
    return segment.balls.map((ball,i)=>evaluate(ball,segment.motion[i],time-segment.start));
  }
  // Exact quadratic Bezier for constant-acceleration segments. No resampling
  // of past motion and no ball/omega object allocation per trail vertex.
  function paintTrail(ctx,segment,elapsed,map,color){
    if(elapsed<=0)return;
    for(let i=0;i<segment.balls.length;i++){
      const b=segment.balls[i],a=segment.motion[i].acceleration;
      if(b.pocket||(!b.velocity.x&&!b.velocity.y&&!a.x&&!a.y))continue;
      const x=b.position.x,y=b.position.y,dt=elapsed;
      ctx.beginPath();ctx.strokeStyle=color(b.id);ctx.lineWidth=2;
      ctx.moveTo(map.X(x),map.Y(y));
      ctx.quadraticCurveTo(map.X(x+.5*b.velocity.x*dt),map.Y(y+.5*b.velocity.y*dt),
        map.X(x+b.velocity.x*dt+.5*a.x*dt*dt),map.Y(y+b.velocity.y*dt+.5*a.y*dt*dt));ctx.stroke();
    }
  }
  // Contact samples are micrometres apart. Batch their visible path into one
  // stroke per ball; every omitted vertex stays within .25 screen pixels.
  // Physics states and time-axis sampling retain every original microstep.
  function paintBurst(ctx,segments,start,end,map,color){
    const threshold=(.25/map.scale)**2;
    for(let i=0;i<segments[start].balls.length;i++){
      const first=segments[start].balls[i];if(first.pocket)continue;
      let x=first.position.x,y=first.position.y,changed=false;
      ctx.beginPath();ctx.strokeStyle=color(first.id);ctx.lineWidth=2;ctx.moveTo(map.X(x),map.Y(y));
      for(let k=start;k<end;k++){
        const s=segments[k],b=s.balls[i],a=s.motion[i].acceleration,dt=s.end-s.start;
        const nx=b.position.x+b.velocity.x*dt+.5*a.x*dt*dt,ny=b.position.y+b.velocity.y*dt+.5*a.y*dt*dt;
        if((nx-x)**2+(ny-y)**2>=threshold||k===end-1){if(nx!==x||ny!==y){ctx.lineTo(map.X(nx),map.Y(ny));changed=true;}x=nx;y=ny;}
      }
      if(changed)ctx.stroke();
    }
  }
  class TrailLayer{
    constructor(result,canvas,paint,burstPaint=null){this.result=result;this.canvas=canvas;this.ctx=canvas.getContext('2d');this.paint=paint;this.burstPaint=burstPaint;this.completed=0;this.last=-1;}
    render(target,time){
      const segments=this.result.segments;
      if(time<this.last){this.ctx.clearRect(0,0,this.canvas.width,this.canvas.height);this.completed=0;}
      while(this.completed<segments.length&&segments[this.completed].end<=time){
        if(this.burstPaint&&segments[this.completed].motion[0].phase==='elastic_contact'){
          const start=this.completed;do{this.completed++;}while(this.completed<segments.length&&segments[this.completed].end<=time&&segments[this.completed].motion[0].phase==='elastic_contact');
          this.burstPaint(this.ctx,segments,start,this.completed);continue;
        }
        const s=segments[this.completed++];this.paint(this.ctx,s,s.end-s.start);
      }
      target.drawImage(this.canvas,0,0);
      const s=segments[this.completed];
      if(s&&time>s.start)this.paint(target,s,Math.min(time,s.end)-s.start);
      this.last=time;
    }
  }
  const api={unpack,segmentIndex,evaluate,stateAt,paintTrail,paintBurst,TrailLayer};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ReplayCore=api;
})(globalThis);
