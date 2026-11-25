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
   for(const cam of ['cue','top','orbit']){await js("document.querySelector('[data-camera="+cam+"]').click()");assert.equal(await js("document.querySelector('[data-camera="+cam+"]').getAttribute('aria-pressed')"),'true');}
   const canvas=software?'room-soft':'room-gl';
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
   await click('preview');await wait("document.getElementById('room-note').textContent.includes('预览已完成')",'practice route');
   await click('shoot');await wait("!document.getElementById('seek').disabled",'practice playback');
   await js("(()=>{const s=document.getElementById('seek');s.value=1000;s.dispatchEvent(new Event('input'));})()");
   assert.ok(await js("document.getElementById('potted').textContent.includes('1')"));await click('next');
   await click('room-match');await wait("document.getElementById('room-rack').textContent.includes('抢 3')",'match resumes from practice');
   await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
   await wait("window.innerWidth===390",'mobile viewport');assert.ok(await js("document.documentElement.scrollWidth<=innerWidth+1"));
   await click('room-help');assert.ok(await visible('dialog-help'));await click('room-close');
   await call('Page.navigate',{url:url+'play'});await wait("document.getElementById('build')?.textContent.includes('"+health.app_version+"')",'workbench');
   assert.ok(await visible('table'));assert.equal(await visible('room-stage'),false);assert.deepEqual(errors,[]);
   console.log(JSON.stringify({renderer:software?'software-3d':'webgl',version:health.app_version,breakResult:turn,score,mobileWidth:390,scriptErrors:errors}));
 }finally{
   if(socket?.readyState===1)socket.close();
   browser.kill();server.kill();try{await fs.rm(tmp,{force:true,recursive:true,maxRetries:4,retryDelay:250});}catch{}
 }
}
run().catch(e=>{console.error(e);process.exitCode=1;});
