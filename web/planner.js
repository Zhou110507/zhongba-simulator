'use strict';

window.ShotPlanner=(()=>{
  let layout='',job=null,token=0,timer=null,picking=false,visibleGoal=false,solutions=[],applying=false,lastRequest=null,lastResult=null;
  const fields=['plan-target','plan-pocket','plan-x','plan-y','plan-radius','plan-banks','plan-seconds','plan-other','plan-approach','plan-first','plan-second','plan-post'];
  const railNames={top:'上库',bottom:'下库',left:'左库',right:'右库',jaw:'袋角'};
  const railText=rails=>rails?.length?rails.map(r=>railNames[r]||r).join(' → '):'无';
  const rules=()=>Boolean(window.TableModes?.isRules());
  const enabled=()=>!rules()&&(window.TableModes?.isPlanner?.()??true);
  const fingerprint=()=>scene?JSON.stringify([scene.model_signature,scene.balls]):'';
  const goal=()=>({x:Number($('plan-x').value)/1000,y:Number($('plan-y').value)/1000,radius:Number($('plan-radius').value)/1000});
  function status(text,error=false){$('plan-status').textContent=text;$('plan-status').dataset.error=String(error);}
  function clear(text){solutions=[];lastResult=null;lastRequest=null;$('plan-export').hidden=true;$('plan-results').replaceChildren();if(text)status(text);}
  function cancel(message='计算已取消。'){
    token++;clearTimeout(timer);timer=null;
    const previous=job;job=null;
    if(previous&&previous!=='starting')api('/api/plan/cancel',{id:previous}).catch(()=>{});
    picking=false;$('plan-pick').textContent='在球台上选终点';
    if(message)status(message);refresh();draw();
  }
  function refresh(){
    if(!scene||!config)return;
    $('planner-panel').hidden=!enabled();if(!enabled()&&picking){picking=false;$('plan-pick').textContent='在球台上选终点';}
    const next=fingerprint();
    if(next!==layout){
      layout=next;
      if(job)cancel('球位已变化，已取消旧局面的反算。');
      clear('球位已更新，请选择目标球和白球终点。');
      const selected=$('plan-target').value;
      $('plan-target').replaceChildren(...scene.balls.filter(b=>b.id!=='cue'&&active(b)).map(b=>{const o=document.createElement('option');o.value=b.id;o.textContent=b.id+' 号球';return o;}));
      if([...$('plan-target').options].some(o=>o.value===selected))$('plan-target').value=selected;
    }
    if((!enabled()||fired)&&job)cancel('已离开自由摆球局面，反算已取消。');
    const disabled=!enabled()||locked()||busy||!active(cueBall())||!$('plan-target').value||applying;
    $('plan-start').disabled=disabled||Boolean(job);
    $('plan-demo').disabled=rules()||locked()||busy||Boolean(job)||applying;
    $('plan-one-demo').disabled=$('plan-two-demo').disabled=$('plan-demo').disabled;
    $('plan-pick').disabled=disabled||Boolean(job);
    $('plan-cancel').hidden=!job;
    for(const id of fields)$(id).disabled=rules()||locked()||busy||Boolean(job)||applying;
    $('plan-rail-controls').hidden=$('plan-approach').value==='direct';
    $('plan-second').disabled||=$('plan-approach').value==='one_bank';
    for(const b of $('plan-results').querySelectorAll('button'))b.disabled=disabled||Boolean(job);
  }
  function changed(){
    if(job)cancel('终点或限制已变化，请重新计算。');
    visibleGoal=true;clear('终点已更新，点击“计算走位”。');draw();
  }
  function pickGoal(point){
    if(!picking||!enabled())return false;
    $('plan-x').value=Math.round(point.x*1000);$('plan-y').value=Math.round(point.y*1000);
    picking=false;$('plan-pick').textContent='在球台上选终点';changed();
    return true;
  }
  function drawGoal(map){
    if(!visibleGoal||!enabled())return;
    const g=goal();if(!Number.isFinite(g.x+g.y+g.radius)||g.radius<=0||g.radius>.3)return;
    const {X,Y,scale}=map;ctx.save();ctx.fillStyle='#f4db7130';ctx.strokeStyle='#f4df91';ctx.lineWidth=2;ctx.setLineDash([6,5]);
    ctx.beginPath();ctx.arc(X(g.x),Y(g.y),g.radius*scale,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.setLineDash([]);
    ctx.beginPath();ctx.moveTo(X(g.x)-6,Y(g.y));ctx.lineTo(X(g.x)+6,Y(g.y));ctx.moveTo(X(g.x),Y(g.y)-6);ctx.lineTo(X(g.x),Y(g.y)+6);ctx.stroke();
    ctx.font='15px sans-serif';ctx.fillStyle='#f3e6b8';ctx.fillText('白球终点',X(g.x)+9,Y(g.y)-g.radius*scale-8);ctx.restore();
  }
  function render(result){
    lastResult=clone(result);$('plan-export').hidden=false;
    solutions=result.solutions;const labels={found:'找到满足终点范围的方案',approximate:'仅找到近似方案，尚未进入指定范围',not_found:'预算内未找到满足硬性条件的方案',incomplete:'前向计算未完整结束，暂无可用方案',cancelled:'计算已取消'};
    status(`${labels[result.status]||'计算结束'} · ${result.evaluations} 次计算 · ${result.elapsed.toFixed(1)} 秒`,result.status!=='found');
    const failed=Object.values(result.numerical_failures||{}).reduce((a,b)=>a+b,0);if(failed)$('plan-status').textContent+=`。${failed} 次前向计算未完成，均未用于推荐。`;
    if(result.performance)$('plan-status').textContent+=` · ${result.performance.route_families} 类候选线路 · ${(result.evaluations/Math.max(.001,result.elapsed)).toFixed(1)} 次/秒`;
    $('plan-results').replaceChildren(...solutions.map((v,i)=>{
      const card=document.createElement('div');card.className='plan-solution'+(v.inside?'':' approximate');
      const title=document.createElement('h3');title.textContent=`方案 ${i+1} · ${v.inside?'范围内':'范围外'} · 偏差 ${(v.error_m*1000).toFixed(1)} mm`;
      const p=document.createElement('p');p.textContent=`方向 ${v.shot.angle_deg.toFixed(3)}° · 杆速 ${v.shot.cue_speed.toFixed(3)} m/s（${(100*v.shot.cue_speed/config.limits.max_cue_speed).toFixed(1)}%）\n击点：左右 ${v.shot.tip_x.toFixed(3)} R / 高低 ${v.shot.tip_y.toFixed(3)} R\n白球初速 ${v.launch_speed.toFixed(2)} m/s · 碰库 ${v.cue_cushions} 次 · 触球 ${v.cue_ball_contacts} 次\n终点 (${Math.round(v.cue_final.x*1000)}, ${Math.round(v.cue_final.y*1000)}) mm · 目标球${v.target_pocket?'进'+(pocketNames[v.target_pocket]||v.target_pocket):'未进袋'}`;p.style.whiteSpace='pre-line';
      const stability=document.createElement('p');const trials=v.perturbations;
      const route=document.createElement('p');route.textContent=`首碰前：${railText(v.approach_rails)}；首碰后：${railText(v.departure_rails)}`;
      stability.textContent=trials?`模型微扰：完成 ${trials.length}/${v.stability_expected||4} 项，${trials.filter(t=>t.inside).length} 项通过；最大偏差 ${Math.max(...trials.map(t=>t.error_mm)).toFixed(1)} mm。方向 ±0.05°、杆速 ±2%、击点 ±0.01 R；不是实战成功率。`:'模型微扰：本方案未评估。';
      const button=document.createElement('button');button.textContent=v.inside?'应用并预览':'应用近似方案并预览';button.onclick=()=>apply(i);
      card.append(title,p,route,stability,button);return card;
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
      const approach=$('plan-approach').value||'direct';
      const input={scene:clone(scene),target:$('plan-target').value,goal:goal(),pocket:$('plan-pocket').value,max_cushions:Number($('plan-banks').value),allow_other:$('plan-other').checked,seconds:Number($('plan-seconds').value),evaluations:approach==='direct'?480:1000,approach,first_rail:approach==='direct'?'any':$('plan-first').value,second_rail:['direct','one_bank'].includes(approach)?'any':$('plan-second').value,post_banks:$('plan-post').value===''?null:Number($('plan-post').value),stability:'full'};
      lastRequest=clone(input);const v=await api('/api/plan/start',input);
      if(current!==token||savedLayout!==fingerprint()||!enabled()||fired){api('/api/plan/cancel',{id:v.id}).catch(()=>{});return;}
      job=v.id;refresh();poll(v.id,current);
    }catch(e){if(current===token){job=null;status(e.message,true);refresh();}}
  }
  async function apply(index){
    if(job||!enabled()||locked()||busy||applying||fingerprint()!==layout)return;
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
    $('plan-approach').value='direct';$('plan-first').value=$('plan-second').value='any';$('plan-post').value='0';
    changed();refresh();status('示例：1 号球进右上角袋，白球停入黄色圆，白球不碰库。点击“计算走位”。');
  };
  async function loadBankExample(kind){
    if(job||locked()||busy||!enabled())return;const previous=layout;
    try{const v=await api('/api/plan/example',{kind});if(layout!==previous||!enabled())return;
      setScene(v.scene);$('plan-target').value=v.target;$('plan-x').value=v.goal.x*1000;$('plan-y').value=v.goal.y*1000;$('plan-radius').value=v.goal.radius*1000;
      $('plan-approach').value=v.approach;$('plan-first').value=v.first_rail;$('plan-second').value=v.second_rail;$('plan-post').value='';$('plan-banks').value=String(v.max_cushions);$('plan-pocket').value='';$('plan-other').checked=false;$('plan-seconds').value='25';
      changed();refresh();status('2 号球挡住直线路径；请按指定库边解到 1 号球，再让白球停入黄色圆。');
    }catch(e){status(e.message,true);}
  }
  $('plan-one-demo').onclick=()=>loadBankExample('one_bank');$('plan-two-demo').onclick=()=>loadBankExample('two_bank');
  $('plan-export').onclick=()=>{
    if(!lastRequest||!lastResult)return;const data={kind:'zhongba-plan-report',schema_version:1,request:lastRequest,result:lastResult};
    const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=url;a.download='中八反算记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  for(const id of fields){$(id).onchange=changed;if(['plan-x','plan-y','plan-radius'].includes(id))$(id).oninput=changed;}
  $('plan-approach').onchange=()=>{if($('plan-approach').value==='direct')$('plan-first').value=$('plan-second').value='any';if($('plan-approach').value==='one_bank')$('plan-second').value='any';const minimum=({direct:0,one_bank:1,two_bank:2,auto:0}[$('plan-approach').value]||0)+Number($('plan-post').value||0);if(minimum<=4&&Number($('plan-banks').value)<minimum)$('plan-banks').value=String(minimum);changed();refresh();};
  const controller={refresh,pickGoal,drawGoal};
  if(config&&scene)Promise.resolve().then(refresh);
  return controller;
})();
