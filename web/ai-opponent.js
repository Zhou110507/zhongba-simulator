'use strict';

// Analysis is tied to the server game revision. Only /execute advances a match.
window.AIOpponent=(()=>{
  let generation=0,job=null,thinking=false,executing=false,analysis=null,binding=null;
  let scheduled=null,attempted='',viewKey='',failed=false;
  const context=()=>window.TableModes?.aiContext()||{game:null,idle:false};
  function ownsTurn(){const {game:g}=context();return Boolean(window.TableModes?.isRules()&&g&&g.ai_player!=null&&g.phase!=='finished'&&(g.phase==='choice'?g.chooser:g.turn)===g.ai_player);}
  const identity=g=>g?`${g.id}:${g.revision}`:'';
  function message(text){$('ai-status').textContent=text;}
  function pause(){ $('ai-auto').checked=false;clearTimeout(scheduled);scheduled=null;refresh(); }
  function cancelForChange(){
    generation++;clearTimeout(scheduled);scheduled=null;
    if(job)api('/api/ai/cancel',{id:job}).catch(()=>{});
    job=null;thinking=false;analysis=null;binding=null;attempted='';viewKey='';failed=false;
    $('ai-routes').replaceChildren();
  }
  function cancel(){pause();cancelForChange();message('AI 已暂停；可重新思考，或切换本地双人接管。');refreshUI();}
  function render(value){
    $('ai-routes').replaceChildren();
    $('ai-model').textContent=value.model==='short-runout-value-v1'?'已训练 · 模拟残局评价':'基础策略';
    if(!value.routes?.length){message(value.message||'本次未找到符合限制的方案。');return;}
    message(`${value.routes[0].clear_verified?'已验证清台路线':'找到部分续接'} · ${value.evaluations} 次模拟 · ${value.elapsed} 秒`);
    for(const [index,route]of value.routes.entries()){
      const card=document.createElement('details'),title=document.createElement('summary');
      card.open=index===0;title.textContent=`${index===0?'推荐':'备选 '+index}：${route.steps.map(s=>s.target).join(' → ')}${route.clear_verified?' · 含黑八清台':' · 后续待规划'}`;card.append(title);
      const list=document.createElement('ol');
      for(const step of route.steps){
        const item=document.createElement('li'),s=step.shot;
        item.textContent=`${step.target} 号 → ${pocketNames[step.pocket]||step.pocket}；白球停点 ${Math.round(step.cue_final.x*1000)}, ${Math.round(step.cue_final.y*1000)} mm。${s.tip_y>.1?'高杆':s.tip_y<-.1?'低杆':'中杆'}，杆头 ${s.cue_speed.toFixed(2)} m/s；切角 ${step.cut_degrees}°，击球距离 ${step.distance_mm} mm。`;
        if(step.human.notes.length)item.textContent+=' '+step.human.notes.join('；');
        list.append(item);
      }
      card.append(list);
      const reason=document.createElement('p');reason.className='hint';reason.textContent=route.reasons.join('。')+'。';card.append(reason);
      if(route.perturbations){const note=document.createElement('p');note.className='hint';note.textContent=`本路线逐杆微扰：${route.perturbations.passed}/${route.perturbations.checked} 项仍合法进球并保留普通续接（工程检查，非真人成功率）。`;card.append(note);}
      $('ai-routes').append(card);
    }
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
    $('ai-cancel').disabled=executing||(!thinking&&!scheduled&&!$('ai-auto').checked);
    $('ai-export').disabled=!analysis;
    if(g?.ai_player==null){message('选择 AI 对手后开始；也可体验三球＋黑八残局。');return;}
    if(!ownsTurn()){if(!thinking)message(g.phase==='finished'?'本局结束。可回看上一杆或开始下一局。':'轮到你击球，AI 等待中。');return;}
    if(!thinking&&!executing&&!analysis&&!failed)message('AI 回合：可先查看清台思路，或勾选自动对打。');
    if($('ai-auto').checked&&idle&&!thinking&&!executing&&attempted!==key&&!scheduled){
      scheduled=setTimeout(()=>{scheduled=null;if(ownsTurn()&&context().idle&&$('ai-auto').checked)think();},600);
    }
  }
  async function think(){
    const {game:g,idle}=context();if(!ownsTurn()||!idle||thinking||executing)return;
    const token=++generation;binding={id:g.id,revision:g.revision};const expected={...binding};
    attempted=identity(g);analysis=null;thinking=true;failed=false;message('AI 正在思考：先检查后斯诺、近库和普通杆法限制…');refreshUI();
    try{
      const started=await api('/api/ai/start',expected);
      if(token!==generation){api('/api/ai/cancel',{id:started.id}).catch(()=>{});return;}
      job=started.id;
      while(token===generation){
        await new Promise(resolve=>setTimeout(resolve,400));
        if(token!==generation)return;
        const status=await api('/api/ai/status',{id:job});
        if(token!==generation||identity(context().game)!==identity(expected))return;
        if(status.status==='running'){message(`${status.progress.stage} · ${status.progress.evaluations} 次模拟`);continue;}
        if(status.status==='error')throw new Error(status.error);
        analysis=status.analysis;thinking=false;render(analysis);refreshUI();
        if($('ai-auto').checked&&analysis.action){
          await new Promise(resolve=>setTimeout(resolve,1600));
          if(token===generation&&$('ai-auto').checked)await execute();
        }
        return;
      }
    }catch(e){if(token===generation){failed=true;message(e.message);}}
    finally{if(token===generation){thinking=false;refreshUI();}}
  }
  async function execute(){
    const {game:g,idle}=context();if(!job||!analysis?.action||!idle||!ownsTurn()||executing||identity(g)!==identity(binding))return;
    const expected={...binding},token=generation;executing=true;window.TableModes.setAIExecuting?.(true);message('正在执行 AI 当前这一杆…');refreshUI();
    try{
      const value=await api('/api/ai/execute',{id:job});
      if(token!==generation)return;
      analysis.action=null;job=null;
      window.TableModes.acceptAI(value,expected);
      message(value.result?'本杆已提交；回放结束后按新球位重新规划。上方保留出杆前的思路。':'AI 已完成规则选择或摆球，可继续查看下一杆思路。');
      if(value.result&&!value.rule_committed){pause();failed=true;message('此杆未完整仿真，未推进对局；请重试或手动接管。');}
    }catch(e){if(token===generation){pause();failed=true;message(e.message);}}
    finally{executing=false;window.TableModes.setAIExecuting?.(false);refreshUI();}
  }
  $('ai-think').onclick=think;$('ai-execute').onclick=execute;$('ai-cancel').onclick=cancel;
  $('ai-auto').onchange=()=>{if(!$('ai-auto').checked)pause();else{attempted='';refresh();}};
  $('ai-export').onclick=()=>{
    if(!analysis)return;
    const data={kind:'zhongba-ai-analysis',schema_version:1,...binding,analysis};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='AI清台思路.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return {refresh,ownsTurn,cancelForChange,pause};
})();
