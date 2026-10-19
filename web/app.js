'use strict';

const $ = id => document.getElementById(id);
const canvas = $('table'), ctx = canvas.getContext('2d'), tipCanvas = $('tip'), tipCtx = tipCanvas.getContext('2d');
const clone = value => JSON.parse(JSON.stringify(value));
const colors = ['#efe9cf','#e6b63a','#4b79c8','#c85146','#8c64b4','#df8c38','#4c9373','#9c4548','#242b28'];
const pocketNames = {'bottom-left':'左下角袋','bottom-middle':'下中袋','bottom-right':'右下角袋','top-left':'左上角袋','top-middle':'上中袋','top-right':'右上角袋'};
const STORAGE = 'zhongba.practice.scene.v1';
let config, scene, record = null, cachedKey = '', revision = 0, requestNumber = 0, requestController = null;
let busy = false, fired = false, playing = false, time = 0, lastFrame = 0, finishedAnnounced = false;
let mode = 'aim', selected = 'cue', pending = null, drag = null, tipDragging = false, history = [], launchTimer = null;

function announce(text, error = false) { $('message').textContent = text; $('message').classList.toggle('error', error); }
function ballName(id) { return id === 'cue' ? '白球' : `${id} 号球`; }
function color(id) { return id === 'cue' ? colors[0] : colors[(Number(id) - 1) % 8 + 1]; }
function active(ball) { return ball.pocket === null || ball.pocket === undefined; }
function cueBall() { return scene.balls.find(ball => ball.id === 'cue'); }
function locked() { return fired; }
function storeScene() { try { localStorage.setItem(STORAGE, JSON.stringify(scene)); } catch {} }
function pushHistory() { history.push(clone(scene)); if (history.length > 50) history.shift(); }

async function api(path, data, signal) {
  const response = await fetch(path, {method: data ? 'POST' : 'GET', headers: data ? {'Content-Type':'application/json'} : {}, body: data ? JSON.stringify(data) : undefined, signal});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '本地服务请求失败');
  return value;
}

function invalidate() {
  revision++; requestNumber++; requestController?.abort(); requestController = null; busy = false;
  record = null; cachedKey = ''; fired = false; playing = false; time = 0; finishedAnnounced = false;
  const hint = document.createElement('p'); hint.className = 'hint';
  hint.textContent = '出杆后显示触球、碰库与进袋事件。'; $('events').replaceChildren(hint);
}

function syncShotControls() {
  const shot = scene.shot;
  $('angle').value = Number(shot.angle_deg.toFixed(2));
  $('power').value = shot.cue_speed / config.limits.max_cue_speed * 100;
  $('tip-x').value = shot.tip_x; $('tip-y').value = shot.tip_y;
  updateShotLabels();
}

function updateShotLabels() {
  $('power-value').textContent = `${Math.round(scene.shot.cue_speed / config.limits.max_cue_speed * 100)}%`;
  $('cue-speed').textContent = `${scene.shot.cue_speed.toFixed(2)} m/s`;
  $('tip-x-value').textContent = `${scene.shot.tip_x.toFixed(2)} R`;
  $('tip-y-value').textContent = `${scene.shot.tip_y.toFixed(2)} R`;
}

function refreshLaunch() {
  clearTimeout(launchTimer); const currentRevision = revision;
  $('launch-speed').textContent = '计算中';
  launchTimer = setTimeout(async () => {
    try {
      const value = await api('/api/validate', scene);
      if (currentRevision === revision) $('launch-speed').textContent = `${value.launch.speed.toFixed(2)} m/s`;
    } catch (error) {
      if (currentRevision === revision) { $('launch-speed').textContent = '—'; announce(error.message, true); }
    }
  }, 160);
}

function setScene(value, preset = 'custom', remember = true) {
  if (remember && scene) pushHistory();
  invalidate(); scene = clone(value); selected = 'cue'; pending = null; drag = null;
  $('preset').value = preset; mode = active(cueBall()) ? 'aim' : 'edit';
  pending = active(cueBall()) ? null : 'cue';
  syncShotControls(); refreshSelection(); storeScene(); refreshLaunch(); refreshUI(); draw();
}

function setTip(horizontal, vertical) {
  if (locked()) return;
  const limit = config.limits.max_tip_offset, distance = Math.hypot(horizontal, vertical);
  if (distance > limit) { horizontal *= limit / distance; vertical *= limit / distance; }
  invalidate(); scene.shot.tip_x = horizontal; scene.shot.tip_y = vertical;
  $('tip-x').value = horizontal; $('tip-y').value = vertical; $('preset').value = 'custom';
  updateShotLabels(); storeScene(); refreshLaunch(); refreshUI(); draw();
}

function refreshSelection() {
  if (!scene.balls.some(ball => ball.id === selected)) selected = 'cue';
  $('selected-ball').replaceChildren(...scene.balls.map(ball => {
    const option = document.createElement('option'); option.value = ball.id;
    option.textContent = ballName(ball.id) + (active(ball) ? '' : '（已进袋）'); return option;
  }));
  $('selected-ball').value = selected;
  const ball = scene.balls.find(ball => ball.id === selected);
  $('ball-x').value = Math.round(ball.position.x * 1000);
  $('ball-y').value = Math.round(ball.position.y * 1000);
}

function refreshUI() {
  if (!config || !scene) return;
  const duration = record?.result.duration || 0, completeTime = fired && time >= duration;
  const cueMissing = !active(cueBall());
  $('phase').textContent = busy ? '正在计算…' : fired ? (playing ? '球在运动中' : completeTime ? (record.complete ? '本杆结束' : '计算已中止') : '已暂停') : pending ? (pending === 'cue' ? '等待摆放白球' : '点击空位添加目标球') : record ? '路线已预览' : mode === 'edit' ? '摆球中' : cueMissing ? '白球需要重新摆放' : '准备出杆';
  $('instruction').textContent = fired ? '拖动时间轴查看任意时刻 · 本杆结束后可继续' : pending ? `点击球桌空位，放置${ballName(pending)}` : mode === 'edit' ? '拖动球的位置，或使用下方数值输入' : '点击或拖动球桌确定方向 · 空格出杆';
  $('aim-mode').setAttribute('aria-pressed', String(mode === 'aim'));
  $('edit-mode').setAttribute('aria-pressed', String(mode === 'edit'));
  for (const id of ['angle','power','tip-x','tip-y','center-tip','aim-mode','edit-mode','preset','selected-ball','ball-x','ball-y','apply-position','import']) $(id).disabled = locked();
  document.querySelectorAll('[data-tip]').forEach(button => button.disabled = locked());
  $('save').disabled = false; $('add').disabled = locked() || scene.balls.length >= 16;
  $('remove').disabled = locked() || selected === 'cue'; $('undo').disabled = locked() || !history.length;
  $('shoot').disabled = busy || fired || cueMissing; $('preview').disabled = busy || fired || cueMissing;
  $('before').disabled = !record; $('play').disabled = !fired || !record; $('replay').disabled = !fired;
  $('seek').disabled = !fired; $('next').disabled = !completeTime || !record?.complete;
  $('play').textContent = playing ? '暂停' : completeTime ? '再播放' : '播放';
  $('next').textContent = record?.summary.scratch ? '摆放白球并继续 →' : '继续下一杆 →';
  $('apply-position').textContent = active(scene.balls.find(ball => ball.id === selected)) ? '应用坐标' : '摆回台面';
  const balls = fired ? stateAt(time) : scene.balls;
  const currentCue = balls.find(ball => ball.id === 'cue');
  $('shot-summary').textContent = record ? `${record.result.duration.toFixed(2)} s · ${fired ? `白球 ${Math.hypot(currentCue.velocity.x,currentCue.velocity.y).toFixed(2)} m/s · 侧旋 ${currentCue.omega.z.toFixed(1)} rad/s` : '路线预览'}` : '调整方向、力度和击点，再试一杆';
  $('ball-count').textContent = `${balls.filter(active).length} / ${balls.length} 球在台`;
  $('potted').replaceChildren(...balls.filter(ball => !active(ball)).map(ball => {
    const marker = document.createElement('span'); marker.textContent = ball.id === 'cue' ? '白' : ball.id;
    marker.title = `${ballName(ball.id)} · ${pocketNames[ball.pocket] || ball.pocket}`; return marker;
  }));
  $('clock').textContent = `${time.toFixed(2)} / ${duration.toFixed(2)} s`;
  $('seek').value = duration ? time / duration * 1000 : 0;
  for (const event of $('events').children) event.classList.toggle('active', fired && Number(event.dataset.time) <= time);
  canvas.style.cursor = fired ? 'default' : mode === 'edit' ? 'grab' : 'crosshair';
}

function populateEvents() {
  const labels = {ball_ball:'触球',ball_cushion:'碰库',ball_pocket:'进袋',sliding_to_rolling:'恢复滚动',rolling_to_rest:'平动停止',spin_to_rest:'侧旋停止'};
  $('events').replaceChildren(...record.result.events.map(event => {
    const row = document.createElement('div'); row.dataset.time = event.time;
    const stamp = document.createElement('time'); stamp.textContent = `${event.time.toFixed(3)} s`;
    const detail = document.createElement('span');
    detail.textContent = event.kind === 'ball_pocket' ? `${ballName(event.actors[0])} → ${pocketNames[event.detail]}` : `${event.actors.map(ballName).join(' / ')} · ${labels[event.kind] || event.kind}${event.detail?.startsWith('jaw:') ? '（袋角）' : ''}`;
    row.append(stamp, detail); return row;
  }));
}

async function calculate(commit) {
  if (fired || busy || !active(cueBall())) return;
  if (commit && record && cachedKey === JSON.stringify(scene)) { startReplay(); return; }
  const currentRevision = revision, currentRequest = ++requestNumber, snapshot = clone(scene);
  busy = true; requestController?.abort(); requestController = new AbortController(); refreshUI();
  announce(commit ? '正在计算这一杆…' : '正在计算预览路线…');
  try {
    const value = await api('/api/shot', snapshot, requestController.signal);
    if (currentRevision !== revision || currentRequest !== requestNumber) return;
    record = value; cachedKey = JSON.stringify(snapshot); populateEvents();
    if (commit) startReplay();
    else { announce(value.complete ? '预览已完成。路线来自同一套物理内核，点击出杆即可播放。' : statusText(value.result.status), !value.complete); draw(); }
  } catch (error) {
    if (error.name !== 'AbortError' && currentRevision === revision) announce(error.message || '无法连接本地服务，请重新启动练习台。', true);
  } finally {
    if (currentRevision === revision && currentRequest === requestNumber) { busy = false; requestController = null; refreshUI(); }
  }
}

function statusText(status) {
  const names = {unsupported_coupled_contact:'这一杆出现当前模型尚不支持的同时多点接触。请回到出杆前调整球位。',unsupported_persistent_contact:'这一杆出现持续贴库或贴球接触，当前模型尚不能可靠处理。',cushion_model_failure:'此杆碰库超出当前平面模型的求解范围。',max_events:'这一杆达到事件计算上限。',max_time:'这一杆在 60 秒内尚未完全停止。'};
  return names[status] || `计算未完成：${status}`;
}

function startReplay() {
  fired = true; playing = true; time = 0; lastFrame = 0; finishedAnnounced = false;
  announce(record.complete ? '这一杆正在回放。可暂停、慢放或拖动时间轴。' : statusText(record.result.status), !record.complete);
  refreshUI(); draw();
}

function reportFinish() {
  playing = false;
  if (finishedAnnounced) return;
  finishedAnnounced = true;
  const potted = record.summary.potted.filter(id => id !== 'cue').map(ballName);
  announce(record.complete ? `${potted.length ? `${potted.join('、')}进袋。` : '本杆结束。'}${record.summary.scratch ? '白球落袋，点击“摆放白球并继续”。' : '可以继续下一杆，或回到出杆前重试。'}` : statusText(record.result.status), !record.complete);
}

function evaluate(ball, motion, elapsed) {
  return {...ball,position:{x:ball.position.x+ball.velocity.x*elapsed+.5*motion.acceleration.x*elapsed**2,y:ball.position.y+ball.velocity.y*elapsed+.5*motion.acceleration.y*elapsed**2},velocity:{x:ball.velocity.x+motion.acceleration.x*elapsed,y:ball.velocity.y+motion.acceleration.y*elapsed},omega:{x:ball.omega.x+motion.angular_acceleration.x*elapsed,y:ball.omega.y+motion.angular_acceleration.y*elapsed,z:ball.omega.z+motion.angular_acceleration.z*elapsed}};
}

function stateAt(at) {
  const result = record.result;
  if (at >= result.duration || !result.segments.length) return result.final;
  let segment = result.segments[0];
  for (const candidate of result.segments) { if (candidate.start > at) break; segment = candidate; }
  return segment.balls.map((ball,index) => evaluate(ball,segment.motion[index],at-segment.start));
}

function transform() {
  const margin = .16, width = config.model.table.length, height = config.model.table.width;
  const scale = Math.min(canvas.width / (width + margin * 2), canvas.height / (height + margin * 2));
  const originX = (canvas.width - width * scale) / 2, originY = (canvas.height - height * scale) / 2;
  return {scale, X:x=>originX+x*scale, Y:y=>canvas.height-originY-y*scale, originX, originY};
}

function pointerPosition(event) {
  const rect = canvas.getBoundingClientRect(), map = transform();
  const pixelX = (event.clientX-rect.left)/rect.width*canvas.width, pixelY = (event.clientY-rect.top)/rect.height*canvas.height;
  return {x:(pixelX-map.originX)/map.scale,y:(canvas.height-map.originY-pixelY)/map.scale};
}

function positionError(id, position) {
  const radius = config.ball_spec.radius, table = config.model.table;
  if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) return '坐标必须是数值。';
  if (position.x < radius || position.x > table.length-radius || position.y < radius || position.y > table.width-radius) return '摆球时请将球心放在台面内，留出球半径。';
  for (const surface of config.geometry.surfaces) {
    const dx=surface.end.x-surface.start.x, dy=surface.end.y-surface.start.y;
    const fraction=Math.max(0,Math.min(1,((position.x-surface.start.x)*dx+(position.y-surface.start.y)*dy)/(dx*dx+dy*dy)));
    if (Math.hypot(position.x-surface.start.x-fraction*dx,position.y-surface.start.y-fraction*dy) < radius+surface.radius-1e-9) return '这个位置与库边或袋角重叠。';
  }
  for (const ball of scene.balls) if (ball.id !== id && active(ball) && Math.hypot(ball.position.x-position.x,ball.position.y-position.y) < 2*radius+1e-6) return '球不能重叠，请留出一点间隙。';
  return '';
}

function placeBall(id, position, adding=false) {
  const error = positionError(id,position); if (error) { announce(error,true); return false; }
  pushHistory(); invalidate();
  if (adding) scene.balls.push({id,position,velocity:{x:0,y:0},omega:{x:0,y:0,z:0},spec:clone(config.ball_spec),pocket:null});
  else { const ball=scene.balls.find(ball=>ball.id===id); ball.position=position; ball.pocket=null; }
  selected=id; pending=null; $('preset').value='custom'; refreshSelection(); storeScene(); refreshLaunch(); refreshUI(); draw();
  announce(`${ballName(id)}已摆好。切换到瞄准即可出杆。`); return true;
}

function drawBall(ball, map, ghost=false) {
  if (!active(ball)) return;
  const x=map.X(ball.position.x), y=map.Y(ball.position.y), radius=ball.spec.radius*map.scale;
  ctx.save(); if(ghost)ctx.globalAlpha=.6;
  ctx.shadowColor='#0009';ctx.shadowBlur=radius*.5;ctx.shadowOffsetY=radius*.25;
  const gradient=ctx.createRadialGradient(x-radius*.35,y-radius*.4,radius*.1,x,y,radius);
  gradient.addColorStop(0,ball.id==='cue'?'#fffdf0':'#f5edcf');gradient.addColorStop(.38,ball.id==='cue'?'#efe9d7':color(ball.id));gradient.addColorStop(1,ball.id==='cue'?'#aeb2a0':'#1a241f');
  ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fillStyle=gradient;ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
  if(Number(ball.id)>8){ctx.save();ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.clip();ctx.fillStyle='#ece9d9';ctx.fillRect(x-radius,y-radius,2*radius,radius*.45);ctx.fillRect(x-radius,y+radius*.55,2*radius,radius*.45);ctx.restore();}
  if(ball.id!=='cue'){ctx.beginPath();ctx.arc(x,y,radius*.47,0,Math.PI*2);ctx.fillStyle='#f0ecd8';ctx.fill();ctx.fillStyle='#27332b';ctx.font=`bold ${radius*.65}px sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(ball.id,x,y+.5);}
  if(!fired&&ball.id===selected&&mode==='edit'){ctx.strokeStyle='#d4e8a7';ctx.lineWidth=2;ctx.setLineDash([5,4]);ctx.beginPath();ctx.arc(x,y,radius+7,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);}
  ctx.restore();
}

function draw() {
  if(!config||!scene)return;
  const map=transform(), table=config.model.table, {X,Y,scale}=map;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  const outer=.105;
  ctx.shadowColor='#0007';ctx.shadowBlur=30;ctx.shadowOffsetY=18;ctx.fillStyle='#63513a';ctx.beginPath();ctx.roundRect(X(-outer),Y(table.width+outer),(table.length+2*outer)*scale,(table.width+2*outer)*scale,24);ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
  ctx.strokeStyle='#bca374';ctx.lineWidth=2;ctx.stroke();
  ctx.fillStyle='#173b2a';ctx.fillRect(X(-.05),Y(table.width+.05),(table.length+.1)*scale,(table.width+.1)*scale);
  const cloth=ctx.createLinearGradient(0,Y(table.width),0,Y(0));cloth.addColorStop(0,'#286949');cloth.addColorStop(1,'#1d573d');ctx.fillStyle=cloth;ctx.fillRect(X(0),Y(table.width),table.length*scale,table.width*scale);
  for(const pocket of config.geometry.pockets){
    const tangent=pocket.tangent,normal=pocket.outward,half=pocket.half_width+.015,depth=pocket.depth+.06;
    ctx.beginPath();for(const [index,across,along] of [[0,-half,-.003],[1,half,-.003],[2,half,depth],[3,-half,depth]]){const position={x:pocket.mouth.x+tangent.x*across+normal.x*along,y:pocket.mouth.y+tangent.y*across+normal.y*along};index?ctx.lineTo(X(position.x),Y(position.y)):ctx.moveTo(X(position.x),Y(position.y));}ctx.closePath();ctx.fillStyle='#0b1611';ctx.fill();
    const hole={x:pocket.gate.x+normal.x*.035,y:pocket.gate.y+normal.y*.035};ctx.beginPath();ctx.ellipse(X(hole.x),Y(hole.y),.043*scale,.037*scale,0,0,Math.PI*2);ctx.fillStyle='#09100d';ctx.fill();
  }
  for(const surface of config.geometry.surfaces){ctx.beginPath();ctx.moveTo(X(surface.start.x),Y(surface.start.y));ctx.lineTo(X(surface.end.x),Y(surface.end.y));ctx.strokeStyle=surface.kind==='jaw'?'#438561':'#367959';ctx.lineWidth=surface.radius*2*scale;ctx.lineCap='round';ctx.stroke();}ctx.lineCap='butt';
  ctx.fillStyle='#d0b888';for(let index=1;index<8;index++){if(index===4)continue;for(const vertical of [-.076,table.width+.076]){const x=X(table.length*index/8),y=Y(vertical);ctx.beginPath();ctx.moveTo(x,y-4);ctx.lineTo(x+3,y);ctx.lineTo(x,y+4);ctx.lineTo(x-3,y);ctx.closePath();ctx.fill();}}
  for(let index=1;index<4;index++){for(const horizontal of [-.076,table.length+.076]){ctx.beginPath();ctx.arc(X(horizontal),Y(table.width*index/4),3,0,Math.PI*2);ctx.fill();}}
  ctx.strokeStyle='#c6ddc014';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(X(table.length/4),Y(0));ctx.lineTo(X(table.length/4),Y(table.width));ctx.stroke();
  const traceTime=fired?time:record?.result.duration||0;
  if(record&&$('trails').checked){for(const segment of record.result.segments){if(segment.start>traceTime)break;const elapsed=Math.min(segment.end,traceTime)-segment.start;for(let index=0;index<segment.balls.length;index++){const ball=segment.balls[index];if(!active(ball)||Math.hypot(ball.velocity.x,ball.velocity.y)===0)continue;ctx.beginPath();ctx.strokeStyle=ball.id==='cue'?'#f0ecd19c':color(ball.id)+'b0';ctx.lineWidth=2;const steps=Math.max(2,Math.ceil(elapsed*70));for(let step=0;step<=steps;step++){const point=evaluate(ball,segment.motion[index],elapsed*step/steps).position;step?ctx.lineTo(X(point.x),Y(point.y)):ctx.moveTo(X(point.x),Y(point.y));}ctx.stroke();}}}
  const balls=fired?stateAt(time):scene.balls;
  if(!fired&&mode==='aim'&&active(cueBall())){
    const cue=cueBall(),angle=scene.shot.angle_deg*Math.PI/180,direction={x:Math.cos(angle),y:Math.sin(angle)};let reach=.95,contact=null;
    for(const ball of scene.balls){if(ball.id==='cue'||!active(ball))continue;const delta={x:ball.position.x-cue.position.x,y:ball.position.y-cue.position.y},projection=delta.x*direction.x+delta.y*direction.y,perpendicular=delta.x**2+delta.y**2-projection**2,diameter=2*cue.spec.radius;if(projection>0&&perpendicular<=diameter**2){const distance=projection-Math.sqrt(Math.max(0,diameter**2-perpendicular));if(distance>=0&&distance<reach){reach=distance;contact=ball;}}}
    ctx.save();ctx.beginPath();ctx.rect(X(0),Y(table.width),table.length*scale,table.width*scale);ctx.clip();ctx.setLineDash([7,9]);ctx.strokeStyle='#e6eccc8a';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(X(cue.position.x),Y(cue.position.y));ctx.lineTo(X(cue.position.x+direction.x*reach),Y(cue.position.y+direction.y*reach));ctx.stroke();if(contact){ctx.beginPath();ctx.arc(X(cue.position.x+direction.x*reach),Y(cue.position.y+direction.y*reach),cue.spec.radius*scale,0,Math.PI*2);ctx.stroke();}ctx.restore();
    ctx.strokeStyle='#c6a675';ctx.lineCap='round';ctx.lineWidth=8;ctx.beginPath();ctx.moveTo(X(cue.position.x-direction.x*.36),Y(cue.position.y-direction.y*.36));ctx.lineTo(X(cue.position.x-direction.x*.075),Y(cue.position.y-direction.y*.075));ctx.stroke();ctx.strokeStyle='#d9ddd0';ctx.lineWidth=7;ctx.beginPath();ctx.moveTo(X(cue.position.x-direction.x*.075),Y(cue.position.y-direction.y*.075));ctx.lineTo(X(cue.position.x-direction.x*.045),Y(cue.position.y-direction.y*.045));ctx.stroke();ctx.lineCap='butt';
  }
  for(const ball of balls)drawBall(drag?.id===ball.id?{...ball,position:drag.position}:ball,map,drag?.id===ball.id);
  if(record&&!fired){ctx.fillStyle='#d7e8bc';ctx.font='18px "Microsoft YaHei", sans-serif';ctx.textAlign='left';ctx.fillText('计算预览 · 点击出杆播放',X(.08),Y(table.width-.07));}
  drawTip();
}

function drawTip() {
  const context=tipCtx, center={x:140,y:119},radius=82;
  context.clearRect(0,0,280,250);context.fillStyle='#90a98e';context.font='11px "Microsoft YaHei",sans-serif';context.textAlign='center';context.fillText('高杆',140,16);context.fillText('低杆',140,237);context.fillText('左',22,123);context.fillText('右',258,123);
  const gradient=context.createRadialGradient(116,93,8,140,119,84);gradient.addColorStop(0,'#fffef1');gradient.addColorStop(.6,'#e6e6d6');gradient.addColorStop(1,'#a5b19a');context.beginPath();context.arc(center.x,center.y,radius,0,Math.PI*2);context.fillStyle=gradient;context.fill();
  context.strokeStyle='#65775b';context.lineWidth=1;context.setLineDash([3,4]);context.beginPath();context.arc(center.x,center.y,radius*config.limits.max_tip_offset,0,Math.PI*2);context.stroke();context.beginPath();context.moveTo(center.x-radius*.7,center.y);context.lineTo(center.x+radius*.7,center.y);context.moveTo(center.x,center.y-radius*.7);context.lineTo(center.x,center.y+radius*.7);context.stroke();context.setLineDash([]);
  const x=center.x+scene.shot.tip_x*radius,y=center.y-scene.shot.tip_y*radius;context.beginPath();context.arc(x,y,7,0,Math.PI*2);context.fillStyle='#294f36';context.fill();context.strokeStyle='#d4e7a9';context.lineWidth=2;context.stroke();
}

canvas.addEventListener('pointerdown',event=>{
  if(!scene||locked()||event.button!==0)return;canvas.focus();const position=pointerPosition(event);
  if(pending){placeBall(pending,position,!scene.balls.some(ball=>ball.id===pending));return;}
  if(mode==='aim'){setAim(position);canvas.setPointerCapture(event.pointerId);drag={aim:true};return;}
  const ball=scene.balls.filter(active).find(ball=>Math.hypot(ball.position.x-position.x,ball.position.y-position.y)<ball.spec.radius*1.6);
  if(ball){invalidate();selected=ball.id;drag={id:ball.id,position:{...ball.position}};canvas.setPointerCapture(event.pointerId);refreshSelection();refreshUI();draw();}
});
canvas.addEventListener('pointermove',event=>{
  if(!scene)return;const position=pointerPosition(event);$('coordinates').textContent=`x ${(position.x*1000).toFixed(0)} · y ${(position.y*1000).toFixed(0)} mm`;
  if(!drag)return;if(drag.aim){setAim(position);return;}const radius=config.ball_spec.radius;drag.position={x:Math.max(radius,Math.min(config.model.table.length-radius,position.x)),y:Math.max(radius,Math.min(config.model.table.width-radius,position.y))};draw();
});
canvas.addEventListener('pointerup',()=>{if(drag&&!drag.aim){const current=drag;drag=null;placeBall(current.id,current.position);}else drag=null;draw();});
canvas.addEventListener('pointercancel',()=>{drag=null;draw();});
function setAim(position){const cue=cueBall();if(!active(cue))return;const angle=(Math.atan2(position.y-cue.position.y,position.x-cue.position.x)*180/Math.PI+360)%360;invalidate();scene.shot.angle_deg=angle;$('angle').value=Number(angle.toFixed(2));$('preset').value='custom';storeScene();refreshLaunch();refreshUI();draw();}
function tipPointer(event){const rect=tipCanvas.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width*280,y=(event.clientY-rect.top)/rect.height*250;setTip((x-140)/82,(119-y)/82);}
tipCanvas.addEventListener('pointerdown',event=>{if(!scene||locked())return;tipDragging=true;tipCanvas.setPointerCapture(event.pointerId);tipPointer(event);});
tipCanvas.addEventListener('pointermove',event=>{if(tipDragging)tipPointer(event);});
tipCanvas.addEventListener('pointerup',()=>tipDragging=false);tipCanvas.addEventListener('pointercancel',()=>tipDragging=false);

$('aim-mode').onclick=()=>{mode='aim';pending=null;refreshUI();draw();};
$('edit-mode').onclick=()=>{mode='edit';pending=active(cueBall())?null:'cue';refreshUI();draw();};
$('angle').oninput=event=>{const angle=Number(event.target.value);if(!Number.isFinite(angle))return;invalidate();scene.shot.angle_deg=(angle%360+360)%360;$('preset').value='custom';storeScene();refreshLaunch();refreshUI();draw();};
$('angle').onchange=()=>syncShotControls();
$('power').oninput=event=>{invalidate();scene.shot.cue_speed=Number(event.target.value)/100*config.limits.max_cue_speed;$('preset').value='custom';updateShotLabels();storeScene();refreshLaunch();refreshUI();draw();};
$('tip-x').oninput=event=>setTip(Number(event.target.value),scene.shot.tip_y);$('tip-y').oninput=event=>setTip(scene.shot.tip_x,Number(event.target.value));
$('center-tip').onclick=()=>setTip(0,0);document.querySelectorAll('[data-tip]').forEach(button=>button.onclick=()=>setTip(...button.dataset.tip.split(',').map(Number)));
$('preview').onclick=()=>calculate(false);$('shoot').onclick=()=>calculate(true);
$('play').onclick=()=>{if(!record)return;if(time>=record.result.duration){startReplay();return;}playing=!playing;lastFrame=0;refreshUI();};
$('replay').onclick=startReplay;
$('seek').oninput=event=>{playing=false;time=Number(event.target.value)/1000*record.result.duration;if(time>=record.result.duration)reportFinish();else announce(`已暂停在 ${time.toFixed(2)} 秒，可继续播放或查看这一时刻。`);refreshUI();draw();};
$('trails').onchange=draw;
$('before').onclick=()=>{invalidate();announce('已回到出杆前，可重新调整这一杆。');refreshUI();draw();};
$('next').onclick=()=>{if(!record?.complete||time<record.result.duration)return;const next=record.next_scene;setScene(next);if(!active(cueBall())){mode='edit';pending='cue';announce('白球落袋。点击台面空位重新摆放白球后继续。');}else announce('已应用本杆停球位置，可以继续下一杆。');refreshUI();draw();};
$('selected-ball').onchange=event=>{selected=event.target.value;mode='edit';refreshSelection();refreshUI();draw();};
$('apply-position').onclick=()=>placeBall(selected,{x:Number($('ball-x').value)/1000,y:Number($('ball-y').value)/1000});
$('add').onclick=()=>{pending=Array.from({length:15},(_,index)=>String(index+1)).find(id=>!scene.balls.some(ball=>ball.id===id));mode='edit';announce(`点击球桌空位，添加${ballName(pending)}。`);refreshUI();draw();};
$('remove').onclick=()=>{if(selected==='cue')return;pushHistory();invalidate();scene.balls=scene.balls.filter(ball=>ball.id!==selected);selected='cue';refreshSelection();$('preset').value='custom';storeScene();refreshLaunch();refreshUI();draw();};
$('undo').onclick=()=>{if(!history.length||locked())return;const previous=history.pop(),previousMode=mode,previousSelected=selected;setScene(previous,'custom',false);mode=active(cueBall())?previousMode:'edit';selected=scene.balls.some(ball=>ball.id===previousSelected)?previousSelected:'cue';refreshSelection();refreshUI();draw();announce('已撤销最近一次摆球或场景变更。');};
$('preset').onchange=event=>{const preset=config.presets.find(preset=>preset.id===event.target.value);if(preset){setScene(preset.scene,preset.id);announce(`已载入${preset.name}，可直接出杆或自由调整。`);}};
$('save').onclick=()=>{const blob=new Blob([JSON.stringify(scene,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download='中八练习场景.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);announce('已保存出杆前场景与完整参数，导入后可复现这一杆。');};
$('import').onclick=()=>$('file').click();
$('file').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>65536)throw new Error('场景文件不能超过 64 KB');const data=JSON.parse(await file.text()),currentRevision=revision,value=await api('/api/validate',data);if(revision!==currentRevision)return;setScene(value.scene);announce('场景已导入，球桌与物理版本校验通过。');}catch(error){announce(error.message,true);}finally{event.target.value='';}};
document.addEventListener('keydown',event=>{
  if(!scene||['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName))return;
  if(event.code==='Space'){event.preventDefault();if(fired)$('play').click();else calculate(true);}
  else if(event.key==='Escape'){pending=null;drag=null;mode='aim';refreshUI();draw();}
  else if((event.ctrlKey||event.metaKey)&&event.key==='z'){event.preventDefault();$('undo').click();}
  else if(mode==='edit'&&!locked()&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){
    event.preventDefault();const ball=scene.balls.find(ball=>ball.id===selected);if(!active(ball))return;const step=event.shiftKey ? .01 : .001,position={...ball.position};if(event.key==='ArrowLeft')position.x-=step;if(event.key==='ArrowRight')position.x+=step;if(event.key==='ArrowUp')position.y+=step;if(event.key==='ArrowDown')position.y-=step;placeBall(selected,position);
  }
});

function tick(now){
  if(playing&&record){const elapsed=lastFrame?Math.min(.15,(now-lastFrame)/1000):0;time=Math.min(record.result.duration,time+elapsed*Number($('speed').value));if(time>=record.result.duration)reportFinish();refreshUI();draw();}lastFrame=now;requestAnimationFrame(tick);
}

async function boot(){
  try{
    config=await api('/api/config');const custom=document.createElement('option');custom.value='custom';custom.textContent='自定义场景';$('preset').replaceChildren(custom,...config.presets.map(preset=>{const option=document.createElement('option');option.value=preset.id;option.textContent=preset.name;return option;}));
    let initial=config.presets[0].scene,presetId=config.presets[0].id,stored=null;try{stored=localStorage.getItem(STORAGE);}catch{}
    if(stored){try{initial=(await api('/api/validate',JSON.parse(stored))).scene;presetId='custom';}catch{try{localStorage.setItem(STORAGE+'.backup',stored);}catch{}}}
    setScene(initial,presetId,false);$('canvas-empty').hidden=true;
    $('model-detail').textContent=`研究用能量恢复参数 ${config.model.physics.cushion_restitution}；台呢滑动摩擦 ${config.model.physics.sliding_friction}。`;
    $('build').textContent=`${config.app_version} · ${config.model_signature.slice(0,8)}`;
    announce(active(cueBall())?'球桌已就绪。点击确定方向，调整力度和击点，然后出杆。':'已恢复上次场景。白球已落袋，点击台面空位重新摆放白球。');
    requestAnimationFrame(tick);
  }catch(error){announce(`无法连接练习台服务：${error.message}。请运行“启动练习台.cmd”后刷新。`,true);$('canvas-empty').textContent='本地服务尚未就绪';}
}
boot();
