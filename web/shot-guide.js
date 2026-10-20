'use strict';

(function(root) {
  // Direction-only fallback. This helper never constructs a collision or stop;
  // instantGuide below separately solves reachable first contacts.
  function aimDirection(cue, angleDeg, table) {
    const angle=angleDeg*Math.PI/180, dx=Math.cos(angle),dy=Math.sin(angle);
    const p=cue.position, margin=.08;
    const times=[dx>1e-12?(table.length+margin-p.x)/dx:dx<-1e-12?(-margin-p.x)/dx:Infinity,
      dy>1e-12?(table.width+margin-p.y)/dy:dy<-1e-12?(-margin-p.y)/dy:Infinity];
    const distance=Math.max(0,Math.min(...times));
    return {start:p,end:{x:p.x+distance*dx,y:p.y+distance*dy}};
  }

  const dot=(a,b)=>a.x*b.x+a.y*b.y;
  const subtract=(a,b)=>({x:a.x-b.x,y:a.y-b.y});
  const along=(p,d,t)=>({x:p.x+d.x*t,y:p.y+d.y*t});
  function closest(point,surface) {
    const axis=subtract(surface.end,surface.start),t=Math.max(0,Math.min(1,dot(subtract(point,surface.start),axis)/dot(axis,axis)));
    return along(surface.start,axis,t);
  }
  function rayCircle(p,d,center,radius) {
    const delta=subtract(p,center),b=dot(delta,d),discriminant=b*b-dot(delta,delta)+radius*radius;
    if(discriminant<=1e-15)return null;
    const distance=-b-Math.sqrt(discriminant);
    return distance>=-1e-9?Math.max(0,distance):null;
  }
  function rayCapsule(p,d,surface,radius) {
    const axis=subtract(surface.end,surface.start),length=Math.hypot(axis.x,axis.y),u={x:axis.x/length,y:axis.y/length},n={x:-u.y,y:u.x};
    const candidates=[rayCircle(p,d,surface.start,radius),rayCircle(p,d,surface.end,radius)];
    const speed=dot(d,n),offset=dot(subtract(p,surface.start),n);
    if(Math.abs(speed)>1e-12)for(const sign of [-1,1]){
      const distance=(sign*radius-offset)/speed,projection=dot(subtract(along(p,d,distance),surface.start),u);
      if(distance>=-1e-9&&projection>=0&&projection<=length)candidates.push(Math.max(0,distance));
    }
    return candidates.filter(t=>t!==null).sort((a,b)=>a-b).find(t=>{
      const delta=subtract(along(p,d,t),closest(along(p,d,t),surface));
      return Math.abs(Math.hypot(delta.x,delta.y)-radius)<1e-7&&dot(delta,d)<-1e-10;
    })??null;
  }
  function freeTravel(ball,shot,model) {
    // Same declared impulse/slide/roll equations, limited to the straight
    // motion before the first contact. Audited against the Python engine.
    const inverse=1/model.cue.effective_mass+(1+2.5*(shot.tip_x**2+shot.tip_y**2))/ball.spec.mass;
    const speed=(1+model.cue.restitution)*shot.cue_speed/inverse/ball.spec.mass;
    const slip=speed*(1-2.5*shot.tip_y),slide=model.physics.sliding_friction*model.physics.gravity;
    if(Math.abs(slip)>1e-9&&!slide)return Infinity;
    const duration=Math.abs(slip)>1e-9?Math.abs(slip)/(3.5*slide):0;
    const acceleration=-Math.sign(slip)*slide,v=speed+acceleration*duration;
    const rolling=model.physics.rolling_friction*model.physics.gravity;
    return rolling?speed*duration+.5*acceleration*duration**2+v*v/(2*rolling):Infinity;
  }
  function instantGuide(scene,model,geometry) {
    const cue=scene.balls.find(b=>b.id==='cue'),angle=scene.shot.angle_deg*Math.PI/180,d={x:Math.cos(angle),y:Math.sin(angle)},p=cue.position;
    const range=freeTravel(cue,scene.shot,model);
    let best={kind:Number.isFinite(range)?'stop':'direction',distance:range,radius:cue.spec.radius,contact:null,target:null};
    const clear=(point,radius)=>geometry.surfaces.every(s=>{const q=closest(point,s);return Math.hypot(point.x-q.x,point.y-q.y)>=radius+s.radius-1e-9;});
    const dropped=ball=>geometry.pockets.some(h=>h.fall_center&&Math.hypot(ball.position.x-h.fall_center.x,ball.position.y-h.fall_center.y)<=h.fall_radius+1e-9&&clear(ball.position,ball.spec.radius));
    const choose=(distance,data)=>{if(distance!==null&&distance<=best.distance+1e-9)best={...best,...data,distance};};
    for(const ball of scene.balls)if(ball.id!=='cue'&&!ball.pocket&&!dropped(ball)){
      const distance=rayCircle(p,d,ball.position,cue.spec.radius+ball.spec.radius);
      if(distance!==null){const center=along(p,d,distance),n=subtract(ball.position,center),length=Math.hypot(n.x,n.y);
        choose(distance,{kind:'ball_ball',target:ball.position,contact:along(center,n,cue.spec.radius/length)});}
    }
    for(const surface of geometry.surfaces){
      const distance=rayCapsule(p,d,surface,cue.spec.radius+surface.radius);
      if(distance!==null){const center=along(p,d,distance),n=subtract(closest(center,surface),center),length=Math.hypot(n.x,n.y);
        choose(distance,{kind:'ball_cushion',target:null,contact:along(center,n,cue.spec.radius/length)});}
    }
    for(const pocket of geometry.pockets)if(pocket.fall_center){
      const distance=dropped(cue)&&Math.hypot(p.x-pocket.fall_center.x,p.y-pocket.fall_center.y)<=pocket.fall_radius+1e-9?0:rayCircle(p,d,pocket.fall_center,pocket.fall_radius);
      if(distance!==null&&clear(along(p,d,distance),cue.spec.radius))choose(distance,{kind:'ball_pocket',target:null,contact:null});
    }
    const center=Number.isFinite(best.distance)?along(p,d,best.distance):aimDirection(cue,scene.shot.angle_deg,model.table).end;
    return {...best,start:p,center,provisional:true};
  }

  function contactGuide(result, geometry) {
    const initial = result.initial.find(ball => ball.id === 'cue');
    const event = result.events.find(item => item.actors.includes('cue') && ['ball_ball','ball_cushion','ball_pocket'].includes(item.kind));
    if (!event) {
      const final = result.final.find(ball => ball.id === 'cue');
      return {kind:result.status === 'stopped' ? 'stop' : 'incomplete', start:initial.position, center:final.position, radius:initial.spec.radius, contact:null, target:null};
    }
    const cue = event.before.find(ball => ball.id === 'cue');
    const target = event.kind === 'ball_ball' ? event.before.find(ball => event.actors.includes(ball.id) && ball.id !== 'cue') : null;
    let contact = null;
    if (target) {
      const dx=target.position.x-cue.position.x, dy=target.position.y-cue.position.y, length=Math.hypot(dx,dy);
      contact={x:cue.position.x+dx/length*cue.spec.radius,y:cue.position.y+dy/length*cue.spec.radius};
    } else if (event.kind === 'ball_cushion' && geometry) {
      const surface=geometry.surfaces.find(item=>item.id===event.detail);
      if (surface) {
        const dx=surface.end.x-surface.start.x,dy=surface.end.y-surface.start.y;
        const t=Math.max(0,Math.min(1,((cue.position.x-surface.start.x)*dx+(cue.position.y-surface.start.y)*dy)/(dx*dx+dy*dy)));
        const nx=surface.start.x+t*dx-cue.position.x,ny=surface.start.y+t*dy-cue.position.y,length=Math.hypot(nx,ny);
        contact={x:cue.position.x+nx/length*cue.spec.radius,y:cue.position.y+ny/length*cue.spec.radius};
      }
    }
    return {kind:event.kind,start:initial.position,center:cue.position,radius:cue.spec.radius,contact,target:target?.position || null,time:event.time};
  }
  const api = {contactGuide,aimDirection,instantGuide};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.ShotGuide=api;
})(globalThis);
