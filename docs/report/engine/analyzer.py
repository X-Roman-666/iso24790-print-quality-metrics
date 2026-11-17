# -*- coding: utf-8 -*-
"""Quality analysis, dimension scoring and diagnosis for ISOPrint Inspector."""

import math
import re
from datetime import datetime

from charts import build_mtf_system_curves, build_sample_charts
from metrics_catalog import ACTIVE_MODULE_ORDER, MODULE_OVERVIEW_ZH, MODULE_ZH

MISSING_SAMPLE = "未提供"
VALID_STATUSES = {"good", "attention", "warning", "danger", "baseline", "missing"}


def _num(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "").replace("％", "")
        if not text:
            return None
        try:
            num = float(text)
        except ValueError:
            return None
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    return None


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _score_int(value):
    return int(round(_clamp(value)))


def _status_for_score(score):
    if score is None:
        return "missing", "未测量"
    if score >= 90:
        return "good", "优秀"
    if score >= 80:
        return "good", "良好"
    if score >= 70:
        return "attention", "需要关注"
    if score >= 60:
        return "warning", "存在明显风险"
    return "danger", "需要重点改进"


def _status_zh(status):
    return {
        "good": "良好",
        "attention": "需要关注",
        "warning": "存在明显风险",
        "danger": "需要重点改进",
        "baseline": "建立基线",
        "missing": "未测量",
    }.get(status, "已记录")


def _piecewise(value, good, attention, risk, danger):
    if value is None:
        return None
    if value <= good:
        return 95
    if value <= attention:
        return 85
    if value <= risk:
        return 70
    if value <= danger:
        return 55
    return 40


def _normalize_sample_id(value):
    text = str(value or "").strip()
    if not text or text.lower() in ("n/a", "na", "none", "null", "-", "--"):
        return MISSING_SAMPLE
    return text


def _first_number(values_map, *keys):
    for key in keys:
        if key in values_map:
            value = _num(values_map[key][-1])
            if value is not None:
                return value
    return None


def _module_values(metrics, module):
    out = {}
    for metric in metrics:
        if metric.get("module") != module:
            continue
        if not metric.get("valid", True):
            continue
        out.setdefault(metric["key"], []).append(metric["value"])
    return out


def _curves_for_module(curves, module):
    return [curve for curve in curves if curve.get("module") == module]


def _derive_mtf_points(curve):
    points = []
    for pair in curve.get("points", []):
        x = _num(pair[0])
        y = _num(pair[1])
        if x is not None and y is not None:
            points.append((x, y))
    points.sort(key=lambda item: item[0])
    return points


def _derive_mtf_values(curve):
    points = _derive_mtf_points(curve)
    if len(points) < 2:
        return {}
    result = {}
    for key, target in (("mtf10", 0.1), ("mtf20", 0.2), ("mtf50", 0.5)):
        value = None
        for index in range(len(points) - 1):
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            if y1 >= target >= y2 or y2 >= target >= y1:
                if y1 == y2:
                    value = x2
                else:
                    value = x1 + (target - y1) * (x2 - x1) / (y2 - y1)
                break
        if value is None and points[0][1] <= target:
            value = points[0][0]
        elif value is None and points[-1][1] >= target:
            value = points[-1][0]
        if value is not None:
            result[key] = value
    return result


def _analyze_oecf_curve(curves):
    if not curves:
        return None
    points = _derive_mtf_points(curves[0])
    if len(points) < 2:
        return None
    ys = [y for _, y in points]
    diffs = [abs(ys[i + 1] - ys[i]) for i in range(len(ys) - 1)]
    good_adjacent = sum(1 for i in range(len(ys) - 1) if ys[i + 1] >= ys[i])
    monotonic = good_adjacent / max(1, len(ys) - 1) * 100.0
    median = sorted(diffs)[len(diffs) // 2] if diffs else 0
    max_step = max(diffs) if diffs else 0
    continuity = 100.0
    if median > 0:
        continuity = _clamp(100.0 - max(0.0, (max_step / median - 1.0) * 15.0))
    return {
        "monotonic": monotonic,
        "continuity": continuity,
        "y_range": max(ys) - min(ys),
        "max_step": max_step,
        "median_step": median,
    }


def _score_oecf(values_map, curves):
    basis = []
    score = 100.0
    curve_stat = _analyze_oecf_curve(curves)
    if curve_stat:
        if curves[0].get("note"):
            basis.append(str(curves[0]["note"]))
        monotonic = _num(curve_stat["monotonic"])
        continuity = _num(curve_stat["continuity"])
        y_range = _num(curve_stat["y_range"])
        if monotonic is not None:
            basis.append("OECF 曲线单调性 {:.1f}%".format(monotonic))
            if monotonic < 95:
                score -= min(25.0, (95.0 - monotonic) * 0.5)
        if continuity is not None:
            basis.append("OECF 曲线连续性 {:.1f}%".format(continuity))
            if continuity < 90:
                score -= min(20.0, (90.0 - continuity) * 0.4)
        if y_range is not None and y_range > 0:
            basis.append("OECF 曲线范围 {:.3f}".format(y_range))
    mono = _first_number(values_map, "oecf_monotonicity")
    cont = _first_number(values_map, "oecf_continuity")
    od_min = _first_number(values_map, "od_min")
    od_max = _first_number(values_map, "od_max")
    od_range = _first_number(values_map, "od_range")
    gamma = _first_number(values_map, "gamma")
    if mono is not None:
        if mono <= 1:
            mono = mono * 100.0
        basis.append("灰阶单调性 {:.1f}%".format(mono))
        if mono < 95:
            score -= min(25.0, (95.0 - mono) * 0.5)
    if cont is not None:
        if cont <= 1:
            cont = cont * 100.0
        basis.append("灰阶连续性 {:.1f}%".format(cont))
        if cont < 90:
            score -= min(20.0, (90.0 - cont) * 0.4)
    if od_min is not None and od_max is not None:
        actual_range = od_max - od_min
        basis.append("黑场至白场范围 {:.3f}".format(actual_range))
        if actual_range < 1.0:
            score -= min(20.0, (1.0 - actual_range) * 15.0)
    elif od_range is not None:
        basis.append("光学密度范围 {:.3f}".format(od_range))
        if od_range < 1.0:
            score -= min(20.0, (1.0 - od_range) * 15.0)
    if od_max is not None:
        basis.append("最大光学密度 {:.3f}".format(od_max))
        if od_max < 1.2:
            score -= min(15.0, (1.2 - od_max) * 15.0)
    if gamma is not None:
        basis.append("灰阶伽马 {:.2f}".format(gamma))
        if gamma < 0.8 or gamma > 1.4:
            score -= min(15.0, abs(gamma - 1.0) * 25.0)
    if not basis:
        return None
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _oecf_summary(score, basis),
    }


def _oecf_summary(score, basis):
    if score >= 85:
        return "当前 OECF 曲线整体连续，未观察到明显离散跳变，可作为当前条件下的扫描链路光电响应记录。"
    if score >= 70:
        return "当前 OECF 曲线整体连续，但部分灰阶区域的响应变化幅度需要结合参考值进一步确认。"
    return "当前 OECF 曲线存在明显波动，建议核查 OECF 标定、扫描曝光条件及灰阶测试卡状态。"


def _score_mtf(values_map, curves):
    visible_curves = [curve for curve in curves if _visible_mtf_curve(curve)] or curves
    system_curves = build_mtf_system_curves(curves) or visible_curves
    mtf10 = _first_number(values_map, "mtf10", "scanner_mtf10", "target_mtf10")
    mtf20 = _first_number(values_map, "mtf20", "scanner_mtf20", "target_mtf20")
    mtf50 = _first_number(values_map, "mtf50", "scanner_mtf50", "target_mtf50")
    derived_mtf10 = _average_derived(system_curves, "mtf10")
    derived_mtf20 = _average_derived(system_curves, "mtf20")
    derived_mtf50 = _average_derived(system_curves, "mtf50")
    mtf10 = mtf10 or derived_mtf10
    mtf20 = mtf20 or derived_mtf20
    mtf50 = mtf50 or derived_mtf50
    if mtf10 is None and mtf20 is None and mtf50 is None:
        return None
    basis = []
    score_parts = []
    if mtf50 is not None:
        sub = _clamp(100.0 - max(0.0, 5.0 - mtf50) * 12.0, 35.0, 100.0)
        basis.append("MTF50 {:.2f}".format(mtf50))
        score_parts.append((0.5, sub))
    if mtf20 is not None:
        sub = _clamp(100.0 - max(0.0, 8.0 - mtf20) * 8.0, 35.0, 100.0)
        basis.append("MTF20 {:.2f}".format(mtf20))
        score_parts.append((0.3, sub))
    if mtf10 is not None:
        sub = _clamp(100.0 - max(0.0, 15.0 - mtf10) * 5.0, 35.0, 100.0)
        basis.append("MTF10 {:.2f}".format(mtf10))
        score_parts.append((0.2, sub))
    total_weight = sum(weight for weight, _ in score_parts)
    score = sum(weight * sub for weight, sub in score_parts) / total_weight
    direction_diff = _first_number(values_map, "direction_difference")
    if direction_diff is None:
        direction_diff = _system_direction_diff(system_curves)
    if direction_diff is not None:
        basis.append("水平/垂直方向差异 {:.1f}%".format(direction_diff))
        if direction_diff > 20:
            score -= min(20.0, (direction_diff - 20.0) * 0.5)
    hf_max = _first_number(values_map, "mtf_hf_max")
    if hf_max is None:
        scanner_curves = [curve for curve in curves if curve.get("name", "").startswith("Scanner MTF ")]
        response_values = [y for curve in scanner_curves for _, y in _derive_mtf_points(curve)]
        if response_values and max(response_values) > 1.1:
            hf_max = max(response_values)
    if hf_max is not None:
        basis.append("高频响应峰值 {:.3f}".format(hf_max))
        if hf_max > 1.1:
            score -= 20.0
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _mtf_summary(score, direction_diff, hf_max),
    }


def _mtf_summary(score, direction_diff, hf_max):
    if score >= 85 and (direction_diff is None or direction_diff <= 20) and (hf_max is None or hf_max <= 1.1):
        return "当前样品在细节与边缘再现方面整体稳定，经 OECF 与 MTF 标准化校正后，未观察到明显异常波动。"
    if score >= 70:
        return "当前样品在细节与边缘再现方面整体处于可接受水平，但部分空间频率区域存在响应变化，建议结合重复测量进一步确认。"
    return "当前样品在细小线条、边缘过渡及高频细节的稳定再现方面存在较明显的改善空间。"


def _average_derived(curves, key):
    values = []
    for curve in curves:
        if _derive_mtf_points(curve):
            value = _derive_mtf_values(curve).get(key)
            if value is not None:
                values.append(value)
    return sum(values) / len(values) if values else None


def _visible_mtf_curve(curve):
    name = curve.get("name", "")
    if name.startswith("Scanner MTF "):
        return name[len("Scanner MTF "):] in ("YH", "YV")
    return True


def _system_direction_diff(curves):
    by_name = {}
    for curve in curves:
        by_name[curve.get("name", "")] = curve
    diffs = []
    for horizontal_name, vertical_name in (
        ("G Channel - Horizontal", "G Channel - Vertical"),
        ("Luminance - Horizontal", "Luminance - Vertical"),
    ):
        horizontal = by_name.get(horizontal_name)
        vertical = by_name.get(vertical_name)
        if not horizontal or not vertical:
            continue
        h_value = _derive_mtf_values(horizontal).get("mtf50")
        v_value = _derive_mtf_values(vertical).get("mtf50")
        if h_value is not None and v_value is not None and max(h_value, v_value) > 0:
            diffs.append(abs(h_value - v_value) / max(h_value, v_value) * 100.0)
    return max(diffs) if diffs else None


def _mtf_direction_diff(curves):
    groups = {}
    for curve in curves:
        name = curve.get("name", "")
        prefix = ""
        token = None
        for part in reversed(name.split()):
            if part.isalpha() and token is None:
                token = part
                break
        if name.split():
            prefix = name.split()[0].lower()
        if not token:
            continue
        base = token[:-1] if token[-1:] in ("H", "V") and len(token) > 1 else token
        groups.setdefault("{}:{}".format(prefix, base.upper()), []).append(curve)
    diffs = []
    for group in groups.values():
        values = [_derive_mtf_values(curve).get("mtf50") for curve in group]
        values = [value for value in values if value is not None]
        if len(values) >= 2:
            for index in range(len(values)):
                for other in range(index + 1, len(values)):
                    denom = max(values[index], values[other])
                    if denom > 0:
                        diffs.append(abs(values[index] - values[other]) / denom * 100.0)
    return max(diffs) if diffs else None


def _score_character_line(values_map):
    line_width = _first_number(values_map, "line_width")
    target_width = _first_number(values_map, "line_width_target")
    error = _first_number(values_map, "line_width_error")
    blur = _first_number(values_map, "edge_blur", "edge_blur_lower", "edge_blur_upper")
    roughness = _first_number(values_map, "edge_roughness", "edge_roughness_lower", "edge_roughness_upper")
    holes = _first_number(values_map, "character_holes", "character_void_ratio")
    marks = _first_number(values_map, "character_marks", "character_mark_ratio")
    fog = _first_number(values_map, "character_fog")
    basis = []
    score = 100.0
    if line_width is not None and target_width is not None and target_width > 0 and error is None:
        error = abs(line_width - target_width) / target_width * 100.0
    if error is not None:
        basis.append("线宽误差 {:.2f}%".format(error))
        if error > 15:
            score -= min(35.0, (error - 15.0) * 0.7)
        elif error > 8:
            score -= (error - 8.0) * 1.2
    if line_width is not None:
        basis.append("实测线宽 {:.4f} mm".format(line_width))
    if blur is not None:
        if blur <= 1:
            blur = blur * 1000.0
        basis.append("边缘模糊度 {:.1f} um".format(blur))
        if blur > 80:
            score -= min(25.0, (blur - 80.0) * 0.2)
        elif blur > 40:
            score -= (blur - 40.0) * 0.2
    if roughness is not None:
        basis.append("边缘粗糙度 {:.2f} um".format(roughness))
        if roughness > 20:
            score -= min(15.0, (roughness - 20.0) * 0.25)
    for key, label, value, ratio_threshold in (
        ("character_holes", "字符空洞", holes, None),
        ("character_marks", "外来标记", marks, None),
        ("character_void_ratio", "字符空洞占比", _first_number(values_map, "character_void_ratio"), 0.02),
        ("character_mark_ratio", "外来标记占比", _first_number(values_map, "character_mark_ratio"), 0.02),
        ("character_fog", "字符雾影", fog, None),
    ):
        if value is not None:
            basis.append("{} {}".format(label, _fmt(value)))
            if ratio_threshold is not None and value > ratio_threshold:
                score -= min(15.0, (value - ratio_threshold) * 120.0)
            elif ratio_threshold is None and value > 0:
                score -= min(15.0, value * 4.0)
    if not basis:
        return None
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _character_summary(score, holes, marks, blur),
    }


def _character_summary(score, holes, marks, blur):
    if score >= 85 and (holes or 0) == 0 and (marks or 0) == 0:
        return "当前检测区域内未发现明显空洞，字符与线条测量结果已记录。"
    if score >= 70:
        return "当前字符与线条测量结果已记录，部分边缘或局部标记需要结合原始图像进一步确认。"
    return "当前字符与线条相关指标存在明显变化趋势，建议结合阈值条件、印刷过程和重复测量进一步确认。"


def _score_large_area(values_map):
    rmax = _first_number(values_map, "rmax")
    rmin = _first_number(values_map, "rmin")
    ref_range = _first_number(values_map, "reflectance_range")
    density_range = _first_number(values_map, "density_range")
    uniformity = _first_number(values_map, "uniformity_index")
    holes = _first_number(values_map, "large_area_holes")
    marks = _first_number(values_map, "large_area_marks")
    void_ratio = _first_number(values_map, "large_area_void_ratio")
    mark_ratio = _first_number(values_map, "background_mark_ratio")
    darkness = _first_number(values_map, "large_area_darkness", "large_area_density")
    basis = []
    score = 100.0
    if rmax is not None and rmin is not None:
        ref_range = rmax - rmin
        basis.append("反射率范围 {:.3f}%".format(ref_range))
    if ref_range is not None:
        if "反射率范围" not in " ".join(basis):
            basis.append("反射率范围 {:.3f}%".format(ref_range))
        if ref_range > 2.0:
            score -= min(45.0, (ref_range - 1.0) * 20.0)
        elif ref_range > 1.0:
            score -= (ref_range - 1.0) * 15.0
    if density_range is not None:
        basis.append("密度差范围 {:.3f}".format(density_range))
        if density_range > 0.10:
            score -= min(45.0, (density_range - 0.10) * 350.0)
        elif density_range > 0.05:
            score -= (density_range - 0.05) * 350.0
    if uniformity is not None:
        basis.append("均匀性指数 {:.2f}%".format(uniformity))
        score = min(score, _clamp(uniformity))
    for key, label, value in (
        ("large_area_holes", "空洞数量", holes),
        ("large_area_marks", "外来标记数量", marks),
    ):
        if value is not None:
            basis.append("{} {}".format(label, _fmt(value)))
            if value > 0:
                score -= min(20.0, value * 5.0)
    if void_ratio is not None:
        basis.append("大面积空洞占比 {:.4f}".format(void_ratio))
        if void_ratio > 0.05:
            score -= min(40.0, (void_ratio - 0.05) * 80.0)
    if mark_ratio is not None:
        basis.append("背景外来标记占比 {:.4f}".format(mark_ratio))
        if mark_ratio > 0.02:
            score -= min(15.0, (mark_ratio - 0.02) * 120.0)
    if darkness is not None:
        basis.append("大面积暗度 {:.4f}".format(darkness))
    if not basis:
        return None
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _large_area_summary(score, ref_range, density_range),
    }


def _large_area_summary(score, ref_range, density_range):
    if score >= 85:
        return "当前大面积区域反射率与暗度数据已记录，均匀性趋势需结合历史基线进一步判断。"
    if score >= 70:
        return "当前大面积区域均匀性存在一定变化趋势，建议增加多 ROI 与重复测量确认。"
    return "当前大面积区域反射率或空洞指标变化较明显，建议检查照明、介质、测量 ROI 及图像处理条件。"


def _score_texture(values_map):
    grain = _first_number(values_map, "graininess")
    mottle = _first_number(values_map, "mottle")
    basis = []
    parts = []
    if grain is not None:
        sub = _piecewise(grain, 1.5, 2.0, 3.0, 4.5)
        basis.append("Graininess {:.3f}".format(grain))
        if sub is not None:
            parts.append((0.5, sub))
    if mottle is not None:
        sub = _piecewise(mottle, 1.2, 2.0, 3.5, 5.0)
        basis.append("Mottle {:.3f}".format(mottle))
        if sub is not None:
            parts.append((0.5, sub))
    if not parts:
        return None
    score = sum(weight * sub for weight, sub in parts) / sum(weight for weight, _ in parts)
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _texture_summary(score, grain, mottle),
    }


def _texture_summary(score, grain, mottle):
    if score >= 85:
        return "当前 Graininess 与 Mottle 测量结果已记录，主要作为质量基线；建议通过重复测量建立统计参考范围。"
    if score >= 70:
        return "当前纹理指标存在一定变化趋势，建议结合历史基线与多区域测量进一步确认。"
    return "当前纹理指标变化较明显，建议复测并检查材料、墨层与扫描噪声对测量结果的影响。"


def _score_banding(values_map):
    amplitude = _first_number(values_map, "banding_amplitude")
    energy = _first_number(values_map, "banding_energy")
    vertical = _first_number(values_map, "vertical_banding")
    horizontal = _first_number(values_map, "horizontal_banding")
    if amplitude is None and (vertical is not None or horizontal is not None):
        candidates = [value for value in (vertical, horizontal) if value is not None]
        if candidates:
            amplitude = max(candidates)
    basis = []
    score = 100.0
    if amplitude is not None:
        basis.append("条带峰值幅度 {:.3f}".format(amplitude))
        if amplitude <= -45:
            pass
        elif amplitude <= -30:
            score -= 10
        elif amplitude <= -15:
            score -= 25
        elif amplitude < 1:
            if amplitude <= 0.005:
                pass
            elif amplitude <= 0.02:
                score -= 15
            elif amplitude <= 0.05:
                score -= 30
            else:
                score -= 45
        else:
            score -= 40
    if energy is not None:
        basis.append("条带能量 {:.4f}".format(energy))
        if energy > 0.02:
            score -= min(30.0, (energy - 0.02) * 500.0)
        elif energy > 0.005:
            score -= (energy - 0.005) * 500.0
    if vertical is not None:
        basis.append("垂直条带评分 {:.3f}".format(vertical))
    if horizontal is not None:
        basis.append("水平条带评分 {:.3f}".format(horizontal))
    if not basis:
        return None
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _banding_summary(score, amplitude),
    }


def _banding_summary(score, amplitude):
    if score >= 85:
        return "当前条带数据已记录，未观察到明显周期性响应，可作为当前条件下的基线记录。"
    if score >= 70:
        return "当前条带幅度存在一定周期性波动，建议结合频谱与原始图像确认。"
    return "当前条带信号变化较明显，建议结合频谱、方向复测及机械/供墨过程进一步排查。"


def _score_defect(values_map):
    count_keys = (
        ("holes_count", "空洞"),
        ("marks_count", "外来标记"),
        ("fog_count", "雾影"),
        ("contamination_count", "污染"),
        ("edge_anomaly_count", "边缘异常"),
        ("defect_count", "缺陷总数"),
    )
    area_keys = (
        ("holes_area", "空洞面积"),
        ("marks_area", "外来标记面积"),
        ("fog_area", "雾影面积"),
    )
    basis = []
    score = 100.0
    for key, label in count_keys:
        value = _first_number(values_map, key)
        if value is not None:
            basis.append("{} {}".format(label, _fmt(value)))
            if value > 0:
                score -= min(15.0, value * 4.0)
    for key, label in area_keys:
        value = _first_number(values_map, key)
        if value is not None:
            basis.append("{} {}".format(label, _fmt(value, 4)))
            if value > 0:
                score -= min(12.0, value * 8.0)
    ratio_keys = (
        ("defect_void_ratio", "空洞占比", 0.02),
        ("defect_mark_ratio", "外来标记占比", 0.02),
        ("defect_fog_csa", "雾影占比 (C.S.A)", None),
        ("defect_fog_r75", "雾影占比 (R75)", None),
    )
    for key, label, threshold in ratio_keys:
        value = _first_number(values_map, key)
        if value is not None:
            basis.append("{} {}".format(label, _fmt(value, 4)))
            if threshold is not None and value > threshold:
                if value > 0.05:
                    score -= 15.0
                else:
                    score -= 8.0
    severity = values_map.get("defect_severity")
    if severity:
        text = str(severity[-1]).lower()
        if text in ("high", "严重", "高"):
            score -= 20
            basis.append("缺陷严重程度 高")
        elif text in ("medium", "中"):
            score -= 10
            basis.append("缺陷严重程度 中")
        elif text in ("low", "低"):
            score -= 5
            basis.append("缺陷严重程度 低")
    if not basis:
        return None
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _defect_summary(score),
    }


def _defect_summary(score):
    if score >= 90:
        return "本次检测未发现明显缺陷，缺陷控制表现良好。"
    if score >= 75:
        return "本次检测发现少量缺陷，整体处于可控范围，建议结合图像确认。"
    return "本次检测发现较多缺陷，建议定位缺陷类型并复测确认。"


def _score_repeatability(values_map):
    cv = _first_number(values_map, "repeatability_cv")
    std = _first_number(values_map, "repeatability_std")
    mean = _first_number(values_map, "repeatability_mean")
    basis = []
    if cv is None and std is not None and mean:
        cv = std / abs(mean) * 100.0
    if cv is None:
        return None
    basis.append("重复性变异系数 {:.2f}%".format(cv))
    score = _piecewise(cv, 1.0, 3.0, 5.0, 8.0)
    if score is None:
        return None
    return {
        "score": _score_int(score),
        "basis": basis,
        "summary": _repeatability_summary(score, cv),
    }


def _repeatability_summary(score, cv):
    if score >= 85:
        return "重复性测量表现稳定，当前数据适合作为质量基线参考。"
    if score >= 70:
        return "重复性处于可接受范围，但存在一定波动，建议确认测量条件一致性。"
    return "重复性波动偏高，建议核查环境、样品放置与测量流程后复测。"


def _fmt(value, digits=3):
    try:
        num = float(value)
        if abs(num - round(num)) < 0.0001:
            return str(int(round(num)))
        return ("{:.%df}" % digits).format(num)
    except (TypeError, ValueError):
        return str(value)


def _score_dimension(module, values_map, curves, provided_score):
    score_obj = None
    if module == "oecf":
        score_obj = _score_oecf(values_map, curves)
    elif module == "mtf":
        score_obj = _score_mtf(values_map, curves)
    elif module == "character_line":
        score_obj = _score_character_line(values_map)
    elif module == "large_area":
        score_obj = _score_large_area(values_map)
    elif module == "texture":
        score_obj = _score_texture(values_map)
    elif module == "banding":
        score_obj = _score_banding(values_map)
    elif module == "defect":
        score_obj = _score_defect(values_map)
    elif module == "repeatability":
        score_obj = _score_repeatability(values_map)
    if score_obj is None:
        return None
    score = score_obj["score"]
    if provided_score is not None:
        score = _score_int(provided_score)
        score_obj["provided"] = True
    status, status_zh = _status_for_score(score)
    if module == "texture" and not _has_history(values_map):
        status = "baseline"
        status_zh = "建立基线"
    return {
        "module": module,
        "zh": MODULE_ZH[module],
        "score": score,
        "status": status,
        "status_zh": status_zh,
        "summary": score_obj["summary"],
        "basis": score_obj.get("basis", []),
        "provided": score_obj.get("provided", False),
    }


def _has_history(values_map):
    return bool(values_map.get("repeatability_cv") or values_map.get("repeatability_std"))


def _quality_status_for_score(score):
    if score is None:
        return "missing", "未测量"
    if score >= 90:
        return "excellent", "优秀"
    if score >= 80:
        return "good", "良好"
    if score >= 70:
        return "fair", "一般"
    if score >= 60:
        return "risk", "存在明显风险"
    return "improve", "需要重点改进"


def _overview_text(module, score):
    if score is None:
        return "当前模块数据不足，暂不进行质量表现判定。"
    if score >= 90:
        level = "excellent"
    elif score >= 80:
        level = "good"
    elif score >= 70:
        level = "attention"
    else:
        level = "warning"
    rules = {
        "oecf": {
            "excellent": "当前灰阶响应稳定，灰阶层次与连续性表现优秀。",
            "good": "当前灰阶响应整体稳定，灰阶层次保持较好，未观察到明显响应异常。",
            "attention": "当前灰阶响应存在一定波动，部分灰阶区域的连续性需要进一步关注。",
            "warning": "当前灰阶响应稳定性不足，可能影响灰阶层次和色调过渡的准确再现。",
        },
        "mtf": {
            "excellent": "当前样品对细小线条、边缘及高频细节具有较好的稳定再现能力。",
            "good": "当前样品整体细节复制能力较好，高频细节保持较稳定。",
            "attention": "当前样品在部分细小线条和边缘细节的再现方面存在一定改善空间。",
            "warning": "当前样品在细小线条、边缘过渡及高频细节的稳定再现方面表现较弱，是需要优先改善的质量项目之一。",
        },
        "character_line": {
            "excellent": "当前字符与线条复制整体表现优秀，线条尺寸、边缘质量及字符完整性均保持较高水平。",
            "good": "当前字符与线条复制质量较好，整体尺寸与边缘表现较稳定。",
            "attention": "当前字符或线条局部区域存在一定复制偏差，需要关注边缘与尺寸稳定性。",
            "warning": "当前字符与线条复制存在较明显偏差，可能影响文字和细线图形的清晰度。",
        },
        "large_area": {
            "excellent": "当前大面积区域整体均匀性良好，未观察到明显的局部反射率波动。",
            "good": "当前大面积区域整体较为均匀，局部存在轻微波动但视觉影响有限。",
            "attention": "当前大面积区域存在一定反射率波动，整体均匀性仍有改善空间。",
            "warning": "当前大面积区域存在较明显的反射率波动或局部不均匀现象，可能影响视觉一致性。",
        },
        "texture": {
            "excellent": "当前颗粒感与低频不均匀性控制良好，整体纹理表现稳定。",
            "good": "当前颗粒感与低频不均匀性整体控制较稳定，纹理质量表现良好。",
            "attention": "当前局部纹理波动有所增加，需要关注颗粒感和低频不均匀性的变化。",
            "warning": "当前纹理波动较明显，可能影响图像区域的视觉平滑性和均匀性。",
        },
        "banding": {
            "excellent": "当前周期性不均匀控制良好，未检测到明显条带特征。",
            "good": "当前条带控制整体稳定，周期性不均匀特征较弱。",
            "attention": "当前存在一定周期性不均匀特征，需要关注条带趋势。",
            "warning": "当前图像中检测到较明显的周期性不均匀特征，可能影响大面积图形的视觉一致性。",
        },
    }
    module_rules = rules.get(module)
    if module_rules:
        return module_rules[level]
    return "当前模块测量结果已记录，具体质量表现需结合评分和指标进一步分析。"


def _technical_note(module):
    return {
        "oecf": "采用统一 ROI 与标准化校正后的灰阶响应数据进行分析。",
        "mtf": "采用统一 ROI，并结合空间响应补偿后的 MTF 数据进行分析。",
        "character_line": "采用统一 ROI 与标准化校正后的图像数据进行分析。",
        "large_area": "采用统一 ROI 与标准化校正后的大面积图形数据进行分析。",
        "texture": "采用统一 ROI 与标准化校正后的纹理数据进行分析。",
        "banding": "采用统一 ROI 与标准化校正后的条带频谱数据进行分析。",
    }.get(module, "当前结果基于本次上传的标准化测量数据生成。")


def _baseline_note(reference_status_zh):
    if reference_status_zh == "已建立评价基准":
        return "当前模块已具备历史参考数据，评价结果可结合历史趋势使用。"
    return "当前历史参考不足，建议通过后续批次重复测量建立长期基线，并持续记录批次变化。"


def _enrich_dimension(module, score_obj, values_map):
    score = score_obj.get("score")
    quality_status, quality_status_zh = _quality_status_for_score(score)
    if _has_history(values_map):
        reference_status = "established"
        reference_status_zh = "已建立评价基准"
    elif module in ("oecf", "texture", "banding"):
        reference_status = "baseline_recommended"
        reference_status_zh = "建议建立长期基线"
    else:
        reference_status = "baseline_missing"
        reference_status_zh = "历史基线不足"
    score_obj["status"] = quality_status
    score_obj["status_zh"] = quality_status_zh
    score_obj["quality_status"] = quality_status
    score_obj["quality_status_zh"] = quality_status_zh
    score_obj["reference_status"] = reference_status
    score_obj["reference_status_zh"] = reference_status_zh
    score_obj["overview"] = _overview_text(module, score)
    score_obj["module_summary"] = score_obj.get("summary") or "当前模块测量结果已记录。"
    score_obj["technical_note"] = _technical_note(module)
    score_obj["baseline_note"] = _baseline_note(reference_status_zh)
    return score_obj


def _provided_status(module, provided_scores):
    status = provided_scores.get(module + "_status")
    if status and str(status).lower() in VALID_STATUSES:
        return str(status).lower()
    zh_map = {
        "良好": "good",
        "优秀": "good",
        "需要关注": "attention",
        "存在明显风险": "warning",
        "需要重点改进": "danger",
        "未测量": "missing",
        "建立基线": "baseline",
    }
    return zh_map.get(str(status))


def _build_sample(sample_id, records, curves, provided_scores, files, batch_id, sample_info=None):
    metrics = []
    for record in records:
        value = record.get("value")
        valid = _num(value) is not None or (isinstance(value, str) and bool(value.strip()))
        item = dict(record)
        item["sample_id"] = sample_id
        item["valid"] = valid
        if not valid:
            item["invalid_reason"] = "非数值或空值"
        metrics.append(item)
    sample_curves = []
    for curve in curves:
        item = dict(curve)
        item["sample_id"] = sample_id
        sample_curves.append(item)
    dimensions = {}
    dimension_scores = []
    for module in ACTIVE_MODULE_ORDER:
        values_map = _module_values(metrics, module)
        module_curves = _curves_for_module(sample_curves, module)
        provided_score = _num(provided_scores.get(module))
        score_obj = _score_dimension(module, values_map, module_curves, provided_score)
        if score_obj is None and provided_score is not None:
            score_obj = {
                "module": module,
                "zh": MODULE_ZH[module],
                "score": _score_int(provided_score),
                "basis": ["评分由上传数据中的 {} 系统评分直接提供".format(MODULE_ZH[module])],
                "summary": "{}评分由上传数据提供，本次未重复计算。".format(MODULE_ZH[module]),
                "provided": True,
            }
        if score_obj is None and values_map:
            score_obj = {
                "module": module,
                "zh": MODULE_ZH[module],
                "score": None,
                "status": "missing",
                "status_zh": "数据不足",
                "summary": "当前模块存在已识别数据，但缺少可用于评分的有效指标。",
                "basis": [],
                "provided": False,
            }
        if score_obj is None:
            score_obj = {
                "module": module,
                "zh": MODULE_ZH[module],
                "score": None,
                "status": "missing",
                "status_zh": "未测量",
                "summary": "当前未提供有效的{}数据。".format(MODULE_ZH[module]),
                "basis": [],
                "provided": False,
            }
        score_obj = _enrich_dimension(module, score_obj, values_map)
        dimensions[module] = score_obj
        if score_obj["score"] is not None:
            dimension_scores.append(score_obj)
    provided_overall = _num(provided_scores.get("overall"))
    overall = None
    overall_basis = []
    if provided_overall is not None:
        overall = _score_int(provided_overall)
        overall_basis = ["综合评分由上传数据中的 overall_score / 系统评分直接提供"]
    elif dimension_scores and len(dimension_scores) >= 2:
        overall = _score_int(sum(item["score"] for item in dimension_scores) / len(dimension_scores))
        overall_basis = ["基于 {} 个已完成且通过有效性检查的模块等权平均".format(len(dimension_scores))]
    elif dimension_scores:
        overall_basis = ["当前仅 {} 个模块参与评分，综合评分暂不计算".format(len(dimension_scores))]
    overall_status, overall_status_zh = _status_for_score(overall)
    if overall is None and dimension_scores:
        overall_status = "missing"
        overall_status_zh = "数据不足"
    if provided_overall is not None and provided_scores.get("overall_status"):
        status = _provided_status("overall", provided_scores)
        if status:
            overall_status = status
            overall_status_zh = _status_zh(status)
    diagnosis = _diagnose_sample(sample_id, dimensions, metrics, sample_curves)
    findings = _build_findings(dimensions, diagnosis)
    recommendations = _build_recommendations(diagnosis)
    summary = _executive_summary(overall, overall_status_zh, dimensions, diagnosis)
    final_conclusion = _final_conclusion(overall, overall_status_zh, dimensions, diagnosis)
    modules_measured = [module for module, item in dimensions.items() if item["score"] is not None]
    modules_missing = [module for module, item in dimensions.items() if item["score"] is None]
    sample = {
        "sample_id": sample_id,
        "metadata": _sample_metadata(records, sample_info or {}),
        "metrics": metrics,
        "curves": sample_curves,
        "charts": {},
        "dimensions": dimensions,
        "overall": {
            "score": overall,
            "status": overall_status,
            "status_zh": overall_status_zh,
            "summary": summary,
            "basis": overall_basis,
            "provided": provided_overall is not None,
        },
        "findings": findings,
        "diagnosis": diagnosis,
        "recommendations": recommendations,
        "final_conclusion": final_conclusion,
        "data_integrity": {
            "sample_id_missing": sample_id == MISSING_SAMPLE,
            "modules_measured": modules_measured,
            "modules_missing": modules_missing,
            "source_files": sorted({item.get("source_file") for item in metrics} | {item.get("source_file") for item in sample_curves}),
            "invalid_metrics": [item for item in metrics if not item.get("valid", True)],
            "batch_id": batch_id,
            "notes": _integrity_notes(sample_id, modules_missing),
        },
    }
    sample["charts"] = build_sample_charts(sample)
    return sample


def _sample_metadata(records, sample_info):
    metadata = dict(sample_info)
    for record in records:
        sid = record.get("sample_id") or ""
        if sid and "sample_id" not in metadata:
            metadata["sample_id"] = sid
    return metadata


def _integrity_notes(sample_id, modules_missing):
    notes = []
    if sample_id == MISSING_SAMPLE:
        notes.append("样品编号未提供，报告中以“未提供”标识；该缺失未阻断测量分析与报告生成。")
    if modules_missing:
        names = "、".join(MODULE_ZH[module] for module in modules_missing)
        notes.append("未测量模块：{}；这些模块不参与综合评分，也不默认视为质量良好。".format(names))
    notes.append("当前综合评分仅基于已完成且通过有效性检查的测试模块计算。")
    notes.append("状态与评分来自系统内部评估，不替代正式门限判定或验收结论。")
    return notes


def _diagnose_sample(sample_id, dimensions, metrics, curves):
    diagnosis = []
    values_by_module = {module: _module_values(metrics, module) for module in ACTIVE_MODULE_ORDER}
    oecf_values = values_by_module["oecf"]
    mtf_values = values_by_module["mtf"]
    char_values = values_by_module["character_line"]
    large_values = values_by_module["large_area"]
    texture_values = values_by_module["texture"]
    banding_values = values_by_module["banding"]

    mono = _first_number(oecf_values, "oecf_monotonicity")
    if mono is not None and mono <= 1:
        mono = mono * 100.0
    cont = _first_number(oecf_values, "oecf_continuity")
    if cont is not None and cont <= 1:
        cont = cont * 100.0
    curve_stat = _analyze_oecf_curve(_curves_for_module(curves, "oecf"))
    if (mono is not None and mono < 95) or (cont is not None and cont < 90) or (curve_stat and curve_stat["monotonic"] < 90):
        evidence = "灰阶单调性或连续性低于系统阈值"
        if curve_stat:
            evidence = "OECF 曲线单调性 {:.1f}%，最大跳变/中位步长 {:.1f}".format(
                curve_stat["monotonic"], curve_stat["max_step"] / max(curve_stat["median_step"], 1e-9)
            )
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "灰阶响应连续性需要关注",
                "evidence": evidence,
                "possible_causes": ["灰阶图输出不稳定", "扫描链路光电响应异常", "OECF 标定数据未更新"],
                "verification": ["使用标准灰阶卡复测", "检查 OECF 标定状态", "对比相邻批次曲线"],
                "recommendation": "复核灰阶图与 OECF 标定后复测。",
            }
        )
    mtf_curves = _curves_for_module(curves, "mtf")
    visible_mtf_curves = [curve for curve in mtf_curves if _visible_mtf_curve(curve)] or mtf_curves
    system_mtf_curves = build_mtf_system_curves(mtf_curves) or visible_mtf_curves
    direction_diff = _first_number(mtf_values, "direction_difference")
    if direction_diff is None:
        direction_diff = _system_direction_diff(system_mtf_curves)
    hf_max = _first_number(mtf_values, "mtf_hf_max")
    if hf_max is None:
        scanner_mtf_curves = [curve for curve in mtf_curves if curve.get("name", "").startswith("Scanner MTF ")]
        response_values = [y for curve in scanner_mtf_curves for _, y in _derive_mtf_points(curve)]
        if response_values and max(response_values) > 1.1:
            hf_max = max(response_values)
    mtf50 = _first_number(mtf_values, "mtf50", "scanner_mtf50", "target_mtf50")
    if not mtf50:
        mtf50 = _average_derived(system_mtf_curves, "mtf50")
    if direction_diff is not None and direction_diff > 20:
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "细节再现存在方向性差异",
                "evidence": "经标准化校正后，水平/垂直方向的细节再现差异约为 {:.1f}%".format(direction_diff),
                "possible_causes": ["印刷过程中的方向性再现特征", "墨点扩散", "介质传输稳定性"],
                "verification": ["对多个 ROI 进行方向性复测", "旋转测试卡后重新测量", "对比不同批次样品"],
                "recommendation": "建议结合印刷方向、工艺参数和材料特性进一步确认方向性差异来源。",
            }
        )
    if hf_max is not None and hf_max > 1.1:
        diagnosis.append(
            {
                "priority": "high",
                "issue": "高频细节响应存在波动",
                "evidence": "经 OECF 与 MTF 标准化校正后，部分高频区域仍存在响应波动，高频响应峰值记录为 {:.3f}".format(hf_max),
                "possible_causes": ["印刷过程高频细节保持能力不足", "墨点扩散", "材料表面特性", "成像工艺参数"],
                "verification": [
                    "对同一样品进行重复扫描和复测",
                    "对多个 ROI 进行方向性对比",
                    "检查印刷设备状态与工艺参数",
                ],
                "recommendation": "建议重点关注印刷过程中的细节保持能力、线条扩散特性及材料适配性，并进一步检查印刷设备状态和工艺参数。",
            }
        )
    if mtf50 is not None and mtf50 < 2.0:
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "高频细节还原能力偏低",
                "evidence": "经标准化处理后，系统细节保持能力记录为 MTF50 = {:.2f}".format(mtf50),
                "possible_causes": ["印刷过程有效分辨率不足", "墨点扩散或网点增益", "材料吸收与表面特性"],
                "verification": ["对同一样品进行重复扫描复测", "对多个 ROI 进行方向性对比", "检查印刷设备状态与工艺参数"],
                "recommendation": "建议结合印刷分辨率、墨点扩散和材料适配性进一步确认，并通过相同条件下的重复测量验证。",
            }
        )
    error = _first_number(char_values, "line_width_error")
    line_width = _first_number(char_values, "line_width")
    target_width = _first_number(char_values, "line_width_target")
    if error is None and line_width is not None and target_width:
        error = abs(line_width - target_width) / abs(target_width) * 100.0
    if error is not None and error > 15:
        diagnosis.append(
            {
                "priority": "high",
                "issue": "线宽误差超出预期",
                "evidence": "线宽误差 {:.2f}%".format(error),
                "possible_causes": ["线条/网点扩散", "墨量波动", "测量阈值设置差异"],
                "verification": ["复测线宽并检查阈值", "对比设计文件目标线宽", "检查印刷方向上的扩散"],
                "recommendation": "确认线宽测量阈值与印刷过程后复测。",
            }
        )
    blur = _first_number(char_values, "edge_blur")
    if blur is not None:
        if blur <= 1:
            blur = blur * 1000.0
        if blur > 80:
            diagnosis.append(
                {
                    "priority": "medium",
                    "issue": "边缘模糊度偏高",
                    "evidence": "边缘模糊度 {:.1f} um".format(blur),
                    "possible_causes": ["印刷扩散或网点增益", "墨量波动", "材料表面特性"],
                    "verification": ["对同一样品进行重复测量", "对比不同 ROI 和方向", "检查印刷设备与工艺参数"],
                    "recommendation": "建议结合印刷扩散、墨量和材料特性进一步确认，并通过重复测量验证结果稳定性。",
                }
            )
    char_holes = _first_number(char_values, "character_holes")
    char_marks = _first_number(char_values, "character_marks")
    char_void_ratio = _first_number(char_values, "character_void_ratio")
    char_mark_ratio = _first_number(char_values, "character_mark_ratio")
    if (
        (char_holes or 0) > 0
        or (char_marks or 0) > 0
        or (char_void_ratio is not None and char_void_ratio > 0.02)
        or (char_mark_ratio is not None and char_mark_ratio > 0.02)
    ):
        evidence_parts = []
        if char_holes:
            evidence_parts.append("字符空洞 {}".format(_fmt(char_holes)))
        if char_marks:
            evidence_parts.append("外来标记 {}".format(_fmt(char_marks)))
        if char_void_ratio is not None and char_void_ratio > 0.02:
            evidence_parts.append("字符空洞占比 {:.4f}".format(char_void_ratio))
        if char_mark_ratio is not None and char_mark_ratio > 0.02:
            evidence_parts.append("外来标记占比 {:.4f}".format(char_mark_ratio))
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "字符区域检测到空洞或外来标记",
                "evidence": "；".join(evidence_parts),
                "possible_causes": ["印版/喷头缺陷", "异物污染", "图像处理残留"],
                "verification": ["放大图像确认缺陷类型", "清洁或更换部件后复测", "检查二值化与阈值参数"],
                "recommendation": "结合图像确认缺陷来源并复测。",
            }
        )
    ref_range = _first_number(large_values, "reflectance_range")
    density_range = _first_number(large_values, "density_range")
    if ref_range is not None and ref_range > 2.0:
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "大面积均匀性存在波动",
                "evidence": "反射率范围 {:.3f}%".format(ref_range),
                "possible_causes": ["供墨不均", "介质平整度差异", "扫描照明不均匀"],
                "verification": ["重新扫描多个 ROI", "检查扫描照明与校准", "对比历史均匀性数据"],
                "recommendation": "确认均匀性波动来源后复测。",
            }
        )
    elif density_range is not None and density_range > 0.10:
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "大面积均匀性存在波动",
                "evidence": "密度差范围 {:.3f}".format(density_range),
                "possible_causes": ["供墨不均", "介质平整度差异", "扫描照明不均匀"],
                "verification": ["重新扫描多个 ROI", "检查扫描照明与校准", "对比历史均匀性数据"],
                "recommendation": "确认均匀性波动来源后复测。",
            }
        )
    grain = _first_number(texture_values, "graininess")
    mottle = _first_number(texture_values, "mottle")
    if (grain is not None and grain > 3.0) or (mottle is not None and mottle > 3.5):
        evidence = []
        if grain is not None:
            evidence.append("Graininess {:.3f}".format(grain))
        if mottle is not None:
            evidence.append("Mottle {:.3f}".format(mottle))
        diagnosis.append(
            {
                "priority": "medium",
                "issue": "表面纹理指标偏高",
                "evidence": "；".join(evidence),
                "possible_causes": ["纸张表面特性", "墨层颗粒", "扫描噪声"],
                "verification": ["确认测量 ROI 一致", "复测并对比历史基线", "检查扫描噪声水平"],
                "recommendation": "结合图像与历史数据判断纹理变化来源。",
            }
        )
    amplitude = _first_number(banding_values, "banding_amplitude")
    energy = _first_number(banding_values, "banding_energy")
    vertical_banding = _first_number(banding_values, "vertical_banding")
    horizontal_banding = _first_number(banding_values, "horizontal_banding")
    if amplitude is None and (vertical_banding is not None or horizontal_banding is not None):
        candidates = [value for value in (vertical_banding, horizontal_banding) if value is not None]
        if candidates:
            amplitude = max(candidates)
    if amplitude is not None and amplitude > -30 or (energy is not None and energy > 0.02):
        evidence = []
        if amplitude is not None:
            evidence.append("条带峰值幅度 {:.3f}".format(amplitude))
        if energy is not None:
            evidence.append("条带能量 {:.4f}".format(energy))
        if vertical_banding is not None:
            evidence.append("垂直条带评分 {:.3f}".format(vertical_banding))
        if horizontal_banding is not None:
            evidence.append("水平条带评分 {:.3f}".format(horizontal_banding))
        diagnosis.append(
            {
                "priority": "high",
                "issue": "检测到较明显的周期性条带",
                "evidence": "；".join(evidence),
                "possible_causes": ["机械传动周期", "供墨/喷头周期", "图像处理引入的周期性纹路"],
                "verification": ["对频谱进行复测", "检查传动与供墨部件", "使用原始图像确认周期性"],
                "recommendation": "优先排查产生周期的机械或供墨环节。",
            }
        )
    return diagnosis


def _build_findings(dimensions, diagnosis):
    scored = [
        item
        for item in dimensions.values()
        if item["score"] is not None and item["score"] >= 80
    ]
    scored.sort(key=lambda item: item["score"], reverse=True)
    good_phrases = {
        "oecf": "灰阶响应整体保持连续",
        "mtf": "细节还原能力表现稳定",
        "character_line": "字符与线条基本完整",
        "large_area": "大面积区域均匀性稳定",
        "texture": "纹理指标处于较低水平",
        "banding": "未检测到明显条带风险",
        "defect": "缺陷数量处于较低水平",
        "repeatability": "重复性测量表现稳定",
    }
    good = [good_phrases[item["module"]] for item in scored[:3]]
    if not good:
        good = ["当前有效数据暂不足以形成明确优势项"]
    attention = []
    for item in diagnosis[:5]:
        attention.append({"issue": item["issue"], "evidence": item["evidence"]})
    priority = []
    for item in diagnosis[:3]:
        priority.append(
            {
                "priority": item["priority"],
                "issue": item["issue"],
                "action": item["recommendation"],
                "purpose": item["issue"].replace("需要关注", "需要优先确认").replace("明显", "明显"),
                "verification": item["verification"][0] if item["verification"] else "复测确认",
            }
        )
    return {
        "good": good,
        "attention": attention,
        "priority": priority,
    }


def _build_recommendations(diagnosis):
    priority_order = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(diagnosis, key=lambda item: priority_order.get(item["priority"], 3))
    recs = []
    for item in ordered[:3]:
        recs.append(
            {
                "priority": item["priority"],
                "priority_zh": {"high": "高", "medium": "中", "low": "低"}.get(item["priority"], "低"),
                "action": item["recommendation"],
                "purpose": item["issue"],
                "verification": item["verification"][0] if item["verification"] else "复测确认",
            }
        )
    if not recs:
        recs.append(
            {
                "priority": "low",
                "priority_zh": "低",
                "action": "将本次结果保存为本批样品质量基线。",
                "purpose": "为后续批次对比与趋势监控提供基线数据。",
                "verification": "在相同测试条件下对下一批次执行同样测量。",
            }
        )
    return recs


def _executive_summary(overall, status_zh, dimensions, diagnosis):
    if overall is None:
        return "当前上传数据仅覆盖部分模块，综合评分暂不可得；已测量模块可正常查看，建议补充缺失模块后重新生成报告。"
    measured = [item for item in dimensions.values() if item["score"] is not None]
    if not measured:
        return "当前上传数据暂不满足综合评分条件，建议补充有效测试模块后重新分析。"
    measured.sort(key=lambda item: item["score"], reverse=True)
    best = measured[0]["zh"]
    worst = measured[-1]["zh"]
    prefix = "当前样品整体印刷质量处于{}，{}表现相对稳定，{}需要进一步关注。".format(status_zh, best, worst)
    if diagnosis:
        prefix += "优先核实“{}”。".format(diagnosis[0]["issue"])
    return prefix[:120]


def _final_conclusion(overall, status_zh, dimensions, diagnosis):
    if overall is None:
        return "本次上传数据仅覆盖部分测试模块，尚不足以形成综合质量结论。已测量模块结果可作为该样品的首轮质量记录；建议补充缺失模块、完成重复性测试并确认样品编号信息后，再形成正式验收结论。"
    measured = [item for item in dimensions.values() if item["score"] is not None]
    measured.sort(key=lambda item: item["score"], reverse=True)
    best = measured[0]["zh"] if measured else "已测量模块"
    worst = measured[-1]["zh"] if measured else "未测量模块"
    problem = diagnosis[0]["issue"] if diagnosis else "未发现明显异常"
    baseline = "可"
    if diagnosis and any(item["priority"] == "high" for item in diagnosis):
        baseline = "暂不"
    next_step = "建议完成相关复测与校准验证后形成最终验收结论。" if diagnosis else "建议在相同条件下补充下一批次测量，建立质量趋势基线。"
    return "本次测试表明，该样品整体印刷质量处于{}。优势主要集中在{}；最需要关注的是{}，具体表现为“{}”。当前结果{}作为该样品的质量基线。{}".format(
        status_zh, best, worst, problem, baseline, next_step
    )[:200]


def analyze_files(parsed_files):
    batch_id = "ISO-BATCH-{}".format(datetime.now().strftime("%Y%m%d-%H%M%S"))
    grouped = {}
    source_by_sample = {}
    for parsed in parsed_files:
        if not parsed.ok:
            continue
        sid = _normalize_sample_id(parsed.sample_info.get("sample_id", ""))
        grouped.setdefault(sid, {"metrics": [], "curves": [], "provided_scores": {}, "files": [], "sample_info": {}})
        for metric in parsed.metrics:
            item = dict(metric)
            if not item.get("sample_id"):
                item["sample_id"] = sid
            grouped[sid]["metrics"].append(item)
        for curve in parsed.curves:
            item = dict(curve)
            if not item.get("sample_id"):
                item["sample_id"] = sid
            grouped[sid]["curves"].append(item)
        for key, value in parsed.provided_scores.items():
            if key not in grouped[sid]["provided_scores"]:
                grouped[sid]["provided_scores"][key] = value
        for key, value in parsed.sample_info.items():
            if key not in grouped[sid]["sample_info"]:
                grouped[sid]["sample_info"][key] = value
        grouped[sid]["files"].append(parsed.filename)
        source_by_sample.setdefault(sid, []).append(parsed.filename)
    samples = []
    for sid, data in grouped.items():
        sample = _build_sample(
            sid,
            data["metrics"],
            data["curves"],
            data["provided_scores"],
            data["files"],
            batch_id,
            sample_info=data["sample_info"],
        )
        samples.append(sample)
    samples.sort(key=lambda item: (item["sample_id"] == MISSING_SAMPLE, item["sample_id"]))
    batch = _build_batch_summary(samples, parsed_files, batch_id)
    return {
        "batch_id": batch_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": [_file_summary(parsed) for parsed in parsed_files],
        "samples": samples,
        "batch": batch,
    }


def _file_summary(parsed):
    modules = []
    for metric in parsed.metrics:
        if metric.get("module") in ACTIVE_MODULE_ORDER and metric.get("module") not in modules:
            modules.append(metric["module"])
    for curve in parsed.curves:
        if curve.get("module") in ACTIVE_MODULE_ORDER and curve.get("module") not in modules:
            modules.append(curve["module"])
    return {
        "filename": parsed.filename,
        "format": parsed.format,
        "ok": parsed.ok,
        "error": parsed.error,
        "sample_id": _normalize_sample_id(parsed.sample_info.get("sample_id", "")),
        "modules": modules,
        "metric_count": len(parsed.metrics),
        "curve_count": len(parsed.curves),
    }


def _build_batch_summary(samples, parsed_files, batch_id):
    sample_ids = [sample["sample_id"] for sample in samples]
    scores = [sample["overall"]["score"] for sample in samples if sample["overall"]["score"] is not None]
    overall = None
    if scores:
        overall = _score_int(sum(scores) / len(scores))
    status, status_zh = _status_for_score(overall)
    matrix = {}
    for module in ACTIVE_MODULE_ORDER:
        matrix[module] = []
        for sample in samples:
            item = sample["dimensions"][module]
            matrix[module].append(
                {
                    "sample_id": sample["sample_id"],
                    "score": item["score"],
                    "status": item["status"],
                    "status_zh": item["status_zh"],
                }
            )
    notes = [
        "默认按同一批次样品分析；未提供样品编号的数据统一标记为“未提供”，不阻断分析与报告生成。",
    ]
    if len(samples) > 1:
        notes.append("检测到多个样品编号，已按样品编号分组分析。")
    return {
        "batch_id": batch_id,
        "sample_count": len(samples),
        "sample_ids": sample_ids,
        "overall": {
            "score": overall,
            "status": status,
            "status_zh": status_zh,
        },
        "module_matrix": matrix,
        "notes": notes,
    }
