'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/index.html','utf8');
const script=html.match(/<script data-local-launch>([\s\S]*?)<\/script>/)[1];

test('opening the HTML file explains the launcher instead of leaving a dead connection screen',()=>{
  let loaded;const document={documentElement:{style:{}},body:{innerHTML:'正在连接本地物理服务…'},
    addEventListener(name,fn){assert.equal(name,'DOMContentLoaded');loaded=fn;}};
  vm.runInNewContext(script,{location:{protocol:'file:'},document});loaded();
  assert.match(document.body.innerHTML,/启动练习台.cmd/);
  assert.match(document.body.innerHTML,/不能从这里直接运行/);
  assert.doesNotMatch(document.body.innerHTML,/正在连接本地物理服务/);
});

test('normal server pages keep their existing layout and startup untouched',()=>{
  const document={documentElement:{style:{}},body:{innerHTML:'normal-page'},
    addEventListener(){assert.fail('No local-file screen on HTTP');}};
  vm.runInNewContext(script,{location:{protocol:'http:'},document});
  assert.equal(document.body.innerHTML,'normal-page');assert.deepEqual(document.documentElement.style,{});
});
