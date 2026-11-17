/* 布猫 · 测绘智序 — 前端骨架
   只渲染接口真实返回的内容；缺令牌、缺接口、无记录分别有各自的空态，不填演示数字。 */
(function () {
  "use strict";

  var KEY = "geoops.ui";
  var state = { section: "overview", status: "", taskQuery: "", artifactQuery: "", auditQuery: "",
                overview: null, tasks: [], rules: null, artifacts: [], audit: null, runs: [],
                projects: [], datasets: [], catalog: null, reviews: [], trace: null, token: "",
                deliverables: [], qualityReports: [], settings: null, lastQuality: null, modelRuntime: null };

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
    if (section === "runs") loadRuns();
    if (section === "rules") loadRules();
    if (section === "quality") loadQualityReports();
    if (section === "artifacts") { loadDeliverables(); loadArtifacts(); }
    if (section === "reviews") loadReviews();
    if (section === "trace") loadAudit();
    if (section === "settings") loadSettings();
  }
  navItems.forEach(function (el) {
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      show(el.dataset.nav);
      try { history.replaceState(null, "", "#" + el.dataset.nav); } catch (e) {}
    });
  });
  window.addEventListener("hashchange", function () {
    var target = location.hash.replace("#", "");
    if (target && document.getElementById(target)) show(target);
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
  function loadRuns() {
    var box = document.getElementById("runTable");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/runs 取运行日志。");
    api("/api/v1/runs").then(function (res) {
      if (res.status === 404) {
        document.getElementById("runsCount").textContent = "未配置";
        box.innerHTML = emptyBox("未", "运行日志未配置", "服务端没有挂载运行日志（<code>--runs</code>），不伪造运行记录。");
        return;
      }
      if (res.status !== 200) {
        document.getElementById("runsCount").textContent = "接口 " + res.status;
        box.innerHTML = emptyBox("未", "运行接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.runs = (res.body && res.body.runs) || [];
      document.getElementById("runsCount").textContent = state.runs.length + " 次";
      renderRuns();
    }).catch(function () {
      box.innerHTML = emptyBox("断", "取不到运行日志", "服务未启动或网络不可达。");
    });
  }

  function runPill(status) {
    var map = { PASS: "pass", FAIL: "fail", ERROR: "fail", SKIP: "idle", SKIPPED: "idle", REUSED: "info" };
    return '<span class="pill ' + (map[status] || "idle") + '">' + esc(status || "—") + "</span>";
  }

  function renderRuns() {
    var box = document.getElementById("runTable");
    var rows = state.runs.slice().reverse();
    if (!rows.length) {
      box.innerHTML = emptyBox("空", "还没有运行记录",
        "运行完成才会写日志；这里没有记录时就是没有跑过，不补示例。");
      return;
    }
    var html = "";
    rows.forEach(function (run) {
      var nodes = run.node_runs || [];
      html += '<div class="run">' +
        '<div class="run-head"><span class="run-id">' + esc(run.run_id) + "</span>" +
        runPill(run.status) +
        '<span class="run-meta"><span>' + esc(run.task_id || "未挂任务") + "</span>" +
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
      html += "</div>";
    });
    box.innerHTML = html;
  }
  var runReload = document.getElementById("runReload");
  if (runReload) runReload.addEventListener("click", loadRuns);

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

  function loadDatasets() {
    var box = document.getElementById("datasetRows");
    box.innerHTML = emptyBox("阅", "读取中", "正在向 /api/v1/datasets 取数据集清单。");
    return api("/api/v1/datasets").then(function (res) {
      if (res.status !== 200) {
        box.innerHTML = emptyBox("未", "数据集接口不可用", "接口返回 " + res.status + "。");
        return;
      }
      state.datasets = (res.body && res.body.datasets) || [];
      document.getElementById("datasetsCount").textContent = state.datasets.length + " 个";
      renderDatasets();
    }).catch(function () { box.innerHTML = emptyBox("断", "取不到数据集", "服务未启动或网络不可达。"); });
  }

  function renderDatasets() {
    var box = document.getElementById("datasetRows");
    if (!state.datasets.length) {
      box.innerHTML = emptyBox("空", "还没有登记数据集", "登记会真实读文件：算 sha256、取 sidecar CRS；缺一项即拒绝。");
      return;
    }
    var html = '<table class="tbl"><thead><tr><th>Dataset</th><th>Project</th><th>Task</th><th>CRS</th><th>sha256</th><th>Size</th><th></th></tr></thead><tbody>';
    state.datasets.forEach(function (row) {
      var p = row.payload || {};
      html += "<tr>" +
        '<td class="id">' + esc(row.object_id) + '<div class="sub">' + esc(p.path) + "</div></td>" +
        '<td class="id">' + esc(p.project_id) + "</td>" +
        '<td class="id">' + esc(p.task_id || "—") + "</td>" +
        '<td class="id">' + esc(p.crs) + "</td>" +
        '<td class="dim">' + shortHash(p.sha256) + "…</td>" +
        '<td class="num">' + bytes(p.size_bytes) + "</td>" +
        '<td class="act"><button class="btn ghost sm" data-validate="' + esc(row.object_id) + '">复核</button></td>' +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
  }

  document.getElementById("datasetRows").addEventListener("click", function (ev) {
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

  function renderQuality(report) {
    var box = document.getElementById("qualityResult");
    if (!box) return;
    if (!report) {
      box.innerHTML = emptyBox("待", "尚未执行", "选择数据集或成果后执行三层质检；结果、逐项证据与报告路径会出现在这里。");
      return;
    }
    var p = report.payload || report;
    var layers = p.layers || {};
    var html = '<div class="quality-result">' +
      '<div class="wrow">' + qualityPill(p.status) +
      '<span class="dim">' + esc(p.report_id || report.object_id || "") + "</span>" +
      '<span class="dim">' + esc(p.generated_at || "") + "</span></div>";
    ["file", "spatial", "professional"].forEach(function (key) {
      var layer = layers[key] || { status: "NOT_RECORDED", checks: [] };
      var names = { file: "文件与结构", spatial: "空间数据", professional: "专业成果验证" };
      html += '<div class="layerbox"><div class="lh"><b>' + esc(key.toUpperCase()) + "</b>" +
        esc(names[key]) + qualityPill(layer.status) + "</div>";
      html += (layer.checks || []).map(function (check) {
        return '<div class="qcheck"><span class="qn">' + esc(check.name) + "</span>" +
          qualityPill(check.status) + '<span class="qd">' + esc(check.detail || "") + "</span></div>";
      }).join("") || '<div class="empty-mini">该层没有记录</div>';
      html += "</div>";
    });
    if (p.report_path) {
      html += '<div class="note">报告已落盘：<code>' + esc(p.report_path) + "</code></div>";
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
        state.lastQuality = state.qualityReports[0];
        renderQuality(state.lastQuality);
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
    var html = '<table class="tbl"><thead><tr><th>Report</th><th>Target</th><th>Task</th><th>Status</th><th>Layers</th><th>Generated</th><th>Path</th></tr></thead><tbody>';
    state.qualityReports.forEach(function (row) {
      var p = row.payload || {};
      var target = p.target || {};
      var layers = p.layers || {};
      html += "<tr>" +
        '<td class="id">' + esc(row.object_id) + "</td>" +
        '<td class="id">' + esc(target.dataset_id || target.deliverable_id || "—") + "</td>" +
        '<td class="id">' + esc(p.task_id || "—") + "</td>" +
        "<td>" + qualityPill(p.status) + "</td>" +
        '<td class="dim">' + ["file", "spatial", "professional"].map(function (k) { return k + ":" + esc((layers[k] || {}).status || "—"); }).join(" · ") + "</td>" +
        '<td class="dim">' + esc(p.generated_at || "") + "</td>" +
        '<td class="wrap">' + esc(p.report_path || "—") + "</td>" +
        "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
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
      var body = {
        target_type: values.target_type,
        target_id: values.target_id,
        task_id: values.task_id,
        professional_sample: sample,
        sample_note: values.sample_note || "",
        actor: values.actor || ""
      };
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
