(function () {
  'use strict';

  const modelList = document.querySelector('#modelList');
  const agentList = document.querySelector('#agentList');
  const toast = document.querySelector('#toast');
  const moreButton = document.querySelector('#moreButton');
  const moreMenu = document.querySelector('#moreMenu');
  const results = document.querySelector('#results');
  const runButton = document.querySelector('#runTest');
  const saveButton = document.querySelector('#saveOnly');
  const closeButton = document.querySelector('#closeManager');
  const saveState = document.querySelector('#saveState');
  const logOutput = document.querySelector('#logOutput');
  const selectAllAgents = document.querySelector('#selectAllAgents');
  let toastTimer;
  let backendReady = false;
  let busy = false;
  let appVersion = '1.0.0';
  let selectedAgentState = null;

  const providerPresets = {
    zhipu: {
      apiBase: 'https://open.bigmodel.cn/api/paas/v4',
      protocol: 'openai',
      displayName: '智谱开放平台',
      defaultModels: {
        vision: ['glm-4.6v-flash', 'glm-4.1v-thinking-flash'],
        image_generation: [],
        video_generation: []
      },
      modelOptions: {
        vision: [
          {id: 'glm-4.6v-flash', concurrency: 1},
          {id: 'glm-4.1v-thinking-flash', concurrency: 5}
        ],
        image_generation: [{id: 'cogview-3-flash', concurrency: 1}],
        video_generation: [{id: 'cogvideox-flash', concurrency: 3}]
      },
      keyUrl: 'https://docs.bigmodel.cn/cn/guide/models/free/glm-4.6v-flash'
    },
    bailian: {
      apiBase: 'https://coding.dashscope.aliyuncs.com/v1',
      protocol: 'openai',
      displayName: '阿里云百炼 Coding Plan',
      defaultModels: {vision: [], image_generation: [], video_generation: []},
      modelOptions: {vision: [], image_generation: [], video_generation: []},
      keyUrl: 'https://help.aliyun.com/zh/model-studio/coding-plan'
    },
    custom: {
      apiBase: '',
      protocol: 'openai',
      displayName: '',
      defaultModels: {vision: [], image_generation: [], video_generation: []},
      modelOptions: {vision: [], image_generation: [], video_generation: []},
      keyUrl: ''
    }
  };

  const statusClasses = {
    configured: 'configured',
    conflict: 'conflict',
    invalid_config: 'conflict',
    not_detected: 'missing'
  };

  function api() {
    return window.pywebview && window.pywebview.api;
  }

  function newId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
      const random = Math.random() * 16 | 0;
      const value = character === 'x' ? random : (random & 3 | 8);
      return value.toString(16);
    });
  }

  function showToast(message, kind = 'success') {
    clearTimeout(toastTimer);
    toast.textContent = String(message || '操作完成');
    toast.classList.toggle('error', kind === 'error');
    toast.classList.add('visible');
    toastTimer = setTimeout(() => toast.classList.remove('visible'), 2600);
  }

  function setDirty() {
    if (!busy) saveState.textContent = '有未保存的更改';
  }

  function updateMoveButtons() {
    const rows = [...modelList.querySelectorAll('[data-model-row]')];
    rows.forEach((row, index) => {
      row.querySelector('.move-up').disabled = index === 0;
      row.querySelector('.move-down').disabled = index === rows.length - 1;
      row.querySelector('.delete-model').disabled = rows.length === 1;
      row.querySelector('.priority-label').textContent = `#${index + 1}`;
    });
  }

  const capabilityLabels = {
    vision: '视觉理解',
    image_generation: '图片生成',
    video_generation: '视频生成'
  };

  function normalizeModels(value) {
    const fallback = value?.model ? [value.model] : [];
    const source = value?.models || {vision: fallback, image_generation: [], video_generation: []};
    return Object.fromEntries(Object.keys(capabilityLabels).map(capability => [
      capability,
      Array.isArray(source[capability]) ? source[capability].map(String).filter(Boolean) : []
    ]));
  }

  function collectRowModels(row) {
    const result = {vision: [], image_generation: [], video_generation: []};
    row.querySelectorAll('.model-option input:checked').forEach(input => {
      result[input.dataset.capability].push(input.dataset.model);
    });
    row.querySelectorAll('.custom-model-row input').forEach(input => {
      const capability = input.dataset.capability;
      const value = input.value.trim();
      if (value && !result[capability].some(existing => existing.toLowerCase() === value.toLowerCase())) {
        result[capability].push(value);
      }
    });
    return result;
  }

  function addCustomModelInput(row, container, capability, value = '') {
    const item = document.createElement('div');
    item.className = 'custom-model-row';
    const input = document.createElement('input');
    input.dataset.capability = capability;
    input.placeholder = '请输入模型 ID';
    input.value = value;
    input.maxLength = 300;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'inline-remove';
    remove.textContent = '移除';
    input.addEventListener('input', () => {
      updateModelSummary(row);
      duplicateModelMessage(false);
      setDirty();
    });
    remove.addEventListener('click', event => {
      event.stopPropagation();
      item.remove();
      updateModelSummary(row);
      setDirty();
    });
    item.append(input, remove);
    container.append(item);
    input.focus();
  }

  function updateModelSummary(row) {
    const models = collectRowModels(row);
    const parts = [
      models.vision.length ? `视觉理解 ${models.vision.length}` : '',
      models.image_generation.length ? `图片生成 ${models.image_generation.length}` : '',
      models.video_generation.length ? `视频生成 ${models.video_generation.length}` : ''
    ].filter(Boolean);
    row.querySelector('.model-summary').textContent = parts.join(' · ') || '请选择或填写模型';
  }

  function renderModelPicker(row, presetId, selectedModels) {
    const panel = row.querySelector('.model-picker-panel');
    panel.replaceChildren();
    const preset = providerPresets[presetId] || providerPresets.custom;
    const selected = normalizeModels({models: selectedModels});
    Object.keys(capabilityLabels).forEach(capability => {
      const group = document.createElement('div');
      group.className = 'capability-group';
      const title = document.createElement('div');
      title.className = 'capability-title';
      title.textContent = capabilityLabels[capability];
      const options = document.createElement('div');
      options.className = 'model-options';
      const known = preset.modelOptions?.[capability] || [];
      known.forEach(option => {
        const model = typeof option === 'string' ? option : option.id;
        const label = document.createElement('label');
        label.className = 'model-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.dataset.capability = capability;
        checkbox.dataset.model = model;
        checkbox.checked = selected[capability].includes(model);
        checkbox.addEventListener('change', () => {
          updateModelSummary(row);
          duplicateModelMessage(true);
          setDirty();
        });
        const name = document.createElement('span');
        name.textContent = model;
        label.append(checkbox, name);
        if (option.concurrency) {
          const badge = document.createElement('span');
          badge.className = 'concurrency-badge';
          badge.textContent = `并发 ${option.concurrency}`;
          label.append(badge);
        }
        options.append(label);
      });
      const customList = document.createElement('div');
      customList.className = 'custom-model-list';
      const knownIds = known.map(option => typeof option === 'string' ? option : option.id);
      selected[capability].filter(model => !knownIds.includes(model)).forEach(model => {
        addCustomModelInput(row, customList, capability, model);
      });
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'add-inline-button';
      add.textContent = '+ 添加其他模型';
      add.addEventListener('click', () => addCustomModelInput(row, customList, capability));
      group.append(title, options, customList, add);
      panel.append(group);
    });
    updateModelSummary(row);
  }

  function duplicateModelMessage(showMessage = false) {
    // 同一服务商可通过多组配置使用不同 Key，组 ID 保证凭据彼此隔离。
    return '';
  }

  async function revealStoredKey(slot, input) {
    if (slot.dataset.hasStoredKey === 'true' && !input.value) {
      showToast('已保存的 Key 不会回显；输入新 Key 可安全替换');
    }
  }

  function bindKeySlot(row, slot) {
    const input = slot.querySelector('input');
    const toggle = slot.querySelector('.key-toggle');
    toggle.addEventListener('click', async () => {
      const willShow = input.type === 'password';
      if (willShow) await revealStoredKey(slot, input);
      input.type = willShow ? 'text' : 'password';
      toggle.textContent = willShow ? '隐藏' : '显示';
    });
    input.addEventListener('input', () => {
      input.dataset.edited = 'true';
      setDirty();
    });
  }

  function renderKeySlots(row, slots) {
    const list = row.querySelector('.key-list');
    list.replaceChildren();
    const value = slots?.[0] || {id: row.dataset.providerId || newId(), has_key: false};
    const slot = document.createElement('div');
    slot.className = 'key-slot';
    slot.dataset.keyId = row.dataset.providerId || value.id || newId();
    slot.dataset.hasStoredKey = value.has_key ? 'true' : 'false';
    const control = document.createElement('div');
    control.className = 'key-control';
    const input = document.createElement('input');
    input.type = 'password';
    input.autocomplete = 'off';
    input.placeholder = value.has_key ? '已安全保存，留空保持不变' : '请输入 API Key';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'key-toggle';
    toggle.textContent = '显示';
    control.append(input, toggle);
    slot.append(control);
    list.append(slot);
    bindKeySlot(row, slot);
  }

  function bindModelRow(row) {
    const provider = row.querySelector('.provider-select');
    const keyLink = row.querySelector('[data-key-link]');

    row.querySelector('.model-picker > summary').addEventListener('click', () => {
      document.querySelectorAll('.model-picker[open]').forEach(details => {
        if (details !== row.querySelector('.model-picker')) details.removeAttribute('open');
      });
    });

    provider.addEventListener('change', () => {
      const preset = providerPresets[provider.value] || {
        apiBase: '', protocol: '', displayName: '',
        defaultModels: {vision: [], image_generation: [], video_generation: []}, keyUrl: false
      };
      renderModelPicker(row, provider.value, preset.defaultModels);
      row.querySelector('.api-base-input').value = preset.apiBase;
      row.querySelector('.protocol-select').value = preset.protocol;
      row.querySelector('.display-name-input').value = preset.displayName;
      keyLink.hidden = !preset.keyUrl;
      keyLink.href = preset.keyUrl || '';
      renderKeySlots(row, [{id: row.dataset.providerId, has_key: false}]);
      row.querySelector('.key-slot input').dataset.edited = 'true';
      duplicateModelMessage(true);
      setDirty();
      if (provider.value === 'custom') showToast('请在高级设置中填写 API 地址和协议');
      else if (provider.value) showToast(`已填入「${preset.displayName}」的基础信息`);
    });

    row.querySelector('.api-base-input').addEventListener('change', () => duplicateModelMessage(true));

    keyLink.addEventListener('click', async event => {
      if (!backendReady) {
        if (!keyLink.href) event.preventDefault();
        return;
      }
      event.preventDefault();
      const response = await api().open_key_page(provider.value);
      if (!response.ok) showToast(response.message, 'error');
    });

    row.querySelectorAll('input:not(.key-control input), select').forEach(control => {
      control.addEventListener('input', setDirty);
      control.addEventListener('change', setDirty);
    });

    row.querySelector('.delete-model').addEventListener('click', () => {
      if (modelList.querySelectorAll('[data-model-row]').length === 1) {
        showToast('至少需要保留一个模型配置', 'error');
        return;
      }
      row.remove();
      updateMoveButtons();
      setDirty();
      showToast('已删除模型配置');
    });

    row.querySelector('.move-up').addEventListener('click', () => {
      const previous = row.previousElementSibling;
      if (previous) modelList.insertBefore(row, previous);
      updateMoveButtons();
      setDirty();
    });

    row.querySelector('.move-down').addEventListener('click', () => {
      const next = row.nextElementSibling;
      if (next) modelList.insertBefore(next, row);
      updateMoveButtons();
      setDirty();
    });
  }

  function createModelRow(provider) {
    const row = document.querySelector('#modelTemplate').content.firstElementChild.cloneNode(true);
    const value = provider || {
      id: newId(), preset_id: '', name: '', models: null, model: '', api_base: '', api_protocol: '', has_key: false
    };
    row.dataset.providerId = value.id || newId();
    row.querySelector('.provider-select').value = value.preset_id || '';
    renderModelPicker(row, value.preset_id || '', normalizeModels(value));
    row.querySelector('.api-base-input').value = value.api_base || '';
    row.querySelector('.protocol-select').value = value.api_protocol || '';
    row.querySelector('.display-name-input').value = value.name || '';
    renderKeySlots(row, [{id: value.id, has_key: value.has_key}]);
    const link = row.querySelector('[data-key-link]');
    const keyUrl = providerPresets[value.preset_id]?.keyUrl || '';
    link.hidden = !keyUrl;
    link.href = keyUrl;
    bindModelRow(row);
    return row;
  }

  function renderModels(providers) {
    modelList.replaceChildren();
    (providers && providers.length ? providers : [null]).forEach(provider => {
      modelList.append(createModelRow(provider));
    });
    updateMoveButtons();
  }

  function renderAgents(agents, selectedKeys) {
    const preserved = selectedKeys != null
      ? new Set(selectedKeys)
      : selectedAgentState != null
        ? new Set(selectedAgentState)
        : null;
    const nextSelection = new Set();
    agentList.querySelectorAll('.agent-row').forEach(row => row.remove());
    agents.forEach(agent => {
      const row = document.createElement('label');
      row.className = 'agent-row';
      row.dataset.agentKey = agent.key;
      row.dataset.agentStatus = agent.status;
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = preserved ? preserved.has(agent.key) : Boolean(agent.selected);
      checkbox.disabled = !agent.installed;
      if (checkbox.checked) nextSelection.add(agent.key);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) selectedAgentState.add(agent.key);
        else selectedAgentState.delete(agent.key);
        setDirty();
        updatePrimaryActionLabel();
        updateSelectAllAgents();
      });
      const name = document.createElement('span');
      name.className = 'agent-name';
      name.textContent = agent.name;
      const installed = document.createElement('span');
      installed.className = `agent-install ${agent.installed ? 'installed' : 'not-installed'}`;
      installed.textContent = agent.installed ? '已安装' : '未安装';
      const status = document.createElement('span');
      status.className = `agent-status ${statusClasses[agent.status] || ''}`;
      status.textContent = agent.installed ? agent.status_label : '不可配置';
      row.append(checkbox, name, installed, status);
      agentList.append(row);
    });

    const other = document.createElement('div');
    other.className = 'agent-row other-agent';
    other.innerHTML = '<span class="other-agent-mark" aria-hidden="true">···</span><span class="agent-name">其他 Agent</span><span class="agent-install not-installed">手动接入</span>';
    const copy = document.createElement('button');
    copy.className = 'copy-config-button';
    copy.id = 'copyMcpConfig';
    copy.type = 'button';
    copy.textContent = '复制 MCP 配置';
    copy.addEventListener('click', copyManualConfig);
    other.append(copy);
    agentList.append(other);
    selectedAgentState = nextSelection;
    updatePrimaryActionLabel();
    updateSelectAllAgents();
  }

  function updateSelectAllAgents() {
    const available = [...agentList.querySelectorAll('.agent-row[data-agent-key] input:not(:disabled)')];
    const checked = available.filter(checkbox => checkbox.checked).length;
    selectAllAgents.disabled = available.length === 0;
    selectAllAgents.checked = available.length > 0 && checked === available.length;
    selectAllAgents.indeterminate = checked > 0 && checked < available.length;
    selectAllAgents.setAttribute(
      'aria-checked',
      selectAllAgents.indeterminate ? 'mixed' : String(selectAllAgents.checked)
    );
  }

  function updatePrimaryActionLabel() {
    if (busy) return;
    const selectedRows = [...agentList.querySelectorAll('.agent-row[data-agent-key]')]
      .filter(row => row.querySelector('input:checked'));
    const allConfigured = selectedRows.length > 0 && selectedRows.every(row =>
      row.dataset.agentStatus === 'configured' || row.querySelector('.agent-status')?.classList.contains('configured')
    );
    runButton.querySelector('span').textContent = allConfigured ? '重新配置并测试' : '一键配置并测试';
  }

  function collectPayload() {
    const providers = [...modelList.querySelectorAll('[data-model-row]')].map(row => {
      const input = row.querySelector('.key-slot input');
      const edited = input.dataset.edited === 'true';
      const apiKey = input.value;
      let keyAction = 'keep';
      if (edited) keyAction = apiKey ? 'set' : 'delete';
      return {
        id: row.dataset.providerId,
        preset_id: row.querySelector('.provider-select').value,
        enabled: true,
        models: collectRowModels(row),
        api_base: row.querySelector('.api-base-input').value.trim(),
        api_protocol: row.querySelector('.protocol-select').value,
        name: row.querySelector('.display-name-input').value.trim(),
        api_key: apiKey,
        key_action: keyAction
      };
    });
    return { providers };
  }

  function selectedAgentKeys() {
    return [...agentList.querySelectorAll('.agent-row[data-agent-key] input:checked')]
      .map(input => input.closest('.agent-row').dataset.agentKey);
  }

  function selectedAgentNames() {
    return [...agentList.querySelectorAll('.agent-row[data-agent-key] input:checked')]
      .map(input => input.closest('.agent-row').querySelector('.agent-name').textContent);
  }

  function missingKeyMessage() {
    const rows = [...modelList.querySelectorAll('[data-model-row]')];
    const missing = rows.map((row, index) => {
        const available = [...row.querySelectorAll('.key-slot')].some(slot => {
          const input = slot.querySelector('input');
          return Boolean(input.value.trim()) ||
            (input.dataset.edited !== 'true' && slot.dataset.hasStoredKey === 'true');
        });
        return available ? null : index + 1;
      })
      .filter(index => index !== null);
    return missing.length ? `第 ${missing.join('、')} 个服务商未填写 API Key` : '';
  }

  function stage(name, state, message) {
    const row = results.querySelector(`[data-stage="${name}"]`);
    row.className = `result-row ${state}`;
    row.querySelector('.result-indicator').textContent = state === 'success' ? '✓' : state === 'failed' ? '×' : '';
    row.querySelector('.result-message').textContent = message;
  }

  function resetStages() {
    ['agent', 'protocol', 'model'].forEach((name, index) => {
      const row = results.querySelector(`[data-stage="${name}"]`);
      row.className = 'result-row';
      row.querySelector('.result-indicator').textContent = String(index + 1);
      row.querySelector('.result-message').textContent = '等待开始';
    });
  }

  function appendLog(text) {
    const line = String(text || '').trim();
    if (!line) return;
    logOutput.textContent = logOutput.textContent === '尚未执行测试。' ? line : `${logOutput.textContent}\n${line}`;
  }

  window.visionApp = {
    stageUpdate: stage,
    appendLog
  };

  async function saveModels(showMessage = true) {
    if (duplicateModelMessage(true)) return false;
    if (!backendReady) {
      saveState.textContent = '模型配置已保存（原型预览）';
      if (showMessage) showToast('原型预览中未写入系统配置');
      return true;
    }
    const selected = selectedAgentKeys();
    const response = await api().save_models(collectPayload());
    if (!response.ok) {
      showToast(response.message, 'error');
      saveState.textContent = '保存失败';
      return false;
    }
    renderModels(response.state.providers);
    renderAgents(response.state.agents, selected);
    saveState.textContent = '模型配置已保存';
    if (showMessage) showToast(response.message, response.warning ? 'error' : 'success');
    return true;
  }

  async function runConfigureAndTest() {
    if (duplicateModelMessage(true)) return;
    const selected = selectedAgentKeys();
    if (!selected.length) {
      showToast('请先选择至少一个已安装的 Agent', 'error');
      return;
    }
    const keyError = missingKeyMessage();
    if (keyError) {
      resetStages();
      results.classList.add('visible');
      stage('model', 'failed', keyError);
      logOutput.textContent = keyError;
      saveState.textContent = keyError;
      showToast(keyError, 'error');
      const firstMissing = [...modelList.querySelectorAll('[data-model-row]')]
        .find(row => {
          return ![...row.querySelectorAll('.key-slot')].some(slot => {
            const input = slot.querySelector('input');
            return input.value.trim() || (input.dataset.edited !== 'true' && slot.dataset.hasStoredKey === 'true');
          });
        });
      firstMissing?.querySelector('.key-slot input')?.focus();
      return;
    }
    if (!backendReady) {
      resetStages();
      results.classList.add('visible');
      stage('agent', 'success', '原型预览：Agent 配置完成');
      stage('protocol', 'success', '原型预览：发现 11 个视觉与生成工具');
      stage('model', 'success', '原型预览：模型连接正常');
      showToast('原型状态演示完成');
      return;
    }
    if (busy) return;
    busy = true;
    resetStages();
    results.classList.add('visible');
    logOutput.textContent = '开始配置所选 Agent…';
    runButton.disabled = true;
    runButton.querySelector('span').textContent = '正在配置…';
    saveButton.disabled = true;
    saveState.textContent = '正在执行三阶段检查';
    const response = await api().configure_and_test(collectPayload(), selected);
    busy = false;
    runButton.disabled = false;
    saveButton.disabled = false;
    if (!response.ok) {
      stage('model', 'failed', response.message);
      logOutput.textContent = response.message;
      showToast(response.message, 'error');
      saveState.textContent = '测试未通过';
      updatePrimaryActionLabel();
      return;
    }
    renderModels(response.state.providers);
    renderAgents(response.state.agents, selected);
    saveState.textContent = response.passed ? '测试通过' : '测试未通过';
    showToast(response.message, response.passed ? 'success' : 'error');
  }

  async function closeManager() {
    if (!backendReady) {
      showToast('原型预览模式不会关闭浏览器页面');
      return;
    }
    const response = await api().close_manager();
    if (!response.ok) showToast(response.message, 'error');
  }

  async function openProjectPage(event) {
    if (!backendReady) return;
    event.preventDefault();
    const response = await api().open_project_page();
    if (!response.ok) showToast(response.message, 'error');
  }

  async function copyManualConfig() {
    if (!backendReady) {
      showToast('正式程序会复制包含实际安装路径的配置');
      return;
    }
    const response = await api().copy_manual_config();
    showToast(response.message, response.ok ? 'success' : 'error');
  }

  async function handleMenuAction(action) {
    const selected = selectedAgentKeys();
    const names = selectedAgentNames();
    if (action === 'help') {
      document.querySelector('#helpDialog').showModal();
      return;
    }
    if (action === 'about') {
      document.querySelector('#aboutVersion').textContent = appVersion;
      document.querySelector('#aboutDialog').showModal();
      return;
    }
    if (action === 'uninstall') {
      if (!backendReady) return showToast('正式程序中将直接打开卸载向导');
      const response = await api().uninstall();
      if (!response.ok) showToast(response.message, 'error');
      return;
    }
    if (!selected.length) return showToast('请先选择至少一个已安装的 Agent', 'error');
    if (!backendReady) return showToast('原型预览中未修改 Agent 配置');
    let response;
    if (action === 'remove') {
      if (!window.confirm(`确认从以下 Agent 移除 Vision MCP 配置？\n\n${names.join('、')}\n\n不会卸载 Agent，也不会删除模型凭据。`)) return;
      response = await api().remove_agents(selected);
    } else if (action === 'restore') {
      if (!window.confirm(`确认恢复以下 Agent 的最近备份？\n\n${names.join('、')}\n\n恢复会替换对应配置文件，请确认 Agent 已关闭。`)) return;
      response = await api().restore_backups(selected);
    }
    if (!response) return;
    (response.logs || []).forEach(appendLog);
    if (response.agents) renderAgents(response.agents, selected);
    showToast(response.message, response.ok ? 'success' : 'error');
  }

  async function initializeBackend() {
    if (!api()) return;
    const response = await api().get_state();
    if (!response.ok) {
      saveState.textContent = '配置加载失败';
      showToast(response.message, 'error');
      return;
    }
    backendReady = true;
    appVersion = response.state.version;
    renderModels(response.state.providers);
    renderAgents(response.state.agents);
    saveState.textContent = '配置已加载';
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }));
  }

  document.querySelector('#addModel').addEventListener('click', () => {
    const row = createModelRow(null);
    modelList.append(row);
    updateMoveButtons();
    row.querySelector('select').focus();
    setDirty();
    showToast('已添加模型配置');
  });

  runButton.addEventListener('click', runConfigureAndTest);
  saveButton.addEventListener('click', () => saveModels(true));
  closeButton.addEventListener('click', closeManager);
  selectAllAgents.addEventListener('change', () => {
    agentList.querySelectorAll('.agent-row[data-agent-key] input:not(:disabled)').forEach(checkbox => {
      checkbox.checked = selectAllAgents.checked;
    });
    selectedAgentState = new Set(selectedAgentKeys());
    updateSelectAllAgents();
    updatePrimaryActionLabel();
    setDirty();
  });
  document.querySelector('#projectLink').addEventListener('click', openProjectPage);
  document.querySelectorAll('[data-close-dialog]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog').close());
  });
  document.querySelector('#closeResults')?.addEventListener('click', () => results.classList.remove('visible'));

  moreButton.addEventListener('click', event => {
    event.stopPropagation();
    const open = moreMenu.classList.toggle('open');
    moreButton.setAttribute('aria-expanded', String(open));
  });

  document.addEventListener('click', event => {
    const eventPath = event.composedPath();
    document.querySelectorAll('.model-picker[open]').forEach(details => {
      if (!eventPath.includes(details)) details.removeAttribute('open');
    });
    if (!event.target.closest('.more-wrap')) {
      moreMenu.classList.remove('open');
      moreButton.setAttribute('aria-expanded', 'false');
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.model-picker[open]').forEach(details => details.removeAttribute('open'));
  });

  moreMenu.addEventListener('click', event => {
    const action = event.target.dataset.action;
    if (!action) return;
    moreMenu.classList.remove('open');
    moreButton.setAttribute('aria-expanded', 'false');
    handleMenuAction(action);
  });

  document.querySelector('#copyMcpConfig')?.addEventListener('click', copyManualConfig);
  agentList.querySelectorAll('.agent-row[data-agent-key] input').forEach(checkbox => {
    checkbox.addEventListener('change', () => {
      selectedAgentState = new Set(selectedAgentKeys());
      updateSelectAllAgents();
      updatePrimaryActionLabel();
      setDirty();
    });
  });
  document.querySelectorAll('[data-model-row]').forEach(row => {
    row.dataset.providerId = row.dataset.providerId || newId();
    renderModelPicker(row, 'zhipu', providerPresets.zhipu.defaultModels);
    renderKeySlots(row, [{id: row.dataset.providerId, has_key: false}]);
    bindModelRow(row);
  });
  updateMoveButtons();
  updatePrimaryActionLabel();
  updateSelectAllAgents();
  saveState.textContent = '原型预览模式';
  window.scrollTo(0, 0);
  window.addEventListener('pywebviewready', initializeBackend);
})();
