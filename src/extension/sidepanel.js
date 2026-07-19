/**
 * @file sidepanel.js
 * @module extension/sidepanel
 *
 * Main entry point for the AetherBrowser sidebar.
 * Wires WebSocket, components, and user interactions together.
 */

import { WsClient } from './lib/ws-client.js';
import { loadSettings } from './lib/storage.js';
import { captureVisibleTab, getOpenTabs, readActivePage } from './lib/dom-reader.js';
import { renderAgentGrid, updateAgentBadge, resetAllBadges, renderProviderHealth, clearProviderHealth } from './components/AgentGrid.js';
import { initConversationFeed, appendMessage, appendUserMessage } from './components/ConversationFeed.js';
import { renderZoneApproval } from './components/ZoneApproval.js';
import { renderProgress } from './components/ProgressCard.js';
import { renderDisconnectedBanner } from './components/DisconnectedBanner.js';
import { renderSettingsPanel } from './components/SettingsPanel.js';
import { SharedContextPanel } from './components/SharedContextPanel.js';

// DOM refs
const agentGridEl = document.getElementById('agent-grid');
const sharedContextEl = document.getElementById('shared-context');
const feedEl = document.getElementById('conversation-feed');
const disconnectedEl = document.getElementById('disconnected-banner');
const settingsEl = document.getElementById('settings-panel');
const inputEl = document.getElementById('input-text');
const sendBtn = document.getElementById('btn-send');
const thisPageBtn = document.getElementById('btn-this-page');
const researchBtn = document.getElementById('btn-research');
const commandBar = document.getElementById('command-bar');

// "+ Spot" opens another agent window (a new spot) that shares this context pool.
const newSpotBtn = document.getElementById('btn-new-spot');
newSpotBtn?.addEventListener('click', () => window.aether?.newAgentWindow());

let ws = null;
let currentSettings = null;
let healthPollHandle = null;
let sharedContext = null;

function routingContext() {
  return {
    preferences: currentSettings?.preferences || {},
    auto_cascade: Boolean(currentSettings?.autoCascade),
  };
}

async function init() {
  currentSettings = await loadSettings();

  renderAgentGrid(agentGridEl);
  clearProviderHealth();
  initConversationFeed(feedEl);

  // Shared Context panel — makes the multi-agent pool visible. Reads the port
  // lazily so a settings change is picked up on the next refresh tick.
  sharedContext = new SharedContextPanel(sharedContextEl, {
    getPort: () => currentSettings?.port || 8002,
  });
  sharedContext.start();

  // Add settings gear to agent grid
  const gearBtn = document.createElement('button');
  gearBtn.className = 'ab-btn ab-btn--secondary';
  gearBtn.textContent = '\u2699';
  gearBtn.title = 'Settings';
  gearBtn.style.cssText = 'margin-left:auto;font-size:16px;padding:2px 6px';
  gearBtn.addEventListener('click', () => {
    renderSettingsPanel(settingsEl, async () => {
      const newSettings = await loadSettings();
      currentSettings = newSettings;
      stopHealthPolling();
      if (ws) {
        ws.disconnect();
        ws.url = `ws://127.0.0.1:${newSettings.port}/ws`;
        ws.connect();
      }
    });
  });
  document.getElementById('agent-grid-row')?.appendChild(gearBtn);

  // Connect WebSocket
  ws = new WsClient({
    url: `ws://127.0.0.1:${currentSettings.port}/ws`,
    onMessage: handleWsMessage,
    onConnectionChange: handleConnectionChange,
  });
  ws.connect();

  // Bind events
  sendBtn.addEventListener('click', handleSend);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });
  thisPageBtn.addEventListener('click', handleThisPage);
  researchBtn.addEventListener('click', handleResearch);
}

function handleWsMessage(msg) {
  // Surface cross-agent broadcasts (command / page_context from OTHER sidebars)
  // in the Shared Context panel's live feed.
  sharedContext?.update(msg);
  switch (msg.type) {
    case 'chat':
      appendMessage(feedEl, msg);
      break;
    case 'agent_status':
      updateAgentBadge(msg.agent, msg.payload?.state || 'idle', msg.model);
      break;
    case 'progress':
      renderProgress(feedEl, msg);
      break;
    case 'zone_request':
      renderZoneApproval(feedEl, msg, (seq, decision) => {
        ws.sendZoneResponse(seq, decision);
      });
      break;
    case 'browser_action':
      handleBrowserAction(msg);
      break;
    case 'controller_event':
      handleControllerEvent(msg);
      break;
    case 'error':
      appendMessage(feedEl, {
        agent: 'system',
        payload: { text: `Error: ${msg.payload?.reason || 'unknown'}` },
      });
      break;
  }
}

async function handleControllerEvent(msg) {
  const payload = msg.payload || {};
  const event = payload.event || 'unknown';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      throw new Error('No active tab found');
    }
    const result = await chrome.tabs.sendMessage(tab.id, {
      action: 'controllerEvent',
      payload,
    });
    appendMessage(feedEl, {
      agent: 'system',
      payload: { text: `Controller ${event}: ${result?.ok === false ? result.error || 'failed' : 'ok'}` },
    });
    if (event === 'observe') {
      await handleThisPage();
    }
  } catch (err) {
    appendMessage(feedEl, {
      agent: 'system',
      payload: { text: `Controller ${event} failed: ${err.message}` },
    });
  }
}

async function handleBrowserAction(msg) {
  const payload = msg.payload || {};
  const action = payload.action;
  try {
    if (action === 'navigate' && payload.url) {
      chrome.tabs.update({ url: payload.url });
      appendMessage(feedEl, {
        agent: 'system',
        payload: { text: `Headless action: navigating to ${payload.url}` },
      });
      return;
    }
    if (action === 'read_page' || action === 'capture_page_context') {
      appendMessage(feedEl, {
        agent: 'system',
        payload: { text: `Headless action: ${action}` },
      });
      await handleThisPage();
      return;
    }
    if (action === 'open_agent_spot') {
      window.aether?.newAgentWindow();
      appendMessage(feedEl, {
        agent: 'system',
        payload: { text: 'Headless action: opened another agent spot' },
      });
      return;
    }
    appendMessage(feedEl, {
      agent: 'system',
      payload: { text: `Unsupported headless browser action: ${action || 'unknown'}` },
    });
  } catch (err) {
    appendMessage(feedEl, {
      agent: 'system',
      payload: { text: `Headless browser action failed: ${err.message}` },
    });
  }
}

function handleConnectionChange(connected) {
  if (connected) {
    disconnectedEl.classList.add('hidden');
    feedEl.classList.remove('hidden');
    commandBar.classList.remove('hidden');
    resetAllBadges();
    refreshHealthStatus();
    startHealthPolling();
    sharedContext?.refresh().catch(() => {});
  } else {
    stopHealthPolling();
    feedEl.classList.add('hidden');
    commandBar.classList.add('hidden');
    disconnectedEl.classList.remove('hidden');
    clearProviderHealth();
    renderDisconnectedBanner(disconnectedEl, {
      port: ws?.url ? parseInt(new URL(ws.url).port, 10) : 8002,
      onServerStarted: () => ws.connect(),
    });
  }
}

function handleSend() {
  const text = inputEl.value.trim();
  if (!text) return;
  appendUserMessage(feedEl, text);
  ws.sendCommand(text, routingContext());
  inputEl.value = '';
  inputEl.focus();
}

async function handleThisPage() {
  try {
    appendUserMessage(feedEl, '[Analyzing current page...]');
    const [page, tabs, screenshot] = await Promise.all([
      readActivePage(),
      getOpenTabs().catch(() => []),
      captureVisibleTab().catch(() => ''),
    ]);
    ws.sendPageContext(
      {
        url: page.url,
        title: page.title,
        text: page.text,
        headings: page.headings || [],
        links: page.links || [],
        buttons: page.buttons || [],
        forms: page.forms || [],
        selection: page.selection || '',
        page_type: page.pageType || 'generic',
        tabs,
        screenshot,
      },
      routingContext(),
    );
  } catch (err) {
    appendMessage(feedEl, {
      agent: 'system',
      payload: { text: `Could not read page: ${err.message}` },
    });
  }
}

function handleResearch() {
  const text = inputEl.value.trim();
  if (!text) {
    inputEl.placeholder = 'Type a research topic first...';
    inputEl.focus();
    return;
  }
  appendUserMessage(feedEl, `[Research] ${text}`);
  ws.sendCommand(text, routingContext());
  inputEl.value = '';
}

function healthUrl() {
  return `http://127.0.0.1:${currentSettings?.port || 8002}/health`;
}

async function refreshHealthStatus() {
  try {
    const response = await fetch(healthUrl(), { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`health ${response.status}`);
    }
    const health = await response.json();
    renderProviderHealth(health.executor || health.providers || {});
  } catch {
    renderProviderHealth({});
  }
}

function startHealthPolling() {
  if (healthPollHandle) return;
  healthPollHandle = window.setInterval(() => {
    refreshHealthStatus().catch(() => {});
  }, 15000);
}

function stopHealthPolling() {
  if (!healthPollHandle) return;
  window.clearInterval(healthPollHandle);
  healthPollHandle = null;
}

init().catch(console.error);
