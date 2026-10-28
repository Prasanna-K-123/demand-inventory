// Executed DOM calculation checks, not visual browser or accessibility certification.
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'explorer/index.html'),'utf8');
const data=JSON.parse(html.match(/<script id="evidence-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const source=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const nodes=new Map();
for(const [,id] of html.matchAll(/\bid="([^"]+)"/g)) {
  nodes.set(id,{value:'',textContent:'',innerHTML:'',listeners:{},addEventListener(event,fn){this.listeners[event]=fn;}});
}
nodes.get('evidence-data').textContent=JSON.stringify(data);
nodes.get('split').value='final';nodes.get('identity').value='fitting_identities';nodes.get('cost').value='3';
vm.runInNewContext(source,{document:{getElementById:id=>{
  assert(nodes.has(id),'missing DOM node '+id);return nodes.get(id);
}}});
let checks=0;
function check(fn){fn();checks++;}
check(()=>assert.equal(Number(nodes.get('headline-tests').textContent),data.summary.systems.automated_tests));
check(()=>assert.equal(nodes.get('headline-p95').textContent,data.benchmark.job_end_to_end.p95_ms.toFixed(0)+' ms'));
check(()=>assert(nodes.get('provenance').textContent.includes(data.summary.model_version)));
check(()=>assert(data.benchmark.peak_server_process_tree_rss_mb===null
  ?nodes.get('benchmark-table').innerHTML.includes('Unmeasured')
  :nodes.get('benchmark-table').innerHTML.includes(data.benchmark.peak_server_process_tree_rss_mb.toFixed(1))));
for(const split of ['final','official_external'])for(const identity of ['fitting_identities','transfer_holdout']) {
  nodes.get('split').value=split;nodes.get('identity').value=identity;
  nodes.get('split').listeners.change();
  const rows=data.metrics.filter(r=>r.split===split&&r.identity_split===identity);
  check(()=>assert.equal((nodes.get('bars').innerHTML.match(/class="barrow"/g)||[]).length,5));
  for(const row of rows)check(()=>assert(nodes.get('bars').innerHTML.includes(row.mae.toFixed(4))));
  const interval=data.intervals.find(r=>r.split===split&&r.identity_split===identity);
  check(()=>assert(nodes.get('coverage-summary').textContent.includes((interval.coverage80*100).toFixed(1)+'%')));
  check(()=>assert(!/NaN|undefined|Infinity/.test(nodes.get('weekly-chart').innerHTML)));
}
for(const cost of [1,3,5]) {
  nodes.get('cost').value=String(cost);nodes.get('cost').listeners.change();
  const rows=data.decisions.filter(r=>r.shortage_weight===cost);
  const chosen=rows.find(r=>r.policy==='scenario_dp'),simple=rows.find(r=>r.policy==='proportional_point');
  check(()=>assert(nodes.get('cost-table').innerHTML.includes(chosen.mean_proxy_cost.toFixed(4))));
  check(()=>assert(nodes.get('decision-summary').textContent.includes(chosen.mean_proxy_cost<simple.mean_proxy_cost?'lower':'higher')));
}
console.log(JSON.stringify({checks,status:'passed',executed_utc:new Date().toISOString(),html_sha256:require('node:crypto').createHash('sha256').update(html).digest('hex'),scope:'DOM calculations for all forecast groups and cost controls; null telemetry handling; no visual browser claim'}));
