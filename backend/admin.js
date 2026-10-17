(() => {
  const $ = (id) => document.getElementById(id);
  const loginForm = $('login-form');
  const dashboard = $('dashboard');
  const logoutButton = $('logout');
  let csrfToken = '';
  let selectedId = null;

  const statusNames = { new: '新提交', contacted: '已联系', closed: '已结束' };
  const typeNames = { vision: '视觉项目', sop: 'SOP 检测' };
  const message = (text, error = false) => {
    $('message').textContent = text;
    $('message').classList.toggle('error', error);
  };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(csrfToken && options.method && options.method !== 'GET' ? { 'X-CSRF-Token': csrfToken } : {}),
      },
    });
    let data = {};
    try { data = await response.json(); } catch { /* Response unavailable. */ }
    if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
    return data;
  }

  function showLogin() {
    csrfToken = '';
    selectedId = null;
    loginForm.hidden = false;
    dashboard.hidden = true;
    logoutButton.hidden = true;
  }

  function showDashboard() {
    loginForm.hidden = true;
    dashboard.hidden = false;
    logoutButton.hidden = false;
  }

  async function loadSummary() {
    const data = await api('/api/admin/summary');
    for (const key of ['total', 'new', 'contacted', 'closed']) {
      $(`count-${key}`).textContent = data[key];
    }
  }

  async function loadList() {
    const query = new URLSearchParams();
    if ($('filter-status').value) query.set('status', $('filter-status').value);
    if ($('filter-type').value) query.set('type', $('filter-type').value);
    const data = await api(`/api/admin/inquiries?${query}`);
    const list = $('inquiry-list');
    list.replaceChildren();
    if (!data.items.length) {
      const empty = document.createElement('li');
      empty.className = 'muted';
      empty.textContent = '暂无符合条件的咨询。';
      list.append(empty);
      return;
    }
    for (const item of data.items) {
      const li = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'list-item';
      button.textContent = `${item.name} · ${typeNames[item.type] || item.type} · ${statusNames[item.status] || item.status} · ${new Date(item.created_at).toLocaleString('zh-CN')}`;
      button.addEventListener('click', () => loadDetail(item.id).catch((error) => message(error.message, true)));
      li.append(button);
      list.append(li);
    }
  }

  async function loadDetail(id) {
    const item = await api(`/api/admin/inquiries/${id}`);
    selectedId = id;
    for (const [key, value] of Object.entries({
      name: item.name,
      contact: item.contact,
      company: item.company || '未填写',
      type: typeNames[item.type] || item.type,
      created: new Date(item.created_at).toLocaleString('zh-CN'),
      description: item.description,
    })) {
      $(`detail-${key}`).textContent = value;
    }
    $('update-form').elements.status.value = item.status;
    $('update-form').elements.note.value = item.note;
    $('detail').hidden = false;
    $('detail-empty').hidden = true;
    message('');
  }

  async function refresh() {
    await Promise.all([loadSummary(), loadList()]);
  }

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(loginForm);
    try {
      const result = await api('/api/admin/login', {
        method: 'POST', body: JSON.stringify({ username: data.get('username'), password: data.get('password') }),
      });
      csrfToken = result.csrf_token;
      loginForm.reset();
      showDashboard();
      await refresh();
      message('登录成功');
    } catch (error) { message(error.message, true); }
  });

  logoutButton.addEventListener('click', async () => {
    try {
      await api('/api/admin/logout', { method: 'POST', body: '{}' });
      showLogin();
      message('已退出登录');
    } catch (error) { message(error.message, true); }
  });

  $('update-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selectedId) return;
    const form = event.currentTarget;
    try {
      await api(`/api/admin/inquiries/${selectedId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: form.elements.status.value, note: form.elements.note.value }),
      });
      await refresh();
      message('跟进记录已保存');
    } catch (error) { message(error.message, true); }
  });

  for (const id of ['filter-status', 'filter-type']) {
    $(id).addEventListener('change', () => loadList().catch((error) => message(error.message, true)));
  }
  $('refresh').addEventListener('click', () => refresh().catch((error) => message(error.message, true)));

  api('/api/admin/me').then((data) => {
    csrfToken = data.csrf_token;
    showDashboard();
    return refresh();
  }).catch(() => showLogin());
})();
