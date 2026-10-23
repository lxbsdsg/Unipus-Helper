'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const STATUS = {
  INITIALIZING: { label: '登录中' },
  READY: { label: '待开始' },
  NEED_OPERATION: { label: '需要操作' },
  WAITING: { label: '等待中' },
  RUNNING: { label: '运行中' },
  PAUSED: { label: '已暂停' },
  COMPLETED: { label: '已完成' },
  ERROR: { label: '出错' },
};

const LEVEL_RANK = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };

const TYPE_LABEL = {
  'single-choice': '单选',
  'material-banked-cloze': '选词填空',
  short_answer: '简答',
  translation: '翻译',
  'text-learn': '课文学习',
  discussion: '讨论',
  input: '填空',
  'video-point-read': '视频',
  'rich-text-read': '阅读',
  vocabulary: '生词',
  sequence: '排序',
  'basic-scoop-content': '内容学习',
  'video-popup': '视频弹题',
  writing: '写作',
  __unknown__: '未知题型',
};

const state = {
  tasks: new Map(),
  credentials: [],
  logs: [],
  network: [],
  logFilter: { level: '', query: '' },
  netFilter: { method: '', status: '' },
  addMode: 'new',
  selectedCredential: null,
  pendingRemember: new Map(),
  courseTaskId: null,
  courseSelection: { course: null, resource: null, courses: [] },
  catalogTaskId: null,
  catalogRequestId: 0,
  catalog: null,
  catalogLeavesById: new Map(),
  catalogSelection: new Set(),
  activeTaskId: null,
  ws: null,
  reconnectDelay: 1000,
};

/* ------------------------------------------------------------ 基础工具 */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function button(label, className, onClick) {
  const node = el('button', className, label);
  node.type = 'button';
  if (onClick) node.addEventListener('click', onClick);
  return node;
}

function formatTime(ts) {
  const date = new Date(ts);
  const pad = (value, width = 2) => String(value).padStart(width, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

function shortUrl(url) {
  try {
    const parsed = new URL(url, location.origin);
    return parsed.pathname + parsed.search;
  } catch {
    return url;
  }
}

async function api(path, { method = 'GET', body = null } = {}) {
  const options = { method, headers: {} };
  if (body !== null) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error('无法连接到本地服务，请确认程序仍在运行');
  }

  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      if (data && data.error && data.error.message) message = data.error.message;
      else if (data && typeof data.detail === 'string') message = data.detail;
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(message);
  }

  if (response.status === 204) return null;
  return response.json();
}

function toast(message, kind = 'info') {
  const stack = $('#toast-stack');
  const item = el('div', 'toast', message);
  item.dataset.kind = kind;
  stack.append(item);
  setTimeout(() => item.remove(), 6000);
}

let confirmResolve = null;

function confirmAction(title, message, okLabel) {
  $('#confirm-title').textContent = title;
  $('#confirm-message').textContent = message;
  $('#confirm-ok').textContent = okLabel || '确认';
  $('#confirm-dialog').showModal();
  return new Promise((resolve) => {
    confirmResolve = resolve;
  });
}

/* ------------------------------------------------------------ 任务渲染 */

function renderTasks() {
  const tasks = [...state.tasks.values()].sort((a, b) => a.id.localeCompare(b.id));
  const list = $('#task-list');
  list.textContent = '';

  for (const task of tasks) {
    list.append(renderTask(task));
  }

  const hasTasks = tasks.length > 0;
  $('#empty-state').hidden = hasTasks;
  $('.task-foot').hidden = !hasTasks;

  const running = tasks.filter((task) => task.status === 'RUNNING').length;
  $('#task-summary').textContent = hasTasks
    ? `${tasks.length} 个任务 · ${running} 个运行中`
    : '0 个任务';
}

function renderTask(task) {
  const row = el('article', 'task');
  row.dataset.status = task.status;
  row.dataset.id = task.id;

  const main = el('div', 'task-main');
  const titleRow = el('div', 'task-title-row');
  titleRow.append(el('h3', 'task-name', task.name || task.username || task.id));

  const badge = el('span', 'status', (STATUS[task.status] || { label: task.status }).label);
  badge.dataset.tone = task.status;
  titleRow.append(badge);
  main.append(titleRow);

  const meta = [task.user_name, task.school_name].filter(Boolean).join(' · ');
  if (meta) main.append(el('p', 'task-meta', meta));

  const desc = el('p', 'task-desc', task.description || '');
  if (task.status === 'ERROR') desc.classList.add('is-error');
  main.append(desc);

  const progress = el('div', 'task-progress');
  const percent = Math.max(0, Math.min(100, task.progress_percent || 0));
  const ruler = el('div', 'ruler');
  ruler.setAttribute('role', 'progressbar');
  ruler.setAttribute('aria-valuemin', '0');
  ruler.setAttribute('aria-valuemax', '100');
  ruler.setAttribute('aria-valuenow', String(percent));
  ruler.setAttribute('aria-label', `${task.name || task.id} 进度`);
  const fill = el('span', 'ruler-fill');
  fill.style.width = `${percent}%`;
  ruler.append(fill);
  progress.append(ruler);

  const numbers = el('div', 'progress-numbers');
  numbers.append(el('strong', null, String(task.completed || 0)));
  numbers.append(el('span', null, `/ ${task.total || 0}`));
  numbers.append(el('span', 'pct', `${percent}%`));
  progress.append(numbers);

  const controls = el('div', 'task-controls');
  controls.append(...taskControls(task));
  row.append(main, progress, controls);
  return row;
}

function taskControls(task) {
  const controls = [];
  const action = (label, name, className = 'btn btn-ghost btn-sm') => {
    const node = button(label, className, () => runTaskAction(task.id, name));
    node.dataset.action = name;
    node.dataset.id = task.id;
    return node;
  };

  switch (task.status) {
    case 'READY':
      controls.push(action('开始', 'start', 'btn btn-primary btn-sm'));
      controls.push(action('全目录刷题', 'catalog', 'btn btn-ghost btn-sm'));
      break;
    case 'RUNNING':
      controls.push(action('暂停', 'pause'), action('停止', 'stop'));
      break;
    case 'PAUSED':
      controls.push(action('恢复', 'resume', 'btn btn-primary btn-sm'), action('停止', 'stop'));
      break;
    case 'WAITING':
      controls.push(action('暂停', 'pause'), action('停止', 'stop'));
      break;
    case 'NEED_OPERATION': {
      const practice = task.user_operation === 'CHOOSE_PRACTICE';
      controls.push(
        action(practice ? '选择题目' : '选择教程', practice ? 'catalog' : 'choose', 'btn btn-primary btn-sm')
      );
      controls.push(action('暂停', 'pause'));
      break;
    }
    case 'ERROR':
    case 'COMPLETED':
      controls.push(action('重试', 'restart', 'btn btn-primary btn-sm'));
      break;
    default:
      break;
  }

  controls.push(action('管理', 'manage', 'btn-link'));
  return controls;
}

async function runTaskAction(taskId, action) {
  if (action === 'manage') {
    openManage(taskId);
    return;
  }
  if (action === 'choose') {
    openCourse(taskId);
    return;
  }
  if (action === 'catalog') {
    const task = state.tasks.get(taskId);
    if (task && task.status === 'NEED_OPERATION') {
      openCatalog(taskId);
    } else {
      startCatalog(taskId);
    }
    return;
  }
  if (action === 'stop') {
    const confirmed = await confirmAction('停止任务', '停止后任务会回到待开始状态，可以再次启动。', '停止');
    if (!confirmed) return;
  }
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(taskId)}/${action}`, {
      method: 'POST',
    });
    if (result && result.ok === false) {
      toast('任务当前无法执行该操作，请稍后再试', 'warning');
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ------------------------------------------------------------ 管理弹窗 */

function openManage(taskId) {
  const task = state.tasks.get(taskId);
  if (!task) return;
  state.activeTaskId = taskId;
  renderManage(task);
  $('#manage-dialog').showModal();
}

function renderManage(task) {
  const body = $('#manage-body');
  body.textContent = '';
  const rows = [
    ['任务 ID', task.id],
    ['名称', task.name || '—'],
    ['账号', task.username],
    ['用户', [task.user_name, task.school_name].filter(Boolean).join(' · ') || '—'],
    ['状态', (STATUS[task.status] || { label: task.status }).label],
    ['进度', `${task.completed || 0}/${task.total || 0}（${task.progress_percent || 0}%）`],
    ['描述', task.description || '—'],
  ];
  for (const [label, value] of rows) {
    const row = el('dl', 'manage-row');
    row.append(el('dt', null, label), el('dd', null, value));
    body.append(row);
  }

  const actions = $('#manage-actions');
  actions.textContent = '';
  const add = (label, action, className) =>
    actions.append(button(label, className, () => manageAction(task, action)));

  switch (task.status) {
    case 'READY':
      add('开始', 'start', 'btn btn-primary btn-sm');
      add('全目录刷题', 'catalog', 'btn btn-ghost btn-sm');
      break;
    case 'RUNNING':
    case 'WAITING':
      add('暂停', 'pause', 'btn btn-ghost btn-sm');
      add('停止', 'stop', 'btn btn-ghost btn-sm');
      break;
    case 'PAUSED':
      add('恢复', 'resume', 'btn btn-primary btn-sm');
      add('停止', 'stop', 'btn btn-ghost btn-sm');
      break;
    case 'NEED_OPERATION': {
      const practice = task.user_operation === 'CHOOSE_PRACTICE';
      add(
        practice ? '选择题目' : '选择教程',
        practice ? 'catalog' : 'choose',
        'btn btn-primary btn-sm'
      );
      break;
    }
    case 'ERROR':
    case 'COMPLETED':
      add('重新开始', 'restart', 'btn btn-primary btn-sm');
      break;
    default:
      break;
  }
  add('移除', 'remove', 'btn btn-danger btn-sm');
}

async function manageAction(task, action) {
  $('#manage-dialog').close();
  if (action === 'remove') {
    const confirmed = await confirmAction('移除任务', `将停止并移除 ${task.username} 的任务。`, '移除');
    if (!confirmed) return;
    try {
      await api(`/api/tasks/${encodeURIComponent(task.id)}`, { method: 'DELETE' });
    } catch (error) {
      toast(error.message, 'error');
    }
    return;
  }
  if (action === 'choose') {
    openCourse(task.id);
    return;
  }
  if (action === 'catalog') {
    if (task.status === 'NEED_OPERATION') openCatalog(task.id);
    else startCatalog(task.id);
    return;
  }
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(task.id)}/${action}`, {
      method: 'POST',
    });
    if (result && result.ok === false) {
      toast('任务当前无法执行该操作，请稍后再试', 'warning');
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ------------------------------------------------------------ 选择课程 */

async function openCourse(taskId) {
  state.courseTaskId = taskId;
  state.courseSelection = { course: null, resource: null, courses: [] };
  $('#course-error').hidden = true;

  let courses;
  try {
    courses = await api(`/api/tasks/${encodeURIComponent(taskId)}/courses`);
  } catch (error) {
    toast(error.message, 'error');
    return;
  }

  state.courseSelection.courses = Array.isArray(courses) ? courses : [];
  renderCourseOptions();
  $('#course-dialog').showModal();
}

function renderCourseOptions() {
  const selection = state.courseSelection;
  const courseBox = $('#course-options');
  const resourceBox = $('#resource-options');
  courseBox.textContent = '';
  resourceBox.textContent = '';

  if (!selection.courses.length) {
    courseBox.append(el('div', 'saved-empty', '没有可选课程'));
    return;
  }

  for (const course of selection.courses) {
    const node = el('button', 'option', course.name || `课程 ${course.id}`);
    node.type = 'button';
    node.setAttribute('role', 'option');
    node.setAttribute('aria-selected', 'false');
    node.addEventListener('click', () => {
      selection.course = course;
      selection.resource = null;
      $$('.option', courseBox).forEach((item) => {
        item.classList.toggle('is-selected', item === node);
        item.setAttribute('aria-selected', item === node ? 'true' : 'false');
      });
      renderResourceOptions();
    });
    courseBox.append(node);
  }
  renderResourceOptions();
}

function renderResourceOptions() {
  const selection = state.courseSelection;
  const box = $('#resource-options');
  box.textContent = '';
  const resources = selection.course ? selection.course.resources || [] : [];

  if (!resources.length) {
    box.append(el('div', 'saved-empty', selection.course ? '该课程没有教程' : '先选择左侧课程'));
    return;
  }

  for (const resource of resources) {
    const node = el('button', 'option', resource.name || `教程 ${resource.id}`);
    node.type = 'button';
    node.setAttribute('role', 'option');
    node.setAttribute('aria-selected', 'false');
    const meta = el('small', null, `必修 ${resource.finish_point_num}/${resource.total_point_num}`);
    node.append(meta);
    node.addEventListener('click', () => {
      selection.resource = resource;
      $$('.option', box).forEach((item) => {
        item.classList.toggle('is-selected', item === node);
        item.setAttribute('aria-selected', item === node ? 'true' : 'false');
      });
    });
    box.append(node);
  }
}

/* ------------------------------------------------------------ 全目录刷题 */

async function startCatalog(taskId) {
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/catalog`, { method: 'POST' });
    toast('正在加载题目目录，完成后会提示选择题目', 'info');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function openCatalog(taskId) {
  const requestId = ++state.catalogRequestId;
  state.catalogTaskId = taskId;
  state.catalog = null;
  state.catalogLeavesById = new Map();
  state.catalogSelection = new Set();
  $('#catalog-error').hidden = true;
  $('#catalog-tree').textContent = '';
  $('#catalog-summary').textContent = '正在加载目录…';
  $('#catalog-start').disabled = true;

  let tree;
  try {
    tree = await api(`/api/tasks/${encodeURIComponent(taskId)}/catalog`);
  } catch (error) {
    if (requestId === state.catalogRequestId) toast(error.message, 'error');
    return;
  }
  // 并发的重复请求只渲染最后一次，避免覆盖已勾选内容
  if (requestId !== state.catalogRequestId) return;

  state.catalog = tree;
  renderCatalogTree(tree);
  $('#catalog-dialog').showModal();
}

function catalogLabel(node) {
  return node.caption || node.name || node.id || '未命名';
}

let catalogKeySeq = 0;

function catalogNodeKey(node) {
  if (!node._key) node._key = node.id || `node-${++catalogKeySeq}`;
  return node._key;
}

function indexCatalog(node) {
  const leaves = [];
  const children = node.children || [];
  if (children.length) {
    for (const child of children) leaves.push(...indexCatalog(child));
  } else if (node.selectable) {
    leaves.push(node.id);
  }
  const key = catalogNodeKey(node);
  state.catalogLeavesById.set(key, leaves);
  return leaves;
}

function renderCatalogTree(tree) {
  const box = $('#catalog-tree');
  box.textContent = '';
  state.catalogLeavesById = new Map();
  state.catalogSelection = new Set();

  const units = (tree && tree.units) || [];
  if (!units.length) {
    box.append(el('div', 'saved-empty', '这个教程没有可用的题目目录'));
    syncCatalogChecks();
    return;
  }

  for (const unit of units) indexCatalog(unit);
  for (const unit of units) box.append(renderCatalogNode(unit, 0));
  syncCatalogChecks();
}

function renderCatalogNode(node, depth) {
  const children = node.children || [];
  const row = el('div', 'catalog-row');
  row.style.setProperty('--depth', String(depth));

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'catalog-check';
  const nodeKey = catalogNodeKey(node);
  checkbox.dataset.nodeId = nodeKey;
  checkbox.setAttribute('aria-label', catalogLabel(node));

  if (children.length) {
    row.classList.add('catalog-group-row');
    const leaves = state.catalogLeavesById.get(nodeKey) || [];
    checkbox.disabled = leaves.length === 0;
    const details = document.createElement('details');
    details.className = 'catalog-group';
    details.open = depth < 2;

    const summary = document.createElement('summary');
    summary.append(checkbox, el('span', 'catalog-name', catalogLabel(node)));
    summary.append(el('span', 'catalog-count', `${leaves.length} 题`));

    checkbox.addEventListener('click', (event) => event.stopPropagation());
    checkbox.addEventListener('change', () => {
      for (const leafId of leaves) {
        if (checkbox.checked) state.catalogSelection.add(leafId);
        else state.catalogSelection.delete(leafId);
      }
      syncCatalogChecks();
    });

    details.append(summary);
    const childBox = el('div', 'catalog-children');
    for (const child of children) childBox.append(renderCatalogNode(child, depth + 1));
    details.append(childBox);
    row.append(details);
    return row;
  }

  const selectable = Boolean(node.selectable);
  const finish = Number(node.finish_progress || 0);
  checkbox.disabled = !selectable;
  row.classList.add('catalog-leaf-row');
  row.classList.toggle('is-complete', finish >= 100);
  row.classList.toggle('is-unsupported', !selectable && finish < 100);

  const types = (node.bases || []).map((raw) => TYPE_LABEL[raw] || raw).join('、');
  const parts = [];
  if (types) parts.push(types);
  if (node.question_num > 1) parts.push(`${node.question_num} 小题`);
  if (!node.status_known) parts.push('状态未知');
  else parts.push(finish >= 100 ? '已完成' : selectable ? '未完成' : '不可刷');

  checkbox.addEventListener('change', () => {
    if (checkbox.checked) state.catalogSelection.add(node.id);
    else state.catalogSelection.delete(node.id);
    syncCatalogChecks();
  });

  row.append(checkbox, el('span', 'catalog-name', catalogLabel(node)));
  row.append(el('span', 'catalog-meta', parts.join(' · ')));
  return row;
}

function syncCatalogChecks() {
  $$('.catalog-check', $('#catalog-tree')).forEach((checkbox) => {
    const leaves = state.catalogLeavesById.get(checkbox.dataset.nodeId) || [];
    if (!leaves.length) {
      checkbox.checked = false;
      checkbox.indeterminate = false;
      checkbox.disabled = true;
      return;
    }
    const selected = leaves.filter((leafId) => state.catalogSelection.has(leafId)).length;
    checkbox.checked = selected === leaves.length;
    checkbox.indeterminate = selected > 0 && selected < leaves.length;
  });

  const count = state.catalogSelection.size;
  $('#catalog-summary').textContent = `已选 ${count} 题`;
  $('#catalog-start').disabled = count === 0;
}

function selectAllCatalog() {
  state.catalogSelection = new Set();
  for (const unit of (state.catalog && state.catalog.units) || []) {
    for (const leafId of state.catalogLeavesById.get(catalogNodeKey(unit)) || []) {
      state.catalogSelection.add(leafId);
    }
  }
  syncCatalogChecks();
}

/* ------------------------------------------------------------ 添加任务 */

function setAddMode(mode) {
  state.addMode = mode;
  $$('.seg').forEach((node) => {
    const active = node.dataset.addMode === mode;
    node.classList.toggle('is-active', active);
    node.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  $('#add-new').hidden = mode !== 'new';
  $('#add-saved').hidden = mode !== 'saved';
  $('#add-error').hidden = true;
  if (mode === 'saved') refreshCredentials();
}

async function refreshCredentials() {
  try {
    state.credentials = await api('/api/credentials');
  } catch (error) {
    toast(error.message, 'error');
    state.credentials = [];
  }
  renderCredentials();
}

function renderCredentials() {
  const box = $('#saved-list');
  box.textContent = '';
  state.selectedCredential = null;

  if (!state.credentials.length) {
    box.append(el('div', 'saved-empty', '本机还没有保存的账号'));
    return;
  }

  for (const credential of state.credentials) {
    const item = el('div', 'saved-item');
    item.setAttribute('role', 'option');
    item.setAttribute('aria-selected', 'false');
    item.tabIndex = 0;

    const mark = el('span', 'radio-mark');
    mark.setAttribute('aria-hidden', 'true');
    const label = el('span', 'saved-label', credential.label ? `${credential.label} · ${credential.username}` : credential.username);
    const ident = el('span', 'saved-id', credential.id.slice(0, 6));

    const remove = button('×', 'icon-btn saved-remove', async (event) => {
      event.stopPropagation();
      const confirmed = await confirmAction('删除已保存账号', `将删除 ${credential.username} 的本地凭据。`, '删除');
      if (!confirmed) return;
      try {
        await api(`/api/credentials/${encodeURIComponent(credential.id)}`, { method: 'DELETE' });
        state.credentials = state.credentials.filter((item) => item.id !== credential.id);
        renderCredentials();
      } catch (error) {
        toast(error.message, 'error');
      }
    });
    remove.setAttribute('aria-label', `删除 ${credential.username}`);

    const select = () => {
      state.selectedCredential = credential.id;
      $$('.saved-item', box).forEach((node) => {
        const selected = node === item;
        node.classList.toggle('is-selected', selected);
        node.setAttribute('aria-selected', selected ? 'true' : 'false');
      });
    };

    item.addEventListener('click', select);
    item.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select();
      }
    });

    item.append(mark, label, ident, remove);
    box.append(item);
  }
}

async function submitAddForm(event) {
  event.preventDefault();
  const errorBox = $('#add-error');
  const submit = $('#add-submit');
  errorBox.hidden = true;
  submit.disabled = true;

  try {
    if (state.addMode === 'saved') {
      if (!state.selectedCredential) throw new Error('请选择一个已保存的账号');
      await api('/api/tasks', {
        method: 'POST',
        body: { credential_id: state.selectedCredential },
      });
    } else {
      const username = $('#add-username').value.trim();
      const password = $('#add-password').value;
      if (!username || !password) throw new Error('请填写账号和密码');
      const snapshot = await api('/api/tasks', {
        method: 'POST',
        body: { username, password },
      });
      if ($('#add-remember').checked) {
        state.pendingRemember.set(snapshot.id, { username, password });
      }
    }
    $('#add-task-dialog').close();
    $('#add-form').reset();
    toast('任务已添加，正在登录', 'success');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submit.disabled = false;
  }
}

async function maybeRemember(task) {
  if (task.status !== 'READY') return;
  const pending = state.pendingRemember.get(task.id);
  if (!pending) return;
  state.pendingRemember.delete(task.id);
  try {
    await api('/api/credentials', {
      method: 'POST',
      body: {
        username: pending.username,
        password: pending.password,
        label: '',
        task_id: task.id,
      },
    });
    toast('账号已保存到本机', 'success');
    if (!$('#add-saved').hidden) refreshCredentials();
  } catch (error) {
    toast(`保存账号失败：${error.message}`, 'error');
  }
}

/* ------------------------------------------------------------ WebSocket */

function setConnection(stateName) {
  const node = $('#conn-status');
  node.dataset.state = stateName;
  $('#conn-label').textContent =
    { online: '已连接', offline: '已断开', connecting: '连接中' }[stateName] || stateName;
}

function connectWebSocket() {
  setConnection('connecting');
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  state.ws = socket;

  socket.addEventListener('open', () => {
    state.reconnectDelay = 1000;
    setConnection('online');
  });

  socket.addEventListener('message', (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    handleEvent(payload);
  });

  socket.addEventListener('close', () => {
    setConnection('offline');
    state.ws = null;
    setTimeout(connectWebSocket, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 2, 10000);
  });

  socket.addEventListener('error', () => socket.close());
}

function handleEvent(event) {
  switch (event.type) {
    case 'snapshot': {
      const tasks = Array.isArray(event.data) ? event.data : [];
      state.tasks = new Map(tasks.map((task) => [task.id, task]));
      renderTasks();
      break;
    }
    case 'task.added':
    case 'task.updated': {
      const task = event.data;
      if (!task || !task.id) return;
      state.tasks.set(task.id, task);
      renderTasks();
      maybeRemember(task);
      if (task.status === 'ERROR') {
        state.pendingRemember.delete(task.id);
        toast(`${task.name || task.username || task.id}：${task.error || task.description}`, 'error');
      }
      if ($('#manage-dialog').open && state.activeTaskId === task.id) renderManage(task);
      break;
    }
    case 'task.removed': {
      const id = event.data && event.data.id;
      if (!id) return;
      state.tasks.delete(id);
      renderTasks();
      if (state.activeTaskId === id && $('#manage-dialog').open) $('#manage-dialog').close();
      break;
    }
    case 'task.warning':
      toast(event.data.message, 'warning');
      break;
    case 'task.error':
      toast(event.data.message, 'error');
      break;
    case 'log.append':
      appendLog(event.data);
      break;
    case 'network.append':
      appendNetwork(event.data);
      break;
    default:
      break;
  }
}

/* ------------------------------------------------------------ 日志面板 */

function logMatches(record) {
  const filter = state.logFilter;
  if (filter.level) {
    const rank = LEVEL_RANK[record.level] || 0;
    if (rank < (LEVEL_RANK[filter.level] || 0)) return false;
  }
  if (filter.query) {
    const query = filter.query.toLowerCase();
    const haystack = `${record.message || ''} ${record.task_id || ''}`.toLowerCase();
    if (!haystack.includes(query)) return false;
  }
  return true;
}

function logRow(record) {
  const row = el('div', 'log-row');
  row.append(el('span', 'log-time', formatTime(record.ts)));

  const level = el('span', 'log-level', String(record.level || '').toLowerCase());
  level.dataset.level = record.level;
  row.append(level);

  const message = el('span', 'log-message');
  if (record.task_id) message.append(el('span', 'log-task', `[${record.task_id}]`));
  message.append(document.createTextNode(record.message || ''));
  row.append(message);
  return row;
}

function renderLogs() {
  const box = $('#log-list');
  if (!box) return;
  box.textContent = '';
  const filtered = state.logs.filter(logMatches).slice(-1500);
  for (const record of filtered) box.append(logRow(record));
  if ($('#log-autoscroll').checked) box.scrollTop = box.scrollHeight;
}

function appendLog(record) {
  state.logs.push(record);
  if (state.logs.length > 5000) state.logs.splice(0, state.logs.length - 5000);
  if ($('#debug-drawer').classList.contains('is-open') && !$('#panel-logs').hidden && logMatches(record)) {
    const box = $('#log-list');
    box.append(logRow(record));
    while (box.childElementCount > 1500) box.firstElementChild.remove();
    if ($('#log-autoscroll').checked) box.scrollTop = box.scrollHeight;
  }
}

/* ------------------------------------------------------------ 网络面板 */

function netMatches(record) {
  if (state.netFilter.method && record.method !== state.netFilter.method) return false;
  const status = state.netFilter.status;
  if (status === 'error' && !record.error) return false;
  if (status === '2xx' && !(record.status_code >= 200 && record.status_code < 300)) return false;
  if (status === '4xx' && !(record.status_code >= 400 && record.status_code < 500)) return false;
  if (status === '5xx' && !(record.status_code >= 500)) return false;
  return true;
}

function buildNetworkDetail(record) {
  const wrap = el('div', 'net-detail');
  const sections = [
    ['请求头', record.request_headers],
    ['响应头', record.response_headers],
    ['请求体', record.request_payload],
    ['响应体', record.response_body],
  ];
  for (const [title, value] of sections) {
    const section = el('div', 'net-section');
    section.append(el('h4', null, title));
    const pre = el('pre', null, typeof value === 'string' ? value.slice(0, 4000) : JSON.stringify(value || {}, null, 2));
    section.append(pre);
    wrap.append(section);
  }
  if (record.error) {
    const section = el('div', 'net-section');
    section.append(el('h4', null, '错误'), el('pre', null, record.error));
    wrap.append(section);
  }
  return wrap;
}

function networkRow(record) {
  const details = el('details', 'net-row');
  const summary = document.createElement('summary');
  summary.append(el('span', 'net-method', record.method || 'GET'));

  const url = el('span', 'net-url', shortUrl(record.url || ''));
  url.title = record.url || '';
  summary.append(url);

  const status = el('span', 'net-status', record.error ? 'ERR' : String(record.status_code ?? '—'));
  if (record.error) status.classList.add('is-bad');
  else if (record.status_code >= 500) status.classList.add('is-bad');
  else if (record.status_code >= 400) status.classList.add('is-warn');
  else status.classList.add('is-ok');
  summary.append(status);

  summary.append(el('span', 'net-duration', `${record.duration_ms ?? 0} ms`));
  details.append(summary);
  details.addEventListener('toggle', () => {
    if (details.open && !details.dataset.built) {
      details.append(buildNetworkDetail(record));
      details.dataset.built = '1';
    }
  });
  return details;
}

function renderNetwork() {
  const box = $('#network-list');
  if (!box) return;
  box.textContent = '';
  const filtered = state.network.filter(netMatches).slice(-600).reverse();
  for (const record of filtered) box.append(networkRow(record));
  updateNetworkCount();
}

function updateNetworkCount() {
  const count = state.network.filter(netMatches).length;
  const node = $('#net-count');
  if (node) node.textContent = `${count} 条`;
}

function appendNetwork(record) {
  state.network.push(record);
  if (state.network.length > 2000) state.network.splice(0, state.network.length - 2000);
  updateNetworkCount();
  if (
    $('#debug-drawer').classList.contains('is-open') &&
    !$('#panel-network').hidden &&
    netMatches(record)
  ) {
    const box = $('#network-list');
    box.prepend(networkRow(record));
    while (box.childElementCount > 600) box.lastElementChild.remove();
  }
}

/* ------------------------------------------------------------ 抽屉 */

function openDrawer(tab) {
  $('#debug-drawer').classList.add('is-open');
  $('#debug-drawer').setAttribute('aria-hidden', 'false');
  $('#drawer-backdrop').hidden = false;
  selectTab(tab);
  $('#debug-close').focus();
}

function closeDrawer() {
  $('#debug-drawer').classList.remove('is-open');
  $('#debug-drawer').setAttribute('aria-hidden', 'true');
  $('#drawer-backdrop').hidden = true;
}

function selectTab(tab) {
  $$('.tab').forEach((node) => {
    const active = node.dataset.tab === tab;
    node.classList.toggle('is-active', active);
    node.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  $('#panel-logs').hidden = tab !== 'logs';
  $('#panel-network').hidden = tab !== 'network';
  if (tab === 'logs') renderLogs();
  if (tab === 'network') renderNetwork();
}

/* ------------------------------------------------------------ 主题 */

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('theme', theme);
  $('#theme-toggle').setAttribute(
    'aria-label',
    theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'
  );
}

/* ------------------------------------------------------------ 事件绑定 */

function openAddDialog() {
  setAddMode('new');
  $('#add-error').hidden = true;
  $('#add-task-dialog').showModal();
}

async function submitCatalogForm(event) {
  event.preventDefault();
  const errorBox = $('#catalog-error');
  errorBox.hidden = true;
  const ids = [...state.catalogSelection];
  if (!ids.length) {
    errorBox.textContent = '至少选择一道题目';
    errorBox.hidden = false;
    return;
  }

  try {
    await api(`/api/tasks/${encodeURIComponent(state.catalogTaskId)}/catalog/choose`, {
      method: 'POST',
      body: { task_ids: ids },
    });
    $('#catalog-dialog').close();
    toast(`已选择 ${ids.length} 道题，开始刷题`, 'success');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
}

function bindEvents() {
  $('#add-task').addEventListener('click', openAddDialog);
  $('#add-task-empty').addEventListener('click', openAddDialog);
  $('#add-form').addEventListener('submit', submitAddForm);

  $('#catalog-form').addEventListener('submit', submitCatalogForm);
  $('#catalog-select-all').addEventListener('click', selectAllCatalog);
  $('#catalog-clear').addEventListener('click', () => {
    state.catalogSelection = new Set();
    syncCatalogChecks();
  });

  $$('.seg').forEach((node) => {
    node.addEventListener('click', () => setAddMode(node.dataset.addMode));
  });

  $('#course-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const selection = state.courseSelection;
    const errorBox = $('#course-error');
    if (!selection.course || !selection.resource) {
      errorBox.textContent = '请选择课程和教程';
      errorBox.hidden = false;
      return;
    }
    try {
      await api(`/api/tasks/${encodeURIComponent(state.courseTaskId)}/choose`, {
        method: 'POST',
        body: {
          course_id: selection.course.id,
          resource_id: selection.resource.id,
        },
      });
      $('#course-dialog').close();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  $('#debug-open').addEventListener('click', () => openDrawer('logs'));
  $('#debug-close').addEventListener('click', closeDrawer);
  $('#drawer-backdrop').addEventListener('click', closeDrawer);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && $('#debug-drawer').classList.contains('is-open')) {
      closeDrawer();
    }
  });

  $$('.tab').forEach((node) => {
    node.addEventListener('click', () => selectTab(node.dataset.tab));
  });

  $('#log-level').addEventListener('change', (event) => {
    state.logFilter.level = event.target.value;
    renderLogs();
  });
  $('#log-search').addEventListener('input', (event) => {
    state.logFilter.query = event.target.value.trim();
    renderLogs();
  });
  $('#log-autoscroll').addEventListener('change', () => {
    if ($('#log-autoscroll').checked) {
      const box = $('#log-list');
      box.scrollTop = box.scrollHeight;
    }
  });
  $('#log-clear').addEventListener('click', () => {
    state.logs = [];
    renderLogs();
  });
  $('#log-export').addEventListener('click', exportLogs);

  $('#net-method').addEventListener('change', (event) => {
    state.netFilter.method = event.target.value;
    renderNetwork();
  });
  $('#net-status').addEventListener('change', (event) => {
    state.netFilter.status = event.target.value;
    renderNetwork();
  });
  $('#net-clear').addEventListener('click', () => {
    state.network = [];
    renderNetwork();
  });

  $('#report-open').addEventListener('click', () => $('#report-modal').showModal());
  $('#report-download').addEventListener('click', downloadReport);

  $('#theme-toggle').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });

  $('#confirm-ok').addEventListener('click', () => {
    $('#confirm-dialog').close();
    if (confirmResolve) confirmResolve(true);
    confirmResolve = null;
  });
  $('#confirm-cancel').addEventListener('click', () => {
    $('#confirm-dialog').close();
    if (confirmResolve) confirmResolve(false);
    confirmResolve = null;
  });
  $('#confirm-dialog').addEventListener('close', () => {
    if (confirmResolve) confirmResolve(false);
    confirmResolve = null;
  });

  document.addEventListener('click', (event) => {
    const closer = event.target.closest('[data-close]');
    if (closer) {
      const dialog = closer.closest('dialog');
      if (dialog) dialog.close();
    }
  });
}

function exportLogs() {
  const lines = state.logs
    .filter(logMatches)
    .map((record) => `${new Date(record.ts).toISOString()} [${record.level}] [${record.task_id || '-'}] ${record.message}`);
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `unipus_logs_${Date.now()}.log`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadReport() {
  try {
    const response = await fetch('/api/report', { method: 'POST' });
    if (!response.ok) throw new Error('报告生成失败');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `unipus_report_${Date.now()}.zip`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('#report-modal').close();
    toast('报告已下载', 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ------------------------------------------------------------ 启动 */

async function boot() {
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(savedTheme || (prefersDark ? 'dark' : 'light'));

  bindEvents();
  renderTasks();

  try {
    const [tasks, credentials, logs, network] = await Promise.all([
      api('/api/tasks'),
      api('/api/credentials'),
      api('/api/logs?limit=2000'),
      api('/api/network?limit=500'),
    ]);
    state.tasks = new Map((tasks || []).map((task) => [task.id, task]));
    state.credentials = credentials || [];
    state.logs = logs || [];
    state.network = network || [];
  } catch (error) {
    toast(error.message, 'error');
  }

  renderTasks();
  renderCredentials();
  renderLogs();
  renderNetwork();
  connectWebSocket();
}

document.addEventListener('DOMContentLoaded', boot);
