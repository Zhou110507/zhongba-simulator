const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {instantGuide,contactGuide}=require('../web/shot-guide.js');
const payload=JSON.parse(fs.readFileSync(path.join(__dirname,'../artifacts/aim-v5/parity.json'),'utf8'));
let worst=0;
for(const item of payload.cases){
 const fast=instantGuide(item.scene,payload.config.model,payload.config.geometry);
 const actual=contactGuide(item.result,payload.config.geometry);
 assert.equal(fast.kind,actual.kind,item.name);
 const error=Math.hypot(fast.center.x-actual.center.x,fast.center.y-actual.center.y);
 assert.ok(error<1e-7,`${item.name}: position error ${error}`);
 worst=Math.max(worst,error);
}
console.log(`${payload.cases.length} synchronous aim cases match the engine; max centre error ${worst.toExponential(3)} m`);
