/**
 * aether_tools.js — the full Claude-in-Chrome tool surface for AetherBrowser's agents, GATED.
 *
 * Every tool operates on the active window's browserView.webContents and passes through action_gate first
 * (classify -> audit -> enforce), so a hijacked/injected agent can still only do what the governor allows.
 * This is additive: it registers ONE ipc handler ('aether-tool') that dispatches every tool, plus an attach()
 * to wire per-view console/network buffers. Nothing existing is changed.
 *
 * Tools (Claude-in-Chrome parity): navigate, read_page, get_text, screenshot, click, type, key, scroll, find,
 * form_input, console, network, eval_js, tabs_list, tabs_create, tabs_close, tabs_activate, back, forward, reload.
 */
'use strict';

const READ_PAGE_JS = `(function(){
  const SKIP=new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','IFRAME']);const MAX=100000;let text='';
  const w=document.createTreeWalker(document.body||document.documentElement,NodeFilter.SHOW_TEXT,{acceptNode(n){
    const p=n.parentElement;if(!p||SKIP.has(p.tagName))return NodeFilter.FILTER_REJECT;
    if(p.hidden||p.getAttribute('aria-hidden')==='true')return NodeFilter.FILTER_REJECT;
    const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return NodeFilter.FILTER_REJECT;
    return NodeFilter.FILTER_ACCEPT;}});
  while(w.nextNode()){const v=w.currentNode.nodeValue.trim();if(v){text+=v+' ';if(text.length>MAX)break;}}
  const links=[...document.querySelectorAll('a[href]')].slice(0,60).map(el=>({text:(el.textContent||'').trim(),href:el.href}));
  const buttons=[...document.querySelectorAll('button,input[type=submit],input[type=button],[role=button]')].slice(0,40)
    .map(el=>({text:(el.textContent||el.value||'').trim()}));
  const inputs=[...document.querySelectorAll('input,textarea,select')].slice(0,40)
    .map(el=>({name:el.name||el.id||'',type:el.type||el.tagName.toLowerCase(),placeholder:el.placeholder||''}));
  return {url:location.href,title:document.title,text:text.slice(0,MAX).trim(),links,buttons,inputs,
    selection:(getSelection()?.toString()||'').trim()};})()`;

const clickSelectorJS = (sel) => `(function(){const el=document.querySelector(${JSON.stringify(sel)});
  if(!el)return{ok:false,error:'no element'};const r=el.getBoundingClientRect();
  el.scrollIntoView({block:'center'});el.click();return{ok:true,clicked:${JSON.stringify(sel)},x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`;

const findJS = (text) => `(function(){const q=${JSON.stringify(String(text||'').toLowerCase())};
  const hits=[...document.querySelectorAll('a,button,input,[role=button],h1,h2,h3,label,li,span')]
   .filter(el=>((el.textContent||el.value||el.placeholder||'').toLowerCase().includes(q)))
   .slice(0,15).map(el=>{const r=el.getBoundingClientRect();return{tag:el.tagName.toLowerCase(),
     text:(el.textContent||el.value||el.placeholder||'').trim().slice(0,80),x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};});
  return{ok:true,matches:hits};})()`;

const formInputJS = (sel, value) => `(function(){const el=document.querySelector(${JSON.stringify(sel)});
  if(!el)return{ok:false,error:'no field'};el.focus();el.value=${JSON.stringify(String(value))};
  el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
  return{ok:true,field:${JSON.stringify(sel)}};})()`;

function register({ ipcMain, ctxFromEvent, actionGate }) {
  const consoleBuf = new Map();   // webContents.id -> [{level,message,...}]
  const netBuf = new Map();       // webContents.id -> [{url,method,...}]

  // call attach(browserView.webContents) once per view (from createBrowserWindow)
  function attach(wc) {
    const id = wc.id;
    consoleBuf.set(id, []); netBuf.set(id, []);
    wc.on('console-message', (_e, level, message, line, sourceId) => {
      const b = consoleBuf.get(id); if (!b) return;
      b.push({ level, message, line, sourceId, t: Date.now() }); if (b.length > 500) b.shift();
    });
    try {
      if (!wc.debugger.isAttached()) wc.debugger.attach('1.3');
      wc.debugger.on('message', (_e, method, params) => {
        if (method === 'Network.requestWillBeSent') {
          const b = netBuf.get(id); if (!b) return;
          b.push({ url: params.request.url, method: params.request.method, type: params.type, t: Date.now() });
          if (b.length > 500) b.shift();
        }
      });
      wc.debugger.sendCommand('Network.enable').catch(() => {});
    } catch (_) { /* debugger may be unavailable; console + JS tools still work */ }
    wc.on('destroyed', () => { consoleBuf.delete(id); netBuf.delete(id); });
  }

  // callable directly (by the in-process agent) AND via IPC — same gated logic either way
  async function invoke(c, tool, args) {
    if (!c || !c.browserView) return { ok: false, error: 'no active browser view' };
    const wc = c.browserView.webContents;
    tool = String(tool || '');
    args = args || {};

    // --- GATE every tool call (same governor as controllerEvent) ---
    const verdict = actionGate.gate(tool, args);
    actionGate.log(verdict, { event: tool, ...args });
    if (verdict.decision === 'BLOCK') return { ok: false, blocked: true, tool, reason: verdict.reason };
    if (verdict.decision === 'CONFIRM' && !args.confirmed) return { ok: false, needsConfirm: true, tool, reason: verdict.reason };

    try {
      switch (tool) {
        case 'navigate': await wc.loadURL(String(args.url)); return { ok: true, url: args.url };
        case 'read_page': return await wc.executeJavaScript(READ_PAGE_JS);
        case 'get_text': return { ok: true, text: await wc.executeJavaScript('(document.body||document.documentElement).innerText.slice(0,100000)') };
        case 'screenshot': { const img = await wc.capturePage(); return { ok: true, mime: 'image/png', base64: img.toPNG().toString('base64') }; }
        case 'click':
          if (args.selector) return await wc.executeJavaScript(clickSelectorJS(args.selector));
          wc.sendInputEvent({ type: 'mouseDown', x: args.x | 0, y: args.y | 0, button: 'left', clickCount: 1 });
          wc.sendInputEvent({ type: 'mouseUp', x: args.x | 0, y: args.y | 0, button: 'left', clickCount: 1 });
          return { ok: true, x: args.x | 0, y: args.y | 0 };
        case 'type': for (const ch of String(args.text || '')) wc.sendInputEvent({ type: 'char', keyCode: ch }); return { ok: true, typed: (args.text || '').length };
        case 'key': wc.sendInputEvent({ type: 'keyDown', keyCode: String(args.key) }); wc.sendInputEvent({ type: 'keyUp', keyCode: String(args.key) }); return { ok: true, key: args.key };
        case 'scroll': await wc.executeJavaScript(`window.scrollBy({top:${Number(args.dy || 400)},left:${Number(args.dx || 0)},behavior:'smooth'})`); return { ok: true };
        case 'find': return await wc.executeJavaScript(findJS(args.text));
        case 'form_input': return await wc.executeJavaScript(formInputJS(args.selector, args.value));
        case 'console': return { ok: true, messages: (consoleBuf.get(wc.id) || []).slice(-Number(args.limit || 50)) };
        case 'network': return { ok: true, requests: (netBuf.get(wc.id) || []).slice(-Number(args.limit || 50)) };
        case 'eval_js': return { ok: true, result: await wc.executeJavaScript(String(args.code)) };   // gated as EVAL (see action_gate)
        case 'back': if (wc.canGoBack()) wc.goBack(); return { ok: true };
        case 'forward': if (wc.canGoForward()) wc.goForward(); return { ok: true };
        case 'reload': wc.reload(); return { ok: true };
        case 'tabs_list': return { ok: true, tabs: (c.tabs || []).map((t, i) => ({ id: i, title: t.title || '', url: t.url || '', active: i === c.activeTabIndex })) };
        default: return { ok: false, error: 'unknown tool: ' + tool };
      }
    } catch (err) {
      return { ok: false, tool, error: String(err && err.message || err) };
    }
  }

  ipcMain.handle('aether-tool', async (event, msg) => invoke(ctxFromEvent(event), msg && msg.tool, (msg && msg.args) || {}));

  return { attach, invoke, TOOLS: ['navigate','read_page','get_text','screenshot','click','type','key','scroll','find','form_input','console','network','eval_js','back','forward','reload','tabs_list'] };
}

module.exports = { register };
