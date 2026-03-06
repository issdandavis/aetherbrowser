const AGENT_NAMES = {
  KO: 'KO Commander', AV: 'AV Navigator', RU: 'RU Policy',
  CA: 'CA Compute', UM: 'UM Shadow', DR: 'DR Schema',
  user: 'You', system: 'System',
};

export function initConversationFeed(container) {
  container.innerHTML = '';
}

// Track active streaming messages by agent
const _streamBuffers = {};

export function appendMessage(container, msg) {
  const agent = msg.agent || 'system';
  const model = msg.model || '';

  // Handle streaming chunks
  if (msg.type === 'stream') {
    const chunk = msg.payload?.chunk || '';
    const done = msg.payload?.done || false;

    if (!_streamBuffers[agent]) {
      // Create new streaming message element
      const el = document.createElement('div');
      el.className = `ab-message ab-message--${agent} ab-message--streaming`;
      el.innerHTML = `
        <div class="ab-message__header">
          <span class="ab-message__agent">${AGENT_NAMES[agent] || agent}</span>
          ${model ? `<span class="ab-message__model">${model}</span>` : ''}
          <span class="ab-message__streaming-dot"></span>
        </div>
        <div class="ab-message__text"></div>
      `;
      container.appendChild(el);
      _streamBuffers[agent] = { el, text: '' };
    }

    _streamBuffers[agent].text += chunk;
    const textEl = _streamBuffers[agent].el.querySelector('.ab-message__text');
    textEl.textContent = _streamBuffers[agent].text;
    container.scrollTop = container.scrollHeight;

    if (done) {
      _streamBuffers[agent].el.classList.remove('ab-message--streaming');
      const dot = _streamBuffers[agent].el.querySelector('.ab-message__streaming-dot');
      if (dot) dot.remove();
      delete _streamBuffers[agent];
    }
    return;
  }

  const text = msg.payload?.text || msg.payload?.state || JSON.stringify(msg.payload);

  const el = document.createElement('div');
  el.className = `ab-message ab-message--${agent}`;
  el.innerHTML = `
    <div class="ab-message__header">
      <span class="ab-message__agent">${AGENT_NAMES[agent] || agent}</span>
      ${model ? `<span class="ab-message__model">${model}</span>` : ''}
    </div>
    <div class="ab-message__text">${escapeHtml(text)}</div>
  `;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

export function appendUserMessage(container, text) {
  appendMessage(container, { agent: 'user', payload: { text } });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
