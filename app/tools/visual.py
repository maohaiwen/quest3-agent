"""可视化工具服务 — 生成 ECharts 图表、Mermaid 流程图、富表格等 HTML5 内容"""
import json
import re
import logging
from typing import Dict, Any, Optional
from app.tools.base import BaseToolService
from app.services.mcp_service import MCPTool

logger = logging.getLogger(__name__)

# HTML 模板常量
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
DEFAULT_WIDTH = "100%"
DEFAULT_HEIGHT = "520px"

# 消息内容中 HTML 块的分隔标记
VISUAL_BLOCK_MARKER = "<!--visual-->"
VISUAL_BLOCK_END = "<!--/visual-->"


def _sanitize_html(html: str) -> str:
    """基本 XSS 过滤：移除 script 标签和事件属性"""
    # 移除 <script>...</script>
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 移除 on* 事件属性
    html = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)
    # 移除 javascript: 协议
    html = re.sub(r'javascript\s*:', '', html, flags=re.IGNORECASE)
    return html


def _build_echarts_html(option: dict, width: str = DEFAULT_WIDTH, height: str = DEFAULT_HEIGHT) -> str:
    """生成 ECharts 图表 HTML 片段"""
    import hashlib
    chart_id = "echarts_" + hashlib.md5(str(option).encode()).hexdigest()[:8]
    # 用 json.dumps 保证合法 JSON，转义 </ 防止提前关闭 script 标签
    option_json = json.dumps(option, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return f'''<div class="visual-block">
<div id="{chart_id}" style="width:{width};height:{height};"></div>
<script src="{ECHARTS_CDN}"></script>
<script>
(function() {{
    // 递归遍历 option，将函数字符串还原为真正的 JS 函数
    function reviveFunctions(obj) {{
        if (obj === null || obj === undefined) return obj;
        if (Array.isArray(obj)) return obj.map(reviveFunctions);
        if (typeof obj === 'object') {{
            var result = {{}};
            for (var key in obj) {{
                if (obj.hasOwnProperty(key)) {{
                    result[key] = reviveFunctions(obj[key]);
                }}
            }}
            return result;
        }}
        if (typeof obj === 'string') {{
            var s = obj.trim();
            // 匹配 function(params) {...} 或 (params) => {...} 等函数字符串
            if (/^function\\s*\\(/.test(s) || /^function\\s+\\w+\\s*\\(/.test(s) ||
                /^\\([\\w,\\s]*\\)\\s*=>/.test(s) || /^[a-zA-Z_$][\\w$]*\\s*=>/.test(s)) {{
                try {{ return new Function('return ' + s)(); }}
                catch(e) {{ return obj; }}
            }}
        }}
        return obj;
    }}

    var dom = document.getElementById('{chart_id}');
    var chart = echarts.init(dom);
    var rawOption = JSON.parse({option_json!r});
    var option = reviveFunctions(rawOption);
    chart.setOption(option);
    window.addEventListener('resize', function() {{ chart.resize(); }});

    function notifyHeight() {{
        var h = dom.offsetHeight + 24;
        window.parent.postMessage({{type:'visual-resize',frameId:window.frameElement.id,height:h}}, '*');
    }}
    chart.on('finished', function() {{ setTimeout(notifyHeight, 100); }});
    setTimeout(notifyHeight, 300);
    setTimeout(notifyHeight, 1000);
    setTimeout(notifyHeight, 2000);
}})();
</script>
</div>'''


def _build_mermaid_html(code: str) -> str:
    """生成 Mermaid 流程图 HTML 片段"""
    # 转义单引号防止 JS 报错
    safe_code = code.replace("'", "&#39;")
    return f'''<div class="visual-block">
<pre class="mermaid">{safe_code}</pre>
<script src="{MERMAID_CDN}"></script>
<script>
(function() {{
    mermaid.initialize({{startOnLoad:true,theme:'default'}});
    function notifyHeight() {{
        var el = document.querySelector('.mermaid');
        if(el) window.parent.postMessage({{type:'visual-resize',frameId:window.frameElement.id,height:el.offsetHeight+24}}, '*');
    }}
    setTimeout(notifyHeight, 500);
    setTimeout(notifyHeight, 1500);
    setTimeout(notifyHeight, 3000);
}})();
</script>
</div>'''


def _build_table_html(headers: list, rows: list) -> str:
    """生成富表格 HTML 片段"""
    header_html = "".join(f"<th>{h}</th>" for h in headers)
    body_html = ""
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_html += f"<tr>{cells}</tr>"
    return f'''<div class="visual-block">
<table style="width:100%;border-collapse:collapse;font-size:14px;">
<thead><tr>{header_html}</tr></thead>
<tbody>{body_html}</tbody>
</table>
<style>
.visual-block table th, .visual-block table td {{border:1px solid #ddd;padding:8px 12px;text-align:left;}}
.visual-block table th {{background:#f5f5f5;font-weight:600;}}
.visual-block table tr:nth-child(even) {{background:#fafafa;}}
</style>
</div>'''


def _build_image_html(url: str, alt: str = "") -> str:
    """生成图片 HTML 片段"""
    return f'''<div class="visual-block">
<img src="{url}" alt="{alt}" style="max-width:100%;height:auto;border-radius:8px;" />
</div>'''


class VisualToolService(BaseToolService):
    """可视化工具服务"""

    service_name = "可视化"
    service_description = "生成ECharts图表、Mermaid流程图、富表格、图片等可视化内容"
    deps = []

    def __init__(self):
        self._chart_counter = 0

    def _build_html(self, vis_type: str, data: dict) -> tuple[str, str]:
        """根据类型构建 HTML 片段

        Args:
            vis_type: 可视化类型
            data: 类型相关的数据

        Returns:
            (html_content, summary)
        """
        if vis_type == "echarts":
            option = data.get("option", {})
            if not option:
                return "", "ECharts 配置为空"
            html = _build_echarts_html(option)
            return html, "ECharts 图表"

        elif vis_type == "mermaid":
            code = data.get("code", "")
            if not code:
                return "", "Mermaid 代码为空"
            html = _build_mermaid_html(code)
            return html, "Mermaid 流程图"

        elif vis_type == "table":
            headers = data.get("headers", [])
            rows = data.get("rows", [])
            if not headers:
                return "", "表格表头为空"
            html = _build_table_html(headers, rows)
            return html, f"数据表格({len(rows)}行)"

        elif vis_type == "image":
            url = data.get("url", "")
            if not url:
                return "", "图片 URL 为空"
            alt = data.get("alt", "")
            html = _build_image_html(url, alt)
            return html, f"图片: {alt or url[:50]}"

        elif vis_type == "html":
            content = data.get("content", "")
            if not content:
                return "", "HTML 内容为空"
            html = f'<div class="visual-block">{_sanitize_html(content)}</div>'
            return html, "自定义 HTML 内容"

        else:
            return "", f"不支持的可视化类型: {vis_type}"

    async def render_visual(self, type: str = "", data: dict = None, **kwargs) -> dict:
        """生成可视化内容

        Args:
            type: 可视化类型 (echarts/mermaid/table/image/html)
            data: 可视化数据

        Returns:
            包含 __render_html__ 标记的字典，供执行器识别
        """
        # 容错：LLM 可能将参数放在 kwargs 里
        if not type:
            type = kwargs.get("type", "")
        if data is None:
            data = kwargs.get("data", {})

        if not type:
            return {"error": "请指定可视化类型 (type): echarts, mermaid, table, image, html"}
        if not data:
            return {"error": f"请提供可视化数据 (data)，类型 {type} 需要的数据结构请参考工具描述"}

        html, summary = self._build_html(type, data)
        if not html:
            return {"error": summary}

        return {
            "__render_html__": html,
            "summary": summary,
        }

    def get_tools(self) -> Dict[str, MCPTool]:
        return {
            "render_visual": MCPTool(
                name="render_visual",
                description=(
                    "生成可视化内容，用于图文并茂地展示信息。"
                    "支持以下类型：\n"
                    "- echarts: 交互式图表（折线图、柱状图、饼图、散点图等），传入 ECharts option 对象\n"
                    "- mermaid: 流程图/架构图/思维导图，传入 Mermaid 语法代码\n"
                    "- table: 富样式数据表格，传入表头和行数据\n"
                    "- image: 展示图片，传入图片URL\n"
                    "- html: 自定义HTML内容\n"
                    "当需要用图表、图形、表格来直观展示数据或流程时使用此工具。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["echarts", "mermaid", "table", "image", "html"],
                            "description": "可视化类型",
                        },
                        "data": {
                            "type": "object",
                            "description": (
                                "可视化数据，结构因类型而异：\n"
                                'echarts: {"option": {ECharts配置}}\n'
                                'mermaid: {"code": "Mermaid语法代码"}\n'
                                'table: {"headers": ["列1","列2"], "rows": [["值1","值2"]]}\n'
                                'image: {"url": "图片地址", "alt": "图片描述"}\n'
                                'html: {"content": "HTML内容"}'
                            ),
                        },
                    },
                    "required": ["type", "data"],
                },
                handler=self.render_visual,
            )
        }


def wrap_message_with_visuals(text: str, html_blocks: list[str]) -> str:
    """将文本和 HTML 块合并为一条消息内容

    格式: 文本部分 + 交替的 <!--visual-->...<!--/visual--> 块
    """
    if not html_blocks:
        return text
    parts = [text] if text else []
    for html in html_blocks:
        parts.append(f"{VISUAL_BLOCK_MARKER}\n{html}\n{VISUAL_BLOCK_END}")
    return "\n".join(parts)


def extract_visual_from_result(result: Any) -> tuple[Any, Optional[str], str]:
    """从工具调用结果中提取可视化 HTML，返回清洗后的结果

    Args:
        result: 工具调用结果

    Returns:
        (clean_result, html_or_none, summary)
        - clean_result: 移除 __render_html__ 后的结果（给 LLM 看的纯文本摘要）
        - html_or_none: 可视化 HTML 内容，如果没有则为 None
        - summary: 可视化内容摘要
    """
    if not isinstance(result, dict) or "__render_html__" not in result:
        return result, None, ""

    html = result.pop("__render_html__")
    summary = result.pop("summary", "可视化内容已渲染")

    # 构建给 LLM 看的纯文本摘要
    clean_result = {"summary": summary, "status": "rendered"}
    # 保留其他字段（如 error 等）
    for key, value in result.items():
        if key not in ("summary", "status"):
            clean_result[key] = value

    return clean_result, html, summary


def split_message_with_visuals(content: str) -> tuple[str, list[str]]:
    """从消息内容中拆分出纯文本和 HTML 块

    Returns:
        (text, html_blocks)
    """
    if VISUAL_BLOCK_MARKER not in content:
        return content, []

    text_parts = []
    html_blocks = []
    pattern = re.compile(
        re.escape(VISUAL_BLOCK_MARKER) + r"\s*(.*?)\s*" + re.escape(VISUAL_BLOCK_END),
        re.DOTALL,
    )

    last_end = 0
    for m in pattern.finditer(content):
        # 标记之前的内容是文本
        text_parts.append(content[last_end:m.start()].strip())
        html_blocks.append(m.group(1))
        last_end = m.end()

    # 标记之后的内容
    remaining = content[last_end:].strip()
    if remaining:
        text_parts.append(remaining)

    text = "\n".join(p for p in text_parts if p)
    return text, html_blocks
