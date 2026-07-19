const mm = require('../desktop/electron/aether_ollama_middleman');
let page = { url: 'about:blank', text: '' };
const callTool = async (tool, args) => {
  if (tool === 'navigate') { page = { url: args.url, text: `On ${args.url}: The capital of France is Paris.` }; return { ok: true, url: page.url }; }
  if (tool === 'read_page' || tool === 'get_text') return { ok: true, url: page.url, text: page.text };
  if (tool === 'find') return { ok: true, matches: [] };
  return { ok: true, tool };
};
(async () => {
  const out = await mm.runTask({
    task: "Navigate to https://example.com then read the page and answer: what is the capital of France?",
    model: process.argv[2] || 'scbe-coder:latest', callTool, maxSteps: 8, log: (m) => console.log('  ' + m),
  });
  console.log('RESULT:', JSON.stringify({ done: out.done, answer: (out.answer||'').slice(0,120), steps: out.steps }));
})();
