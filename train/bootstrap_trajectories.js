const mm = require('../desktop/electron/aether_ollama_middleman');
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'bootstrap_trajectories.jsonl');
const WEB = {
  'https://example.com': 'Welcome. The capital of France is Paris.',
  'https://shop.example/item': 'Product: Widget. The price is $42. A Buy button is available.',
  'https://docs.example/api': 'API reference. The main function is called processData(). See examples below.',
  'https://wiki.example/water': 'Water is H2O. Water boils at 100 degrees Celsius at sea level.',
  'https://news.example': 'Breaking news. Headline: Rockets win 5 to 2 tonight.',
};
const TASKS = [
  'Go to https://example.com and tell me the capital of France.',
  'Go to https://shop.example/item and tell me the price.',
  'Go to https://docs.example/api and tell me the main function name.',
  'Go to https://wiki.example/water and tell me at what temperature water boils.',
  'Go to https://news.example and tell me the headline.',
];
function makeMock(){ let page={url:'about:blank',text:''};
  return async (tool,args)=>{
    if(tool==='navigate'){page={url:args.url,text:WEB[args.url]||'Page not found.'};return{ok:true,url:page.url};}
    if(tool==='read_page'||tool==='get_text')return{ok:true,url:page.url,text:page.text};
    if(tool==='find'){const q=(args.text||'').toLowerCase();return{ok:true,matches:page.text.toLowerCase().includes(q)?[{text:args.text,x:100,y:200}]:[]};}
    return{ok:true,tool};};}
(async()=>{
  const model = process.argv[2] || 'qwen2.5-coder:3b'; let ok=0; const lines=[];
  for(const task of TASKS){
    const out = await mm.runTask({task,model,callTool:makeMock(),maxSteps:8,log:()=>{}});
    lines.push(JSON.stringify({task,model,...out})); if(out.done)ok++;
    console.log(`${out.done?'PASS':'fail'} [${out.steps}] ${task.slice(0,46)} -> ${(out.answer||'').slice(0,38)}`);
  }
  fs.writeFileSync(OUT,lines.join('\n')+'\n');
  console.log(`\n${ok}/${TASKS.length} completed; wrote ${OUT}`);
})();
