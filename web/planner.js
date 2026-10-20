'use strict';

window.ShotPlanner=(()=>{
  let layout='',job=null,token=0,timer=null,picking=false,visibleGoal=false,solutions=[],applying=false;
  const fields=['plan-target','plan-pocket','plan-x','plan-y','plan-radius','plan-banks','plan-seconds','plan-other'];
  const rules=()=>Boolean(window.TableModes?.isRules());
  const fingerprint=()=>scene?JSON.stringify([scene.model_signature,scene.balls]):'';
  const goal=()=>({x:Number($('plan-x').value)/1000,y:Number($('plan-y').value)/1000,radius:Number($('plan-radius').value)/1000});
  function status(text,error=false){$('plan-status').textContent=text;$('plan-status').dataset.error=String(error);}
  function clear(text){solutions=[];$('plan-results').replaceChildren();if(text)status(text);}
  function cancel(message='计算已取消。'){
    token++;clearTimeout(timer);timer=null;
    const previous=job;job=null;
    if(previous&&previous!=='starting')api('/api/plan/cancel',{id:previous}).catch(()=>{});
    picking=false;$('plan-pick').textContent='在球台上选终点';
    if(message)status(message);refresh();draw();
  }
  function refresh(){
    if(!scene||!config)return;
    $('planner-panel').hidden=rules();
    const next=fingerprint();
    if(next!==layout){
      layout=next;
      if(job)cancel('球位已变化，已取消旧局面的反算。');
      clear('球位已更新，请选择目标球和白球终点。');
      const selected=$('plan-target').value;
      $('plan-target').replaceChildren(...scene.balls.filter(b=>b.id!=='cue'&&active(b)).map(b=>{const o=document.createElement('option');o.value=b.id;o.textContent=b.id+' 号球';return o;}));
      if([...$('plan-target').options].some(o=>o.value===selected))$('plan-target').value=selected;
    }
    if((rules()||fired)&&job)cancel('已离开自由摆球局面，反算已取消。');
    const disabled=rules()||locked()||busy||!active(cueBall())||!$('plan-target').value||applying;
    $('plan-start').disabled=disabled||Boolean(job);
    $('plan-demo').disabled=rules()||locked()||busy||Boolean(job)||applying;
    $('plan-pick').disabled=disabled||Boolean(job);
    $('plan-cancel').hidden=!job;
    for(const id of fields)$(id).disabled=rules()||locked()||busy||Boolean(job)||applying;
    for(const b of $('plan-results').querySelectorAll('button'))b.disabled=disabled||Boolean(job);
  }
  function changed(){
    if(job)cancel('终点或限制已变化，请重新计算。');
    visibleGoal=true;clear('终点已更新，点击“计算走位”。');draw();
  }
  function pickGoal(point){
    if(!picking||rules())return false;
    $('plan-x').value=Math.round(point.x*1000);$('plan-y').value=Math.round(point.y*1000);
    picking=false;$('plan-pick').textContent='在球台上选终点';changed();
    return true;
  }
  function drawGoal(map){
    if(!visibleGoal||rules())return;
    const g=goal();if(!Number.isFinite(g.x+g.y+g.radius)||g.radius<=0||g.radius>.3)return;
    const {X,Y,scale}=map;ctx.save();ctx.fillStyle='#f4db7130';ctx.strokeStyle='#f4df91';ctx.lineWidth=2;ctx.setLineDash([6,5]);
    ctx.beginPath();ctx.arc(X(g.x),Y(g.y),g.radius*scale,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.setLineDash([]);
    ctx.beginPath();ctx.moveTo(X(g.x)-6,Y(g.y));ctx.lineTo(X(g.x)+6,Y(g.y));ctx.moveTo(X(g.x),Y(g.y)-6);ctx.lineTo(X(g.x),Y(g.y)+6);ctx.stroke();
    ctx.font='15px sans-serif';ctx.fillStyle='#f3e6b8';ctx.fillText('白球终点',X(g.x)+9,Y(g.y)-g.radius*scale-8);ctx.restore();
  }
  function render(result){
    solutions=result.solutions;const labels={found:'找到满足终点范围的方案',approximate:'仅找到近似方案，尚未进入指定范围',not_found:'预算内未找到满足硬性条件的方案',incomplete:'前向计算未完整结束，暂无可用方案',cancelled:'计算已取消'};
    status(`${labels[result.status]||'计算结束'} · ${result.evaluations} 次计算 · ${result.elapsed.toFixed(1)} 秒`,result.status!=='found');
    const failed=Object.values(result.numerical_failures||{}).reduce((a,b)=>a+b,0);if(failed)$('plan-status').textContent+=`。${failed} 次前向计算未完成，均未用于推荐。`;
    $('plan-results').replaceChildren(...solutions.map((v,i)=>{
      const card=document.createElement('div');card.className='plan-solution'+(v.inside?'':' approximate');
      const title=document.createElement('h3');title.textContent=`方案 ${i+1} · ${v.inside?'范围内':'范围外'} · 偏差 ${(v.error_m*1000).toFixed(1)} mm`;
      const p=document.createElement('p');p.textContent=`方向 ${v.shot.angle_deg.toFixed(3)}° · 杆速 ${v.shot.cue_speed.toFixed(3)} m/s（${(100*v.shot.cue_speed/config.limits.max_cue_speed).toFixed(1)}%）\n击点：左右 ${v.shot.tip_x.toFixed(3)} R / 高低 ${v.shot.tip_y.toFixed(3)} R\n白球初速 ${v.launch_speed.toFixed(2)} m/s · 碰库 ${v.cue_cushions} 次 · 触球 ${v.cue_ball_contacts} 次\n终点 (${Math.round(v.cue_final.x*1000)}, ${Math.round(v.cue_final.y*1000)}) mm · 目标球${v.target_pocket?'进'+(pocketNames[v.target_pocket]||v.target_pocket):'未进袋'}`;p.style.whiteSpace='pre-line';
      const stability=document.createElement('p');const trials=v.perturbations;
      stability.textContent=trials?`模型微扰：${trials.filter(t=>t.inside).length}/${trials.length} 次仍在区域内（方向 ±0.05°、杆速 ±2%；不是实战成功率）。`:'模型微扰：本方案未评估。';
      const button=document.createElement('button');button.textContent=v.inside?'应用并预览':'应用近似方案并预览';button.onclick=()=>apply(i);
      card.append(title,p,stability,button);return card;
    }));refresh();
  }
  async function poll(id,current){
    try{
      const value=await api('/api/plan/status',{id});
      if(current!==token||job!==id)return;
      if(value.status==='running'){
        const p=value.progress;status(`${p.stage} · ${p.evaluations} 次 · ${p.elapsed.toFixed(1)} 秒${p.best_error_mm==null?'':` · 当前最小偏差 ${p.best_error_mm} mm`}`);
        timer=setTimeout(()=>poll(id,current),350);
      }else{job=null;if(value.result)render(value.result);else{status(value.error||'反算失败',true);refresh();}}
    }catch(e){if(current===token){api('/api/plan/cancel',{id}).catch(()=>{});job=null;status(e.message,true);refresh();}}
  }
  async function start(){
    if($('plan-start').disabled)return;
    visibleGoal=true;picking=false;$('plan-pick').textContent='在球台上选终点';clear();
    const current=++token,savedLayout=layout;job='starting';refresh();status('正在启动后台走位计算…');draw();
    try{
      const v=await api('/api/plan/start',{scene:clone(scene),target:$('plan-target').value,goal:goal(),pocket:$('plan-pocket').value,max_cushions:Number($('plan-banks').value),allow_other:$('plan-other').checked,seconds:Number($('plan-seconds').value),evaluations:480});
      if(current!==token||savedLayout!==fingerprint()||rules()||fired){api('/api/plan/cancel',{id:v.id}).catch(()=>{});return;}
      job=v.id;refresh();poll(v.id,current);
    }catch(e){if(current===token){job=null;status(e.message,true);refresh();}}
  }
  async function apply(index){
    if(job||rules()||locked()||busy||applying||fingerprint()!==layout)return;
    const v=solutions[index];if(!v?.verified)return;
    applying=true;refresh();
    const current=token,currentLayout=layout,next=clone(scene);next.shot=clone(v.shot);const key=JSON.stringify(next);
    try{setScene(next);await calculate(false);if(current!==token||fingerprint()!==currentLayout||JSON.stringify(scene)!==key)return;
      if(record?.complete&&cachedKey===key)status(`已应用方案 ${index+1}，完整路线使用普通预览重新计算。`);
      else status('参数已应用，但预览未完成。请查看上方提示后重试。',true);}
    finally{applying=false;refresh();}
  }
  $('plan-start').onclick=start;$('plan-cancel').onclick=()=>cancel();
  $('plan-pick').onclick=()=>{picking=!picking;$('plan-pick').textContent=picking?'取消选点':'在球台上选终点';if(picking)status('请点击球台指定白球的最终球心；黄色圆表示容差。');};
  $('plan-demo').onclick=()=>{
    setScene(clone(config.presets.find(p=>p.id==='corner').scene),'corner');
    $('plan-target').value='1';$('plan-x').value=1600;$('plan-y').value=500;$('plan-radius').value=60;$('plan-banks').value='0';$('plan-pocket').value='top-right';$('plan-other').checked=false;
    changed();status('示例：1 号球进右上角袋，白球停入黄色圆，白球不碰库。点击“计算走位”。');
  };
  for(const id of fields){$(id).onchange=changed;if(['plan-x','plan-y','plan-radius'].includes(id))$(id).oninput=changed;}
  const controller={refresh,pickGoal,drawGoal};
  if(config&&scene)Promise.resolve().then(refresh);
  return controller;
})();
