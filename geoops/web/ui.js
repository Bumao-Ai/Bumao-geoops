/* Bumao GeoOps — 前端骨架
   只渲染接口真实返回的内容；缺令牌、缺接口、无记录分别有各自的空态，不填演示数字。 */
(function () {
  "use strict";

  var KEY = "geoops.ui";
  var state = { section: "overview", status: "", taskQuery: "", artifactQuery: "", auditQuery: "",
                overview: null, tasks: [], rules: null, artifacts: [], audit: null, runs: [],
                projects: [], datasets: [], catalog: null, reviews: [], trace: null, token: "",
                deliverables: [], qualityReports: [], settings: null, lastQuality: null, modelRuntime: null,
                datasetQuery: "", profileDatasetId: "", workflows: [], workflowEditId: "", runQuery: "" };

  function readUi() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; }
  }
  function writeUi(patch) {
    var next = Object.assign(readUi(), patch);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch (e) {}
  }

  /* ---------- 导航 ---------- */
  var navItems = Array.prototype.slice.call(document.querySelectorAll("[data-nav]"));
  var sections = Array.prototype.slice.call(document.querySelectorAll(".section"));

  function show(section) {
    state.section = section;
    sections.forEach(function (el) { el.classList.toggle("on", el.id === section); });
    navItems.forEach(function (el) {
      el.setAttribute("aria-current", el.dataset.nav === section ? "page" : "false");
    });
    var current = document.getElementById("topCurrent");
    if (current) {
      var active = navItems.filter(function (el) { return el.dataset.nav === section; })[0];
      var zh = active ? active.querySelector(".zh") : null;
      current.textContent = zh ? zh.textContent : "总览";
    }
    if (section === "projects") loadProjects();
    if (section === "tasks") loadTasks();
    if (section === "resources") { loadCatalog(); loadModelRuntime(); }
    if (section === "data") loadDatasets();
    if (section === "runs") { loadRuns(); loadWorkflows(); }
    if (section === "rules") loadRules();
    if (section === "quality") { loadQualityReports(); loadQualityTargets(); }
    if (section === "artifacts") { loadDeliverables(); loadArtifacts(); }
    if (section === "reviews") loadReviews();
    if (section === "trace") loadAudit();
    if (section === "settings") loadSettings();
  }

  function go(section, jump) {
    if (!document.getElementById(section)) return;
    show(section);
    try { history.replaceState(null, "", "#" + section); } catch (e) {}
    if (jump) {
      var target = document.getElementById(section);
      if (target && target.scrollIntoView) target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  navItems.forEach(function (el) {
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      go(el.dataset.nav, true);
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll("[data-goto]"), function (el) {
    function openKpi(ev) {
      if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
      if (ev.type === "keydown") ev.preventDefault();
      go(el.getAttribute("data-goto"), true);
    }
    el.addEventListener("click", openKpi);
    el.addEventListener("keydown", openKpi);
  });
  window.addEventListener("hashchange", function () {
    var target = location.hash.replace("#", "");
    if (target && document.getElementById(target)) go(target, true);
  });

  /* ---------- 主题 / 纸色 / 字号 ---------- */
  var themeBtn = document.getElementById("themeBtn");
  themeBtn.addEventListener("click", function () {
    var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    writeUi({ theme: next });
  });

  Array.prototype.forEach.call(document.querySelectorAll(".swatch"), function (btn) {
    btn.addEventListener("click", function () {
      document.documentElement.dataset.palette = btn.dataset.palette;
      Array.prototype.forEach.call(document.querySelectorAll(".swatch"), function (other) {
        other.setAttribute("aria-pressed", other === btn ? "true" : "false");
      });
      writeUi({ palette: btn.dataset.palette });
    });
  });

  var zoom = 1;
  Array.prototype.forEach.call(document.querySelectorAll("[data-zoom]"), function (btn) {
    btn.addEventListener("click", function () {
      zoom = Math.min(1.3, Math.max(0.86, zoom + 0.06 * Number(btn.dataset.zoom)));
      document.documentElement.style.setProperty("--fs-zoom", zoom.toFixed(2));
      writeUi({ zoom: zoom });
    });
  });

  /* ---------- 令牌 ---------- */
  var tokenInput = document.getElementById("token");
  function currentToken() { return (tokenInput.value || sessionStorage.getItem("geoops.token") || "").trim(); }
  tokenInput.addEventListener("change", function () {
    var value = tokenInput.value.trim();
    if (value) sessionStorage.setItem("geoops.token", value); else sessionStorage.removeItem("geoops.token");
    state.token = value;
    updateWritePill();
    loadOverview(); loadAudit();
    if (state.section && state.section !== "overview") show(state.section);
  });
  try {
    var savedToken = sessionStorage.getItem("geoops.token");
    if (savedToken) tokenInput.value = savedToken;
  } catch (e) {}

  /* ---------- 请求 ---------- */
  function setLink(kind, text) {
    var badge = document.getElementById("badgeLink");
    var label = document.getElementById("badgeLinkText");
    badge.classList.remove("ok", "bad", "warn");
    if (kind) badge.classList.add(kind);
    label.textContent = text;
  }

  function api(path, options) {
    options = options || {};
    var headers = {};
    if (options.token) headers["X-GeoOps-Token"] = options.token;
    if (options.body) headers["Content-Type"] = "application/json";
    return fetch(path, {
      method: options.method || "GET",
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store"
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        return { status: response.status, body: body };
      });
    });
  }

  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  function bytes(n) {
    if (n === null || n === undefined) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(2) + " MB";
  }
  function shortHash(hash) { return hash ? String(hash).slice(0, 10) : "—"; }

  function fmtNum(value, digits) {
    if (value === null || value === undefined || value === "") return "—";
    var number = Number(value);
    if (!isFinite(number)) return "—";
    if (digits === undefined) return number.toLocaleString("en-US", { maximumFractionDigits: 6 });
    return number.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function fmtRate(value) {
    if (value === null || value === undefined || value === "") return "—";
    var number = Number(value);
    if (!isFinite(number)) return "—";
    return (number * 100).toFixed(2) + "%";
  }
  function fmtThreshold(value) {
    if (value === null || value === undefined) return "—";
    var number = Number(value);
    return isFinite(number) ? number.toFixed(3) : "—";
  }
  function fmtArea(area, basis) {
    if (area === null || area === undefined || area === "") return "—";
    var number = Number(area);
    if (!isFinite(number)) return "—";
    if (basis === "map_units") return fmtNum(number, 1) + " map-unit²";
    if (number >= 1000000) return fmtNum(number / 1000000, 2) + " km²";
    return fmtNum(number, 1) + " m²";
  }

  function emptyBox(glyph, title, body) {
    return '<div class="empty"><div class="glyph">' + glyph + '</div><div><h4>' + title + '</h4><p>' + body + '</p></div></div>';
  }

  function statusPill(status) {
    var map = {
      COMPLETED: "pass", RUNNING: "warn", PAUSED: "warn", READY: "info",
      DRAFT: "idle", FAILED: "fail", CANCELLED: "idle"
    };
    return '<span class="pill ' + (map[status] || "idle") + '">' + esc(status || "—") + "</span>";
  }

  /* ---------- 概览 ---------- */
  function loadOverview() {
    return api("/api/v1/overview").then(function (res) {
      if (res.status !== 200) { setLink("bad", "接口 " + res.status); return; }
      state.overview = res.body;
      var body = res.body || {};
      var tasks = body.tasks || {};
      var rules = body.rules || {};
      var artifacts = body.artifacts || {};
      document.getElementById("kpiObjects").textContent = body.objects === undefined ? "—" : body.objects;
      document.getElementById("kpiTasks").textContent = tasks.total === undefined ? "—" : tasks.total;
      document.getElementById("kpiRules").textContent = rules.rules === undefined ? "—" : rules.rules;
      document.getElementById("kpiArtifacts").textContent = artifacts.configured === false ? "—" : (artifacts.count === undefined ? "—" : artifacts.count);
      document.getElementById("kpiArtifactsNote").textContent = artifacts.configured === false ? "成果接口未配置" : "登记成果";
      var context = body.context || {};
      if (context.version) {
        document.getElementById("badgeVersion").textContent = "v" + context.version;
        document.getElementById("idVersion").textContent = context.version;
      }
      if (context.kernel) {
        document.getElementById("badgeKernel").textContent = "kernel " + context.kernel;
        document.getElementById("idKernel").textContent = context.kernel + " · read-only";
      }
      setLink("ok", "已连接");
    }).catch(function () { setLink("bad", "离线"); });
  }

  /* ---------- 任务 ---------- */
  function loadTasks() {
    var box = document.getElementById("taskTable");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/tasks 取任务列表。");
    return api("/api/v1/tasks").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "任务接口不可用", "接口返回 " + res.status + "；任务端点未配置时不会伪造列表。");
        return;
      }
      state.tasks = (res.body && res.body.tasks) || [];
      document.getElementById("tasksCount").textContent = state.tasks.length + " 条";
      renderTasks();
    }).catch(function () {
      box.innerHTML = emptyBox("断", "取不到任务列表", "网络或服务不可达。启动 <code>python -m geoops.api</code> 后再刷新。");
    });
  }

  function renderTasks() {
    var box = document.getElementById("taskTable");
    var query = state.taskQuery.trim().toLowerCase();
    var rows = state.tasks.filter(function (task) {
      if (state.status && task.status !== state.status) return false;
      if (!query) return true;
      return [task.task_id, task.name, task.project_id, task.task_type]
        .filter(Boolean).join(" ").toLowerCase().indexOf(query) >= 0;
    });
    if (!rows.length) {
      box.innerHTML = emptyBox("空", "没有符合条件的任务",
        "任务表是接口真实返回的；筛掉全部记录时显示此空态，不补示例数据。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Task</th><th>Name</th><th>Type</th><th>Project</th><th>Status</th><th>Runs</th><th>Version</th><th></th></tr></thead><tbody>';
    rows.forEach(function (task) {
      html += "<tr>" +
        '<td class="id">' + esc(task.task_id) + "</td>" +
        "<td>" + esc(task.name) + "</td>" +
        '<td class="dim">' + esc(task.task_type) + "</td>" +
        '<td class="id">' + esc(task.project_id) + "</td>" +
        "<td>" + statusPill(task.status) + "</td>" +
        '<td class="num">' + ((task.workflow_run_ids || []).length) + "</td>" +
        '<td class="num">v' + esc(task.version) + "</td>" +
        '<td class="act"><button class="btn ghost sm" data-move="' + esc(task.task_id) + '">迁移</button></td>' +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  var seg = document.getElementById("taskSeg");
  if (seg) {
    Array.prototype.forEach.call(seg.querySelectorAll("button"), function (btn) {
      btn.addEventListener("click", function () {
        state.status = btn.dataset.status;
        Array.prototype.forEach.call(seg.querySelectorAll("button"), function (other) {
          other.setAttribute("aria-pressed", other === btn ? "true" : "false");
        });
        renderTasks();
      });
    });
  }
  var taskSearch = document.getElementById("taskSearch");
  if (taskSearch) taskSearch.addEventListener("input", function () { state.taskQuery = taskSearch.value; renderTasks(); });
  document.getElementById("taskReload").addEventListener("click", loadTasks);

  /* ---------- 写操作 ---------- */
  function setMsg(id, kind, text) {
    var node = document.getElementById(id);
    node.className = "wmsg" + (kind ? " " + kind : "");
    node.textContent = text;
  }

  function updateWritePill() {
    var pill = document.getElementById("writePill");
    if (!pill) return;
    var has = !!currentToken();
    pill.className = "pill " + (has ? "info" : "idle");
    pill.textContent = has ? "令牌已填" : "需令牌";
  }

  function selectTask(task) {
    document.getElementById("moveTask").value = task.task_id;
    var select = document.getElementById("moveTarget");
    var targets = task.allowed_targets || [];
    select.innerHTML = '<option value="">选择目标</option>' + targets.map(function (target) {
      return '<option value="' + esc(target) + '">' + esc(target) + "</option>";
    }).join("");
    setMsg("moveMsg", "", "当前 " + task.status + "；允许 " + (targets.join(" / ") || "无可用迁移"));
  }

  document.getElementById("taskTable").addEventListener("click", function (ev) {
    var button = ev.target.closest("[data-move]");
    if (!button) return;
    var taskId = button.getAttribute("data-move");
    var task = state.tasks.filter(function (row) { return row.task_id === taskId; })[0];
    if (task) selectTask(task);
  });

  document.getElementById("createForm").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var token = currentToken();
    if (!token) { setMsg("createMsg", "bad", "先在右上角填令牌（需要 task:create 权限）"); return; }
    var projectId = document.getElementById("newProject").value.trim();
    var name = document.getElementById("newName").value.trim();
    var taskType = document.getElementById("newType").value.trim();
    if (!projectId || !name) { setMsg("createMsg", "bad", "项目 id 与任务名称不能为空"); return; }
    setMsg("createMsg", "", "提交中…");
    api("/api/v1/tasks", {
      method: "POST", token: token,
      body: { project_id: projectId, name: name, task_type: taskType }
    }).then(function (res) {
      if (res.status === 201) {
        var task = (res.body && res.body.task) || {};
        setMsg("createMsg", "ok", "已创建 " + task.task_id + "（v" + task.version + "，DRAFT）");
        document.getElementById("createForm").reset();
        loadTasks(); loadOverview();
        return;
      }
      if (res.status === 404) { setMsg("createMsg", "bad", "写入口未配置：服务以只读方式启动"); return; }
      var reason = (res.body && res.body.error) || res.status;
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 task:create 权限：" : "创建被拒：";
      setMsg("createMsg", "bad", prefix + reason);
    }).catch(function () { setMsg("createMsg", "bad", "网络或服务不可达"); });
  });

  document.getElementById("transitionForm").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var token = currentToken();
    if (!token) { setMsg("moveMsg", "bad", "先在右上角填令牌（需要 task:transition 权限）"); return; }
    var taskId = document.getElementById("moveTask").value.trim();
    var target = document.getElementById("moveTarget").value;
    var reason = document.getElementById("moveReason").value.trim();
    if (!taskId || !target) { setMsg("moveMsg", "bad", "任务 id 与目标状态必填"); return; }
    setMsg("moveMsg", "", "提交中…");
    api("/api/v1/tasks/" + encodeURIComponent(taskId) + "/transitions", {
      method: "POST", token: token,
      body: { target: target, reason: reason }
    }).then(function (res) {
      if (res.status === 200) {
        var task = (res.body && res.body.task) || {};
        setMsg("moveMsg", "ok", "已迁移到 " + task.status + "（v" + task.version + "）");
        document.getElementById("moveReason").value = "";
        loadOverview();
        loadTasks().then(function () {
          var fresh = state.tasks.filter(function (row) { return row.task_id === task.task_id; })[0];
          if (fresh) selectTask(fresh);
        });
        return;
      }
      if (res.status === 404) { setMsg("moveMsg", "bad", "写入口未配置：服务以只读方式启动"); return; }
      var reasonText = (res.body && res.body.error) || res.status;
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 task:transition 权限：" : "迁移被拒：";
      setMsg("moveMsg", "bad", prefix + reasonText);
    }).catch(function () { setMsg("moveMsg", "bad", "网络或服务不可达"); });
  });

  /* ---------- 流程 ---------- */
  function clearResumeRuns() {
    var select = document.getElementById("resumeRunSelect");
    if (!select) return;
    select.innerHTML = '<option value="">新建运行</option>';
    select.value = "";
    updateResumeButton();
  }

  function loadRuns() {
    var box = document.getElementById("runTable");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/runs 取运行日志。");
    api("/api/v1/runs").then(function (res) {
      if (res.status === 404) {
        document.getElementById("runsCount").textContent = "未配置";
        box.innerHTML = emptyBox("未", "运行日志未配置", "服务端没有挂载运行日志（<code>--runs</code>），不伪造运行记录。");
        clearResumeRuns();
        return;
      }
      if (res.status !== 200) {
        document.getElementById("runsCount").textContent = "接口 " + res.status;
        box.innerHTML = emptyBox("未", "运行接口不可用", "接口返回 " + res.status + "。");
        clearResumeRuns();
        return;
      }
      state.runs = (res.body && res.body.runs) || [];
      populateResumeRuns();
      renderRuns();
    }).catch(function () {
      box.innerHTML = emptyBox("断", "取不到运行日志", "服务未启动或网络不可达。");
      clearResumeRuns();
    });
  }

  function runPill(status) {
    var map = { PASS: "pass", FAIL: "fail", ERROR: "fail", SKIP: "idle", SKIPPED: "idle", REUSED: "info" };
    return '<span class="pill ' + (map[status] || "idle") + '">' + esc(status || "—") + "</span>";
  }

  function runMatches(run, query) {
    var parts = [run.run_id, run.status, run.task_id, run.workflow_id, run.resumed_from, run.recorded_at];
    (run.node_runs || []).forEach(function (node) {
      parts.push(node.node_id, node.name, node.status, node.detail);
    });
    return parts.join(" ").toLowerCase().indexOf(query) >= 0;
  }

  function filteredRuns() {
    var rows = state.runs.slice().reverse();
    var query = (state.runQuery || "").trim().toLowerCase();
    return query ? rows.filter(function (run) { return runMatches(run, query); }) : rows;
  }

  function updateRunsCount(shown) {
    var pill = document.getElementById("runsCount");
    if (!pill) return;
    pill.textContent = (state.runQuery || "").trim()
      ? shown + " / " + state.runs.length + " 次"
      : state.runs.length + " 次";
  }

  function renderRuns() {
    var box = document.getElementById("runTable");
    var rows = filteredRuns();
    updateRunsCount(rows.length);
    if (!rows.length) {
      if ((state.runQuery || "").trim()) {
        box.innerHTML = emptyBox("筛", "没有匹配的运行",
          "当前关键词没有命中。按 Esc 清空筛选。");
      } else {
        box.innerHTML = emptyBox("空", "还没有运行记录",
          "运行完成才会写日志；这里没有记录时就是没有跑过，不补示例。");
      }
      return;
    }
    var html = "";
    rows.forEach(function (run) {
      var nodes = run.node_runs || [];
      var resumable = run.status === "FAIL" || run.status === "ERROR";
      html += '<div class="run">' +
        '<div class="run-head"><span class="run-id">' + esc(run.run_id) + "</span>" +
        runPill(run.status) +
        '<span class="run-meta"><span>' + esc(run.task_id || "未挂任务") + "</span>" +
        (run.workflow_id ? "<span>WF " + esc(run.workflow_id) + "</span>" : "") +
        "<span>节点 " + nodes.length + "</span>" +
        "<span>跳过 " + esc(run.skipped || 0) + "</span>" +
        (run.resumed_from ? "<span>恢复自 " + esc(run.resumed_from) + "</span>" : "") +
        "<span>" + esc(String(run.recorded_at || "").replace("T", " ").replace("Z", "")) + "</span></span></div>";
      if (nodes.length) {
        html += '<ul class="nodes">' + nodes.map(function (node) {
          return '<li class="node-row"><span class="nid">' + esc(node.node_id) + "</span>" +
            runPill(node.status) +
            '<span class="ndetail"><b>' + esc(node.name) + "</b> · " + esc(node.detail || "") + "</span></li>";
        }).join("") + "</ul>";
      }
      if (resumable) {
        html += '<div class="run-actions">' +
          '<button class="btn ghost sm" type="button" data-run-resume="' + esc(run.run_id) + '">恢复运行</button>' +
          "</div>";
      }
      html += "</div>";
    });
    box.innerHTML = html;
  }

  function updateResumeButton() {
    var select = document.getElementById("resumeRunSelect");
    var button = document.getElementById("workflowExecuteBtn");
    if (!select || !button) return;
    button.textContent = select.value ? "恢复运行" : "执行流程";
  }

  function applyResumeDefaults() {
    var select = document.getElementById("resumeRunSelect");
    if (!select) return;
    if (!select.value) {
      updateResumeButton();
      return;
    }
    var run = state.runs.filter(function (row) { return row.run_id === select.value; })[0];
    if (!run) {
      select.value = "";
      updateResumeButton();
      return;
    }
    var workflowSelect = document.getElementById("workflowSelect");
    if (run.workflow_id && workflowSelect) {
      var found = Array.prototype.some.call(workflowSelect.options, function (option) {
        return option.value === run.workflow_id;
      });
      if (found) workflowSelect.value = run.workflow_id;
    }
    var form = document.getElementById("workflowRunForm");
    if (form && form.task_id && !form.task_id.value && run.task_id) form.task_id.value = run.task_id;
    updateResumeButton();
  }

  function populateResumeRuns() {
    var select = document.getElementById("resumeRunSelect");
    if (!select) return;
    var previous = select.value;
    var resumable = state.runs.filter(function (run) {
      return run.status === "FAIL" || run.status === "ERROR";
    });
    select.innerHTML = '<option value="">新建运行</option>' + resumable.map(function (run) {
      return '<option value="' + esc(run.run_id) + '">' + esc(run.run_id) + " · " + esc(run.status) +
        " · " + esc(run.task_id || "未挂任务") + "</option>";
    }).join("");
    var keep = previous && resumable.some(function (run) { return run.run_id === previous; });
    if (keep) select.value = previous;
    applyResumeDefaults();
  }

  function selectResumeRun(runId) {
    var select = document.getElementById("resumeRunSelect");
    if (!select) return;
    select.value = runId;
    applyResumeDefaults();
    var form = document.getElementById("workflowRunForm");
    if (form && form.scrollIntoView) form.scrollIntoView({ behavior: "smooth", block: "center" });
    setMsg("workflowRunMsg", "info", "已带入恢复：" + runId);
  }

  var runTable = document.getElementById("runTable");
  if (runTable) runTable.addEventListener("click", function (ev) {
    var target = ev.target;
    if (!target || !target.closest) return;
    var resume = target.closest("[data-run-resume]");
    if (resume) selectResumeRun(resume.getAttribute("data-run-resume"));
  });

  var resumeSelect = document.getElementById("resumeRunSelect");
  if (resumeSelect) resumeSelect.addEventListener("change", applyResumeDefaults);

  var runReload = document.getElementById("runReload");
  if (runReload) runReload.addEventListener("click", loadRuns);

  var runQuery = document.getElementById("runQuery");
  if (runQuery) {
    runQuery.addEventListener("input", function () {
      state.runQuery = runQuery.value || "";
      renderRuns();
    });
    runQuery.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        runQuery.value = "";
        state.runQuery = "";
        renderRuns();
      }
    });
  }

  /* ---------- 流程定义 ---------- */
  function loadWorkflows() {
    var box = document.getElementById("workflowTable");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/workflows 取流程定义。");
    api("/api/v1/workflows").then(function (res) {
      if (res.status === 404) {
        document.getElementById("workflowCount").textContent = "未配置";
        box.innerHTML = emptyBox("未", "流程定义接口未配置", "服务端没有流程定义库；不补演示定义。");
        return;
      }
      if (res.status !== 200) {
        document.getElementById("workflowCount").textContent = "接口 " + res.status;
        box.innerHTML = emptyBox("未", "流程定义接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.workflows = (res.body && res.body.workflows) || [];
      document.getElementById("workflowCount").textContent = state.workflows.length + " 份";
      renderWorkflows();
    }).catch(function () {
      box.innerHTML = emptyBox("断", "取不到流程定义", "服务未启动或网络不可达。");
    });
  }

  function renderWorkflows() {
    var box = document.getElementById("workflowTable");
    var select = document.getElementById("workflowSelect");
    var previous = select.value;
    if (!state.workflows.length) {
      box.innerHTML = emptyBox("空", "还没有流程定义",
        "先在右侧登记一份定义；节点会逐项校验后再允许执行。");
      select.innerHTML = '<option value="">还没有流程定义</option>';
      return;
    }
    box.innerHTML = state.workflows.slice().reverse().map(function (obj) {
      var p = obj.payload || {};
      var nodes = p.nodes || [];
      var editing = state.workflowEditId === obj.object_id;
      return '<div class="run workflow-card' + (editing ? " is-editing" : "") + '" data-workflow="' + esc(obj.object_id) + '">' +
        '<div class="run-head"><span class="run-id">' + esc(obj.object_id) + "</span>" +
        '<span class="pill info">' + esc(p.task_type || "—") + "</span>" +
        (editing ? '<span class="pill editing">编辑中…</span>' : "") +
        '<span class="run-meta"><span>v' + esc(obj.version || "—") + "</span>" +
        "<span>节点 " + nodes.length + "</span></span></div>" +
        '<div class="run-meta" style="margin:5px 0 0;justify-content:flex-start">' +
        "<span>" + esc(p.name || "") + "</span>" +
        (p.description ? "<span>" + esc(p.description) + "</span>" : "") + "</div>" +
        '<div class="note" style="margin:7px 0 0">' + nodes.map(function (node) {
          return "<code>" + esc(node.node_id) + " · " + esc(node.type) + "</code>";
        }).join(" ") + "</div>" +
        '<div class="run-actions">' +
        '<button class="btn ghost sm" type="button" data-workflow-edit="' + esc(obj.object_id) + '">编辑</button>' +
        '<button class="btn ghost sm" type="button" data-workflow-use="' + esc(obj.object_id) + '">带入执行</button>' +
        "</div></div>";
    }).join("");
    select.innerHTML = '<option value="">选择流程定义</option>' + state.workflows.map(function (obj) {
      var p = obj.payload || {};
      return '<option value="' + esc(obj.object_id) + '">' + esc(obj.object_id) + " · " + esc(p.name || "") + "</option>";
    }).join("");
    if (previous) select.value = previous;
    applyResumeDefaults();
  }

  function workflowObject(workflowId) {
    return state.workflows.filter(function (obj) { return obj.object_id === workflowId; })[0] || null;
  }

  function setWorkflowMode(editingId) {
    state.workflowEditId = editingId || "";
    var form = document.getElementById("workflowForm");
    var idInput = document.getElementById("workflowIdInput");
    var submit = document.getElementById("workflowSubmitBtn");
    var cancel = document.getElementById("workflowCancelBtn");
    var note = document.getElementById("workflowEditNote");
    var noteId = document.getElementById("workflowEditId");
    if (!form || !idInput || !submit || !cancel || !note || !noteId) return;
    idInput.readOnly = !!state.workflowEditId;
    idInput.setAttribute("aria-readonly", state.workflowEditId ? "true" : "false");
    submit.textContent = state.workflowEditId ? "更新定义" : "登记定义";
    cancel.hidden = !state.workflowEditId;
    note.hidden = !state.workflowEditId;
    noteId.textContent = state.workflowEditId || "";
    markWorkflowEditing();
  }

  function markWorkflowEditing() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-workflow]"), function (card) {
      var editing = card.getAttribute("data-workflow") === state.workflowEditId;
      card.classList.toggle("is-editing", editing);
      var badge = card.querySelector(".pill.editing");
      if (!editing) {
        if (badge) badge.remove();
        return;
      }
      if (badge) return;
      var head = card.querySelector(".run-head");
      if (!head) return;
      badge = document.createElement("span");
      badge.className = "pill editing";
      badge.textContent = "编辑中…";
      var meta = head.querySelector(".run-meta");
      head.insertBefore(badge, meta || null);
    });
  }

  function fitWorkflowNodes() {
    var form = document.getElementById("workflowForm");
    if (!form || !form.nodes) return;
    form.nodes.rows = Math.min(16, Math.max(7, (form.nodes.value || "").split("\n").length));
  }

  function resetWorkflowForm() {
    var form = document.getElementById("workflowForm");
    if (!form) return;
    form.reset();
    if (form.nodes) form.nodes.rows = 7;
    setWorkflowMode("");
    setMsg("workflowMsg", "", "");
  }

  function fillWorkflowForm(obj) {
    var form = document.getElementById("workflowForm");
    if (!form || !obj) return;
    var p = obj.payload || {};
    form.reset();
    form.workflow_id.value = obj.object_id;
    form.name.value = p.name || "";
    form.task_type.value = p.task_type || "";
    form.description.value = p.description || "";
    form.nodes.value = JSON.stringify(p.nodes || [], null, 2);
    fitWorkflowNodes();
    setWorkflowMode(obj.object_id);
    setMsg("workflowMsg", "info", "编辑中…");
    var card = document.getElementById("workflowFormCard");
    if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "start" });
    if (form.name.focus) form.name.focus();
  }

  function addNodeTemplate(type, label) {
    var form = document.getElementById("workflowForm");
    if (!form) return;
    var nodes;
    try { nodes = JSON.parse(form.nodes.value || "[]"); }
    catch (e) { setMsg("workflowMsg", "bad", "节点 JSON 解析失败：" + e.message); return; }
    if (!Array.isArray(nodes)) { setMsg("workflowMsg", "bad", "节点 JSON 必须是数组"); return; }
    var templates = {
      rule_check: { node_id: "R1", name: "规则门", type: "rule_check", task_type: form.task_type.value || "change_detection" },
      change_detection: { node_id: "C2", name: "逐格差分", type: "change_detection", threshold: 1.0, min_area_m2: 150 },
      artifact_register: { node_id: "A3", name: "成果登记", type: "artifact_register", path_key: "deliverable_path", kind: "change_mask" },
      model_chat: { node_id: "M4", name: "模型说明", type: "model_chat", prompt: "描述本次变化", prompt_key: "prompt" }
    };
    var spec = templates[type];
    if (!spec) return;
    spec = JSON.parse(JSON.stringify(spec));
    var prefix = (String(spec.node_id).match(/^[A-Za-z]+/) || ["N"])[0].toUpperCase();
    var usedIds = {};
    var usedNames = {};
    nodes.forEach(function (node) {
      usedIds[node.node_id] = true;
      usedNames[node.name] = true;
    });
    var number = 1;
    while (usedIds[prefix + number]) number += 1;
    spec.node_id = prefix + number;
    var baseName = spec.name;
    var name = baseName;
    var suffix = 2;
    while (usedNames[name]) { name = baseName + " " + suffix; suffix += 1; }
    spec.name = name;
    nodes.push(spec);
    form.nodes.value = JSON.stringify(nodes, null, 2);
    fitWorkflowNodes();
    setMsg("workflowMsg", "ok", "已加入模板：" + label);
  }

  var workflowReload = document.getElementById("workflowReload");
  if (workflowReload) workflowReload.addEventListener("click", loadWorkflows);

  var workflowTable = document.getElementById("workflowTable");
  if (workflowTable) workflowTable.addEventListener("click", function (ev) {
    var target = ev.target;
    if (!target || !target.closest) return;
    var edit = target.closest("[data-workflow-edit]");
    if (edit) {
      var obj = workflowObject(edit.getAttribute("data-workflow-edit"));
      if (obj) fillWorkflowForm(obj);
      return;
    }
    var use = target.closest("[data-workflow-use]");
    if (use) {
      var workflowId = use.getAttribute("data-workflow-use");
      var select = document.getElementById("workflowSelect");
      select.value = workflowId;
      var form = document.getElementById("workflowRunForm");
      if (form && form.scrollIntoView) form.scrollIntoView({ behavior: "smooth", block: "center" });
      if (form && form.task_id && form.task_id.focus) form.task_id.focus();
      setMsg("workflowRunMsg", "info", "已带入执行：" + workflowId);
    }
  });

  Array.prototype.forEach.call(document.querySelectorAll("[data-node-template]"), function (button) {
    button.addEventListener("click", function () {
      addNodeTemplate(button.getAttribute("data-node-template"), (button.textContent || "").trim());
    });
  });

  var workflowForm = document.getElementById("workflowForm");
  if (workflowForm) workflowForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var nodes;
    try { nodes = JSON.parse(workflowForm.nodes.value || "[]"); }
    catch (e) { setMsg("workflowMsg", "bad", "节点 JSON 解析失败：" + e.message); return; }
    var editingId = state.workflowEditId;
    var body = {
      workflow_id: (workflowForm.workflow_id.value || "").trim(),
      name: (workflowForm.name.value || "").trim(),
      task_type: (workflowForm.task_type.value || "").trim(),
      description: (workflowForm.description.value || "").trim(),
      nodes: nodes
    };
    if (!editingId && !body.workflow_id) {
      setMsg("workflowMsg", "bad", "流程编号不能为空");
      return;
    }
    var url = editingId ? "/api/v1/workflows/" + encodeURIComponent(editingId) : "/api/v1/workflows";
    var payload = editingId ? {
      name: body.name,
      task_type: body.task_type,
      description: body.description,
      nodes: nodes
    } : body;
    setMsg("workflowMsg", "info", editingId ? "更新中…" : "登记中…");
    api(url, { method: "POST", token: currentToken(), body: payload }).then(function (res) {
      if (editingId ? res.status === 200 : res.status === 201) {
        var saved = (res.body && res.body.workflow) || {};
        var version = saved.version ? " · v" + saved.version : "";
        var done = (editingId ? "已更新 " : "已登记 ") + (saved.object_id || body.workflow_id) + version;
        resetWorkflowForm();
        setMsg("workflowMsg", "ok", done);
        loadWorkflows();
        return;
      }
      var reason = (res.body && res.body.error) || ("接口 " + res.status);
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 workflow:write 权限：" : (editingId ? "更新被拒：" : "登记被拒：");
      setMsg("workflowMsg", "bad", prefix + reason);
    }).catch(function () { setMsg("workflowMsg", "bad", "网络或服务不可达"); });
  });

  var workflowCancel = document.getElementById("workflowCancelBtn");
  if (workflowCancel) workflowCancel.addEventListener("click", function () {
    resetWorkflowForm();
    setMsg("workflowMsg", "info", "已取消编辑");
  });

  var workflowRunForm = document.getElementById("workflowRunForm");
  if (workflowRunForm) workflowRunForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var workflowId = document.getElementById("workflowSelect").value;
    if (!workflowId) { setMsg("workflowRunMsg", "bad", "先选择一份流程定义"); return; }
    var resumeRunId = document.getElementById("resumeRunSelect").value;
    var context;
    try { context = JSON.parse(workflowRunForm.context.value || "{}"); }
    catch (e) { setMsg("workflowRunMsg", "bad", "执行上下文 JSON 解析失败：" + e.message); return; }
    var body = { task_id: (workflowRunForm.task_id.value || "").trim(), context: context };
    var target = resumeRunId
      ? "/api/v1/workflow-runs/" + encodeURIComponent(resumeRunId) + "/resume"
      : "/api/v1/workflows/" + encodeURIComponent(workflowId) + "/execute";
    var payload = resumeRunId
      ? { workflow_id: workflowId, task_id: body.task_id, context: context }
      : body;
    setMsg("workflowRunMsg", "info", resumeRunId ? "恢复中…" : "执行中…");
    api(target, {
      method: "POST", token: currentToken(), body: payload
    }).then(function (res) {
      if (res.status === 200 && res.body && res.body.run) {
        setMsg("workflowRunMsg", "ok", (resumeRunId ? "恢复已记录：" : "运行已记录：") + res.body.run.run_id);
        renderWorkflowRun(res.body);
        if (resumeRunId) {
          document.getElementById("resumeRunSelect").value = "";
          updateResumeButton();
        }
        loadRuns();
        return;
      }
      var reason = (res.body && res.body.error) || ("接口 " + res.status);
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 workflow:execute 权限：" : (resumeRunId ? "恢复被拒：" : "执行被拒：");
      setMsg("workflowRunMsg", "bad", prefix + reason);
    }).catch(function () { setMsg("workflowRunMsg", "bad", "网络或服务不可达"); });
  });

  function renderWorkflowRun(result) {
    var out = document.getElementById("workflowRunOut");
    var run = result.run || {};
    var nodes = run.node_runs || [];
    out.textContent = "run_id  " + (run.run_id || "—") + "\n" +
      "status  " + (run.status || result.status || "—") + "\n" +
      "task    " + (result.task_id || "未挂任务") + "\n" +
      nodes.map(function (node) {
        return "[" + (node.status || "—") + "] " + node.node_id + " · " + node.name + " · " + (node.detail || "");
      }).join("\n");
  }

  /* ---------- 规则 ---------- */
  function loadRules() {
    var packs = document.getElementById("packList");
    packs.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/rules 取规则包。");
    api("/api/v1/rules").then(function (res) {
      if (res.status !== 200) {
        packs.innerHTML = emptyBox("未", "规则接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.rules = res.body || {};
      var list = state.rules.packs || [];
      var rules = state.rules.rules || [];
      document.getElementById("rulesCount").textContent = rules.length + " 条 / " + list.length + " 包";
      if (!list.length) {
        packs.innerHTML = emptyBox("空", "没有已载规则包", "规则包是数据文件，装载前会整包校验。");
      } else {
        packs.innerHTML = list.map(function (pack) {
          return '<div class="pack"><span class="pid">' + esc(pack.pack_id || "—") + "</span>" +
            "<span>" + esc(pack.rule_count !== undefined ? pack.rule_count + " rules" : "") + "</span>" +
            '<span class="pv">v' + esc(pack.version || "—") + "</span>" +
            "<span>" + esc((pack.task_types || []).join(" · ")) + "</span></div>";
        }).join("");
      }
      renderRuleGroups(rules);
    }).catch(function () { packs.innerHTML = emptyBox("断", "取不到规则包", "服务未启动或网络不可达。"); });
  }

  function renderRuleGroups(rules) {
    var box = document.getElementById("ruleGroups");
    if (!rules.length) { box.innerHTML = ""; return; }
    var groups = {};
    rules.forEach(function (rule) { (groups[rule.task_type] = groups[rule.task_type] || []).push(rule); });
    var html = "";
    Object.keys(groups).forEach(function (taskType) {
      html += '<div class="card"><h3>' + esc(taskType) + ' <span class="zh">任务类型</span><span class="right"><span class="pill idle">' +
        groups[taskType].length + " 条</span></span></h3>";
      groups[taskType].forEach(function (rule) {
        var severity = String(rule.severity || "").toLowerCase();
        var chip = severity === "warning"
          ? '<span class="pill warn">警告</span>'
          : '<span class="pill fail">阻断</span>';
        html += '<div class="rule-row">' +
          '<div class="rid">' + esc(rule.rule_id || rule.id) + "</div>" +
          "<div><div class=\"rt\">" + esc(rule.rule_name || rule.title) + "</div>" +
          '<div class="rd">' + esc(rule.description || rule.evidence_requirement || "") + "</div></div>" +
          '<div class="rr">' + chip + "</div>" +
          "</div>";
      });
      html += "</div>";
    });
    box.innerHTML = html;
  }

  /* ---------- 成果 ---------- */
  function loadArtifacts() {
    var box = document.getElementById("artifactTable");
    var token = currentToken();
    if (!token) {
      document.getElementById("artifactsCount").textContent = "需令牌";
      box.innerHTML = emptyBox("钥", "成果簿需要令牌", "读取 <code>/api/v1/artifacts</code> 需要 <code>audit:read</code> 权限。在右上角填入令牌后再刷新。");
      return;
    }
    box.innerHTML = emptyBox("阅", "读取中", "正在取成果登记簿。");
    api("/api/v1/artifacts", { token: token }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        document.getElementById("artifactsCount").textContent = "拒绝 " + res.status;
        box.innerHTML = emptyBox("钥", "令牌不被接受", "服务端原由：<code>" + esc((res.body && res.body.error) || res.status) + "</code>。");
        return;
      }
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "成果接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.artifacts = (res.body && res.body.artifacts) || [];
      document.getElementById("artifactsCount").textContent = state.artifacts.length + " 个";
      renderArtifacts();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到成果簿", "服务未启动或网络不可达。"); });
  }

  function renderArtifacts() {
    var box = document.getElementById("artifactTable");
    var query = state.artifactQuery.trim().toLowerCase();
    var rows = state.artifacts.filter(function (row) {
      if (!query) return true;
      return [row.artifact_id, row.label, row.path, row.task_id, row.deliverable_id, row.kind]
        .filter(Boolean).join(" ").toLowerCase().indexOf(query) >= 0;
    });
    if (!rows.length) {
      box.innerHTML = emptyBox("空", "还没有登记成果",
        "登记发生在运行内：规则门通过后，节点才把真实文件的哈希写进成果簿。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Artifact</th><th>File</th><th>Kind</th><th>sha256</th><th>Size</th><th>Task</th><th>Deliverable</th></tr></thead><tbody>';
    rows.forEach(function (row) {
      html += "<tr>" +
        '<td class="id">' + esc(row.artifact_id) + "</td>" +
        '<td class="wrap">' + esc(row.path) + "</td>" +
        '<td class="dim">' + esc(row.kind) + "</td>" +
        '<td class="dim">' + shortHash(row.sha256) + "…</td>" +
        '<td class="num">' + bytes(row.size) + "</td>" +
        '<td class="id">' + esc(row.task_id || "—") + "</td>" +
        '<td class="id">' + esc(row.deliverable_id || "—") + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }
  var artifactSearch = document.getElementById("artifactSearch");
  if (artifactSearch) artifactSearch.addEventListener("input", function () { state.artifactQuery = artifactSearch.value; renderArtifacts(); });
  document.getElementById("artifactReload").addEventListener("click", loadArtifacts);

  /* ---------- 审计 ---------- */
  function loadAudit() {
    var token = currentToken();
    var mini = document.getElementById("auditMini");
    var box = document.getElementById("auditTable");
    var pill = document.getElementById("auditPill");
    if (!token) {
      pill.className = "pill idle"; pill.textContent = "需令牌";
      mini.innerHTML = emptyBox("未", "尚未读取", "审计接口需要 <code>audit:read</code> 令牌。");
      box.innerHTML = emptyBox("钥", "审计流需要令牌", "在右上角填入令牌后读取 <code>/api/v1/audit</code>。");
      return;
    }
    api("/api/v1/audit", { token: token }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        pill.className = "pill fail"; pill.textContent = "拒绝 " + res.status;
        var reason = (res.body && res.body.error) || res.status;
        mini.innerHTML = emptyBox("钥", "令牌不被接受", "服务端原由：<code>" + esc(reason) + "</code>。");
        box.innerHTML = emptyBox("钥", "令牌不被接受", "服务端原由：<code>" + esc(reason) + "</code>。");
        return;
      }
      if (res.status !== 200) {
        pill.className = "pill fail"; pill.textContent = "接口 " + res.status;
        mini.innerHTML = emptyBox("未", "审计接口不可用", "接口返回 " + res.status + "。");
        box.innerHTML = emptyBox("未", "审计接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.audit = (res.body && res.body.rows) || [];
      pill.className = "pill pass"; pill.textContent = state.audit.length + " 条";
      document.getElementById("auditCount").textContent = state.audit.length + " 条";
      renderAudit();
    }).catch(function () {
      pill.className = "pill fail"; pill.textContent = "离线";
      mini.innerHTML = emptyBox("断", "取不到审计流", "服务未启动或网络不可达。");
      box.innerHTML = emptyBox("断", "取不到审计流", "服务未启动或网络不可达。");
    });
  }

  function renderAudit() {
    var rows = (state.audit || []).slice().reverse();
    var mini = document.getElementById("auditMini");
    var box = document.getElementById("auditTable");
    var query = state.auditQuery.trim().toLowerCase();
    var filtered = rows.filter(function (row) {
      if (!query) return true;
      return [row.path, row.reason, row.token_fp, row.decision, row.method]
        .filter(Boolean).join(" ").toLowerCase().indexOf(query) >= 0;
    });
    if (!rows.length) {
      var none = emptyBox("空", "还没有审计记录", "写入口每次放行或拒绝都会落一条；这里读的是真实日志文件。");
      mini.innerHTML = none; box.innerHTML = none; return;
    }
    mini.innerHTML = '<ul class="tl">' + rows.slice(0, 6).map(function (row) {
      return '<li><span class="t">' + esc(String(row.at || "").slice(11, 19)) + "</span>" +
        '<span class="e"><b>' + esc(row.decision) + "</b> · " + esc(row.method) + " " + esc(row.path) +
        ' · <span class="dim">' + esc(row.reason) + "</span></span></li>";
    }).join("") + "</ul>";
    if (!filtered.length) {
      box.innerHTML = emptyBox("空", "没有符合条件的审计记录", "筛选只在已加载的记录里做。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>At</th><th>Method</th><th>Path</th><th>Token fp</th><th>Decision</th><th>Reason</th><th>Status</th></tr></thead><tbody>';
    filtered.forEach(function (row) {
      var decision = row.decision === "allow" ? "pass" : "fail";
      html += "<tr>" +
        '<td class="dim">' + esc(row.at) + "</td>" +
        '<td class="dim">' + esc(row.method) + "</td>" +
        '<td class="id">' + esc(row.path) + "</td>" +
        '<td class="dim">' + esc(row.token_fp) + "</td>" +
        '<td><span class="pill ' + decision + '">' + esc(row.decision) + "</span></td>" +
        '<td class="wrap">' + esc(row.reason) + "</td>" +
        '<td class="num">' + esc(row.status) + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }
  var auditSearch = document.getElementById("auditSearch");
  if (auditSearch) auditSearch.addEventListener("input", function () { state.auditQuery = auditSearch.value; renderAudit(); });
  document.getElementById("auditReload").addEventListener("click", loadAudit);

  /* ---------- 数据 ---------- */
  function formValues(form) {
    var out = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.name) out[el.name] = String(el.value || "").trim();
    });
    return out;
  }

  function loadData() {
    return Promise.all([loadProjects(), loadDatasets(), loadCatalog()]);
  }

  function loadProjects() {
    var box = document.getElementById("projectRows");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/projects 取项目清单。");
    return api("/api/v1/projects").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "项目接口不可用", "接口返回 " + res.status + "；不伪造项目。");
        return;
      }
      state.projects = (res.body && res.body.projects) || [];
      document.getElementById("projectsCount").textContent = state.projects.length + " 个";
      renderProjects();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到项目清单", "服务未启动或网络不可达。"); });
  }

  function renderProjects() {
    var box = document.getElementById("projectRows");
    if (!state.projects.length) {
      box.innerHTML = emptyBox("空", "还没有登记项目", "项目是任务的前置：先登记编号、类型、区域、CRS 与高程基准。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Project</th><th>Code</th><th>Name</th><th>Type</th><th>Area</th><th>CRS</th><th>Datum</th></tr></thead><tbody>';
    state.projects.forEach(function (row) {
      var p = row.payload || {};
      html += "<tr>" +
        '<td class="id">' + esc(row.object_id) + "</td>" +
        '<td class="dim">' + esc(p.project_code) + "</td>" +
        "<td>" + esc(p.name) + "</td>" +
        '<td class="dim">' + esc(p.project_type) + "</td>" +
        "<td>" + esc(p.area) + "</td>" +
        '<td class="id">' + esc(p.crs) + "</td>" +
        '<td class="wrap">' + esc(p.vertical_datum) + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  document.getElementById("projectForm").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var token = currentToken();
    if (!token) { setMsg("projectMsg", "bad", "先在右上角填令牌（需要 project:write 权限）"); return; }
    setMsg("projectMsg", "", "提交中…");
    api("/api/v1/projects", { method: "POST", token: token, body: formValues(ev.target) }).then(function (res) {
      if (res.status === 201) {
        var project = (res.body && res.body.project) || {};
        setMsg("projectMsg", "ok", "已登记 " + project.object_id + "（" + (project.payload || {}).project_code + "）");
        ev.target.reset();
        loadProjects(); loadOverview();
        return;
      }
      if (res.status === 404) { setMsg("projectMsg", "bad", "写入口未配置：服务以只读方式启动"); return; }
      var reason = (res.body && res.body.error) || res.status;
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 project:write 权限：" : "登记被拒：";
      setMsg("projectMsg", "bad", prefix + reason);
    }).catch(function () { setMsg("projectMsg", "bad", "网络或服务不可达"); });
  });
  document.getElementById("projectReload").addEventListener("click", loadProjects);

  function datasetMatches(row, query) {
    if (!query) return true;
    var p = row.payload || {};
    var haystack = [row.object_id, p.path, p.project_id, p.task_id, p.crs, p.label]
      .filter(function (value) { return value !== null && value !== undefined; })
      .join(" ").toLowerCase();
    return haystack.indexOf(query) >= 0;
  }

  function filteredDatasets() {
    var query = state.datasetQuery.trim().toLowerCase();
    return state.datasets.filter(function (row) { return datasetMatches(row, query); });
  }

  function updateDatasetCount(shown) {
    var pill = document.getElementById("datasetsCount");
    if (!pill) return;
    pill.textContent = state.datasetQuery.trim()
      ? shown + " / " + state.datasets.length + " 个"
      : state.datasets.length + " 个";
  }

  function loadDatasets() {
    var box = document.getElementById("datasetRows");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/datasets 取数据集清单。");
    return api("/api/v1/datasets").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "数据集接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.datasets = (res.body && res.body.datasets) || [];
      updateDatasetCount(filteredDatasets().length);
      renderDatasets();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到数据集", "服务未启动或网络不可达。"); });
  }

  function renderDatasets() {
    var box = document.getElementById("datasetRows");
    var rows = filteredDatasets();
    updateDatasetCount(rows.length);
    if (!state.datasets.length) {
      box.innerHTML = emptyBox("空", "还没有登记数据集", "登记会真实读文件：算 sha256、取 sidecar CRS；缺一项即拒绝。");
      return;
    }
    if (!rows.length) {
      box.innerHTML = emptyBox("筛", "没有匹配的数据集", '当前关键词没有命中。调整筛选，或 <button class="btn ghost sm" data-clear-dataset type="button">清除筛选</button>。');
      return;
    }
    var html = '<table class="tbl data-table"><thead><tr><th>Dataset</th><th>Project · Task</th><th>CRS</th><th>Size</th><th></th></tr></thead><tbody>';
    rows.forEach(function (row) {
      var p = row.payload || {};
      html += "<tr>" +
        '<td class="id">' + esc(row.object_id) + '<div class="sub">' + esc(p.path) + "</div></td>" +
        '<td class="id">' + esc(p.project_id) + '<div class="sub">' + esc(p.task_id || "—") + "</div></td>" +
        '<td class="id">' + esc(p.crs) + "</td>" +
        '<td class="num">' + bytes(p.size_bytes) + '<div class="sub">#' + shortHash(p.sha256) + "</div></td>" +
        '<td class="act dataset-actions"><button class="btn ghost sm" data-profile="' + esc(row.object_id) + '">统计</button>' +
        '<button class="btn ghost sm" data-validate="' + esc(row.object_id) + '">复核</button></td>' +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  function renderDatasetProfile(profile) {
    var body = document.getElementById("datasetProfileBody");
    if (!body) return;
    var p = profile || {};
    var valid = Number(p.valid_cells);
    var nodata = Number(p.nodata_cells);
    var nonFinite = Number(p.non_finite_cells);
    var total = valid + nodata + nonFinite;
    if (!isFinite(total) || total <= 0) total = 0;
    var validPct = total ? valid / total * 100 : 0;
    var unit = p.linear_unit ? " " + p.linear_unit : "";
    var bounds = Array.isArray(p.bounds)
      ? "[" + p.bounds.map(function (value) { return fmtNum(value, 3); }).join(", ") + "]"
      : "—";
    var area = p.area_basis === "map_units" ? p.footprint_area_map_units : p.footprint_area_m2;
    var cellArea = p.area_basis === "map_units" ? null : p.cell_area_m2;
    var crsText = p.crs || "—";
    var crsNote = [p.crs_model, p.linear_unit].filter(Boolean).join(" · ") || "—";
    var gridSize = fmtNum(p.ncols, 0) + " × " + fmtNum(p.nrows, 0);
    var cellsize = fmtNum(p.cellsize, 6) + " × " + fmtNum(p.cellsize_y, 6) + unit;

    function cell(name, value, detail, extraClass) {
      return '<div class="profile-cell' + (extraClass ? " " + extraClass : "") + '">' +
        '<div class="k">' + esc(name) + '</div><div class="v">' + value + "</div>" +
        (detail ? '<div class="d">' + detail + "</div>" : "") + "</div>";
    }

    body.innerHTML = '<div class="profile-grid">' +
      cell("GRID", gridSize, "有效像元 " + fmtNum(valid, 0)) +
      cell("BAND", fmtNum(p.band, 0) + " / " + fmtNum(p.bands, 0), "单波段读取") +
      cell("CELL", esc(cellsize), "像元尺寸") +
      cell("CRS", esc(crsText), esc(crsNote)) +
      cell("VALID", fmtNum(valid, 0) + " · " + validPct.toFixed(2) + "%",
        '<div class="meter"><i style="width:' + Math.max(0, Math.min(100, validPct)).toFixed(2) + '%"></i></div>') +
      cell("NODATA", fmtNum(nodata, 0), "标记值 " + esc(fmtNum(p.nodata, 6)) + " · " + (total ? (nodata / total * 100).toFixed(2) + "%" : "—")) +
      cell("NON-FINITE", fmtNum(nonFinite, 0), "NaN / Inf 已剔除，不参与值域") +
      cell("RANGE", esc(fmtNum(p.min, 6)) + " … " + esc(fmtNum(p.max, 6)), "NODATA 已剔除") +
      cell("MEAN", esc(fmtNum(p.mean, 6)), "有效像元均值") +
      cell("FOOTPRINT", esc(fmtArea(area, p.area_basis)),
        cellArea === null || cellArea === undefined ? esc(p.area_basis || "—") : "单元 " + esc(fmtArea(cellArea, "m2")) ) +
      cell("I/O", '<span class="pill info">' + esc(p.format || "—") + '</span>', esc(p.read_mode || "—"), "wide") +
      cell("BOUNDS", '<span style="font-size:calc(12px * var(--fs-zoom))">' + esc(bounds) + '</span>', "xmin, ymin, xmax, ymax", "full") +
      "</div>";
  }

  function loadDatasetProfile(id, band) {
    var card = document.getElementById("datasetProfileCard");
    var body = document.getElementById("datasetProfileBody");
    if (!card || !body || !id) return Promise.resolve();
    var row = state.datasets.filter(function (item) { return item.object_id === id; })[0] || {};
    var p = row.payload || {};
    var bandInput = document.getElementById("datasetProfileBand");
    band = band || (state.profileDatasetId === id && bandInput ? Number(bandInput.value) : 1);
    if (!isFinite(band) || band < 1 || band !== Math.floor(band)) {
      body.innerHTML = '<div class="profile-error"><b>波段无效</b>：必须是正整数。</div>';
      return Promise.resolve();
    }
    state.profileDatasetId = id;
    card.hidden = false;
    document.getElementById("datasetProfileName").textContent = id + (p.label ? " · " + p.label : "");
    document.getElementById("datasetProfilePath").textContent = p.path || "—";
    if (bandInput) {
      bandInput.value = String(band);
      bandInput.max = String(p.bands || 1);
    }
    body.innerHTML = '<div class="profile-empty"><div class="empty-mini">读取真实像元中…</div></div>';
    return api("/api/v1/datasets/" + encodeURIComponent(id) + "/profile?band=" + encodeURIComponent(band))
      .then(function (res) {
        if (res.status === 200) {
          renderDatasetProfile(res.body || {});
          setMsg("datasetMsg", "ok", id + " · band " + band + " 统计已读取");
          return;
        }
        var reason = (res.body && res.body.error) || ("profile 返回 " + res.status);
        var label = res.status === 409 ? "文件在登记后被改写，请重新登记" : res.status === 404 ? "统计不可用" : "统计失败";
        body.innerHTML = '<div class="profile-error"><b>' + esc(label) + "</b>：" + esc(reason) + "</div>";
        setMsg("datasetMsg", "bad", id + " 统计 " + res.status + "：" + reason);
      }).catch(function () {
        body.innerHTML = '<div class="profile-error"><b>网络或服务不可达</b>：统计请求没有返回。</div>';
        setMsg("datasetMsg", "bad", "统计请求失败：网络或服务不可达");
      });
  }

  document.getElementById("datasetRows").addEventListener("click", function (ev) {
    var clear = ev.target.closest("[data-clear-dataset]");
    if (clear) {
      var queryInput = document.getElementById("datasetQuery");
      if (queryInput) queryInput.value = "";
      state.datasetQuery = "";
      renderDatasets();
      return;
    }
    var profileButton = ev.target.closest("[data-profile]");
    if (profileButton) {
      var profileId = profileButton.getAttribute("data-profile");
      profileButton.disabled = true;
      loadDatasetProfile(profileId, 1).then(function () { profileButton.disabled = false; });
      return;
    }
    var button = ev.target.closest("[data-validate]");
    if (!button) return;
    var id = button.getAttribute("data-validate");
    button.disabled = true;
    api("/api/v1/datasets/" + encodeURIComponent(id) + "/validate").then(function (res) {
      button.disabled = false;
      if (res.status !== 200) { setMsg("datasetMsg", "bad", (res.body && res.body.error) || ("复核返回 " + res.status)); return; }
      var result = res.body || {};
      var failed = (result.checks || []).filter(function (check) { return check.status !== "PASS"; });
      if (result.status === "PASS") setMsg("datasetMsg", "ok", id + " 复核 PASS：哈希与 CRS 未变");
      else setMsg("datasetMsg", "bad", id + " 复核 " + (result.status || "FAIL") + "：" + failed.map(function (check) { return check.name + " " + check.detail; }).join("；"));
    }).catch(function () { button.disabled = false; setMsg("datasetMsg", "bad", "网络或服务不可达"); });
  });

  var datasetQuery = document.getElementById("datasetQuery");
  if (datasetQuery) {
    datasetQuery.addEventListener("input", function () {
      state.datasetQuery = datasetQuery.value || "";
      renderDatasets();
    });
    datasetQuery.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        datasetQuery.value = "";
        state.datasetQuery = "";
        renderDatasets();
      }
    });
  }
  var datasetProfileRead = document.getElementById("datasetProfileRead");
  if (datasetProfileRead) {
    datasetProfileRead.addEventListener("click", function () {
      if (!state.profileDatasetId) return;
      datasetProfileRead.disabled = true;
      var band = Number(document.getElementById("datasetProfileBand").value);
      loadDatasetProfile(state.profileDatasetId, band).then(function () { datasetProfileRead.disabled = false; });
    });
  }
  var datasetProfileClose = document.getElementById("datasetProfileClose");
  if (datasetProfileClose) {
    datasetProfileClose.addEventListener("click", function () {
      var card = document.getElementById("datasetProfileCard");
      if (card) card.hidden = true;
      state.profileDatasetId = "";
    });
  }

  document.getElementById("datasetForm").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var token = currentToken();
    if (!token) { setMsg("datasetMsg", "bad", "先在右上角填令牌（需要 dataset:write 权限）"); return; }
    var values = formValues(ev.target);
    if (!values.project_id || !values.path) { setMsg("datasetMsg", "bad", "项目 id 与文件路径必填"); return; }
    setMsg("datasetMsg", "", "读取文件中…");
    api("/api/v1/datasets", { method: "POST", token: token, body: values }).then(function (res) {
      if (res.status === 201) {
        var dataset = (res.body && res.body.dataset) || {};
        var p = dataset.payload || {};
        setMsg("datasetMsg", "ok", "已登记 " + dataset.object_id + "（sha256 " + shortHash(p.sha256) + "…，CRS " + p.crs + "）");
        ev.target.reset();
        loadDatasets(); loadOverview();
        return;
      }
      if (res.status === 404) { setMsg("datasetMsg", "bad", "写入口未配置：服务以只读方式启动"); return; }
      var reason = (res.body && res.body.error) || res.status;
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 dataset:write 权限：" : "登记被拒：";
      setMsg("datasetMsg", "bad", prefix + reason);
    }).catch(function () { setMsg("datasetMsg", "bad", "网络或服务不可达"); });
  });
  document.getElementById("datasetReload").addEventListener("click", loadDatasets);

  function loadCatalog() {
    var box = document.getElementById("catalogRows");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/catalog 取模型、工具与 Agent。");
    return api("/api/v1/catalog").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "目录接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.catalog = res.body || {};
      var count = (state.catalog.models || []).length + (state.catalog.tools || []).length + (state.catalog.agents || []).length;
      document.getElementById("catalogCount").textContent = count + " 项";
      renderCatalog();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到目录", "服务未启动或网络不可达。"); });
  }

  function renderCatalog() {
    var box = document.getElementById("catalogRows");
    var catalog = state.catalog || {};
    var groups = [
      ["Models", catalog.models || []],
      ["Tools", catalog.tools || []],
      ["Agents", catalog.agents || []]
    ];
    var total = groups[0][1].length + groups[1][1].length + groups[2][1].length;
    if (!total) {
      box.innerHTML = emptyBox("空", "目录还是空的", "登记模型 / 工具 / Agent 后，这里按可用性列出；不可用的带原因。");
      return;
    }
    box.innerHTML = groups.map(function (group) {
      var rows = group[1];
      var body = rows.length ? rows.map(function (row) {
        var p = row.payload || {};
        var ok = p.available === true;
        return '<div class="objrow"><div><div class="rt">' + esc(p.name || row.object_id) +
          ' <span class="dim">' + esc(row.object_id) + " · v" + esc(p.version) + "</span></div>" +
          '<div class="rd">' + esc(p.capability || p.category || p.strategy || "") + " · " + esc(p.adapter || "") +
          (p.reason ? " · " + esc(p.reason) : "") + "</div></div>" +
          '<span class="pill ' + (ok ? "pass" : "idle") + '">' + (ok ? "可用" : "不可用") + "</span></div>";
      }).join("") : '<div class="empty-mini">尚无记录</div>';
      return '<div class="catcol"><h4>' + group[0] + ' <span class="pill idle">' + rows.length + "</span></h4>" + body + "</div>";
    }).join("");
  }
  document.getElementById("catalogReload").addEventListener("click", loadCatalog);

  /* ---------- 真实模型运行时 ---------- */
  function loadModelRuntime() {
    var box = document.getElementById("modelRuntimeRows");
    if (!box) return;
    box.innerHTML = '<div class="empty-mini">读取 /api/v1/model-runtime…</div>';
    api("/api/v1/model-runtime").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "模型运行时接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.modelRuntime = (res.body && res.body.runtime) || {};
      renderModelRuntime(state.modelRuntime);
    }).catch(function () {
      box.innerHTML = emptyBox("断", "取不到模型运行时", "服务未启动或网络不可达。");
    });
  }

  function renderModelRuntime(runtime) {
    var box = document.getElementById("modelRuntimeRows");
    var status = document.getElementById("modelRuntimeStatus");
    var ready = runtime.configured === true;
    status.className = "pill " + (ready ? "pass" : "idle");
    status.textContent = ready ? "READY" : "NOT_CONFIGURED";
    var cells = [
      ["State", ready ? "真实端点已配置" : "尚未配置", ""],
      ["Model", runtime.model || "—", "dim"],
      ["Endpoint", runtime.endpoint || "—", "dim"],
      ["Auth", runtime.authentication === "bearer" ? "Bearer（密钥在服务端）" : "无密钥（本地端点）", ""],
      ["Timeout", (runtime.timeout_s || "—") + " s", "dim"]
    ];
    box.innerHTML = cells.map(function (cell) {
      return '<div class="runtime-cell"><div class="k">' + esc(cell[0]) + '</div><div class="v ' +
        cell[2] + '">' + esc(cell[1]) + "</div></div>";
    }).join("");
    if (!ready) {
      document.getElementById("modelOutput").textContent =
        "未配置： " + (runtime.reason || "缺少 GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME") +
        "\n\n在服务进程的环境里设置变量后重启；服务端不会生成占位回复。";
    }
  }

  function modelRequest(path, body, label) {
    var token = currentToken();
    var out = document.getElementById("modelOutput");
    if (!token) {
      out.textContent = "需要令牌：请在右上角填入具备 model:invoke 权限的调用方令牌。";
      return;
    }
    out.textContent = label + "中…";
    api(path, { method: "POST", token: token, body: body }).then(function (res) {
      if (res.status === 200 && res.body && res.body.result) {
        var r = res.body.result;
        out.textContent = r.text + "\n\n— " + (r.model || "") + " · " + (r.elapsed_ms || "?") + " ms · token " +
          ((r.usage && r.usage.total_tokens) || "—");
        if (res.body.runtime) { state.modelRuntime = res.body.runtime; renderModelRuntime(state.modelRuntime); }
        return;
      }
      var reason = (res.body && res.body.error) || ("HTTP " + res.status);
      out.textContent = "调用失败：" + reason;
      if (res.status === 404) out.textContent = "写入口未配置：服务以只读方式启动。";
    }).catch(function () {
      out.textContent = "网络或服务不可达，未收到模型回复。";
    });
  }

  var modelProbe = document.getElementById("modelProbe");
  if (modelProbe) modelProbe.addEventListener("click", function () {
    modelRequest("/api/v1/model-runtime/probe", {}, "真实连接测试");
  });
  var modelRun = document.getElementById("modelRun");
  if (modelRun) modelRun.addEventListener("click", function () {
    var prompt = (document.getElementById("modelPrompt").value || "").trim();
    if (!prompt) { document.getElementById("modelOutput").textContent = "提示词不能为空。"; return; }
    modelRequest("/api/v1/model-runtime/chat", { prompt: prompt, max_tokens: 512 }, "运行模型");
  });


  /* ---------- 审核 ---------- */
  function loadReviews() {
    var box = document.getElementById("reviewRows");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/reviews 取审核记录。");
    return api("/api/v1/reviews").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "审核接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.reviews = (res.body && res.body.reviews) || [];
      document.getElementById("reviewsCount").textContent = state.reviews.length + " 条";
      renderReviews();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到审核记录", "服务未启动或网络不可达。"); });
  }

  function decisionPill(decision) {
    var map = { APPROVE: "pass", REJECT: "fail", RERUN: "warn" };
    return '<span class="pill ' + (map[decision] || "idle") + '">' + esc(decision) + "</span>";
  }

  function renderReviews() {
    var box = document.getElementById("reviewRows");
    if (!state.reviews.length) {
      box.innerHTML = emptyBox("空", "还没有审核记录", "人工通过才置 accepted；驳回与返工必须写意见。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Review</th><th>Task</th><th>Deliverable</th><th>Reviewer</th><th>Decision</th><th>Opinion</th><th>At</th></tr></thead><tbody>';
    state.reviews.forEach(function (row) {
      var p = row.payload || {};
      html += "<tr>" +
        '<td class="id">' + esc(row.object_id) + "</td>" +
        '<td class="id">' + esc(p.task_id) + "</td>" +
        '<td class="id">' + esc(p.deliverable_id) + "</td>" +
        "<td>" + esc(p.reviewer) + "</td>" +
        "<td>" + decisionPill(p.decision) + "</td>" +
        '<td class="wrap">' + esc(p.opinion || "—") + "</td>" +
        '<td class="dim">' + esc(p.reviewed_at) + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  document.getElementById("reviewForm").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var token = currentToken();
    if (!token) { setMsg("reviewMsg", "bad", "先在右上角填令牌（需要 review:write 权限）"); return; }
    var values = formValues(ev.target);
    if (!values.task_id || !values.deliverable_id || !values.reviewer) {
      setMsg("reviewMsg", "bad", "任务、成果与审核人必填"); return;
    }
    if ((values.decision === "REJECT" || values.decision === "RERUN") && !values.opinion) {
      setMsg("reviewMsg", "bad", "驳回或返工必须写意见"); return;
    }
    setMsg("reviewMsg", "", "提交中…");
    api("/api/v1/reviews", { method: "POST", token: token, body: values }).then(function (res) {
      if (res.status === 201) {
        var review = (res.body && res.body.review) || {};
        var p = review.payload || {};
        setMsg("reviewMsg", "ok", "已记录 " + review.object_id + "（" + p.decision + "）");
        ev.target.reset();
        loadReviews(); loadOverview();
        return;
      }
      if (res.status === 404) { setMsg("reviewMsg", "bad", "写入口未配置：服务以只读方式启动"); return; }
      var reason = (res.body && res.body.error) || res.status;
      var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 review:write 权限：" : "审核被拒：";
      setMsg("reviewMsg", "bad", prefix + reason);
    }).catch(function () { setMsg("reviewMsg", "bad", "网络或服务不可达"); });
  });
  document.getElementById("reviewReload").addEventListener("click", loadReviews);

  /* ---------- 追溯 ---------- */
  function loadTrace() {
    var taskId = document.getElementById("traceTaskId").value.trim();
    var box = document.getElementById("traceBox");
    if (!taskId) { setMsg("traceMsg", "bad", "先填任务 id"); return; }
    box.innerHTML = emptyBox("阅", "读取中", "正在生成 " + taskId + " 的追溯链。");
    return api("/api/v1/tasks/" + encodeURIComponent(taskId) + "/trace").then(function (res) {
      if (res.status === 404) {
        document.getElementById("traceMsg").className = "wmsg bad";
        document.getElementById("traceMsg").textContent = "没有这个任务：" + taskId;
        box.innerHTML = emptyBox("空", "任务不存在", "追溯只对已登记任务生成，不补链。");
        return;
      }
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "追溯接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.trace = res.body || {};
      setMsg("traceMsg", state.trace.complete ? "ok" : "bad",
        state.trace.complete ? "追溯链完整" : "追溯链不完整：缺 " + (state.trace.missing || []).length + " 环");
      renderTrace();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到追溯链", "服务未启动或网络不可达。"); });
  }

  function renderTrace() {
    var box = document.getElementById("traceBox");
    var t = state.trace;
    if (!t) { box.innerHTML = ""; return; }
    var chips = [
      ["项目", t.project ? 1 : 0], ["数据集", (t.datasets || []).length],
      ["运行", (t.runs || []).length], ["规则节点", (t.rules || []).length],
      ["成果", (t.deliverables || []).length], ["文件", (t.artifacts || []).length],
      ["审核", (t.reviews || []).length]
    ];
    var missing = t.missing || [];
    var links = t.links || [];
    var html = '<div class="trace-sum">' +
      '<span class="pill ' + (t.complete ? "pass" : "fail") + '">' + (t.complete ? "COMPLETE" : "PARTIAL") + "</span>" +
      '<span class="dim">' + esc(t.task_id) + " · " + esc(t.task_status) + "</span>" +
      chips.map(function (chip) {
        return '<span class="tchip">' + chip[0] + ' <b class="' + (chip[1] ? "" : "zero") + '">' + chip[1] + "</b></span>";
      }).join("") + "</div>";

    if (missing.length) {
      html += '<div class="missbox"><h4>NOT_RECORDED</h4><ul>' + missing.map(function (m) {
        return "<li><b>" + esc(m.name) + "</b> · " + esc(m.reason) + "</li>";
      }).join("") + "</ul></div>";
    }
    if (links.length) {
      html += '<table class="tbl"><thead><tr><th>From</th><th>Kind</th><th>To</th></tr></thead><tbody>' +
        links.map(function (link) {
          return "<tr><td class=\"id\">" + esc(link.from || "—") + "</td><td class=\"dim\">" +
            esc(link.kind) + "</td><td class=\"id\">" + esc(link.to || "—") + "</td></tr>";
        }).join("") + "</tbody></table>";
    } else {
      html += '<div class="empty-mini">没有任何可连的环节。</div>';
    }
    box.innerHTML = html;
  }

  document.getElementById("traceLoad").addEventListener("click", loadTrace);
  document.getElementById("traceTaskId").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); loadTrace(); }
  });

  /* ---------- 质量检查 ---------- */
  function qualityStatusText(status) {
    var map = { PASS: "通过", FAIL: "失败", ERROR: "异常", PARTIAL: "部分", NOT_RECORDED: "未记录" };
    return map[status] || status || "—";
  }

  function qualityPill(status) {
    var map = { PASS: "pass", FAIL: "fail", ERROR: "fail", PARTIAL: "warn", NOT_RECORDED: "idle" };
    return '<span class="pill ' + (map[status] || "idle") + '">' + esc(status || "—") + "</span>";
  }

  function refreshQualityTargets() {
    var list = document.getElementById("qualityTargetList");
    var typeSelect = document.getElementById("qualityTargetType");
    if (!list || !typeSelect) return;
    var type = typeSelect.value === "deliverable" ? "deliverable" : "dataset";
    var rows = type === "deliverable" ? state.deliverables : state.datasets;
    list.innerHTML = rows.map(function (row) {
      var p = row.payload || {};
      var label = type === "deliverable"
        ? [p.name, p.kind, p.task_id].filter(Boolean).join(" · ")
        : [p.project_id, p.task_id, p.crs].filter(Boolean).join(" · ");
      return '<option value="' + esc(row.object_id) + '" label="' + esc(label || row.object_id) + '"></option>';
    }).join("");
  }

  function syncQualityTargetMode() {
    var select = document.getElementById("qualityTargetType");
    var panel = document.getElementById("qualityAccuracyPanel");
    if (!select) return;
    var deliverable = select.value === "deliverable";
    Array.prototype.forEach.call(document.querySelectorAll("[data-deliverable-only]"), function (el) {
      el.disabled = !deliverable;
    });
    if (panel) panel.classList.toggle("is-disabled", !deliverable);
    var hint = document.getElementById("qualityAccuracyHint");
    if (hint) {
      hint.textContent = deliverable
        ? "精度对比只对成果开放：参考真值掩膜必填，预测掩膜留空时使用成果登记路径；不填参考则报告写「未计算」。"
        : "精度对比只对成果开放：当前目标是数据集，参考 / 预测 / 阈值均不提交；切到成果后可启用。";
    }
    refreshQualityTargets();
  }

  function loadQualityTargets() {
    return Promise.all([
      api("/api/v1/datasets"),
      api("/api/v1/deliverables")
    ]).then(function (results) {
      var datasets = results[0];
      var deliverables = results[1];
      if (datasets.status === 200) state.datasets = (datasets.body && datasets.body.datasets) || [];
      if (deliverables.status === 200) state.deliverables = (deliverables.body && deliverables.body.deliverables) || [];
      refreshQualityTargets();
    }).catch(function () { refreshQualityTargets(); });
  }

  function accuracyMetrics(p) {
    var accuracy = p.accuracy || {};
    return accuracy.metrics || {};
  }

  function accuracySummary(p) {
    var accuracy = p.accuracy || {};
    if (accuracy.status === "ERROR") return "ERROR";
    var metrics = accuracyMetrics(p);
    if (metrics.pixel_accuracy === null || metrics.pixel_accuracy === undefined) return "—";
    return "PA " + fmtRate(metrics.pixel_accuracy) + " · F1 " + fmtRate(metrics.f1);
  }

  function renderAccuracy(accuracy, reportPayload) {
    var p = reportPayload || {};
    if (!accuracy) {
      var reason = p.target_type === "deliverable"
        ? "未计算：本次没有提供参考真值掩膜。"
        : "未开放：精度对比的目标类型必须是成果（deliverable）。";
      return '<div class="accbox"><div class="acc-head"><span>ACCURACY</span><span class="dim">' +
        esc(reason) + "</span></div></div>";
    }
    if (accuracy.status === "ERROR") {
      return '<div class="accbox"><div class="acc-head"><span>ACCURACY</span>' +
        qualityPill("ERROR") + '</div><div class="acc-error"><b>精度计算失败</b>：' +
        esc(accuracy.error || "参考与预测掩膜无法对齐或无法读取") + "</div></div>";
    }
    var metrics = accuracy.metrics || {};
    var cells = accuracy.cells || {};
    var thresholds = accuracy.thresholds || {};
    var grid = accuracy.grid || {};
    var synthetic = accuracy.synthetic_reference ? '<span class="pill warn">SYNTHETIC REFERENCE</span>' : "";
    var metricRows = [
      ["PA", metrics.pixel_accuracy],
      ["Precision", metrics.precision],
      ["Recall", metrics.recall],
      ["F1", metrics.f1],
      ["IoU", metrics.iou]
    ].map(function (row) {
      return '<div class="acc-metric"><div class="k">' + esc(row[0]) + '</div><div class="v">' + fmtRate(row[1]) + "</div></div>";
    }).join("");
    var thresholdText = Object.keys(thresholds).map(function (key) {
      var names = { pixel_accuracy: "PA", precision: "Precision", recall: "Recall", f1: "F1", iou: "IoU" };
      return esc(names[key] || key) + " ≥ " + fmtThreshold(thresholds[key]);
    }).join(" · ");
    var matrix = '<table class="matrix"><thead><tr><th></th><th>Ref 1</th><th>Ref 0</th></tr></thead><tbody>' +
      '<tr><th>Pred 1</th><td class="hit">TP ' + fmtNum(cells.tp, 0) + '</td><td class="miss">FP ' + fmtNum(cells.fp, 0) + "</td></tr>" +
      '<tr><th>Pred 0</th><td class="miss">FN ' + fmtNum(cells.fn, 0) + '</td><td class="hit">TN ' + fmtNum(cells.tn, 0) + "</td></tr>" +
      "</tbody></table>";
    var skipText = "Valid " + fmtNum(cells.valid, 0) +
      " · NODATA " + fmtNum(cells.skipped_nodata, 0) +
      " · non-finite " + fmtNum(cells.skipped_non_finite, 0);
    var gridText = grid.ncols === undefined ? "—" : fmtNum(grid.ncols, 0) + " × " + fmtNum(grid.nrows, 0) +
      " · cell " + fmtNum(grid.cellsize, 4);
    return '<div class="accbox"><div class="acc-head"><span>ACCURACY</span><span class="dim">' +
      esc(gridText) + "</span></div>" +
      (synthetic ? '<div style="margin-top:8px">' + synthetic + "</div>" : "") +
      '<div class="acc-metrics">' + metricRows + "</div>" +
      '<div class="acc-grid">' + matrix +
      '<div class="acc-side"><div class="acc-thresholds">' + (thresholdText ? "Thresholds<br>" + thresholdText : "Thresholds · 未设") +
      "<br>" + esc(skipText) + "</div>" +
      '<div class="acc-thresholds">Ref: ' + esc(accuracy.reference_path || "—") +
      "<br>Pred: " + esc(accuracy.predicted_path || "—") + "</div></div></div></div>";
  }

  function renderQuality(report) {
    var box = document.getElementById("qualityResult");
    if (!box) return;
    if (!report) {
      box.innerHTML = emptyBox("待", "尚未执行", "选择数据集或成果后执行三层质检；结果、逐项证据与报告路径会出现在这里。");
      return;
    }
    var p = report.payload || report;
    var layers = p.layers || {};
    var target = p.target || {};
    var targetId = target.dataset_id || target.deliverable_id || p.target_id || "";
    var html = '<div class="quality-result">' +
      '<div class="wrow">' + qualityPill(p.status) +
      '<span class="dim">' + esc(p.report_id || report.object_id || "") + "</span>" +
      '<span class="dim">' + esc(p.target_type || "") + (targetId ? " · " + esc(targetId) : "") + "</span>" +
      '<span class="dim">' + esc(p.generated_at || "") + "</span></div>";
    ["file", "spatial", "professional"].forEach(function (key) {
      var layer = layers[key] || { status: "NOT_RECORDED", checks: [] };
      var names = { file: "文件与结构", spatial: "空间数据", professional: "专业成果验证" };
      html += '<div class="layerbox"><div class="lh"><b>' + esc(key.toUpperCase()) + "</b>" +
        esc(names[key]) + qualityPill(layer.status) + "</div>";
      html += (layer.checks || []).map(function (check) {
        var checkName = esc(check.name).replace(/_/g, "_<wbr>");
        return '<div class="qcheck"><span class="qn">' + checkName + "</span>" +
          qualityPill(check.status) + '<span class="qd">' + esc(check.detail || "") + "</span></div>";
      }).join("") || '<div class="empty-mini">该层没有记录</div>';
      html += "</div>";
    });
    html += renderAccuracy(p.accuracy, p);
    if (p.report_path) {
      html += '<div class="note">报告已落盘： <code>' + esc(p.report_path) + "</code></div>";
    }
    html += "</div>";
    box.innerHTML = html;
  }

  function loadQualityReports() {
    var box = document.getElementById("qualityReportRows");
    if (!box) return;
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/quality-reports 取质检报告。");
    return api("/api/v1/quality-reports").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "质检接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.qualityReports = (res.body && res.body.reports) || [];
      var count = document.getElementById("qualityCount");
      if (count) count.textContent = state.qualityReports.length + " 份";
      if (state.qualityReports.length) {
        var current = null;
        if (state.lastQuality && state.lastQuality.object_id) {
          current = state.qualityReports.filter(function (row) {
            return row.object_id === state.lastQuality.object_id;
          })[0];
        }
        state.lastQuality = current || state.qualityReports[state.qualityReports.length - 1];
        renderQuality(state.lastQuality);
      } else {
        state.lastQuality = null;
        renderQuality(null);
      }
      renderQualityReports();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到质检报告", "服务未启动或网络不可达。"); });
  }

  function renderQualityReports() {
    var box = document.getElementById("qualityReportRows");
    if (!state.qualityReports.length) {
      box.innerHTML = emptyBox("空", "还没有质检报告", "执行三层质检后，报告会写入 var/quality 并登记为 QualityReport。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Report</th><th>Target</th><th>Task</th><th>Status</th><th>Accuracy</th><th>Layers</th><th>Generated</th><th>Path</th></tr></thead><tbody>';
    state.qualityReports.slice().reverse().forEach(function (row) {
      var p = row.payload || {};
      var target = p.target || {};
      var layers = p.layers || {};
      html += "<tr>" +
        '<td class="id"><button class="report-open" type="button" data-open-report="' + esc(row.object_id) + '">' + esc(row.object_id) + "</button></td>" +
        '<td class="id">' + esc(target.dataset_id || target.deliverable_id || "—") + "</td>" +
        '<td class="id">' + esc(p.task_id || "—") + "</td>" +
        "<td>" + qualityPill(p.status) + "</td>" +
        '<td class="dim">' + esc(accuracySummary(p)) + "</td>" +
        '<td class="dim">' + ["file", "spatial", "professional"].map(function (k) { return k + ":" + esc((layers[k] || {}).status || "—"); }).join(" · ") + "</td>" +
        '<td class="dim">' + esc(p.generated_at || "") + "</td>" +
        '<td class="wrap">' + esc(p.report_path || "—") + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  var qualityReportRows = document.getElementById("qualityReportRows");
  if (qualityReportRows) {
    qualityReportRows.addEventListener("click", function (ev) {
      var button = ev.target.closest("[data-open-report]");
      if (!button) return;
      var id = button.getAttribute("data-open-report");
      var report = state.qualityReports.filter(function (row) { return row.object_id === id; })[0];
      if (!report) return;
      state.lastQuality = report;
      renderQuality(report);
      var result = document.getElementById("qualityResult");
      if (result && result.scrollIntoView) result.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  function readAccuracyThresholds() {
    var fields = [
      ["pixel_accuracy", "threshold_pixel_accuracy"],
      ["precision", "threshold_precision"],
      ["recall", "threshold_recall"],
      ["f1", "threshold_f1"],
      ["iou", "threshold_iou"]
    ];
    var values = {};
    for (var i = 0; i < fields.length; i++) {
      var input = document.querySelector('[name="' + fields[i][1] + '"]');
      var raw = input ? input.value.trim() : "";
      if (!raw) continue;
      var number = Number(raw);
      if (!isFinite(number) || number < 0 || number > 1) {
        return { values: values, error: "阈值 " + fields[i][0] + " 必须在 0–1 之间" };
      }
      values[fields[i][0]] = number;
    }
    return { values: values, error: "" };
  }

  var qualityTargetType = document.getElementById("qualityTargetType");
  if (qualityTargetType) {
    qualityTargetType.addEventListener("change", syncQualityTargetMode);
    syncQualityTargetMode();
  }
  var qualityTargetId = document.getElementById("qualityTargetId");
  if (qualityTargetId) {
    qualityTargetId.addEventListener("change", function () {
      var type = qualityTargetType ? qualityTargetType.value : "dataset";
      var rows = type === "deliverable" ? state.deliverables : state.datasets;
      var row = rows.filter(function (item) { return item.object_id === qualityTargetId.value.trim(); })[0];
      var taskInput = document.getElementById("qualityTaskId");
      var task = row && row.payload ? row.payload.task_id : "";
      if (task && taskInput && !taskInput.value.trim()) taskInput.value = task;
    });
  }

  var qualityForm = document.getElementById("qualityForm");
  if (qualityForm) {
    qualityForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var token = currentToken();
      if (!token) { setMsg("qualityMsg", "bad", "先在右上角填令牌（需要 quality:write 权限）"); return; }
      var values = formValues(ev.target);
      var sample = document.getElementById("qualitySample").checked;
      if (sample && !values.sample_note) { setMsg("qualityMsg", "bad", "人工抽样必须写依据"); return; }
      var targetType = values.target_type;
      var referencePath = targetType === "deliverable" ? (values.reference_path || "").trim() : "";
      var predictedPath = targetType === "deliverable" ? (values.predicted_path || "").trim() : "";
      var thresholds = targetType === "deliverable" ? readAccuracyThresholds() : { values: {}, error: "" };
      if (thresholds.error) { setMsg("qualityMsg", "bad", thresholds.error); return; }
      if (Object.keys(thresholds.values).length && !referencePath) {
        setMsg("qualityMsg", "bad", "精度阈值必须先给参考真值掩膜"); return;
      }
      var body = {
        target_type: targetType,
        target_id: values.target_id,
        task_id: values.task_id,
        professional_sample: sample,
        sample_note: values.sample_note || "",
        actor: values.actor || ""
      };
      if (targetType === "deliverable") {
        body.reference_path = referencePath;
        body.predicted_path = predictedPath;
        body.synthetic_reference = document.getElementById("qualitySynthetic").checked;
        body.accuracy_thresholds = thresholds.values;
      }
      setMsg("qualityMsg", "", "质检执行中…");
      api("/api/v1/quality-reports", { method: "POST", token: token, body: body }).then(function (res) {
        if (res.status === 201) {
          state.lastQuality = (res.body && res.body.report) || {};
          renderQuality(state.lastQuality);
          var p = state.lastQuality.payload || {};
          setMsg("qualityMsg", p.status === "PASS" ? "ok" : "bad",
            "已生成 " + (p.report_id || state.lastQuality.object_id) + "：三层判定 " + qualityStatusText(p.status));
          loadQualityReports(); loadOverview();
          return;
        }
        var reason = (res.body && res.body.error) || res.status;
        var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 quality:write 权限：" : "质检被拒：";
        setMsg("qualityMsg", "bad", prefix + reason);
      }).catch(function () { setMsg("qualityMsg", "bad", "网络或服务不可达"); });
    });
  }
  var qualityReload = document.getElementById("qualityReload");
  if (qualityReload) qualityReload.addEventListener("click", loadQualityReports);

  /* ---------- 成果登记 / 归档 ---------- */
  function loadDeliverables() {
    var box = document.getElementById("deliverableRows");
    if (!box) return;
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/deliverables 取成果簿。");
    return api("/api/v1/deliverables").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "成果接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.deliverables = (res.body && res.body.deliverables) || [];
      var count = document.getElementById("deliverableCount");
      if (count) count.textContent = state.deliverables.length + " 件";
      renderDeliverables();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到成果簿", "服务未启动或网络不可达。"); });
  }

  function deliverableStatusPill(status) {
    var map = { accepted: "pass", archived: "info", registered: "warn", rejected: "fail" };
    return '<span class="pill ' + (map[status] || "idle") + '">' + esc(status || "—") + "</span>";
  }

  function renderDeliverables() {
    var box = document.getElementById("deliverableRows");
    if (!state.deliverables.length) {
      box.innerHTML = emptyBox("空", "还没有登记成果", "成果必须是真实文件；登记时读 sha256 和大小，审核通过后才能归档。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Deliverable</th><th>Task</th><th>Name</th><th>Kind</th><th>Version</th><th>Size</th><th>Status</th><th>Path</th><th></th></tr></thead><tbody>';
    state.deliverables.forEach(function (row) {
      var p = row.payload || {};
      var status = p.archived_at ? "archived" : row.status;
      html += "<tr>" +
        '<td class="id">' + esc(row.object_id) + "</td>" +
        '<td class="id">' + esc(p.task_id || "—") + "</td>" +
        "<td>" + esc(p.name || "—") + "</td>" +
        '<td class="dim">' + esc(p.kind || "—") + "</td>" +
        '<td class="num">v' + esc(p.deliverable_version || 1) + "</td>" +
        '<td class="num">' + bytes(p.size_bytes) + "</td>" +
        "<td>" + deliverableStatusPill(status) + "</td>" +
        '<td class="wrap">' + esc(p.path || "—") + "</td>" +
        '<td class="act">' + (row.status === "accepted" && !p.archived_at ?
          '<button class="btn ghost sm" data-archive="' + esc(row.object_id) + '">归档</button>' : "—") + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  var deliverableForm = document.getElementById("deliverableForm");
  if (deliverableForm) {
    deliverableForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var token = currentToken();
      if (!token) { setMsg("deliverableMsg", "bad", "先在右上角填令牌（需要 deliverable:write 权限）"); return; }
      var values = formValues(ev.target);
      setMsg("deliverableMsg", "", "登记中…");
      api("/api/v1/deliverables", { method: "POST", token: token, body: values }).then(function (res) {
        if (res.status === 201) {
          var deliverable = (res.body && res.body.deliverable) || {};
          setMsg("deliverableMsg", "ok", "已登记 " + deliverable.object_id + "（" + deliverable.status + "）");
          ev.target.reset();
          loadDeliverables(); loadOverview();
          return;
        }
        var reason = (res.body && res.body.error) || res.status;
        var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 deliverable:write 权限：" : "成果登记被拒：";
        setMsg("deliverableMsg", "bad", prefix + reason);
      }).catch(function () { setMsg("deliverableMsg", "bad", "网络或服务不可达"); });
    });
  }
  var deliverableRows = document.getElementById("deliverableRows");
  if (deliverableRows) {
    deliverableRows.addEventListener("click", function (ev) {
      var button = ev.target.closest ? ev.target.closest("[data-archive]") : null;
      if (!button) return;
      var token = currentToken();
      if (!token) { setMsg("deliverableMsg", "bad", "先填令牌（需要 deliverable:write 权限）"); return; }
      button.disabled = true;
      api("/api/v1/deliverables/" + encodeURIComponent(button.getAttribute("data-archive")) + "/archive",
        { method: "POST", token: token, body: { actor: "console", note: "final acceptance archived" } }).then(function (res) {
        if (res.status === 200) {
          setMsg("deliverableMsg", "ok", "已归档：" + ((res.body.deliverable || {}).object_id || ""));
          loadDeliverables(); loadOverview();
          return;
        }
        button.disabled = false;
        var reason = (res.body && res.body.error) || res.status;
        setMsg("deliverableMsg", "bad", "归档被拒：" + reason);
      }).catch(function () { button.disabled = false; setMsg("deliverableMsg", "bad", "网络或服务不可达"); });
    });
  }
  var deliverableReload = document.getElementById("deliverableReload");
  if (deliverableReload) deliverableReload.addEventListener("click", loadDeliverables);

  /* ---------- AI 资源登记 ---------- */
  var catalogForm = document.getElementById("catalogForm");
  if (catalogForm) {
    catalogForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var token = currentToken();
      if (!token) { setMsg("catalogMsg", "bad", "先在右上角填令牌（需要 catalog:write 权限）"); return; }
      var values = formValues(ev.target);
      var kind = values.kind;
      var body = {
        kind: kind,
        id: values.resource_id,
        name: values.name,
        version: values.version || "1",
        adapter: values.adapter,
        capability: values.capability || "",
        available: true
      };
      if (kind === "Model") {
        body.model_kind = values.subkind || "algorithm";
        body.capability = values.capability || "change_detection";
      } else if (kind === "Tool") {
        body.category = values.subkind || "raster";
        body.error_handling = "fail closed";
      } else {
        body.strategy = values.capability || "sequential";
        body.model_ids = (values.depends_on || "").split(",").map(function (s) { return s.trim(); }).filter(function (s) { return /^MOD-/i.test(s); });
        body.tool_ids = (values.depends_on || "").split(",").map(function (s) { return s.trim(); }).filter(function (s) { return /^TOL-/i.test(s); });
        body.description = "registered from console";
      }
      setMsg("catalogMsg", "", "登记中…");
      api("/api/v1/catalog", { method: "POST", token: token, body: body }).then(function (res) {
        if (res.status === 201) {
          var obj = (res.body && res.body.object) || {};
          setMsg("catalogMsg", "ok", "已登记 " + obj.object_id + "（" + (obj.payload && obj.payload.available ? "可用" : "不可用") + "）");
          ev.target.reset();
          loadCatalog(); loadOverview();
          return;
        }
        var reason = (res.body && res.body.error) || res.status;
        var prefix = res.status === 401 ? "令牌不被接受：" : res.status === 403 ? "缺 catalog:write 权限：" : "资源登记被拒：";
        setMsg("catalogMsg", "bad", prefix + reason);
      }).catch(function () { setMsg("catalogMsg", "bad", "网络或服务不可达"); });
    });
  }

  /* ---------- 设置 / 权限 ---------- */
  function loadSettings() {
    var identity = document.getElementById("settingsIdentity");
    var storage = document.getElementById("settingsStorage");
    var roles = document.getElementById("settingsRoles");
    var perms = document.getElementById("settingsPerms");
    if (!identity || !storage || !roles || !perms) return;
    identity.innerHTML = '<div class="empty-mini">读取中…</div>';
    return api("/api/v1/settings").then(function (res) {
      if (res.status !== 200) {
        identity.innerHTML = '<div class="empty-mini">设置接口返回 ' + esc(res.status) + "</div>";
        return;
      }
      state.settings = res.body || {};
      var s = state.settings;
      var caller = s.caller || {};
      var context = s.context || {};
      var pill = document.getElementById("callerPill");
      if (pill) {
        pill.className = "pill " + (caller.token_present ? "pass" : "idle");
        pill.textContent = caller.token_present ? "TOKEN" : "只读";
      }
      identity.innerHTML = [
        ["Token", caller.token_present ? "present" : "未提供"],
        ["Version", context.version || "0.1.0"],
        ["Kernel", context.kernel || "—"],
        ["Tier", context.tier || "核心工程 · CORE"],
        ["Permissions", (caller.permissions || []).join(" · ") || "只读"]
      ].map(function (row) {
        return '<div class="row"><span class="k">' + esc(row[0]) + '</span><span class="v mono">' + esc(row[1]) + "</span></div>";
      }).join("");
      var store = s.storage || {};
      storage.innerHTML = Object.keys(store).map(function (key) {
        return '<div class="row"><span class="k">' + esc(key) + '</span><span class="v mono">' + esc(store[key]) + "</span></div>";
      }).join("");
      var roleRows = (s.roles || []).map(function (role) {
        return "<tr><td class=\"role\">" + esc(role.role) + "</td><td>" +
          (role.permissions || []).map(function (p) { return '<span class="permtag on">' + esc(p) + "</span>"; }).join("") +
          "</td></tr>";
      });
      roles.innerHTML = '<table class="tbl perm-table"><thead><tr><th>Role</th><th>Granted keys</th></tr></thead><tbody>' +
        roleRows.join("") + "</tbody></table>";
      perms.innerHTML = (s.permissions || []).map(function (p) {
        return '<span class="permtag">' + esc(p) + "</span>";
      }).join("") || '<div class="empty-mini">服务端没有声明权限键。</div>';
    }).catch(function () {
      identity.innerHTML = '<div class="empty-mini">设置接口不可达。</div>';
    });
  }

  /* ---------- 首屏 ---------- */
  var params = new URLSearchParams(location.search);
  if (params.get("palette")) {
    document.documentElement.dataset.palette = params.get("palette");
  }
  if (params.get("theme")) {
    document.documentElement.dataset.theme = params.get("theme");
  }
  Array.prototype.forEach.call(document.querySelectorAll(".swatch"), function (btn) {
    btn.setAttribute("aria-pressed", btn.dataset.palette === document.documentElement.dataset.palette ? "true" : "false");
  });
  var initial = location.hash.replace("#", "");
  updateWritePill();
  show(document.getElementById(initial) ? initial : "overview");
  loadOverview();
  var deepTrace = params.get("trace");
  if (deepTrace) {
    document.getElementById("traceTaskId").value = deepTrace;
    show("trace");
    loadTrace();
  }
})();

/* == GEOOPS i18n == 整节点精确匹配优先；短串才做子串替换；
   长句（>=8 汉字）只认整句，绝不拆碎成半中半英。 */
(function () {
  "use strict";
  var KEY = "geoops.ui";
  var MAP = {"序":"OV","总览":"Overview","项目":"Projects","任务":"Tasks","AI 资源":"AI Resources","数据":"Data","流程":"Workflows","规则":"Rules","质量":"Quality","成果":"Deliverables","审核":"Reviews","追溯":"Trace","设置":"Settings","核心":"Core","缺口按验收表逐项清理":"Gaps cleared item by item against the acceptance list","连接中":"Connecting","域对象":"Objects","测绘任务":"Survey tasks","已载规则":"Rules loaded","登记成果":"Registered deliverables","运行原则":"Run principle","规则门在前 · 登记在后":"Gate first · registration second","文件 / 空间 / 专业三层":"File / spatial / professional","人工签认才置 accepted":"Human sign-off before accepted","缺环写 NOT_RECORDED":"Missing link = NOT_RECORDED","十二模块":"Twelve modules","I · 治理":"I · Governance","总览 · 项目 · 任务":"Overview · Projects · Tasks","II · 作业":"II · Operations","III · 验收":"III · Acceptance","质量 · 成果 · 审核":"Quality · Deliverables · Reviews","IV · 证据":"IV · Evidence","追溯 · 设置":"Trace · Settings","工程身份":"Engineering","核心工程 · CORE":"Core project · CORE","未发布":"Not published","未清门槛":"Open gaps","真实遥感影像与专业抽样待用户提供":"Real imagery and professional sampling to be supplied","跨进程文件锁未做":"Cross-process file lock not implemented","统一身份源未接，轮换靠人工":"No unified identity source; rotation is manual","未发布：等级 ≠ 发布资格":"Not published: tier ≠ release readiness","登记":"Register","项":"PRJ","项目册":"Project registry","刷新":"Refresh","登记项目":"Register project","项目 id":"Project id","项目编号":"Project code","项目名称":"Project name","项目类型":"Project type","区域":"Area","坐标参考":"CRS","高程基准":"Vertical datum","需要":"requires","台账":"Ledger","务":"TSK","全部":"All","草稿":"Draft","就绪":"Ready","运行":"Running","完成":"Completed","失败":"Failed","写操作":"Write actions","需令牌":"Token required","新建任务":"New task","任务名称":"Task name","任务类型":"Task type","创建":"Create","迁移状态":"Transition","任务 id":"Task id","目标状态":"Target status","先填任务":"Fill task first","理由":"Reason","迁移":"Transition","资源":"Resources","器":"CAT","资源目录":"Resource catalog","真实模型运行时":"Model runtime","读取中":"Loading","测试提示词":"Test prompt","测试连接":"Test connection","运行模型":"Run model","服务端只从环境变量读端点与密钥：":"Server reads endpoint and key from env only:","登记资源":"Register resource","资源 id":"Resource id","类型":"Type","模型 Model":"Model","工具 Tool":"Tool","名称":"Name","版本":"Version","适配器 / 路径":"Adapter / path","模型类型 / 工具类别":"Model type / tool class","模型 · algorithm":"Model · algorithm","模型 · ai-model":"Model · ai-model","工具 · gis":"Tool · gis","工具 · raster":"Tool · raster","工具 · vector":"Tool · vector","工具 · conversion":"Tool · conversion","能力 / 类别":"Capability / class","接入":"Intake","据":"DS","数据集":"Datasets","登记数据集":"Register dataset","任务 id（可选）":"Task id (optional)","文件路径":"File path","文件绝对路径":"Absolute file path","标签":"Label","读取并登记":"Read and register","同名 sidecar":"Sidecar","需写":"Write required","流":"WF","流程定义":"Workflow definitions","登记流程定义":"Register workflow","流程编号":"Workflow id","说明":"Description","节点 JSON":"Node JSON","登记定义":"Register definition","编辑":"Edit","正在编辑":"Editing","。保存会生成新版本，编号不可改。":" Saving creates a new version; the id is locked.","取消编辑":"Cancel edit","更新定义":"Update definition","更新中…":"Updating…","已更新 ":"Updated ","更新被拒：":"Update rejected: ","编辑中…":"Editing…","已取消编辑":"Edit cancelled","已加入模板：":"Template added: ","节点模板":"Node templates","模型节点":"Model node","带入执行":"Use in execute","已带入执行：":"Loaded for execution: ","节点 JSON 必须是数组":"Node JSON must be an array","流程编号不能为空":"Workflow id cannot be empty","可用节点：":"Available nodes:","按定义执行":"Execute definition","任务编号（可选）":"Task id (optional)","执行上下文 JSON":"Execution context JSON","执行流程":"Execute workflow","上次运行（可选）":"Previous run (optional)","新建运行":"New run","选择失败运行后，执行按钮切换为恢复；已完成节点会跳过。":"Pick a failed run to switch the action to resume; passed nodes are skipped.","恢复运行":"Resume run","恢复中…":"Resuming…","恢复已记录：":"Resume recorded: ","恢复被拒：":"Resume rejected: ","已带入恢复：":"Loaded for resume: ","恢复自 ":"Resumed from ","运行历史":"Run history","按 run / 任务 / 流程 / 节点筛选":"Filter by run / task / workflow / node","没有匹配的运行":"No runs match the filter","当前关键词没有命中。按 Esc 清空筛选。":"No run matches the current keyword. Press Esc to clear it.","运行完成才写一行日志（":"A line is written only after a run completes (","登记链路":"Chain","规则门":"Rule gate","变化检测":"Change detection","掩膜写出":"Mask write","成果登记":"Deliverable registration","包":"RULE","规":"RULE","已载规则包":"Loaded rule packs","检查":"Check","质":"QA","发起质检":"Run check","检查对象":"Target type","数据集 Dataset":"Dataset","成果 Deliverable":"Deliverable","对象 id":"Object id","任务 id（可空）":"Task id (optional)","操作人":"Actor","已完成人工抽样 / 专业核验":"Manual sampling / professional verification done","专业抽样依据（勾选后必填）":"Sampling evidence (required when checked)","执行三层质检":"Run three-layer check","。质检报告会写入":". The quality report is written to","本次判定":"Latest result","待":"WAIT","尚未执行":"Not run yet","质检报告":"Quality reports","簿":"DLV","果":"DLV","已登记成果":"Registered deliverables","成果名称":"Deliverable name","成果类型":"Deliverable kind","备注":"Notes","文件簿":"Registered files","签认":"Sign-off","审":"REV","审核记录":"Review records","提交审核":"Submit review","成果 id":"Deliverable id","审核人":"Reviewer","结论":"Decision","通过":"Approve","驳回":"Reject","返工":"Rerun","意见（驳回 / 返工必填）":"Opinion (required for reject / rerun)","写入审核记录":"Write review","反向":"Reverse","溯":"TRC","生成追溯链":"Build trace","生成":"Build","还没有生成追溯链":"No trace built yet","审计记录":"Audit rows","最近审计":"Recent audit","未":"NONE","尚未读取":"Not read yet","审计接口需要":"The audit endpoint requires","系统":"System","设":"SYS","调用方":"Caller","令牌只存本页":"Token is kept in this page only","，不会写入磁盘。权限由服务端":", never written to disk. Permissions come from the server's","存储与策略":"Storage","角色与权限":"Role matrix","权限键":"Permission keys","主导航":"Main navigation","写入口与审计读取需要令牌；令牌只存在本页 sessionStorage":"Write and audit endpoints need a token; it stays in this page's sessionStorage","输入访问令牌":"Enter access token","字号":"Font size","缩小字号":"Decrease font size","放大字号":"Increase font size","切换字重":"Switch font weight","字重：细 / 常规 / 中 / 粗":"Weight: light / regular / medium / bold","配色":"Palette","白":"White","黑":"Black","粉":"Pink","莱茵蓝":"Rhine blue","橙":"Orange","切换明暗":"Toggle light / dark","深空 / 纸面":"Deep space / Paper","内部唯一编号":"Internal unique code","项目全称":"Full project name","行政区或测区":"Administrative area or survey block","1985 国家高程基准":"1985 national vertical datum","按状态筛选":"Filter by status","按 id / 名称 / 项目筛选":"Filter by id / name / project","筛选任务":"Filter tasks","变化检测 2026-11":"Change detection 2026-11","从下表点「迁移」带入":"Filled by clicking Transition below","完成 / 取消必须写理由":"Completion / cancellation needs a reason","资源显示名称":"Display name","builtin:... 或 external:绝对路径":"builtin:... or external:absolute path","已登记项目":"Registered project","绑定到任务后进入追溯链":"Binds to a task and joins the trace chain","例如 一期影像":"e.g. phase-1 imagery","例如 变化检测标准流程":"e.g. standard change detection workflow","可选；会写入定义记录":"Optional; stored in the definition record","TSK-...；填写时任务必须为 RUNNING":"TSK-...; the task must be RUNNING","DS-xxxx 或 DLV-xxxx":"DS-xxxx or DLV-xxxx","绑定追溯链":"Bind to trace chain","姓名或工号":"Name or employee id","抽样位置、样本编号、核验结论":"Sample location, sample id, verification result","变化检测成果 v1":"Change detection deliverable v1","范围、来源、限制":"Scope, source, limits","按成果 id / 文件名 / 任务筛选":"Filter by deliverable id / file name / task","筛选成果":"Filter deliverables","具体问题与依据":"Specific issue and evidence","输入任务 id，例如 TSK-xxxx":"Enter a task id, e.g. TSK-xxxx","按路径 / 原由 / 令牌前缀筛选":"Filter by path / reason / token prefix","筛选审计":"Filter audit","登记于 docs/ENGINEERING_TIER.md":"Registered in docs/ENGINEERING_TIER.md","规则先行、判定留痕、成果可核。只展示接口真实返回的内容：没有记录就写「未记录」，没有接口就写「未开放」。":"Rules first, decisions on record, deliverables checkable. Only what the API actually returns is shown: no record means \"not recorded\", no endpoint means \"not available\".","任何一层没有证据，结果只能是 PARTIAL 或 FAIL；不用推断补链，不用占位冒充真实。":"Without evidence at any layer the result can only be PARTIAL or FAIL; no inferred links, no placeholders posing as real.","AI 资源 · 数据 · 流程 · 规则":"AI resources · Data · Workflows · Rules","真实 AI 模型与外部 GIS 适配器待接":"Real AI model and external GIS adapter still to be connected","Agent 自动执行器仍只做目录登记":"Agent executor still only registers in the catalog","项目编号、名称、类型、区域、坐标参考、高程基准六项必填；编号唯一，缺一项即拒绝。":"Six required fields: code, name, type, area, CRS, vertical datum. Codes are unique; any missing field is rejected.","项目是任务、数据集、成果追溯的根。登记后不可用同编号重复建项。":"A project is the root of tasks, datasets and deliverable traceability. The same code cannot be registered twice.","。缺字段或编号重复时服务端原文拒绝，不落半条记录。":". Missing fields or duplicate codes are rejected verbatim by the server; nothing is half-written.","七态状态机：非法迁移被拒且不落半条记录；完成与取消必须写理由。":"Seven-state machine: illegal transitions are rejected with nothing half-written; completion and cancellation need a reason.","。服务端在读 body 之前校验令牌；没有权限就写不进去。":". The server checks the token before reading the body; without permission nothing is written.","。目标状态只列该任务当前允许迁移的项，非法边会被服务端拒绝。":". Target status lists only transitions allowed from the current state; illegal edges are rejected by the server.","模型、工具、Agent 分开登记。builtin 必须是真实实现，external 路径不存在即标不可用；Agent 引用未知依赖直接拒绝。":"Models, tools and agents are registered separately. builtin must be a real implementation; a missing external path is marked unavailable; an agent referencing an unknown dependency is rejected.","可用性不是标签：builtin 适配器必须是本仓真实实现，external 必须指向存在的路径；不可用会带原因。Agent 引用未登记的模型或工具会被拒绝。":"Availability is not a label: a builtin adapter must exist in this repository, an external one must point to a real path; unavailable entries carry a reason. An agent referencing an unregistered model or tool is rejected.","尚未调用。配置环境变量并重启服务后，这里显示真实模型回复；没有配置时不会生成占位内容。":"Not called yet. After configuring the environment and restarting, the real model reply appears here; without configuration no placeholder is produced.","。密钥不进浏览器、不写入仓库。测试与运行需要":". The key never enters the browser or the repository. Test and run require","Agent 依赖（模型 id 与工具 id，逗号分隔）":"Agent dependencies (model ids and tool ids, comma separated)","。外部路径必须已存在且可读；不可用的资源仍会入册，但会写明原因，不会伪装可用。":". An external path must exist and be readable; unavailable resources are still registered but carry the reason and are never faked as available.","数据集登记时读真实文件算 sha256，CRS 取自 sidecar 或 classic GeoTIFF 头；复核重探测，文件内容变化即 FAIL。":"Dataset registration reads the real file for sha256; CRS comes from the sidecar or a classic GeoTIFF header; re-validation re-probes and FAILs if the content changed.","；无 CRS 或文件不存在会被拒绝。BigTIFF 与像元解码明确不支持。":"; missing CRS or a missing file is rejected. BigTIFF and pixel decoding are explicitly unsupported.","一次运行里规则门在前、登记在后：判定不过，成果不会被登记。":"In a run the rule gate comes first and registration second: if the gate fails, no deliverable is registered.","定义是登记过的数据：节点 id、类型、阈值都先校验；执行时按这份记录建节点，不另写一套隐藏流程。":"A definition is registered data: node ids, types and thresholds are validated first; execution builds nodes from that record, not from a hidden parallel flow.","。模型节点在未配置端点时会明确记 ERROR，不会假装通过。":". A model node records ERROR when no endpoint is configured and never pretends to pass.","尚未执行；这里只显示真实运行返回，不预填结果。":"Not executed yet; only real run output appears here, never prefilled.","执行会产生真实运行记录；规则门不过、路径缺失或模型未配置都会落成 FAIL / ERROR。任务编号留空时只独立运行，不写任务关联。":"Execution writes a real run record; a failed gate, missing path or unconfigured model lands as FAIL / ERROR. With no task id it runs standalone and writes no task link.","后才返回）；重复 run_id 拒绝，坏行整份拒载。":"before returning); duplicate run_ids are rejected and a corrupt line rejects the whole file.","· CRS / 格距 / 两期一致性":"· CRS / cell size / two-epoch consistency","· 逐格差分 + 4 邻域斑块 + 最小面积":"· Cell-wise difference + 4-neighbour patches + minimum area","· 源头信息保留，nodata 仍为 nodata":"· Source metadata preserved, nodata stays nodata","· 真文件、真 sha256、绑已登记成果":"· Real file, real sha256, bound to a registered deliverable","规则是数据不是代码：校验器缺失或异常判 ERROR，条件不满足判 SKIPPED，两者都不升格为 PASS。":"Rules are data, not code: a missing or failing checker is ERROR, an unmet condition is SKIPPED, and neither is promoted to PASS.","规则包整包校验后装载：缺字段、severity 非法、id 重复、与已载冲突都会整包拒绝，不半装。":"A rule pack is validated as a whole before loading: missing fields, illegal severity, duplicate ids or conflicts with a loaded pack reject the whole pack, never half-load.","文件与结构、空间数据、专业成果验证三层。第三层没有人工抽样与书面依据，只能是 NOT_RECORDED，汇总结果只能是 PARTIAL。":"Three layers: file and structure, spatial data, professional verification. Without manual sampling and written evidence the third layer is NOT_RECORDED and the aggregate can only be PARTIAL.","并以 QualityReport 入域，不是只在前端算一遍。":"and enters the domain as a QualityReport, not just a front-end calculation.","选择数据集或成果后执行三层质检；结果、逐项证据与报告路径会出现在这里。":"Pick a dataset or deliverable and run the three-layer check; the verdict, per-item evidence and report path appear here.","成果登记读真实文件：哈希、大小、路径当场记录；人工审核通过后才 accepted，之后才允许归档。":"Deliverable registration reads the real file: hash, size and path recorded on the spot; only a passing human review makes it accepted, and only then can it be archived.","「归档」只在 accepted 后开放。归档不会改动文件，只把成果状态与归档人、时间写入域对象。":"Archive opens only after accepted. Archiving never touches the file; it records the status, archiver and time on the domain object.","。路径必须存在且为普通文件；符号链接与目录一律拒绝。":". The path must exist and be a regular file; symlinks and directories are rejected.","成果只有经人工通过才置为 accepted；驳回或返工必须写意见，已签认的成果拒绝二次审核。":"A deliverable becomes accepted only through human approval; reject or rerun requires an opinion, and a signed-off deliverable refuses a second review.","需要 review:write。记录写入同时改成果状态；通过即最终验收，驳回或返工不签认。":"Requires review:write. The record and the deliverable status change together; approval is final acceptance, reject or rerun signs nothing.","从任务串回项目、数据集、运行、规则、成果、文件与审核；缺失的一环写 NOT_RECORDED，不拿推断补链。":"Traces from a task back through project, datasets, runs, rules, deliverables, files and reviews; a missing link is NOT_RECORDED, never inferred.","输入已登记任务 id，系统按项目→数据集→运行→规则→成果→文件→审核逐环取证。":"Enter a registered task id; the system evidences each link: project → datasets → runs → rules → deliverables → files → reviews.","权限的令牌。在右上角填入令牌后，这里会显示真实记录。":"permission. Enter a token at the top right to see real records here.","鉴权发生在读取请求体之前；拒绝也留痕，令牌只记哈希前八位。":"Authorization happens before the body is read; refusals are logged too, and only the first eight hash characters of a token are kept.","这里展示服务端真实权限矩阵与调用方令牌授权，不在前端伪造角色。没有令牌就只能读公开接口。":"This shows the server's real permission matrix and the caller's token grants; roles are never faked in the front end. Without a token only public endpoints are readable.","的 PERMISSIONS 与授权文件决定。":"PERMISSIONS and the grant file.","域对象、运行日志、成果簿与质检报告的真实配置状态在这里展示；未配置就写「未配置」。":"The real configuration state of domain objects, run journal, deliverable book and quality reports appears here; unconfigured is written as \"not configured\".","权限键是写操作的边界。GET 公开接口不要求令牌；审计读取与所有写入口都要求对应权限。":"Permission keys bound every write. Public GET endpoints need no token; audit reads and all write entries require the matching permission.","条 /":"items /","中…":"ing…","：三层判定":": three-layer verdict","已创建":"Created","已生成":"Built","已登记":"Registered","已记录":"Recorded","已连接":"Connected","已归档：":"Archived: ","未提供":"Not provided","未记录":"Not recorded","未配置":"Not configured","未挂任务":"No task","只读":"Read-only","离线":"Offline","异常":"Error","拒绝":"Rejected","部分":"Partial","执行中…":"Running…","登记中…":"Registering…","创建被拒：":"Create rejected: ","迁移被拒：":"Transition rejected: ","登记被拒：":"Registration rejected: ","审核被拒：":"Review rejected: ","归档被拒：":"Archive rejected: ","质检被拒：":"Quality check rejected: ","执行被拒：":"Execution rejected: ","资源登记被拒：":"Resource registration rejected: ","成果登记被拒：":"Deliverable registration rejected: ","调用失败：":"Call failed: ","令牌不被接受：":"Token rejected: ","没有这个任务：":"No such task: ","提示词不能为空。":"Prompt cannot be empty.","真实端点已配置":"Real endpoint configured","无密钥（本地端点）":"No key (local endpoint)","成果接口未配置":"Deliverable endpoint not configured","运行已记录：":"Run recorded: ","已迁移到":"Transitioned to ","追溯链完整":"Trace complete","追溯链不完整：缺":"Trace incomplete: missing ","人工抽样必须写依据":"Manual sampling requires evidence","先选择一份流程定义":"Select a workflow definition first","网络或服务不可达":"Network or service unreachable","共":"Total ","页":"page","当前":"Current","全选":"Select all","未配置： 缺少 GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME\n\n在服务进程的环境里设置变量后重启；服务端不会生成占位回复。":"Not configured: missing GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME\n\nSet them in the service environment and restart; the server never fabricates a reply.","空":"EMPTY","逐格差分":"Cell-wise difference","尚未配置":"Not configured","目录还是空的":"The registry is still empty","登记模型 / 工具 / Agent 后，这里按可用性列出；不可用的带原因。":"After registering models, tools or agents they are listed by availability; unavailable ones carry the reason.","规则包是数据文件，装载前会整包校验。":"A rule pack is a data file and is validated as a whole before loading.","没有已载规则包":"No rule packs loaded","还没有审核记录":"No review records yet","人工通过才置 accepted；驳回与返工必须写意见。":"Only human approval sets accepted; reject and rerun require an opinion.","提交中…":"Submitting…","读取文件中…":"Reading file…","质检执行中…":"Quality check running…","读取中…":"Loading…","缺少 GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME":"missing GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME","在服务进程的环境里设置变量后重启；服务端不会生成占位回复。":"Set them in the service environment and restart; the server never fabricates a reply.","未配置：":"Not configured: ","还没有运行记录":"No runs yet","还没有流程定义":"No workflow definitions yet","还没有登记成果":"No deliverables registered yet","还没有审计记录":"No audit records yet","还没有登记项目":"No projects registered yet","还没有登记数据集":"No datasets registered yet","没有符合条件的任务":"No tasks match the filter","没有符合条件的审计记录":"No audit records match the filter","钥":"KEY","成果簿需要令牌":"The deliverable book requires a token","审计流需要令牌":"The audit stream requires a token","令牌不被接受":"Token rejected","服务端原由：":"Server reason: ","读取":"Read","权限。在右上角填入令牌后再刷新。":"permission. Enter a token at the top right and refresh.","在右上角填入令牌后读取 ":"Enter a token at the top right, then read ","成果必须是真实文件；登记时读 sha256 和大小，审核通过后才能归档。":"A deliverable must be a real file; registration reads sha256 and size, and archiving only follows approval.","项目是任务的前置：先登记编号、类型、区域、CRS 与高程基准。":"A project precedes a task: register code, type, area, CRS and vertical datum first.","服务端没有声明权限键。":"The server declares no permission keys.","统计":"Profile","栅格统计":"Raster profile","读取统计":"Read profile","关闭":"Close","波段":"Band","没有匹配的数据集":"No matching datasets","清除筛选":"Clear filter","精度核验":"Accuracy","参考真值掩膜":"Reference truth mask","预测掩膜（可空）":"Predicted mask (optional)","留空则使用成果登记路径":"Blank uses the registered deliverable path","参考为合成真值（报告会保留标记）":"Synthetic reference (kept in the report)","精度阈值":"Accuracy thresholds","像元尺寸":"Cell size","单波段读取":"Single-band read","有效像元均值":"Mean of valid cells","NaN / Inf 已剔除，不参与值域":"NaN / Inf excluded from value statistics","读取真实像元中…":"Reading real pixels…","文件在登记后被改写，请重新登记":"Dataset file changed after registration; register again","统计不可用":"Profile unavailable","统计失败":"Profile failed","统计请求失败：网络或服务不可达":"Profile request failed: network or service unreachable","精度阈值必须先给参考真值掩膜":"Accuracy thresholds require a reference truth mask","报告已落盘：":"Report written to:","未计算：本次没有提供参考真值掩膜。":"Not computed: no reference truth mask was supplied.","未开放：精度对比的目标类型必须是成果（deliverable）。":"Not available: accuracy comparison requires a deliverable target.","精度计算失败":"Accuracy calculation failed","参考与预测掩膜无法对齐或无法读取":"reference and predicted masks could not be aligned or read","当前关键词没有命中。调整筛选，或":"No dataset matches the current filter. Adjust it, or","精度对比只对成果开放：当前目标是数据集，参考 / 预测 / 阈值均不提交；切到成果后可启用。":"Accuracy comparison is deliverable-only: the current target is a dataset, so reference / predicted / thresholds are not submitted. Switch to a deliverable to enable them.","精度对比只对成果开放：参考真值掩膜必填，预测掩膜留空时使用成果登记路径；不填参考则报告写「未计算」。":"Accuracy comparison is deliverable-only: reference truth is required; leave the predicted path blank to use the registered deliverable path. Without a reference the report says not computed.","「统计」按波段读真实像元，给出有效 / NODATA / 非有限值与值域；「复核」只重探测哈希与 CRS，不会改动文件。":"Profile reads real pixels by band and reports valid / NODATA / non-finite counts and range; Validate only re-probes the hash and CRS and never changes the file.","数据集登记时读真实文件算 sha256，CRS 取自 sidecar 或 GeoTIFF 头；复核重探测，文件内容变化即 FAIL。":"Dataset registration reads the real file for sha256; CRS comes from the sidecar or GeoTIFF header; re-validation re-probes and FAILs if the content changed.","0–1，可空":"0–1, optional","非有限值":"non-finite","包围盒":"bounds","统计已读取":"Profile loaded","有效像元 ":"valid cells ","标记值 ":"NODATA value ","必须在 0–1 之间":" must be between 0 and 1","阈值 ":"Threshold ","NODATA 已剔除":"NODATA excluded","空间数据":"Spatial data","专业成果验证":"Professional verification","文件与结构":"File and structure","Ref：":"Ref:","Pred：":"Pred:"};
  var SUBKEYS = ["未配置： 缺少 GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME\n\n在服务进程的环境里设置变量后重启；服务端不会生成占位回复。","可用性不是标签：builtin 适配器必须是本仓真实实现，external 必须指向存在的路径；不可用会带原因。Agent 引用未登记的模型或工具会被拒绝。","数据集登记时读真实文件算 sha256，CRS 取自 sidecar 或 classic GeoTIFF 头；复核重探测，文件内容变化即 FAIL。","模型、工具、Agent 分开登记。builtin 必须是真实实现，external 路径不存在即标不可用；Agent 引用未知依赖直接拒绝。","文件与结构、空间数据、专业成果验证三层。第三层没有人工抽样与书面依据，只能是 NOT_RECORDED，汇总结果只能是 PARTIAL。","执行会产生真实运行记录；规则门不过、路径缺失或模型未配置都会落成 FAIL / ERROR。任务编号留空时只独立运行，不写任务关联。","规则是数据不是代码：校验器缺失或异常判 ERROR，条件不满足判 SKIPPED，两者都不升格为 PASS。","从任务串回项目、数据集、运行、规则、成果、文件与审核；缺失的一环写 NOT_RECORDED，不拿推断补链。","规则先行、判定留痕、成果可核。只展示接口真实返回的内容：没有记录就写「未记录」，没有接口就写「未开放」。","规则包整包校验后装载：缺字段、severity 非法、id 重复、与已载冲突都会整包拒绝，不半装。","成果登记读真实文件：哈希、大小、路径当场记录；人工审核通过后才 accepted，之后才允许归档。","定义是登记过的数据：节点 id、类型、阈值都先校验；执行时按这份记录建节点，不另写一套隐藏流程。","「归档」只在 accepted 后开放。归档不会改动文件，只把成果状态与归档人、时间写入域对象。","任何一层没有证据，结果只能是 PARTIAL 或 FAIL；不用推断补链，不用占位冒充真实。","成果只有经人工通过才置为 accepted；驳回或返工必须写意见，已签认的成果拒绝二次审核。","需要 review:write。记录写入同时改成果状态；通过即最终验收，驳回或返工不签认。","这里展示服务端真实权限矩阵与调用方令牌授权，不在前端伪造角色。没有令牌就只能读公开接口。","缺少 GEOOPS_MODEL_BASE_URL / GEOOPS_MODEL_NAME","尚未调用。配置环境变量并重启服务后，这里显示真实模型回复；没有配置时不会生成占位内容。","权限键是写操作的边界。GET 公开接口不要求令牌；审计读取与所有写入口都要求对应权限。","域对象、运行日志、成果簿与质检报告的真实配置状态在这里展示；未配置就写「未配置」。","项目编号、名称、类型、区域、坐标参考、高程基准六项必填；编号唯一，缺一项即拒绝。","输入已登记任务 id，系统按项目→数据集→运行→规则→成果→文件→审核逐环取证。","。外部路径必须已存在且可读；不可用的资源仍会入册，但会写明原因，不会伪装可用。","；无 CRS 或文件不存在会被拒绝。BigTIFF 与像元解码明确不支持。","登记模型 / 工具 / Agent 后，这里按可用性列出；不可用的带原因。","成果必须是真实文件；登记时读 sha256 和大小，审核通过后才能归档。","写入口与审计读取需要令牌；令牌只存在本页 sessionStorage","选择数据集或成果后执行三层质检；结果、逐项证据与报告路径会出现在这里。","项目是任务、数据集、成果追溯的根。登记后不可用同编号重复建项。","七态状态机：非法迁移被拒且不落半条记录；完成与取消必须写理由。","项目是任务的前置：先登记编号、类型、区域、CRS 与高程基准。","。目标状态只列该任务当前允许迁移的项，非法边会被服务端拒绝。","。模型节点在未配置端点时会明确记 ERROR，不会假装通过。","并以 QualityReport 入域，不是只在前端算一遍。","。服务端在读 body 之前校验令牌；没有权限就写不进去。","一次运行里规则门在前、登记在后：判定不过，成果不会被登记。","鉴权发生在读取请求体之前；拒绝也留痕，令牌只记哈希前八位。","在服务进程的环境里设置变量后重启；服务端不会生成占位回复。","登记于 docs/ENGINEERING_TIER.md","builtin:... 或 external:绝对路径","Agent 依赖（模型 id 与工具 id，逗号分隔）","人工通过才置 accepted；驳回与返工必须写意见。","后才返回）；重复 run_id 拒绝，坏行整份拒载。","。路径必须存在且为普通文件；符号链接与目录一律拒绝。","权限的令牌。在右上角填入令牌后，这里会显示真实记录。","。缺字段或编号重复时服务端原文拒绝，不落半条记录。","· 源头信息保留，nodata 仍为 nodata","TSK-...；填写时任务必须为 RUNNING","尚未执行；这里只显示真实运行返回，不预填结果。","。密钥不进浏览器、不写入仓库。测试与运行需要","· 逐格差分 + 4 邻域斑块 + 最小面积","的 PERMISSIONS 与授权文件决定。","真实 AI 模型与外部 GIS 适配器待接","· 真文件、真 sha256、绑已登记成果","AI 资源 · 数据 · 流程 · 规则","按成果 id / 文件名 / 任务筛选","输入任务 id，例如 TSK-xxxx","DS-xxxx 或 DLV-xxxx","Agent 自动执行器仍只做目录登记","· CRS / 格距 / 两期一致性","规则包是数据文件，装载前会整包校验。","字重：细 / 常规 / 中 / 粗","按路径 / 原由 / 令牌前缀筛选","缺环写 NOT_RECORDED","真实遥感影像与专业抽样待用户提供","服务端只从环境变量读端点与密钥：","按 id / 名称 / 项目筛选","权限。在右上角填入令牌后再刷新。","人工签认才置 accepted","工具 · conversion","文件 / 空间 / 专业三层","模型 · algorithm","成果 Deliverable","已完成人工抽样 / 专业核验","，不会写入磁盘。权限由服务端","抽样位置、样本编号、核验结论","统一身份源未接，轮换靠人工","未发布：等级 ≠ 发布资格","模型 · ai-model","专业抽样依据（勾选后必填）","意见（驳回 / 返工必填）","规则门在前 · 登记在后","总览 · 项目 · 任务","质量 · 成果 · 审核","变化检测 2026-11","完成 / 取消必须写理由","在右上角填入令牌后读取 ","核心工程 · CORE","模型类型 / 工具类别","工具 · raster","工具 · vector","运行完成才写一行日志（","数据集 Dataset","1985 国家高程基准","绑定到任务后进入追溯链","例如 变化检测标准流程","没有符合条件的审计记录","服务端没有声明权限键。","缺口按验收表逐项清理","同名 sidecar","执行上下文 JSON","从下表点「迁移」带入","可选；会写入定义记录","任务 id（可选）","任务 id（可空）","变化检测成果 v1","无密钥（本地端点）","人工抽样必须写依据","先选择一份流程定义","没有符合条件的任务","III · 验收","跨进程文件锁未做","模型 Model","适配器 / 路径","工具 · gis","任务编号（可选）","。质检报告会写入","还没有生成追溯链","范围、来源、限制","提示词不能为空。","追溯链不完整：缺","网络或服务不可达","还没有登记数据集","II · 作业","IV · 证据","追溯 · 设置","真实模型运行时","工具 Tool","能力 / 类别","节点 JSON","深空 / 纸面","例如 一期影像","具体问题与依据","资源登记被拒：","成果登记被拒：","令牌不被接受：","没有这个任务：","真实端点已配置","成果接口未配置","没有已载规则包","还没有审核记录","还没有运行记录","还没有流程定义","还没有登记成果","还没有审计记录","还没有登记项目","成果簿需要令牌","审计流需要令牌","I · 治理","文件绝对路径","登记流程定义","执行三层质检","写入审核记录","审计接口需要","令牌只存本页","输入访问令牌","内部唯一编号","行政区或测区","资源显示名称","运行已记录：","恢复已记录：","恢复被拒：","已带入恢复：","恢复自 ","目录还是空的","读取文件中…","质检执行中…","令牌不被接受","服务端原由：","AI 资源","项目 id","任务 id","测试提示词","资源 id","登记数据集","读取并登记","可用节点：","按定义执行","已载规则包","对象 id","已登记成果","成果 id","生成追溯链","存储与策略","角色与权限","按状态筛选","已登记项目","绑定追溯链","姓名或工号","：三层判定","创建被拒：","迁移被拒：","登记被拒：","审核被拒：","归档被拒：","质检被拒：","执行被拒：","调用失败：","追溯链完整","测绘任务","已载规则","登记成果","运行原则","十二模块","工程身份","未清门槛","登记项目","项目编号","项目名称","项目类型","坐标参考","高程基准","新建任务","任务名称","任务类型","迁移状态","目标状态","先填任务","资源目录","测试连接","运行模型","登记资源","流程定义","流程编号","登记定义","执行流程","运行历史","登记链路","变化检测","掩膜写出","成果登记","发起质检","检查对象","本次判定","尚未执行","质检报告","成果名称","成果类型","审核记录","提交审核","审计记录","最近审计","尚未读取","缩小字号","放大字号","切换字重","切换明暗","项目全称","筛选任务","筛选成果","筛选审计","已归档：","未挂任务","执行中…","登记中…","已迁移到","逐格差分","尚未配置","提交中…","读取中…","未配置：","连接中","域对象","未发布","项目册","写操作","需令牌","读取中","数据集","规则门","操作人","文件簿","审核人","调用方","权限键","主导航","莱茵蓝","条 /","已创建","已生成","已登记","已更新 ","已加入模板：","已带入执行：","已记录","已连接","未提供","未记录","未配置","总览","项目","任务","数据","流程","规则","质量","成果","审核","追溯","设置","核心","登记","刷新","区域","需要","台账","全部","草稿","就绪","运行","完成","失败","创建","理由","迁移","资源","类型","名称","版本","接入","标签","需写","说明","检查","备注","签认","结论","通过","驳回","返工","反向","生成","系统","字号","配色","中…","只读","离线","异常","拒绝","部分","当前","全选","读取","统计已读取","有效像元 ","标记值 ","必须在 0–1 之间","阈值 ","精度阈值"];
  function readUi() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } }
  var LANG = (function () {
    var q = (location.search.match(/[?&]lang=(en|zh)/) || [])[1];
    return q || readUi().lang || "zh";
  })();
  document.documentElement.lang = LANG === "en" ? "en" : "zh-CN";
  document.documentElement.dataset.lang = LANG;

  var langBtn = document.getElementById("langBtn");
  if (langBtn) {
    langBtn.textContent = LANG === "en" ? "ZH" : "EN";
    langBtn.title = LANG === "en" ? "Chinese / English" : "中文 / English";
    langBtn.setAttribute("aria-label", LANG === "en" ? "Switch to Chinese" : "Switch to English");
    langBtn.addEventListener("click", function () {
      var st = readUi();
      st.lang = LANG === "en" ? "zh" : "en";
      try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {}
      // 地址栏带着 ?lang= 时，reload 会被查询参数再次覆盖，看起来像「点了没反应」。
      // 切换时把 lang 参数摘掉，让 localStorage 的唯一真身生效。
      var href = location.href.replace(/([?&])lang=(en|zh)(&?)/, function (m, a, b, c) {
        return c ? a : "";
      }).replace(/[?&]$/, "").replace(/\?($|#)/, "$1");
      try { location.replace(href); } catch (e) { location.reload(); }
    });
  }
  if (LANG !== "en") return;

  var reCJK = /[\u4e00-\u9fff]/;
  function tr(s) {
    if (!s || !reCJK.test(s)) return s;
    var lead = s.match(/^\s*/)[0], tail = s.match(/\s*$/)[0];
    var core = s.trim();
    if (!core) return s;
    if (MAP[core] !== undefined) return lead + MAP[core] + tail;
    var cjk = (core.match(/[\u4e00-\u9fff]/g) || []).length;
    if (cjk >= 8) return s;
    var out = core;
    for (var i = 0; i < SUBKEYS.length; i++) {
      var k = SUBKEYS[i];
      if (out.indexOf(k) >= 0) out = out.split(k).join(MAP[k]);
      if (!reCJK.test(out)) break;
    }
    out = out
      .replace(/(\d+)\s*个/g, "$1").replace(/(\d+)\s*件/g, "$1")
      .replace(/(\d+)\s*份/g, "$1").replace(/(\d+)\s*项/g, "$1")
      .replace(/(\d+)\s*条/g, "$1").replace(/(\d+)\s*包/g, "$1")
      .replace(/(\d+)\s*次/g, "$1")
      .replace(/(\d+)\s*条\s*\/\s*/g, "$1 items / ")
      .replace(/\s{2,}/g, " ");
    return lead + out + tail;
  }
  var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1 };
  function walk(node) {
    for (var c = node.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) {
        var v = c.nodeValue;
        if (v && reCJK.test(v)) { var t = tr(v); if (t !== v) c.nodeValue = t; }
      } else if (c.nodeType === 1 && !SKIP[c.tagName]) walk(c);
    }
  }
  function doAttrs(root) {
    var list = root.querySelectorAll("[placeholder],[title],[aria-label]");
    for (var i = 0; i < list.length; i++) {
      (function (el) {
        ["placeholder", "title", "aria-label"].forEach(function (a) {
          var v = el.getAttribute(a);
          if (v && reCJK.test(v)) { var t = tr(v); if (t !== v) el.setAttribute(a, t); }
        });
      })(list[i]);
    }
  }
  function once() {
    walk(document.body);
    doAttrs(document.body);
    var f = document.getElementById("fwBtn");
    if (f) f.title = "Font weight " + (Number(readUi().weight) || 400) + ": light / regular / medium / bold";
  }
  once();
  var timer = null;
  new MutationObserver(function () {
    if (timer) return;
    timer = setTimeout(function () { timer = null; once(); }, 30);
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
})();
