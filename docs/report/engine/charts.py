# -*- coding: utf-8 -*-
"""Inline SVG chart generation for ISOPrint Inspector reports."""

import html
import math

from metrics_catalog import ACTIVE_MODULE_ORDER, MODULE_OVERVIEW_ZH


def _fmt_tick(value):
    if value is None:
        return ""
    if abs(value) >= 100:
        return str(int(round(value)))
    if abs(value) >= 10:
        return "{:.1f}".format(value)
    return "{:.2f}".format(value)


def line_chart(series, title="", x_label="", y_label="", width=760, height=360, y_min=None, y_max=None):
    clean_series = []
    for item in series:
        points = []
        for pair in item.get("points", []):
            try:
                x = float(pair[0])
                y = float(pair[1])
            except (TypeError, ValueError):
                continue
            if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
                continue
            points.append((x, y))
        if len(points) >= 2:
            clean_series.append({"name": item.get("name", ""), "color": item.get("color", "#2563eb"), "points": points})
    if not clean_series:
        return None
    all_x = [x for item in clean_series for x, _ in item["points"]]
    all_y = [y for item in clean_series for _, y in item["points"]]
    x_min, x_max = min(all_x), max(all_x)
    fixed_y = y_min is not None and y_max is not None
    y_min = min(all_y) if y_min is None else y_min
    y_max = max(all_y) if y_max is None else y_max
    if x_min == x_max:
        x_min -= 1
        x_max += 1
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    x_pad = max((x_max - x_min) * 0.04, 0.1)
    y_pad = 0.0 if fixed_y else max((y_max - y_min) * 0.08, 0.1)
    x_min -= x_pad
    x_max += x_pad
    if not fixed_y:
        y_min -= y_pad
        y_max += y_pad
    legend_width = 190
    margin = {"left": 64, "right": 18 + legend_width, "top": 44, "bottom": 54}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    def sx(x):
        return margin["left"] + (x - x_min) / (x_max - x_min) * plot_w

    def sy(y):
        return margin["top"] + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{title}">'.format(w=width, h=height, title=html.escape(title)))
    parts.append('<rect x="0" y="0" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="#e5e7eb"/>'.format(w=width, h=height))
    grid_x = 5
    grid_y = 4
    for index in range(grid_x + 1):
        x = x_min + (x_max - x_min) * index / grid_x
        px = sx(x)
        parts.append(
            '<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#eef1f5" stroke-width="1"/>'.format(
                x1=px, y1=margin["top"], x2=px, y2=margin["top"] + plot_h
            )
        )
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#8a94a6" font-size="11" text-anchor="middle">{label}</text>'.format(
                x=px, y=margin["top"] + plot_h + 18, label=html.escape(_fmt_tick(x))
            )
        )
    for index in range(grid_y + 1):
        y = y_min + (y_max - y_min) * index / grid_y
        py = sy(y)
        parts.append(
            '<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#eef1f5" stroke-width="1"/>'.format(
                x1=margin["left"], y1=py, x2=margin["left"] + plot_w, y2=py
            )
        )
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#8a94a6" font-size="11" text-anchor="end">{label}</text>'.format(
                x=margin["left"] - 8, y=py + 4, label=html.escape(_fmt_tick(y))
            )
        )
    if title:
        parts.append(
            '<text x="{x:.1f}" y="24" fill="#1f2937" font-size="14" font-weight="600">{title}</text>'.format(
                x=margin["left"], title=html.escape(title)
            )
        )
    parts.append(
        '<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#cbd5e1" stroke-width="1.2"/>'.format(
            x1=margin["left"], y1=margin["top"] + plot_h, x2=margin["left"] + plot_w, y2=margin["top"] + plot_h
        )
    )
    parts.append(
        '<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#cbd5e1" stroke-width="1.2"/>'.format(
            x1=margin["left"], y1=margin["top"], x2=margin["left"], y2=margin["top"] + plot_h
        )
    )
    legend_x = margin["left"] + plot_w + 20
    legend_y_start = margin["top"] + 8
    for index, item in enumerate(clean_series):
        parts.append(
            '<rect x="{x:.1f}" y="{y:.1f}" width="12" height="12" rx="3" fill="{color}"/>'.format(
                x=legend_x, y=legend_y_start + index * 28, color=item["color"]
            )
        )
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#374151" font-size="12">{name}</text>'.format(
                x=legend_x + 18, y=legend_y_start + index * 28 + 10, name=html.escape(item["name"])
            )
        )
    for item in clean_series:
        polyline = " ".join("{x:.1f},{y:.1f}".format(x=sx(x), y=sy(y)) for x, y in item["points"])
        parts.append(
            '<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'.format(
                points=polyline, color=item["color"]
            )
        )
        if len(item["points"]) <= 20:
            for x, y in item["points"]:
                parts.append(
                    '<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>'.format(
                        x=sx(x), y=sy(y), color=item["color"]
                    )
                )
    if x_label:
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#6b7280" font-size="12" text-anchor="middle">{label}</text>'.format(
                x=margin["left"] + plot_w / 2, y=height - 14, label=html.escape(x_label)
            )
        )
    if y_label:
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#6b7280" font-size="12" text-anchor="middle" transform="rotate(-90 {x:.1f} {y:.1f})">{label}</text>'.format(
                x=18, y=margin["top"] + plot_h / 2, label=html.escape(y_label)
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def radar_chart(items, width=560, height=440):
    scored = [item for item in items if item.get("score") is not None]
    if len(scored) < 3:
        return None
    cx = width / 2
    cy = height / 2 - 10
    radius = min(width, height) / 2 - 76
    n = len(scored)
    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="综合质量雷达图">'.format(w=width, h=height))
    parts.append('<rect x="0" y="0" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="#e5e7eb"/>'.format(w=width, h=height))
    parts.append('<text x="{x:.1f}" y="28" fill="#1f2937" font-size="14" font-weight="600" text-anchor="middle">综合质量雷达图</text>'.format(x=cx))
    grid_colors = ["#eef1f5", "#e3e8ef", "#d6dde7", "#c8d1de"]
    for grid_index, ratio in enumerate((0.25, 0.5, 0.75, 1.0)):
        color = grid_colors[grid_index]
        points = []
        for index in range(n):
            angle = -math.pi / 2 + 2 * math.pi * index / n
            px = cx + math.cos(angle) * radius * ratio
            py = cy + math.sin(angle) * radius * ratio
            points.append("{x:.1f},{y:.1f}".format(x=px, y=py))
        parts.append('<polygon points="{points}" fill="#f8fafc" fill-opacity="0.25" stroke="{color}" stroke-width="1"/>'.format(points=" ".join(points), color=color))
    for index, item in enumerate(scored):
        angle = -math.pi / 2 + 2 * math.pi * index / n
        px = cx + math.cos(angle) * radius
        py = cy + math.sin(angle) * radius
        parts.append('<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#d6dde7" stroke-width="1"/>'.format(x1=cx, y1=cy, x2=px, y2=py))
        label_x = cx + math.cos(angle) * (radius + 26)
        label_y = cy + math.sin(angle) * (radius + 18)
        anchor = "middle"
        if abs(label_x - cx) > 20:
            anchor = "start" if label_x > cx else "end"
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#374151" font-size="12" font-weight="600" text-anchor="{anchor}">{label}</text>'.format(
                x=label_x, y=label_y, anchor=anchor, label=html.escape(item.get("label", ""))
            )
        )
    data_points = []
    for index, item in enumerate(scored):
        angle = -math.pi / 2 + 2 * math.pi * index / n
        value = max(0.0, min(100.0, float(item["score"]))) / 100.0
        px = cx + math.cos(angle) * radius * value
        py = cy + math.sin(angle) * radius * value
        data_points.append("{x:.1f},{y:.1f}".format(x=px, y=py))
    parts.append('<polygon points="{points}" fill="#0ea5e9" fill-opacity="0.28" stroke="#0284c7" stroke-width="2.4" stroke-linejoin="round"/>'.format(points=" ".join(data_points)))
    for index, item in enumerate(scored):
        angle = -math.pi / 2 + 2 * math.pi * index / n
        value = max(0.0, min(100.0, float(item["score"]))) / 100.0
        px = cx + math.cos(angle) * radius * value
        py = cy + math.sin(angle) * radius * value
        parts.append('<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#0284c7"/>'.format(x=px, y=py))
        parts.append(
            '<text x="{x:.1f}" y="{y:.1f}" fill="#0c4a6e" font-size="11" font-weight="600" text-anchor="middle">{score}</text>'.format(
                x=px, y=py - 8, score=int(round(float(item["score"])))
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def build_sample_charts(sample):
    charts = {}
    for module in ("oecf", "mtf", "banding"):
        chart = line_chart_for_sample(sample, module)
        if chart:
            charts[module] = chart
    radar_items = [
        {"label": MODULE_OVERVIEW_ZH[module], "score": sample["dimensions"][module]["score"]}
        for module in ACTIVE_MODULE_ORDER
        if sample["dimensions"][module]["score"] is not None
    ]
    charts["radar"] = radar_chart(radar_items)
    return charts


def _series_color(module, name, index, fallback):
    if module == "oecf":
        if "R" in name:
            return "#dc2626"
        if "G" in name:
            return "#16a34a"
        if "B" in name:
            return "#2563eb"
    if module == "mtf":
        color_by_name = {
            "G Channel - Horizontal": "#2563eb",
            "Luminance - Horizontal": "#dc2626",
            "G Channel - Vertical": "#16a34a",
            "Luminance - Vertical": "#d97706",
            "Target MTF": "#6b7280",
        }
        if name in color_by_name:
            return color_by_name[name]
    palette = ["#2563eb", "#0d9488", "#d97706", "#dc2626", "#7c3aed", "#16a34a"]
    return palette[index % len(palette)] if fallback is None else fallback


def _chart_labels(module):
    if module == "oecf":
        return "RGB值", "反射率"
    if module == "mtf":
        return "空间频率（cycles/mm）", "MTF值"
    if module == "banding":
        return "频率", "幅度"
    return "横轴", "纵轴"


def build_mtf_system_curves(curves):
    target = None
    for curve in curves:
        name = curve.get("name", "")
        if name == "Target MTF" or name == "Target MTF G":
            target = curve
            break
    if not target:
        return []
    target_by_x = {}
    for pair in target.get("points", []):
        try:
            x = float(pair[0])
            y = float(pair[1])
        except (TypeError, ValueError):
            continue
        target_by_x[round(x, 6)] = y
    suffix_names = {
        "GH": "G Channel - Horizontal",
        "GV": "G Channel - Vertical",
        "YH": "Luminance - Horizontal",
        "YV": "Luminance - Vertical",
    }
    system_curves = []
    for suffix, name in suffix_names.items():
        source_name = "Scanner MTF " + suffix
        source = next((curve for curve in curves if curve.get("name") == source_name), None)
        if not source:
            continue
        points = []
        for pair in source.get("points", []):
            try:
                x = float(pair[0])
                y = float(pair[1])
            except (TypeError, ValueError):
                continue
            target_value = target_by_x.get(round(x, 6))
            if target_value is not None:
                points.append([x, y * target_value])
        if len(points) >= 2:
            system_curves.append({"name": name, "points": points})
    target_points = []
    for pair in target.get("points", []):
        try:
            target_points.append([float(pair[0]), float(pair[1])])
        except (TypeError, ValueError):
            continue
    if len(target_points) >= 2:
        system_curves.append({"name": "Target MTF", "points": target_points})
    return system_curves


def line_chart_for_sample(sample, module):
    fallback = {"oecf": "#0d9488", "mtf": "#2563eb", "banding": "#f59e0b"}.get(module, "#2563eb")
    series = []
    if module == "mtf":
        for index, item in enumerate(build_mtf_system_curves(sample.get("curves", []))):
            series.append(
                {
                    "name": item["name"],
                    "color": _series_color(module, item["name"], index, fallback),
                    "points": item["points"],
                }
            )
        if not series:
            return None
        return line_chart(series, title="", x_label="空间频率（cycles/mm）", y_label="Response", y_min=0, y_max=1)
    for index, curve in enumerate(sample.get("curves", [])):
        if curve.get("module") != module:
            continue
        if curve.get("display") is False:
            continue
        name = curve.get("name") or module
        if module == "mtf":
            if name.startswith("Scanner MTF "):
                tail = name[len("Scanner MTF "):]
                if tail not in ("YH", "YV"):
                    continue
                if tail == "YH":
                    name = "Scanner MTF Y Horizontal"
                else:
                    name = "Scanner MTF Y Vertical"
        series.append(
            {
                "name": name,
                "color": _series_color(module, name, index, fallback),
                "points": curve.get("points", []),
            }
        )
    if not series:
        return None
    x_label, y_label = _chart_labels(module)
    chart_options = {}
    if module == "mtf":
        chart_options["y_min"] = 0
        chart_options["y_max"] = 1
    return line_chart(series, title="", x_label=x_label, y_label=y_label, **chart_options)
