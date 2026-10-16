const courses = {
  foundation: {
    kicker: '项目交付 / 合作流程',
    title: '视觉模块交付',
    description: '以具体工件、检测目标和验收条件为起点，确定视觉模块的范围与交付方式。',
    steps: ['了解工件、现场条件、精度与节拍要求', '确定成像、打光、算法与软件方案', '以样件和约定条件验证关键指标', '完成联机调试，并记录验收条件与结果']
  },
  agent: {
    kicker: '课程规划 / 待开发',
    title: '机器视觉项目方法课',
    description: '规划将实际项目方法整理为学习内容。大纲和售价尚未确定。',
    steps: ['从工件和客户痛点提炼需求', '选型、打光与成像条件设计', '定位、测量和检测算法的应用示例', '现场调试、效果测试与项目验收']
  },
  consulting: {
    kicker: '研发探索 / 验证路线',
    title: '边缘端 SOP 验证',
    description: '先在固定机位、单工位验证少量可观察步骤；具体能力取决于开发与实测。',
    steps: ['选定 3—5 个清晰可观察的步骤', '确定漏步骤、顺序错误与超时的判定方式', '在目标边缘设备上测试速度与稳定性', '评估异常提醒、视频追溯与验收指标']
  }
};

const menuToggle = document.querySelector('.menu-toggle');
const siteNav = document.querySelector('.site-nav');
menuToggle.addEventListener('click', () => {
  const open = menuToggle.getAttribute('aria-expanded') !== 'true';
  menuToggle.setAttribute('aria-expanded', String(open));
  menuToggle.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
  siteNav.classList.toggle('open', open);
});
siteNav.addEventListener('click', event => {
  if (event.target.closest('a')) {
    menuToggle.setAttribute('aria-expanded', 'false');
    menuToggle.setAttribute('aria-label', '打开导航菜单');
    siteNav.classList.remove('open');
  }
});

const dialog = document.getElementById('course-dialog');
document.querySelectorAll('[data-course]').forEach(button => {
  button.addEventListener('click', () => {
    const course = courses[button.dataset.course];
    document.getElementById('dialog-kicker').textContent = course.kicker;
    document.getElementById('dialog-title').textContent = course.title;
    document.getElementById('dialog-description').textContent = course.description;
    const content = document.getElementById('dialog-content');
    content.replaceChildren();
    const heading = document.createElement('h3');
    heading.textContent = '四个关键步骤';
    const list = document.createElement('ol');
    course.steps.forEach(step => {
      const item = document.createElement('li');
      item.textContent = step;
      list.append(item);
    });
    content.append(heading, list);
    dialog.showModal();
  });
});
dialog.querySelector('.dialog-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  if (event.target === dialog) dialog.close();
});

let currentMode = 'content';
const ideaInput = document.getElementById('idea-input');
const generateButton = document.getElementById('generate-button');
const result = document.getElementById('demo-result');
const resultContent = document.getElementById('result-content');
const modeTabs = [...document.querySelectorAll('[data-mode]')];
const modeNames = { content: '漏步骤', course: '顺序错误', workflow: '超时提醒' };
let resultText = '';

function showToast(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2600);
}

modeTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => {
    currentMode = tab.dataset.mode;
    modeTabs.forEach(item => item.setAttribute('aria-selected', String(item === tab)));
    result.hidden = true;
  });
  tab.addEventListener('keydown', event => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const next = modeTabs[(index + (event.key === 'ArrowRight' ? 1 : modeTabs.length - 1)) % modeTabs.length];
    next.focus();
    next.click();
  });
});
ideaInput.addEventListener('input', () => {
  document.getElementById('char-count').textContent = ideaInput.value.length;
});

function makeSteps(topic) {
  if (currentMode === 'course') return [
    `场景：围绕「${topic}」列出正常步骤和允许的操作分支。`,
    '观察：确认固定机位能清楚看到每一步的起止动作。',
    '判定：定义哪些顺序变化算异常，以及人工复核方式。',
    '验证：采集正常与异常样本，再测试误报和漏报。'
  ];
  if (currentMode === 'workflow') return [
    `场景：围绕「${topic}」确定要计时的步骤。`,
    '阈值：结合节拍要求，记录正常耗时范围与超时门槛。',
    '提醒：约定何时提示操作员、何时记录并上报异常。',
    '验证：在目标设备上实测延迟、误报与现场可用性。'
  ];
  return [
    `场景：围绕「${topic}」列出 3—5 个必须完成的可观察步骤。`,
    '成像：检查机位、遮挡、光照与人员动作是否稳定可见。',
    '判定：定义漏步骤的触发条件及人工复核入口。',
    '验证：采集样例，记录漏报、误报和测试条件。'
  ];
}

generateButton.addEventListener('click', () => {
  const topic = ideaInput.value.trim();
  if (!topic) {
    showToast('先描述工位与步骤，再生成清单');
    ideaInput.focus();
    return;
  }
  const steps = makeSteps(topic);
  resultContent.replaceChildren();
  const heading = document.createElement('h3');
  heading.textContent = `${modeNames[currentMode]} · ${topic}`;
  const list = document.createElement('ol');
  steps.forEach(step => {
    const item = document.createElement('li');
    item.textContent = step;
    list.append(item);
  });
  resultContent.append(heading, list);
  resultText = `${modeNames[currentMode]} · ${topic}\n${steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}`;
  result.hidden = false;
  result.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'nearest' });
});

document.getElementById('copy-result').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(resultText);
    showToast('已复制到剪贴板');
  } catch {
    showToast('复制不可用，请直接选中结果文字');
  }
});

document.getElementById('year').textContent = new Date().getFullYear();
