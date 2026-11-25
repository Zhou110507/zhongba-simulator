'use strict';
if(document.documentElement.dataset.arena==='on'){
  window.ArenaRoom=(()=>{
    const stage=$('room-stage'),dialog=$('room-dialog'),camera=new ArenaMath.Camera();
    const paths={
      sound:'M4 10h4l5-4v12l-5-4H4z M16 9c2 2 2 4 0 6 M19 6c4 4 4 8 0 12',
      mute:'M4 10h4l5-4v12l-5-4H4z M17 10l4 4m0-4-4 4',
      help:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M9.6 9a2.4 2.4 0 1 1 3.6 2.1c-1 .6-1.2 1.1-1.2 2.2 M12 16.5h.01',
      settings:'M4 7h6m4 0h6 M4 17h9m4 0h3 M14 7a2 2 0 1 1-4 0 2 2 0 1 1 4 0 M17 17a2 2 0 1 1-4 0 2 2 0 1 1 4 0',
      orbit:'M21 8c3 3-2 7-8 9S1 19 2 16m4-2a7 7 0 1 1 3 4 M18 5l3 1-1 3',
      cue:'M3 20 18.5 4.5l1.5 1.5L5 21z M19 15a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4',
      top:'M3 6h18v12H3z M3 6l3 3m12 0 3-3M3 18l3-3m12 0 3 3 M12 6v2m0 8v2',
      reset:'M4 7v5h5 M4.3 11a8 8 0 1 1 1.9 6',full:'M4 9V4h5m6 0h5v5m0 6v5h-5M4 15v5h5',
      flag:'M5 21V4m1 0c5-3 8 3 14 0v9c-6 3-9-3-14 0',
      replay:'M4 8V4m0 4h4 M4.5 8a8 8 0 1 1-.2 7 M10 9l5 3-5 3z',
      place:'M12 2v5m0 10v5M2 12h5m10 0h5M18 12a6 6 0 1 1-12 0 6 6 0 0 1 12 0',
      close:'M6 6l12 12m0-12L6 18',list:'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01'
    };
    function icon(el,name){
      const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),p=document.createElementNS(ns,'path');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');p.setAttribute('d',paths[name]);svg.append(p);el.replaceChildren(svg);
    }
    document.querySelectorAll('#arena [data-icon]').forEach(n=>icon(n,n.dataset.icon));
    // Reparent the original controls. Disabled states, validation and listeners
    // remain authoritative in the same game, replay and positioning controllers.
    document.querySelectorAll('#arena [data-slot]').forEach(n=>n.append($(n.dataset.slot)));
    document.querySelectorAll('#arena [data-slot-class]').forEach(n=>n.append(document.querySelector('#main .'+n.dataset.slotClass)));
    const pref=(k,fallback)=>{try{const v=localStorage.getItem('zhongba.arena.'+k);return v===null?fallback:v==='on';}catch{return fallback;}};
    const remember=(k,b)=>{try{localStorage.setItem('zhongba.arena.'+k,b?'on':'off');}catch{}};
    const rules=()=>TableModes.isRules(),match=()=>rules()?TableModes.displayGame():null;
    const ready=()=>Boolean(config&&scene),mayAim=()=>mode==='edit'&&!TableModes.isSetup()&&active(cueBall())&&!match()?.needs_placement;
    function put(id,text){const el=$(id);if(el.textContent!==text)el.textContent=text;}
    function notice(msg,error=false){put('room-note',msg);$('room-note').closest('.room-status').dataset.error=String(error);}
    $('room-guide').checked=pref('guide',true);$('ai-auto').checked=pref('auto',true);
    $('ai-auto').addEventListener('change',()=>remember('auto',$('ai-auto').checked));
    let sound=pref('sound',true),audio=null,audioRecord=null,audioTime=0,eventIndex=0;
    function soundLabel(){$('room-sound').setAttribute('aria-pressed',String(sound));icon($('room-sound').firstElementChild,sound?'sound':'mute');}
    function unlockSound(){
      const C=window.AudioContext||window.webkitAudioContext;if(!sound||!C)return;
      if(!audio)audio=new C();if(audio.state==='suspended')audio.resume().catch(()=>{});
    }
    soundLabel();document.addEventListener('pointerdown',unlockSound,{passive:true});document.addEventListener('keydown',unlockSound);
    $('room-sound').onclick=()=>{sound=!sound;remember('sound',sound);soundLabel();if(sound)unlockSound();};
    function impact(freq,len,level){
      if(!sound||audio?.state!=='running')return;
      const osc=audio.createOscillator(),gain=audio.createGain(),now=audio.currentTime;
      osc.frequency.setValueAtTime(freq,now);osc.frequency.exponentialRampToValueAtTime(freq*.43,now+len);
      gain.gain.setValueAtTime(level,now);gain.gain.exponentialRampToValueAtTime(.0001,now+len);
      osc.connect(gain);gain.connect(audio.destination);osc.start(now);osc.stop(now+len);
    }
    function sounds(){
      if(!fired||!record){audioRecord=null;return;}
      const events=record.result.events;
      if(audioRecord!==record||time<audioTime){audioRecord=record;eventIndex=0;audioTime=0;}
      const audible=playing&&time>audioTime&&time-audioTime<.32;
      if(audible&&audioTime===0)impact(680,.048,.15);
      let type=0;while(eventIndex<events.length&&events[eventIndex].time<=time){
        const e=events[eventIndex++];if(audible&&e.time>audioTime)type=Math.max(type,({ball_pocket:3,ball_ball:2,ball_cushion:1})[e.kind]||0);
      }
      if(type===3)impact(135,.13,.19);else if(type===2)impact(1140,.037,.14);else if(type)impact(275,.062,.11);audioTime=time;
    }
    let surface,renderer,frame,screenKey='',boardKey='',rotation=null,track=null,resizeFrame=0;
    function initRenderer(software=false){
      if(!software){try{surface=$('room-gl');renderer=new ArenaRenderer.Renderer(surface,CueVisual);stage.dataset.renderer='webgl';}
        catch{software=true;}}
      if(software){surface=$('room-soft');renderer=new ArenaSoftware(surface);stage.dataset.renderer='software-3d';}
      $('room-gl').hidden=$('room-gl')!==surface;$('room-soft').hidden=$('room-soft')!==surface;screenKey='';
    }
    initRenderer();$('room-gl').addEventListener('webglcontextlost',e=>{e.preventDefault();initRenderer(true);draw();});
    $('room-gl').addEventListener('webglcontextrestored',()=>{initRenderer();draw();});
    function cameraLabels(){
      document.querySelectorAll('[data-camera]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.camera===camera.mode)));
      put('room-gesture',pending?'点击台呢放下球':mode==='edit'?'拖动球摆位':camera.mode==='cue'?'左右拖动瞄准 · Shift 精瞄':camera.mode==='top'?'点击台呢瞄准 · 滚轮缩放':'点击瞄准 · 拖动环绕');
    }
    function selectView(m){camera.select(m);cameraLabels();draw();}
    document.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>selectView(b.dataset.camera));
    $('room-reset').onclick=()=>{Object.assign(camera,new ArenaMath.Camera());cameraLabels();draw();};
    $('room-full').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await stage.requestFullscreen();}catch{notice('本窗口未提供全屏，可用浏览器全屏。');}};
    $('room-center').onclick=()=>$('center-tip').click();
    $('room-guide').onchange=()=>{remember('guide',$('room-guide').checked);draw();};
    function nudge(delta){
      if(!ready()||locked()||busy||$('angle').disabled)return;
      const a=$('angle');a.value=Number((((scene.shot.angle_deg+delta)%360+360)%360).toFixed(3));a.dispatchEvent(new Event('input',{bubbles:true}));
    }
    $('room-left').onclick=()=>nudge(-.1);$('room-right').onclick=()=>nudge(.1);
    $('room-match').onclick=()=>TableModes.switchMode('rules');$('room-practice').onclick=()=>TableModes.switchMode('free');
    $('room-place').onclick=()=>{if(mayAim())$('aim-mode').click();else $('edit-mode').click();};
    $('room-rematch').onclick=()=>$('new-match').click();
    function showDialog(kind,title){
      for(const n of ['help','settings','log'])$('dialog-'+n).hidden=n!==kind;put('room-dialog-title',title);dialog.showModal();
    }
    $('room-help').onclick=()=>showDialog('help','操作与规则');$('room-settings').onclick=()=>showDialog('settings',rules()?'对局设置':'练习设置');
    $('room-close').onclick=()=>dialog.close();dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
    $('room-log').onclick=()=>{
      const history=match()?.history||[];
      $('room-history').replaceChildren(...history.slice().reverse().map(d=>{
        const el=document.createElement('li'),pots=(d.potted||[]).map(ballName).join('、');
        el.textContent='玩家 '+(d.shooter+1)+' · '+d.outcome+(pots?' · 进袋 '+pots:'')+(d.fouls?.length?' · '+d.fouls.join('、'):'');return el;
      }));showDialog('log','击球记录');
    };
    for(const id of ['new-match','ai-demo','ai-custom','ai-finish-setup','generate-free','fill-fifteen','add'])$(id).addEventListener('click',()=>dialog.close());
    $('preset').addEventListener('change',()=>dialog.close());
    $('opponent').addEventListener('change',()=>{if($('opponent').value!==''){$('ai-auto').checked=true;$('ai-auto').dispatchEvent(new Event('change'));}});
    function seat(i,g){
      const el=$('room-group-'+i),chosen=g?.groups[i];el.replaceChildren();
      put('room-name-'+i,g?(g.ai_player===i?'电脑 · '+($('ai-level').selectedOptions[0]?.textContent.split('（')[0]||'AI'):'玩家 '+(i+1)):i?'在台目标球':'自由练习');
      if(!g)el.textContent=i?scene.balls.filter(b=>active(b)&&b.id!=='cue').length+' 颗':$('preset').selectedOptions[0]?.textContent||'自定义场景';
      else if(!chosen)el.textContent='未分组';
      else {
        const ids=g.scene.balls.filter(b=>active(b)&&(chosen==='solid'?+b.id>=1&&+b.id<=7:+b.id>=9&&+b.id<=15)).map(b=>+b.id).sort((a,b)=>a-b);
        if(!ids.length&&g.scene.balls.some(b=>b.id==='8'&&active(b)))ids.push(8);
        el.setAttribute('aria-label',(chosen==='solid'?'全色球':'花色球')+'剩余 '+ids.join('、'));
        for(const n of ids){const b=document.createElement('span');b.className='room-mini-ball'+(n>8?' striped':'');b.style.backgroundColor=ArenaRenderer.palette[(n-1)%8+1];b.textContent=n;el.append(b);}
      }
      $('room-seat-'+i).classList.toggle('active',g?g.phase!=='finished'&&(g.phase==='choice'?g.chooser:g.turn)===i:i===0);
    }
    function refresh(){
      if(!ready())return;
      const rule=rules(),g=match(),setup=TableModes.isSetup(),ai=g?.ai_player!=null&&(g.phase==='choice'?g.chooser:g.turn)===g.ai_player;
      const key=[rule,g?.id,g?.revision,g?.phase,scene.balls.map(b=>b.id+(b.pocket||'')).join(),$('preset').value].join('|');
      if(key!==boardKey){
        boardKey=key;seat(0,g);seat(1,g);put('room-title',rule?'中式八球':'自由练习');
        put('room-settings-label',rule?'对局设置':'练习设置');
        put('room-rack',g?'第 '+g.rack_number+' 局'+(g.race_to?' · 抢 '+g.race_to:''):'练习台');put('room-score',g?g.scores.join(' : '):'∞');
        put('room-spec',(rule?'CBSA 2017':'自由练习')+' · '+Math.round(config.model.table.length*1000)+' × '+Math.round(config.model.table.width*1000)+' mm · 球径 '+Number((config.ball_spec.radius*2000).toFixed(3))+' mm');
        put('room-version',config.app_version);put('room-last-result',g?.last_decision?.outcome||'');$('room-presets').hidden=rule&&!setup;
        $('room-match').setAttribute('aria-pressed',String(rule));$('room-practice').setAttribute('aria-pressed',String(!rule));
      }
      const badge=busy?'计算中':fired?(playing?'击球回放':'回放暂停'):g?.phase==='finished'?'本局结束':g?.phase==='choice'?'裁判选择':setup?'残局摆球':pending?'等待摆球':g?.is_break?'开球阶段':ai?'AI 回合':rule?'比赛中':'练习中';
      const label=$('room-badge').lastElementChild;if(label.textContent!==badge)label.textContent=badge;
      const winner=g?.match_winner!=null?'玩家 '+(g.match_winner+1)+' 赢得本场':g?.phase==='finished'?'玩家 '+(g.winner+1)+' 赢得本局':'';
      put('room-turn',fired?$('phase').textContent:winner|| (g?.phase==='choice'?'玩家 '+(g.chooser+1)+' 选择处理方式':setup?'自定义残局':pending?'请在台面摆球':g?(ai?'电脑':'玩家 '+(g.turn+1))+(g.is_break?' 开球':' 击球'):mode==='edit'?'自由摆球':'准备出杆'));
      const overlay=g&&!fired&&(g.phase==='finished'||g.phase==='choice'||g.head_respot_candidates?.length);
      $('room-state-card').hidden=!overlay;$('room-rematch').hidden=g?.match_winner==null;
      if(overlay)put('room-decision',winner||$('rule-turn').textContent);
      $('room-ai').hidden=!rule||g?.ai_player==null;$('room-center').disabled=$('center-tip').disabled;
      $('room-left').disabled=$('room-right').disabled=$('angle').disabled;
      $('room-place').hidden=Boolean(fired||(!setup&&rule&&$('edit-mode').disabled));$('room-place').disabled=$('edit-mode').disabled&&!setup;
      $('room-place').lastChild.textContent=mayAim()?'返回瞄准':rule&&!setup?'摆放白球':'摆球';
      $('room-match').disabled=$('rules-mode').disabled||busy||Boolean(fired&&playing);$('room-practice').disabled=$('free-mode').disabled||busy||Boolean(fired&&playing);
      put('room-power',Math.round(100*scene.shot.cue_speed/config.limits.max_cue_speed)+'%');
      put('room-side',scene.shot.tip_x.toFixed(2));put('room-height',scene.shot.tip_y.toFixed(2));cameraLabels();
      if(config.app_version!==document.querySelector('meta[name=arena-version]').content)notice('页面与服务版本不一致，请使用启动器打开新版球房。',true);
    }
    // Preview paths are sampled from the stored simulator result, never fed
    // back into gameplay. Match replay keeps the competition table trail-free.
    function trail(result,t){
      if(track?.result!==result){
        const dt=.075,count=Math.ceil(result.duration/dt),verts=[],ends=[0];let before=result.initial;
        for(let j=1;j<=count;j++){
          const after=ReplayCore.stateAt(result,Math.min(j*dt,result.duration));
          after.forEach((b,i)=>{const a=before[i];if(a.pocket||b.pocket||Math.hypot(a.position.x-b.position.x,a.position.y-b.position.y)<.001)return;
            const color=b.id==='cue'?[.83,.85,.71]:[.67,.76,.56];for(const p of [a.position,b.position])verts.push(p.x,p.y,.0015,0,0,1,...color,7);});
          ends.push(verts.length/10);before=after;
        }track={result,data:new Float32Array(verts),ends,dt};
      }
      const i=t>=result.duration?track.ends.length-1:Math.floor(t/track.dt);
      return {data:track.data,count:track.ends[i]||0};
    }
    function render(){
      if(!ready())return;
      const rect=stage.getBoundingClientRect(),dpr=Math.min(2,devicePixelRatio||1),w=Math.max(1,Math.round(rect.width*dpr)),h=Math.max(1,Math.round(rect.height*dpr));
      if(surface.width!==w||surface.height!==h){surface.width=w;surface.height=h;}
      const snapshot=fired?record?.snapshot:null,shot=snapshot?.shot||scene.shot;
      const cue=(snapshot?.balls||scene.balls).find(b=>b.id==='cue');
      const key=[w,h,camera.mode,camera.azimuth,camera.pitch,camera.zoom,config.model_signature,...(camera.mode==='cue'?[cue.position.x,cue.position.y,shot.angle_deg]:[])].join('|');
      if(key!==screenKey){frame=camera.frame(w,h,config.model.table,cue.position,shot);screenKey=key;}
      const balls=(fired?stateAt(time):scene.balls).map(b=>drag?.id===b.id?{...b,position:drag.position}:b);
      const aiming=!fired&&mode==='aim'&&active(cue)&&!TableModes.locksAction();
      const stroke=cueStroke?CueVisual.pose(cueStroke.elapsed,cueStroke.speed):aiming?{gap:.018,alpha:1}:null;
      if(fired&&rotation?.result!==record.result)rotation=new ArenaMath.BallRotation(record.result);
      const trace=record&&TableModes.showTrails()?trail(record.result,fired?time:record.result.duration):null;
      renderer.render(frame,{config,balls,cue,shot,stroke,rotations:fired?rotation.at(time):null,guide:aiming&&$('room-guide').checked?currentGuide():null,
        head:match()?.ball_in_hand==='head'&&!fired,selected:!fired&&mode==='edit'?selected:null,trace});
      if(!record){rotation=null;track=null;}sounds();
    }
    const pointers=new Map();let gesture=null,pinch=0;
    function point(e){const r=surface.getBoundingClientRect();return {x:(e.clientX-r.left)*surface.width/r.width,y:(e.clientY-r.top)*surface.height/r.height};}
    function separation(){const [a,b]=pointers.values();return Math.hypot(a.x-b.x,a.y-b.y);}
    function nearest(p){let found=null,best=Infinity;
      for(const b of scene.balls.filter(active)){const c=frame.project([b.position.x,b.position.y,b.spec.radius]);if(!c)continue;
        const d=Math.hypot(c.x-p.x,c.y-p.y),r=b.spec.radius*frame.height/2/(frame.ortho||c.depth/frame.lens);
        if(d<=Math.max(10,1.55*r)&&d<best){found=b;best=d;}}
      return found;
    }
    function down(e){
      if(!ready()||!frame||![0,2].includes(e.button))return;
      surface.focus({preventScroll:true});surface.setPointerCapture(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(pointers.size>1){pinch=separation();gesture=null;drag=null;draw();return;}
      const ball=mode==='edit'&&!pending&&!locked()&&!busy&&e.button===0?nearest(point(e)):null;
      gesture={id:e.pointerId,x:e.clientX,y:e.clientY,px:e.clientX,py:e.clientY,moved:false,ball,right:e.button===2,scene};
      if(ball){selected=ball.id;refreshSelection();draw();}
    }
    function move(e){
      if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(pointers.size===2){const d=separation();if(pinch>0&&d>0)camera.magnify(d/pinch);pinch=d;draw();return;}
      const g=gesture;if(!g||g.id!==e.pointerId||g.scene!==scene)return;
      if(!g.moved&&Math.hypot(e.clientX-g.x,e.clientY-g.y)<4)return;
      g.moved=true;const dx=e.clientX-g.px,dy=e.clientY-g.py;g.px=e.clientX;g.py=e.clientY;
      if(g.ball&&!locked()&&!busy){const p=point(e),pos=frame.pick(p.x,p.y,g.ball.spec.radius);if(pos)drag={id:g.ball.id,position:pos};}
      else if(camera.mode==='cue'&&!g.right&&!locked()&&!busy&&!pending&&mode==='aim'){nudge(-dx*(e.shiftKey?.015:.13));return;}
      else{camera.orbit(dx,dy);cameraLabels();}draw();
    }
    function end(e,cancel=false){
      if(!pointers.has(e.pointerId))return;pointers.delete(e.pointerId);pinch=0;
      const g=gesture;gesture=null;if(!g||g.id!==e.pointerId)return;
      const moving=drag;drag=null;if(cancel||g.scene!==scene||locked()||busy||g.right){draw();return;}
      if(g.ball&&moving){placeBall(g.ball.id,moving.position);draw();return;}if(g.moved)return;
      const p=point(e);
      if(pending){const pos=frame.pick(p.x,p.y);if(pos)placeBall(pending,pos,!scene.balls.some(b=>b.id===pending));}
      else if(mode==='aim'){const pos=frame.pick(p.x,p.y,config.ball_spec.radius);if(pos){setAim(pos);storeScene();}}
      draw();
    }
    for(const c of [$('room-gl'),$('room-soft')]){
      c.addEventListener('pointerdown',down);c.addEventListener('pointermove',move);
      c.addEventListener('pointerup',e=>end(e));c.addEventListener('pointercancel',e=>end(e,true));c.addEventListener('contextmenu',e=>e.preventDefault());
      c.addEventListener('wheel',e=>{e.preventDefault();camera.magnify(Math.exp(-Math.max(-400,Math.min(400,e.deltaY))*.001));draw();},{passive:false});
    }
    document.addEventListener('keydown',e=>{
      if(dialog.open||e.ctrlKey||e.metaKey||e.altKey||e.target.closest?.('input,select,button,a,summary,textarea'))return;
      const m=({Digit1:'orbit',Digit2:'cue',Digit3:'top'})[e.code];
      if(m){e.preventDefault();selectView(m);}else if(mode==='aim'&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();nudge((e.key==='ArrowLeft'?1:-1)*(e.shiftKey?.02:.2));}
    },true);
    new ResizeObserver(()=>{if(!resizeFrame)resizeFrame=requestAnimationFrame(()=>{resizeFrame=0;draw();});}).observe(stage);
    if(ready())queueMicrotask(()=>{refresh();draw();notice($('message').textContent);});
    return {render,refresh,notice};
  })();
}
