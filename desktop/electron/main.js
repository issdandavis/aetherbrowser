/**
 * @file main.js
 * @module desktop/electron/main
 *
 * AetherBrowser Electron main process — MULTI-WINDOW ("agent spots").
 * Each window has its own browser pane (75%) + AI sidebar (25%). ALL sidebars
 * connect to the single shared Python backend (src.aetherbrowser.serve, port 8002),
 * so every window/agent spot shares ONE context pool. Ctrl+N opens another spot.
 */

const {
  app,
  BrowserWindow,
  WebContentsView,
  ipcMain,
  Menu,
} = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const actionGate = require('./action_gate');   // SCBE action-governor for sidepanel-agent actions
const aetherToolsMod = require('./aether_tools'); // full Claude-in-Chrome tool surface for agents (gated)
const aetherTerminal = require('./aether_terminal_tools'); // tmux + vim programmatic tools (gated)
const aetherRecorder = require('./aether_train_recorder'); // consent-gated trajectory recorder (training faucet)
const aetherMiddleman = require('./aether_ollama_middleman'); // local-model agent loop (points OUR model at the browser)
let aetherTools = null;

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------
const ROOT = path.resolve(__dirname, '..', '..');
const EXTENSION_DIR = path.join(ROOT, 'src', 'extension');
const RENDERER_DIR = path.join(__dirname, '..', 'renderer');
const PRELOAD_SIDEPANEL = path.join(__dirname, 'preload-sidepanel.js');
const PRELOAD_BROWSER = path.join(__dirname, 'preload-browser.js');
const PRELOAD_ADDRESSBAR = path.join(__dirname, 'preload-addressbar.js');

// ---------------------------------------------------------------------------
// Backend process management (single, shared across all windows)
// ---------------------------------------------------------------------------
let backendProcess = null;
const BACKEND_PORT = 8002;

// Studio home: AetherBrowser lands on I Tube (local AI-first YouTube studio) instead of Google.
// Override with the AETHER_HOME_URL env var. Requires the I Tube dev server running on :9002.
const HOME_URL = process.env.AETHER_HOME_URL || 'http://localhost:9002/';

function spawnBackend() {
  if (backendProcess) return;

  backendProcess = spawn(
    'python',
    ['-m', 'uvicorn', 'src.aetherbrowser.serve:app', '--port', String(BACKEND_PORT), '--host', '127.0.0.1'],
    {
      cwd: ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
      shell: true,
    }
  );

  backendProcess.stdout.on('data', (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });
  backendProcess.stderr.on('data', (data) => {
    console.error(`[backend] ${data.toString().trim()}`);
  });
  backendProcess.on('close', (code) => {
    console.log(`[backend] exited with code ${code}`);
    backendProcess = null;
  });
  backendProcess.on('error', (err) => {
    console.error(`[backend] failed to start: ${err.message}`);
    backendProcess = null;
  });
}

function killBackend() {
  if (!backendProcess) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(backendProcess.pid), '/T', '/F'], { shell: true });
    } else {
      backendProcess.kill('SIGTERM');
    }
  } catch {
    // best effort
  }
  backendProcess = null;
}

// ---------------------------------------------------------------------------
// Multi-window registry. Each window gets its own context (views + tab state).
// IPC events are resolved back to their window via the sender's webContents id.
// ---------------------------------------------------------------------------
const windows = [];               // array of window contexts
const viewToCtx = new Map();      // webContents.id -> ctx

const SIDEPANEL_RATIO = 0.25;
const ADDRESS_BAR_HEIGHT = 52;

function ctxFromEvent(event) {
  return viewToCtx.get(event.sender.id) || windows[0] || null;
}

function focusedCtx() {
  const fw = BrowserWindow.getFocusedWindow();
  if (fw) {
    const c = windows.find((w) => w.win === fw);
    if (c) return c;
  }
  return windows[0] || null;
}

function currentTab(ctx) {
  return ctx.tabs[ctx.activeTabIndex] || null;
}

function syncTabState(ctx) {
  const wc = ctx.browserView.webContents;
  const tab = currentTab(ctx);
  if (tab) {
    tab.url = wc.getURL();
    tab.title = wc.getTitle();
  }
}

function layoutViews(ctx) {
  if (!ctx || !ctx.win) return;
  const [width, height] = ctx.win.getContentSize();
  const spWidth = Math.round(width * SIDEPANEL_RATIO);
  const bpWidth = width - spWidth;
  const bodyHeight = height - ADDRESS_BAR_HEIGHT;

  ctx.addressBarView.setBounds({ x: 0, y: 0, width, height: ADDRESS_BAR_HEIGHT });
  ctx.browserView.setBounds({ x: 0, y: ADDRESS_BAR_HEIGHT, width: bpWidth, height: bodyHeight });
  ctx.sidepanelView.setBounds({ x: bpWidth, y: ADDRESS_BAR_HEIGHT, width: spWidth, height: bodyHeight });
}

function notifyAddressBar(ctx) {
  if (!ctx || !ctx.addressBarView) return;
  const wc = ctx.browserView.webContents;
  ctx.addressBarView.webContents.send('navigation-update', {
    url: wc.getURL(),
    title: wc.getTitle(),
    canGoBack: wc.canGoBack(),
    canGoForward: wc.canGoForward(),
  });
}

function createBrowserWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: `AetherBrowser — agent spot ${windows.length + 1}`,
    backgroundColor: '#0d1117',
    show: false,
  });

  const ctx = { win, addressBarView: null, browserView: null, sidepanelView: null, tabs: [], activeTabIndex: 0 };

  // --- Address bar (top chrome) ---
  ctx.addressBarView = new WebContentsView({
    webPreferences: { preload: PRELOAD_ADDRESSBAR, contextIsolation: true, nodeIntegration: false },
  });
  win.contentView.addChildView(ctx.addressBarView);
  ctx.addressBarView.webContents.loadFile(path.join(RENDERER_DIR, 'address-bar.html'));

  // --- Browser pane ---
  ctx.browserView = new WebContentsView({
    webPreferences: { preload: PRELOAD_BROWSER, contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.contentView.addChildView(ctx.browserView);
  ctx.browserView.webContents.loadURL(HOME_URL);
  if (aetherTools) aetherTools.attach(ctx.browserView.webContents);  // wire console/network buffers for the tools
  ctx.tabs.push({ url: HOME_URL, title: 'I Tube' });

  const onNav = () => { syncTabState(ctx); notifyAddressBar(ctx); };
  ctx.browserView.webContents.on('did-navigate', onNav);
  ctx.browserView.webContents.on('did-navigate-in-page', onNav);
  ctx.browserView.webContents.on('page-title-updated', onNav);

  // --- Sidepanel (reuses extension UI; connects to the shared backend pool) ---
  ctx.sidepanelView = new WebContentsView({
    webPreferences: { preload: PRELOAD_SIDEPANEL, contextIsolation: true, nodeIntegration: false },
  });
  win.contentView.addChildView(ctx.sidepanelView);
  ctx.sidepanelView.webContents.loadFile(path.join(EXTENSION_DIR, 'sidepanel.html'));

  // Register this window's views so IPC can resolve them back to this ctx.
  for (const v of [ctx.addressBarView, ctx.browserView, ctx.sidepanelView]) {
    viewToCtx.set(v.webContents.id, ctx);
  }

  layoutViews(ctx);
  win.on('resize', () => layoutViews(ctx));
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => {
    for (const v of [ctx.addressBarView, ctx.browserView, ctx.sidepanelView]) {
      try { if (v) viewToCtx.delete(v.webContents.id); } catch { /* gone */ }
    }
    const i = windows.indexOf(ctx);
    if (i >= 0) windows.splice(i, 1);
  });

  windows.push(ctx);
  return ctx;
}

// ---------------------------------------------------------------------------
// IPC handlers — every handler resolves the SENDER'S window context.
// ---------------------------------------------------------------------------

ipcMain.on('navigate', (event, url) => {
  const c = ctxFromEvent(event);
  if (c && c.browserView) c.browserView.webContents.loadURL(url);
});

ipcMain.on('go-back', (event) => {
  const c = ctxFromEvent(event);
  if (c && c.browserView && c.browserView.webContents.canGoBack()) c.browserView.webContents.goBack();
});

ipcMain.on('go-forward', (event) => {
  const c = ctxFromEvent(event);
  if (c && c.browserView && c.browserView.webContents.canGoForward()) c.browserView.webContents.goForward();
});

ipcMain.on('reload', (event) => {
  const c = ctxFromEvent(event);
  if (c && c.browserView) c.browserView.webContents.reload();
});

// Open another agent spot (new window) — shares the same backend context pool.
ipcMain.on('new-agent-window', () => {
  createBrowserWindow();
});

ipcMain.handle('chrome-tabs-query', async (event) => {
  const c = ctxFromEvent(event);
  if (!c) return [];
  return c.tabs.map((tab, i) => ({
    id: i,
    title: tab.title || '',
    url: tab.url || '',
    active: i === c.activeTabIndex,
    pinned: false,
    audible: false,
  }));
});

ipcMain.handle('chrome-tabs-sendMessage', async (event, tabId, message) => {
  const c = ctxFromEvent(event);
  if (!c || !c.browserView) return null;
  if (message.action === 'getPageContent') {
    try {
      const result = await c.browserView.webContents.executeJavaScript(`
        (function() {
          const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'IFRAME']);
          const MAX_LENGTH = 100000;
          let text = '';
          const walker = document.createTreeWalker(
            document.body || document.documentElement,
            NodeFilter.SHOW_TEXT,
            {
              acceptNode(node) {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                if (SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
                if (parent.hidden || parent.getAttribute('aria-hidden') === 'true')
                  return NodeFilter.FILTER_REJECT;
                const style = getComputedStyle(parent);
                if (style.display === 'none' || style.visibility === 'hidden')
                  return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
              },
            }
          );
          while (walker.nextNode()) {
            const value = walker.currentNode.nodeValue.trim();
            if (value) { text += value + ' '; if (text.length > MAX_LENGTH) break; }
          }

          const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
            .slice(0, 20)
            .map(el => ({ level: el.tagName, text: el.textContent?.trim() || '' }))
            .filter(r => r.text);

          const links = Array.from(document.querySelectorAll('a[href]'))
            .slice(0, 40)
            .map(el => ({ text: (el.textContent || '').trim(), href: el.href || '' }))
            .filter(r => r.href);

          const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'))
            .slice(0, 20)
            .map(el => ({ text: (el.textContent || el.value || '').trim(), type: el.getAttribute('type') || el.tagName.toLowerCase() }))
            .filter(r => r.text);

          const forms = Array.from(document.forms).slice(0, 10).map((form, index) => ({
            index,
            action: form.action || '',
            method: (form.method || 'get').toLowerCase(),
            fields: Array.from(form.elements).slice(0, 20).map(f => ({
              name: f.name || '',
              type: f.type || f.tagName.toLowerCase(),
            })).filter(f => f.name || f.type),
          }));

          let pageType = 'generic';
          if (document.forms.length > 0) pageType = 'form';
          else if (document.querySelector('article')) pageType = 'article';
          else if (document.querySelector('[role="main"]')) pageType = 'app';

          return {
            url: window.location.href,
            title: document.title,
            text: text.slice(0, MAX_LENGTH).trim(),
            headings,
            links,
            buttons,
            forms,
            selection: window.getSelection()?.toString().trim() || '',
            pageType,
          };
        })();
      `);
      return result;
    } catch (err) {
      return { url: '', title: '', text: '', error: err.message };
    }
  }
  if (message.action === 'controllerEvent') {
    const payload = message.payload || {};
    const eventName = payload.event || '';
    // --- SCBE action-governor: gate every sidepanel-agent action (audit + enforce) ---
    const verdict = actionGate.gate(eventName, payload);
    actionGate.log(verdict, payload);
    if (verdict.decision === 'BLOCK') return { ok: false, event: eventName, blocked: true, reason: verdict.reason };
    if (verdict.decision === 'CONFIRM' && !payload.confirmed) return { ok: false, event: eventName, needsConfirm: true, reason: verdict.reason };
    if (eventName === 'back') {
      if (c.browserView.webContents.canGoBack()) c.browserView.webContents.goBack();
      return { ok: true, event: eventName };
    }
    if (eventName === 'forward') {
      if (c.browserView.webContents.canGoForward()) c.browserView.webContents.goForward();
      return { ok: true, event: eventName };
    }
    if (eventName === 'reload') {
      c.browserView.webContents.reload();
      return { ok: true, event: eventName };
    }
    try {
      const encoded = JSON.stringify(payload);
      return await c.browserView.webContents.executeJavaScript(`
        (function(payload) {
          const eventName = payload.event || '';
          const text = payload.text || '';
          const centerElement = () => document.elementFromPoint(
            Math.max(1, Math.floor(window.innerWidth / 2)),
            Math.max(1, Math.floor(window.innerHeight / 2))
          );
          const activeOrCenter = () => {
            const active = document.activeElement;
            if (active && active !== document.body && active !== document.documentElement) return active;
            return centerElement();
          };
          const result = { ok: true, event: eventName, url: window.location.href, title: document.title };
          if (eventName === 'move_up') window.scrollBy({ top: -Math.round(window.innerHeight * 0.62), behavior: 'smooth' });
          else if (eventName === 'move_down') window.scrollBy({ top: Math.round(window.innerHeight * 0.62), behavior: 'smooth' });
          else if (eventName === 'move_left') window.scrollBy({ left: -Math.round(window.innerWidth * 0.62), behavior: 'smooth' });
          else if (eventName === 'move_right') window.scrollBy({ left: Math.round(window.innerWidth * 0.62), behavior: 'smooth' });
          else if (eventName === 'primary') {
            const el = activeOrCenter();
            if (!el) return { ...result, ok: false, error: 'no target element' };
            el.click();
            result.target = el.tagName;
          } else if (eventName === 'secondary') {
            const el = activeOrCenter();
            if (!el) return { ...result, ok: false, error: 'no target element' };
            el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, view: window }));
            result.target = el.tagName;
          } else if (eventName === 'type') {
            const el = activeOrCenter();
            if (!el) return { ...result, ok: false, error: 'no target element' };
            if ('value' in el) {
              el.value = String(el.value || '') + text;
              el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            } else if (el.isContentEditable) {
              el.focus();
              document.execCommand('insertText', false, text);
            } else {
              return { ...result, ok: false, error: 'target is not text-editable', target: el.tagName };
            }
            result.target = el.tagName;
          } else if (eventName === 'escape') {
            document.activeElement?.blur?.();
          } else if (eventName !== 'observe' && eventName !== 'haptic') {
            return { ...result, ok: false, error: 'unsupported page controller event' };
          }
          result.scroll = { x: window.scrollX, y: window.scrollY };
          return result;
        })(${encoded});
      `);
    } catch (err) {
      return { ok: false, event: eventName, error: err.message };
    }
  }
  return null;
});

ipcMain.handle('chrome-tabs-captureVisibleTab', async (event) => {
  const c = ctxFromEvent(event);
  if (!c || !c.browserView) return { ok: false, error: 'No browser pane' };
  try {
    const image = await c.browserView.webContents.capturePage();
    const dataUrl = 'data:image/jpeg;base64,' + image.toJPEG(70).toString('base64');
    return { ok: true, dataUrl };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('read-page', async (event) => {
  const c = ctxFromEvent(event);
  if (!c || !c.browserView) return null;
  try {
    return await c.browserView.webContents.executeJavaScript(`
      ({
        url: window.location.href,
        title: document.title,
        text: document.body?.innerText?.slice(0, 100000) || '',
      })
    `);
  } catch {
    return null;
  }
});

ipcMain.handle('get-page-meta', async (event) => {
  const c = ctxFromEvent(event);
  if (!c || !c.browserView) return null;
  try {
    return await c.browserView.webContents.executeJavaScript(`
      ({
        url: window.location.href,
        title: document.title,
        favicon: document.querySelector('link[rel*="icon"]')?.href || '',
      })
    `);
  } catch {
    return null;
  }
});

// ---------------------------------------------------------------------------
// Application menu — "New Agent Window" (Ctrl+N) opens another shared-pool spot.
// ---------------------------------------------------------------------------
function buildMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'New Agent Window',
          accelerator: 'CmdOrCtrl+N',
          click: () => createBrowserWindow(),
        },
        {
          label: 'New Tab',
          accelerator: 'CmdOrCtrl+T',
          click: () => {
            const c = focusedCtx();
            if (c && c.browserView) {
              c.tabs.push({ url: 'https://www.google.com', title: 'New Tab' });
              c.activeTabIndex = c.tabs.length - 1;
              c.browserView.webContents.loadURL('https://www.google.com');
            }
          },
        },
        {
          label: 'Close Tab',
          accelerator: 'CmdOrCtrl+W',
          click: () => {
            const c = focusedCtx();
            if (!c) return;
            if (c.tabs.length > 1) {
              c.tabs.splice(c.activeTabIndex, 1);
              c.activeTabIndex = Math.min(c.activeTabIndex, c.tabs.length - 1);
              const tab = currentTab(c);
              if (tab && c.browserView) c.browserView.webContents.loadURL(tab.url);
            } else if (c.win) {
              c.win.close();
            }
          },
        },
        { type: 'separator' },
        {
          label: 'Focus Address Bar',
          accelerator: 'CmdOrCtrl+L',
          click: () => {
            const c = focusedCtx();
            if (c && c.addressBarView) c.addressBarView.webContents.send('focus-address-bar');
          },
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'View',
      submenu: [
        {
          label: 'Reload Page',
          accelerator: 'CmdOrCtrl+R',
          click: () => { const c = focusedCtx(); if (c && c.browserView) c.browserView.webContents.reload(); },
        },
        {
          label: 'Toggle Sidepanel DevTools',
          accelerator: 'CmdOrCtrl+Shift+I',
          click: () => { const c = focusedCtx(); if (c && c.sidepanelView) c.sidepanelView.webContents.toggleDevTools(); },
        },
        {
          label: 'Toggle Browser DevTools',
          accelerator: 'F12',
          click: () => { const c = focusedCtx(); if (c && c.browserView) c.browserView.webContents.toggleDevTools(); },
        },
      ],
    },
    {
      label: 'Navigate',
      submenu: [
        {
          label: 'Back',
          accelerator: 'Alt+Left',
          click: () => { const c = focusedCtx(); if (c && c.browserView && c.browserView.webContents.canGoBack()) c.browserView.webContents.goBack(); },
        },
        {
          label: 'Forward',
          accelerator: 'Alt+Right',
          click: () => { const c = focusedCtx(); if (c && c.browserView && c.browserView.webContents.canGoForward()) c.browserView.webContents.goForward(); },
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  aetherTools = aetherToolsMod.register({ ipcMain, ctxFromEvent, actionGate });  // register the agent tool surface (before windows)
  aetherTerminal.register({ ipcMain, actionGate });  // register tmux + vim programmatic tools
  aetherRecorder.register({ ipcMain });  // register the trajectory recorder (browser allows the AI to train on it)

  // --- POINT OUR MODEL AT THE BROWSER: scbe-coder drives the gated tools, every run recorded for training ---
  ipcMain.handle('agent-run', async (event, opts = {}) => {
    const ctx = ctxFromEvent(event);
    if (!ctx) return { ok: false, error: 'no browser window for this agent' };
    const model = opts.model || 'scbe-coder:latest';        // our homemade model; the browser is free for it
    const out = await aetherMiddleman.runTask({
      task: String(opts.task || ''), model,
      callTool: (tool, args) => aetherTools.invoke(ctx, tool, args),   // real browser, gated
      ollama: opts.ollama || 'http://localhost:11434',
      maxSteps: Number(opts.maxSteps || 12),
      log: (m) => { try { ctx.sidepanelView && ctx.sidepanelView.webContents.send('agent-log', m); } catch (_) {} },
    });
    try { aetherRecorder.write({ task: opts.task, model, ...out }); } catch (_) {}   // record the session -> training data
    return out;
  });
  spawnBackend();
  buildMenu();
  createBrowserWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createBrowserWindow();
  });
});

app.on('window-all-closed', () => {
  killBackend();
  app.quit();
});

app.on('before-quit', () => {
  killBackend();
});
