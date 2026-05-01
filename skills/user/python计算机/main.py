import math
import re
import json
from typing import Dict, Any, Optional

# 安全模块白名单
SAFE_MODULES = {
    'math': math,
    'json': json,
    're': re,
}

# 危险模块黑名单
DANGEROUS_KEYWORDS = [
    '__import__', 'eval', 'exec', 'compile', 'open', 'file',
    'os.', 'sys.', 'subprocess.', 'shutil.', 'socket.', 'importlib.',
    'breakpoint', 'globals', 'locals', 'vars', 'dir'
]

def is_code_safe(code: str) -> bool:
    """检查代码是否安全"""
    code_lower = code.lower()
    
    # 检查危险关键字
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in code_lower:
            return False
    
    # 检查导入语句
    lines = code.split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('import ') or line.startswith('from '):
            # 只允许导入白名单中的模块
            for safe_module in SAFE_MODULES:
                if safe_module in line:
                    continue
            return False
    
    return True

def execute_python_code(code: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
    """执行Python代码并返回结果"""
    if variables is None:
        variables = {}
    
    # 安全检查
    if not is_code_safe(code):
        return {
            "status": "error",
            "message": "代码包含不安全的内容，无法执行",
            "result": None,
            "output": ""
        }
    
    try:
        # 准备执行环境
        exec_globals = {
            '__builtins__': {
                'print': print,
                'len': len,
                'range': range,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'list': list,
                'dict': dict,
                'tuple': tuple,
                'set': set,
                'sum': sum,
                'min': min,
                'max': max,
                'abs': abs,
                'round': round,
                'pow': pow,
                'sorted': sorted,
                'reversed': reversed,
                'enumerate': enumerate,
                'zip': zip,
                'type': type,
                'isinstance': isinstance,
                'issubclass': issubclass,
                'hasattr': hasattr,
                'getattr': getattr,
                'setattr': setattr,
            }
        }
        
        # 添加安全模块
        exec_globals.update(SAFE_MODULES)
        
        # 添加用户变量
        exec_globals.update(variables)
        
        # 执行代码
        exec_result = {}
        exec(code, exec_globals, exec_result)
        
        # 获取结果
        result = None
        output = ""
        
        # 尝试获取最后表达式的结果
        lines = code.strip().split('\n')
        last_line = lines[-1].strip()
        
        # 如果最后一行是表达式（不是赋值或控制语句）
        if (last_line and 
            not last_line.startswith('#') and
            not last_line.startswith('def ') and
            not last_line.startswith('class ') and
            not last_line.startswith('import ') and
            not last_line.startswith('from ') and
            not last_line.startswith('if ') and
            not last_line.startswith('for ') and
            not last_line.startswith('while ') and
            not last_line.startswith('try:') and
            not last_line.startswith('except ') and
            not last_line.startswith('with ') and
            '=' not in last_line.split('#')[0] and
            'return' not in last_line):
            
            try:
                # 尝试计算最后表达式
                result = eval(last_line, exec_globals)
            except:
                pass
        
        # 更新变量（排除内置变量）
        new_variables = {}
        for key, value in exec_globals.items():
            if (key not in SAFE_MODULES and 
                key not in exec_globals['__builtins__'] and
                not key.startswith('__')):
                new_variables[key] = value
        
        return {
            "status": "success",
            "message": "代码执行成功",
            "result": result,
            "output": output,
            "variables": new_variables
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"代码执行错误: {str(e)}",
            "result": None,
            "output": "",
            "variables": variables
        }

def calculate_expression(expr: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
    """计算数学表达式"""
    if variables is None:
        variables = {}
    
    try:
        # 替换变量
        for var_name, var_value in variables.items():
            if isinstance(var_value, (int, float)):
                expr = expr.replace(var_name, str(var_value))
        
        # 安全检查：只允许数学表达式
        safe_chars = set('0123456789+-*/().^%!πe ')
        safe_functions = ['sin', 'cos', 'tan', 'log', 'ln', 'sqrt', 'abs']
        
        # 检查表达式是否安全
        expr_clean = expr.lower()
        for func in safe_functions:
            expr_clean = expr_clean.replace(func, '')
        
        if any(c not in safe_chars for c in expr_clean if c.isalpha()):
            return {
                "status": "error",
                "message": "表达式包含不安全的内容",
                "result": None
            }
        
        # 替换数学常数
        expr = expr.replace('π', 'math.pi').replace('pi', 'math.pi')
        expr = expr.replace('e', 'math.e')
        
        # 替换函数名
        expr = expr.replace('sin', 'math.sin')
        expr = expr.replace('cos', 'math.cos')
        expr = expr.replace('tan', 'math.tan')
        expr = expr.replace('log', 'math.log10')
        expr = expr.replace('ln', 'math.log')
        expr = expr.replace('sqrt', 'math.sqrt')
        expr = expr.replace('^', '**')
        
        # 计算表达式
        result = eval(expr, {"math": math, "__builtins__": {}}, {})
        
        return {
            "status": "success",
            "message": "计算成功",
            "result": result
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"计算错误: {str(e)}",
            "result": None
        }

def explain_code(code: str) -> Dict[str, Any]:
    """解释Python代码的功能"""
    try:
        explanation = []
        
        lines = code.strip().split('\n')
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            if '=' in line and '==' not in line:
                # 赋值语句
                var_name = line.split('=')[0].strip()
                explanation.append(f"第{i}行: 定义变量 {var_name}")
                
            elif line.startswith('def '):
                # 函数定义
                func_name = line[4:].split('(')[0].strip()
                explanation.append(f"第{i}行: 定义函数 {func_name}")
                
            elif line.startswith('if '):
                explanation.append(f"第{i}行: 条件判断语句")
                
            elif line.startswith('for '):
                explanation.append(f"第{i}行: 循环语句")
                
            elif line.startswith('print('):
                explanation.append(f"第{i}行: 输出语句")
                
            else:
                explanation.append(f"第{i}行: 执行表达式或语句")
        
        return {
            "status": "success",
            "message": "代码解释完成",
            "explanation": explanation,
            "line_count": len(lines)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"解释错误: {str(e)}"
        }

def execute(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    主执行函数
    
    Args:
        context: 上下文字典，包含输入数据、状态等信息
        
    Returns:
        执行结果字典
    """
    try:
        # 获取输入数据
        input_data = context.get("input_data", {})
        state = context.get("state", {})
        
        # 获取用户输入
        code = input_data.get("code", "").strip()
        operation = input_data.get("operation", "execute")
        user_variables = input_data.get("variables", {})
        
        # 合并状态中的变量
        state_variables = state.get("variables", {})
        all_variables = {**state_variables, **user_variables}
        
        if not code:
            return {
                "status": "error",
                "message": "请输入要执行的代码或表达式"
            }
        
        result = None
        
        # 根据操作类型执行不同的功能
        if operation == "execute":
            result = execute_python_code(code, all_variables)
            
        elif operation == "calculate":
            result = calculate_expression(code, all_variables)
            
        elif operation == "explain":
            result = explain_code(code)
            
        else:
            # 默认尝试执行代码
            result = execute_python_code(code, all_variables)
        
        # 更新状态（保存变量）
        if result.get("status") == "success" and "variables" in result:
            state["variables"] = result["variables"]
            # 保存计算历史
            history = state.get("history", [])
            history.append({
                "code": code,
                "operation": operation,
                "result": result.get("result"),
                "timestamp": context.get("timestamp", "")
            })
            # 只保留最近10条历史
            state["history"] = history[-10:]
        
        # 返回结果
        return {
            "status": result.get("status", "error"),
            "message": result.get("message", ""),
            "result": result.get("result"),
            "output": result.get("output", ""),
            "explanation": result.get("explanation"),
            "variables": result.get("variables", {}),
            "state": state
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"技能执行错误: {str(e)}"
        }