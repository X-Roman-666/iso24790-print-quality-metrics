const runtimeUrl = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs";
const modules = [
  "analyzer", "charts", "data_parser", "explanation_engine", "metrics_catalog", "report_generator"
];

self.onmessage = async ({ data: inputs }) => {
  try {
    const { loadPyodide } = await import(runtimeUrl);
    const python = await loadPyodide();
    await Promise.all(modules.map(async (name) => {
      const response = await fetch(new URL("./engine/" + name + ".py", import.meta.url));
      if (!response.ok) throw new Error("无法加载分析模块：" + name);
      python.FS.writeFile("/home/pyodide/" + name + ".py", await response.text());
    }));

    if (inputs.some(({ name }) => /\.xlsx$/i.test(name))) {
      await python.loadPackage("micropip");
      await python.runPythonAsync('import micropip\nawait micropip.install("openpyxl==3.1.5")');
    }
    inputs.forEach(({ bytes }, index) => {
      python.FS.writeFile("/tmp/measurement-" + index, new Uint8Array(bytes));
    });
    python.globals.set("input_names_json", JSON.stringify(inputs.map(({ name }) => name)));
    const result = python.runPython(`
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/pyodide")
from analyzer import analyze_files
from data_parser import parse_file
from report_generator import generate_report

parsed = [
    parse_file(name, Path(f"/tmp/measurement-{index}").read_bytes())
    for index, name in enumerate(json.loads(input_names_json))
]
if not any(item.ok and (item.metrics or item.curves or item.provided_scores) for item in parsed):
    errors = [item.error for item in parsed if item.error]
    detail = "；".join(errors) if errors else "请检查所选文件的内容。"
    raise ValueError("未识别到可分析的测量数据。" + detail)
analysis = analyze_files(parsed)
json.dumps({"analysis": analysis, "report_html": generate_report(analysis)}, ensure_ascii=False)
`);
    self.postMessage(JSON.parse(result));
  } catch (error) {
    const message = error.message.trim().split("\n").at(-1);
    self.postMessage({ error: "分析失败：" + message.replace(/^ValueError: /, "") });
  }
};
