# -*- coding: utf-8 -*-
"""File recognition and normalization for ISOPrint Inspector uploads."""

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field

from metrics_catalog import (
    GENERIC_IGNORED_KEYS,
    MODULE_CONTAINER_KEYS,
    MODULE_ZH,
    SAMPLE_INFO_KEYS,
    find_module_for_key,
    metric_definition,
    normalize_key,
    resolve_metric,
)

SUPPORTED_EXTS = {".json", ".txt", ".csv", ".tsv", ".dat", ".xlsx", ".xls"}

CURVE_X_KEYS = {
    "x",
    "freq",
    "frequency",
    "frequencies",
    "input",
    "step",
    "gray",
    "greylevel",
    "density",
    "reflectance",
    "cyclespermm",
    "lpmm",
    "spatialfrequency",
    "position",
}
CURVE_Y_KEYS = {
    "y",
    "mtf",
    "response",
    "responses",
    "output",
    "reflectance",
    "density",
    "od",
    "value",
    "values",
    "oecf",
    "amplitude",
}


@dataclass
class ParsedFile:
    filename: str
    ext: str = ""
    format: str = ""
    ok: bool = True
    error: str = ""
    sample_info: dict = field(default_factory=dict)
    metrics: list = field(default_factory=list)
    curves: list = field(default_factory=list)
    provided_scores: dict = field(default_factory=dict)
    provided_diagnosis: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def parse_file(filename, content):
    ext = filename[filename.rfind("."):].lower() if "." in filename else ""
    parsed = ParsedFile(filename=filename, ext=ext)
    if ext not in SUPPORTED_EXTS:
        parsed.ok = False
        parsed.error = "不支持的文件类型，请上传 JSON / XLSX / TXT / CSV / DAT"
        return parsed
    parsed.ext = ext
    try:
        if ext == ".json":
            parsed.format = "json"
            _parse_json(content, parsed)
        elif ext == ".xlsx":
            parsed.format = "xlsx"
            _parse_xlsx(content, parsed)
        elif ext == ".xls":
            parsed.ok = False
            parsed.error = "暂不支持旧版 .xls，请另存为 .xlsx 后重新上传"
            return parsed
        else:
            parsed.format = "text"
            _parse_text(content, parsed)
    except Exception as exc:  # noqa: BLE001 - parser should isolate bad files
        parsed.ok = False
        parsed.error = "解析失败：{}".format(exc)
    return parsed


def _decode(content):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _to_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "").replace("％", "")
        if not text:
            return None
        try:
            num = float(text)
            if math.isnan(num) or math.isinf(num):
                return None
            return num
        except ValueError:
            return None
    return None


def _scalar_string(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _sample_info_keys():
    out = {}
    for field_name, aliases in SAMPLE_INFO_KEYS.items():
        for alias in aliases:
            out[normalize_key(alias)] = field_name
    return out


_SAMPLE_INFO_LOOKUP = _sample_info_keys()


def _add_sample_info(parsed, key, value):
    norm = normalize_key(key)
    field_name = _SAMPLE_INFO_LOOKUP.get(norm)
    if not field_name:
        return False
    if field_name in parsed.sample_info:
        return True
    text = _scalar_string(value)
    if text:
        parsed.sample_info[field_name] = text
    return True


def _extract_sample_info(parsed, obj):
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        norm = normalize_key(key)
        if norm in _SAMPLE_INFO_LOOKUP:
            if isinstance(value, dict):
                _extract_sample_info(parsed, value)
            elif isinstance(value, list):
                if value and all(not isinstance(item, (dict, list)) for item in value):
                    text = _scalar_string(value[0])
                    if text:
                        parsed.sample_info.setdefault(_SAMPLE_INFO_LOOKUP[norm], text)
            else:
                _add_sample_info(parsed, key, value)
        elif key in ("sample_info", "report_info", "batch_info", "metadata", "meta"):
            _extract_sample_info(parsed, value)


def _is_curve_pair(value):
    if not isinstance(value, list) or len(value) < 2:
        return False
    return all(
        isinstance(item, (list, tuple))
        and len(item) >= 2
        and _to_number(item[0]) is not None
        and _to_number(item[1]) is not None
        for item in value
    )


def _curve_name(context, key):
    if context == "oecf":
        return "OECF 灰阶响应曲线"
    if context == "mtf":
        return "MTF 响应曲线"
    if context == "banding":
        return "条带频谱曲线"
    label = MODULE_ZH.get(context, str(key))
    return "{} 曲线".format(label)


def _add_curve(parsed, module, name, x_values, y_values, source_key):
    if not x_values or not y_values or len(x_values) != len(y_values):
        return False
    points = []
    for xv, yv in zip(x_values, y_values):
        x = _to_number(xv)
        y = _to_number(yv)
        if x is not None and y is not None:
            points.append([x, y])
    if len(points) >= 2:
        parsed.curves.append(
            {
                "module": module,
                "name": name,
                "x_label": "频率" if module == "mtf" else ("输入灰阶" if module == "oecf" else "横轴"),
                "y_label": "MTF" if module == "mtf" else ("输出密度/反射率" if module == "oecf" else "纵轴"),
                "points": points,
                "source_file": parsed.filename,
                "source_key": source_key,
            }
        )
        return True
    return False


def _add_oecf_matrix(parsed, rows, source_key):
    matrix = []
    for row in rows:
        nums = [_to_number(cell) for cell in row]
        nums = [num for num in nums if num is not None]
        if len(nums) >= 2:
            matrix.append(nums)
    if len(matrix) < 20:
        return False
    channel_count = min(len(matrix[0]), 6)
    if len(matrix) >= 512:
        matrix = matrix[:256]
    channels = [[] for _ in range(channel_count)]
    average = []
    for index, row in enumerate(matrix):
        values = row[:channel_count]
        avg = sum(values) / len(values)
        average.append([index, avg])
        for col in range(channel_count):
            channels[col].append([index, values[col]])
    mean_curve = {
        "module": "oecf",
        "name": "OECF Rvis 均值",
        "x_label": "扫描位置 / 灰阶步",
        "y_label": "视觉反射率 Rvis",
        "points": average,
        "source_file": parsed.filename,
        "source_key": source_key,
        "display": False,
        "note": "RGB→Rvis（前 256 行）",
    }
    parsed.curves.append(mean_curve)
    channel_names = ["R 通道", "G 通道", "B 通道", "通道 4", "通道 5", "通道 6"]
    for col, points in enumerate(channels):
        parsed.curves.append(
            {
                "module": "oecf",
                "name": channel_names[col],
                "x_label": "扫描位置 / 灰阶步",
                "y_label": "视觉反射率 Rvis",
                "points": points,
                "source_file": parsed.filename,
                "source_key": source_key,
                "display": True,
                "note": "RGB→Rvis（前 256 行）",
            }
        )
    return True


def _parse_mtf_text_table(parsed, text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    header = lines[0].replace("\t", " ").split()
    if not header or header[0].upper() != "SF" or len(header) < 3:
        return False
    prefix = "Target MTF" if "target" in parsed.filename.lower() else "Scanner MTF"
    columns = {index: [] for index in range(1, len(header))}
    for line in lines[1:]:
        cells = line.replace("\t", " ").split()
        if len(cells) < len(header):
            continue
        x = _to_number(cells[0])
        if x is None:
            continue
        for index in range(1, len(header)):
            y = _to_number(cells[index])
            if y is not None:
                columns[index].append([x, y])
    added = False
    for index in range(1, len(header)):
        if len(columns[index]) >= 2:
            parsed.curves.append(
                {
                    "module": "mtf",
                    "name": "{} {}".format(prefix, header[index]),
                    "x_label": "空间频率 (lp/mm)",
                    "y_label": "MTF",
                    "points": columns[index],
                    "source_file": parsed.filename,
                    "source_key": "mtf_table",
                }
            )
            added = True
    return added


def _parse_banding_text_table(parsed, text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    header = lines[0].split("\t") if "\t" in lines[0] else lines[0].split()
    lowered = [cell.lower() for cell in header]
    vertical_index = next(
        (index for index, cell in enumerate(lowered) if "vertical" in cell and "score" in cell),
        None,
    )
    horizontal_index = next(
        (index for index, cell in enumerate(lowered) if "horizontal" in cell and "score" in cell),
        None,
    )
    if vertical_index is None and horizontal_index is None:
        return False
    added = False
    for line in lines[1:]:
        cells = line.split("\t") if "\t" in line else line.split()
        if vertical_index is not None and len(cells) > vertical_index:
            value = _to_number(cells[vertical_index])
            if value is not None:
                _record_metric(parsed, "vertical_score", value, "banding", sample_id=parsed.sample_info.get("sample_id", ""))
                added = True
        if horizontal_index is not None and len(cells) > horizontal_index:
            value = _to_number(cells[horizontal_index])
            if value is not None:
                _record_metric(parsed, "horizontal_score", value, "banding", sample_id=parsed.sample_info.get("sample_id", ""))
                added = True
    return added


def _extract_curve_value(parsed, key, value, context):
    module = find_module_for_key(key) or context
    if module not in ("oecf", "mtf", "banding"):
        return False
    name = _curve_name(module, key)
    if isinstance(value, list) and _is_curve_pair(value):
        x_values = [item[0] for item in value]
        y_values = [item[1] for item in value]
        return _add_curve(parsed, module, name, x_values, y_values, key)
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        first = value[0]
        x_key = next((k for k in CURVE_X_KEYS if k in first), None)
        y_key = next((k for k in CURVE_Y_KEYS if k in first), None)
        if x_key is None:
            x_key = next((k for k in first if normalize_key(k) in CURVE_X_KEYS), None)
        if y_key is None:
            y_key = next((k for k in first if normalize_key(k) in CURVE_Y_KEYS), None)
        if x_key and y_key:
            x_values = [item.get(x_key) for item in value]
            y_values = [item.get(y_key) for item in value]
            return _add_curve(parsed, module, name, x_values, y_values, key)
        if len(first) >= 2:
            x_values = [list(item.values())[0] if isinstance(item, dict) else None for item in value]
            y_values = [list(item.values())[1] if isinstance(item, dict) else None for item in value]
            return _add_curve(parsed, module, name, x_values, y_values, key)
        return False
    if isinstance(value, dict):
        x_key = next((k for k in CURVE_X_KEYS if normalize_key(k) in {normalize_key(x) for x in value.keys()}), None)
        y_key = next((k for k in CURVE_Y_KEYS if normalize_key(k) in {normalize_key(y) for y in value.keys()}), None)
        if x_key is None and y_key is None:
            return False
        x_values = value.get(x_key) if x_key else []
        y_values = value.get(y_key) if y_key else []
        if isinstance(x_values, dict) and "values" in x_values:
            x_values = x_values["values"]
        if isinstance(y_values, dict) and "values" in y_values:
            y_values = y_values["values"]
        if not isinstance(x_values, (list, tuple)) or not isinstance(y_values, (list, tuple)):
            return False
        if x_values and not y_values:
            y_values = x_values
            x_values = list(range(1, len(y_values) + 1))
        if y_values and not x_values:
            x_values = list(range(1, len(y_values) + 1))
        return _add_curve(parsed, module, name, x_values, y_values, key)
    return False


def _extract_provided_scores(parsed, obj):
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        norm = normalize_key(key)
        if norm in ("overallscore", "oqi", "total", "total_score"):
            num = _to_number(value)
            if num is not None:
                parsed.provided_scores["overall"] = num
        elif norm in ("score", "scores"):
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    sub_norm = normalize_key(sub_key)
                    if sub_norm in ("overall", "overallscore", "oqi", "total"):
                        num = _to_number(sub_value)
                        if num is not None:
                            parsed.provided_scores["overall"] = num
                            continue
                    module = find_module_for_key(sub_key)
                    if module:
                        num = _to_number(sub_value)
                        if num is not None:
                            parsed.provided_scores[module] = num
        elif norm == "dimensionscores" and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                module = find_module_for_key(sub_key)
                if not module:
                    continue
                if isinstance(sub_value, dict):
                    num = _to_number(sub_value.get("score"))
                    status = _scalar_string(sub_value.get("status"))
                    if num is not None:
                        parsed.provided_scores[module] = num
                    if status:
                        parsed.provided_scores[module + "_status"] = status
                else:
                    num = _to_number(sub_value)
                    if num is not None:
                        parsed.provided_scores[module] = num
        elif norm == "overallresult" and isinstance(value, dict):
            num = _to_number(value.get("score"))
            if num is not None:
                parsed.provided_scores["overall"] = num
            status = _scalar_string(value.get("status"))
            if status:
                parsed.provided_scores["overall_status"] = status
            summary = _scalar_string(value.get("summary"))
            if summary:
                parsed.provided_scores["overall_summary"] = summary


def _extract_provided_diagnosis(parsed, value):
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, dict):
            parsed.provided_diagnosis.append(item)


def _record_metric(parsed, key, value, context, unit=None, notes=None, status=None, sample_id=None):
    canonical, module = resolve_metric(key, context)
    if not canonical:
        return False
    if context and module != context:
        return False
    num = _to_number(value)
    text = _scalar_string(value)
    definition = metric_definition(canonical)
    if definition and definition[0] != module:
        module = definition[0]
    if num is None and not text:
        return False
    parsed.metrics.append(
        {
            "module": module,
            "key": canonical,
            "zh": definition[1] if definition else canonical,
            "value": num if num is not None else text,
            "unit": unit or (definition[2] if definition else ""),
            "status": status or "",
            "notes": notes or "",
            "source_file": parsed.filename,
            "source_key": key,
            "sample_id": sample_id or "",
        }
    )
    return True


def _extract_defect_from_character_quality(parsed, obj):
    if not isinstance(obj, dict):
        return
    mapping = {
        "voidratio": "defect_void_ratio",
        "extraneousmarkratio": "defect_mark_ratio",
        "csahaze": "defect_fog_csa",
        "r75haze": "defect_fog_r75",
        "字符空洞占比": "defect_void_ratio",
        "外来标记占比": "defect_mark_ratio",
        "雾影占比csa": "defect_fog_csa",
        "雾影占比r75": "defect_fog_r75",
    }
    for key, value in obj.items():
        canonical = mapping.get(normalize_key(key))
        if canonical:
            _record_metric(
                parsed,
                canonical,
                value,
                "defect",
                sample_id=parsed.sample_info.get("sample_id", ""),
            )


def _extract_metrics(parsed, obj, context=None, path=None):
    if isinstance(obj, dict):
        for key, value in obj.items():
            norm = normalize_key(key)
            if norm in GENERIC_IGNORED_KEYS and not isinstance(value, (dict, list)):
                continue
            if norm in _SAMPLE_INFO_LOOKUP or key in ("sample_info", "report_info", "batch_info", "metadata"):
                continue
            if norm in ("scores", "dimensionscores"):
                _extract_provided_scores(parsed, value)
                continue
            if norm in ("overallresult", "overall_result"):
                _extract_provided_scores(parsed, {norm: value})
                _extract_sample_info(parsed, value)
                continue
            if norm == "diagnosis":
                _extract_provided_diagnosis(parsed, value)
                continue
            if isinstance(value, dict):
                if "value" in value and _to_number(value.get("value")) is not None:
                    canonical, module = resolve_metric(key, context)
                    if canonical:
                        _record_metric(
                            parsed,
                            key,
                            value.get("value"),
                            context,
                            unit=_scalar_string(value.get("unit")),
                            notes=_scalar_string(value.get("note") or value.get("description")),
                            status=_scalar_string(value.get("status")),
                            sample_id=parsed.sample_info.get("sample_id", ""),
                        )
                        continue
                module = find_module_for_key(key) or context
                if _extract_curve_value(parsed, key, value, module):
                    continue
                if norm in ("characterquality", "character_quality"):
                    _extract_metrics(parsed, value, context=module, path=path + [key] if path else [key])
                    _extract_defect_from_character_quality(parsed, value)
                    continue
                if module != context and module is not None:
                    _extract_metrics(parsed, value, context=module, path=path + [key] if path else [key])
                else:
                    _extract_metrics(parsed, value, context=context, path=path + [key] if path else [key])
            elif isinstance(value, list):
                if norm in (
                    "repeatvalues",
                    "repeatmeasurements",
                    "repeatedvalues",
                    "repeatedmeasurements",
                    "重复测量值",
                    "重复测量",
                ) and len(value) >= 3:
                    numbers = [num for num in (_to_number(item) for item in value) if num is not None]
                    if len(numbers) >= 3:
                        mean = sum(numbers) / len(numbers)
                        variance = sum((num - mean) ** 2 for num in numbers) / (len(numbers) - 1)
                        std = math.sqrt(variance)
                        cv = std / abs(mean) * 100.0 if mean else 0.0
                        _record_metric(
                            parsed,
                            "repeatability_mean",
                            mean,
                            "repeatability",
                            sample_id=parsed.sample_info.get("sample_id", ""),
                        )
                        _record_metric(
                            parsed,
                            "repeatability_std",
                            std,
                            "repeatability",
                            sample_id=parsed.sample_info.get("sample_id", ""),
                        )
                        _record_metric(
                            parsed,
                            "repeatability_cv",
                            cv,
                            "repeatability",
                            sample_id=parsed.sample_info.get("sample_id", ""),
                        )
                        continue
                module = find_module_for_key(key) or context
                if _extract_curve_value(parsed, key, value, module):
                    continue
                nums = [_to_number(item) for item in value]
                if len(nums) == 1 and nums[0] is not None:
                    _record_metric(parsed, key, nums[0], context, sample_id=parsed.sample_info.get("sample_id", ""))
                elif len(value) > 1 and all(isinstance(item, dict) for item in value):
                    inner_curves = [
                        item
                        for item in value
                        if isinstance(item, dict)
                        and ("x" in item or "frequency" in item or "input" in item or "freq" in item)
                        and ("y" in item or "mtf" in item or "response" in item or "output" in item)
                    ]
                    if inner_curves:
                        _extract_curve_value(parsed, key, inner_curves, module)
                elif len(value) > 1 and _is_curve_pair(value):
                    _extract_curve_value(parsed, key, value, module)
            else:
                if _add_sample_info(parsed, key, value):
                    continue
                _record_metric(
                    parsed,
                    key,
                    value,
                    context,
                    sample_id=parsed.sample_info.get("sample_id", ""),
                )
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            _extract_metrics(parsed, item, context=context, path=path + [str(index)] if path else [str(index)])


def _parse_json(content, parsed):
    text = _decode(content)
    obj = json.loads(text)
    _extract_sample_info(parsed, obj)
    _extract_provided_scores(parsed, obj)
    _extract_metrics(parsed, obj)
    if not parsed.metrics and not parsed.curves:
        parsed.ok = False
        parsed.error = "JSON 中未识别到 OECF / MTF / 字符线条 / 大面积 / 纹理 / 条带 / 缺陷等指标数据"


def _detect_text_module(line):
    cleaned = line.strip().strip("[]:-= ")
    if not cleaned or len(cleaned) > 40:
        return None
    return find_module_for_key(cleaned)


def _parse_text_table_line(parsed, line, context):
    if "\t" in line:
        cells = [c.strip() for c in line.split("\t") if c.strip()]
    elif line.count(",") > 0:
        cells = [c.strip() for c in line.split(",") if c.strip()]
    else:
        cells = line.split()
    nums = [_to_number(c) for c in cells]
    if context in ("oecf", "mtf", "banding") and sum(1 for n in nums if n is not None) >= 2:
        points = [[x, y] for x, y in zip(nums, nums[1:]) if x is not None and y is not None]
        if points:
            parsed.curves.append(
                {
                    "module": context,
                    "name": _curve_name(context, ""),
                    "x_label": "频率" if context == "mtf" else "输入灰阶",
                    "y_label": "MTF" if context == "mtf" else "输出",
                    "points": points,
                    "source_file": parsed.filename,
                    "source_key": "text_table",
                }
            )
    elif len(cells) >= 2:
        _record_metric(
            parsed,
            cells[0],
            cells[1],
            context,
            unit=cells[2] if len(cells) > 2 else "",
            sample_id=parsed.sample_info.get("sample_id", ""),
        )


def _parse_csv_text(content, parsed):
    text = _decode(content)
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return
    header = [cell.strip() for cell in rows[0]]
    known_headers = 0
    header_meta = []
    for cell in header:
        canonical, module = resolve_metric(cell)
        if canonical:
            known_headers += 1
            header_meta.append((cell, canonical, module))
    if known_headers < 2:
        if _add_oecf_matrix(parsed, rows, "csv_matrix"):
            return
        _parse_text_plain(content, parsed)
        return
    for row in rows[1:]:
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        for index, cell in enumerate(header):
            if index >= len(header_meta):
                continue
            _, canonical, module = header_meta[index]
            value = row[index].strip()
            num = _to_number(value)
            if num is None:
                continue
            definition = metric_definition(canonical)
            parsed.metrics.append(
                {
                    "module": module,
                    "key": canonical,
                    "zh": definition[1] if definition else canonical,
                    "value": num,
                    "unit": definition[2] if definition else "",
                    "status": "",
                    "notes": "",
                    "source_file": parsed.filename,
                    "source_key": cell,
                    "sample_id": parsed.sample_info.get("sample_id", ""),
                }
            )


def _parse_text(content, parsed):
    text = _decode(content)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "," in first_line:
        _parse_csv_text(content, parsed)
    else:
        _parse_text_plain(content, parsed)


def _parse_text_plain(content, parsed):
    text = _decode(content)
    if _parse_mtf_text_table(parsed, text):
        return
    if _parse_banding_text_table(parsed, text):
        return
    context = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        module = _detect_text_module(line)
        if module is not None:
            context = module
            continue
        if "\t" in line or line.count(",") > 0:
            _parse_text_table_line(parsed, line, context)
            continue
        key, value = line, ""
        for sep in ("=", ":", "："):
            if sep in line:
                key, value = line.split(sep, 1)
                break
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if not value:
            words = line.split()
            if len(words) >= 2:
                key, value = words[0], " ".join(words[1:])
        if _add_sample_info(parsed, key, value):
            continue
        if context:
            _record_metric(parsed, key, value, context, sample_id=parsed.sample_info.get("sample_id", ""))
        else:
            canonical, module = resolve_metric(key)
            if canonical:
                _record_metric(parsed, key, value, module, sample_id=parsed.sample_info.get("sample_id", ""))
    if not parsed.metrics and not parsed.curves:
        parsed.ok = False
        parsed.error = "TXT/CSV 中未识别到测试指标，请确认包含 OECF / MTF / 字符 / 均匀性 / 纹理 / 条带等字段"


def _xlsx_rows(sheet, max_rows=5000):
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append(["" if cell is None else cell for cell in row])
        if len(rows) >= max_rows:
            break
    return rows


def _xlsx_context(rows):
    candidates = []
    for row in rows[:8]:
        for cell in row:
            if isinstance(cell, str):
                module = _detect_text_module(cell)
                if module:
                    candidates.append(module)
    return candidates[0] if candidates else None


def _xlsx_table_mode(rows, context):
    if not rows:
        return False, []
    for row in rows[:8]:
        hits = 0
        meta = []
        for cell in row:
            if isinstance(cell, str):
                canonical, module = resolve_metric(cell, context)
                if canonical:
                    hits += 1
                    meta.append((cell, canonical, module))
        if hits >= 2:
            return True, meta
    return False, []


def _xlsx_category_table_mode(rows):
    if not rows:
        return False
    for row in rows[:3]:
        normalized = [normalize_key(str(cell)) for cell in row if cell is not None]
        has_category = any(value in normalized for value in ("category", "类别"))
        has_metric = any(value in normalized for value in ("metric", "参数", "指标"))
        has_value = any(value in normalized for value in ("value", "值", "数值"))
        if has_category and has_metric and has_value:
            return True
    return False


def _xlsx_numeric_matrix_rows(rows):
    if len(rows) < 50:
        return False
    first = rows[0]
    if not first:
        return False
    nums = [_to_number(cell) for cell in first]
    return len(nums) >= 2 and all(num is not None for num in nums)


def _parse_xlsx_category_rows(parsed, rows):
    for row in rows[1:]:
        if len(row) < 3:
            continue
        category = str(row[0] or "").strip()
        metric = str(row[1] or "").strip()
        value = row[2]
        unit = row[3] if len(row) > 3 else ""
        if not metric:
            continue
        if category in ("元数据", "Metadata"):
            _add_sample_info(parsed, metric, value)
            continue
        module = find_module_for_key(category)
        if module:
            _record_metric(
                parsed,
                metric,
                value,
                module,
                unit=unit if isinstance(unit, str) else "",
                sample_id=parsed.sample_info.get("sample_id", ""),
            )
            if normalize_key(category) in ("characterquality", "字符质量"):
                _extract_defect_from_character_quality(parsed, {metric: value})
        else:
            _record_metric(
                parsed,
                metric,
                value,
                None,
                unit=unit if isinstance(unit, str) else "",
                sample_id=parsed.sample_info.get("sample_id", ""),
            )


def _parse_xlsx(content, parsed):
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    for sheet in workbook.worksheets:
        rows = _xlsx_rows(sheet)
        context = _xlsx_context(rows) or find_module_for_key(sheet.title)
        if _xlsx_category_table_mode(rows):
            _parse_xlsx_category_rows(parsed, rows)
            continue
        if not context and _xlsx_numeric_matrix_rows(rows):
            _add_oecf_matrix(parsed, rows, "xlsx_matrix")
            continue
        table_mode, header_meta = _xlsx_table_mode(rows, context)
        if table_mode:
            header = [cell for cell in rows[0] if isinstance(cell, str)]
            for row in rows[1:]:
                for index, (cell, canonical, module) in enumerate(header_meta):
                    value = row[index] if index < len(row) else ""
                    num = _to_number(value)
                    if num is None:
                        continue
                    definition = metric_definition(canonical)
                    parsed.metrics.append(
                        {
                            "module": module,
                            "key": canonical,
                            "zh": definition[1] if definition else canonical,
                            "value": num,
                            "unit": definition[2] if definition else "",
                            "status": "",
                            "notes": "",
                            "source_file": parsed.filename,
                            "source_key": cell,
                            "sample_id": parsed.sample_info.get("sample_id", ""),
                        }
                    )
            continue
        for row in rows:
            if not row:
                continue
            first = row[0]
            second = row[1] if len(row) > 1 else ""
            if isinstance(first, str) and first.strip():
                module = _detect_text_module(first)
                if module:
                    context = module
                    continue
                if _add_sample_info(parsed, first, second):
                    continue
                if context and _to_number(second) is not None:
                    unit = row[2] if len(row) > 2 and isinstance(row[2], str) else ""
                    status = row[3] if len(row) > 3 and isinstance(row[3], str) else ""
                    _record_metric(
                        parsed,
                        first,
                        second,
                        context,
                        unit=unit,
                        status=status,
                        sample_id=parsed.sample_info.get("sample_id", ""),
                    )
                elif _to_number(second) is not None:
                    _record_metric(
                        parsed,
                        first,
                        second,
                        None,
                        sample_id=parsed.sample_info.get("sample_id", ""),
                    )
            elif isinstance(first, (int, float)) and _to_number(second) is not None and context:
                if context in ("oecf", "mtf", "banding"):
                    parsed.curves.append(
                        {
                            "module": context,
                            "name": _curve_name(context, ""),
                            "x_label": "频率" if context == "mtf" else "输入灰阶",
                            "y_label": "MTF" if context == "mtf" else "输出",
                            "points": [[_to_number(first), _to_number(second)]],
                            "source_file": parsed.filename,
                            "source_key": "xlsx_table",
                        }
                    )
    if not parsed.metrics and not parsed.curves:
        parsed.ok = False
        parsed.error = "XLSX 中未识别到测试指标，请确认工作表包含 OECF / MTF / 字符 / 均匀性 / 纹理 / 条带等字段"
