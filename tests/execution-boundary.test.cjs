/* eslint-disable @typescript-eslint/no-require-imports -- Node CommonJS test harness. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
function moduleUnderTest(file, fetch) {
  const exports = {};
  const context = {exports, module: {exports}, fetch, window: {}, localStorage: {getItem:()=>null,setItem:()=>{}}, console:{warn(){}}, AbortSignal, AbortController, URLSearchParams, setTimeout, clearTimeout, process:{env:{}}, require:(name)=>moduleUnderTest('src/'+name.slice(2)+'.ts',fetch)};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root,file),'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
  return exports;
}
const input={instrument:'NIFTY 50',contractSymbol:'TEST',bias:'CE',strike:24000,expiry:'TEST',entryPremium:105,lots:1,lotSize:25,stopLoss:90,target1:135,target2:165};
for(const status of [200,401,403,409,422,500]) test(`rejected open HTTP ${status} never mutates state`,async()=>{
 const m=moduleUnderTest('src/services/paperTradingService.ts',async()=>({ok:status===200,status,json:async()=>({success:false,message:'risk rejected'})})).paperTradingManager;
 const before=JSON.stringify(m.getState());assert.equal((await m.openPositionBackend(input)).success,false);assert.equal(JSON.stringify(m.getState()),before);
});
test('unknown network outcome never creates a local fill',async()=>{const m=moduleUnderTest('src/services/paperTradingService.ts',async()=>{throw Error('offline')}).paperTradingManager;assert.equal((await m.openPositionBackend(input)).success,false);assert.equal(m.getState().positions.length,0)});
test('rejected exit and reset retain existing position and cash',async()=>{const m=moduleUnderTest('src/services/paperTradingService.ts',async()=>({ok:false,json:async()=>({success:false})})).paperTradingManager;m.openPosition({...input,index:'NIFTY 50',currentPremium:105},1);const before=JSON.stringify(m.getState());await m.closePositionBackend(m.getState().positions[0].id,150);await m.resetAccount();assert.equal(JSON.stringify(m.getState()),before)});
test('empty successful signals remain empty',async()=>{const api=moduleUnderTest('src/lib/api.ts',async()=>({ok:true,json:async()=>({success:true,data:[]})})).apiClient;assert.equal((await api.getTopCallCandidates()).length,0);assert.equal((await api.getTopPutCandidates()).length,0)});
test('offline data never becomes mock opportunities or live observer',async()=>{const api=moduleUnderTest('src/lib/api.ts',async()=>{throw Error('offline')}).apiClient;assert.equal((await api.getTopCallCandidates()).length,0);assert.equal(await api.getStockAnalysis('RELIANCE'),null);await assert.rejects(()=>api.getObserverIntelligence(),/unavailable/)});
