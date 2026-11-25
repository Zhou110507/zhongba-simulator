// Integration smoke test for the generated game, in a new headless Chrome
// profile and an ephemeral local server. No browser driver or npm install.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const deadline=async(fn,label,ms=45000)=>{
  const end=Date.now()+ms;let last;
  while(Date.now()<end){try{const v=await fn();if(v)return v;}catch(e){last=e;}await delay(100);}
  throw Error('Timed out: '+label+(last?' / '+last.message:''));
};
// Observe the frame that actually reaches the selected renderer without changing any camera controls.
function installCameraProbe(){
  const software=document.getElementById('room-stage').dataset.renderer==='software-3d';
  const proto=software?ArenaSoftware.prototype:ArenaRenderer.Renderer.prototype;
  const original=proto.render,canvas=document.getElementById(software?'room-soft':'room-gl');
  let lastFrame,lastState;
  function clientPoint(p){
    const rect=canvas.getBoundingClientRect();
    return {x:rect.left+p.x*rect.width/lastFrame.width,y:rect.top+p.y*rect.height/lastFrame.height};
  }
  const probe={sample:null,
    aimTarget(kind){
      const ball=lastState.balls.find(b=>b.id==='1'),cue=lastState.balls.find(b=>b.id==='cue');
      const pocket=lastState.config.geometry.pockets.find(p=>p.id==='top-right');
      const dest=kind==='ball'?ball.position:pocket.fall_center,z=kind==='ball'?ball.spec.radius:0;
      return {point:clientPoint(lastFrame.project([dest.x,dest.y,z])),
        angle:Math.atan2(dest.y-cue.position.y,dest.x-cue.position.x)*180/Math.PI};
    },
    restore(){proto.render=original;delete window.__cameraProbe;}
  };
  proto.render=function(frame,state){
    lastFrame=frame;lastState=state;
    const cue=state.balls.find(ball=>ball.id==='cue');
    if(cue&&!cue.pocket){
      const {x,y}=cue.position,r=cue.spec.radius,angle=state.shot.angle_deg*Math.PI/180;
      const center=frame.project([x,y,r]),edge=frame.project([x+r*frame.right[0],y+r*frame.right[1],r+r*frame.right[2]]);
      const ahead=frame.project([x+.48*Math.cos(angle),y+.48*Math.sin(angle),r]);
      if(center&&edge&&ahead){
        probe.sample={view:[...frame.eye,...frame.right,...frame.up,...frame.forward,frame.lens,frame.ortho],
          radius:Math.hypot(edge.x-center.x,edge.y-center.y),width:frame.width,cueX:center.x,
          point:clientPoint(ahead),position:[x,y]};
      }
    }
    return original.call(this,frame,state);
  };
  window.__cameraProbe=probe;
}
function sameView(a,b,label){
  assert.equal(a.length,b.length);
  a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<1e-6,label+' / camera component '+i+': '+v+' vs '+b[i]));
}
async function run(){
 const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'zhongba-browser-'));
 const python=process.env.PYTHON||'python',chrome=process.env.CHROME_BIN||(process.platform==='win32'?path.join(process.env.ProgramFiles,'Google','Chrome','Application','chrome.exe'):'google-chrome');
 const server=spawn(python,['-u','-m','billiards.webapp','--port','0'],{windowsHide:true});
 const software=process.argv.includes('--software'),browser=spawn(chrome,['--headless=new','--no-first-run','--disable-dev-shm-usage','--remote-debugging-port=0','--user-data-dir='+tmp,
   ...(software?['--disable-webgl']:['--use-angle=swiftshader','--enable-unsafe-swiftshader']),...(process.env.CI?['--no-sandbox']:[]),'about:blank'],{windowsHide:true,stdio:'ignore'});
 let url,socket,serial=0;const waiting=new Map(),errors=[];
 server.stdout.on('data',b=>{url||=b.toString().match(/http:\/\/127\.0\.0\.1:\d+\//)?.[0];});
 server.stderr.on('data',b=>process.stderr.write(b));
 function send(method,params={},sessionId){
   const id=++serial;return new Promise((resolve,reject)=>{waiting.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params,sessionId}));});
 }
 try{
   await deadline(()=>url,'server ready');const health=await(await fetch(url+'api/health')).json();
   assert.equal(health.status,'ok');
   const address=await deadline(async()=>{const parts=(await fs.readFile(path.join(tmp,'DevToolsActivePort'),'utf8')).trim().split(/\r?\n/);return parts[1]&&'ws://127.0.0.1:'+parts[0]+parts[1];},'Chrome ready');
   socket=new WebSocket(address);await once(socket,'open');
   socket.addEventListener('message',e=>{const m=JSON.parse(e.data);
     if(m.id){const p=waiting.get(m.id);if(!p)return;waiting.delete(m.id);if(m.error)p.reject(Error(m.error.message));else p.resolve(m.result);}
     if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
   });
   const {targetId}=await send('Target.createTarget',{url:'about:blank'}),{sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
   const call=(m,p)=>send(m,p,sessionId);
   await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
   const js=async expression=>{const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
   const visible=id=>js('!!document.getElementById('+JSON.stringify(id)+')?.getClientRects().length');
   const click=id=>js('document.getElementById('+JSON.stringify(id)+').click()');
   const text=id=>js('document.getElementById('+JSON.stringify(id)+')?.textContent');
   const wait=(expression,label)=>deadline(()=>js(expression),label);
   await call('Page.navigate',{url});await wait("document.getElementById('room-turn')?.textContent.includes('开球')",'match boot');
   assert.equal(await text('room-version'),health.app_version);assert.equal(await js("document.getElementById('room-stage').dataset.renderer"),software?'software-3d':'webgl');
   assert.equal(await js("document.querySelector('meta[name=arena-equipment]').content"),'2026.11-pocket-2');
   for(const cam of ['cue','top','orbit']){await js("document.querySelector('[data-camera="+cam+"]').click()");assert.equal(await js("document.querySelector('[data-camera="+cam+"]').getAttribute('aria-pressed')"),'true');}
   const canvas=software?'room-soft':'room-gl';
   // Check the actual composited frame, including drivers that silently produce a blank canvas.
   const clip=await js("(()=>{const r=document.getElementById('"+canvas+"').getBoundingClientRect();return {x:r.x+r.width*.1,y:r.y+r.height*.22,width:r.width*.8,height:r.height*.54,scale:.45};})()");
   const shot=await call('Page.captureScreenshot',{format:'png',clip});
   const felt=await js("(async()=>{const i=new Image();i.src='data:image/png;base64,"+shot.data+"';await i.decode();const c=document.createElement('canvas');c.width=96;c.height=64;const g=c.getContext('2d');g.drawImage(i,0,0,96,64);const a=g.getImageData(0,0,96,64).data;let n=0;for(let p=0;p<a.length;p+=4)if(a[p+1]>a[p]*1.4&&a[p+1]>a[p+2]*1.1&&a[p+1]>45)n++;return n/(96*64);})()");
   assert.ok(felt>.08,'The rendered table should have a visible playing surface: '+felt);
   const center=await js("(()=>{const r=document.getElementById('"+canvas+"').getBoundingClientRect();return {x:r.x+r.width*.63,y:r.y+r.height*.5};})()");
   await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,...center});
   await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,...center});
   assert.notEqual(await js("document.getElementById('angle').value"),'0');
   await js("(()=>{const a=document.getElementById('angle');a.value=0;a.dispatchEvent(new Event('input'));})()");
   await click('room-settings');assert.ok(await visible('race-to'));await js("document.getElementById('race-to').value='3'");await click('new-match');
   await wait("document.getElementById('room-rack').textContent.includes('抢 3')&&!document.getElementById('shoot').disabled",'race-to-three');
   await click('preview');await wait("document.getElementById('room-note').textContent.includes('预览完成')",'preview break');
   assert.equal(await text('room-score'),'0 : 0');await click('shoot');
   await wait("!document.getElementById('seek').disabled",'live playback');
   await click('play');await js("(()=>{const s=document.getElementById('seek');s.value=1000;s.dispatchEvent(new Event('input'));})()");
   await wait("!document.getElementById('last-shot').disabled",'break adjudicated');
   const turn=await text('room-turn'),score=await text('room-score');await click('last-shot');
   await wait("!document.getElementById('before').disabled",'review available');await click('before');
   assert.equal(await text('room-turn'),turn);assert.equal(await text('room-score'),score);
   await click('room-log');assert.ok(await visible('room-history'));assert.ok(await js("document.querySelectorAll('#room-history li').length>=1"));await click('room-close');
   await call('Page.reload');await wait("document.getElementById('room-rack')?.textContent.includes('抢 3')",'saved game after reload');
   await click('room-practice');await wait("document.getElementById('room-practice').getAttribute('aria-pressed')==='true'",'practice mode');
   await click('room-settings');await js("(()=>{const p=document.getElementById('preset');p.value='corner';p.dispatchEvent(new Event('change'));})()");
   await click('room-right');assert.ok(+(await js("document.getElementById('angle').value"))>45);
   await js("(()=>{const a=document.getElementById('angle');a.value=45;a.dispatchEvent(new Event('input'));})()");
   await js('('+installCameraProbe.toString()+')()');
   const view=mode=>js("document.querySelector('[data-camera="+mode+"]').click()");
   const cameraSample=()=>js('window.__cameraProbe.sample');
   await view('cue');
   const initial=await cameraSample();
   const wheelAt=await js("(()=>{const r=document.getElementById('"+canvas+"').getBoundingClientRect();return {x:r.left+r.width*.5,y:r.top+r.height*.5};})()");
   await call('Input.dispatchMouseEvent',{type:'mouseWheel',...wheelAt,deltaX:0,deltaY:-175});
   const zoomed=await deadline(async()=>{const sample=await cameraSample();return sample.radius>initial.radius*1.03&&sample;},'visible cue-view zoom');
   await view('top');await view('cue');
   const restored=await cameraSample();
   sameView(restored.view,zoomed.view,'returning from overhead preserves cue view');
   assert.ok(Math.abs(restored.cueX-restored.width/2)<.75,'cue ball lies on the sight line');
   // Click a known point on the current sight line through the canvas at CSS-pixel precision.
   const clickPoint=async point=>{
     await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,...point});
     await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,...point});
   };
   await clickPoint(restored.point);
   assert.ok(Math.abs(+(await js("document.getElementById('angle').value"))-45)<.25,'centerline click preserves the aim');
   // At 17 degrees off-axis, confusing the slate and ball-center heights caused ~1 degree of aim error.
   for(const kind of ['pocket','ball']){
     await js("(()=>{const a=document.getElementById('angle');a.value=62;a.dispatchEvent(new Event('input'));})()");
     const target=await js('window.__cameraProbe.aimTarget('+JSON.stringify(kind)+')');
     await clickPoint(target.point);
     const angle=Number(await js("document.getElementById('angle').value"));
     assert.ok(Math.abs(angle-target.angle)<.25,kind+' center should select its world bearing: '+angle+' vs '+target.angle);
   }
   await js("(()=>{const a=document.getElementById('angle');a.value=45;a.dispatchEvent(new Event('input'));})()");
   const addressView=await cameraSample();
   await click('preview');await wait("document.getElementById('room-note').textContent.includes('预览已完成')",'practice route');
   sameView((await cameraSample()).view,addressView.view,'preview preserves address');
   await click('shoot');await wait("!document.getElementById('seek').disabled",'practice playback');
   const rolling=await deadline(async()=>{
     const sample=await cameraSample();
     return Math.hypot(sample.position[0]-addressView.position[0],sample.position[1]-addressView.position[1])>.015&&sample;
   },'cue ball actually rolls in the original view',75000);
   sameView(rolling.view,addressView.view,'shot and moving ball share the address camera');
   await js("(()=>{const s=document.getElementById('seek');s.value=1000;s.dispatchEvent(new Event('input'));})()");
   assert.ok(await js("document.getElementById('potted').textContent.includes('1')"));await click('next');
   await js('window.__cameraProbe.restore()');await click('room-reset');
   // Place a ball frozen behind the cue ball and exercise both the button and the shared keyboard action.
   await js("(()=>{const s=structuredClone(config.presets.find(p=>p.id==='corner').scene);s.shot.angle_deg=0;s.shot.tip_x=0;s.shot.tip_y=0;const cue=s.balls.find(b=>b.id==='cue'),b=s.balls.find(b=>b.id!=='cue');cue.position={x:1.30,y:.60};b.position={x:1.30-2*cue.spec.radius-.0001,y:.60};setScene(s);})()");
   assert.ok(await js("document.getElementById('shoot').disabled&&document.getElementById('preview').disabled&&document.getElementById('room-turn').textContent.includes('出杆受阻')"));
   await js("calculate(true)");assert.ok(await js("!fired&&!record&&document.getElementById('room-note').textContent.includes('出杆受阻')"));
   await js("(()=>{const a=document.getElementById('angle');a.value=90;a.dispatchEvent(new Event('input'));})()");
   assert.ok(await js("!document.getElementById('shoot').disabled&&document.getElementById('room-stage').dataset.cueClearance==='clear'"));
   await click('room-match');await wait("document.getElementById('room-rack').textContent.includes('抢 3')",'match resumes from practice');
   let aiResult=null;
   if(!software){
     const request=async(path,body)=>{
       const response=await fetch(url+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
       const data=await response.json();assert.equal(response.status,200,JSON.stringify(data));return data;
     };
     const config=await request('api/rules/config'),scene=config.presets.find(p=>p.id==='corner').scene;
     for(const b of scene.balls){
       if(b.id==='cue')b.position={x:1.19,y:.44};
       else{b.id='8';b.position={x:1.27,y:.22};}
     }
     const setup=await request('api/game/new',{scenario:'ai_custom',ai_player:0,ai_group:'solid',race_to:1,scene});
     await request('api/game/action',{id:setup.id,revision:setup.revision,action:'finish_setup',ai_group:'solid',ai_player:0,scene});
     await js("localStorage.setItem('zhongba.rule-match.v1',"+JSON.stringify(setup.id)+")");
     await call('Page.reload');await wait("document.getElementById('room-turn')?.textContent.includes('电脑')&&!document.getElementById('ai-think').disabled",'AI owns the final eight');
     await js("document.querySelector('#room-ai summary').click()");await click('ai-think');
     await deadline(()=>js("!document.getElementById('ai-execute').disabled"),'validated AI shot',150000);
     await click('ai-execute');
     await wait("document.getElementById('room-turn')?.textContent.includes('赢得本场')",'AI wins the game');
     const finished=await request('api/game/get',{id:setup.id});
     assert.equal(finished.match_winner,0);assert.ok(finished.last_decision.potted.includes('8'));aiResult=finished.last_decision.outcome;
   }
   await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
   await wait("window.innerWidth===390",'mobile viewport');assert.ok(await js("document.documentElement.scrollWidth<=innerWidth+1"));
   await click('room-help');assert.ok(await visible('dialog-help'));await click('room-close');
   await call('Page.navigate',{url:url+'play'});await wait("document.getElementById('build')?.textContent.includes('"+health.app_version+"')",'workbench');
   assert.ok(await visible('table'));assert.equal(await visible('room-stage'),false);assert.deepEqual(errors,[]);
   console.log(JSON.stringify({renderer:software?'software-3d':'webgl',version:health.app_version,breakResult:turn,score,aiResult,felt,mobileWidth:390,scriptErrors:errors}));
 }finally{
   if(socket?.readyState===1)socket.close();
   browser.kill();server.kill();try{await fs.rm(tmp,{force:true,recursive:true,maxRetries:4,retryDelay:250});}catch{}
 }
}
run().catch(e=>{console.error(e);process.exitCode=1;});
