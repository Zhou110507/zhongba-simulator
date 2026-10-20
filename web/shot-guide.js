'use strict';

(function(root) {
  // Immediate direction feedback only. A contact circle still requires an
  // engine result; this ray must never claim a reachable collision or stop.
  function aimDirection(cue, angleDeg, table) {
    const angle=angleDeg*Math.PI/180, dx=Math.cos(angle),dy=Math.sin(angle);
    const p=cue.position, margin=.08;
    const times=[dx>1e-12?(table.length+margin-p.x)/dx:dx<-1e-12?(-margin-p.x)/dx:Infinity,
      dy>1e-12?(table.width+margin-p.y)/dy:dy<-1e-12?(-margin-p.y)/dy:Infinity];
    const distance=Math.max(0,Math.min(...times));
    return {start:p,end:{x:p.x+distance*dx,y:p.y+distance*dy}};
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
  const api = {contactGuide,aimDirection};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.ShotGuide=api;
})(globalThis);
