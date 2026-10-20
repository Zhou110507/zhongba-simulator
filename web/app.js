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
let guideRecord = null, guideKey = '', guideController = null;

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
  clearTimeout(launchTimer); guideController?.abort(); guideController=null; guideRecord=null; guideKey='';
  $('guide-info').textContent='方向线实时更新；正在计算实际接触位置…'; $('contact-analysis').textContent='';
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
  const cueSpeed = scene.shot.cue_speed;
  const strokeBand = cueSpeed >= 4.5 ? '冲球级' : cueSpeed >= 3 ? '强杆' : cueSpeed < 1 ? '轻推' : '常用档';
  $('power-value').textContent = `${Math.round(cueSpeed / config.limits.max_cue_speed * 100)}% · ${strokeBand}`;
  $('cue-speed').textContent = `${scene.shot.cue_speed.toFixed(2)} m/s`;
  $('tip-x-value').textContent = `${scene.shot.tip_x.toFixed(2)} R`;
  $('tip-y-value').textContent = `${scene.shot.tip_y.toFixed(2)} R`;
}

function refreshLaunch() {
  clearTimeout(launchTimer); const currentRevision = revision;
  if (!active(cueBall())) { $('launch-speed').textContent='—'; $('guide-info').textContent='请先将白球摆回台面。'; return; }
  $('launch-speed').textContent = '计算中';
  const snapshot=clone(scene);
  launchTimer = setTimeout(async () => {
    guideController=new AbortController();
    try {
      const value = await api('/api/shot', snapshot, guideController.signal);
      if (currentRevision === revision && !fired) {
        guideRecord=value; guideKey=JSON.stringify(snapshot);
        const ball=value.result.initial.find(ball=>ball.id==='cue');
        $('launch-speed').textContent = `${Math.hypot(ball.velocity.x,ball.velocity.y).toFixed(2)} m/s`;
        draw();
      }
    } catch (error) {
      if (currentRevision === revision && error.name!=='AbortError') {
        $('launch-speed').textContent = '—'; $('guide-info').textContent='接触位置尚未算出，可点击预览重试。';
      }
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
    const value = guideRecord && guideKey===JSON.stringify(snapshot) ? guideRecord : await api('/api/shot', snapshot, requestController.signal);
    if (currentRevision !== revision || currentRequest !== requestNumber) return;
    record = value; cachedKey = JSON.stringify(snapshot); populateEvents();
    const launched=value.result.initial.find(ball=>ball.id==='cue');
    $('launch-speed').textContent=`${Math.hypot(launched.velocity.x,launched.velocity.y).toFixed(2)} m/s`;
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
  const wood=ctx.createLinearGradient(0,Y(table.width+outer),0,Y(-outer));wood.addColorStop(0,'#66523d');wood.addColorStop(.48,'#493c30');wood.addColorStop(1,'#352e27');
  ctx.shadowColor='#0007';ctx.shadowBlur=30;ctx.shadowOffsetY=18;ctx.fillStyle=wood;ctx.beginPath();ctx.roundRect(X(-outer),Y(table.width+outer),(table.length+2*outer)*scale,(table.width+2*outer)*scale,24);ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
  ctx.strokeStyle='#a18d66';ctx.lineWidth=1.5;ctx.stroke();
  const cloth=ctx.createLinearGradient(0,Y(table.width),0,Y(0));cloth.addColorStop(0,'#286949');cloth.addColorStop(1,'#1d573d');ctx.fillStyle=cloth;ctx.fillRect(X(0),Y(table.width),table.length*scale,table.width*scale);
  ctx.save();ctx.beginPath();ctx.roundRect(X(-outer),Y(table.width+outer),(table.length+2*outer)*scale,(table.width+2*outer)*scale,24);ctx.clip();
  for(const pocket of config.geometry.pockets){
    // One smooth well replaces overlapping rotated black boxes. Its entry
    // follows the physical circular jaws; only the rounded back is decorative.
    const t=pocket.tangent,n=pocket.outward,half=pocket.half_width,radius=-(pocket.entry_depth||-.03);
    ctx.save();ctx.translate(X(pocket.mouth.x),Y(pocket.mouth.y));ctx.transform(t.x*scale,-t.y*scale,n.x*scale,-n.y*scale,0,0);
    ctx.beginPath();ctx.moveTo(-half-radius,-radius);ctx.lineTo(half+radius,-radius);
    ctx.arc(half+radius,0,radius,-Math.PI/2,-Math.PI,true);
    ctx.lineTo(half,.01);ctx.quadraticCurveTo(half,.054,0,.054);ctx.quadraticCurveTo(-half,.054,-half,.01);
    ctx.lineTo(-half,0);ctx.arc(-half-radius,0,radius,0,-Math.PI/2,true);ctx.closePath();
    const well=ctx.createLinearGradient(0,-radius,0,.054);well.addColorStop(0,'#17251e');well.addColorStop(.45,'#0c1511');well.addColorStop(1,'#050a08');ctx.fillStyle=well;ctx.fill();ctx.restore();
  }
  // Fill the solid behind each nose so rounded jaws join the cushion body.
  // Clip remote channel caps to the frame; capture occurs before those caps.
  ctx.save();ctx.beginPath();ctx.roundRect(X(-.075),Y(table.width+.075),(table.length+.15)*scale,(table.width+.15)*scale,12);ctx.clip();
  const rubber=ctx.createLinearGradient(0,Y(table.width+.075),0,Y(-.075));rubber.addColorStop(0,'#397b59');rubber.addColorStop(1,'#2d674b');ctx.fillStyle=rubber;ctx.strokeStyle=rubber;
  for(const surface of config.geometry.surfaces){
    if(surface.radius===0){
      const normal=surface.id.startsWith('bottom')?{x:0,y:-1}:surface.id.startsWith('top')?{x:0,y:1}:surface.id==='left'?{x:-1,y:0}:{x:1,y:0};
      ctx.beginPath();for(const [index,point,depth] of [[0,surface.start,0],[1,surface.end,0],[2,surface.end,.15],[3,surface.start,.15]]){const x=X(point.x+normal.x*depth),y=Y(point.y+normal.y*depth);index?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.closePath();ctx.fill();
    }else{ctx.beginPath();ctx.moveTo(X(surface.start.x),Y(surface.start.y));ctx.lineTo(X(surface.end.x),Y(surface.end.y));ctx.lineWidth=surface.radius*2*scale;ctx.lineCap='round';ctx.stroke();}
  }
  ctx.restore();ctx.restore();ctx.lineCap='butt';
  ctx.fillStyle='#d0b888';for(let index=1;index<8;index++){if(index===4)continue;for(const vertical of [-.076,table.width+.076]){const x=X(table.length*index/8),y=Y(vertical);ctx.beginPath();ctx.moveTo(x,y-4);ctx.lineTo(x+3,y);ctx.lineTo(x,y+4);ctx.lineTo(x-3,y);ctx.closePath();ctx.fill();}}
  for(let index=1;index<4;index++){for(const horizontal of [-.076,table.length+.076]){ctx.beginPath();ctx.arc(X(horizontal),Y(table.width*index/4),3,0,Math.PI*2);ctx.fill();}}
  ctx.strokeStyle='#c6ddc014';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(X(table.length/4),Y(0));ctx.lineTo(X(table.length/4),Y(table.width));ctx.stroke();
  const traceTime=fired?time:record?.result.duration||0;
  if(record&&$('trails').checked){for(const segment of record.result.segments){if(segment.start>traceTime)break;const elapsed=Math.min(segment.end,traceTime)-segment.start;for(let index=0;index<segment.balls.length;index++){const ball=segment.balls[index];if(!active(ball)||Math.hypot(ball.velocity.x,ball.velocity.y)===0)continue;ctx.beginPath();ctx.strokeStyle=ball.id==='cue'?'#f0ecd19c':color(ball.id)+'b0';ctx.lineWidth=2;const steps=Math.max(2,Math.ceil(elapsed*70));for(let step=0;step<=steps;step++){const point=evaluate(ball,segment.motion[index],elapsed*step/steps).position;step?ctx.lineTo(X(point.x),Y(point.y)):ctx.moveTo(X(point.x),Y(point.y));}ctx.stroke();}}}
  const balls=fired?stateAt(time):scene.balls;
  if(!fired&&mode==='aim'&&active(cueBall())){
    const cue=cueBall(),angle=scene.shot.angle_deg*Math.PI/180,direction={x:Math.cos(angle),y:Math.sin(angle)};
    drawContactGuide(map);
    ctx.strokeStyle='#c6a675';ctx.lineCap='round';ctx.lineWidth=8;ctx.beginPath();ctx.moveTo(X(cue.position.x-direction.x*.36),Y(cue.position.y-direction.y*.36));ctx.lineTo(X(cue.position.x-direction.x*.075),Y(cue.position.y-direction.y*.075));ctx.stroke();ctx.strokeStyle='#d9ddd0';ctx.lineWidth=7;ctx.beginPath();ctx.moveTo(X(cue.position.x-direction.x*.075),Y(cue.position.y-direction.y*.075));ctx.lineTo(X(cue.position.x-direction.x*.045),Y(cue.position.y-direction.y*.045));ctx.stroke();ctx.lineCap='butt';
  }
  for(const ball of balls)drawBall(drag?.id===ball.id?{...ball,position:drag.position}:ball,map,drag?.id===ball.id);
  if(record&&!fired){ctx.fillStyle='#d7e8bc';ctx.font='18px "Microsoft YaHei", sans-serif';ctx.textAlign='left';ctx.fillText('计算预览 · 点击出杆播放',X(.08),Y(table.width-.07));}
  updateContactReadout();
  drawTip();
}

function drawContactGuide(map) {
  const source=record||guideRecord;
  if (!source) {
    const line=ShotGuide.aimDirection(cueBall(),scene.shot.angle_deg,config.model.table);
    ctx.save();ctx.strokeStyle='#f0ecd1c0';ctx.lineWidth=2;ctx.setLineDash([9,6]);
    ctx.beginPath();ctx.moveTo(map.X(line.start.x),map.Y(line.start.y));ctx.lineTo(map.X(line.end.x),map.Y(line.end.y));ctx.stroke();ctx.restore();
    return;
  }
  const guide=ShotGuide.contactGuide(source.result,config.geometry), {X,Y,scale}=map;
  ctx.save();ctx.setLineDash([7,7]);ctx.strokeStyle='#f0ecd1a0';ctx.lineWidth=2;
  ctx.beginPath();ctx.moveTo(X(guide.start.x),Y(guide.start.y));ctx.lineTo(X(guide.center.x),Y(guide.center.y));ctx.stroke();
  if (['ball_ball','ball_cushion'].includes(guide.kind)) {
    ctx.beginPath();ctx.arc(X(guide.center.x),Y(guide.center.y),guide.radius*scale,0,Math.PI*2);ctx.stroke();
  } else {
    const x=X(guide.center.x),y=Y(guide.center.y);ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(x-4,y-4);ctx.lineTo(x+4,y+4);ctx.moveTo(x-4,y+4);ctx.lineTo(x+4,y-4);ctx.stroke();
  }
  ctx.setLineDash([]);
  if (guide.contact) {
    if (guide.target) {ctx.strokeStyle='#cfe6a778';ctx.beginPath();ctx.moveTo(X(guide.center.x),Y(guide.center.y));ctx.lineTo(X(guide.target.x),Y(guide.target.y));ctx.stroke();}
    ctx.fillStyle='#d4f3a1';ctx.beginPath();ctx.arc(X(guide.contact.x),Y(guide.contact.y),4,0,Math.PI*2);ctx.fill();
  }
  ctx.restore();
}

function updateContactReadout() {
  const source=record||guideRecord;
  if (!source) return;
  const guide=ShotGuide.contactGuide(source.result,config.geometry);
  const labels={ball_ball:'虚线圆＝白球碰撞前的位置；亮点＝两球接触点。',ball_cushion:'先碰库：虚线圆＝接触前白球位置；亮点＝球库接触点。',ball_pocket:'这条路线先越过落袋线，未发生球球或球库接触。',stop:'白球会先停止：× 为真实停点，这一力度到不了更远的目标球。',incomplete:'当前模型未能完成接触计算，暂不显示碰撞圆。'};
  $('guide-info').textContent=labels[guide.kind];
  const data=source.contact_analysis;
  if (!data) { $('contact-analysis').textContent=''; return; }
  const recovery=data.observed_return_angle_deg;
  const spin=data.backspin_speed_ratio>0 ? `碰前倒旋比 ${data.backspin_speed_ratio.toFixed(2)}` : data.backspin_speed_ratio<0 ? '碰前已为前旋' : '碰前无高低旋转';
  $('contact-analysis').textContent=`第一碰：触球切角 ${data.cut_angle_deg.toFixed(2)}° · ${spin}${recovery!==null ? ` · ${data.backspin_speed_ratio>0 ? '回拉偏角' : '恢复滚动方向距回头线'} ${recovery.toFixed(2)}°（相对入射反向）` : ' · 下一次接触发生前未记录到滑动结束，不能直接拿停点估算分离角'}。`;
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
$('before').onclick=()=>{invalidate();announce('已回到出杆前，可重新调整这一杆。');refreshLaunch();refreshUI();draw();};
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
    let initial=config.presets[0].scene,presetId=config.presets[0].id,stored=null,oldVersion=false;try{stored=localStorage.getItem(STORAGE);}catch{}
    if(stored){try{initial=(await api('/api/validate',JSON.parse(stored))).scene;presetId='custom';}catch{oldVersion=true;try{localStorage.setItem(STORAGE+'.backup',stored);}catch{}}}
    setScene(initial,presetId,false);$('canvas-empty').hidden=true;
    $('model-detail').textContent=`研究用能量恢复参数 ${config.model.physics.cushion_restitution}；滑动摩擦 ${config.model.physics.sliding_friction}；滚动减速度系数 ${config.model.physics.rolling_friction}。`;
    $('build').textContent=`${config.app_version} · ${config.model_signature.slice(0,8)}`;
    announce(active(cueBall())?(oldVersion?'进袋判定已更新，旧参数场景已在本机备份。可试角袋、中袋或慢速进袋。':'球桌已就绪。50% 为中力，先试“中力走台”或调整击点出杆。'):'已恢复上次场景。白球已落袋，点击台面空位重新摆放白球。');
    requestAnimationFrame(tick);
  }catch(error){announce(`无法连接练习台服务：${error.message}。请运行“启动练习台.cmd”后刷新。`,true);$('canvas-empty').textContent='本地服务尚未就绪';}
}
boot();
