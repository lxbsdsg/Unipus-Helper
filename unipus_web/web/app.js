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
  catalogNodeByKey: new Map(),
  catalogParentByKey: new Map(),
  catalogCurrentKey: null,
  catalogQuery: '',
  catalogFilter: 'all',
  catalogCollapsed: false,
  catalogGroupsOpen: new Map(),
  courseQuery: '',
  taskQuery: '',
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
  const allTasks = [...state.tasks.values()].sort((a, b) => a.id.localeCompare(b.id));
  const query = state.taskQuery.trim().toLowerCase();
  const tasks = query
    ? allTasks.filter((task) =>
        [task.name, task.username, task.user_name, task.school_name, task.description, task.id]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(query)
      )
    : allTasks;
  const list = $('#task-list');
  list.textContent = '';

  for (const task of tasks) {
    list.append(renderTask(task));
  }

  const hasTasks = allTasks.length > 0;
  $('#empty-state').hidden = hasTasks;
  $('#task-search-empty').hidden = !hasTasks || tasks.length > 0;

  const running = allTasks.filter((task) => task.status === 'RUNNING').length;
  const attention = allTasks.filter((task) =>
    ['NEED_OPERATION', 'ERROR'].includes(task.status)
  ).length;
  const completed = allTasks.filter((task) => task.status === 'COMPLETED').length;
  const taskValue = (id, value) => {
    const node = $(id);
    if (node) node.textContent = String(value);
  };
  taskValue('#summary-total', allTasks.length);
  taskValue('#summary-running', running);
  taskValue('#summary-attention', attention);
  taskValue('#summary-completed', completed);
  taskValue('#context-task-count', allTasks.length);
  $('#task-summary').textContent = hasTasks
    ? `${allTasks.length} 个任务 · ${running} 个运行中`
    : '0 个任务';
  renderContext(allTasks);
}

function renderContext(tasks) {
  let task = tasks.find((item) => item.status === 'RUNNING');
  if (!task) task = tasks.find((item) => item.status === 'NEED_OPERATION');
  if (!task) task = tasks.find((item) => item.status === 'ERROR');
  if (!task) task = tasks.find((item) => item.status === 'PAUSED');
  if (!task) task = tasks[0];

  const label = task ? task.name || task.username || task.id : '等待任务';
  const note = task
    ? task.description || [task.user_name, task.school_name].filter(Boolean).join(' · ') || task.id
    : '添加任务后，这里会显示当前学习进度。';
  const status = task ? task.status : 'READY';
  const tones = {
    RUNNING: 'running',
    NEED_OPERATION: 'attention',
    ERROR: 'error',
    COMPLETED: 'done',
  };
  const percent = task ? Math.max(0, Math.min(100, task.progress_percent || 0)) : 0;
  $('#context-state-label').textContent = label;
  $('#context-state-note').textContent = note;
  $('#context-state-dot').dataset.tone = tones[status] || 'idle';
  $('#context-progress').textContent = `${percent}%`;
  $('#context-count').textContent = task ? `${task.completed || 0} / ${task.total || 0}` : '0 / 0';
  $('#context-progress-fill').style.width = `${percent}%`;
  $('.context-meter').setAttribute('aria-valuenow', String(percent));
  $('#context-account').textContent = task ? task.username : '未添加';
  $('#context-log-count').textContent = `${state.logs.length} 条`;
  renderSidebarCounts();
}

function renderSidebarCounts() {
  const errors = state.logs.filter((record) =>
    ['ERROR', 'CRITICAL'].includes(record.level)
  ).length;
  $('#log-nav-count').textContent = String(errors);
  $('#net-nav-count').textContent = String(state.network.length);
  $('#credential-nav-count').textContent = String(state.credentials.length);
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
  state.courseQuery = '';
  $('#course-search').value = '';
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
  const query = state.courseQuery.trim().toLowerCase();
  const courses = selection.courses.filter((course) =>
    !query || (course.name || '').toLowerCase().includes(query)
  );
  $('#course-option-count').textContent = `${courses.length} 门`;

  if (!selection.courses.length) {
    courseBox.append(el('div', 'saved-empty', '没有可选课程'));
    $('#resource-option-count').textContent = '0 个';
    return;
  }
  if (!courses.length) {
    courseBox.append(el('div', 'saved-empty', '没有匹配的课程'));
  }

  for (const course of courses) {
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
  const query = state.courseQuery.trim().toLowerCase();
  const resources = selection.course
    ? (selection.course.resources || []).filter((resource) =>
        !query || (resource.name || '').toLowerCase().includes(query)
      )
    : [];
  $('#resource-option-count').textContent = `${resources.length} 个`;

  if (!resources.length) {
    let message = '先选择左侧课程';
    if (selection.course) {
      message = (selection.course.resources || []).length
        ? '没有匹配的教程'
        : '该课程没有教程';
    }
    box.append(el('div', 'saved-empty', message));
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
  state.catalogNodeByKey = new Map();
  state.catalogParentByKey = new Map();
  state.catalogCurrentKey = null;
  state.catalogQuery = '';
  state.catalogFilter = 'all';
  state.catalogCollapsed = false;
  state.catalogGroupsOpen = new Map();
  $('#catalog-collapse').setAttribute('aria-label', '收起全部目录');
  $('#catalog-collapse').title = '收起全部目录';
  $('#catalog-error').hidden = true;
  $('#catalog-tree').textContent = '';
  $('#catalog-summary').textContent = '正在加载…';
  $('#catalog-search').value = '';
  $('#catalog-filter').value = 'all';
  $('#catalog-start').disabled = true;
  renderCatalogContext();

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

function indexCatalog(node, parentKey = null) {
  const leaves = [];
  const children = node.children || [];
  const key = catalogNodeKey(node);
  state.catalogNodeByKey.set(key, node);
  state.catalogParentByKey.set(key, parentKey);
  if (children.length) {
    for (const child of children) leaves.push(...indexCatalog(child, key));
  } else if (node.selectable) {
    leaves.push(node.id);
  }
  state.catalogLeavesById.set(key, leaves);
  return leaves;
}

function renderCatalogTree(tree) {
  state.catalogLeavesById = new Map();
  state.catalogSelection = new Set();
  state.catalogNodeByKey = new Map();
  state.catalogParentByKey = new Map();
  state.catalogCurrentKey = null;

  const units = (tree && tree.units) || [];
  $('#catalog-unit-count').textContent = `${units.length} 个单元`;
  renderCatalogContext();
  if (!units.length) {
    const box = $('#catalog-tree');
    box.textContent = '';
    box.append(el('div', 'saved-empty', '这个教程没有可用的题目目录'));
    renderCatalogItems();
    syncCatalogChecks();
    return;
  }

  for (const unit of units) indexCatalog(unit);
  state.catalogCurrentKey = catalogNodeKey(units[0]);
  renderCatalogNavigation(true);
  syncCatalogChecks();
}

function catalogIsLeaf(node) {
  return !(node.children || []).length;
}

function catalogStatus(node) {
  const finish = Number(node.finish_progress || 0);
  if (finish >= 100) return 'done';
  if (node.selectable) return 'open';
  if (!node.status_known) return 'unknown';
  return 'blocked';
}

function catalogMatches(node) {
  if (catalogIsLeaf(node)) {
    const filter = state.catalogFilter;
    const filterMatch =
      filter === 'all' ||
      catalogStatus(node) === filter ||
      (filter === 'open' && catalogStatus(node) === 'unknown');
    if (!filterMatch) return false;
  }
  const query = state.catalogQuery.trim().toLowerCase();
  return !query || catalogLabel(node).toLowerCase().includes(query);
}

function catalogChecked(key) {
  const leaves = state.catalogLeavesById.get(key) || [];
  const selected = leaves.filter((id) => state.catalogSelection.has(id)).length;
  return {
    leaves,
    selected,
    checked: leaves.length > 0 && selected === leaves.length,
    indeterminate: selected > 0 && selected < leaves.length,
  };
}

function catalogNodeCheckbox(node, onChange) {
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'catalog-check';
  checkbox.dataset.nodeId = catalogNodeKey(node);
  checkbox.setAttribute('aria-label', `${catalogLabel(node)}，选择全部可练习题目`);
  checkbox.disabled = !(state.catalogLeavesById.get(checkbox.dataset.nodeId) || []).length;
  checkbox.addEventListener('click', (event) => event.stopPropagation());
  checkbox.addEventListener('change', () => {
    onChange(checkbox.checked);
    syncCatalogChecks();
  });
  return checkbox;
}

function setCatalogGroupSelection(node, checked) {
  const leafIds = new Set(state.catalogLeavesById.get(catalogNodeKey(node)) || []);
  const visibleLeaves = catalogDescendantLeaves(node)
    .filter((leaf) => catalogMatches(leaf))
    .map((leaf) => leaf.id)
    .filter((leafId) => leafIds.has(leafId));
  for (const leafId of visibleLeaves) {
    if (checked) state.catalogSelection.add(leafId);
    else state.catalogSelection.delete(leafId);
  }
}

function renderCatalogNavigation(preserveSelection = false) {
  const box = $('#catalog-tree');
  box.textContent = '';
  const units = (state.catalog && state.catalog.units) || [];
  const visibleUnits = units.filter(catalogMatches);
  $('#catalog-nav-empty').hidden = visibleUnits.length > 0;
  $('#catalog-unit-count').textContent = `${visibleUnits.length} 个单元`;
  if (!visibleUnits.length) {
    renderCatalogItems();
    return;
  }
  for (const unit of visibleUnits) box.append(renderCatalogNode(unit, 0));
  renderCatalogItems();
  syncCatalogChecks(preserveSelection);
}

function renderCatalogNode(node, depth) {
  const children = node.children || [];
  const row = el('div', 'catalog-row');
  const nodeKey = catalogNodeKey(node);

  if (children.length) {
    row.classList.add('catalog-group-row');
    const leaves = state.catalogLeavesById.get(nodeKey) || [];
    const details = document.createElement('details');
    details.className = 'catalog-group';
    details.dataset.nodeKey = nodeKey;
    details.open = state.catalogQuery.trim() || state.catalogGroupsOpen.get(nodeKey) ||
      state.catalogFilter !== 'all' ||
      (!state.catalogCollapsed && (state.catalogCurrentKey === nodeKey ||
        isCatalogAncestor(nodeKey, state.catalogCurrentKey) || depth === 0));

    const summary = document.createElement('summary');
    summary.style.setProperty('--depth', String(depth));
    summary.classList.toggle('is-current', state.catalogCurrentKey === nodeKey);
    const checkbox = catalogNodeCheckbox(node, (checked) =>
      setCatalogGroupSelection(node, checked)
    );
    summary.append(checkbox, el('span', 'catalog-name', catalogLabel(node)));
    summary.append(el('span', 'catalog-count', `${leaves.length} 题`));
    summary.addEventListener('click', (event) => {
      if (event.target.closest('.catalog-check')) return;
      event.preventDefault();
      details.open = true;
      state.catalogGroupsOpen.set(nodeKey, true);
      for (let ancestor = state.catalogParentByKey.get(nodeKey); ancestor;
        ancestor = state.catalogParentByKey.get(ancestor)) {
        state.catalogGroupsOpen.set(ancestor, true);
      }
      selectCatalogNode(nodeKey, false);
    });

    details.append(summary);
    const childBox = el('div', 'catalog-children');
    for (const child of children) {
      if (catalogMatches(child)) childBox.append(renderCatalogNode(child, depth + 1));
    }
    details.append(childBox);
    row.append(details);
    return row;
  }

  const selectable = Boolean(node.selectable);
  const finish = Number(node.finish_progress || 0);
  row.classList.add('catalog-leaf-row');
  row.classList.toggle('is-complete', finish >= 100);
  row.classList.toggle('is-unsupported', !selectable && finish < 100);
  row.style.setProperty('--depth', String(depth));
  const checkbox = catalogNodeCheckbox(node, (checked) => {
    if (checked) state.catalogSelection.add(node.id);
    else state.catalogSelection.delete(node.id);
  });

  row.append(checkbox, el('span', 'catalog-name', catalogLabel(node)));
  row.append(el('span', 'catalog-meta', node.status_known && finish >= 100 ? '已完成' : ''));
  return row;
}

function isCatalogAncestor(ancestorKey, nodeKey) {
  let current = nodeKey;
  while (current) {
    if (current === ancestorKey) return true;
    current = state.catalogParentByKey.get(current);
  }
  return false;
}

function selectCatalogNode(key, shouldScroll = true) {
  const node = state.catalogNodeByKey.get(key);
  if (!node) return;
  state.catalogCurrentKey = key;
  renderCatalogNavigation();
  renderCatalogItems();
  if (shouldScroll) {
    const summary = [...$$('.catalog-group > summary', $('#catalog-tree'))]
      .find((item) => item.parentElement.dataset.nodeKey === key);
    if (summary) summary.scrollIntoView({ block: 'nearest' });
  }
}

function renderCatalogContext() {
  const task = state.tasks.get(state.catalogTaskId);
  const name = task ? task.name || task.course_name || task.username || task.id : '当前任务';
  $('#catalog-context').textContent = name;
}

function catalogPathKeys(key) {
  const keys = [];
  let current = key;
  while (current) {
    keys.unshift(current);
    current = state.catalogParentByKey.get(current);
  }
  return keys;
}

function catalogDescendantLeaves(node, leaves = []) {
  const children = node.children || [];
  if (!children.length) {
    leaves.push(node);
    return leaves;
  }
  for (const child of children) catalogDescendantLeaves(child, leaves);
  return leaves;
}

function renderCatalogPath() {
  const box = $('#catalog-path');
  box.textContent = '';
  const keys = catalogPathKeys(state.catalogCurrentKey);
  keys.forEach((key, index) => {
    if (index) box.append(el('span', 'catalog-path-separator', '/'));
    const node = state.catalogNodeByKey.get(key);
    if (!node) return;
    const crumb = button(catalogLabel(node), null, () => selectCatalogNode(key, false));
    crumb.setAttribute('aria-current', index === keys.length - 1 ? 'location' : 'false');
    box.append(crumb);
  });
}

function catalogLeafParts(node) {
  const parts = [];
  const types = (node.bases || []).map((raw) => TYPE_LABEL[raw] || raw).join('、');
  if (types) parts.push(types);
  if (node.question_num > 1) parts.push(`${node.question_num} 小题`);
  return parts;
}

function renderCatalogItems() {
  const box = $('#catalog-items');
  box.textContent = '';
  const current = state.catalogNodeByKey.get(state.catalogCurrentKey);
  renderCatalogPath();
  const leaves = current ? catalogDescendantLeaves(current) : [];
  const visible = leaves.filter(catalogMatches);
  $('#catalog-item-count').textContent = `${visible.length} 道题目`;
  $('#catalog-items-empty').hidden = visible.length > 0;

  for (const child of visible) {
    const row = el('div', 'catalog-leaf-row');
    row.classList.toggle('is-complete', catalogStatus(child) === 'done');
    row.classList.toggle('is-unsupported', !child.selectable && catalogStatus(child) !== 'done');
    const checkbox = catalogNodeCheckbox(child, (checked) => {
      if (checked) state.catalogSelection.add(child.id);
      else state.catalogSelection.delete(child.id);
    });
    const details = el('div', 'catalog-item-details');
    details.append(el('span', 'catalog-name', catalogLabel(child)));
    const path = catalogPathKeys(catalogNodeKey(child)).slice(0, -1).map((key) => {
      const ancestor = state.catalogNodeByKey.get(key);
      return ancestor ? catalogLabel(ancestor) : '';
    }).filter(Boolean).join(' / ');
    const facts = catalogLeafParts(child);
    facts.unshift(path);
    details.append(el('span', 'catalog-item-types', facts.filter(Boolean).join(' · ')));

    const meta = el('div', 'catalog-meta');
    const status = el('span', 'catalog-status');
    const statusKey = catalogStatus(child);
    status.dataset.status = statusKey;
    status.textContent = {
      open: '可练习',
      done: '已完成',
      blocked: '不可练习',
      unknown: '状态未知',
    }[statusKey];
    meta.append(status);
    if (!child.selectable) {
      const reason = child.select_reason || child.reason || child.skip_reason;
      if (reason) meta.append(el('span', 'catalog-block-reason', String(reason)));
    }
    row.append(checkbox, details, meta);
    box.append(row);
  }
  syncCatalogChecks();
}

function syncCatalogChecks(preserveSelection = true) {
  $$('.catalog-check', $('#catalog-tree')).forEach((checkbox) => {
    const key = checkbox.dataset.nodeId;
    const node = state.catalogNodeByKey.get(key);
    const visibleLeaves = node ? catalogDescendantLeaves(node).filter(catalogMatches) : [];
    const visibleResult = {
      leaves: visibleLeaves,
      selected: visibleLeaves.filter((leaf) => state.catalogSelection.has(leaf.id)).length,
    };
    visibleResult.checked =
      visibleResult.leaves.length > 0 && visibleResult.selected === visibleResult.leaves.length;
    visibleResult.indeterminate = visibleResult.selected > 0 &&
      visibleResult.selected < visibleResult.leaves.length;
    const result = visibleResult;
    const leaves = result.leaves;
    if (!leaves.length) {
      checkbox.checked = false;
      checkbox.indeterminate = false;
      checkbox.disabled = true;
      return;
    }
    checkbox.checked = result.checked;
    checkbox.indeterminate = result.indeterminate;
  });

  $$('.catalog-check', $('#catalog-items')).forEach((checkbox) => {
    const result = catalogChecked(checkbox.dataset.nodeId);
    checkbox.checked = result.checked;
    checkbox.indeterminate = result.indeterminate;
    checkbox.disabled = result.leaves.length === 0;
  });

  const current = state.catalogNodeByKey.get(state.catalogCurrentKey);
  if (current) {
    const result = catalogChecked(state.catalogCurrentKey);
    const selectCurrent = $('#catalog-select-current');
    selectCurrent.checked = result.checked;
    selectCurrent.indeterminate = result.indeterminate;
    const selectableLeaves = catalogDescendantLeaves(current).filter((leaf) => leaf.selectable).length;
    const filteredLeaves = catalogDescendantLeaves(current).filter(catalogMatches);
    selectCurrent.disabled = selectableLeaves === 0;
    $('#catalog-current-total').textContent =
      `${filteredLeaves.length} 道符合筛选 · 共 ${selectableLeaves} 道可练习`;
  }

  const count = state.catalogSelection.size;
  $('#catalog-summary').textContent = `已选 ${count} 道题`;
  $('#catalog-start').disabled = count === 0;
}

function selectAllCatalog() {
  for (const node of state.catalogNodeByKey.values()) {
    if (catalogIsLeaf(node) && node.selectable && catalogMatches(node)) {
      state.catalogSelection.add(node.id);
    }
  }
  syncCatalogChecks();
}

function toggleCatalogCurrent(checked) {
  const current = state.catalogNodeByKey.get(state.catalogCurrentKey);
  if (current) {
    // 只影响当前过滤视图内可见的题目，保留其它筛选条件下已勾选的题目
    for (const leaf of catalogDescendantLeaves(current).filter(catalogMatches)) {
      if (!leaf.selectable) continue;
      if (checked) state.catalogSelection.add(leaf.id);
      else state.catalogSelection.delete(leaf.id);
    }
  }
  syncCatalogChecks();
}

function collapseCatalog() {
  state.catalogCollapsed = !state.catalogCollapsed;
  const expand = !state.catalogCollapsed;
  $$('.catalog-group', $('#catalog-tree')).forEach((details) => {
    if (expand) details.open = true;
  });
  if (state.catalogCollapsed) {
    $$('#catalog-tree > .catalog-row > .catalog-group').forEach((details) => {
      details.open = true;
    });
  }
  $('#catalog-collapse').setAttribute(
    'aria-label',
    state.catalogCollapsed ? '展开全部目录' : '收起全部目录'
  );
  $('#catalog-collapse').title = state.catalogCollapsed ? '展开全部目录' : '收起全部目录';
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
  renderSidebarCounts();

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
  renderSidebarCounts();
}

function appendLog(record) {
  state.logs.push(record);
  if (state.logs.length > 5000) state.logs.splice(0, state.logs.length - 5000);
  $('#context-log-count').textContent = `${state.logs.length} 条`;
  renderSidebarCounts();
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
  renderSidebarCounts();
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
  $$('[data-nav]').forEach((node) => {
    const active = node.dataset.nav === tab;
    node.classList.toggle('is-active', active);
    if (active) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
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
  const current = $('[data-nav][aria-current="page"]');
  if (current && current.dataset.nav !== 'tasks') {
    $$('[data-nav]').forEach((node) => {
      const active = node.dataset.nav === 'tasks';
      node.classList.toggle('is-active', active);
      if (active) node.setAttribute('aria-current', 'page');
      else node.removeAttribute('aria-current');
    });
  }
  $('#page-label').textContent = '任务总览';
  $('#workspace-title').textContent = '任务总览';
  $('#workspace-description').textContent = '统一管理课程任务与学习进度';
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

function openNavigation(tab) {
  $$('[data-nav]').forEach((node) => {
    const active = node.dataset.nav === tab;
    node.classList.toggle('is-active', active);
    if (active) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
  if (tab === 'logs' || tab === 'network') {
    openDrawer(tab);
    return;
  }
  if (tab === 'accounts') {
    openAddDialog();
    setAddMode('saved');
    return;
  }
  $('#page-label').textContent = '任务总览';
  $('#workspace-title').textContent = '任务总览';
  $('#workspace-description').textContent = '统一管理课程任务与学习进度';
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
  $('#task-search').addEventListener('input', (event) => {
    state.taskQuery = event.target.value;
    renderTasks();
  });
  $$('[data-nav]').forEach((node) => {
    node.addEventListener('click', () => openNavigation(node.dataset.nav));
  });

  $('#catalog-form').addEventListener('submit', submitCatalogForm);
  $('#catalog-select-all').addEventListener('click', selectAllCatalog);
  $('#catalog-clear').addEventListener('click', () => {
    state.catalogSelection = new Set();
    syncCatalogChecks();
  });
  $('#catalog-select-current').addEventListener('change', (event) => {
    toggleCatalogCurrent(event.target.checked);
  });
  $('#catalog-collapse').addEventListener('click', collapseCatalog);
  $('#catalog-search').addEventListener('input', (event) => {
    state.catalogQuery = event.target.value;
    renderCatalogNavigation();
  });
  $('#catalog-filter').addEventListener('change', (event) => {
    state.catalogFilter = event.target.value;
    renderCatalogNavigation();
  });
  $('#course-search').addEventListener('input', (event) => {
    state.courseQuery = event.target.value;
    renderCourseOptions();
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
