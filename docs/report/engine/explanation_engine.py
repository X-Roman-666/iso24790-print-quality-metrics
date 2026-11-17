# -*- coding: utf-8 -*-
"""Structured explanation rules for ISOPrint Inspector report sections.

Each module returns five blocks following the report chain:
measured -> quality -> conditions -> print_factors -> improvement.
The report layer only renders these blocks and does not re-infer quality.
"""

import re


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


def _fmt(value, digits=4):
    if value is None:
        return "未提供"
    try:
        num = float(value)
        if abs(num - round(num)) < 0.0001:
            return str(int(round(num)))
        return ("{:.%df}" % digits).format(num)
    except (TypeError, ValueError):
        return str(value)


def _quality_by_score(score, good, acceptable, limited, weak):
    if score is None:
        return ["当前已完成相关测量，但由于评分条件不足，本次结果仅作为测量记录，不进行综合质量等级判定。"]
    if score >= 85:
        return [good]
    if score >= 70:
        return [acceptable]
    if score >= 50:
        return [limited]
    return [weak]


def _build_oecf(sample, metrics, dimension):
    score = dimension.get("score")
    measured = ["本次获得 OECF 灰阶响应数据，使用 RGB 至视觉反射率（Rvis）的前 256 行数据。"]
    oecf_curves = [curve for curve in sample.get("curves", []) if curve.get("module") == "oecf"]
    visible = [curve for curve in oecf_curves if curve.get("display") is not False]
    if visible:
        measured.append("已识别 R、G、B 三个通道的灰阶响应曲线，每条曲线包含 {} 个测量点。".format(len(visible[0].get("points", []))))
    monotonic = _basis_value(dimension, "单调性")
    continuity = _basis_value(dimension, "连续性")
    if monotonic:
        measured.append("灰阶单调性记录为 {}%。".format(monotonic))
    if continuity:
        measured.append("灰阶连续性记录为 {}%。".format(continuity))
    quality = _quality_by_score(
        score,
        "当前灰阶响应曲线整体连续，未观察到明显的离散跳变。",
        "当前灰阶响应整体连续，但部分灰阶区域的响应变化幅度需要结合重复测量进一步确认。",
        "当前灰阶响应存在一定波动，暗调、中间调或高光区域的连续性需要进一步验证。",
        "当前灰阶响应存在较明显波动，灰阶复制一致性有待改善。",
    )
    quality.append("当前状态：{}。".format(dimension["status_zh"]))
    conditions = [
        "已执行 OECF 光度响应校正，并采用统一 ROI 数据进行分析。",
        "OECF 主要用于描述扫描采集链路的光电响应特性，其本身不作为被测印刷样品的质量扣分项。",
    ]
    print_factors = [
        "若需评价印刷品本身的灰阶复制，应结合灰阶测试卡状态、扫描曝光条件及 RGB 通道一致性。",
        "当前数据未建立设备、纸张和测试条件对应的历史参考范围，暂不据此直接归因印刷设备。",
    ]
    improvement = [
        "建议结合灰阶目标值、重复测量和不同通道间的一致性，对灰阶复制稳定性进行量化评价。",
        "如后续批次数据积累后，可建立历史基线用于识别灰阶响应变化趋势。",
    ]
    return {
        "measured": measured,
        "quality": quality,
        "conditions": conditions,
        "print_factors": print_factors,
        "improvement": improvement,
    }


def _build_mtf(sample, metrics, dimension):
    score = dimension.get("score")
    measured = []
    mtf50 = _basis_value(dimension, "MTF50")
    mtf20 = _basis_value(dimension, "MTF20")
    mtf10 = _basis_value(dimension, "MTF10")
    if mtf50:
        measured.append("经标准化处理后，系统细节保持能力综合记录：MTF50 = {}、MTF20 = {}、MTF10 = {}。".format(mtf50, mtf20 or "未提供", mtf10 or "未提供"))
    direction = _basis_value(dimension, "水平/垂直方向差异")
    if direction:
        measured.append("水平与垂直方向之间的细节再现差异约为 {}%。".format(direction))
    hf = _basis_value(dimension, "高频响应峰值")
    if hf:
        measured.append("高频响应峰值记录为 {}。".format(hf))
    quality = _quality_by_score(
        score,
        "经标准化处理后，样品在测试空间频率范围内保持较稳定的响应特征，说明当前印刷过程对边缘结构和细节信息具有较好的保持能力。",
        "经标准化处理后，样品整体细节再现能力处于可接受水平，但部分空间频率区域存在响应变化，细节保持能力仍可能受到印刷分辨率、墨点扩散或材料表面特性的影响。",
        "经标准化处理后，样品在中高空间频率区域的细节保持能力相对有限，细小结构和边缘过渡的稳定再现存在一定改善空间。",
        "经标准化处理后，样品在细节保持相关指标上的表现相对有限，细小线条、边缘过渡及高频结构的稳定再现能力存在较明显的改善空间。",
    )
    if direction:
        try:
            value = float(direction)
            if value < 5:
                quality.append("水平与垂直方向之间的细节再现差异较小，当前结果未显示明显的方向性响应不一致。")
            elif value < 15:
                quality.append("水平与垂直方向之间存在一定的细节再现差异，建议结合重复测量确认其稳定性。")
            else:
                quality.append("水平与垂直方向之间存在较明显的细节再现差异，建议检查走纸方向、成像方向、墨点扩散及材料传输稳定性等因素。")
        except ValueError:
            quality.append("检测到水平与垂直方向存在差异，建议结合重复测量确认其稳定性。")
    quality.append("当前状态：{}。".format(dimension["status_zh"]))
    conditions = [
        "质量指标计算前已执行 OECF 光度响应校正、Scanner MTF 测量及空间响应补偿，并采用统一 ROI 进行分析。",
        "细节与清晰度评价反映标准化处理条件下被测样品的细节再现特征，而非扫描系统自身的空间响应表现。",
    ]
    print_factors = [
        "有效成像分辨率",
        "墨点扩散或网点增益控制",
        "材料吸收与表面特性",
        "走纸方向与成像方向的一致性",
    ]
    improvement = []
    if score is not None and score < 70:
        improvement.append("后续优化应优先关注印刷过程本身的细节复制能力，包括有效成像分辨率、墨点扩散控制、材料吸收特性及工艺参数匹配。")
    improvement.append("建议在相同测试条件下进行重复测量，并通过多 ROI 和方向性复测验证优化效果。")
    return {
        "measured": measured,
        "quality": quality,
        "conditions": conditions,
        "print_factors": print_factors,
        "improvement": improvement,
    }


def _build_character(sample, metrics, dimension):
    score = dimension.get("score")
    measured = []
    line_width = _metric_value(metrics, "line_width")
    target_width = _metric_value(metrics, "line_width_target")
    if line_width is not None:
        if target_width is not None and target_width > 0:
            delta = line_width - target_width
            ratio = delta / target_width * 100.0
            measured.append("当前测得线宽为 {:.4f} mm，相对标称线宽 {:.4f} mm 的偏差为 {:.4f} mm（{:.2f}%）。".format(line_width, target_width, delta, ratio))
        else:
            measured.append("当前测得线宽为 {:.4f} mm，未提供设计标称值或验收范围。".format(line_width))
    upper_transition = _metric_value(metrics, "edge_transition_width_upper")
    lower_transition = _metric_value(metrics, "edge_transition_width_lower")
    if upper_transition is not None and lower_transition is not None:
        measured.append("上、下边缘过渡宽度分别为 {:.4f} µm 和 {:.4f} µm。".format(upper_transition, lower_transition))
    upper_blur = _metric_value(metrics, "edge_blur_upper")
    lower_blur = _metric_value(metrics, "edge_blur_lower")
    if upper_blur is not None and lower_blur is not None:
        measured.append("上、下边缘模糊度分别为 {:.4f} 和 {:.4f}。".format(upper_blur, lower_blur))
    void_ratio = _metric_value(metrics, "character_void_ratio")
    mark_ratio = _metric_value(metrics, "character_mark_ratio")
    if void_ratio is not None:
        measured.append("字符空洞占比为 {:.4f}。".format(void_ratio))
    if mark_ratio is not None:
        measured.append("外来标记相关指标为 {:.4f}。".format(mark_ratio))
    fog_csa = _metric_text(metrics, "character_fog_csa")
    fog_r75 = _metric_text(metrics, "character_fog_r75")
    if fog_csa is not None and fog_r75 is not None:
        measured.append("雾影相关指标分别输出为 C.S.A = {} 和 R75 = {}。".format(fog_csa, fog_r75))
    quality = _quality_by_score(
        score,
        "当前字符与线条测量结果显示图形完整性较好，未发现明显空洞，边缘和尺寸复制整体稳定。",
        "当前字符与线条整体保持较完整，但部分边缘或局部标记需要结合原始图像进一步确认。",
        "当前字符与线条相关指标存在一定变化，尺寸或边缘复制稳定性需要进一步验证。",
        "当前字符与线条相关指标存在较明显变化，细小文字、线条边缘或图形完整性需要重点确认。",
    )
    if upper_transition is not None and lower_transition is not None:
        if lower_transition > upper_transition:
            quality.append("下边缘过渡区域相对更宽，当前边缘响应存在一定不对称性。")
        else:
            quality.append("上边缘过渡区域相对更宽，当前边缘响应存在一定不对称性。")
    if void_ratio is not None and void_ratio <= 0.02:
        quality.append("当前检测区域内未发现明显空洞；该结论仅适用于当前 ROI 和当前阈值条件。")
    if mark_ratio is not None and mark_ratio > 0:
        quality.append("外来标记响应可能来自真实印刷污染、纸张表面结构、扫描噪声或图像处理伪影，需结合缺陷位置图确认。")
    quality.append("当前状态：{}。".format(dimension["status_zh"]))
    conditions = [
        "采用统一 ROI 与标准化校正后的图像数据进行分析，当前阈值条件适用于本次测量。",
        "不同雾影指标采用不同的计算区域和阈值定义，不建议直接比较或相加。",
    ]
    print_factors = [
        "印刷扩散或网点增益",
        "墨量与供墨稳定性",
        "材料表面特性",
        "走纸或成像方向一致性",
        "图像处理阈值与二值化参数",
    ]
    improvement = [
        "建议核对测试图标称线宽，并结合不同方向和多位置重复测量判断偏差是否具有方向性。",
        "如偏差持续存在，可进一步检查印刷扩散、成像分辨率及材料适配性。",
        "建议结合缺陷位置图和原始图像区分真实印刷缺陷与测量伪影。",
    ]
    return {
        "measured": measured,
        "quality": quality,
        "conditions": conditions,
        "print_factors": print_factors,
        "improvement": improvement,
    }


def _build_large_area(sample, metrics, dimension):
    score = dimension.get("score")
    measured = []
    rmax = _metric_value(metrics, "rmax")
    rmin = _metric_value(metrics, "rmin")
    if rmax is not None and rmin is not None:
        measured.append("大面积反射率特征记录：Rmax = {:.4f}，Rmin = {:.4f}，反射率范围为 {:.4f}。".format(rmax, rmin, rmax - rmin))
    darkness = _metric_value(metrics, "large_area_darkness", "large_area_density")
    if darkness is not None:
        measured.append("大面积暗度记录为 {:.4f}。".format(darkness))
    void_ratio = _metric_value(metrics, "large_area_void_ratio")
    mark_ratio = _metric_value(metrics, "background_mark_ratio")
    if void_ratio is not None:
        measured.append("大面积空洞占比为 {:.4f}。".format(void_ratio))
    if mark_ratio is not None:
        measured.append("背景外来标记占比为 {:.4f}。".format(mark_ratio))
    quality = _quality_by_score(
        score,
        "当前大面积区域的亮度与反射率数据整体较稳定，均匀性趋势需结合历史基线进一步判断。",
        "当前大面积区域均匀性整体处于可接受水平，但局部区域存在一定变化趋势。",
        "当前大面积区域均匀性存在一定变化，局部反射率或空洞指标需要进一步确认。",
        "当前大面积区域均匀性存在较明显变化，亮度或反射率一致性需要重点改善。",
    )
    quality.append("当前状态：{}。".format(dimension["status_zh"]))
    conditions = [
        "采用统一 ROI 与标准化校正后的测量数据进行分析。",
        "不同 ROI 或不同样品的数据仅分别展示，不进行直接优劣比较。",
    ]
    print_factors = [
        "供墨均匀性",
        "介质平整度与表面特性",
        "扫描照明与测量条件",
        "材料吸收特性",
    ]
    improvement = [
        "建议增加多个 ROI 和重复测量，建立大面积均匀性的统计参考范围。",
        "如空洞或外来标记持续出现，建议结合原始图像区分真实缺陷与测量伪影。",
    ]
    return {
        "measured": measured,
        "quality": quality,
        "conditions": conditions,
        "print_factors": print_factors,
        "improvement": improvement,
    }


def _build_texture(sample, metrics, dimension):
    score = dimension.get("score")
    measured = []
    grain = _metric_value(metrics, "graininess")
    mottle = _metric_value(metrics, "mottle")
    if grain is not None:
        measured.append("Graininess 记录为 {:.4f}，用于表征测试区域内的高频亮度波动水平。".format(grain))
    if mottle is not None:
        measured.append("Mottle 记录为 {:.4f}，用于表征较大空间尺度上的亮度或密度不均匀现象。".format(mottle))
    quality = _quality_by_score(
        score,
        "当前纹理相关测量结果较稳定，可作为质量基线记录。",
        "当前纹理指标整体处于可接受范围，部分区域需要结合历史数据进一步确认。",
        "当前纹理指标存在一定变化，高频颗粒感或低频不均匀性需要进一步观察。",
        "当前纹理指标变化较明显，颗粒感或斑驳度需要重点确认。",
    )
    quality.append("当前状态：{}。".format(dimension["status_zh"]))
    conditions = [
        "采用统一 ROI 与标准化校正后的测量数据进行分析。",
        "当前尚未建立同类样品的历史参考范围，本次结果主要作为质量基线记录。",
    ]
    print_factors = [
        "材料表面微观结构",
        "墨层颗粒与成膜特性",
        "供墨均匀性",
        "测量系统噪声（已通过标准化校正降低影响）",
    ]
    improvement = [
        "建议通过重复扫描和多区域测量建立 Graininess / Mottle 的正常波动范围。",
        "后续批次可对比基线数据，用于识别颗粒度或斑驳度的异常变化。",
    ]
    return {
        "measured": measured,
        "quality": quality,
        "conditions": conditions,
        "print_factors": print_factors,
        "improvement": improvement,
    }


def _build_banding(sample, metrics, dimension):
    score = dimension.get("score")
    measured = []
    vertical = _metric_value(metrics, "vertical_banding")
    horizontal = _metric_value(metrics, "horizontal_banding")
    amplitude = _metric_value(metrics, "banding_amplitude")
    if vertical is not None or horizontal is not None:
        measured.append("条带指标记录：垂直条带评分 = {}，水平条带评分 = {}。".format(
            "--" if vertical is None else "{:.3f}".format(vertical),
            "--" if horizontal is None else "{:.3f}".format(horizontal),
        ))
    if amplitude is not None:
        measured.append("条带峰值幅度记录为 {:.3f}。".format(amplitude))
    quality = _quality_by_score(
        score,
        "当前条带相关测量结果较稳定，未观察到明显周期性响应。",
        "当前条带指标整体处于可接受范围，但存在一定周期性波动。",
        "当前条带指标存在一定变化，周期性条带需要结合频谱进一步确认。",
        "当前条带信号变化较明显，周期性条带控制需要重点改善。",
    )
    quality.append("当前状态：{}。".format(dimension["status_zh"]))
    conditions = [
        "采用统一 ROI 与标准化校正后的测量数据进行分析。",
        "垂直与水平条带采用各自的测量方向和计算方式，应分别查看。",
    ]
    print_factors = [
        "供墨或供粉周期",
        "走纸或介质传输稳定性",
        "机械传动周期",
        "喷头或印版周期",
    ]
    improvement = [
        "建议结合频谱分析、原始图像和方向性复测确认条带来源。",
        "如条带持续存在，可进一步检查供墨、走纸和机械传动环节。",
    ]
    return {
        "measured": measured,
        "quality": quality,
        "conditions": conditions,
        "print_factors": print_factors,
        "improvement": improvement,
    }


def build_module_explanation(sample, module, dimension):
    metrics = [item for item in sample.get("metrics", []) if item.get("module") == module]
    builders = {
        "oecf": _build_oecf,
        "mtf": _build_mtf,
        "character_line": _build_character,
        "large_area": _build_large_area,
        "texture": _build_texture,
        "banding": _build_banding,
    }
    builder = builders.get(module)
    if builder is None:
        return {
            "summary": dimension.get("summary", "当前模块测量结果已记录。"),
            "result": ["当前模块已完成数据解析，但未配置专项解释规则。"],
            "interpretation": [dimension.get("summary", "当前模块测量结果已记录。")],
            "measurement_note": ["当前结果基于本次上传的测量数据生成。"],
            "diagnosis": [],
            "recommendation": ["建议补充专项测量或历史基线后重新评估。"],
        }
    raw = builder(sample, metrics, dimension)
    quality = raw.get("quality", [])
    measured = raw.get("measured", [])
    conditions = raw.get("conditions", [])
    print_factors = raw.get("print_factors", [])
    improvement = raw.get("improvement", [])
    score = dimension.get("score")
    status = dimension.get("status", "missing")
    status_zh = dimension.get("status_zh", "已记录")

    diagnosis = []
    if score is not None and (score < 70 or status in ("attention", "warning", "danger")):
        diagnosis.append("当前模块评分为 {}，状态为 {}，需要结合具体指标和重复测量进一步确认。".format(score, status_zh))
        if print_factors:
            diagnosis.append("可能影响因素包括：{}。".format("、".join(print_factors)))
    elif score is None:
        diagnosis.append("当前数据仅作为测量记录，评分条件不足，不进行综合质量等级判定。")

    recommendation = improvement
    if score is not None and score >= 85 and module in ("mtf", "character_line", "large_area", "banding"):
        recommendation = []
    if score is None:
        recommendation = ["建议补充有效测量数据或历史基线后重新评估。"]

    return {
        "summary": quality[0] if quality else dimension.get("summary", "当前模块测量结果已记录。"),
        "result": measured,
        "interpretation": quality,
        "measurement_note": conditions,
        "diagnosis": diagnosis,
        "recommendation": recommendation,
    }
