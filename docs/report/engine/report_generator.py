# -*- coding: utf-8 -*-
"""HTML report generation following the ISOPrint Inspector report spec."""

import html
import re

from charts import line_chart_for_sample, radar_chart
from explanation_engine import build_module_explanation
from metrics_catalog import ACTIVE_MODULE_ORDER, MODULE_OVERVIEW_ZH, MODULE_ZH

STATUS_CLASS = {
    "excellent": "good",
    "good": "good",
    "fair": "attention",
    "attention": "attention",
    "risk": "warning",
    "warning": "warning",
    "improve": "danger",
    "danger": "danger",
    "baseline": "baseline",
    "missing": "missing",
}

MODULE_ACTION_NAMES = {
    "oecf": "灰阶复制与 OECF 评估",
    "mtf": "细节与清晰度 / MTF 评估",
    "character_line": "字符与线条质量",
    "large_area": "大面积图形与均匀性",
    "texture": "表面纹理质量",
    "banding": "条带质量",
    "defect": "缺陷检测",
    "repeatability": "测量可靠性",
}

SECTION_LABELS = {
    "result": "测量结果",
    "interpretation": "结果解读",
    "measurement_note": "测量说明",
    "diagnosis": "问题分析",
    "recommendation": "后续建议",
}

CURVE_COLORS = {
    "oecf": "#0d9488",
    "mtf": "#2563eb",
    "banding": "#f59e0b",
}

REPORT_CSS = """
:root { --ink:#17212b; --muted:#64748b; --line:#dbe3ea; --bg:#f4f7f9; --paper:#ffffff; --teal:#0f766e; --blue:#2563eb; --amber:#d97706; --red:#dc2626; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif; line-height:1.65; letter-spacing:0; }
.report-shell { max-width:1080px; margin:0 auto; padding:28px 20px 56px; }
.report-cover { background:var(--paper); border:1px solid var(--line); border-top:6px solid var(--teal); border-radius:8px; padding:30px 34px 26px; }
.brand-row { display:flex; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); padding-bottom:16px; }
.brand-name { font-size:15px; font-weight:700; color:var(--teal); }
.report-id { font-size:12px; color:var(--muted); }
h1 { margin:20px 0 6px; font-size:30px; line-height:1.25; }
.cover-sub { margin:0 0 22px; color:var(--muted); font-size:14px; }
.meta-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px 18px; margin:18px 0 24px; }
.meta-item { font-size:13px; }
.meta-item b { display:block; color:var(--muted); font-weight:600; margin-bottom:2px; }
.score-hero { display:flex; align-items:center; gap:22px; background:#f0f7f6; border:1px solid #cfe5e0; border-radius:8px; padding:18px 22px; }
.score-number { font-size:44px; font-weight:800; color:var(--teal); line-height:1; white-space:nowrap; }
.score-caption { font-size:13px; color:var(--muted); }
.score-side { flex:1; }
.score-status-row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:6px; }
.executive { margin:14px 0 0; font-size:15px; color:#334155; }
.status { display:inline-flex; align-items:center; border-radius:999px; padding:3px 12px; font-size:13px; font-weight:700; white-space:nowrap; }
.status.good { background:#e7f6ee; color:#15803d; }
.status.attention { background:#fef3c7; color:#b45309; }
.status.warning { background:#ffedd5; color:#c2410c; }
.status.danger { background:#fee2e2; color:#b91c1c; }
.status.baseline { background:#e0f2fe; color:#0369a1; }
.status.missing { background:#e5e7eb; color:#4b5563; }
.section { background:var(--paper); border:1px solid var(--line); border-radius:8px; margin-top:16px; padding:26px 30px; }
.section-title { display:flex; align-items:center; gap:10px; margin:0 0 18px; font-size:20px; }
.section-num { display:inline-flex; align-items:center; justify-content:center; min-width:28px; height:28px; border-radius:8px; background:var(--teal); color:#fff; font-size:14px; font-weight:700; padding:0 6px; }
.section-title small { color:var(--muted); font-weight:500; margin-left:auto; font-size:13px; }
.summary-card { border:1px solid var(--line); background:#fbfcfd; border-radius:8px; padding:16px 18px; }
.summary-card.missing { background:#f7f8f9; color:#4b5563; }
.summary-card .label { font-size:12px; color:var(--muted); font-weight:700; margin-bottom:4px; }
.table-wrap { overflow-x:auto; margin-top:14px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { border:1px solid var(--line); padding:9px 11px; text-align:left; vertical-align:top; }
th { background:#f2f5f7; color:#334155; font-weight:700; white-space:nowrap; }
td.num { font-variant-numeric:tabular-nums; }
.chart-wrap { margin-top:16px; }
.chart-wrap svg { width:100%; height:auto; display:block; }
.findings-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; }
.finding-card { border:1px solid var(--line); border-radius:8px; padding:14px 16px; background:#fff; }
.finding-card h4 { margin:0 0 10px; font-size:14px; }
.finding-card ul { margin:0; padding-left:18px; }
.finding-card li { margin:6px 0; font-size:13px; }
.finding-card .good-icon { color:#15803d; }
.finding-card .warn-icon { color:#d97706; }
.module-user { font-size:15px; margin-bottom:8px; }
.explain-block { border:1px solid var(--line); border-radius:8px; background:#fbfcfd; padding:12px 16px; margin:10px 0; }
.explain-label { font-size:13px; font-weight:700; color:var(--teal); margin-bottom:6px; }
.explain-block p { margin:5px 0; font-size:13px; color:#334155; }
.metric-note { font-size:12px; color:var(--muted); margin-top:8px; }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.rank-list { margin:0; padding-left:20px; }
.rank-list li { margin:6px 0; }
.diagnosis { border-top:1px solid var(--line); padding-top:16px; margin-top:16px; }
.diagnosis h4 { margin:0 0 8px; font-size:16px; color:#0f172a; }
.diagnosis .evidence { background:#f8fafc; border:1px solid var(--line); border-radius:8px; padding:10px 14px; font-size:13px; margin:8px 0; }
.rec-grid { display:grid; gap:12px; }
.rec-item { border:1px solid var(--line); border-left:4px solid var(--blue); border-radius:8px; padding:12px 16px; }
.rec-item.priority-high { border-left-color:var(--red); }
.rec-item.priority-medium { border-left-color:var(--amber); }
.rec-item.priority-low { border-left-color:var(--blue); }
.rec-item p { margin:4px 0; font-size:13px; }
.integrity-note { background:#f8fafc; border:1px solid var(--line); border-radius:8px; padding:12px 16px; font-size:13px; margin:8px 0; }
.batch-table td, .batch-table th { text-align:center; }
.print-footer { margin-top:18px; color:var(--muted); font-size:12px; text-align:center; }
@media (max-width:760px) {
  .report-shell { padding:12px 8px 32px; }
  .report-cover, .section { padding:18px 16px; }
  .score-hero { flex-direction:column; align-items:flex-start; }
  h1 { font-size:24px; }
  .findings-grid, .two-col { grid-template-columns:1fr; }
}
@media print {
  body { background:#fff; }
  .report-shell { max-width:none; padding:0; }
  .section, .report-cover { break-inside:avoid; page-break-inside:avoid; }
}
"""


def _h(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def _fmt(value, digits=4):
    if value is None:
        return "未提供"
    try:
        num = float(value)
        if abs(num - round(num)) < 0.0001:
            return str(int(round(num)))
        return ("{:.%df}" % digits).format(num)
    except (TypeError, ValueError):
        return _h(value)


def _metric_value(metrics, *keys):
    for key in keys:
        for metric in reversed(metrics):
            if metric.get("key") == key:
                try:
                    return float(metric["value"])
                except (TypeError, ValueError):
                    continue
    return None


def _metric_text(metrics, key):
    for metric in reversed(metrics):
        if metric.get("key") == key:
            return str(metric["value"])
    return None


def _basis_value(dimension, label):
    for item in dimension.get("basis", []):
        if label in item:
            match = re.search(r"([-+]?\d+\.?\d*)", item)
            if match:
                return match.group(1)
    return None


def _oecf_narrative(metrics, dimension):
    lines = []
    lines.append("OECF 用于描述扫描系统在不同灰阶输入下的光电响应特性，本次使用 RGB 至视觉反射率（Rvis）的前 256 行数据。")
    score = dimension.get("score")
    if score is not None and score >= 85:
        lines.append("当前曲线整体呈连续变化趋势，未观察到明显的离散跳变。")
    elif score is not None and score >= 70:
        lines.append("当前曲线整体连续，但部分灰阶区域的响应变化幅度与整体趋势存在差异。")
    elif score is not None:
        lines.append("当前曲线存在明显波动，局部灰阶区域的响应连续性需要进一步确认。")
    else:
        lines.append("当前结果仅作为已测量区域的 OECF 记录。")
    lines.append("由于尚未建立与该设备、纸张及测试条件对应的历史参考范围，本次结果主要作为扫描链路的 OECF 基线记录，建议结合灰阶目标值、重复测量及 RGB 通道一致性进一步量化评价。")
    lines.append("当前状态：{}。".format(dimension["status_zh"]))
    return lines


def _mtf_narrative(sample, dimension):
    lines = []
    lines.append("MTF 用于表征印刷图像在不同空间频率下的调制传递能力。低空间频率主要反映较大结构和整体边缘对比度的保持情况，中高空间频率则与细线、小尺寸字符及边缘细节的再现能力相关。")
    lines.append("质量指标计算前已执行 OECF 光度响应校正、Scanner MTF 测量及空间响应补偿，并采用统一 ROI 进行分析，以降低扫描采集链路对测量结果的影响。")
    lines.append("因此，报告中的细节与清晰度评价主要反映标准化处理条件下被测样品的细节再现特征，而非扫描系统自身的空间响应表现。")
    score = dimension.get("score")
    if score is None:
        lines.append("当前已完成 MTF 相关数据测量，但由于评分条件不足，本次结果仅作为细节再现能力的测量记录，不进行综合质量等级判定。")
    elif score >= 85:
        lines.append("经标准化处理后，样品在测试空间频率范围内保持较稳定的响应特征，说明当前印刷过程对边缘结构和细节信息具有较好的保持能力。")
    elif score >= 70:
        lines.append("经标准化处理后，样品整体细节再现能力处于可接受水平，但部分空间频率区域存在响应变化，说明细节保持能力仍可能受到印刷分辨率、墨点扩散或材料表面特性的影响。")
    elif score >= 50:
        lines.append("经标准化处理后，样品在中高空间频率区域的细节保持能力相对有限，细小结构和边缘过渡的稳定再现存在一定改善空间。")
    else:
        lines.append("经标准化处理后，样品在细节保持相关指标上的表现相对有限，细小线条、边缘过渡及高频结构的稳定再现能力存在较明显的改善空间。")
    hf = _basis_value(dimension, "高频响应峰值")
    if hf:
        lines.append("经标准化处理后，高频响应峰值记录为 {}，该记录属于标准化处理后的测量结果，不作为扫描系统校准状态的判定依据。".format(hf))
    direction = _basis_value(dimension, "水平/垂直方向差异")
    if direction:
        try:
            value = float(direction)
            if value < 5:
                lines.append("水平与垂直方向之间的细节再现差异较小，当前结果未显示明显的方向性响应不一致。")
            elif value < 15:
                lines.append("水平与垂直方向之间存在一定的细节再现差异，建议结合重复测量进一步确认该差异是否具有稳定的方向性特征。")
            else:
                lines.append("水平与垂直方向之间存在较明显的细节再现差异，建议进一步检查走纸方向、成像方向、墨点扩散及材料传输稳定性等因素。")
        except ValueError:
            lines.append("检测到水平与垂直方向存在差异，建议结合重复测量进一步确认其稳定性。")
    if score is not None and score < 70:
        lines.append("后续优化应优先关注印刷过程本身的细节复制能力，包括有效成像分辨率、墨点扩散控制、材料吸收特性及工艺参数匹配，并通过相同测试条件下的重复测量验证优化效果。")
    lines.append("当前状态：{}。".format(dimension["status_zh"]))
    return lines


def _character_narrative(metrics, dimension):
    lines = []
    line_width = _metric_value(metrics, "line_width")
    target_width = _metric_value(metrics, "line_width_target")
    if line_width is not None:
        if target_width is not None and target_width > 0:
            delta = line_width - target_width
            ratio = delta / target_width * 100.0
            lines.append(
                "当前测得线宽为 {:.4f} mm，相对标称线宽 {:.4f} mm 的偏差为 {:.4f} mm（{:.2f}%），该结果反映当前测试区域的线条尺寸复制情况。".format(
                    line_width, target_width, delta, ratio
                )
            )
        else:
            lines.append(
                "当前测得线宽为 {:.4f} mm。由于尚未提供设计标称值或验收范围，本次结果仅作为尺寸复制能力的测量记录，暂不进行合格性判定。".format(line_width)
            )
    upper_transition = _metric_value(metrics, "edge_transition_width_upper")
    lower_transition = _metric_value(metrics, "edge_transition_width_lower")
    if upper_transition is not None and lower_transition is not None:
        compare = "下边缘" if lower_transition > upper_transition else "上边缘"
        lines.append(
            "上、下边缘过渡宽度分别为 {:.4f} µm 和 {:.4f} µm，{}的过渡区域相对更宽，表明当前边缘响应存在一定不对称性，可能与印刷扩散、扫描方向响应或图像处理参数有关。".format(
                upper_transition, lower_transition, compare
            )
        )
    upper_blur = _metric_value(metrics, "edge_blur_upper")
    lower_blur = _metric_value(metrics, "edge_blur_lower")
    if upper_blur is not None and lower_blur is not None:
        lines.append(
            "上、下边缘模糊度分别为 {:.4f} 和 {:.4f}，下边缘模糊度相对较高，与边缘过渡宽度的变化趋势基本一致。".format(upper_blur, lower_blur)
        )
    void_ratio = _metric_value(metrics, "character_void_ratio")
    if void_ratio is not None and void_ratio <= 0.02:
        lines.append("当前检测区域内未发现明显空洞，该结论仅适用于当前 ROI 和当前阈值条件。")
    mark_ratio = _metric_value(metrics, "character_mark_ratio")
    if mark_ratio is not None and mark_ratio > 0:
        lines.append(
            "外来标记相关指标为 {:.4f}，该响应可能来自真实印刷污染、纸张表面结构、扫描噪声或图像处理伪影，建议结合缺陷位置图与原始图像确认。".format(mark_ratio)
        )
    fog_csa = _metric_text(metrics, "character_fog_csa")
    fog_r75 = _metric_text(metrics, "character_fog_r75")
    if fog_csa is not None and fog_r75 is not None:
        lines.append(
            "雾影相关指标分别输出为 C.S.A = {} 和 R75 = {}，两项指标采用不同的计算区域和阈值定义，不建议直接比较或相加，需结合缺陷分布图确认字符周围的灰度残留与边缘扩散。".format(
                fog_csa, fog_r75
            )
        )
    lines.append("当前状态：{}。".format(dimension["status_zh"]))
    return lines


def _large_area_narrative(metrics, dimension):
    lines = []
    rmax = _metric_value(metrics, "rmax")
    rmin = _metric_value(metrics, "rmin")
    if rmax is not None and rmin is not None:
        lines.append(
            "大面积均匀性用于评价较大区域内亮度或反射率的一致性，当前 Rmax = {:.4f}，Rmin = {:.4f}，两者之间的差异反映了当前测量区域内的反射率分布范围。".format(
                rmax, rmin
            )
        )
    darkness = _metric_value(metrics, "large_area_darkness", "large_area_density")
    if darkness is not None:
        lines.append("大面积暗度记录为 {:.4f}，该值可作为当前介质与墨层状态的测量记录。".format(darkness))
    void_ratio = _metric_value(metrics, "large_area_void_ratio")
    mark_ratio = _metric_value(metrics, "background_mark_ratio")
    if void_ratio is not None:
        lines.append("大面积空洞占比为 {:.4f}。".format(void_ratio))
    if mark_ratio is not None:
        lines.append("背景外来标记占比为 {:.4f}，建议结合原始图像确认是否来自真实污染或测量伪影。".format(mark_ratio))
    lines.append("由于尚未建立历史参考范围，本次结果主要作为质量基线记录，建议增加多 ROI、重复测量并与后续批次数据对比。")
    lines.append("当前状态：{}。".format(dimension["status_zh"]))
    return lines


def _texture_narrative(metrics, dimension):
    lines = []
    grain = _metric_value(metrics, "graininess")
    mottle = _metric_value(metrics, "mottle")
    if grain is not None:
        lines.append(
            "Graininess 用于表征测试区域内的高频亮度波动水平，可反映印刷微观结构、材料表面特性及测量系统噪声的综合影响，当前值为 {:.4f}。".format(grain)
        )
    if mottle is not None:
        lines.append(
            "Mottle 用于表征较大空间尺度上的亮度或密度不均匀现象，与局部供墨、材料均匀性及印刷稳定性有关，当前值为 {:.4f}。".format(mottle)
        )
    lines.append("由于当前尚未建立同类样品的历史参考范围，本次结果主要作为质量基线记录，建议通过重复扫描和多区域测量建立正常波动范围，用于识别后续异常变化。")
    lines.append("当前状态：{}。".format(dimension["status_zh"]))
    return lines


def _banding_narrative(metrics, dimension):
    lines = []
    vertical = _metric_value(metrics, "vertical_banding")
    horizontal = _metric_value(metrics, "horizontal_banding")
    amplitude = _metric_value(metrics, "banding_amplitude")
    if vertical is not None or horizontal is not None:
        lines.append(
            "条带指标用于评价周期性空间不均匀。当前垂直条带评分为 {}，水平条带评分为 {}。".format(
                "--" if vertical is None else "{:.3f}".format(vertical),
                "--" if horizontal is None else "{:.3f}".format(horizontal),
            )
        )
    if amplitude is not None:
        lines.append("条带峰值幅度记录为 {:.3f}。".format(amplitude))
    lines.append("垂直与水平方向的差异可能与扫描方向、走纸方向或供墨过程有关，建议结合频谱分析、原始图像及方向性复测进一步确认。")
    lines.append("当前状态：{}。".format(dimension["status_zh"]))
    return lines


def _render_explanation(explanation):
    html_parts = []
    for key, label in SECTION_LABELS.items():
        lines = explanation.get(key, [])
        if not lines:
            continue
        content = "".join("<p>{}</p>".format(_h(line)) for line in lines)
        html_parts.append('<div class="explain-block"><div class="explain-label">{label}</div>{content}</div>'.format(label=_h(label), content=content))
    return "".join(html_parts)


def _status_span(status, text=None):
    cls = STATUS_CLASS.get(status, "missing")
    return '<span class="status {cls}">{text}</span>'.format(cls=cls, text=_h(text or status))


def _reference_span(reference_status, text=None):
    cls = {
        "established": "good",
        "baseline_recommended": "baseline",
        "baseline_missing": "missing",
    }.get(reference_status, "missing")
    return '<span class="status {cls}">{text}</span>'.format(cls=cls, text=_h(text or reference_status))


def _meta_value(sample, key):
    value = sample["metadata"].get(key)
    return _h(value) if value else "未提供"


def _charts_for_module(sample, module):
    return line_chart_for_sample(sample, module)


def _metric_status(metric, dimension):
    if not metric.get("valid", True):
        return "无效", "missing"
    if dimension and dimension.get("score") is None:
        return "已记录，未参与评分", "missing"
    return "已记录", "good"


def _metrics_table(metrics, dimension):
    if not metrics:
        return ""
    rows = []
    for metric in metrics:
        text, status = _metric_status(metric, dimension)
        unit = " " + _h(metric.get("unit")) if metric.get("unit") else ""
        rows.append(
            "<tr><td>{zh}</td><td class=\"num\">{value}{unit}</td><td>{status}</td><td>{note}</td></tr>".format(
                zh=_h(metric.get("zh") or metric.get("key")),
                value=_fmt(metric.get("value")),
                unit=unit,
                status=_status_span(status, text),
                note=_h(metric.get("notes") or metric.get("source_key") or "来自上传测量数据"),
            )
        )
    return '<div class="table-wrap"><table><thead><tr><th>指标</th><th>测试结果</th><th>状态</th><th>说明</th></tr></thead><tbody>{}</tbody></table></div>'.format(
        "".join(rows)
    )


def _module_section(sample, module, section_index):
    dimension = sample["dimensions"][module]
    measured = dimension["score"] is not None
    title = MODULE_ACTION_NAMES[module]
    if not measured:
        return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>{title}<small>未参与综合评分</small></h2>
  <div class="summary-card missing">
    <div class="label">当前状态</div>
    当前未提供有效的{title}数据，本次报告不对此模块作出质量结论，该模块不参与综合评分。
  </div>
</section>
""".format(num=section_index, title=_h(title))
    chart = _charts_for_module(sample, module)
    chart_html = ""
    if chart:
        chart_html = '<div class="chart-wrap">{chart}</div>'.format(chart=chart)
    explanation = build_module_explanation(sample, module, dimension)
    user_note = dimension.get("module_summary") or explanation.get("summary") or dimension.get("summary", "当前模块测量结果已记录。")
    basis = "；".join(dimension.get("basis", []))
    basis_html = '<div class="integrity-note">评分依据：{}</div>'.format(_h(basis)) if basis else ""
    narrative = _render_explanation(explanation)
    mtf_note = ""
    if module == "mtf":
        mtf_note = '<div class="integrity-note">MTF 图按 MTFGenerator 规则绘制：G/Y 通道水平/垂直方向的系统 MTF 与 Target MTF 对比；Scanner MTF 超过 1 属于测量链路补偿后的中间量，不作为样品质量扣分项。</div>'
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>{title}<small>{status}</small></h2>
  <div class="module-user">{user_note}</div>
  {narrative}
  {chart}
  {basis_html}
  {mtf_note}
  {table}
  <div class="metric-note">表中状态为系统内部记录状态，不替代正式门限判定；指标可追溯至上传文件 {source}。</div>
</section>
""".format(
        num=section_index,
        title=_h(title),
        status=_status_span(dimension["status"], dimension["status_zh"]),
        user_note=_h(user_note),
        narrative=narrative,
        chart=chart_html,
        basis_html=basis_html,
        mtf_note=mtf_note,
        table=_metrics_table([item for item in sample["metrics"] if item.get("module") == module], dimension),
        source="、".join(_h(name) for name in sample["data_integrity"]["source_files"]) or "未提供",
    )


def _overview_section(sample, section_index):
    rows = []
    for module in ACTIVE_MODULE_ORDER:
        dim = sample["dimensions"][module]
        if dim["score"] is None:
            continue
        score_text = "--" if dim["score"] is None else "{}/100".format(dim["score"])
        rows.append(
            "<tr><td>{name}</td><td class=\"num\">{score}</td><td>{status}</td><td>{overview}</td></tr>".format(
                name=_h(MODULE_OVERVIEW_ZH[module]),
                score=score_text,
                status=_status_span(dim["quality_status"], dim["quality_status_zh"]),
                overview=_h(dim.get("overview") or dim.get("summary", "")),
            )
        )
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>质量概览<small>核心质量指标综合评价</small></h2>
  <div class="table-wrap"><table><thead><tr><th>质量维度</th><th>评分</th><th>评价状态</th><th>质量表现</th></tr></thead><tbody>{rows}</tbody></table></div>
</section>
""".format(num=section_index, rows="".join(rows))


def _findings_section(sample, section_index):
    findings = sample["findings"]
    good_items = "".join("<li>{}</li>".format(_h(item)) for item in findings["good"])
    attention_items = "".join(
        "<li>{issue}：{evidence}</li>".format(issue=_h(item["issue"]), evidence=_h(item["evidence"]))
        for item in findings["attention"]
    )
    if not attention_items:
        attention_items = "<li>当前有效数据未触发明显异常判定。</li>"
    priority_items = "".join(
        "<li><b>{level}优先级：</b>{issue}</li>".format(level=_h(item["priority"]), issue=_h(item["issue"]))
        for item in findings["priority"]
    )
    if not priority_items:
        priority_items = "<li><b>低优先级：</b>建立本批质量基线。</li>"
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>主要发现</h2>
  <div class="findings-grid">
    <div class="finding-card"><h4 class="good-icon">表现良好的项目</h4><ul>{good}</ul></div>
    <div class="finding-card"><h4 class="warn-icon">需要关注的项目</h4><ul>{attention}</ul></div>
    <div class="finding-card"><h4>最优先建议</h4><ul>{priority}</ul></div>
  </div>
</section>
""".format(num=section_index, good=good_items, attention=attention_items, priority=priority_items)


def _radar_section(sample, section_index):
    radar_items = [
        {"label": MODULE_OVERVIEW_ZH[module], "score": sample["dimensions"][module]["score"]}
        for module in ACTIVE_MODULE_ORDER
        if sample["dimensions"][module]["score"] is not None
    ]
    radar = radar_chart(radar_items)
    if radar is None:
        radar = '<div class="summary-card missing">当前有效评分维度不足 3 项，暂不生成综合质量雷达图。</div>'
    else:
        radar = '<div class="chart-wrap">{}</div>'.format(radar)
    scored = sorted(
        (sample["dimensions"][module] for module in ACTIVE_MODULE_ORDER if sample["dimensions"][module]["score"] is not None),
        key=lambda item: item["score"],
        reverse=True,
    )
    best = "".join("<li>{}. {}（{} 分）</li>".format(index + 1, _h(item["zh"]), item["score"]) for index, item in enumerate(scored[:3]))
    worst = "".join("<li>{}. {}（{} 分）</li>".format(index + 1, _h(item["zh"]), item["score"]) for index, item in enumerate(reversed(scored[-3:]), 1))
    if not worst:
        worst = "<li>暂无足够评分数据。</li>"
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>综合质量分析</h2>
  {radar}
  <div class="two-col" style="margin-top:18px;">
    <div>
      <h4>表现最好</h4>
      <ol class="rank-list">{best}</ol>
    </div>
    <div>
      <h4>最需要改进</h4>
      <ol class="rank-list">{worst}</ol>
    </div>
  </div>
</section>
""".format(num=section_index, radar=radar, best=best, worst=worst)


def _diagnosis_section(sample, section_index):
    if not sample["diagnosis"]:
        return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>问题诊断</h2>
  <div class="summary-card">
    <div class="label">诊断结论</div>
    当前有效数据未触发明显异常判定；建议在相同条件下完成重复性测试，并保存本次结果作为质量基线。
  </div>
</section>
""".format(num=section_index)
    blocks = []
    for index, item in enumerate(sample["diagnosis"], 1):
        causes = "".join("<li>{}</li>".format(_h(cause)) for cause in item["possible_causes"])
        verifications = "".join("<li>{}</li>".format(_h(step)) for step in item["verification"])
        blocks.append(
            """
<div class="diagnosis">
  <h4>问题 {index}：{issue}</h4>
  <div class="evidence"><b>检测证据：</b>{evidence}</div>
  <p><b>可能原因：</b></p><ol>{causes}</ol>
  <p><b>建议验证：</b></p><ol>{verifications}</ol>
</div>
""".format(
                index=index,
                issue=_h(item["issue"]),
                evidence=_h(item["evidence"]),
                causes=causes,
                verifications=verifications,
            )
        )
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>问题诊断</h2>
  {blocks}
</section>
""".format(num=section_index, blocks="".join(blocks))


def _recommendations_section(sample, section_index):
    items = []
    for rec in sample["recommendations"]:
        items.append(
            """
<div class="rec-item priority-{priority}">
  <p><b>{level}优先级：{action}</b></p>
  <p>目的：{purpose}</p>
  <p>验证方法：{verification}</p>
</div>
""".format(
                priority=_h(rec["priority"]),
                level=_h(rec["priority_zh"]),
                action=_h(rec["action"]),
                purpose=_h(rec["purpose"]),
                verification=_h(rec["verification"]),
            )
        )
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>改进建议</h2>
  <div class="rec-grid">{items}</div>
</section>
""".format(num=section_index, items="".join(items))


def _integrity_section(sample, section_index):
    integrity = sample["data_integrity"]
    notes = "".join('<div class="integrity-note">{}</div>'.format(_h(note)) for note in integrity["notes"])
    source_rows = "".join(
        "<tr><td>{file}</td><td>{sample}</td><td>{modules}</td></tr>".format(
            file=_h(file),
            sample=_h(sample["sample_id"]),
            modules=_h("、".join(MODULE_ZH[module] for module in sample["data_integrity"]["modules_measured"]) or "未测量"),
        )
        for file in integrity["source_files"]
    )
    invalid = sample["data_integrity"]["invalid_metrics"]
    invalid_html = ""
    if invalid:
        invalid_rows = "".join(
            "<tr><td>{key}</td><td>{value}</td><td>{reason}</td><td>{file}</td></tr>".format(
                key=_h(item.get("key")),
                value=_h(item.get("value")),
                reason=_h(item.get("invalid_reason", "无效")),
                file=_h(item.get("source_file")),
            )
            for item in invalid[:20]
        )
        invalid_html = '<div class="table-wrap"><table><thead><tr><th>指标</th><th>原始值</th><th>原因</th><th>来源文件</th></tr></thead><tbody>{}</tbody></table></div>'.format(invalid_rows)
    measured_names = "、".join(MODULE_ZH[module] for module in integrity["modules_measured"]) or "无"
    missing_names = "、".join(MODULE_ZH[module] for module in integrity["modules_missing"]) or "无"
    return """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>数据完整性说明</h2>
  {notes}
  <div class="table-wrap"><table>
    <thead><tr><th>项目</th><th>说明</th></tr></thead>
    <tbody>
      <tr><td>参与评分模块</td><td>{measured}</td></tr>
      <tr><td>未测量模块</td><td>{missing}</td></tr>
      <tr><td>样品编号</td><td>{sample_id}</td></tr>
    </tbody>
  </table></div>
  {invalid_html}
  <h4 style="margin-top:18px;">来源文件追溯</h4>
  <div class="table-wrap"><table><thead><tr><th>文件</th><th>样品</th><th>识别模块</th></tr></thead><tbody>{source_rows}</tbody></table></div>
</section>
""".format(
        num=section_index,
        notes=notes,
        measured=_h(measured_names),
        missing=_h(missing_names),
        sample_id=_h(sample["sample_id"]),
        invalid_html=invalid_html,
        source_rows=source_rows,
    )


def _sample_report(sample, index, total):
    overall = sample["overall"]
    meta = sample["metadata"]
    sections = []
    section_index = 2
    sections.append(
        """
<div class="report-cover">
  <div class="brand-row">
    <div class="brand-name">ISOPrint Inspector</div>
    <div class="report-id">样品报告 {index} / {total}</div>
  </div>
  <h1>打印输出印刷质量评估报告</h1>
  <p class="cover-sub">本报告基于上传测量数据自动解析、有效性检查、评分与诊断生成。</p>
  <h2 class="section-title" style="margin-top:6px;"><span class="section-num">01</span>执行摘要</h2>
  <div class="meta-grid">
    <div class="meta-item"><b>样品编号</b>{sample_id}</div>
    <div class="meta-item"><b>测试日期</b>{test_date}</div>
    <div class="meta-item"><b>测试设备</b>{device}</div>
    <div class="meta-item"><b>测试条件</b>{conditions}</div>
    <div class="meta-item"><b>批次编号</b>{batch_id}</div>
    <div class="meta-item"><b>分析时间</b>{created_at}</div>
  </div>
  <div class="score-hero">
    <div>
      <div class="score-number">{score_text}</div>
      <div class="score-caption">综合质量评分</div>
    </div>
    <div class="score-side">
      <div class="score-status-row">总体状态：{status}</div>
      <div>{basis}</div>
    </div>
  </div>
  <p class="executive">{summary}</p>
  <div style="margin-top:20px;">
    <h3 style="font-size:16px;margin-bottom:10px;">测量处理状态</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>项目</th><th>状态</th><th>说明</th></tr></thead>
        <tbody>
          <tr><td>OECF 光度校正</td><td>已执行</td><td>对扫描采集链路的光度响应进行标准化处理</td></tr>
          <tr><td>Scanner MTF 测量</td><td>已执行</td><td>测量扫描采集系统的空间频率响应特性</td></tr>
          <tr><td>MTF 空间响应补偿</td><td>已执行</td><td>基于 Scanner MTF 对扫描链路的空间响应影响进行补偿或校正</td></tr>
          <tr><td>ROI 标准化</td><td>已执行</td><td>采用统一测量区域，提高不同指标及重复测量之间的可比性</td></tr>
          <tr><td>质量指标分析</td><td>已完成</td><td>基于标准化处理后的测量数据评价被测印刷样品的质量特征</td></tr>
        </tbody>
      </table>
    </div>
    <p class="metric-note">本报告中的质量指标基于 ISOPrint Inspector 标准化处理后的测量结果进行分析。OECF 与 MTF 校正用于降低扫描采集系统对测量结果的影响，其本身不作为被测印刷样品的质量扣分项。</p>
  </div>
</div>
""".format(
            index=index,
            total=total,
            sample_id=_h(meta.get("sample_id") or "未提供"),
            test_date=_meta_value(sample, "test_date"),
            device=_meta_value(sample, "device"),
            conditions=_meta_value(sample, "conditions"),
            batch_id=_h(sample["data_integrity"]["batch_id"]),
            created_at=_h(sample["data_integrity"].get("created_at") or sample["data_integrity"]["batch_id"]),
            score_text="--" if overall["score"] is None else "{} / 100".format(overall["score"]),
            status=_status_span(overall["status"], overall["status_zh"]),
            basis=_h("；".join(overall["basis"]) or "综合评分条件不足"),
            summary=_h(overall["summary"]),
        )
    )
    sections.append(_overview_section(sample, section_index))
    section_index += 1
    sections.append(_findings_section(sample, section_index))
    section_index += 1
    for module in ACTIVE_MODULE_ORDER:
        if sample["dimensions"][module]["score"] is None:
            continue
        sections.append(_module_section(sample, module, section_index))
        section_index += 1
    sections.append(_radar_section(sample, section_index))
    section_index += 1
    sections.append(_diagnosis_section(sample, section_index))
    section_index += 1
    sections.append(_recommendations_section(sample, section_index))
    section_index += 1
    sections.append(
        """
<section class="section">
  <h2 class="section-title"><span class="section-num">{num}</span>最终结论</h2>
  <p>{conclusion}</p>
</section>
""".format(num=section_index, conclusion=_h(sample["final_conclusion"]))
    )
    return "\n".join(sections)


def _batch_overview(analysis):
    batch = analysis["batch"]
    if batch["sample_count"] <= 1:
        return ""
    rows = []
    for sample in analysis["samples"]:
        rows.append(
            "<tr><td>{sample}</td><td>{score}</td><td>{status}</td></tr>".format(
                sample=_h(sample["sample_id"]),
                score="--" if sample["overall"]["score"] is None else "{} / 100".format(sample["overall"]["score"]),
                status=_status_span(sample["overall"]["status"], sample["overall"]["status_zh"]),
            )
        )
    module_header = "<th>质量维度</th>" + "".join("<th>{}</th>".format(_h(sample["sample_id"])) for sample in analysis["samples"])
    matrix_rows = []
    visible_modules = [
        module
        for module in ACTIVE_MODULE_ORDER
        if any(sample["dimensions"][module]["score"] is not None for sample in analysis["samples"])
    ]
    for module in visible_modules:
        cells = ""
        for sample in analysis["samples"]:
            dim = sample["dimensions"][module]
            cells += "<td>{score}<br/>{status}</td>".format(
                score="--" if dim["score"] is None else dim["score"],
                status=_status_span(dim["status"], dim["status_zh"]),
            )
        matrix_rows.append("<tr><td>{}</td>{}</tr>".format(_h(MODULE_OVERVIEW_ZH[module]), cells))
    notes = "".join('<div class="integrity-note">{}</div>'.format(_h(note)) for note in batch["notes"])
    return """
<div class="report-cover" style="margin-top:16px;">
  <div class="brand-row"><div class="brand-name">批量分析概览</div><div class="report-id">{count} 个样品</div></div>
  {notes}
  <div class="table-wrap"><table class="batch-table"><thead><tr><th>样品编号</th><th>综合评分</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table></div>
  <div class="table-wrap"><table class="batch-table"><thead><tr>{module_header}</tr></thead><tbody>{matrix_rows}</tbody></table></div>
</div>
""".format(
        count=batch["sample_count"],
        notes=notes,
        rows="".join(rows),
        module_header=module_header,
        matrix_rows="".join(matrix_rows),
    )


def generate_report(analysis):
    sample_reports = []
    for index, sample in enumerate(analysis["samples"], 1):
        sample["data_integrity"]["created_at"] = analysis["created_at"]
        sample_reports.append(_sample_report(sample, index, len(analysis["samples"])))
    page_title = "ISOPrint Inspector 打印输出印刷质量评估报告"
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="report-shell">
{batch}
{sample_reports}
<div class="print-footer">本报告由 ISOPrint Inspector 自动生成 · {batch_id} · 状态与评分为系统内部评估，不替代正式门限判定</div>
</div>
</body>
</html>""".format(
        title=_h(page_title),
        css=REPORT_CSS,
        batch=_batch_overview(analysis),
        sample_reports="\n".join(sample_reports),
        batch_id=_h(analysis["batch_id"]),
    )
