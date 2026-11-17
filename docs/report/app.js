(function () {
  "use strict";

  const MODULE_ZH = {
    oecf: "灰阶复制",
    mtf: "细节与清晰度",
    character_line: "字符与线条质量",
    large_area: "大面积图形与均匀性",
    texture: "表面纹理质量",
    banding: "条带质量",
    defect: "缺陷检测",
    repeatability: "测量可靠性"
  };

  const MODULE_ORDER = [
    "oecf",
    "mtf",
    "character_line",
    "large_area",
    "texture",
    "banding"
  ];

  const state = {
    files: [],
    analysis: null,
    reportUrl: null,
    reportHtml: "",
    activeTab: "overview",
    activeSample: 0,
    nextId: 1,
    toastTimer: null
  };

  const $ = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatValue(value) {
    if (typeof value === "number") {
      if (Number.isInteger(value)) return String(value);
      return parseFloat(value.toFixed(4)).toString();
    }
    return value == null ? "--" : String(value);
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function refreshIcons() {
    if (window.lucide && lucide.createIcons) {
      lucide.createIcons();
    }
  }

  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.classList.remove("hidden");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
  }

  function fileIcon(name) {
    const ext = (name.split(".").pop() || "").toLowerCase();
    if (ext === "json") return "FileJson";
    if (ext === "xlsx" || ext === "xls") return "FileSpreadsheet";
    return "FileText";
  }

  function addFiles(fileList) {
    const existing = new Set(state.files.map((item) => item.file.name + ":" + item.file.size));
    const previousCount = state.files.length;
    Array.from(fileList).forEach((file) => {
      const key = file.name + ":" + file.size;
      if (existing.has(key)) return;
      existing.add(key);
      state.files.push({ id: state.nextId++, file, parsed: null });
    });
    if (state.files.length !== previousCount) resetResult();
    renderFileList();
    updateAnalyzeButton();
  }

  function removeFile(id) {
    state.files = state.files.filter((item) => item.id !== id);
    resetResult();
    renderFileList();
    updateAnalyzeButton();
  }

  function clearAll() {
    state.files = [];
    resetResult();
    renderFileList();
    updateAnalyzeButton();
  }

  function resetResult() {
    state.analysis = null;
    state.reportHtml = "";
    if (state.reportUrl) URL.revokeObjectURL(state.reportUrl);
    state.reportUrl = null;
    $("report-frame").removeAttribute("src");
    state.activeSample = 0;
    $("result").classList.add("hidden");
  }

  function renderFileList() {
    const list = $("file-list");
    $("file-count").textContent = state.files.length + " 个";
    if (!state.files.length) {
      list.innerHTML =
        '<div class="empty-state"><i data-lucide="Files"></i><span>等待选择测量文件</span></div>';
      refreshIcons();
      return;
    }
    const parsedByFile = {};
    if (state.analysis) {
      state.analysis.files.forEach((item) => {
        parsedByFile[item.filename] = item;
      });
    }
    list.innerHTML = state.files
      .map((item) => {
        const parsed = parsedByFile[item.file.name] || item.parsed;
        const ok = !parsed || parsed.ok !== false;
        const ext = (item.file.name.split(".").pop() || "").toLowerCase();
        const icon = fileIcon(item.file.name);
        const tags = [];
        if (parsed) {
          if (!parsed.ok) {
            tags.push('<span class="tag error">' + escapeHtml(parsed.error || "解析失败") + "</span>");
          } else {
            (parsed.modules || []).forEach((module) => {
              tags.push('<span class="tag">' + escapeHtml(MODULE_ZH[module] || module) + "</span>");
            });
            if (parsed.sample_id) {
              tags.push('<span class="tag">' + escapeHtml(parsed.sample_id) + "</span>");
            }
          }
        } else {
          tags.push('<span class="tag">' + (ext === "json" ? "JSON" : ext === "xlsx" ? "XLSX" : "TXT/CSV") + "</span>");
        }
        return (
          '<div class="file-row">' +
          '<span class="file-icon ' + (ok ? "ok" : "error") + '"><i data-lucide="' + icon + '"></i></span>' +
          '<div class="file-meta">' +
          '<div class="file-name">' + escapeHtml(item.file.name) + "</div>" +
          '<div class="file-detail">' + formatBytes(item.file.size) + "</div>" +
          '<div class="module-tags">' + tags.join("") + "</div>" +
          "</div>" +
          '<button class="file-remove" type="button" data-remove="' + item.id + '" title="移除文件">' +
          '<i data-lucide="X"></i></button>' +
          "</div>"
        );
      })
      .join("");
    list.querySelectorAll("[data-remove]").forEach((button) => {
      button.addEventListener("click", () => removeFile(Number(button.getAttribute("data-remove"))));
    });
    refreshIcons();
  }

  function updateAnalyzeButton() {
    const button = $("btn-analyze");
    button.disabled = state.files.length === 0 || button.dataset.loading === "1";
  }

  async function analyzeInBrowser(files) {
    const inputs = await Promise.all(files.map(async ({ file }) => ({
      name: file.name,
      bytes: await file.arrayBuffer()
    })));
    const worker = new Worker("./analysis-worker.mjs", { type: "module" });
    try {
      return await new Promise((resolve, reject) => {
        worker.onmessage = ({ data }) => data.error ? reject(new Error(data.error)) : resolve(data);
        worker.onerror = () => reject(new Error("分析组件加载失败，请检查网络连接后重试。"));
        worker.postMessage(inputs, inputs.map(({ bytes }) => bytes));
      });
    } finally {
      worker.terminate();
    }
  }

  async function analyze() {
    const button = $("btn-analyze");
    if (!state.files.length || button.disabled) return;
    const inputs = state.files.slice();
    resetResult();
    button.dataset.loading = "1";
    button.disabled = true;
    button.innerHTML = '<i data-lucide="Loader2"></i><span>分析中</span>';
    refreshIcons();
    try {
      const payload = await analyzeInBrowser(inputs);
      if (inputs.length !== state.files.length ||
          inputs.some((input, index) => input !== state.files[index])) return;
      state.analysis = payload.analysis;
      state.reportHtml = payload.report_html || "";
      state.activeSample = 0;
      $("result").classList.remove("hidden");
      renderFileList();
      renderResult();
      $("result").scrollIntoView({ block: "start" });
      toast("分析完成");
    } catch (error) {
      toast(error.message || "分析失败，请检查文件内容");
    } finally {
      delete button.dataset.loading;
      button.innerHTML = '<i data-lucide="Play"></i><span>统一分析</span>';
      refreshIcons();
      updateAnalyzeButton();
    }
  }

  function renderResult() {
    renderSampleBar();
    renderOverview();
    renderMetrics();
    renderIntegrity();
    renderReport();
    switchTab("report");
  }

  function renderSampleBar() {
    const bar = $("sample-bar");
    if (!state.analysis || state.analysis.samples.length <= 1) {
      bar.classList.add("hidden");
      bar.innerHTML = "";
      return;
    }
    bar.classList.remove("hidden");
    bar.innerHTML = state.analysis.samples
      .map((sample, index) => {
        const score = sample.overall.score == null ? "--" : sample.overall.score;
        return (
          '<button class="sample-chip' + (index === state.activeSample ? " active" : "") + '" type="button" data-sample="' + index + '">' +
          '<span>' + escapeHtml(sample.sample_id) + '</span>' +
          '<span class="chip-score">' + score + "</span>" +
          "</button>"
        );
      })
      .join("");
    bar.querySelectorAll("[data-sample]").forEach((button) => {
      button.addEventListener("click", () => {
        state.activeSample = Number(button.getAttribute("data-sample"));
        renderSampleBar();
        renderOverview();
        renderMetrics();
        renderIntegrity();
      });
    });
  }

  function activeSample() {
    if (!state.analysis || !state.analysis.samples.length) return null;
    const index = Math.min(state.activeSample, state.analysis.samples.length - 1);
    return state.analysis.samples[index];
  }

  function statusHtml(status, text) {
    return '<span class="status ' + escapeHtml(status || "missing") + '">' + escapeHtml(text || status || "已记录") + "</span>";
  }

  function renderOverview() {
    const sample = activeSample();
    if (!sample) return;
    const overall = sample.overall;
    const scoreText = overall.score == null ? "--" : overall.score + " / 100";
    $("overall-card").innerHTML =
      '<div class="score-big">' + escapeHtml(scoreText) + "</div>" +
      '<div class="overall-side">' +
      '<div class="overall-title">综合质量评分</div>' +
      '<div style="margin-top:8px;">' + statusHtml(overall.status, overall.status_zh) + "</div>" +
      '<p class="overall-summary">' + escapeHtml(overall.summary) + "</p>" +
      '<div class="overall-summary" style="color:var(--muted);">' + escapeHtml((overall.basis || []).join("；")) + "</div>" +
      "</div>";

    const integrity = sample.data_integrity;
    const files = state.analysis.files || [];
    const measured = (integrity.modules_measured || []).map((m) => MODULE_ZH[m] || m);
    const missing = (integrity.modules_missing || []).map((m) => MODULE_ZH[m] || m);
    $("batch-card").innerHTML =
      '<div class="overall-side">' +
      '<div class="overall-title">批次信息</div>' +
      '<div class="overall-summary">批次 ' + escapeHtml(state.analysis.batch_id) + "</div>" +
      '<div class="overall-summary">' +
      "文件 " + files.length + " · 样品 " + state.analysis.batch.sample_count + " · 评分模块 " + measured.length + " / 8" +
      "</div>" +
      '<div class="overall-summary">参与评分：' + escapeHtml(measured.join("、") || "无") + "</div>" +
      '<div class="overall-summary" style="color:var(--muted);">未测量：' + escapeHtml(missing.join("、") || "无") + "</div>" +
      '<div class="overall-summary" style="color:var(--muted);">' + escapeHtml(state.analysis.created_at) + "</div>" +
      "</div>";

    $("dimension-grid").innerHTML = MODULE_ORDER.map((module) => {
      const dim = sample.dimensions[module];
      const score = dim.score == null ? "--" : dim.score;
      const qualityClass = {
        excellent: "good",
        good: "good",
        fair: "attention",
        risk: "warning",
        improve: "danger",
        missing: "missing"
      }[dim.quality_status || dim.status] || "missing";
      return (
        '<div class="dim-item">' +
        '<div class="dim-name">' + escapeHtml(MODULE_ZH[module]) + "</div>" +
        '<div class="dim-score' + (dim.score == null ? " missing" : "") + '">' + score + "</div>" +
        '<div style="margin-bottom:4px;">' + statusHtml(qualityClass, dim.quality_status_zh || dim.status_zh) + "</div>" +
        '<div class="dim-desc">' + escapeHtml(dim.overview || dim.summary) + "</div>" +
        "</div>"
      );
    }).join("");

    const findings = sample.findings || {};
    const attention = (findings.attention || []).map((item) => {
      return "<li>" + escapeHtml(item.issue) + "：" + escapeHtml(item.evidence) + "</li>";
    }).join("") || "<li>当前有效数据未触发明显异常判定。</li>";
    const priority = (findings.priority || []).map((item) => {
      return "<li><b>" + escapeHtml(item.priority) + "优先级：</b>" + escapeHtml(item.issue) + "</li>";
    }).join("") || "<li>建立本批质量基线。</li>";
    $("findings").innerHTML =
      '<div class="finding-block"><h4 class="good">表现良好</h4><ul>' +
      (findings.good || []).map((item) => "<li>" + escapeHtml(item) + "</li>").join("") +
      "</ul></div>" +
      '<div class="finding-block"><h4 class="warn">需要关注</h4><ul>' + attention + "</ul></div>" +
      '<div class="finding-block"><h4>最优先建议</h4><ul>' + priority + "</ul></div>";

    const charts = sample.charts || {};
    $("oecf-chart").innerHTML = charts.oecf || '<div class="chart-empty">未测量</div>';
    $("mtf-chart").innerHTML = charts.mtf || '<div class="chart-empty">未测量</div>';
    $("radar-chart").innerHTML = charts.radar || '<div class="chart-empty">评分维度不足，暂不生成雷达图</div>';
    refreshIcons();
  }

  function renderMetrics() {
    const sample = activeSample();
    if (!sample) return;
    const moduleSelect = $("metric-module-filter");
    if (moduleSelect.options.length === 1) {
      MODULE_ORDER.forEach((module) => {
        const option = document.createElement("option");
        option.value = module;
        option.textContent = MODULE_ZH[module];
        moduleSelect.appendChild(option);
      });
    }
    const sampleSelect = $("metric-sample-filter");
    if (sampleSelect.options.length === 1 && state.analysis) {
      state.analysis.samples.forEach((item) => {
        const option = document.createElement("option");
        option.value = item.sample_id;
        option.textContent = item.sample_id;
        sampleSelect.appendChild(option);
      });
    }
    const search = ($("metric-search").value || "").trim().toLowerCase();
    const moduleFilter = moduleSelect.value;
    const sampleFilter = sampleSelect.value;
    const rows = sample.metrics
      .filter((metric) => {
        if (!MODULE_ORDER.includes(metric.module)) return false;
        if (moduleFilter && metric.module !== moduleFilter) return false;
        if (sampleFilter && metric.sample_id !== sampleFilter) return false;
        if (search) {
          const haystack = (metric.zh + " " + metric.key + " " + metric.source_key + " " + formatValue(metric.value)).toLowerCase();
          if (!haystack.includes(search)) return false;
        }
        return true;
      })
      .map((metric) => {
        const valid = metric.valid !== false;
        return (
          "<tr>" +
          "<td>" + escapeHtml(metric.sample_id) + "</td>" +
          "<td>" + escapeHtml(MODULE_ZH[metric.module] || metric.module) + "</td>" +
          "<td>" + escapeHtml(metric.zh || metric.key) + "</td>" +
          "<td>" + escapeHtml(formatValue(metric.value)) + "</td>" +
          "<td>" + escapeHtml(metric.unit || "") + "</td>" +
          "<td>" + statusHtml(valid ? "good" : "danger", valid ? "有效" : "无效") + "</td>" +
          "<td>" + escapeHtml(metric.source_file) + "</td>" +
          "</tr>"
        );
      })
      .join("");
    $("metric-table-body").innerHTML = rows || '<tr><td colspan="7">暂无匹配指标</td></tr>';
  }

  function renderIntegrity() {
    const sample = activeSample();
    if (!sample) return;
    const files = (state.analysis.files || []).map((file) => {
      const ok = file.ok !== false;
      const modules = (file.modules || []).map((m) => MODULE_ZH[m] || m).join("、") || "未识别";
      return (
        '<div class="integrity-item">' +
        '<div>' +
        '<div class="name">' + escapeHtml(file.filename) + "</div>" +
        '<div class="detail">' + escapeHtml(file.format || "") + " · 指标 " + file.metric_count + " · 曲线 " + file.curve_count + " · 样品 " + escapeHtml(file.sample_id) + "</div>" +
        '<div class="detail">' + escapeHtml(modules) + "</div>" +
        "</div>" +
        statusHtml(ok ? "good" : "danger", ok ? "已解析" : "解析失败") +
        "</div>"
      );
    }).join("");
    $("integrity-files").innerHTML = files || '<div class="integrity-note">暂无文件信息</div>';

    const notes = (sample.data_integrity.notes || []).map((note) => {
      return '<div class="integrity-note">' + escapeHtml(note) + "</div>";
    }).join("");
    const invalid = (sample.data_integrity.invalid_metrics || []).slice(0, 10).map((metric) => {
      return "<li>" + escapeHtml(metric.zh || metric.key) + "：" + escapeHtml(formatValue(metric.value)) + "（" + escapeHtml(metric.invalid_reason || "无效") + "）</li>";
    }).join("");
    $("integrity-notes").innerHTML =
      notes +
      (invalid
        ? '<div class="integrity-note"><b>无效数据：</b><ul>' + invalid + "</ul></div>"
        : '<div class="integrity-note">未发现无效标量指标。</div>');
  }

  function renderReport() {
    if (!state.reportHtml) return;
    const blob = new Blob([state.reportHtml], { type: "text/html;charset=utf-8" });
    state.reportUrl = URL.createObjectURL(blob);
    $("report-frame").src = state.reportUrl;
  }

  function switchTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".tab").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-tab") === tab);
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === tab);
    });
  }

  function downloadBlob(content, filename, type) {
    const blob = content instanceof Blob ? content : new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function init() {
    const dropzone = $("dropzone");
    const fileInput = $("file-input");
    dropzone.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      fileInput.click();
    });
    $("btn-pick").addEventListener("click", (event) => {
      event.stopPropagation();
      fileInput.click();
    });
    fileInput.addEventListener("change", () => {
      addFiles(fileInput.files);
      fileInput.value = "";
    });
    ["dragenter", "dragover"].forEach((name) => {
      dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((name) => {
      dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        dropzone.classList.remove("dragover");
      });
    });
    dropzone.addEventListener("drop", (event) => {
      addFiles(event.dataTransfer.files);
    });
    $("btn-analyze").addEventListener("click", analyze);
    $("btn-clear").addEventListener("click", clearAll);
    $("btn-download-json").addEventListener("click", () => {
      if (state.analysis) {
        downloadBlob(JSON.stringify(state.analysis, null, 2), state.analysis.batch_id + "_analysis.json", "application/json");
      }
    });
    $("btn-download-report").addEventListener("click", () => {
      if (state.reportHtml) {
        downloadBlob(state.reportHtml, state.analysis.batch_id + "_report.html", "text/html;charset=utf-8");
      }
    });
    $("btn-download-pdf").addEventListener("click", () => {
      if (!state.reportHtml) return;
      switchTab("report");
      const frame = $("report-frame");
      if (frame.contentDocument?.URL !== state.reportUrl || frame.contentDocument.readyState !== "complete") {
        toast("报告正在加载，请稍后重试。");
        return;
      }
      frame.contentWindow.focus();
      frame.contentWindow.print();
    });
    document.querySelectorAll(".tab").forEach((button) => {
      button.addEventListener("click", () => switchTab(button.getAttribute("data-tab")));
    });
    $("metric-search").addEventListener("input", renderMetrics);
    $("metric-module-filter").addEventListener("change", renderMetrics);
    $("metric-sample-filter").addEventListener("change", renderMetrics);
    refreshIcons();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
