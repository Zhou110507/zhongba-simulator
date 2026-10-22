'use strict';

// Analysis is tied to the server game revision. Only /execute advances a match.
window.AIOpponent=(()=>{
  let generation=0,job=null,thinking=false,executing=false,analysis=null,binding=null;
  let source=null,future=null,layoutEpoch=0;
  let scheduled=null,rollingTimer=null,attempted='',viewKey='',failed=false;
  const context=()=>window.TableModes?.aiContext()||{game:null,idle:false};
  function ownsTurn(){const {game:g}=context();return Boolean(window.TableModes?.isRules()&&g&&g.ai_player!=null&&['playing','choice'].includes(g.phase)&&(g.phase==='choice'?g.chooser:g.turn)===g.ai_player);}
  const identity=g=>g?`${g.id}:${g.revision}`:'';
  function message(text){$('ai-status').textContent=text;}
  function executionText(e){
    if(e.level==='expert')return '最强（训练原版）：按计划参数执行，无额外出杆误差。';
    const p=e.planned_shot,a=e.actual_shot;
    return `${e.label}：计划方向 ${p.angle_deg.toFixed(3)}°、杆头 ${p.cue_speed.toFixed(3)} m/s；实际方向 ${a.angle_deg.toFixed(3)}°、杆头 ${a.cue_speed.toFixed(3)} m/s。方向偏差 ${e.angle_error_deg.toFixed(3)}°，杆头速度偏差 ${(e.speed_error_fraction*100).toFixed(2)}%。`;
  }
  function pause(){ $('ai-auto').checked=false;clearTimeout(scheduled);scheduled=null;refresh(); }
  function cancelForChange(){
    generation++;layoutEpoch++;clearTimeout(scheduled);scheduled=null;
    clearTimeout(rollingTimer);rollingTimer=null;
    if(job)api('/api/ai/cancel',{id:job}).catch(()=>{});
    if(future)api('/api/ai/cancel',{id:future.id}).catch(()=>{});
    future=null;
    job=null;thinking=false;analysis=null;binding=null;source=null;attempted='';viewKey='';failed=false;
    $('ai-routes').replaceChildren();
  }
  function cancel(){pause();cancelForChange();message('AI 已暂停；可重新思考，或切换本地双人接管。');refreshUI();}
  function render(value){
    $('ai-routes').replaceChildren();
    $('ai-model').textContent=value.model?.startsWith('short-runout-value-')?'已训练 · 进攻与K球':value.model?.startsWith('escape-safety-')?'已训练 · 解球与防守':value.model?.startsWith('random-gap-break-')?'离线开球策略':'基础策略';
    if(!value.routes?.length){
      let text=value.message||'本次未找到符合限制的方案。';
      const action=value.action;
      if(value.rack_read===false)text+='；本局开球搜索 0 次。';
      if(action?.action==='place')text+=` 白球位置 ${Math.round(action.x*1000)}, ${Math.round(action.y*1000)} mm。`;
      if(action?.action==='shoot'){const s=action.shot;text+=` 杆头 ${s.cue_speed.toFixed(2)} m/s，高低击点 ${s.tip_y.toFixed(2)} R、侧击点 ${s.tip_x.toFixed(2)} R${value.cue_cushions!=null?`；白球预计 ${value.cue_cushions} 库`:''}。`;}
      if(value.predicted_fouls?.length)text+=' 预计风险：'+value.predicted_fouls.join('、');
      message(text);return;
    }
    const rolling=value.rolling;
    message(`${value.cache_hit?'球位符合预期，复用后续路线 · ':''}${value.routes[0].clear_verified?'已验证清台路线':'找到部分续接'} · ${value.evaluations} 次模拟 · ${value.elapsed} 秒${rolling?.extending?` · 保留后续 ${rolling.remaining} 杆，后台继续补算`:''}${value.extended_steps?` · 已从队尾新增 ${value.extended_steps} 杆（${value.extension_evaluations} 次模拟）`:''}`);
    for(const [index,route]of value.routes.entries()){
      const card=document.createElement('details'),title=document.createElement('summary');
      card.open=index===0;title.textContent=`${index===0?'推荐':'备选 '+index}：${route.steps.map(s=>s.target).join(' → ')}${route.clear_verified?' · 含黑八清台':' · 后续待规划'}`;card.append(title);
      const list=document.createElement('ol');
      for(const step of route.steps){
        const item=document.createElement('li'),s=step.shot;
        const side=Math.abs(s.tip_x)>.02?`＋${s.tip_x>0?'右':'左'}塞 ${Math.abs(s.tip_x).toFixed(2)} R`:'';
        item.textContent=`${step.target} 号 → ${pocketNames[step.pocket]||step.pocket}；白球停点 ${Math.round(step.cue_final.x*1000)}, ${Math.round(step.cue_final.y*1000)} mm。${s.tip_y>.1?'高杆':s.tip_y<-.1?'低杆':'中杆'}${side}，杆头 ${s.cue_speed.toFixed(2)} m/s；白球 ${step.cue_cushions??0} 库，${step.clean_pot===false?'目标球碰袋角后入袋':step.clean_pot===true?'目标球未碰袋角入袋':'旧记录未注明袋角接触'}；切角 ${step.cut_degrees}°，白球到接触位 ${step.distance_mm} mm，目标球距袋 ${step.object_distance_mm??'未记录'} mm。`;
        if(step.human.notes.length)item.textContent+=' '+step.human.notes.join('；');
        if(step.secondary_contacts?.length)item.textContent+=` 此路线包含碰球 ${step.secondary_contacts.map(p=>p.join('／')).join('、')}${step.opened_targets?.length?'，打开 '+step.opened_targets.join('、')+' 号球的进攻线路':'，走位误差可能被放大'}。`;
        list.append(item);
      }
      card.append(list);
      const reason=document.createElement('p');reason.className='hint';reason.textContent=route.reasons.join('。')+'。';card.append(reason);
      if(route.perturbations){const note=document.createElement('p');note.className='hint';note.textContent=`本路线逐杆微扰：${route.perturbations.passed}/${route.perturbations.checked} 项仍合法进球并保留普通续接（工程检查，非真人成功率）。`;card.append(note);}
      $('ai-routes').append(card);
    }
  }
  function watchRolling(token,expected,key){
    clearTimeout(rollingTimer);rollingTimer=null;
    const r=analysis?.rolling;
    if(!r||!analysis.routes?.length||analysis.routes[0].clear_verified||r.exhausted||(!r.extending&&r.remaining>=r.target))return;
    rollingTimer=setTimeout(async()=>{
      rollingTimer=null;
      if(token!==generation||executing||job!==key||identity(context().game)!==identity(expected)||!context().idle)return;
      try{
        const status=await api('/api/ai/status',{id:key});
        if(token!==generation||executing||job!==key||identity(context().game)!==identity(expected))return;
        if(status.status==='found'&&status.analysis){analysis=status.analysis;render(analysis);refreshUI();watchRolling(token,expected,key);}
      }catch{} // The retained current stroke remains usable if background polling fails.
    },750);
  }
  function refresh(){
    const {game:g,idle}=context(),rule=Boolean(window.TableModes?.isRules());
    $('ai-panel').hidden=!rule;
    if(!rule)return;
    const key=identity(g);
    if(viewKey&&viewKey!==g?.id){$('ai-routes').replaceChildren();analysis=null;binding=null;}
    viewKey=g?.id||'';
    $('ai-think').disabled=!ownsTurn()||!idle||thinking||executing;
    $('ai-execute').disabled=!ownsTurn()||!idle||thinking||executing||!analysis?.action||identity(binding)!==key;
    $('ai-cancel').disabled=executing||(!thinking&&!scheduled&&!future&&!$('ai-auto').checked);
    $('ai-export').disabled=!analysis;
    if(g?.ai_player==null){message('选择 AI 对手后开始；也可体验三球＋黑八残局。');return;}
    if(g?.phase==='setup'){message('摆好你自己的残局，再点击“完成摆球，开始分析”。');return;}
    if(!ownsTurn()){if(!thinking)message(g.phase==='finished'?'本局结束。可回看上一杆或开始下一局。':future?'球运动中，AI 已预先计算下一回合；球停后才会执行。':'轮到你击球，AI 等待中。');return;}
    if(!thinking&&!executing&&!analysis&&!failed)message('AI 回合：可先查看清台思路，或勾选自动对打。');
    if($('ai-auto').checked&&idle&&!thinking&&!executing&&attempted!==key&&!scheduled){
      scheduled=setTimeout(()=>{scheduled=null;if(ownsTurn()&&context().idle&&$('ai-auto').checked)think();},600);
    }
  }
  async function think(){
    const {game:g,idle}=context();if(!ownsTurn()||!idle||thinking||executing)return;
    const token=++generation;binding={id:g.id,revision:g.revision};const expected={...binding};
    source={source_scene:g.scene,source_groups:g.groups,source_turn:g.turn,source_ai_player:g.ai_player,source_ai_level:g.ai_level||'expert'};
    attempted=identity(g);analysis=null;thinking=true;failed=false;message('AI 正在思考：先检查后斯诺、近库和普通杆法限制…');refreshUI();
    try{
      let started;
      if(future&&future.game_id===g.id&&future.revision===g.revision){started=future;future=null;}
      else{if(future)api('/api/ai/cancel',{id:future.id}).catch(()=>{});future=null;started=await api('/api/ai/start',expected);}
      if(token!==generation){api('/api/ai/cancel',{id:started.id}).catch(()=>{});return;}
      job=started.id;
      while(token===generation){
        await new Promise(resolve=>setTimeout(resolve,400));
        if(token!==generation)return;
        const status=await api('/api/ai/status',{id:job});
        if(token!==generation||identity(context().game)!==identity(expected))return;
        if(status.status==='running'){message(`${status.progress.stage} · ${status.progress.evaluations} 次模拟`);continue;}
        if(status.status==='error')throw new Error(status.error);
        analysis=status.analysis;
        if(started.reused_job&&started.status==='found')analysis={...analysis,cache_hit:true,cached_from_evaluations:analysis.evaluations,evaluations:0,elapsed:0};
        thinking=false;render(analysis);refreshUI();watchRolling(token,expected,job);
        if($('ai-auto').checked&&analysis.action){
          await new Promise(resolve=>setTimeout(resolve,1600));
          if(token===generation&&$('ai-auto').checked)await execute();
        }
        return;
      }
    }catch(e){if(token===generation){failed=true;if(/计算繁忙|已有 AI 在思考/.test(e.message)&&$('ai-auto').checked)attempted='';message(e.message);}}
    finally{if(token===generation){thinking=false;refreshUI();}}
  }
  async function execute(){
    const {game:g,idle}=context();if(!job||!analysis?.action||!idle||!ownsTurn()||executing||identity(g)!==identity(binding))return;
    const expected={...binding},token=generation;executing=true;clearTimeout(rollingTimer);rollingTimer=null;window.TableModes.setAIExecuting?.(true);message('正在执行 AI 当前这一杆…');refreshUI();
    try{
      const value=await api('/api/ai/execute',{id:job,prefetch:true});
      if(token!==generation){if(value.prefetch)api('/api/ai/cancel',{id:value.prefetch.id}).catch(()=>{});return;}
      future=value.prefetch||null;
      if(value.ai_execution)analysis.execution=value.ai_execution;
      analysis.action=null;job=null;
      window.TableModes.acceptAI(value,expected);
      message(value.result?(future?.extending?`本杆已提交；保留后续 ${future.queued_steps} 杆，回放期间从队尾继续补算。`:future?.cache_hit?'本杆已提交；后续路线与实际停点相符，已复用，无需重算。':future?'本杆已提交；回放同时正在预先计算下一杆。':'本杆已提交；球停后按实际局面继续。'):'AI 已完成规则选择或摆球，可继续查看下一杆思路。');
      if(value.result&&!value.rule_committed){pause();failed=true;message('此杆未完整仿真，未推进对局；请重试或手动接管。');}
    }catch(e){if(token===generation){pause();failed=true;message(e.message);}}
    finally{executing=false;window.TableModes.setAIExecuting?.(false);refreshUI();}
  }
  async function precompute(g){
    if(!window.TableModes?.isRules()||g?.ai_player==null||!['playing','choice'].includes(g.phase)||(g.phase==='choice'?g.chooser:g.turn)!==g.ai_player)return;
    const token=layoutEpoch;
    try{
      const started=await api('/api/ai/start',{id:g.id,revision:g.revision});
      const live=context().game;
      if(token!==layoutEpoch||!window.TableModes?.isRules()||live?.id!==g.id||live.revision>g.revision){api('/api/ai/cancel',{id:started.id}).catch(()=>{});return;}
      if(future&&future.revision>g.revision)return;
      future={...started,game_id:g.id,revision:g.revision};refreshUI();
    }catch{} // CPU occupied: regular post-replay start remains available.
  }
  $('ai-think').onclick=think;$('ai-execute').onclick=execute;$('ai-cancel').onclick=cancel;
  $('ai-auto').onchange=()=>{if(!$('ai-auto').checked)pause();else{attempted='';refresh();}};
  $('ai-export').onclick=()=>{
    if(!analysis)return;
    const data={kind:'zhongba-ai-analysis',schema_version:2,...binding,...source,analysis};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='AI清台思路.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return {refresh,ownsTurn,cancelForChange,pause,think,precompute,executionText};
})();
