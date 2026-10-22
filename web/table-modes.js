'use strict';

// Mode coordination uses the practice renderer/replay and the same scene API.
// Rule boards and decisions are owned by the server; only shot inputs are sent.
window.TableModes=(()=>{
  const MODE_KEY='zhongba.table-mode.v1',MATCH_KEY='zhongba.rule-match.v1';
  let wanted,remembered;try{wanted=localStorage.getItem(MODE_KEY);remembered=localStorage.getItem(MATCH_KEY);}catch{}
  let current='free',game=null,freeConfig=null,ruleConfig=null,initialized=false,nonce=0,gameBusy=false,freeSeed=0,lastPanelKey='',submitting=false,lastShot=null,reviewing=false;
  const isRules=()=>current==='rules';
  const isSetup=()=>isRules()&&game?.phase==='setup';
  const isPlanner=()=>current==='planner';
  const showTrails=()=>!isRules()&&$('trails').checked;
  const displayGame=()=>!reviewing&&record?.rule_committed&&fired&&time>=record.result.duration?record.game_after:game;
  function store(){try{localStorage.setItem(MODE_KEY,current);if(game)localStorage.setItem(MATCH_KEY,game.id);}catch{}}
  function syncFree(){if(isRules()||!scene)return;const ids=scene.balls.filter(b=>b.id!=='cue').map(b=>b.id);$('target-count').value=ids.length;$('free-count').textContent=`当前 ${ids.length} 颗目标球＋1 颗白球（${scene.balls.filter(active).length} 颗在台）`;for(const input of $('ball-picker').querySelectorAll('input'))input.checked=ids.includes(input.value);$('free-cue-x').value=Math.round(cueBall().position.x*1000);$('free-cue-y').value=Math.round(cueBall().position.y*1000);}
  function onScene(){if(!initialized&&config){initialized=true;freeConfig=clone(config);for(let i=1;i<=15;i++){const label=document.createElement('label'),input=document.createElement('input'),marker=document.createElement('span');input.type='checkbox';input.value=String(i);input.setAttribute('aria-label',`选择 ${i} 号球`);marker.textContent=i;marker.style.background=color(String(i));input.onchange=()=>$('target-count').value=$('ball-picker').querySelectorAll('input:checked').length;label.append(input,marker);$('ball-picker').append(label);}if(wanted==='rules'||wanted==='planner')Promise.resolve().then(()=>switchMode(wanted));}syncFree();refresh();}
  function adopt(value){reviewing=false;game=value;current='rules';config=ruleConfig;$('ai-level').value=value.ai_level||'expert';$('opponent').value=value.ai_player==null?'':String(value.ai_player);store();setScene(value.scene,'custom',false);if(value.phase==='setup'){mode='edit';pending=null;}else if(value.needs_placement){mode='edit';pending='cue';}refreshUI();draw();}
  async function switchMode(target,forceNew=false,scenario='rack'){if(submitting)return;window.AIOpponent?.cancelForChange();if(target!=='rules'&&!isRules()&&initialized&&!gameBusy){++nonce;current=target;store();refreshUI();draw();announce(isPlanner()?'反算台已就绪：选择目标球与白球终点。':'练习台已就绪：在右侧直接调整力度与杆法。');return;}const token=++nonce;lastShot=null;reviewing=false;gameBusy=true;invalidate();refreshUI();announce('正在准备球台…');try{if(target!=='rules'){current=target;config=freeConfig;store();let value=config.presets.find(p=>p.id==='free').scene;try{const saved=localStorage.getItem(STORAGE);if(saved)value=(await api('/api/validate',JSON.parse(saved))).scene;}catch{}if(token!==nonce)return;setScene(value,'custom',false);announce('自由球台已就绪，可选择目标球数量、球号和白球位置。');}else{if(!ruleConfig)ruleConfig=await api('/api/rules/config');let value;const key=game?.id||remembered;if(!forceNew&&key){try{value=await api('/api/game/get',{id:key});}catch{}}if(!value)value=await api('/api/game/new',{breaker:Number($('breaker').value),gap_mm:Number($('rack-gap').value),ai_player:['0','1'].includes($('opponent').value)?Number($('opponent').value):null,ai_level:$('ai-level').value||'expert',scenario});if(token!==nonce)return;adopt(value);announce(value.scenario==='ai_endgame'?'AI 三球＋黑八残局已就绪，可查看思路后让 AI 执行。':value.is_break?'中八规则对局已就绪。开球前可在线后摆放白球。':'已恢复中八对局，请按当前球权和判罚提示继续。');}}catch(e){if(token===nonce)announce(e.message,true);}finally{if(token===nonce){gameBusy=false;refreshUI();draw();}}}
  function locksAction(){return Boolean(gameBusy||(isRules()&&game&&(!['playing','setup'].includes(game.phase)||submitting||window.AIOpponent?.ownsTurn())));}
  function deferLaunch(){if(!scene||!config)return false;if(isSetup())$('guide-info').textContent='自由摆球阶段：完成摆球后，AI 将按新球形重新分析。';if(isRules()&&(game.phase!=='playing'||game.needs_placement)){ $('launch-speed').textContent='—';return true;}if(scene.balls.filter(active).length>8){const shot=scene.shot,cue=config.model.cue,m=config.ball_spec.mass;const inverse=1/cue.effective_mass+(1+2.5*(shot.tip_x**2+shot.tip_y**2))/m;$('launch-speed').textContent=((1+cue.restitution)*shot.cue_speed/inverse/m).toFixed(2)+' m/s';$('guide-info').textContent='即时瞄准已显示；多球局面请点击预览或出杆计算完整路线。';return true;}return false;}
  function setControlLayout(rule,g){
    const aiTurn=rule&&g?.ai_player!=null&&(g.phase==='choice'?g.chooser:g.turn)===g.ai_player;
    $('workspace').classList.toggle('rule-workspace',rule);
    $('workspace').classList.toggle('ai-turn',aiTurn);
    $('shot-control-context').textContent=rule?(aiTurn?'AI 回合':g?.phase==='playing'?'你的回合':'水平出杆'):'水平出杆';
  }
  function renderPlayerCard(card,g,i){
    card.replaceChildren();card.classList.toggle('active-player',g.phase!=='finished'&&(g.phase==='choice'?g.chooser:g.turn)===i);
    const title=document.createElement('strong'),score=document.createElement('span');
    title.textContent=`${g.ai_player===i?'AI · '+(ruleConfig?.ai_difficulty?.levels?.[g.ai_level||'expert']?.label||'最强')+' · ':''}玩家 ${i+1}`;
    score.className='score';score.textContent=g.scores[i];card.append(title,score);
    const chosen=g.groups[i];if(!chosen)return;
    const remaining=g.scene.balls.filter(b=>active(b)&&b.id!=='cue'&&(chosen==='solid'?Number(b.id)>=1&&Number(b.id)<=7:Number(b.id)>=9&&Number(b.id)<=15)).sort((a,b)=>Number(a.id)-Number(b.id));
    const p=document.createElement('p');p.textContent=chosen==='solid'?'全色球':'花色球';
    const row=document.createElement('div');row.className='group-balls';row.setAttribute('aria-label',p.textContent+'剩余球');
    for(const b of remaining)row.append(ballIcon(b.id));
    if(!remaining.length&&g.scene.balls.some(b=>b.id==='8'&&active(b))){p.textContent+=' · 可击打 8 号球';row.append(ballIcon('8'));}
    card.append(p,row);
  }
  function ballIcon(id){
    const ball=document.createElement('span'),number=document.createElement('span');
    ball.className='group-ball'+(Number(id)>=9?' stripe':id==='8'?' black':'');
    ball.style.backgroundColor=color(id);ball.setAttribute('aria-label',id+' 号球');
    number.className='ball-number';number.textContent=id;number.setAttribute('aria-hidden','true');
    ball.append(number);return ball;
  }
  function decisionText(value){const d=value.last_decision;if(!d)return value.is_break?'15 球已摆好；白球在线后，可直接开球':'请按当前球组继续击球';return d.outcome+(d.fouls.length?'。原因：'+d.fouls.join('、'):'')+(d.clauses.length?'（条款 '+d.clauses.join('；')+'）':'');}
  function refresh(){if(!initialized)return;window.AIOpponent?.refresh();const rule=isRules(),g=rule?displayGame():null;setControlLayout(rule,g);const execution=g?.last_decision?.ai_execution;$('ai-execution-record').hidden=!rule||!execution;$('ai-execution').textContent=execution?window.AIOpponent?.executionText(execution)||'':'';$('trails-control').hidden=rule;$('trails').disabled=rule;$('next').hidden=rule;$('last-shot').hidden=!rule;$('last-shot').disabled=!lastShot||busy||gameBusy||fired;$('before').hidden=rule&&!reviewing&&!record;$('before').textContent=reviewing?'返回当前球台':'回到出杆前';const panelKey=[current,g?.id,g?.revision,fired,Boolean(record&&time>=record.result.duration),gameBusy,busy,mode,reviewing,Boolean(record?.rule_committed)].join('|');if(panelKey===lastPanelKey){if(rule)applyRuleLocks(g);else{$('generate-free').disabled=gameBusy;$('fill-fifteen').disabled=gameBusy;}return;}lastPanelKey=panelKey;$('free-mode').setAttribute('aria-pressed',String(!rule&&!isPlanner()));$('planner-mode').setAttribute('aria-pressed',String(isPlanner()));$('shot-settings').hidden=isPlanner();$('rules-mode').setAttribute('aria-pressed',String(rule));$('free-setup').hidden=rule;$('rule-panel').hidden=!rule;$('mode-caption').textContent=rule?(g?.ai_player==null?'CBSA 2017 · 本地双人 · 球停后自动继续':'CBSA 2017 · 可选 AI 对手 · 球停后自动继续'):isPlanner()?'碰库线路 · 障碍球 · 多方案反算':'可选 0–15 颗目标球 · 自由练习';$('edit-mode').textContent=rule&&!isSetup()?'摆放白球':'摆球';$('save').textContent=rule&&!isSetup()?'导出对局记录':'保存场景';document.querySelector('h1 span').textContent=rule?'规则对局':isPlanner()?'反算台':'练习台';$('coordinates').textContent=`${Math.round(config.model.table.length*1000)} × ${Math.round(config.model.table.width*1000)} mm · 球径 57.15 mm`;
    const equipment=document.querySelectorAll('.equipment-row b');if(equipment.length>=2){equipment[0].textContent=rule?'CBSA 2017 规则台型':'乔氏公开台型';equipment[1].textContent=`${Math.round(config.model.table.length*1000)} × ${Math.round(config.model.table.width*1000)}`;}
    if(!rule){$('generate-free').disabled=gameBusy;$('fill-fifteen').disabled=gameBusy;return;}
    const finishedReplay=record&&fired&&time>=record.result.duration;
    $('ai-group-control').hidden=$('ai-finish-setup').hidden=$('ai-setup-hint').hidden=!isSetup();
    $('rule-turn').textContent=isSetup()?'自定义 AI 残局 · 自由摆球':g.phase==='finished'?`玩家 ${g.winner+1} 赢得第 ${g.rack_number} 局`:`第 ${g.rack_number} 局 · 玩家 ${g.turn+1}${g.phase==='choice'?'等待规则选择':g.is_break?'开球':'击球'}`;
    for(const [i,id]of ['player-one','player-two'].entries())renderPlayerCard($(id),g,i);
    let summary=isSetup()?'独立练习局正在摆球，尚未开始判罚。可移动任意球并选择 AI 球组。':decisionText(g);if(g.is_break)summary+=g.gap_mm?`。本局采用 ≤${g.gap_mm} mm 随机微隙（工程设置）`:'。本局采用规范紧密摆球';if(g.ball_in_hand&&g.phase==='playing')summary+=`。玩家 ${g.turn+1} 持${g.ball_in_hand==='head'?'线后':'全台'}自由球${g.needs_placement?'，请先点击台面或输入坐标摆白球':'，出杆前可继续调整白球'}`;textRule(summary,Boolean(g.last_decision?.fouls.length));
    $('rule-choices').replaceChildren();if(g.phase==='choice'&&(!fired||finishedReplay)){const labels={rerack_self:`玩家 ${g.chooser+1} 重新开球`,rerack_opponent:`要求玩家 ${2-g.chooser} 重开（警告）`,accept_free:'接受台面 · 全台自由球',accept_head:'线后自由球',accept_position:'接受白球当前位置',choose_solid:'选择全色球',choose_stripe:'选择花色球'};for(const choice of g.choices){const button=document.createElement('button');button.textContent=labels[choice];button.disabled=gameBusy||Boolean(window.AIOpponent?.ownsTurn());button.onclick=()=>act('choice',{choice});$('rule-choices').append(button);}}
    $('head-respot').replaceChildren();if(g.head_respot_candidates&&(!fired||finishedReplay))for(const ball of g.head_respot_candidates){const button=document.createElement('button');button.textContent=`将线后 ${ball} 号球重置到置球点`;button.onclick=()=>act('respot_head',{ball});button.disabled=gameBusy||Boolean(window.AIOpponent?.ownsTurn());$('head-respot').append(button);}
    applyRuleLocks(g);
  }
  function applyRuleLocks(g){
    $('ai-level').disabled=gameBusy||submitting||fired||busy||g.ai_player==null;
    $('ai-custom').disabled=gameBusy||submitting||fired;
    $('ai-finish-setup').disabled=$('ai-group').disabled=gameBusy||submitting||fired;
    if(isSetup()){
      $('preset').disabled=true;$('shoot').disabled=$('preview').disabled=true;
      $('new-match').disabled=$('opponent').disabled=$('ai-demo').disabled=gameBusy||submitting;
      $('before').disabled=true;return;
    }
    const finishedReplay=record&&fired&&time>=record.result.duration;
    const aiTurn=Boolean(window.AIOpponent?.ownsTurn());
    const mayPlace=!aiTurn&&game?.phase==='playing'&&Boolean(game.ball_in_hand)&&!fired&&!gameBusy&&!busy&&!submitting;
    for(const id of ['preset','selected-ball','add','remove','undo','import'])$(id).disabled=true;
    for(const id of ['ball-x','ball-y','apply-position','edit-mode'])$(id).disabled=!mayPlace;
    $('shoot').disabled||=gameBusy||game.phase!=='playing'||game.needs_placement||aiTurn;
    $('preview').disabled||=gameBusy||game.phase!=='playing'||game.needs_placement||aiTurn;
    $('before').disabled=reviewing?false:submitting||Boolean(record?.rule_committed)||!record;
    $('next-rack').hidden=g.phase!=='finished';$('next-rack').disabled=gameBusy||Boolean(fired&&!finishedReplay);$('new-match').disabled=gameBusy||submitting;$('opponent').disabled=gameBusy||submitting||fired;$('ai-demo').disabled=gameBusy||submitting||fired;$('free-mode').disabled=submitting;$('planner-mode').disabled=submitting;$('rules-mode').disabled=submitting;
  }
  function textRule(value,foul){$('rule-status').textContent=value;$('rule-status').classList.toggle('foul',foul);}
  async function act(action,extra={}){if(gameBusy||busy||submitting)return;if(action==='next_rack')lastShot=null;const source=displayGame();const token=nonce;gameBusy=true;refreshUI();try{const value=await api('/api/game/action',{id:source.id,revision:source.revision,action,...extra});if(token!==nonce||!isRules())return;adopt(value);announce(action==='place'?'白球已按自由球范围摆好。':'对局已更新，可按提示继续。');}catch(e){if(token===nonce)announce(e.message,true);}finally{if(token===nonce){gameBusy=false;refreshUI();draw();}}}
  function place(id,position){if(id!=='cue'||!game.ball_in_hand){announce('规则对局中只能在获得自由球权时移动白球。',true);return false;}act('place',{x:position.x,y:position.y});return false;}
  function beginPlace(){if(!game.ball_in_hand)return;mode='edit';pending='cue';selected='cue';refreshSelection();refreshUI();draw();announce(game.ball_in_hand==='head'?'点击开球线后空位摆放白球，也可输入毫米坐标。':'点击台面空位摆放白球，也可输入毫米坐标。');}
  async function calculateRule(commit){if(fired||busy||gameBusy||game.phase!=='playing'||game.needs_placement||window.AIOpponent?.ownsTurn())return;const token=revision,currentRequest=++requestNumber,snapshot=clone(scene);busy=true;submitting=commit;requestController?.abort();requestController=new AbortController();refreshUI();announce(commit?'正在计算并判定本杆…':'正在计算预览，预览不会推进对局…');try{const value=await api(commit?'/api/game/action':'/api/game/preview',{id:game.id,revision:game.revision,...(commit?{action:'shoot'}:{}),shot:snapshot.shot},requestController.signal);if(token!==revision||currentRequest!==requestNumber)return;record=value;cachedKey=JSON.stringify(snapshot);populateEvents();const cue=value.result.initial.find(b=>b.id==='cue');$('launch-speed').textContent=Math.hypot(cue.velocity.x,cue.velocity.y).toFixed(2)+' m/s';if(commit){startReplay();if(value.complete&&value.rule_committed)window.AIOpponent?.precompute?.(value.game_after);}else{announce(value.complete?'预览完成；点击出杆才会正式判罚和推进对局。':statusText(value.result.status),!value.complete);draw();}}catch(e){if(token===revision&&e.name!=='AbortError')announce(e.message,true);}finally{if(token===revision&&currentRequest===requestNumber){busy=false;submitting=false;refreshUI();}}}
  function finish(){if(!isRules())return false;if(reviewing){announce('上一杆回看结束。点击“返回当前球台”继续对局。');refresh();return true;}if(!record?.complete||!record.rule_committed)return false;lastShot=record;const after=record.game_after;adopt(after);announce(decisionText(after)+(after.needs_placement?'。请摆放自由球。':after.phase==='playing'?'。已进入下一杆。':''),Boolean(after.last_decision?.fouls.length));return true;}
  function review(){window.AIOpponent?.pause();if(!isRules()||!lastShot||fired||busy||gameBusy)return;reviewing=true;record=lastShot;populateEvents();startReplay();announce('正在回看上一杆；回看不会再次判罚或推进球权。');}
  function before(){if(!isRules())return false;if(reviewing){adopt(game);announce('已返回当前球台。');return true;}return false;}
  function acceptAI(value,expected){
    if(!isRules()||game.id!==expected.id||game.revision!==expected.revision)return false;
    if(value.result){
      invalidate();scene.shot=clone(value.snapshot.shot);syncShotControls();
      record=value;cachedKey=JSON.stringify(scene);populateEvents();
      const cue=value.result.initial.find(b=>b.id==='cue');$('launch-speed').textContent=Math.hypot(cue.velocity.x,cue.velocity.y).toFixed(2)+' m/s';
      if(value.complete&&value.rule_committed)startReplay({cueAnimation:true});
      else announce('AI 此杆未完整仿真，未推进对局。',true);
    }else adopt(value);
    return true;
  }
  function exportRules(){if(!isRules()||isSetup())return false;const value=displayGame(),url=URL.createObjectURL(new Blob([JSON.stringify({kind:'zhongba-match-record',schema_version:1,...value},null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='中八对局记录.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);announce('已导出对局记录。对局本身由本机服务自动保存。');return true;}
  function drawMarkings(map){if(!isRules())return;const {X,Y,scale}=map,w=config.model.table.width,l=config.model.table.length;ctx.save();if(game.ball_in_hand==='head'&&!fired){ctx.fillStyle='#d6e8a511';ctx.fillRect(X(0),Y(w),.635*scale,w*scale);}ctx.strokeStyle='#cbdca65c';ctx.lineWidth=1.5;ctx.setLineDash([9,8]);ctx.beginPath();ctx.moveTo(X(.635),Y(0));ctx.lineTo(X(.635),Y(w));ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#d7e6bd';for(const x of [.635,l-.635]){ctx.beginPath();ctx.arc(X(x),Y(w/2),2,0,Math.PI*2);ctx.fill();}ctx.font='16px sans-serif';ctx.fillStyle='#c4d6b294';ctx.fillText('开球线',X(.635)+8,Y(w-.08));ctx.restore();}
  $('free-mode').onclick=()=>switchMode('free');$('planner-mode').onclick=()=>switchMode('planner');$('rules-mode').onclick=()=>switchMode('rules');$('new-match').onclick=()=>switchMode('rules',true);$('next-rack').onclick=()=>act('next_rack');
  $('target-count').oninput=e=>{const n=Number(e.target.value);if(Number.isInteger(n)&&n>=0&&n<=15)for(const input of $('ball-picker').querySelectorAll('input'))input.checked=Number(input.value)<=n;};
  async function generateFree(){if(gameBusy||isRules())return;const count=Number($('target-count').value);if(!Number.isInteger(count)||count<0||count>15){announce('目标球个数必须是 0 到 15 的整数。',true);return;}const token=nonce,currentRevision=revision;gameBusy=true;refreshUI();try{const value=await api('/api/free-table',{balls:[...$('ball-picker').querySelectorAll('input:checked')].map(i=>i.value),cue:{x:Number($('free-cue-x').value)/1000,y:Number($('free-cue-y').value)/1000},seed:freeSeed++});if(token!==nonce||currentRevision!==revision)return;setScene(value.scene,'custom');announce('自由球台已生成，可任意摆球、调整击点和出杆。');}catch(e){if(token===nonce)announce(e.message,true);}finally{if(token===nonce){gameBusy=false;refreshUI();draw();}}}
  $('generate-free').onclick=generateFree;
  $('fill-fifteen').onclick=()=>{if(gameBusy||isRules())return;$('target-count').value=15;for(const input of $('ball-picker').querySelectorAll('input'))input.checked=true;return generateFree();};
  async function customLayout(){
    if(!isRules()||busy||gameBusy||submitting||fired)return;
    window.AIOpponent?.pause();window.AIOpponent?.cancelForChange();
    const snapshot=clone(scene),ai=game.ai_player??1,chosen=game.groups[ai]||'solid';
    const token=++nonce;gameBusy=true;refreshUI();
    try{
      const value=await api('/api/game/new',{scenario:'ai_custom',scene:snapshot,ai_player:ai,ai_group:chosen,ai_level:game.ai_level||'expert'});
      if(token!==nonce)return;
      lastShot=null;adopt(value);$('ai-group').value=chosen;
      announce('已建立独立 AI 残局。拖动任意球或输入坐标，添加／移除球后完成摆球。');
    }catch(e){if(token===nonce)announce(e.message,true);}
    finally{if(token===nonce){gameBusy=false;refreshUI();draw();}}
  }
  $('ai-custom').onclick=customLayout;
  $('ai-finish-setup').onclick=async()=>{
    if(!isSetup()||gameBusy)return;
    await act('finish_setup',{scene:clone(scene),ai_group:$('ai-group').value,ai_player:game.ai_player??1});
    if(!isSetup())window.AIOpponent?.think();
  };
  $('last-shot').onclick=review;
  $('opponent').onchange=()=>{window.AIOpponent?.cancelForChange();return act('set_ai',{ai_player:['0','1'].includes($('opponent').value)?Number($('opponent').value):null});};
  $('ai-level').onchange=async()=>{window.AIOpponent?.cancelForChange();await act('set_ai_level',{ai_level:$('ai-level').value});$('ai-level').value=game.ai_level||'expert';refreshUI();};
  $('ai-demo').onclick=()=>{$('opponent').value='1';return switchMode('rules',true,'ai_endgame');};
  const controller={isSetup,setAIExecuting:value=>{submitting=value;refreshUI();},aiContext:()=>({game:game?clone(game):null,idle:isRules()&&!busy&&!gameBusy&&!submitting&&!fired&&!reviewing}),acceptAI,switchMode,act,isRules,isPlanner,showTrails,store,onScene,refresh,locksAction,deferLaunch,place,beginPlace,calculate:calculateRule,finish,before,exportRules,drawMarkings};
  if(config&&scene)Promise.resolve().then(onScene);
  return controller;
})();
