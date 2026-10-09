"use strict";

(() => {
  const $ = (selector, parent = document) => parent.querySelector(selector);
  const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
  const state = {
    token: "", fields: [], templates: [], projects: [], stats: {}, project: null,
    view: "workspace", stage: "source", dirty: false, fresh: false, revision: 0,
    busy: false, componentKind: "", libraryPage: 1, requestSequence: {},
    componentCache: new Map(), toastTimer: null, loaded: false, dialogSequence: 0,
  };
  const stages = [
    {id: "source", label: "光源", en: "LIGHT SOURCE", title: "光源与收集条件", icon: "☼", number: "01", description: "定义发光尺寸、光通量与收集角度，建立原型的能量入口。", footnote: "Lambertian 收集比例只适用于相应角分布假设。实际 LED、激光和封装光源需要实测或供应商的角分布数据。"},
    {id: "collimator", label: "准直透镜", en: "COLLIMATOR", title: "准直与扩展量预算", icon: "◯", number: "02", kind: "collimators", description: "用目标发散角与有限光源尺寸约束光束口径，并记录参考焦距。", footnote: "轴向扩展量估算不能替代透镜处方验证。可先采用少量确定性光线与角度—位置映射优化，再验证有限光源、渐晕和效率。"},
    {id: "flyeye", label: "复眼阵列", en: "FLY-EYE ARRAY", title: "复眼与目标面覆盖", icon: "▦", number: "03", kind: "flyeyes", description: "设置单元节距、有效口径与中继焦距，检查理想投影覆盖。", footnote: "单元像覆盖只是一阶几何条件；均匀性、阵列拼接、串扰和实际能量分布需要后续光线与公差验证。"},
    {id: "prism", label: "棱镜", en: "PRISM & INTERFACE", title: "棱镜界面与角度余量", icon: "△", number: "04", kind: "prisms", description: "给定材料折射率与入射角区间，检查反射或透射的界面条件。", footnote: "角度使用界面局部法线作参考。TIR 条件适用于指定介质界面；PBS 需要膜系、波长与偏振数据，不能由临界角替代。"},
    {id: "efficiency", label: "系统预算", en: "SYSTEM BUDGET", title: "逐级效率与输出预算", icon: "↗", number: "05", description: "记录每一级假设效率，观察光通量如何沿光学链路变化。", footnote: "各级效率只有在定义与分母一致时才能相乘。不要把已含某项损失的效率再次计入；输出预算不代表通过亮度验收。"},
  ];
  const groupAliases = {source: "source", collimator: "collimator", flyeye: "flyeye", prism: "prism", efficiency: "efficiency"};
  const viewTitles = {workspace: "参数工作台", library: "资料数据库", components: "器件参考库", knowledge: "设计知识", models: "模型索引"};
  const kindTitles = {collimators: "准直透镜", flyeyes: "复眼阵列", prisms: "棱镜"};
  const statusTitles = {unread: "未核读", unread_or_no_registered_review: "未登记核读", registered_partial_review: "范围性核读", partial_review: "范围性核读", reviewed: "已核读", excluded: "已排除", excluded_after_classification: "分类后排除", excluded_not_optical: "已排除（非光学）", synthetic_demo: "演示假设", historical_candidate: "历史候选", historical: "历史候选", demo: "演示假设"};
  const parameterGroups = {
    source: new Set(["source_width_mm", "source_height_mm", "source_lumens", "collection_half_angle_deg", "source_model", "custom_collection_fraction"]),
    collimator: new Set(["output_half_angle_x_deg", "output_half_angle_y_deg", "reference_efl_mm"]),
    flyeye: new Set(["pitch_x_mm", "pitch_y_mm", "cell_clear_width_mm", "cell_clear_height_mm", "cell_efl_mm", "relay_efl_mm", "wavelength_nm", "columns", "rows", "target_width_mm", "target_height_mm", "margin_mm"]),
    prism: new Set(["n_high", "n_low", "incidence_min_deg", "incidence_max_deg", "required_margin_deg", "prism_behavior"]),
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function button(label, className, action) {
    const node = el("button", className, label);
    node.type = "button";
    if (action) node.addEventListener("click", action);
    return node;
  }
  function valueText(value) {
    if (value === null || value === undefined || value === "") return "未提供";
    if (typeof value === "boolean") return value ? "是" : "否";
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
  }
  function finite(value) { return typeof value === "number" && Number.isFinite(value); }
  function num(value, digits = 2) {
    return finite(value) ? new Intl.NumberFormat("zh-CN", {maximumFractionDigits: digits}).format(value) : "—";
  }
  function percent(value, digits = 1) { return finite(value) ? `${num(value * 100, digits)}%` : "—"; }
  function pick(object, keys) {
    for (const key of keys) if (object && object[key] !== undefined && object[key] !== null) return object[key];
    return undefined;
  }
  function statusLabel(status) { return statusTitles[status] || status || "状态未提供"; }
  function badge(label, tone = "neutral") { return el("span", `pill pill-${tone}`, label); }
  function loading(container, text = "正在读取…") {
    const block = el("div", "list-message");
    block.setAttribute("role", "status");
    block.append(el("span", "loading-spinner"), document.createTextNode(text));
    container.replaceChildren(block);
  }
  function message(container, text, error = false) {
    const block = el("div", `list-message${error ? " list-error" : ""}`, text);
    if (error) block.setAttribute("role", "alert");
    container.replaceChildren(block);
  }
  function toast(text, error = false) {
    clearTimeout(state.toastTimer);
    $("#toast-region").replaceChildren(el("div", `toast${error ? " error" : ""}`, text));
    state.toastTimer = setTimeout(() => $("#toast-region").replaceChildren(), error ? 8000 : 4500);
  }
  async function api(path, body) {
    const options = {headers: {Accept: "application/json"}, credentials: "same-origin"};
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.headers["X-Workbench-Token"] = state.token;
      options.body = JSON.stringify(body);
    }
    let response;
    try { response = await fetch(path, options); }
    catch { throw new Error("无法连接本地工作台服务，请确认服务仍在运行。"); }
    let data;
    try { data = await response.json(); }
    catch { throw new Error(`服务返回了无法读取的响应（HTTP ${response.status}）。`); }
    if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）。`);
    return data;
  }
  async function withBusy(action) {
    if (state.busy) return;
    state.busy = true;
    updateControls();
    try { return await action(); }
    catch (error) { toast(error.message, true); }
    finally { state.busy = false; updateControls(); }
  }
  let visual;
  function updateControls() {
    const noProject = !state.project;
    ["#save-button", "#clone-button", "#export-button", "#calculate-button", "#project-name", "#project-notes"].forEach(selector => { $(selector).disabled = noProject || state.busy; });
    ["#new-button", "#empty-new-button", "#import-button", "#project-select", "#sync-button"].forEach(selector => { $(selector).disabled = state.busy || !state.loaded; });
    $$("#parameter-fields input, #parameter-fields select, #component-selection button").forEach(node => { node.disabled = noProject || state.busy; });
    $("#calculate-button").textContent = state.busy ? "正在处理…" : "计算原型预算 ↗";
    const status = $("#save-status");
    status.textContent = noProject ? "尚未载入" : state.busy ? "处理中…" : state.dirty ? "● 有未保存修改" : `已保存 · v${state.project.version ?? 1}`;
    status.classList.toggle("is-dirty", state.dirty);
    visual?.update();
  }
  function markEdited() {
    state.dirty = true;
    state.fresh = false;
    state.revision += 1;
    updateControls();
    updateResultState();
  }
  function fieldStage(field) {
    if (groupAliases[field.group]) return groupAliases[field.group];
    return Object.keys(parameterGroups).find(group => parameterGroups[group].has(field.key)) || "efficiency";
  }
  function renderChain() {
    $("#optical-chain").replaceChildren(...stages.map(stage => {
      const node = button("", `chain-step${state.stage === stage.id ? " active" : ""}`, () => changeStage(stage.id));
      node.id = `stage-${stage.id}`;
      node.setAttribute("role", "tab");
      node.setAttribute("aria-selected", String(stage.id === state.stage));
      node.setAttribute("aria-controls", "parameter-form");
      node.tabIndex = stage.id === state.stage ? 0 : -1;
      node.dataset.stage = stage.id;
      const icon = el("span", "chain-icon", stage.icon); icon.setAttribute("aria-hidden", "true");
      const copy = el("div"); copy.append(el("h3", "", stage.label), el("small", "", stage.en));
      node.append(icon, copy);
      node.addEventListener("keydown", event => {
        const index = stages.findIndex(item => item.id === stage.id);
        let next;
        if (event.key === "ArrowRight") next = (index + 1) % stages.length;
        else if (event.key === "ArrowLeft") next = (index + stages.length - 1) % stages.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = stages.length - 1;
        if (next !== undefined) { event.preventDefault(); changeStage(stages[next].id); $(`#stage-${stages[next].id}`).focus(); }
      });
      return node;
    }));
  }
  function changeStage(stage) {
    state.stage = stage;
    renderChain();
    renderFields();
  }
  function renderFields() {
    const stage = stages.find(item => item.id === state.stage);
    $("#parameter-title").textContent = stage.title;
    $("#parameter-eyebrow").textContent = stage.en;
    $("#parameter-number").textContent = stage.number;
    $("#parameter-description").textContent = stage.description;
    $("#parameter-footnote").textContent = stage.footnote;
    const form = $("#parameter-form");
    form.setAttribute("aria-labelledby", `stage-${stage.id}`);
    const fields = state.fields.filter(field => fieldStage(field) === stage.id);
    $("#parameter-fields").replaceChildren(...fields.map(field => {
      const wrap = el("div", "field");
      const label = el("label", "", field.label || field.key);
      label.htmlFor = `field-${field.key}`;
      const inputWrap = el("div", "input-wrap");
      let input;
      const current = state.project?.parameters?.[field.key];
      if (field.type === "select") {
        input = el("select");
        const hasValue = (field.options || []).some(option => String(option.value) === String(current));
        const unset = el("option", "", hasValue ? "选择…" : current === undefined || current === null || current === "" ? "未设定" : `未识别：${current}`);
        unset.value = ""; input.append(unset);
        (field.options || []).forEach(option => { const node = el("option", "", option.label || option.value); node.value = option.value; input.append(node); });
        input.value = hasValue ? String(current) : "";
      } else {
        input = el("input", field.unit ? "has-unit" : "");
        input.type = "number";
        input.inputMode = "decimal";
        input.step = field.step ?? "any";
        if (field.min !== undefined) input.min = field.min;
        if (field.max !== undefined) input.max = field.max;
        input.placeholder = "未设定";
        input.value = finite(current) ? current : "";
        if (field.unit) inputWrap.append(el("span", "input-unit", field.unit));
      }
      input.id = `field-${field.key}`;
      input.name = field.key;
      const hintText = field.hint || (field.key === "custom_collection_fraction" ? "仅在“自定义角收集比例”模型下参与计算。" : "");
      if (hintText) input.setAttribute("aria-describedby", `hint-${field.key}`);
      input.addEventListener(field.type === "select" ? "change" : "input", () => {
        if (!state.project) return;
        const value = field.type === "select" ? (input.value || null) : input.value === "" ? null : Number(input.value);
        state.project.parameters[field.key] = value;
        markEdited();
      });
      inputWrap.prepend(input);
      wrap.append(label, inputWrap);
      if (hintText) { const hint = el("p", "field-hint", hintText); hint.id = `hint-${field.key}`; wrap.append(hint); }
      return wrap;
    }));
    renderComponentSelection(stage);
    updateControls();
  }
  function renderComponentSelection(stage) {
    const container = $("#component-selection");
    container.replaceChildren();
    container.hidden = !stage.kind;
    if (!stage.kind) return;
    const selectedId = state.project?.selected_components?.[stage.kind];
    const item = selectedId ? state.componentCache.get(selectedId) : null;
    const copy = el("div");
    copy.append(el("strong", "", selectedId ? item?.name || `已关联：${selectedId}` : "从参考库选择器件"), el("small", "", selectedId ? "关联候选 · 参数变更仍需重新验证" : "历史参数采用后会记录来源与假设"));
    container.append(copy, button(selectedId ? "查看 / 更换" : "选择候选 ↗", "button button-secondary button-small", () => { state.componentKind = stage.kind; setComponentFilters(); navigate("components"); }));
  }
  function updateProjectOptions() {
    const selector = $("#project-select");
    selector.replaceChildren();
    if (!state.projects.length) { const option = el("option", "", "还没有原型"); option.value = ""; selector.append(option); }
    state.projects.forEach(project => { const option = el("option", "", project.name || "未命名原型"); option.value = project.id; selector.append(option); });
    if (state.project) selector.value = state.project.id;
  }
  function adoptProject(project) {
    state.project = project;
    state.project.parameters ||= {};
    state.project.selected_components ||= {};
    state.dirty = false;
    state.fresh = Boolean(project.calculation);
    state.revision += 1;
    const old = state.projects.findIndex(item => item.id === project.id);
    const summary = {id: project.id, name: project.name, version: project.version, updated_at: project.updated_at, template: project.template};
    if (old >= 0) state.projects[old] = summary; else state.projects.unshift(summary);
    updateProjectOptions();
    $("#project-name").value = project.name || "";
    $("#project-notes").value = project.notes || "";
    $("#workspace-content").hidden = false;
    $("#workspace-empty").hidden = true;
    renderChain(); renderFields(); renderResults(); updateControls();
    $("#external-update").hidden = true;
    visual?.load(project);
    try { localStorage.setItem("optics-workbench:last-project", project.id); } catch { /* Persistence is optional. */ }
  }
  function confirmDiscard() {
    return !state.dirty || window.confirm("当前原型有未保存的修改。继续切换将丢弃这些修改，是否继续？");
  }
  async function loadProject(id) {
    if (!id) return;
    await withBusy(async () => adoptProject(await api(`/api/projects/${encodeURIComponent(id)}`)));
    updateProjectOptions();
  }
  function validateInputs() {
    const invalid = state.fields.find(field => {
      const value = state.project?.parameters?.[field.key];
      if (value === undefined || value === null || value === "") return true;
      if (field.type === "select") return !(field.options || []).some(option => String(option.value) === String(value));
      return !finite(value) || (field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max);
    });
    if (invalid) {
      changeStage(fieldStage(invalid));
      $(`#field-${invalid.key}`)?.focus();
      toast(`请检查“${invalid.label || invalid.key}”：需要填写符合范围的参数。`, true);
      return false;
    }
    if (!state.project.name?.trim()) { $("#project-name").focus(); toast("请填写原型名称。", true); return false; }
    return true;
  }
  async function calculate() {
    if (!state.project || !validateInputs()) return;
    await withBusy(async () => {
      const revision = state.revision;
      const result = await api("/api/calculate", state.project);
      state.project.calculation = result;
      state.fresh = state.revision === revision;
      renderResults();
      toast("预算已更新；计算结果依赖当前输入假设。");
    });
  }
  async function saveProject() {
    if (!state.project || !validateInputs()) return;
    await withBusy(async () => { adoptProject(await api("/api/projects", state.project)); toast("原型与计算预算已保存到本地数据库。"); });
  }
  function updateResultState() {
    const hasResult = Boolean(state.project?.calculation);
    const node = $("#result-status");
    node.textContent = hasResult ? state.fresh ? "已计算" : "参数已变更" : "等待计算";
    node.className = `pill pill-${hasResult ? state.fresh ? "teal" : "warning" : "neutral"}`;
    $("#results-body").classList.toggle("stale-results", hasResult && !state.fresh);
    $("#checks-panel").classList.toggle("stale-checks", hasResult && !state.fresh);
    if (hasResult) {
      const count = (state.project.calculation.checks || []).filter(check => check.status !== "ok").length;
      $("#checks-count").textContent = `${state.fresh ? "" : "上次检查 · "}${count} 项待关注`;
    }
    $("#calculation-caption").textContent = hasResult && !state.fresh ? "当前显示上次预算及检查。请重新计算以对应当前参数。" : hasResult ? `计算器 ${state.project.calculation.calculator_version || "版本未提供"} · ${state.dirty ? "当前修改尚未保存" : "条件性估算"}` : "填写参数后，计算光通量与几何边界。";
  }
  function metricTile(label, value, unit, note) {
    const tile = el("div", "metric-tile");
    const val = el("div", "metric-value", value);
    if (unit) val.append(el("small", "", unit));
    tile.append(el("div", "metric-label", label), val);
    if (note) tile.append(el("div", "metric-note", note));
    return tile;
  }
  function renderResults() {
    const result = state.project?.calculation;
    const container = $("#results-body");
    container.replaceChildren();
    $("#checks-panel").hidden = !result;
    if (!result) {
      const empty = el("div", "empty-results");
      empty.append(el("span", "empty-symbol", "⌁"), el("p", "", "将参数转化为可比较的预算。"));
      container.append(empty);
      updateResultState(); return;
    }
    const power = result.power || {}, collimator = result.collimator || {}, flyeye = result.flyeye || {}, prism = result.prism || {};
    const main = el("div", "main-metric");
    const mainValue = el("div", "main-value", num(power.output_lumens, 1));
    mainValue.append(el("span", "metric-unit", "lm"));
    main.append(el("div", "metric-label", "预计系统输出光通量"), mainValue, el("div", "main-metric-note", `总效率 ${percent(power.total_efficiency)}　·　收集比例 ${percent(power.collection_fraction)}`));
    const metrics = el("div", "result-metrics");
    const beamX = pick(collimator, ["axis_matched_output_width_mm", "output_width_mm", "beam_width_mm"]);
    const beamY = pick(collimator, ["axis_matched_output_height_mm", "output_height_mm", "beam_height_mm"]);
    const coverX = pick(flyeye, ["projected_cell_width_mm", "coverage_width_mm"]);
    const coverY = pick(flyeye, ["projected_cell_height_mm", "coverage_height_mm"]);
    metrics.append(metricTile("准直光束口径", `${num(beamX)} × ${num(beamY)}`, "mm", "轴向匹配的一阶估算"));
    metrics.append(metricTile("复眼单元像覆盖", `${num(coverX)} × ${num(coverY)}`, "mm", typeof flyeye.covers_target_rectangle === "boolean" ? flyeye.covers_target_rectangle ? "理想覆盖满足输入目标" : "理想覆盖不足，请检查" : "覆盖结果需确认"));
    if (prism.supported === false || state.project.parameters.prism_behavior === "pbs") {
      metrics.append(metricTile("PBS 偏振界面", "待膜系数据", "", prism.note || "需要波长、角度及偏振性能"));
    } else {
      const margin = pick(prism, ["intended_clearance_deg", "minimum_margin_deg", "margin_deg"]);
      metrics.append(metricTile(state.project.parameters.prism_behavior === "transmit" ? "透射临界角余量" : "TIR 临界角余量", num(margin), "°", `需求 ${num(prism.required_margin_deg ?? state.project.parameters.required_margin_deg)}° · 临界角 ${num(prism.critical_angle_deg)}°`));
    }
    container.append(main, metrics);
    if (Array.isArray(power.stages) && power.stages.length) {
      const efficiency = el("div", "efficiency-section");
      efficiency.append(el("div", "metric-label", "逐级光通量"));
      const max = Math.max(...power.stages.map(item => finite(item.lumens) ? item.lumens : 0), 1);
      power.stages.forEach(stage => {
        const row = el("div", "efficiency-row");
        row.append(el("span", "stage-name", stage.name || "未命名阶段"), el("span", "stage-value", `${num(stage.lumens, 1)} lm`));
        const bar = el("div", "efficiency-bar"), fill = el("div", "efficiency-fill");
        fill.style.width = `${finite(stage.lumens) ? Math.max(0, Math.min(100, stage.lumens / max * 100)) : 0}%`;
        bar.append(fill); efficiency.append(row, bar);
      });
      container.append(efficiency);
    }
    const checks = Array.isArray(result.checks) ? result.checks : [];
    $("#checks-count").textContent = `${checks.filter(check => check.status !== "ok").length} 项待关注`;
    $("#checks-list").replaceChildren(...checks.map(check => {
      const status = ["ok", "attention", "unknown"].includes(check.status) ? check.status : "unknown";
      const item = el("div", `check-item ${status}`);
      const symbol = el("span", "check-symbol", status === "ok" ? "✓" : status === "attention" ? "!" : "○");
      symbol.setAttribute("aria-label", status === "ok" ? "计算条件满足" : status === "attention" ? "需要关注" : "条件未知");
      const copy = el("div"); copy.append(el("div", "check-title", check.title || "检查项"), el("div", "check-detail", check.detail || "未提供详细说明"));
      item.append(symbol, copy); return item;
    }));
    const assumptions = Array.isArray(result.assumptions) ? result.assumptions : [];
    $("#assumptions-list").replaceChildren(...assumptions.map(value => el("li", "", value)));
    $("#assumptions-details").hidden = !assumptions.length;
    updateResultState();
  }
  function openDialog(title, eyebrow = "") {
    state.dialogSequence += 1;
    $("#dialog-title").textContent = title;
    $("#dialog-eyebrow").textContent = eyebrow;
    $("#dialog-content").replaceChildren();
    $("#dialog-actions").replaceChildren();
    $("#dialog-actions").hidden = true;
    if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
    return $("#dialog-content");
  }
  function section(title, children) {
    const node = el("section", "detail-section");
    node.append(el("h3", "", title));
    (Array.isArray(children) ? children : [children]).filter(Boolean).forEach(child => node.append(child));
    return node;
  }
  function detailGrid(pairs) {
    const grid = el("dl", "detail-grid");
    pairs.forEach(([label, value]) => { grid.append(el("dt", "", label), el("dd", "", valueText(value))); });
    return grid;
  }
  function showNewDialog() {
    if (!confirmDiscard()) return;
    const content = openDialog("新建参数原型", "START WITH A TEMPLATE");
    content.append(el("p", "field-hint", "选择起始模板。所有默认值均为演示假设，可在原型中替换。"));
    state.templates.forEach(template => {
      const option = button("", "template-option", async () => {
        $("#detail-dialog").close();
        await withBusy(async () => { adoptProject(await api("/api/projects/new", {template: template.id})); navigate("workspace"); toast("已创建演示参数原型，请按实际条件修改。"); });
      });
      option.append(el("strong", "", template.name || template.id), el("span", "", template.description || "参数化演示模板"));
      content.append(option);
    });
    if (!state.templates.length) content.append(el("p", "list-message", "当前没有可用模板。"));
  }
  async function exportProject() {
    if (!state.project) return;
    if (state.dirty) { toast("请先保存修改，再导出当前原型。", true); return; }
    await withBusy(async () => {
      const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/export`);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json;charset=utf-8"});
      const url = URL.createObjectURL(blob), anchor = el("a");
      anchor.href = url; anchor.download = `${(state.project.name || "optical-prototype").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 100)}.json`;
      document.body.append(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 3000);
      toast("原型已导出；公开分享前仍请检查自行填写的备注。");
    });
  }
  async function cloneProject() {
    if (!state.project) return;
    if (state.dirty) { toast("请先保存修改，再复制原型。", true); return; }
    await withBusy(async () => {
      const exported = await api(`/api/projects/${encodeURIComponent(state.project.id)}/export`);
      if (exported.project) exported.project.name = `${String(exported.project.name || "光学原型").slice(0, 110)} · 副本`;
      const copy = await api("/api/projects/import", exported);
      adoptProject(copy); toast("已创建独立副本，可以继续修改参数。");
    });
  }
  async function importFile(file) {
    if (!file) return;
    if (!confirmDiscard()) return;
    if (file.size > 2 * 1024 * 1024) { toast("原型 JSON 文件过大，请使用工作台导出的参数文件。", true); return; }
    await withBusy(async () => {
      let payload;
      try { payload = JSON.parse(await file.text()); }
      catch { throw new Error("无法解析 JSON，请检查文件是否为工作台导出的原型。"); }
      adoptProject(await api("/api/projects/import", payload)); navigate("workspace"); toast("原型已导入为新的本地记录。");
    });
  }
  function navigate(view, updateHash = true) {
    if (!Object.prototype.hasOwnProperty.call(viewTitles, view)) view = "workspace";
    state.view = view;
    $$(".view").forEach(node => { node.hidden = node.id !== `view-${view}`; });
    $$(".nav-item").forEach(node => { const active = node.dataset.view === view; node.classList.toggle("active", active); if (active) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
    $("#breadcrumb-current").textContent = viewTitles[view];
    if (updateHash && location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
    if (!state.loaded) return;
    if (view === "library") loadLibrary();
    if (view === "components") loadComponents();
    if (view === "knowledge") loadKnowledge();
    if (view === "models") loadModels();
  }
  function renderStats() {
    const stats = state.stats || {};
    const statusCounts = stats.status_counts || stats.reading_status_counts || stats.coverage_by_status || stats.coverage?.status_counts || {};
    const unique = pick(stats, ["unique_documents", "unique_files", "unique_hashes", "document_count", "documents", "unique_contents"]) ?? stats.coverage?.unique_hashes;
    const reviewed = pick(stats, ["reviewed_documents", "reviewed", "partial_review_count"]) ?? statusCounts.registered_partial_review;
    const unread = pick(stats, ["unread_documents", "unread"]) ?? statusCounts.unread;
    const components = pick(stats, ["component_count", "components", "catalog_entries"]);
    $("#library-stats").replaceChildren(...[[unique, "去重内容"], [reviewed, "已有范围性核读"], [unread, "待读内容"], [components, "器件参考条目"]].map(([value, label]) => { const card = el("div", "stat-card"); card.append(el("div", "stat-value", num(value, 0)), el("div", "stat-label", label)); return card; }));
    const filter = $("#library-status"), current = filter.value;
    if (Object.keys(statusCounts).length) {
      const all = el("option", "", "全部核读状态"); all.value = "";
      filter.replaceChildren(all, ...Object.keys(statusCounts).map(status => { const option = el("option", "", `${statusLabel(status)} (${statusCounts[status]})`); option.value = status; return option; }));
      if (Object.hasOwn(statusCounts, current)) filter.value = current;
    }
  }
  async function latestList(name, container, getData, render) {
    const seq = (state.requestSequence[name] || 0) + 1;
    state.requestSequence[name] = seq;
    loading(container);
    try { const result = await getData(); if (seq === state.requestSequence[name]) render(result); }
    catch (error) { if (seq === state.requestSequence[name]) message(container, error.message, true); }
  }
  async function loadLibrary() {
    renderStats();
    $("#library-pagination").replaceChildren();
    await latestList("library", $("#library-list"), () => api(`/api/library?${new URLSearchParams({q: $("#library-search").value, status: $("#library-status").value, page: String(state.libraryPage)})}`), data => {
      const items = data.items || [], total = data.total || 0;
      $("#library-count").textContent = `${num(total, 0)} 项内容`;
      if (!items.length) { message($("#library-list"), "没有找到匹配资料。试试其他关键词或核读状态。"); return; }
      const table = el("table", "data-table"), thead = el("thead"), header = el("tr");
      ["文件 / 内容", "格式", "核读状态", "副本"].forEach(label => { const th = el("th", "", label); th.scope = "col"; header.append(th); });
      thead.append(header); const body = el("tbody");
      items.forEach(item => {
        const row = el("tr"), title = el("td");
        title.append(button(item.title || "未命名资料", "document-title", () => openDocument(item.id)));
        const sources = Array.isArray(item.source_ids) ? item.source_ids.join(" · ") : item.source_ids;
        title.append(el("div", "document-meta", sources || item.summary || item.id));
        const format = el("td", "format-chip", item.format || "—"), status = el("td");
        status.append(badge(statusLabel(item.status), item.status?.includes("review") ? "teal" : "neutral"));
        row.append(title, format, status, el("td", "", valueText(item.path_count))); body.append(row);
      });
      table.append(thead, body); $("#library-list").replaceChildren(table);
      const pages = Math.max(1, Math.ceil(total / (data.limit || 30))), page = data.page || state.libraryPage;
      const actions = el("div", "pagination-actions");
      const prev = button("← 上一页", "button button-secondary button-small", () => { state.libraryPage = page - 1; loadLibrary(); }); prev.disabled = page <= 1;
      const next = button("下一页 →", "button button-secondary button-small", () => { state.libraryPage = page + 1; loadLibrary(); }); next.disabled = page >= pages;
      actions.append(prev, next);
      $("#library-pagination").replaceChildren(el("span", "", `第 ${page} / ${pages} 页 · 按内容去重`), actions);
    });
  }
  async function openDocument(id) {
    const container = openDialog("资料来源详情", "SOURCE & REVIEW SCOPE");
    const sequence = state.dialogSequence;
    loading(container);
    try {
      const data = await api(`/api/library/${encodeURIComponent(id)}`);
      if (!$("#detail-dialog").open || sequence !== state.dialogSequence) return;
      $("#dialog-title").textContent = data.title || "资料来源详情";
      container.replaceChildren(section("索引信息", detailGrid([["核读状态", statusLabel(data.status)], ["文件格式", data.format], ["内容标识", data.sha256 || data.id], ["来源编号", data.source_ids]])));
      if (data.summary) container.append(section("范围说明", el("p", "", data.summary)));
      if (Array.isArray(data.reviews) && data.reviews.length) {
        const reviews = data.reviews.map(review => {
          const block = el("div", "detail-section");
          block.append(detailGrid([["来源记录", review.source_id], ["已核读范围", review.scope], ["证据参考", review.reference]]));
          return block;
        });
        container.append(section("核读记录", reviews));
      } else container.append(section("核读范围", el("p", "", "当前没有核读证据。文件存在于索引中，并不表示已读取或验证。")));
      if (Array.isArray(data.paths) && data.paths.length) container.append(section("本地来源定位", data.paths.map(path => el("p", "path-text", typeof path === "object" ? path.path || valueText(path) : path))));
    } catch (error) { if (sequence === state.dialogSequence && $("#detail-dialog").open) message(container, error.message, true); }
  }
  function setComponentFilters() {
    $$("#component-filters button").forEach(node => { const active = node.dataset.kind === state.componentKind; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
  }
  async function loadComponents() {
    setComponentFilters();
    await latestList("components", $("#component-list"), () => api(`/api/components?${new URLSearchParams({kind: state.componentKind, q: $("#component-search").value})}`), data => {
      const items = Array.isArray(data) ? data : data.items || [];
      $("#component-count").textContent = `${items.length} 项候选`;
      if (!items.length) { message($("#component-list"), "没有匹配器件。更改关键词或器件类型后重试。"); return; }
      $("#component-list").replaceChildren(...items.map(item => {
        state.componentCache.set(item.id, item);
        const card = el("article", "component-card"), top = el("div", "card-topline");
        top.append(el("span", "component-type", kindTitles[item.kind] || item.kind || "参考器件"), badge(statusLabel(item.status), "neutral"));
        card.append(top, el("h3", "", item.name || item.id));
        const props = el("div", "component-properties");
        (item.fields || []).slice(0, 3).forEach(field => { const row = el("div", "component-property"); row.append(el("span", "", field.label), el("strong", "", valueText(field.value))); props.append(row); });
        card.append(props, el("div", "card-source", `来源 ${item.source_id || "未提供"}${item.source_sheet ? ` · ${item.source_sheet}` : ""}${item.source_row ? ` · 第 ${item.source_row} 行` : ""}`));
        const foot = el("div", "card-footer");
        foot.append(el("span", "muted", `${item.suggestions?.length || 0} 项建议参数`), button("查看候选 ↗", "button button-quiet", () => showComponent(item)));
        card.append(foot); return card;
      }));
    });
  }
  function showComponent(item) {
    const container = openDialog(item.name || item.id, "REFERENCE CANDIDATE");
    container.append(section("来源与适用性", detailGrid([["类别", kindTitles[item.kind] || item.kind], ["记录状态", statusLabel(item.status)], ["来源编号", item.source_id], ["工作表 / 行", `${item.source_sheet || "未提供"} / ${item.source_row || "未提供"}`]])));
    if (item.fields?.length) container.append(section("参考字段", detailGrid(item.fields.map(field => [`${field.label}${field.cell ? ` (${field.cell})` : ""}`, field.value]))));
    const suggestions = (item.suggestions || []).filter(suggestion => state.fields.some(field => field.key === suggestion.parameter));
    const suggestionSection = el("div"), selected = new Set(suggestions.map((_, index) => index));
    if (suggestions.length) {
      suggestionSection.append(el("p", "", "勾选需要采用的参数。采用是新的设计假设，不表示历史器件已适配当前系统。"));
      suggestions.forEach((suggestion, index) => {
        const row = el("label", "suggestion-row"), checkbox = el("input");
        checkbox.type = "checkbox"; checkbox.checked = true;
        checkbox.addEventListener("change", () => checkbox.checked ? selected.add(index) : selected.delete(index));
        const copy = el("span"), field = state.fields.find(entry => entry.key === suggestion.parameter);
        copy.append(el("span", "suggestion-title", `${field?.label || suggestion.parameter} = ${valueText(suggestion.value)} ${field?.unit || ""}`), el("span", "suggestion-note", suggestion.note || "未附额外条件；需要自行确认适用性。"));
        row.append(checkbox, copy); suggestionSection.append(row);
      });
      container.append(section("可采用的原型假设", suggestionSection));
    } else container.append(section("参数采用", el("p", "", "当前条目没有可直接映射的建议参数。可关联该候选，并在原型中手动填写。")));
    const actions = $("#dialog-actions"); actions.hidden = false;
    const apply = button("采用为原型假设", "button button-primary", () => {
      if (!state.project || state.busy) return;
      const chosen = [...selected].sort((a, b) => a - b).map(index => suggestions[index]);
      chosen.forEach(suggestion => { state.project.parameters[suggestion.parameter] = suggestion.value; });
      state.project.selected_components[item.kind] = item.id;
      const provenance = [`采用参考候选：${item.name || item.id} [${item.id}]`, `来源：${item.source_id || "未提供"}${item.source_sheet ? ` / ${item.source_sheet}` : ""}${item.source_row ? ` / 行 ${item.source_row}` : ""}`, "适用性：历史候选或演示值，仅作为当前原型假设，尚未完成器件匹配验证。", ...chosen.map(suggestion => `${suggestion.parameter}=${valueText(suggestion.value)}；${suggestion.note || "需确认适用条件"}`)].join("\n");
      state.project.notes = [state.project.notes, provenance].filter(Boolean).join("\n\n");
      $("#project-notes").value = state.project.notes;
      markEdited();
      $("#detail-dialog").close();
      const stage = stages.find(entry => entry.kind === item.kind);
      if (stage) changeStage(stage.id);
      navigate("workspace"); toast(`已关联候选并采用 ${chosen.length} 项参数；请重新计算并保存。`);
    });
    apply.disabled = !state.project || state.busy;
    if (!state.project) actions.append(el("span", "muted", "请先创建或载入一个原型。"));
    actions.append(button("关闭", "button button-secondary", () => $("#detail-dialog").close()), apply);
  }
  async function loadKnowledge() {
    await latestList("knowledge", $("#knowledge-list"), () => api(`/api/knowledge?${new URLSearchParams({q: $("#knowledge-search").value})}`), data => {
      const items = Array.isArray(data) ? data : data.items || [];
      if (!items.length) { message($("#knowledge-list"), "没有匹配的知识条目。试试相关术语或更短的关键词。"); return; }
      $("#knowledge-list").replaceChildren(...items.map(item => {
        const card = el("article", "knowledge-card");
        card.append(el("div", "eyebrow", "METHOD & EVIDENCE"), el("h3", "", item.title || item.slug), el("p", "knowledge-excerpt", item.excerpt || "查看方法、条件与来源。"));
        const foot = el("div", "card-footer");
        foot.append(el("span", "muted", "设计参考"), button("阅读条目 ↗", "button button-quiet", () => openKnowledge(item.slug)));
        card.append(foot); return card;
      }));
    });
  }
  async function openKnowledge(slug) {
    const container = openDialog("设计知识", "METHOD, CONDITIONS & EVIDENCE"); loading(container);
    const sequence = state.dialogSequence;
    try { const data = await api(`/api/knowledge/${encodeURIComponent(slug)}`); if (!$("#detail-dialog").open || sequence !== state.dialogSequence) return; $("#dialog-title").textContent = data.title || data.slug || "设计知识"; container.replaceChildren(el("pre", "plain-reference", data.body || "条目正文为空。")); }
    catch (error) { if (sequence === state.dialogSequence && $("#detail-dialog").open) message(container, error.message, true); }
  }
  async function loadModels() {
    await latestList("models", $("#models-list"), () => api(`/api/models?${new URLSearchParams({q: $("#models-search").value})}`), data => {
      const items = Array.isArray(data) ? data : data.items || [];
      if (!items.length) { message($("#models-list"), "当前没有匹配的模型索引。原型参数计算仍可独立使用。"); return; }
      $("#models-list").replaceChildren(...items.map(item => {
        const row = el("article", "model-row");
        row.append(el("h3", "", item.title || item.name || item.filename || item.id || "模型记录"));
        const pairs = Object.entries(item).filter(([key]) => !["title", "name", "filename"].includes(key));
        row.append(detailGrid(pairs)); return row;
      }));
    });
  }
  function debounce(action, delay = 260) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => action(...args), delay); };
  }
  async function syncLibrary() {
    await withBusy(async () => { state.stats = await api("/api/sync", {}); renderStats(); navigate(state.view); toast("本地资料索引已同步。"); });
  }
  function bindEvents() {
    visual = new window.OpticalView($("#visual-workspace"), {
      api, toast, busy: withBusy, adopt: adoptProject, state: () => state,
      edit: scene => { if (state.project) { state.project.scene = scene; markEdited(); } },
    });
    $("#external-reload").onclick = () => { if (confirmDiscard()) loadProject(state.project.id); };
    $("#external-copy").onclick = () => withBusy(async () => {
      const draft = structuredClone(state.project);
      const exported = {schema: "optics-workbench.prototype", schema_version: 1, project: {name: `${draft.name}（本地修改副本）`.slice(0,120), template: draft.template, parameters: draft.parameters, selected_components: draft.selected_components, notes: draft.notes, ...(draft.scene ? {scene: draft.scene} : {})}};
      adoptProject(await api("/api/projects/import", exported)); toast("本地修改已另存为新原型。");
    });
    [["#library-search", "搜索资料"], ["#component-search", "搜索器件"], ["#knowledge-search", "搜索设计知识"], ["#models-search", "搜索模型"]].forEach(([selector, name]) => $(selector).setAttribute("aria-label", name));
    $$(".nav-item").forEach(node => node.addEventListener("click", () => navigate(node.dataset.view)));
    $(".brand").addEventListener("click", event => { event.preventDefault(); navigate("workspace"); });
    window.addEventListener("hashchange", () => navigate(location.hash.slice(1), false));
    $("#new-button").addEventListener("click", showNewDialog);
    $("#empty-new-button").addEventListener("click", showNewDialog);
    $("#save-button").addEventListener("click", saveProject);
    $("#calculate-button").addEventListener("click", calculate);
    $("#clone-button").addEventListener("click", cloneProject);
    $("#export-button").addEventListener("click", exportProject);
    $("#import-button").addEventListener("click", () => $("#import-file").click());
    $("#import-file").addEventListener("change", event => { const file = event.target.files[0]; event.target.value = ""; importFile(file); });
    $("#project-select").addEventListener("change", event => { if (!confirmDiscard()) { event.target.value = state.project?.id || ""; return; } loadProject(event.target.value); });
    $("#project-name").addEventListener("input", event => { if (!state.project) return; state.project.name = event.target.value; markEdited(); });
    $("#project-notes").addEventListener("input", event => { if (!state.project) return; state.project.notes = event.target.value; markEdited(); });
    $("#parameter-form").addEventListener("submit", event => { event.preventDefault(); calculate(); });
    $("#sync-button").addEventListener("click", syncLibrary);
    $("#library-search").addEventListener("input", debounce(() => { state.libraryPage = 1; loadLibrary(); }));
    $("#library-status").addEventListener("change", () => { state.libraryPage = 1; loadLibrary(); });
    $("#component-search").addEventListener("input", debounce(loadComponents));
    $$("#component-filters button").forEach(node => node.addEventListener("click", () => { state.componentKind = node.dataset.kind; loadComponents(); }));
    $("#knowledge-search").addEventListener("input", debounce(loadKnowledge));
    $("#models-search").addEventListener("input", debounce(loadModels));
    $("#dialog-close").addEventListener("click", () => $("#detail-dialog").close());
    $("#detail-dialog").addEventListener("click", event => { if (event.target === $("#detail-dialog")) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
    window.addEventListener("beforeunload", event => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
    document.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key === "s" && state.view === "workspace") { event.preventDefault(); if (!state.busy) saveProject(); } });
  }
  async function initialize() {
    bindEvents(); updateControls();
    try {
      const bootstrap = await api("/api/bootstrap");
      state.token = bootstrap.csrf_token || "";
      state.fields = bootstrap.fields || [];
      state.templates = bootstrap.templates || [];
      state.projects = bootstrap.projects || [];
      state.stats = bootstrap.stats || {};
      state.loaded = true;
      $("#connection-status").textContent = "本地服务已连接";
      updateProjectOptions();
      if (state.projects.length) {
        let preferred;
        try { preferred = localStorage.getItem("optics-workbench:last-project"); } catch { /* Optional preference. */ }
        const id = state.projects.some(project => project.id === preferred) ? preferred : state.projects[0].id;
        await loadProject(id);
      } else { $("#workspace-empty").hidden = false; updateControls(); }
      navigate(location.hash.slice(1) || "workspace", false);
      setInterval(async () => {
        if (!state.project || state.busy || document.hidden) return;
        const id = state.project.id, version = state.project.version;
        try {
          const current = await api(`/api/projects/${encodeURIComponent(id)}`);
          if (state.busy || state.project?.id !== id || state.project.version !== version || current.version === version) return;
          if (state.dirty) {
            $("#external-update-text").textContent = `MCP 或另一窗口已保存 v${current.version}；你的修改仍保留在当前页面。`;
            $("#external-update").hidden = false;
          } else { adoptProject(current); toast(`已同步外部修改 · v${current.version}`); }
        } catch { /* Existing offline banner and explicit requests handle errors. */ }
      }, 2500);
    } catch (error) {
      $("#connection-status").textContent = "本地服务未连接";
      $("#connection-status").classList.add("offline");
      const banner = $("#global-error"); banner.hidden = false;
      banner.textContent = `${error.message} 服务恢复后刷新页面即可。`;
      $("#project-select").replaceChildren(el("option", "", "服务未连接"));
      updateControls();
    }
  }
  initialize();
})();
