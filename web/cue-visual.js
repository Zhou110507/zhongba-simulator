'use strict';

// Visual dimensions only: 1.475 m ash/ebony cue, nominal 9.75 mm tip.
// The existing table scale also scales the taper and wood grain. No physics
// parameters, shot inputs or AI decisions are changed by this renderer.
window.CueVisual=(()=>{
  const LENGTH=1.475,TIP=.00975,BUTT=.029;
  let sprite=null;
  const smooth=t=>t*t*(3-2*t),clamp=t=>Math.max(0,Math.min(1,t));
  function timing(speed){
    const back=.10+.12*clamp(speed/5);
    return {back,delivery:2000*back/Math.max(.25,speed),deliveryStart:1450};
  }
  function pose(elapsed,speed){
    const {back,delivery,deliveryStart}=timing(speed),impact=deliveryStart+delivery;
    let phase,gap,alpha=1;
    if(elapsed<840){phase='feather';gap=.018+.065*(1-Math.cos(elapsed/420*2*Math.PI))/2;}
    else if(elapsed<1050){phase='settle';gap=.018;}
    else if(elapsed<1350){phase='backswing';gap=.018+(back-.018)*smooth(clamp((elapsed-1050)/300));}
    else if(elapsed<deliveryStart){phase='hold';gap=back;}
    else if(elapsed<impact){phase='delivery';const u=clamp((elapsed-deliveryStart)/delivery);gap=back*(1-u*u);}
    else{phase='follow-through';const u=clamp((elapsed-impact)/160);gap=-.055*(1-(1-u)**2);alpha=1-smooth(u);}
    return {phase,gap,alpha,impact,finished:elapsed>=impact+160};
  }
  function begin(speed){return {elapsed:0,speed};}
  function advance(state,seconds){
    const previous=state.elapsed;state.elapsed+=Math.max(0,seconds)*1000;
    const p=pose(state.elapsed,state.speed);
    return {...p,replayDelta:(Math.max(0,state.elapsed-p.impact)-Math.max(0,previous-p.impact))/1000};
  }
  function makeSprite(){
    // High-resolution, deterministic grain is cached once, rather than rebuilt
    // every animation frame. x=0 is the leather contact face, x=L the butt.
    const c=document.createElement('canvas');c.width=2400;c.height=76;
    const g=c.getContext('2d'),s=1600,mid=38;
    const r=x=>(TIP+(BUTT-TIP)*(x/LENGTH)**.78)*s/2;
    g.save();g.beginPath();g.moveTo(0,mid-r(0));
    for(let x=.02;x<LENGTH;x+=.02)g.lineTo(x*s,mid-r(x));
    g.lineTo(LENGTH*s,mid-r(LENGTH));g.lineTo(LENGTH*s,mid+r(LENGTH));
    for(let x=LENGTH-.01;x>0;x-=.02)g.lineTo(x*s,mid+r(x));
    g.lineTo(0,mid+r(0));g.closePath();g.clip();
    const wood=g.createLinearGradient(0,mid-24,0,mid+24);
    for(const [at,color]of [[0,'#897044'],[.28,'#ceae76'],[.43,'#eddbac'],[.67,'#c7a770'],[1,'#745330']])wood.addColorStop(at,color);
    g.fillStyle=wood;g.fillRect(0,0,c.width,c.height);
    for(let i=0;i<29;i++){
      g.beginPath();g.strokeStyle=i%3?'#68452335':'#fff0c43b';g.lineWidth=i%4===0?1.25:.65;
      for(let j=0;j<=90;j++){
        const x=LENGTH*j/90,spread=(i/28-.5)*r(x)*1.82;
        const y=mid+spread+Math.sin(x*(8+i%5)+i*2.3)*(.45+i%3*.35);
        if(j)g.lineTo(x*s,y);else g.moveTo(x*s,y);
      }g.stroke();
    }
    // Pointed ebony splice, with a restrained warm veneer and longitudinal
    // fibres; avoid decorative outlines, exaggerated shine or cartoon bands.
    g.beginPath();g.moveTo(.83*s,mid);g.bezierCurveTo(.98*s,mid-1,1.10*s,mid-18,1.16*s,mid-24);
    g.lineTo(LENGTH*s,0);g.lineTo(LENGTH*s,76);g.lineTo(1.16*s,mid+24);
    g.bezierCurveTo(1.10*s,mid+18,.98*s,mid+1,.83*s,mid);g.closePath();
    const ebony=g.createLinearGradient(0,mid-24,0,mid+24);
    ebony.addColorStop(0,'#100e0c');ebony.addColorStop(.4,'#433429');ebony.addColorStop(.62,'#29221b');ebony.addColorStop(1,'#0b0b09');
    g.fillStyle=ebony;g.fill();g.strokeStyle='#9a693e88';g.lineWidth=1.4;g.stroke();
    g.save();g.clip();for(let i=0;i<17;i++){
      g.strokeStyle=i%3?'#b1814c17':'#08070555';g.lineWidth=.7;g.beginPath();g.moveTo(.8*s,mid-21+i*2.6);
      g.bezierCurveTo(1.05*s,mid-22+i*2.6,1.25*s,mid-19+i*2.6,LENGTH*s,mid-20+i*2.6);g.stroke();
    }g.restore();
    const brass=g.createLinearGradient(0,mid-9,0,mid+9);
    brass.addColorStop(0,'#66522b');brass.addColorStop(.35,'#d6bd77');brass.addColorStop(.6,'#b89950');brass.addColorStop(1,'#594622');
    g.fillStyle=brass;g.fillRect(.004*s,0,.009*s,76);
    const leather=g.createLinearGradient(0,mid-8,0,mid+8);
    leather.addColorStop(0,'#263a36');leather.addColorStop(.4,'#68837c');leather.addColorStop(1,'#273e39');
    g.fillStyle=leather;g.fillRect(0,0,.004*s,76);
    g.fillStyle='#171713';g.fillRect((LENGTH-.012)*s,0,.012*s,76);
    g.restore();return c;
  }
  function draw(ctx,map,cue,shot,{gap=.018,alpha=1}={}){
    if(!sprite)sprite=makeSprite();
    const angle=shot.angle_deg*Math.PI/180,side=(shot.tip_x||0)*cue.spec.radius;
    // The tip meets the sphere at the selected side/high-low offset, rather
    // than passing through the ball centre or floating short of the surface.
    const surface=cue.spec.radius*Math.sqrt(Math.max(0,1-(shot.tip_x||0)**2-(shot.tip_y||0)**2));
    const x=map.X(cue.position.x+Math.sin(angle)*side),y=map.Y(cue.position.y-Math.cos(angle)*side);
    ctx.save();ctx.globalAlpha=alpha;ctx.translate(x,y);ctx.rotate(Math.PI-angle);
    ctx.shadowColor='#00000065';ctx.shadowBlur=2.5;ctx.shadowOffsetY=3;
    ctx.drawImage(sprite,0,0,LENGTH*1600,76,(surface+gap)*map.scale,-38/1600*map.scale,LENGTH*map.scale,76/1600*map.scale);
    ctx.restore();
  }
  return {length:LENGTH,tipDiameter:TIP,buttDiameter:BUTT,pose,begin,advance,draw};
})();
