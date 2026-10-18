const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..');const html=fs.readFileSync(path.join(root,'docs/index.html'),'utf8');
const evidence=html.match(/<script id="evidence" type="application\/json">([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(evidence),final=JSON.parse(fs.readFileSync(path.join(root,'reports/final.json'),'utf8'));
assert.deepStrictEqual(data.forecast,final.metrics);
function element(){return {value:'',textContent:'',children:[],innerHTML:'',events:{},appendChild(e){this.children.push(e)},addEventListener(k,f){this.events[k]=f}}}
const els={};for(const id of ['evidence','model','budget','penalty','fill','spend','stock','first','orders','forecast'])els[id]=element();
els.evidence.textContent=evidence;els.budget.value='primary';
const ctx={document:{getElementById:id=>els[id],createElement:()=>element()}};
vm.createContext(ctx);const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];vm.runInContext(script,ctx);
let checks=1;
for(const model of Object.keys(data.models))for(const budget of ['budget_half','primary','budget_double']){
 els.model.value=model;els.budget.value=budget;vm.runInContext('render()',ctx);
 const ref=data.scenarios[budget][model];assert.strictEqual(els.fill.textContent,(100*ref.unit_fill_rate).toFixed(2)+'%');
 assert.strictEqual(els.penalty.textContent,ref.total_penalty.toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2}));
 assert(els.first.textContent.includes(String(ref.rows[0].ordered_units)+' units ordered'));checks++;
}
assert.strictEqual(typeof els.model.events.change,'function');assert.strictEqual(typeof els.budget.events.change,'function');checks++;
let changed=false;for(const k of Object.keys(data.models))if(data.scenarios.budget_half[k].rows[0].ordered_units!==data.scenarios.budget_double[k].rows[0].ordered_units)changed=true;
assert(changed);checks++;
const report={checks_passed:checks,scope:'Actual inline script in Node VM and a minimal DOM; not rendered browser/mobile/accessibility verification',all_nine_model_budget_combinations:true,source_evidence_equal:true,tighter_budget_changes_saved_orders:true};
fs.writeFileSync(path.join(root,'reports/demo_verification.json'),JSON.stringify(report,null,2)+'\n');console.log(report);
