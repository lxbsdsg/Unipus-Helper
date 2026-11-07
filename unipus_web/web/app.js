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
  practiceTaskId: null,
  durationTaskId: null,
  durationTargetTaskId: null,
  durationTargetSelection: null,
  durationTargetUnitSelection: null,
  durationTargetExpanded: null,
  courseSelection: { course: null, resource: null, courses: [], loaded: false },
  courseLoading: false,
  courseRequestId: 0,
  durationCoursePoll: 0,
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
  stageTaskId: null,
  stageView: 'empty',
  courseSubmitting: false,
  catalogSubmitting: false,
  durationGoingBack: false,
  scrollStageOnNextForm: false,
  ws: null,
  reconnectDelay: 1000,
};// 运行参数保持产品默认值；E2E 通过 window.UNIPUS_UI_TIMING 缩短轮询时间。
const UI_TIMING = Object.assign(
  {
    durationCoursePollIntervalMs: 1000,
    durationCoursePollAttempts: 60,
  },
  window.UNIPUS_UI_TIMING || {},
);



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

function formatDuration(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(value / 60)}分${String(value % 60).padStart(2, '0')}秒`;
}

function progressValue(task, value) {
  return task && task.practice_mode === 'duration' ? formatDuration(value) : String(value || 0);
}

function taskProgress(task) {
  return `${progressValue(task, task.completed)} / ${progressValue(task, task.total)}`;
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
  taskValue('#context-task-count', allTasks.length);
  $('#task-summary').textContent = hasTasks
    ? `${allTasks.length} 个任务 · ${running} 个运行中`
    : '0 个任务';
  renderStage();
  renderContext(allTasks);
}

function taskMode(task) {
  if (!task) return null;
  if (task.status === 'READY') return 'choose';
  return task.practice_mode === 'duration' ? 'duration' : 'practice';
}

function taskStatusLabel(task) {
  return (STATUS[task.status] || { label: task.status || '未知' }).label;
}

function taskProgressText(task) {
  if (!task) return '0 / 0';
  return task.practice_mode === 'duration'
    ? `${progressValue(task, task.completed)} / ${progressValue(task, task.total)}`
    : `${task.completed || 0} / ${task.total || 0}`;
}

function setStage(taskId, view) {
  state.stageTaskId = taskId || null;
  if (taskId) state.activeTaskId = taskId;
  const task = taskId ? state.tasks.get(taskId) : null;
  state.stageView = view || (task ? taskMode(task) : 'empty');
  renderStage();
}

// 进入某个设置步骤：挂载表单并让左侧模式/步骤栏保持同步（不重绘中间工作区）。
function enterStage(taskId, view, formId, host = null, options = {}) {
  state.stageTaskId = taskId;
  state.activeTaskId = taskId;
  state.stageView = view;
  const form = mountStageForm(formId, host, options);
  const task = taskId ? state.tasks.get(taskId) : null;
  if (task) {
    $('#stage-kicker').textContent = '当前进度';
    $('#stage-title').textContent = task.name || task.username || task.id;
    $('#stage-subtitle').textContent = [task.user_name, task.school_name, task.id]
      .filter(Boolean)
      .join(' · ');
    renderStageActions(task);
    renderStageProgress(task);
    renderRailModes(task);
  }
  return form;
}

function stageViewForTask(task) {
  if (!task) return 'empty';
  if (task.status === 'READY') {
    return state.stageView === 'practice' || state.stageView === 'duration'
      ? state.stageView
      : 'modes';
  }
  if (task.status === 'NEED_OPERATION') {
    if (task.user_operation === 'CHOOSE_PRACTICE') return 'catalog';
    if (task.user_operation === 'CHOOSE_DURATION') return 'duration-target';
    return 'course';
  }
  return task.practice_mode === 'duration' ? 'running-duration' : 'running-practice';
}

function stageTask() {
  return state.stageTaskId ? state.tasks.get(state.stageTaskId) || null : null;
}

function renderStage() {
  const task = stageTask();
  const content = $('#stage-content');
  const empty = $('#workbench-empty');
  if (!task) {
    content.hidden = true;
    empty.hidden = false;
    const modeOptions = $('#mode-options');
    if (modeOptions) modeOptions.textContent = '';
    return;
  }
  content.hidden = false;
  empty.hidden = true;
  // 先按任务状态归一化步骤，再渲染左侧栏，避免读到上一次流程的 stageView。
  state.stageView = stageViewForTask(task);
  renderRailModes(task);
  $('#stage-kicker').textContent = task.status === 'READY' ? '选择模式' : '当前进度';
  $('#stage-title').textContent = task.name || task.username || task.id;
  $('#stage-subtitle').textContent = [task.user_name, task.school_name, task.id]
    .filter(Boolean)
    .join(' · ');
  renderStageActions(task);
  renderStageProgress(task);
  renderStageBody(task);
}

// 左侧栏：待开始任务给出模式入口，进行中的任务展示当前处于哪一步。
function renderRailModes(task) {
  const modeOptions = $('#mode-options');
  if (!modeOptions) return;
  modeOptions.textContent = '';
  // 用户已显式选择模式后，左侧改为展示该模式的流程步骤，不再重复弹出模式按钮。
  const chosenMode = state.stageView === 'practice' || state.stageView === 'duration'
    || state.stageView === 'catalog' || state.stageView === 'course'
    || state.stageView === 'duration-target';
  if (task.status === 'READY' && !chosenMode) {
    renderModePicker(task, modeOptions);
    return;
  }
  // 任务已记录 practice_mode 时以它为准；仅用户刚点选、尚未落库时才用 stageView。
  const mode = task.practice_mode === 'duration' || state.stageView === 'duration'
    ? 'duration'
    : task.practice_mode === 'catalog' || state.stageView === 'catalog'
      ? 'catalog'
      : 'practice';
  const steps = mode === 'duration'
    ? ['选择课程与教程', '选择计时内容', '设置每项时长', '后台累计时长']
    : mode === 'catalog'
      ? ['选择刷题范围', '选择课程与教程', '勾选练习题目', '后台完成题目']
      : ['选择刷题范围', '选择课程与教程', '后台完成必修'];
  const currentStep =
    task.status === 'READY'
      ? 0
      : task.status === 'NEED_OPERATION'
      ? task.user_operation === 'CHOOSE_PRACTICE' ? 2 : 1
      : task.status === 'RUNNING'
        ? mode === 'duration'
          // 读取目录时仍停在“选择计时内容”，避免进度条跳到已完成的最后一步。
          ? ((task.selected_duration_targets || []).length ? steps.length - 1 : 1)
          : steps.length - 1
        : steps.length - 1;
  for (const [index, label] of steps.entries()) {
    const node = el('div', 'rail-step', label);
    node.classList.toggle('is-active', index === currentStep);
    node.classList.toggle('is-done', index < currentStep);
    modeOptions.append(node);
  }
}

function renderStageActions(task) {
  const box = $('#stage-actions');
  box.textContent = '';
  if (task.status === 'NEED_OPERATION' && task.user_operation === 'CHOOSE_DURATION') {
    const back = button('返回课程', 'btn btn-ghost btn-sm', () => backToCourseSelection(task.id));
    back.dataset.action = 'back-course';
    back.dataset.id = task.id;
    box.append(back);
  }
  const add = (label, action, className = 'btn btn-ghost btn-sm') => {
    const node = button(label, className, () => runTaskAction(task.id, action));
    node.dataset.action = action;
    node.dataset.id = task.id;
    box.append(node);
  };
  if (task.status === 'RUNNING' || task.status === 'WAITING') {
    add('暂停', 'pause');
    add('停止', 'stop');
  } else if (task.status === 'PAUSED') {
    add('恢复', 'resume', 'btn btn-primary btn-sm');
    add('停止', 'stop');
  } else if (task.status === 'ERROR' || task.status === 'COMPLETED') {
    add('重试', 'restart', 'btn btn-primary btn-sm');
  } else if (task.status === 'NEED_OPERATION') {
    add('暂停', 'pause');
  }
  if (task.status === 'READY' && state.stageView === 'practice') {
    const back = button('重选模式', 'btn btn-ghost btn-sm', () => setStage(task.id, 'modes'));
    back.dataset.action = 'remode';
    back.dataset.id = task.id;
    box.append(back);
  }
  add('管理', 'manage', 'btn-link');
}

function renderStageProgress(task) {
  const box = $('#stage-progress');
  box.textContent = '';
  const percent = Math.max(0, Math.min(100, task.progress_percent || 0));
  const tone = ['RUNNING', 'WAITING', 'NEED_OPERATION'].includes(task.status)
    ? 'running'
    : task.status === 'ERROR'
      ? 'error'
      : task.status === 'COMPLETED'
        ? 'done'
        : 'idle';

  const summary = el('div', 'stage-progress-summary');
  const metric = el('div', 'stage-metric');
  metric.append(el('span', 'stage-metric-label', task.practice_mode === 'duration' ? '学习时长' : '题目进度'));
  metric.append(el('strong', null, taskProgressText(task)));
  metric.append(el('span', 'stage-metric-note',
    task.practice_mode === 'duration'
      ? `每项 ${task.duration_param || '—'} 秒`
      : (task.description || '等待任务更新')));
  summary.append(metric);

  const status = el('div', 'stage-status');
  status.dataset.tone = tone;
  status.append(el('span', 'stage-status-dot'), el('strong', null, taskStatusLabel(task)));
  status.append(el('span', null, task.description || ''));
  summary.append(status);
  box.append(summary);

  const ruler = el('div', 'ruler stage-ruler');
  ruler.setAttribute('role', 'progressbar');
  ruler.setAttribute('aria-valuemin', '0');
  ruler.setAttribute('aria-valuemax', '100');
  ruler.setAttribute('aria-valuenow', String(percent));
  const fill = el('span', 'ruler-fill');
  fill.style.width = `${percent}%`;
  ruler.append(fill);
  const numbers = el('div', 'progress-numbers stage-progress-numbers');
  numbers.append(el('strong', null, `${percent}%`));
  numbers.append(el('span', null, task.practice_mode === 'duration' ? '已累计时长' : '完成题数'));
  numbers.append(el('span', 'pct', task.practice_mode === 'duration'
    ? `目标 ${progressValue(task, task.total)}`
    : `共 ${task.total || 0} 题`));
  box.append(ruler, numbers);
}

function renderStageBody(task) {
  const body = $('#stage-body');
  const nextView = stageViewForTask(task);
  // 同一任务的同一设置步骤只重绘进度，不重建表单，避免实时更新清空用户正在做的选择。
  const courseListPending = nextView === 'course'
    && state.courseTaskId === task.id
    && !state.courseSelection.loaded
    && !state.courseLoading;
  if (
    state.stageView === nextView &&
    body.dataset.view === nextView &&
    body.dataset.taskId === task.id &&
    body.firstElementChild &&
    !courseListPending
  ) {
    return;
  }
  state.stageView = nextView;
  body.dataset.view = nextView;
  body.dataset.taskId = task.id;
  recycleStageForms(body);
  body.textContent = '';
  // 手机端：切换到表单步骤时自动滚到工作台（空状态/运行态不滚动）
  const isFormView = ['practice', 'course', 'duration-target', 'catalog'].includes(nextView);
  if (isFormView && window.matchMedia('(max-width: 820px)').matches) {
    requestAnimationFrame(() => $('.stage')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }
  // 表单模板常驻在 #stage-templates，这里只做挂载；加载态交给具体步骤渲染。
  const openForm = (id, loader) => {
    mountStageForm(id, body);
    if (loader) loader();
  };
  if (task.status === 'NEED_OPERATION') {
    if (nextView === 'catalog') {
      openForm('catalog-form');
      openCatalog(task.id);
      return;
    }
    if (nextView === 'duration-target') {
      openDurationTarget(task.id);
      return;
    }
    openCourse(task.id);
    return;
  }
  if (task.status === 'READY') {
    if (nextView === 'practice') {
      openForm('practice-form');
      updatePracticeHint();
      return;
    }
    if (nextView === 'duration') {
      const pending = el('section', 'stage-running');
      pending.append(el('h3', null, '正在准备时长任务'));
      pending.append(el('p', null, '正在加载课程与教程，请稍候。'));
      body.append(pending);
      return;
    }
    const guide = el('section', 'stage-guide');
    guide.append(el('h3', null, '在左侧选择任务模式'));
    guide.append(el('p', null, '刷正确率会完成必修或自选题目；刷时长会累计课程学习时长。'));
    body.append(guide);
    return;
  }
  const mode = task.practice_mode === 'duration' ? '刷时长' : '刷题';
  // 刷时长在选完课程后会短暂进入运行态去读取目录，随后才出现计时内容选择。
  const waitingDurationTargets = task.practice_mode === 'duration'
    && task.status === 'RUNNING'
    && !(task.selected_duration_targets || []).length
    && !(task.selected_duration_target || null);
  const panel = el('section', 'stage-running');
  const heading = task.status === 'ERROR'
    ? '任务中断'
    : waitingDurationTargets
      ? (task.description || '正在读取计时目录')
      : '任务运行中';
  panel.append(el('h3', null, heading));
  if (task.status === 'ERROR') {
    panel.append(el('p', null, task.error || task.description || '任务发生错误'));
  } else if (waitingDurationTargets) {
    const description = task.description || '正在读取课程的可计时内容。';
    if (description !== heading) panel.append(el('p', null, description));
    panel.append(el('p', 'hint', '读取完成后会自动进入下一步，无需刷新页面。'));
  } else {
    panel.append(el('p', null, `${mode}正在后台运行，进度和日志会实时更新。`));
  }
  if (task.practice_mode === 'catalog' && task.status === 'RUNNING') {
    const selected = el('p', 'hint', task.description || '正在处理已选题目');
    panel.append(selected);
  }
  body.append(panel);
}

function recycleStageForms(scope = document) {
  const templates = $('#stage-templates');
  if (!templates) return;
  for (const form of $$('.stage-form', scope)) {
    if (!templates.contains(form)) templates.append(form);
  }
}

function mountStageForm(id, host = null, options = {}) {
  const form = document.getElementById(id);
  if (!form) return null;
  const target = host || $('#stage-body');
  // 表单是常驻模板：切换视图前先放回模板区，绝不能随中间工作区一起被删除。
  recycleStageForms();
  target.textContent = '';
  form.hidden = false;
  target.append(form);
  if (target === $('#stage-body')) {
    target.dataset.view = state.stageView;
    target.dataset.taskId = state.stageTaskId || '';
    const shouldScrollStage = options.scrollIntoView === true || state.scrollStageOnNextForm;
    state.scrollStageOnNextForm = false;
    if (shouldScrollStage && window.matchMedia('(max-width: 820px)').matches) {
      $('.stage')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
  return form;
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
  $('#context-count').textContent = task ? taskProgress(task) : '0 / 0';
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
  const row = el('button', 'rail-task');
  row.type = 'button';
  row.dataset.status = task.status;
  row.dataset.id = task.id;
  row.classList.toggle('is-active', state.stageTaskId === task.id);
  row.setAttribute('aria-pressed', state.stageTaskId === task.id ? 'true' : 'false');
  row.addEventListener('click', () => setStage(task.id));

  const main = el('div', 'rail-task-main');
  const titleRow = el('div', 'task-title-row');
  titleRow.append(el('span', 'task-name', task.name || task.username || task.id));

  const badge = el('span', 'status', (STATUS[task.status] || { label: task.status }).label);
  badge.dataset.tone = task.status;
  titleRow.append(badge);
  main.append(titleRow);

  const meta = [task.user_name, task.school_name].filter(Boolean).join(' · ');
  if (meta) main.append(el('p', 'task-meta', meta));

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

  const numbers = el('div', 'progress-numbers');
  numbers.append(el('strong', null, task.practice_mode === 'duration'
    ? progressValue(task, task.completed)
    : `${task.completed || 0} / ${task.total || 0}`));
  numbers.append(el('span', 'pct', `${percent}%`));
  row.append(main, ruler, numbers);
  return row;
}

function renderModePicker(task, host = null) {
  const box = host || $('#mode-options');
  box.textContent = '';
  const choices = [
    {
      mode: 'practice',
      title: '刷正确率',
      description: '完成必修题，或从完整目录选择未完成题目。',
      action: 'practice',
    },
    {
      mode: 'duration',
      title: '刷时长',
      description: '选择课程和计时内容，累计学习时长。',
      action: 'duration',
    },
  ];
  for (const choice of choices) {
    const node = button(null, 'mode-option', () => runTaskAction(task.id, choice.action));
    node.dataset.mode = choice.mode;
    node.dataset.id = task.id;
    node.append(el('strong', null, choice.title), el('span', null, choice.description));
    box.append(node);
  }
}

function taskChoices(task, onAction) {
  if (!['READY', 'NEED_OPERATION'].includes(task.status)) return null;
  const section = el('section', 'task-choices');
  section.setAttribute('aria-label', task.status === 'READY' ? '选择任务类型' : '继续设置任务');
  section.append(el('h4', 'choice-heading', task.status === 'READY' ? '选择任务类型' : '下一步'));
  const choices = el('div', 'choice-grid');
  const add = (title, description, next, action) => {
    const card = button(null, 'choice-card', () => onAction(action));
    card.dataset.action = action;
    card.dataset.id = task.id;
    card.append(el('strong', 'choice-title', title), el('span', 'choice-description', description),
      el('span', 'choice-next', `${next} →`));
    choices.append(card);
  };
  if (task.status === 'READY') {
    add('刷正确率', '完成老师布置的必修内容，或从完整目录中自选未完成题目。',
      '展开刷题设置', 'practice');
    add('刷时长', '先选课程，再选计时内容与每个练习时长（固定秒数或随机范围）。',
      '展开时长设置', 'duration');
  } else if (task.user_operation === 'CHOOSE_PRACTICE') {
    add('选择要刷的题目', '按单元或小节勾选题目，查看已选数量后确认开始。', '打开题目选择', 'catalog');
  } else if (task.user_operation === 'CHOOSE_DURATION') {
    add('选择计时内容与时长', `${task.duration_targets?.length || 0} 个学习内容可累计时长。`, '打开内容选择', 'duration-target');
  } else {
    add('选择课程与教程', task.practice_mode === 'duration'
      ? '选择课程和教程后，继续选择计时内容。'
      : task.practice_mode === 'catalog'
        ? '先选课程和教程，再进入目录选择题目。'
        : '先选课程和教程，确认后开始完成未完成的必修内容。', '打开课程选择', 'choose');
  }
  section.append(choices);
  return section;
}

async function runTaskAction(taskId, action) {
  if (action === 'manage') {
    openManage(taskId);
    return;
  }
  if (action === 'choose') {
    state.scrollStageOnNextForm = true;
    openCourse(taskId, { mounted: true, scrollIntoView: true });
    return;
  }
  if (action === 'practice') {
    state.scrollStageOnNextForm = true;
    openPracticeSetup(taskId, { mounted: true });
    return;
  }
  if (action === 'duration') {
    state.scrollStageOnNextForm = true;
    setStage(taskId, 'duration');
    startDuration(taskId);
    return;
  }
  if (action === 'duration-target') {
    state.scrollStageOnNextForm = true;
    openDurationTarget(taskId, { mounted: true });
    return;
  }
  if (action === 'catalog') {
    state.scrollStageOnNextForm = true;
    const task = state.tasks.get(taskId);
    if (task && task.status === 'NEED_OPERATION') {
      openCatalog(taskId, { mounted: true });
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
    await refreshTaskSnapshot(taskId);
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
    ['任务类型', task.practice_mode === 'duration' ? '刷时长' : '刷题'],
    ['每项时长', task.practice_mode === 'duration'
      ? (task.duration_param
          ? (task.duration_param.includes(',')
              ? `随机 ${task.duration_param} 秒`
              : `${task.duration_param} 秒`)
          : '—')
      : '—'],
    ['进度', `${taskProgress(task)}（${task.progress_percent || 0}%）`],
    ['描述', task.description || '—'],
  ];
  for (const [label, value] of rows) {
    const row = el('dl', 'manage-row');
    row.append(el('dt', null, label), el('dd', null, value));
    body.append(row);
  }
  const choices = taskChoices(task, (action) => manageAction(task, action));
  if (choices) body.append(choices);

  const actions = $('#manage-actions');
  actions.textContent = '';
  const add = (label, action, className) =>
    actions.append(button(label, className, () => manageAction(task, action)));

  switch (task.status) {
    case 'READY':
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
  await runTaskAction(task.id, action);
}

/* ------------------------------------------------------------ 任务设置 */

function openPracticeSetup(taskId, options = {}) {
  state.practiceTaskId = taskId;
  const form = enterStage(taskId, 'practice', 'practice-form', options.host || null);
  if (form) form.reset();
  $('#practice-error').hidden = true;
  updatePracticeHint();
}

function updatePracticeHint() {
  const catalog = $('input[name="practice-mode"]:checked').value === 'catalog';
  $('#practice-submit').textContent = catalog ? '加载课程与目录' : '开始必修任务';
  $('#practice-hint').textContent = catalog
    ? '先选择课程和教程，再勾选题目；确认题目后才开始刷题。'
    : '只有一门课程和教程时，将直接开始必修任务。';
}

async function submitPracticeForm(event) {
  event.preventDefault();
  const taskId = state.practiceTaskId;
  const chosen = $('input[name="practice-mode"]:checked').value;
  const action = chosen === 'catalog'
    ? 'catalog' : 'start';
  const submit = $('#practice-submit');
  $('#practice-error').hidden = true;
  submit.disabled = true;
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(taskId)}/${action}`, { method: 'POST' });
    if (result?.ok === false) throw new Error('任务当前无法启动，请稍后重试');
    // 立即在本地记录模式，课程选择页的按钮文案与后续提示才不会退回“必修”。
    patchTaskMode(taskId, chosen === 'catalog' ? 'catalog' : 'practice');
    await refreshTaskSnapshot(taskId);
    toast(action === 'catalog' ? '正在加载目录，完成后请选择题目' : '任务已启动，请留意课程选择提示', 'success');
  } catch (error) {
    $('#practice-error').textContent = error.message;
    $('#practice-error').hidden = false;
  } finally {
    submit.disabled = false;
  }
}

async function startDuration(taskId) {
  // 先进入时长模式加载课程列表，随后按“选课程 → 选时长内容 → 设置时长”顺序进行
  state.durationTaskId = taskId;
  // 立即进入课程步骤并显示加载态，避免等待后端响应时界面像“没反应”。
  state.courseTaskId = taskId;
  state.courseSelection = { course: null, resource: null, courses: [], expandedCourseId: null, loaded: false };
  state.courseLoading = false;
  const loadingForm = enterStage(taskId, 'course', 'course-form', null);
  if (loadingForm) {
    $('#course-search').value = '';
    $('#course-error').hidden = true;
    const box = $('#course-options');
    box.textContent = '';
    box.append(el('div', 'course-loading', '正在启动任务并读取课程列表，请稍候…'));
    updateCourseSelection();
  }
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(state.durationTaskId)}/duration`, {
      method: 'POST',
      body: {},
    });
    if (result?.ok === false) throw new Error('任务当前无法开始刷时长');
    patchTaskMode(taskId, 'duration');
    await refreshTaskSnapshot(taskId);
    toast('正在读取课程列表，完成后自动进入选择', 'success');
    pollDurationCourseList(taskId);
  } catch (error) {
    renderCourseLoadError(error, () => startDuration(taskId));
    toast(error.message, 'error');
  }
}

// POST /duration 立即返回，课程列表由任务线程异步加载。WebSocket 推送
// NEED_OPERATION 后 renderStage 会打开课程选择；这里轮询快照作为 WS
// 延迟/断线时的兜底，避免“启动成功但课程永远不出来”。
async function pollDurationCourseList(taskId) {
  const token = ++state.durationCoursePoll;
  for (let attempt = 0; attempt < UI_TIMING.durationCoursePollAttempts; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, UI_TIMING.durationCoursePollIntervalMs));
    if (token !== state.durationCoursePoll || state.durationTaskId !== taskId) return;
    const current = state.tasks.get(taskId);
    if (!current || current.status !== 'RUNNING') return;
    await refreshTaskSnapshot(taskId);
    const updated = state.tasks.get(taskId);
    if (updated && updated.status === 'NEED_OPERATION') return;
  }
  // 超时后不能让“正在读取课程列表”永远挂着：给出可重试的明确状态。
  if (
    token === state.durationCoursePoll &&
    state.durationTaskId === taskId &&
    state.stageTaskId === taskId
  ) {
    renderDurationCourseTimeout(taskId);
  }
}

function renderDurationCourseTimeout(taskId) {
  const form = enterStage(taskId, 'course', 'course-form', null);
  if (!form) return;
  $('#course-search').value = '';
  $('#course-error').hidden = true;
  const box = $('#course-options');
  box.textContent = '';
  const wrap = el('div', 'load-error');
  wrap.append(el('span', null, '课程列表读取超时，请检查网络后重试'));
  wrap.append(button('重试', 'btn btn-ghost btn-sm', () => retryDurationCourseList(taskId)));
  box.append(wrap);
  updateCourseSelection();
}

async function retryDurationCourseList(taskId) {
  const box = $('#course-options');
  if (box) {
    box.textContent = '';
    box.append(el('div', 'course-loading', '正在重新读取课程列表，请稍候…'));
  }
  await refreshTaskSnapshot(taskId);
  const task = state.tasks.get(taskId);
  if (task && task.status === 'NEED_OPERATION') return; // renderStage 已打开课程选择
  if (task && task.status === 'RUNNING') pollDurationCourseList(taskId);
}

// 后端启动接口只返回 ok，本地任务的 practice_mode 需要立即同步，
// 否则课程选择步骤会误判为“必修模式”。
function patchTaskMode(taskId, mode) {
  const task = state.tasks.get(taskId);
  if (task && task.practice_mode !== mode) {
    task.practice_mode = mode;
    state.tasks.set(taskId, task);
  }
}

function openDurationTarget(taskId, options = {}) {
  const task = state.tasks.get(taskId);
  if (!task) return;
  if (!Array.isArray(task.duration_targets) || task.duration_targets.length === 0) {
    // 后端尚未回传可计时内容时给出可见提示，避免中间区域变成空白。
    const form = enterStage(taskId, 'duration-target', 'duration-target-form', options.host || null);
    if (!form) return;
    $('#duration-target-options').textContent = '';
    $('#duration-target-options').append(
      el('div', 'saved-empty', '暂未获取到可计时内容，请稍候或重新选择课程。')
    );
    $('#duration-target-count').textContent = '0 个';
    resetDurationTargetSelection();
    refreshDurationTargetForm();
    return;
  }
  state.durationTargetTaskId = taskId;
  resetDurationTargetSelection();
  // 后端已自动选中的内容（如单项教程）前端同步勾选，用户只需确认并设时长
  for (const selected of task.selected_duration_targets || []) {
    const match = task.duration_targets.find((t) => t.group_id === selected.group_id);
    if (match) {
      state.durationTargetSelection.add(match);
      state.durationTargetUnitSelection.add(
        String(match.unit_id != null ? match.unit_id : durationTargetUnitLabel(match)),
      );
    }
  }
  const form = enterStage(taskId, 'duration-target', 'duration-target-form', options.host || null);
  if (!form) return;
  $('#duration-target-count').textContent = `${task.duration_targets.length} 个`;
  $('#duration-target-error').hidden = true;
  $('#duration-per-practice').value = task?.duration_param || '30';
  renderDurationTargets(task.duration_targets);
  refreshDurationTargetForm();
}

function resetDurationTargetSelection() {
  state.durationTargetSelection = new Set();
  state.durationTargetUnitSelection = new Set();
  state.durationTargetExpanded = new Set();
}

function durationTargetUnitLabel(target) {
  if (target.unit_name) return target.unit_name;
  const parts = String(target.path || '').split(' / ').filter(Boolean);
  if (parts[0]) return parts[0];
  if (Number.isInteger(target.unit_index)) return `单元 ${target.unit_index + 1}`;
  return target.unit_id || '单元';
}

function durationUnitKey(group) {
  return String(group.unit_id || group.label);
}

function setDurationUnitSelection(group, checked) {
  // 单元是独立“整包选择”：勾选代表整个单元，不逐个点亮子项。
  const key = durationUnitKey(group);
  if (checked) state.durationTargetUnitSelection.add(key);
  else state.durationTargetUnitSelection.delete(key);
}

// 勾选单元=默认刷整个单元；子项保持不勾。勾小节时单元自动进入半选。
function durationUnitCheckbox(group, targets) {
  const checkbox = el('input', 'option-check');
  checkbox.type = 'checkbox';
  const key = durationUnitKey(group);
  const selectedChildren = group.items.filter((t) => state.durationTargetSelection.has(t)).length;
  const wholeUnit = state.durationTargetUnitSelection.has(key);
  checkbox.checked = wholeUnit || (selectedChildren === group.items.length && group.items.length > 0);
  checkbox.indeterminate = !wholeUnit && selectedChildren > 0 && selectedChildren < group.items.length;
  checkbox.setAttribute('aria-label', `选择整个单元：${group.label}`);
  checkbox.addEventListener('click', (event) => event.stopPropagation());
  checkbox.addEventListener('change', () => {
    setDurationUnitSelection(group, checkbox.checked);
    // 不重建列表（重建会丢失展开状态和滚动位置），只原地更新摘要和计数
    const head = checkbox.closest('.duration-unit-head');
    if (head) {
      const meta = head.querySelector('.duration-unit-meta');
      if (meta) meta.textContent = checkbox.checked ? '整个单元' : `${group.items.length} 项`;
    }
    refreshDurationTargetForm();
  });
  return checkbox;
}

// 按单元分组，渲染“单元（点击展开）→ 练习（可勾选）”两级目录。
function renderDurationTargets(targets) {
  const box = $('#duration-target-options');
  box.textContent = '';
  const groups = new Map();
  for (const target of targets) {
    const key = String(target.unit_id != null ? target.unit_id : durationTargetUnitLabel(target));
    if (!groups.has(key)) groups.set(key, { unit_id: key, label: durationTargetUnitLabel(target), items: [] });
    groups.get(key).items.push(target);
  }
  state.durationTargetExpanded = state.durationTargetExpanded || new Set();

  for (const [key, group] of groups) {
    const expanded = state.durationTargetExpanded.has(key);
    const node = el('div', 'duration-unit');
    node.classList.toggle('is-expanded', expanded);

    // 用原生 <button> 处理展开/收起，复选框独立放旁边，彻底避免事件冒泡问题。
    const toggleExpand = () => {
      if (state.durationTargetExpanded.has(key)) state.durationTargetExpanded.delete(key);
      else state.durationTargetExpanded.add(key);
      renderDurationTargets(targets);
    };
    const head = el('button', 'duration-unit-head');
    head.type = 'button';
    head.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    head.addEventListener('click', toggleExpand);
    const chosenInUnit = group.items.filter((t) => state.durationTargetSelection.has(t)).length;
    const wholeUnit = state.durationTargetUnitSelection.has(durationUnitKey(group));
    head.append(
      el('span', 'duration-unit-caret', expanded ? '▾' : '▸'),
      el('span', 'duration-unit-badge', '单元'),
      el('span', 'duration-unit-title', group.label),
      el('span', 'duration-unit-meta',
        wholeUnit ? '整个单元'
          : chosenInUnit ? `已选 ${chosenInUnit} / ${group.items.length}` : `${group.items.length} 项`),
    );
    const checkbox = durationUnitCheckbox(group, targets);
    const headRow = el('div', 'duration-unit-head-row');
    headRow.append(head, checkbox);
    node.append(headRow);

    if (expanded) {
      const children = el('div', 'duration-unit-children');
      for (const target of group.items) {
        const selected = state.durationTargetSelection.has(target);
        const pathParts = String(target.path || '').split(' / ').filter(Boolean);
        const row = courseCheckbox(
          target.name || target.group_id,
          pathParts.slice(1).join(' / ') || target.group_id,
          selected,
          (checked) => {
            if (checked) state.durationTargetSelection.add(target);
            else state.durationTargetSelection.delete(target);
            // 用户细化到小节时取消整单元粗选，避免语义叠加。
            state.durationTargetUnitSelection.delete(durationUnitKey(group));
            // 只刷新勾选状态与摘要，避免重建列表丢失展开状态
            renderDurationTargets(targets);
            refreshDurationTargetForm();
          },
        );
        row.classList.add('duration-item');
        row.dataset.groupId = target.group_id;
        children.append(row);
      }
      node.append(children);
    }
    box.append(node);
  }
}

// 根据已勾选内容与时长输入刷新摘要、校验提示和提交按钮状态
function durationEffectiveTargets(targets) {
  const groups = new Map();
  for (const target of targets) {
    const key = String(target.unit_id != null ? target.unit_id : durationTargetUnitLabel(target));
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(target);
  }
  const chosen = [];
  for (const [key, items] of groups) {
    if (state.durationTargetUnitSelection.has(key)) chosen.push(...items);
    else chosen.push(...items.filter((item) => state.durationTargetSelection.has(item)));
  }
  return chosen;
}

function refreshDurationTargetForm() {
  const chosen = durationEffectiveTargets(
    state.tasks.get(state.durationTargetTaskId)?.duration_targets || [],
  );
  const param = durationParamValue();
  $('#duration-target-summary').textContent = chosen.length
    ? `已选 ${chosen.length} 个练习；勾选单元标题可一次选择整个单元`
    : '勾选单元标题刷整个单元，或展开后勾选具体练习（可多选，同时并行计时）';
  $('#duration-target-submit').disabled = chosen.length === 0 || !param.valid;
  const errorBox = $('#duration-target-error');
  if (param.valid) {
    errorBox.hidden = true;
  } else if ($('#duration-per-practice').value.trim()) {
    // 输入为空时不打扰用户，仅在已有输入但格式错误时提示
    errorBox.textContent = param.error;
    errorBox.hidden = false;
  } else {
    errorBox.hidden = true;
  }
  return { chosen, param };
}

async function backToCourseSelection(taskId) {
  if (!taskId || state.durationGoingBack) return;
  const task = state.tasks.get(taskId);
  if (!task || task.status !== 'NEED_OPERATION' || task.user_operation !== 'CHOOSE_DURATION') return;
  const backButton = $('[data-action="back-course"]');
  if (backButton) backButton.disabled = true;
  state.durationGoingBack = true;
  const finish = () => {
    state.durationGoingBack = false;
    const button = $('[data-action="back-course"]');
    if (button) button.disabled = false;
  };
  let confirmed = false;
  try {
    confirmed = await confirmAction(
      '返回课程选择',
      '返回后需要重新选择课程与教程；当前已勾选的计时内容不会保留。',
      '返回',
    );
    if (!confirmed) return;
    const result = await api(`/api/tasks/${encodeURIComponent(taskId)}/restart`, { method: 'POST' });
    if (result?.ok === false) throw new Error('任务当前无法返回上一级');
    patchTaskMode(taskId, 'duration');
    resetDurationTargetSelection();
    state.durationTargetTaskId = null;
    await refreshTaskSnapshot(taskId);
    state.scrollStageOnNextForm = true;
    toast('已返回课程选择', 'success');
    startDuration(taskId);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    finish();
  }
}

async function submitDurationTargetForm(event) {
  event.preventDefault();
  const { chosen, param } = refreshDurationTargetForm();
  if (chosen.length === 0 || !param.valid) return;
  const errorBox = $('#duration-target-error');
  const submit = $('#duration-target-submit');
  submit.disabled = true;
  try {
    const taskId = state.durationTargetTaskId;
    await api(`/api/tasks/${encodeURIComponent(taskId)}/duration/choose`, {
      method: 'POST',
      body: {
        target_ids: chosen.map((target) => target.group_id),
        duration: param.text,
      },
    });
    await refreshTaskSnapshot(taskId);
    toast(`已选择 ${chosen.length} 个内容，每项 ${param.text} 秒，开始并行累计学习时长`, 'success');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    refreshDurationTargetForm();
  }
}

// 解析每个练习的时长输入："30"（固定秒）或 "10,30"（随机范围）
function durationParamValue() {
  const raw = String($('#duration-per-practice').value || '').trim();
  if (!raw) return { valid: false, error: '请输入每个练习的时长，例如 30 或 10,30' };
  if (raw.includes(',')) {
    const parts = raw.split(',').map((part) => part.trim());
    if (parts.length !== 2) return { valid: false, error: '范围格式为 最小值,最大值，例如 10,30' };
    const lo = Number(parts[0]);
    const hi = Number(parts[1]);
    if (!Number.isInteger(lo) || !Number.isInteger(hi)) {
      return { valid: false, error: '范围必须是整数秒，例如 10,30' };
    }
    if (lo < 1 || hi < 1) return { valid: false, error: '时长至少为 1 秒' };
    if (lo > hi) return { valid: false, error: '范围下限不能大于上限' };
    if (hi > 86400) return { valid: false, error: '时长不能超过 86400 秒' };
    return { valid: true, text: `${lo},${hi}` };
  }
  const value = Number(raw);
  if (!Number.isInteger(value)) return { valid: false, error: '时长必须是整数秒，例如 30 或 10,30' };
  if (value < 1) return { valid: false, error: '时长至少为 1 秒' };
  if (value > 86400) return { valid: false, error: '时长不能超过 86400 秒' };
  return { valid: true, text: String(value) };
}

/* ------------------------------------------------------------ 选择课程 */

async function openCourse(taskId, options = {}) {
  const requestId = ++state.courseRequestId;
  state.courseTaskId = taskId;
  state.courseSelection = { course: null, resource: null, courses: [], expandedCourseId: null, loaded: false };
  state.courseQuery = '';
  state.courseLoading = false;
  const form = enterStage(taskId, 'course', 'course-form', options.host || null, {
    scrollIntoView: options.scrollIntoView === true,
  });
  if (!form) return;
  $('#course-search').value = '';
  $('#course-error').hidden = true;

  state.courseLoading = true;
  let courses;
  try {
    courses = await api(`/api/tasks/${encodeURIComponent(taskId)}/courses`);
  } catch (error) {
    if (requestId === state.courseRequestId) {
      state.courseLoading = false;
      renderCourseLoadError(error, () => openCourse(taskId, { mounted: true, scrollIntoView: true }));
      toast(error.message, 'error');
    }
    return;
  }
  if (requestId !== state.courseRequestId || state.courseTaskId !== taskId) return;

  state.courseSelection.courses = Array.isArray(courses) ? courses : [];
  state.courseSelection.loaded = true;
  state.courseLoading = false;
  renderCourseOptions();
}

function renderCourseLoadError(error, onRetry) {
  const box = $('#course-options');
  if (!box) return;
  box.textContent = '';
  const wrap = el('div', 'load-error');
  wrap.append(el('span', null, `课程加载失败：${error.message}`));
  wrap.append(button('重试', 'btn btn-ghost btn-sm', onRetry));
  box.append(wrap);
  updateCourseSelection();
}

function renderCourseOptions() {
  const selection = state.courseSelection;
  const courseBox = $('#course-options');
  courseBox.textContent = '';
  const query = state.courseQuery.trim().toLowerCase();
  const courses = selection.courses.filter((course) =>
    !query || (course.name || '').toLowerCase().includes(query) ||
    (course.resources || []).some((resource) => (resource.name || '').toLowerCase().includes(query))
  );
  $('#course-option-count').textContent = `${courses.length} 门`;

  if (!selection.courses.length) {
    courseBox.append(el('div', 'saved-empty', '没有可选课程'));
    updateCourseSelection();
    return;
  }
  if (!courses.length) {
    courseBox.append(el('div', 'saved-empty', '没有匹配的课程'));
    updateCourseSelection();
    return;
  }

  for (const course of courses) {
    courseBox.append(courseTreeItem(course));
  }
  updateCourseSelection();
}

// 一级课程行：点击在下方原地展开该课程下的教程（二级目录），让一屏显示更多内容。
function courseTreeItem(course) {
  const selection = state.courseSelection;
  const expanded = selection.expandedCourseId === course.id;
  const group = el('div', 'course-node');
  group.classList.toggle('is-expanded', expanded);

  const resources = course.resources || [];
  const row = el('button', 'course-node-head');
  row.type = 'button';
  row.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  row.append(
    el('span', 'course-node-caret', expanded ? '▾' : '▸'),
    el('span', 'course-node-title', course.name || `课程 ${course.id}`),
    el('span', 'course-node-meta', `${resources.length} 个教程`),
  );
  row.addEventListener('click', (event) => {
    event.stopPropagation();
    selection.course = course;
    if (expanded) {
      // 收起只改变展示，不丢掉已选教程
      selection.expandedCourseId = null;
    } else {
      const resources = course.resources || [];
      const belongsToCourse = selection.resource
        && resources.some((item) => item.id === selection.resource.id);
      // 与旧版两栏选择保持一致：课程下只有一门教程时自动选中
      selection.resource = resources.length === 1
        ? resources[0]
        : (belongsToCourse ? selection.resource : null);
      selection.expandedCourseId = course.id;
    }
    renderCourseOptions();
  });
  group.append(row);

  if (expanded) {
    const sub = el('div', 'course-node-children');
    if (!resources.length) {
      sub.append(el('div', 'course-node-empty', '该课程没有教程'));
    } else {
      for (const resource of resources) {
        const selected = selection.resource?.id === resource.id;
        const item = el('button', 'course-leaf');
        item.type = 'button';
        item.classList.toggle('is-selected', selected);
        item.setAttribute('aria-pressed', selected ? 'true' : 'false');
        item.append(
          el('span', 'course-leaf-title', resource.name || `教程 ${resource.id}`),
          el('span', 'course-leaf-meta',
            `必修 ${resource.finish_point_num ?? 0} / ${resource.total_point_num ?? 0}`),
        );
        item.addEventListener('click', (event) => {
          event.stopPropagation();
          selection.course = course;
          selection.resource = resource;
          renderCourseOptions();
        });
        sub.append(item);
      }
    }
    group.append(sub);
  }
  return group;
}

// 多选版旁白项：用于并行计时内容勾选，onChange 收到布尔值
function courseCheckbox(title, description, checked, onChange) {
  const node = el('label', 'option');
  const box = el('input', 'option-check');
  box.type = 'checkbox';
  box.checked = checked;
  box.addEventListener('change', () => onChange(box.checked));
  const content = el('span', 'option-content');
  content.append(el('strong', null, title), el('small', null, description));
  node.append(box, content, el('span', 'option-selected', '已选'));
  return node;
}

function updateCourseSelection() {
  const { course, resource } = state.courseSelection;
  // 优先用任务上的模式；启动流程尚未落库时回退到当前阶段，避免误显示“必修”。
  const task = state.tasks.get(state.courseTaskId);
  const mode = task?.practice_mode || state.stageView;
  $('#course-selection-summary').textContent = resource
    ? `已选：${course.name || '课程'} / ${resource.name || '教程'}`
    : course ? `已选课程：${course.name || '课程'}，请继续选择教程` : '请选择一门课程，再选择教程';
  $('#course-submit').disabled = !course || !resource;
  $('#course-submit').textContent = mode === 'duration' ? '确认教程，继续选内容'
    : mode === 'catalog' ? '确认教程，继续选题' : '确认并开始必修';
  $('#course-next-hint').textContent = mode === 'duration'
    ? '确认教程后，继续选择要累计时长的学习内容。'
    : mode === 'catalog' ? '选择教程后，继续从目录勾选题目。' : '确认后将开始学习该教程中未完成的必修内容。';
  $('#course-error').hidden = true;
}

/* ------------------------------------------------------------ 全目录刷题 */

async function startCatalog(taskId) {
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/catalog`, { method: 'POST' });
    await refreshTaskSnapshot(taskId);
    toast('正在加载题目目录，完成后会提示选择题目', 'info');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function openCatalog(taskId, options = {}) {
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
  enterStage(taskId, 'catalog', 'catalog-form', options.host || null);

  let tree;
  try {
    tree = await api(`/api/tasks/${encodeURIComponent(taskId)}/catalog`);
  } catch (error) {
    if (requestId !== state.catalogRequestId) return;
    const treeBox = $('#catalog-tree');
    if (treeBox) {
      treeBox.textContent = '';
      const wrap = el('div', 'load-error');
      wrap.append(el('span', null, `目录加载失败：${error.message}`));
      wrap.append(button('重试', 'btn btn-ghost btn-sm', () => openCatalog(taskId, { mounted: true })));
      treeBox.append(wrap);
    }
    $('#catalog-summary').textContent = '目录加载失败';
    $('#catalog-start').disabled = true;
    toast(error.message, 'error');
    return;
  }
  // 并发的重复请求只渲染最后一次，避免覆盖已勾选内容
  if (requestId !== state.catalogRequestId) return;

  state.catalog = tree;
  renderCatalogTree(tree);
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
  checkbox.setAttribute('aria-label', catalogIsLeaf(node)
    ? `选择题目：${catalogLabel(node)}` : `选择 ${catalogLabel(node)} 中符合筛选的可练习题目`);
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
  syncCatalogChecks();
}

function renderCatalogNode(node, depth) {
  const children = node.children || [];
  const row = el(children.length ? 'div' : 'label', 'catalog-row');
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
    const checkTarget = el('label', 'catalog-check-target');
    checkTarget.append(checkbox);
    checkTarget.addEventListener('click', (event) => event.stopPropagation());
    summary.append(checkTarget, el('span', 'catalog-name', catalogLabel(node)));
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
    const row = el('label', 'catalog-leaf-row');
    row.classList.toggle('is-complete', catalogStatus(child) === 'done');
    row.classList.toggle('is-unsupported', !child.selectable && catalogStatus(child) !== 'done');
    const checkbox = catalogNodeCheckbox(child, (checked) => {
      if (checked) state.catalogSelection.add(child.id);
      else state.catalogSelection.delete(child.id);
    });
    const details = el('span', 'catalog-item-details');
    details.append(el('span', 'catalog-name', catalogLabel(child)));
    const path = catalogPathKeys(catalogNodeKey(child)).slice(0, -1).map((key) => {
      const ancestor = state.catalogNodeByKey.get(key);
      return ancestor ? catalogLabel(ancestor) : '';
    }).filter(Boolean).join(' / ');
    const facts = catalogLeafParts(child);
    facts.unshift(path);
    details.append(el('span', 'catalog-item-types', facts.filter(Boolean).join(' · ')));

    const meta = el('span', 'catalog-meta');
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

function syncCatalogChecks() {
  $$('.catalog-check', $('#catalog-tree')).forEach((checkbox) => {
    const key = checkbox.dataset.nodeId;
    const node = state.catalogNodeByKey.get(key);
    const visibleLeaves = node ? catalogDescendantLeaves(node)
      .filter((leaf) => leaf.selectable && catalogMatches(leaf)) : [];
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
    checkbox.disabled = !leaves.length;
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
    const selectCurrent = $('#catalog-select-current');
    const selectableLeaves = catalogDescendantLeaves(current).filter((leaf) => leaf.selectable).length;
    const filteredLeaves = catalogDescendantLeaves(current).filter(catalogMatches);
    const selectable = filteredLeaves.filter((leaf) => leaf.selectable);
    const selected = selectable.filter((leaf) => state.catalogSelection.has(leaf.id)).length;
    selectCurrent.checked = selectable.length > 0 && selected === selectable.length;
    selectCurrent.indeterminate = selected > 0 && selected < selectable.length;
    selectCurrent.disabled = selectable.length === 0;
    $('#catalog-current-total').textContent =
      `${filteredLeaves.length} 道符合筛选 · 共 ${selectableLeaves} 道可练习`;
  }

  const count = state.catalogSelection.size;
  $('#catalog-summary').textContent = `已选 ${count} 道题`;
  $('#catalog-start').disabled = count === 0;
  $('#catalog-start').textContent = count ? `开始刷题（${count} 道）` : '请先选择题目';
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
      if (!state.stageTaskId || !state.tasks.has(state.stageTaskId)) {
        const first = tasks[0];
        state.stageTaskId = first ? first.id : null;
        state.stageView = first ? taskMode(first) : 'empty';
      }
      renderTasks();
      break;
    }
    case 'task.added':
    case 'task.updated': {
      const task = event.data;
      if (!task || !task.id) return;
      state.tasks.set(task.id, task);
      if (!state.stageTaskId) state.stageTaskId = task.id;
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
    toggleSidebarAccounts();
    return;
  }
  $('#page-label').textContent = '任务总览';
  $('#workspace-title').textContent = '任务总览';
  $('#workspace-description').textContent = '统一管理课程任务与学习进度';
}

function toggleSidebarAccounts() {
  const box = $('#sidebar-accounts');
  if (!box) return;
  const willOpen = box.hidden;
  box.hidden = !willOpen;
  if (willOpen) renderSidebarAccounts();
}

function renderSidebarAccounts() {
  const box = $('#sidebar-accounts');
  if (!box) return;
  box.textContent = '';
  if (!state.credentials.length) {
    box.append(el('p', 'sidebar-account-empty', '还没有保存的账号'));
    return;
  }
  for (const credential of state.credentials) {
    const row = el('div', 'sidebar-account');
    row.append(el('span', 'sidebar-account-name', credential.label ? `${credential.label} · ${credential.username}` : credential.username));
    const remove = button('×', 'icon-btn sidebar-account-remove', async (event) => {
      event.stopPropagation();
      const confirmed = await confirmAction('删除已保存账号', `将删除 ${credential.username} 的本地凭据。`, '删除');
      if (!confirmed) return;
      try {
        await api(`/api/credentials/${encodeURIComponent(credential.id)}`, { method: 'DELETE' });
        state.credentials = state.credentials.filter((item) => item.id !== credential.id);
        renderSidebarAccounts();
        renderSidebarCounts();
        if (!$('#add-saved').hidden) renderCredentials();
      } catch (error) {
        toast(error.message, 'error');
      }
    });
    remove.setAttribute('aria-label', `删除 ${credential.username}`);
    row.append(remove);
    box.append(row);
  }
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
  if (state.catalogSubmitting) return;
  const errorBox = $('#catalog-error');
  errorBox.hidden = true;
  const ids = [...state.catalogSelection];
  if (!ids.length) {
    errorBox.textContent = '至少选择一道题目';
    errorBox.hidden = false;
    return;
  }

  const submit = $('#catalog-start');
  state.catalogSubmitting = true;
  submit.disabled = true;
  try {
    const taskId = state.catalogTaskId;
    await api(`/api/tasks/${encodeURIComponent(taskId)}/catalog/choose`, {
      method: 'POST',
      body: { task_ids: ids },
    });
    await refreshTaskSnapshot(taskId);
    toast(`已选择 ${ids.length} 道题，开始刷题`, 'success');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    state.catalogSubmitting = false;
    syncCatalogChecks();
  }
}

async function submitCourseForm(event) {
  event.preventDefault();
  if (state.courseSubmitting) return;
  const selection = state.courseSelection;
  const errorBox = $('#course-error');
  if (!selection.course || !selection.resource) {
    errorBox.textContent = '请选择课程和教程';
    errorBox.hidden = false;
    return;
  }
  const submit = $('#course-submit');
  state.courseSubmitting = true;
  submit.disabled = true;
  try {
    await api(`/api/tasks/${encodeURIComponent(state.courseTaskId)}/choose`, {
      method: 'POST',
      body: {
        course_id: selection.course.id,
        resource_id: selection.resource.id,
      },
    });
    await refreshTaskSnapshot(state.courseTaskId);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    state.courseSubmitting = false;
    updateCourseSelection();
  }
}

async function refreshTaskSnapshot(taskId) {
  if (!taskId) return;
  try {
    const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    if (task && task.id) {
      state.tasks.set(task.id, task);
      renderTasks();
    }
  } catch {
    // WebSocket 仍会推送后续状态；这里是提交后的即时反馈，失败不额外打断流程。
  }
}

function bindEvents() {
  $('#add-task').addEventListener('click', openAddDialog);
  $('#add-task-empty').addEventListener('click', openAddDialog);
  $('#rail-add-task').addEventListener('click', openAddDialog);
  $('#add-form').addEventListener('submit', submitAddForm);
  $('#task-search').addEventListener('input', (event) => {
    state.taskQuery = event.target.value;
    renderTasks();
  });
  $$('[data-nav]').forEach((node) => {
    node.addEventListener('click', () => openNavigation(node.dataset.nav));
  });

  document.addEventListener('submit', (event) => {
    if (event.target === $('#practice-form')) {
      event.preventDefault();
      submitPracticeForm(event);
    } else if (event.target === $('#duration-target-form')) {
      event.preventDefault();
      submitDurationTargetForm(event);
    } else if (event.target === $('#catalog-form')) {
      event.preventDefault();
      submitCatalogForm(event);
    } else if (event.target === $('#course-form')) {
      event.preventDefault();
      submitCourseForm(event);
    }
  });
  $$('input[name="practice-mode"]').forEach((node) => node.addEventListener('change', updatePracticeHint));
  $('#duration-per-practice').addEventListener('input', refreshDurationTargetForm);
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
    // 首次从 REST 载入时默认选中第一条任务，左侧模式区才能立即展开。
    if (!state.stageTaskId || !state.tasks.has(state.stageTaskId)) {
      const first = (tasks || [])[0];
      state.stageTaskId = first ? first.id : null;
      state.stageView = first ? taskMode(first) : 'empty';
    }
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
