"""Skill Writer Service - LLM-assisted skill authoring"""
import ast
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.models.skill import Skill, SkillSource, ChatMessage
from app.config import settings

logger = logging.getLogger(__name__)


class SkillCodeValidator:
    """Validates generated skill code before saving to disk.

    Catches syntax errors, missing entry functions, and compilation issues
    so that users get immediate feedback instead of runtime crashes.
    Also performs smoke tests on shell/PowerShell scripts.
    """

    MAX_RETRIES = 2

    def validate_python(self, code: str) -> List[str]:
        """Validate Python code. Returns list of error strings (empty = valid).

        Checks:
        1. Syntax: ast.parse()
        2. Entry function: module-level execute() exists
        3. Dry-run compile: catches indent errors ast may miss
        """
        errors = []

        # Check 1: Syntax
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            line_info = f" at line {e.lineno}" if e.lineno else ""
            errors.append(f"Syntax error{line_info}: {e.msg}")
            return errors  # Can't check further if syntax is broken

        # Check 2: execute() function exists at module level
        has_execute = False
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "execute":
                has_execute = True
                break
        if not has_execute:
            errors.append(
                "Missing module-level execute() function. "
                "The skill must define 'def execute(context):' at the top level."
            )

        # Check 3: Dry-run compile (catches indent errors ast misses)
        try:
            compile(code, "<skill>", "exec")
        except Exception as e:
            errors.append(f"Compilation error: {e}")

        return errors

    def validate_shell(self, code: str) -> List[str]:
        """Validate shell script. Returns list of error strings (empty = valid).

        Checks:
        1. Non-empty
        2. Shebang line
        3. INPUT_DATA reference (skill scripts read input from env var)
        4. bash -n syntax check (if bash available)
        """
        errors = []

        if not code.strip():
            errors.append("Empty shell script")
            return errors

        if not code.strip().startswith("#!"):
            errors.append("Missing shebang line (e.g., #!/bin/bash)")

        if "INPUT_DATA" not in code:
            errors.append(
                "Shell script must read INPUT_DATA environment variable "
                "to receive input from the skill executor"
            )

        # Smoke test: bash -n (syntax check, no execution)
        import subprocess
        import shutil
        if shutil.which("bash"):
            try:
                result = subprocess.run(
                    ["bash", "-n", "-c", code],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0 and result.stderr.strip():
                    errors.append(f"bash syntax error: {result.stderr.strip()}")
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.debug(f"bash -n check skipped: {e}")

        return errors

    def validate_powershell(self, code: str) -> List[str]:
        """Validate PowerShell script. Returns list of error strings (empty = valid).

        Checks:
        1. Non-empty
        2. INPUT_DATA reference
        3. Smoke test: powershell -Command with syntax check
        """
        errors = []

        if not code.strip():
            errors.append("Empty PowerShell script")
            return errors

        if "INPUT_DATA" not in code:
            errors.append(
                "PowerShell script must read $env:INPUT_DATA "
                "to receive input from the skill executor"
            )

        # Smoke test: PowerShell syntax check
        import subprocess
        import os
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".ps1", delete=False
            ) as tmp:
                tmp.write(b"\xef\xbb\xbf")  # UTF-8 BOM for Windows PS 5.1
                tmp.write(code.encode("utf-8"))
                tmp_path = tmp.name

            env = os.environ.copy()
            env["INPUT_DATA"] = '{"url": "https://test.example.com"}'
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", tmp_path],
                capture_output=True, env=env, timeout=10,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                error_lines = []
                for line in stderr.splitlines():
                    if any(kw in line for kw in [
                        "ParserError", "Unexpected token",
                        "MissingEndCurly", "MissingExpression",
                        "is not recognized",
                    ]):
                        error_lines.append(line.strip())
                if error_lines:
                    errors.append(
                        "PowerShell smoke test failed: " + "; ".join(error_lines)
                    )
            os.unlink(tmp_path)
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug(f"PowerShell smoke test skipped: {e}")
            try:
                if 'tmp_path' in locals():
                    os.unlink(tmp_path)
            except OSError:
                pass

        return errors


class SkillWriterService:
    """Service for LLM-assisted skill creation and editing"""

    def __init__(self, llm_service=None):
        self.llm_service = llm_service
        # Try to get LLM service if not provided
        if not self.llm_service:
            try:
                from app.services.llm_service import llm_service as global_llm_service
                self.llm_service = global_llm_service
                logger.info("SkillWriterService initialized with global LLM service")
            except Exception as e:
                logger.warning(f"Could not initialize LLM service: {e}")

    async def generate_skill_from_description(
        self,
        description: str,
        template: str = "basic",
        requirements: Optional[list] = None
    ) -> Dict[str, str]:
        """
        Generate a complete skill based on user description

        Args:
            description: What the skill should do
            template: Which template pattern to follow
            requirements: Python package requirements

        Returns:
            Dictionary with generated files
        """
        if not self.llm_service or not self.llm_service.is_configured():
            logger.info("LLM service not available, using fallback generation")
            return self._get_fallback_generation(description, template)

        try:
            # Build prompt
            prompt = self._build_skill_generation_prompt(description, template, requirements)

            # Call LLM (disable tools for skill generation)
            logger.info(f"Generating skill for description: {description}")
            response = await self.llm_service.chat(prompt, use_tools=False)
            logger.info(f"Received LLM response of length: {len(response)}")

            # Parse response
            files = self._parse_llm_response(response)
            return files

        except Exception as e:
            logger.error(f"Failed to generate skill: {e}", exc_info=True)
            return self._get_fallback_generation(description, template)

    async def complete_file(
        self,
        skill_name: str,
        file_path: str,
        current_content: str,
        instruction: str
    ) -> str:
        """
        Complete or improve a skill file using LLM

        Args:
            skill_name: Name of the skill
            file_path: Path to the file
            current_content: Current content of the file
            instruction: What to do (e.g., "add error handling")

        Returns:
            New/improved content
        """
        if not self.llm_service or not self.llm_service.is_configured():
            logger.info("LLM service not available, returning original content")
            return current_content

        try:
            prompt = self._build_completion_prompt(skill_name, file_path, current_content, instruction)
            logger.info(f"Calling LLM to complete file: {file_path}")
            response = await self.llm_service.chat(prompt, use_tools=False)
            logger.info(f"Received LLM response")
            return self._extract_code_from_response(response)

        except Exception as e:
            logger.error(f"Failed to complete file: {e}", exc_info=True)
            return current_content

    async def generate_main_py(
        self,
        skill_md_content: str,
        requirements: Optional[list] = None
    ) -> str:
        """
        Generate a main.py file based on skill.md content

        Args:
            skill_md_content: The skill.md content
            requirements: Optional Python requirements

        Returns:
            Generated main.py content
        """
        if not self.llm_service or not self.llm_service.is_configured():
            logger.info("LLM service not available, using fallback main.py")
            return self._get_fallback_main_py()

        try:
            prompt = self._build_main_py_prompt(skill_md_content, requirements)
            logger.info("Calling LLM to generate main.py")
            response = await self.llm_service.chat(prompt, use_tools=False)
            logger.info("Received LLM response for main.py generation")
            return self._extract_code_from_response(response)

        except Exception as e:
            logger.error(f"Failed to generate main.py: {e}", exc_info=True)
            return self._get_fallback_main_py()

    async def improve_skill_content(
        self,
        current_content: str,
        improvement_type: str = "general"
    ) -> str:
        """
        Improve existing skill content

        Args:
            current_content: Current skill.md content
            improvement_type: What kind of improvement (general, clarity, examples)

        Returns:
            Improved content
        """
        if not self.llm_service or not self.llm_service.is_configured():
            logger.info("LLM service not available, returning original content")
            return current_content

        try:
            prompt = self._build_improvement_prompt(current_content, improvement_type)
            logger.info("Calling LLM to improve skill content")
            response = await self.llm_service.chat(prompt, use_tools=False)
            logger.info("Received LLM response for skill improvement")
            return response

        except Exception as e:
            logger.error(f"Failed to improve skill: {e}", exc_info=True)
            return current_content

    def _build_skill_generation_prompt(
        self,
        description: str,
        template: str,
        requirements: Optional[list]
    ) -> str:
        """Build prompt for skill generation"""
        requirements_str = "\n".join(f"- {r}" for r in (requirements or []))

        return f"""你是一个专业的 AI Skill 编写助手。请根据用户的描述创建一个完整的 Skill。

用户描述：{description}

请生成以下文件（如果需要）：
1. skill.md - 必须包含，要有 YAML frontmatter
2. main.py - 如果需要自定义 Python 逻辑
3. requirements.txt - 如果有依赖
4. README.md - 可选的说明文档

要求：
- skill.md 必须包含以下 frontmatter：
  name: <skill_name>
  version: 1.0.0
  description: <description>
  author: <author>
  tags: [tag1, tag2]
  tools: []
- 如果包含 Python 代码，确保有 execute() 函数

请按以下格式输出（用 --- 分隔不同文件）：

FILENAME: skill.md
<content here>
---
FILENAME: main.py
<content here>
---

开始创建！"""

    def _build_completion_prompt(
        self,
        skill_name: str,
        file_path: str,
        current_content: str,
        instruction: str
    ) -> str:
        """Build prompt for file completion"""
        return f"""你是一个代码助手。请根据要求改进以下文件。

Skill: {skill_name}
文件: {file_path}

当前内容：
```
{current_content}
```

用户要求：{instruction}

请直接输出改进后的完整文件内容，不要解释。"""

    def _build_main_py_prompt(
        self,
        skill_md_content: str,
        requirements: Optional[list]
    ) -> str:
        """Build prompt for generating main.py from skill.md"""
        return f"""你是一个 Python 专家。请根据以下 skill.md 的描述，创建一个对应的 main.py 文件。

skill.md 内容：
```
{skill_md_content}
```

要求：
1. 必须有一个 execute(context) 函数作为入口
2. 函数接收一个 context 参数，包含 input_data, config, state 等
3. 可以返回简单的字典或者任意 Python 对象
4. 代码要有适当的注释
5. 要有错误处理

请直接输出完整的 Python 代码，不要解释。"""

    def _build_improvement_prompt(self, current_content: str, improvement_type: str) -> str:
        """Build prompt for improving skill content"""
        improvements = {
            "general": "整体改进，让描述更清晰，结构更好",
            "clarity": "让描述更清楚，添加更多细节和示例",
            "examples": "添加更多的使用示例",
            "structure": "改进组织结构，让更易读",
        }
        instruction = improvements.get(improvement_type, improvements["general"])

        return f"""请改进以下 skill.md 的内容：{instruction}

当前内容：
```
{current_content}
```

请输出改进后的完整内容。"""

    def _parse_llm_response(self, response: str) -> Dict[str, str]:
        """Parse LLM response into files"""
        import re

        files = {}

        # First, try the standard FILENAME: format
        current_file = None
        current_content = []

        lines = response.split("\n")
        for line in lines:
            if line.startswith("FILENAME:"):
                if current_file:
                    files[current_file] = "\n".join(current_content).strip()
                current_file = line[9:].strip()
                current_content = []
            elif line.startswith("---") and current_file:
                continue
            elif current_file:
                current_content.append(line)

        if current_file:
            files[current_file] = "\n".join(current_content).strip()

        # If we found files, return them
        if files:
            logger.info(f"Parsed files using standard format: {list(files.keys())}")
            return files

        # If no files found with standard format, try to extract from markdown code blocks
        logger.info("No files found with standard format, trying code block extraction")

        # Try to find code blocks with filename hints
        # Look for patterns like "```skill.md" or "```python main.py"
        code_block_pattern = r"```([\w\.]*)?\s*([\w\./]*)\s*\n([\s\S]*?)\n```"
        matches = re.findall(code_block_pattern, response)

        for lang, filename, content in matches:
            if not filename:
                # Guess filename from language or context
                if lang == "python" or "def execute" in content:
                    filename = "main.py"
                elif lang == "yaml" or "---" in content[:100]:
                    filename = "skill.md"
                elif "requirements" in response.lower() and "==" in content:
                    filename = "requirements.txt"

            if filename:
                # Clean up filename
                filename = filename.strip().split("/")[-1]
                if filename and filename not in files:
                    files[filename] = content.strip()
                    logger.info(f"Extracted file from code block: {filename}")

        if files:
            return files

        # Last resort: if we have content but no files, assume it's skill.md
        if response.strip():
            logger.info("Last resort: treating response as skill.md")
            files["skill.md"] = self._extract_code_from_response(response)

        return files

    def _extract_code_from_response(self, response: str) -> str:
        """Extract code block from LLM response.

        Handles:
        - Standard markdown code blocks: ```python\\ncode\\n```
        - Auto-continuation: truncated code without closing ```
        - Multiple code blocks from continuation (picks the largest)
        - Bare code without any code fence
        """
        import re

        # Strategy 1: Find code block with opening ``` and closing ```
        # Use greedy match to capture everything between first opening and last closing
        code_block_match = re.search(r"```[\w]*\n([\s\S]*)\n```", response)
        if code_block_match:
            content = code_block_match.group(1)
        else:
            # Strategy 2: Opening ``` found but no closing ``` (truncated output)
            # This happens when LLM output was auto-continued but the combined text
            # has an opening fence without a matching close
            open_only_match = re.search(r"```[\w]*\n([\s\S]+)$", response)
            if open_only_match:
                content = open_only_match.group(1)
            else:
                # Strategy 3: Try inline format ```code``` (no newlines)
                inline_match = re.search(r"```([\s\S]*)```", response)
                if inline_match:
                    content = inline_match.group(1)
                else:
                    # Strategy 4: No code fence — assume entire response is code
                    content = response

        # Clean up any remaining ```python or ``` markers at the start of lines
        # (can happen in continuation scenarios)
        content = re.sub(r"^```python\s*", "", content, flags=re.MULTILINE)
        content = re.sub(r"^```\s*", "", content, flags=re.MULTILINE)

        # Strip leading/trailing whitespace but preserve indentation
        lines = content.split('\n')
        # Remove first line if it's empty or just whitespace
        while lines and not lines[0].strip():
            lines.pop(0)
        # Remove last line if it's empty or just whitespace
        while lines and not lines[-1].strip():
            lines.pop()

        return '\n'.join(lines).strip()

    def _get_fallback_generation(self, description: str, template: str) -> Dict[str, str]:
        """Fallback generation when LLM is not available"""
        from app.skills.templates import SKILL_TEMPLATES

        template_data = SKILL_TEMPLATES.get(template, SKILL_TEMPLATES["basic"])
        files = {}

        for filename, content in template_data["files"].items():
            processed = content.replace("{{name}}", "generated_skill")
            processed = processed.replace("{{description}}", description)
            processed = processed.replace("{{author}}", "LLM Assistant")
            files[filename] = processed

        return files

    async def chat(
        self,
        messages: List[ChatMessage],
        skill_name: Optional[str] = None,
        current_file: Optional[str] = None,
        file_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Chat with the AI assistant - it can edit files!

        Workflow:
        1. LLM decides what files are needed (including script type + intent)
        2. For Python skills: joint generation of skill.md + main.py in one LLM call
        3. For other skills: per-file generation
        4. Validate generated Python code, retry if needed
        5. Frontmatter is generated by code, not by LLM
        6. Save each file and return summary

        Returns:
            {
                "content": "message to show user",
                "files_edited": ["skill.md", "main.py"],
                "success": True
            }
        """
        if not skill_name:
            return {
                "content": "请先选择或创建一个技能，然后我才能帮你编辑文件！",
                "files_edited": [],
                "success": True
            }

        # Get file manager
        from app.skills.file_manager import get_skill_file_manager
        file_manager = get_skill_file_manager()

        # Read current files
        current_files_info = file_manager.get_file_list(skill_name, SkillSource.USER)
        files_content = {}
        for file_info in current_files_info:
            fname = file_info["path"]
            content = file_manager.read_file(skill_name, fname, SkillSource.USER)
            if content is not None:
                files_content[fname] = content

        last_user_msg = messages[-1].content if messages else ""

        # Check if LLM is available
        if not self.llm_service or not self.llm_service.is_configured():
            logger.info("LLM not available, using fallback")
            return {
                "content": "LLM服务未配置，请先配置API密钥！",
                "files_edited": [],
                "success": False
            }

        saved_files = []

        try:
            # ========== Step 1: Decide what files and script type are needed ==========
            logger.info("Deciding what files are needed...")

            user_msg_lower = last_user_msg.lower()
            needs_complete = any(keyword in user_msg_lower for keyword in
                ['完善', '完整', '按照', '根据', '创建', 'create', 'complete', 'make', 'build'])

            file_plan = None
            if needs_complete:
                # 完整创建模式：使用智能规划
                file_plan = await self._plan_skill_files(skill_name, last_user_msg, files_content, current_file)
            else:
                # 普通模式：让LLM决定
                decision_prompt = self._build_file_decision_prompt(skill_name, last_user_msg, files_content, current_file)
                decision_response = await self.llm_service.chat(decision_prompt, use_tools=False)
                files_to_edit = self._parse_file_list(decision_response, current_file, last_user_msg)
                file_plan = {
                    "files": files_to_edit,
                    "script_type": self._detect_script_type_from_files(files_to_edit)
                }

            files_to_edit = file_plan.get("files", [])
            script_type = file_plan.get("script_type", "python")  # python, shell, powershell, prompt-only
            logger.info(f"Files to edit: {files_to_edit}, script_type: {script_type}")

            # ========== Step 2: Generate files ==========
            # For Python skills needing both skill.md and main.py: joint generation
            needs_joint = (
                script_type == "python"
                and "skill.md" in files_to_edit
                and any(f.endswith('.py') for f in files_to_edit)
            )

            if needs_joint:
                saved_files = await self._handle_joint_generation(
                    skill_name, last_user_msg, file_plan, files_content, file_manager
                )
            else:
                saved_files = await self._handle_single_file_generation(
                    skill_name, last_user_msg, file_plan, files_content, file_manager, script_type
                )

            # Reload registry
            try:
                from app.skills.registry import get_skill_registry
                registry = get_skill_registry()
                registry.reload()
            except Exception as e:
                logger.warning(f"Could not reload registry: {e}")

            # ========== Step 3: Build response ==========
            response_msg = self._build_chat_response(saved_files, script_type)

        except Exception as e:
            logger.error(f"Error in chat: {e}", exc_info=True)
            return {
                "content": f"抱歉，生成内容时出错：{str(e)}",
                "files_edited": [],
                "success": False
            }

        return {
            "content": response_msg,
            "files_edited": saved_files,
            "success": True
        }

    async def _handle_joint_generation(
        self,
        skill_name: str,
        user_msg: str,
        file_plan: Dict[str, Any],
        files_content: Dict[str, str],
        file_manager,
    ) -> List[str]:
        """Joint generation of skill.md + main.py in a single LLM call.

        Frontmatter is generated by code. LLM only writes the markdown body.
        Python code is validated and retried if needed.
        """
        saved_files = []

        # Extract existing skill.md body (strip frontmatter if present)
        import re
        existing_body = files_content.get("skill.md", "")
        fm_match = re.match(r"^---\n.*?\n---\n", existing_body, re.DOTALL)
        if fm_match:
            existing_body = existing_body[fm_match.end():]

        # Step A: Joint LLM call for skill.md body + main.py
        joint_prompt = self._build_joint_generation_prompt(
            skill_name, user_msg, file_plan, existing_body
        )
        joint_response = await self.llm_service.chat(joint_prompt, use_tools=False)
        joint_result = self._parse_joint_response(joint_response)

        # Step B: Build skill.md with programmatic frontmatter
        if joint_result.get("skill_md_body"):
            skill_md_content = self._build_skill_md_from_intent(
                file_plan, skill_name, joint_result["skill_md_body"]
            )
            success = file_manager.write_file(
                skill_name, "skill.md", skill_md_content, SkillSource.USER
            )
            if success:
                saved_files.append("skill.md")
                logger.info("Saved skill.md (frontmatter generated by code)")

        # Step C: Validate and save main.py
        if joint_result.get("main_py"):
            content = await self._validate_and_retry_python(
                joint_result["main_py"], user_msg
            )
            success = file_manager.write_file(
                skill_name, "main.py", content, SkillSource.USER
            )
            if success:
                saved_files.append("main.py")
                logger.info("Saved main.py (validated)")

        # Step D: Generate remaining non-joint files (requirements.txt, README.md, etc.)
        all_edit_files = file_plan.get("files", [])
        remaining = [f for f in all_edit_files if f not in ("skill.md", "main.py", "script.py")]
        for filename in remaining:
            content = await self._generate_single_file(
                filename, skill_name, user_msg, files_content
            )
            if content is not None:
                success = file_manager.write_file(
                    skill_name, filename, content, SkillSource.USER
                )
                if success:
                    saved_files.append(filename)
                    logger.info(f"Saved {filename}")

        return saved_files

    async def _handle_single_file_generation(
        self,
        skill_name: str,
        user_msg: str,
        file_plan: Dict[str, Any],
        files_content: Dict[str, str],
        file_manager,
        script_type: str,
    ) -> List[str]:
        """Generate files one by one (for non-Python skills or edit-only mode)."""
        saved_files = []
        files_to_edit = file_plan.get("files", [])
        skill_md_content = files_content.get("skill.md", "")

        for filename in files_to_edit:
            logger.info(f"Generating {filename}...")

            if filename == "skill.md":
                # For prompt-only skills: generate full skill.md with code-generated frontmatter
                if script_type == "prompt-only":
                    prompt = self._build_skill_md_body_prompt(
                        skill_name, user_msg, files_content.get("skill.md", "")
                    )
                    body = await self.llm_service.chat(prompt, use_tools=False)
                    body = self._extract_code_from_response(body)
                    content = self._build_skill_md_from_intent(file_plan, skill_name, body)
                else:
                    # Shell/PowerShell: still generate full skill.md with code frontmatter
                    prompt = self._build_skill_md_body_prompt(
                        skill_name, user_msg, files_content.get("skill.md", "")
                    )
                    body = await self.llm_service.chat(prompt, use_tools=False)
                    body = self._extract_code_from_response(body)
                    content = self._build_skill_md_from_intent(file_plan, skill_name, body)

            elif filename in ["main.py", "script.py"]:
                if not skill_md_content:
                    skill_md_content = user_msg
                prompt = self._build_script_prompt(skill_md_content, "python")
                content = await self.llm_service.chat(prompt, use_tools=False)
                content = self._extract_code_from_response(content)
                # Validate Python code
                content = await self._validate_and_retry_python(content, skill_md_content or user_msg)
                if filename == "script.py":
                    filename = "main.py"

            elif filename in ["main.sh", "script.sh"]:
                if not skill_md_content:
                    skill_md_content = user_msg
                prompt = self._build_script_prompt(skill_md_content, "shell")
                content = await self.llm_service.chat(prompt, use_tools=False)
                content = self._extract_code_from_response(content)
                # Validate shell script
                content = await self._validate_and_retry_script(content, skill_md_content or user_msg, "shell")

            elif filename in ["main.ps1", "script.ps1"]:
                if not skill_md_content:
                    skill_md_content = user_msg
                prompt = self._build_script_prompt(skill_md_content, "powershell")
                content = await self.llm_service.chat(prompt, use_tools=False)
                content = self._extract_code_from_response(content)
                # Validate PowerShell script
                content = await self._validate_and_retry_script(content, skill_md_content or user_msg, "powershell")

            else:
                content = await self._generate_single_file(
                    filename, skill_name, user_msg, files_content
                )
                if content is None:
                    continue

            success = file_manager.write_file(skill_name, filename, content, SkillSource.USER)
            if success:
                saved_files.append(filename)
                logger.info(f"Saved {filename}")

        return saved_files

    async def _generate_single_file(
        self,
        filename: str,
        skill_name: str,
        user_msg: str,
        files_content: Dict[str, str],
    ) -> Optional[str]:
        """Generate a single non-core file (requirements.txt, README.md, etc.)."""
        if filename == "requirements.txt":
            prompt = self._build_requirements_prompt_simple(skill_name, user_msg, files_content.get("requirements.txt", ""))
        elif filename == "README.md":
            prompt = self._build_readme_prompt_simple(skill_name, user_msg, files_content.get("README.md", ""))
        else:
            prompt = self._build_generic_file_prompt_simple(filename, skill_name, user_msg, files_content.get(filename, ""))

        content = await self.llm_service.chat(prompt, use_tools=False)
        content = self._extract_code_from_response(content)
        return content

    def _build_skill_md_body_prompt(
        self,
        skill_name: str,
        user_instruction: str,
        existing_content: str,
    ) -> str:
        """Build prompt for generating skill.md body only (no frontmatter).

        Frontmatter will be injected programmatically by _build_skill_md_from_intent.
        """
        if existing_content:
            # Strip existing frontmatter for the prompt
            import re
            fm_match = re.match(r"^---\n.*?\n---\n", existing_content, re.DOTALL)
            body_only = existing_content[fm_match.end():] if fm_match else existing_content

            return f"""你是一个专业的技能文档作家。请根据用户需求编辑这个skill.md的文档主体部分。

技能名称：{skill_name}
用户需求：{user_instruction}

当前skill.md文档主体：
{body_only}

请输出完整的、改进后的 markdown 文档主体（不要写 YAML frontmatter，系统会自动添加）。
直接输出内容，不要解释。"""
        else:
            return f"""你是一个专业的技能文档作家。请为一个新技能创建skill.md的文档主体部分。

技能名称：{skill_name}
用户需求：{user_instruction}

请创建完整的 markdown 文档主体（不要写 YAML frontmatter，系统会自动添加），包含：
1. "## 你的角色"：说明这个技能的作用
2. "## 能力范围"：用列表列出功能
3. "## 注意事项"：使用注意（如有）

直接输出内容，不要解释。"""

    def _build_chat_response(self, saved_files: List[str], script_type: str) -> str:
        """Build the user-facing response message."""
        if not saved_files:
            return "好的，我明白了！"

        response_msg = "好的！我已经帮你完成了以下工作：\n\n"
        response_msg += "📝 已编辑/创建的文件：\n"
        for fname in saved_files:
            response_msg += f"  • {fname}\n"

        script_files = [f for f in saved_files if f.endswith(('.py', '.sh', '.ps1'))]
        if script_files:
            script_type_desc = {
                "python": "Python脚本",
                "shell": "Shell脚本",
                "powershell": "PowerShell脚本"
            }.get(script_type, "脚本")
            response_msg += f"\n💡 脚本类型：{script_type_desc}"

        if "skill.md" in saved_files:
            response_msg += "\n\n✅ 技能已完善！现在你可以点击'测试'按钮来测试这个技能了。"
        else:
            response_msg += "\n\n✅ 文件已保存！"

        return response_msg

    async def _plan_skill_files(
        self,
        skill_name: str,
        user_msg: str,
        current_files: Dict[str, str],
        current_file: Optional[str]
    ) -> Dict[str, Any]:
        """
        Use LLM to intelligently plan what files and script type are needed.
        Returns: {"files": [...], "script_type": "python|shell|powershell|prompt-only"}
        """
        files_list = "\n".join([f"- {fname}" for fname in current_files.keys()]) if current_files else "（没有现有文件）"
        current_file_note = f"\n\n用户当前正在查看文件：{current_file}" if current_file else ""

        prompt = f"""你是一个专业的AI技能设计师。请根据用户需求，为技能「{skill_name}」规划需要创建/编辑的文件。

用户需求："{user_msg}"{current_file_note}

当前技能目录中的文件：
{files_list}

请分析用户需求，决定需要创建哪些文件，以及使用什么类型的脚本。

## 技能类型判断

根据需求复杂度，选择合适的实现方式：

1. **纯提示词型（prompt-only）**：简单的角色扮演、问答、建议类技能
   - 只需：skill.md
   - 不需要任何脚本

2. **Shell/PowerShell脚本型**：简单的系统命令（关机、重启、打开应用等）
   - Linux/Mac：skill.md + main.sh
   - Windows：skill.md + main.ps1
   - 直接执行系统命令，无需Python

3. **Python脚本型**：需要复杂逻辑、API调用、数据处理的技能
   - 需要：skill.md + main.py
   - 包含execute()函数

4. **混合型**：既有复杂逻辑又调用系统命令
   - 需要：skill.md + main.py + (可选的shell脚本)

## 文件规划

请按以下JSON格式输出（只返回JSON，不要任何其他内容）：

{{
    "thinking": "你对需求的理解和分析（1-2句话）",
    "skill_type": "prompt-only | shell | python | mixed",
    "description": "一句话描述这个技能的功能",
    "tags": ["标签1", "标签2"],
    "tools": ["需要的工具名列表，如 web_search, read_file"],
    "requirements": ["Python依赖包，如 requests>=2.31.0，无依赖则为空数组"],
    "files": ["需要创建/编辑的文件列表"],
    "script_type": "python | shell | powershell | prompt-only",
    "reason": "为什么选择这个方案"
}}

注意：
- 如果skill_type是"shell"，Linux/Mac使用main.sh，Windows使用main.ps1
- 如果skill_type是"python"，使用main.py
- 如果skill_type是"prompt-only"，files只需要["skill.md"]
- 如果skill_type是"mixed"，files包含skill.md + main.py + 可能的shell脚本
- 脚本类型script_type用于决定生成什么类型的执行脚本

现在请输出JSON："""

        try:
            response = await self.llm_service.chat(prompt, use_tools=False)
            # Try to parse as JSON
            import json
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                plan = json.loads(json_match.group())
                logger.info(f"LLM file plan: {plan}")
                return plan
        except Exception as e:
            logger.warning(f"Failed to parse LLM plan response: {e}")

        # Fallback to default: skill.md + main.py
        return {
            "thinking": "使用默认方案",
            "skill_type": "python",
            "files": ["skill.md", "main.py"],
            "script_type": "python",
            "reason": "默认使用Python脚本"
        }

    def _detect_script_type_from_files(self, files: List[str]) -> str:
        """Detect script type from file list"""
        if any(f.endswith(('.ps1',)) for f in files):
            return "powershell"
        if any(f.endswith(('.sh',)) for f in files):
            return "shell"
        if any(f.endswith('.py') for f in files):
            return "python"
        return "python"

    def _build_decision_prompt(self, skill_name: str, user_msg: str, current_files: Dict[str, str]) -> str:
        """Build prompt to let LLM decide what files to edit"""
        files_list = "\n".join([f"- {fname}" for fname in current_files.keys()]) if current_files else "（没有文件）"

        return f"""你是一个专业的技能编辑器助手。用户正在编辑技能：{skill_name}

当前技能目录中的文件：
{files_list}

用户说："{user_msg}"

请分析用户需求，决定需要编辑哪些文件。
只需要回复文件名，用空格分隔，比如：
skill.md main.py
或者只回复一个文件名。

现在请回复："""

    # ============================================
    # Joint Generation (skill.md + main.py in one LLM call)
    # ============================================

    def _build_joint_generation_prompt(
        self,
        skill_name: str,
        user_instruction: str,
        intent: Dict[str, Any],
        existing_skill_md_body: str = "",
    ) -> str:
        """Build prompt for jointly generating skill.md body + main.py.

        The LLM outputs both files in a single response, separated by markers.
        Frontmatter is NOT generated by the LLM — it is injected by code later.
        """
        description = intent.get("description", "")
        tags = intent.get("tags", [])
        tools = intent.get("tools", [])

        existing_note = ""
        if existing_skill_md_body:
            existing_note = f"""
当前skill.md内容（你可以在此基础上修改）：
{existing_skill_md_body}
"""
        return f"""你是一个专业的AI技能开发者。请根据以下需求，同时创建技能的 skill.md 文档主体和 main.py 脚本。

技能名称：{skill_name}
技能描述：{description}
标签：{tags}
工具：{tools}
用户需求：{user_instruction}
{existing_note}
## 输出格式

请严格按照以下格式输出，用标记分隔两个文件的内容：

===SKILL_MD_BODY===
（这里写 skill.md 的 markdown 主体内容，不要写 YAML frontmatter，系统会自动添加）

必须包含以下章节：
- "## 你的角色"：说明这个技能的作用
- "## 能力范围"：用列表列出功能
- "## 脚本使用说明"：说明入口函数和参数

在"脚本使用说明"中，说明：
- 入口函数：execute(context)
- context 参数是一个字典-like对象，包含：
  - "input_data": 输入数据（字典）
  - "state": 状态字典（可读写）
  - "config": 配置字典
  - "session_id": 会话ID
  - "skill_name": 技能名称
- 返回值：字典，包含 status 和 message
===MAIN_PY===
（这里写 main.py 的完整 Python 代码）

要求：
1. 必须有模块级的 execute(context) 函数
2. 使用 context["input_data"] 或 context.get("input_data", {{}}) 访问输入
3. 使用 context["state"] 访问和修改状态
4. 返回字典格式的结果，包含 "status" 和 "message"
5. 不要写 if __name__ == "__main__"
6. 要有错误处理
7. 中文注释
===END==="
"""

    def _parse_joint_response(self, response: str) -> Dict[str, str]:
        """Parse joint generation response into skill.md body and main.py content."""
        import re

        result = {}

        # Try structured format first
        skill_md_match = re.search(
            r'===SKILL_MD_BODY===\s*\n(.*?)\n\s*===MAIN_PY===',
            response, re.DOTALL
        )
        main_py_match = re.search(
            r'===MAIN_PY===\s*\n(.*?)\n\s*===END===',
            response, re.DOTALL
        )

        if not main_py_match:
            # Try without END marker
            main_py_match = re.search(
                r'===MAIN_PY===\s*\n(.*)',
                response, re.DOTALL
            )

        if skill_md_match:
            result["skill_md_body"] = skill_md_match.group(1).strip()
        if main_py_match:
            code = main_py_match.group(1).strip()
            # Strip code fences if LLM wrapped the code
            result["main_py"] = self._extract_code_from_response(code) if "```" in code else code

        # Fallback: if markers not found, try the old multi-codeblock approach
        if not result:
            files = self._parse_llm_response(response)
            if "skill.md" in files:
                result["skill_md_body"] = files["skill.md"]
            if "main.py" in files:
                result["main_py"] = files["main.py"]

        return result

    # ============================================
    # Frontmatter Generation (code, not LLM)
    # ============================================

    def _build_skill_md_from_intent(
        self,
        intent: Dict[str, Any],
        skill_name: str,
        body_markdown: str,
    ) -> str:
        """Build a complete skill.md from LLM-generated intent + body.

        Frontmatter is generated programmatically, guaranteeing valid YAML.
        The LLM only provides the markdown body content.

        Args:
            intent: Dict with keys: description, skill_type, tags, tools,
                    requirements, author, script_files
            skill_name: The skill's directory/name
            body_markdown: The markdown body (no frontmatter) from LLM

        Returns:
            Complete skill.md string with valid YAML frontmatter
        """
        import yaml

        frontmatter = {
            "name": skill_name,
            "version": "1.0.0",
            "description": intent.get("description", ""),
            "author": intent.get("author", "用户"),
            "tags": [str(t) for t in intent.get("tags", ["custom"])],
            "tools": [str(t) for t in intent.get("tools", [])],
        }

        # Add requirements only if non-empty
        requirements = [str(r) for r in intent.get("requirements", [])]
        if requirements:
            frontmatter["requirements"] = requirements

        # Add entrypoint and files based on skill_type
        skill_type = intent.get("skill_type", "prompt-only")
        script_files = intent.get("script_files", intent.get("files", []))

        if skill_type in ("python", "mixed") and "main.py" in script_files:
            frontmatter["entrypoint"] = "main.py"
            frontmatter["files"] = [f for f in script_files if f != "skill.md"]
        elif skill_type == "shell" and any(f.endswith(".sh") for f in script_files):
            sh_file = next(f for f in script_files if f.endswith(".sh"))
            frontmatter["entrypoint"] = sh_file
            frontmatter["files"] = [f for f in script_files if f != "skill.md"]
        elif skill_type == "powershell" and any(f.endswith(".ps1") for f in script_files):
            ps1_file = next(f for f in script_files if f.endswith(".ps1"))
            frontmatter["entrypoint"] = ps1_file
            frontmatter["files"] = [f for f in script_files if f != "skill.md"]

        # Serialize frontmatter with yaml.dump (guarantees valid YAML)
        fm_str = yaml.dump(
            frontmatter,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False
        ).strip()

        return f"---\n{fm_str}\n---\n\n{body_markdown.lstrip()}"

    def _build_retry_prompt(self, failed_code: str, errors: str, skill_description: str, script_type: str = "python") -> str:
        """Build prompt for LLM to fix validation errors"""
        lang_label = {"python": "Python", "shell": "Shell", "powershell": "PowerShell"}.get(script_type, "Python")
        lang_tag = {"python": "python", "shell": "bash", "powershell": "powershell"}.get(script_type, "python")

        extra_note = ""
        if script_type == "python":
            extra_note = "\n必须包含 execute(context) 函数。"
        elif script_type == "shell":
            extra_note = (
                "\n重要注意事项：\n"
                "- 使用 #!/bin/bash 开头。\n"
                "- 必须通过 $INPUT_DATA 环境变量读取输入数据。\n"
                "- 使用 grep/sed/jq 等标准工具解析 JSON。"
            )
        elif script_type == "powershell":
            extra_note = (
                "\n重要注意事项：\n"
                "- 通过 $env:INPUT_DATA 读取输入数据（JSON格式），用 ConvertFrom-Json 解析。\n"
                "- 用 try/catch 处理错误。\n"
                "- 用 Write-Error 输出错误，Write-Host 输出提示。\n"
                "- 用 exit 0 表示成功，exit 1 表示失败。"
            )

        return f"""你之前生成的{lang_label}代码存在以下问题，请修复：

{errors}

原始代码：
```{lang_tag}
{failed_code}
```

技能描述：{skill_description}
{extra_note}

请输出修复后的完整{lang_label}代码。
直接输出代码，不要解释，不要markdown格式包裹。"""

    async def _validate_and_retry_python(self, code: str, skill_description: str) -> str:
        """Validate Python code and retry with LLM if validation fails.

        Args:
            code: Generated Python code
            skill_description: Description for retry prompt context

        Returns:
            Validated (and possibly retried) Python code
        """
        validator = SkillCodeValidator()
        validation_errors = validator.validate_python(code)

        if not validation_errors:
            return code

        # Retry with error feedback
        for retry in range(validator.MAX_RETRIES):
            error_msg = "\n".join(f"- {e}" for e in validation_errors)
            logger.warning(f"Python validation failed (attempt {retry + 1}): {error_msg}")

            retry_prompt = self._build_retry_prompt(code, error_msg, skill_description, "python")
            code = await self.llm_service.chat(retry_prompt, use_tools=False)
            code = self._extract_code_from_response(code)

            validation_errors = validator.validate_python(code)
            if not validation_errors:
                logger.info(f"Validation passed on retry {retry + 1}")
                return code

        # Still failing after retries — save anyway and warn
        error_msg = "; ".join(validation_errors)
        logger.warning(f"Code validation failed after {validator.MAX_RETRIES} retries: {error_msg}")
        return code

    async def _validate_and_retry_script(self, code: str, skill_description: str, script_type: str) -> str:
        """Validate shell/powershell script and retry with LLM if validation fails.

        Args:
            code: Generated script code
            skill_description: Description for retry prompt context
            script_type: "shell" or "powershell"

        Returns:
            Validated (and possibly retried) script code
        """
        validator = SkillCodeValidator()
        validate_map = {
            "shell": validator.validate_shell,
            "powershell": validator.validate_powershell,
        }
        validate_fn = validate_map.get(script_type, validator.validate_shell)
        validation_errors = validate_fn(code)

        if not validation_errors:
            return code

        # Retry with error feedback
        for retry in range(validator.MAX_RETRIES):
            error_msg = "\n".join(f"- {e}" for e in validation_errors)
            logger.warning(f"{script_type} validation failed (attempt {retry + 1}): {error_msg}")

            retry_prompt = self._build_retry_prompt(code, error_msg, skill_description, script_type)
            code = await self.llm_service.chat(retry_prompt, use_tools=False)
            code = self._extract_code_from_response(code)

            validation_errors = validate_fn(code)
            if not validation_errors:
                logger.info(f"{script_type} validation passed on retry {retry + 1}")
                return code

        # Still failing after retries — save anyway and warn
        error_msg = "; ".join(validation_errors)
        logger.warning(f"{script_type} validation failed after {validator.MAX_RETRIES} retries: {error_msg}")
        return code

    def _build_script_prompt(self, skill_md_or_description: str, script_type: str) -> str:
        """
        Build prompt to generate script based on type.

        Args:
            skill_md_or_description: The skill description or skill.md content
            script_type: "python", "shell", "powershell"
        """
        if script_type == "python":
            return f"""你是一个专业的Python开发者。请根据以下描述创建技能的main.py脚本文件。

## 技能描述

{skill_md_or_description}

## 编码要求

1. 脚本中必须有一个模块级的 execute(context) 函数作为入口
2. context 参数是一个字典-like对象，包含以下键：
   - "input_data": 输入数据（字典）
   - "state": 状态字典（可读写）
   - "config": 配置字典
   - "session_id": 会话ID
   - "skill_name": 技能名称
   使用 context["input_data"] 或 context.get("input_data", {{}}) 来访问。
3. 返回字典格式的结果，包含 "status" 和 "message"
4. 你可以自由定义辅助类和内部函数来组织代码，但入口函数必须是模块级函数
5. 不要写 if __name__ == "__main__"
6. 如果需要外部库，在注释中标明，但不要import不存在的库
7. 中文注释
8. 代码要简洁实用，不要过度设计
9. 直接输出完整Python代码，不要markdown格式包裹，不要解释"""

        elif script_type == "shell":
            return f"""你是一个专业的Shell脚本开发者。请根据以下描述创建一个shell脚本（main.sh）。

描述：
{skill_md_or_description}

要求：
1. 如果需要参数，通过环境变量 INPUT_DATA 获取（JSON格式）
2. 错误处理要完善
3. 脚本要有中文注释说明
4. 使用#!/bin/bash开头
5. 确保脚本可以直接运行

直接输出完整的shell脚本，不要解释，不要markdown格式！"""

        elif script_type == "powershell":
            return f"""你是一个专业的 PowerShell 开发者。请根据以下描述创建一个 PowerShell 脚本（main.ps1）。

描述：
{skill_md_or_description}

要求：
1. 通过 $env:INPUT_DATA 获取输入（JSON格式），用 ConvertFrom-Json 解析
2. 错误处理要完善（try/catch）
3. 脚本要有中文注释说明
4. 用 exit 0 表示成功，exit 1 表示失败
5. 用 Write-Host 输出提示信息，用 Write-Error 输出错误（写到stderr）
6. 需要执行外部操作时用 Start-Process

示例模板（解析 url 字段并打开浏览器）：
```powershell
if (-not $env:INPUT_DATA) {{
    Write-Error "INPUT_DATA not set"
    exit 1
}}
$json = $env:INPUT_DATA | ConvertFrom-Json
$url = $json.url
if (-not $url) {{
    Write-Error "url field missing"
    exit 1
}}
Start-Process $url
exit 0
```

直接输出完整的 PowerShell 脚本，不要解释，不要markdown格式！"""

        else:
            return self._build_script_prompt(skill_md_or_description, "python")

    def _build_chat_system_prompt(
        self,
        skill_name: Optional[str],
        current_file: Optional[str],
        file_content: Optional[str]
    ) -> str:
        """Build system prompt for chat"""
        context_parts = [
            "你是一个专业的 AI 助手，专门帮助用户编写和改进 Skill。",
            "你可以：",
            "1. 帮助用户设计 Skill 的功能",
            "2. 解释如何编写 skill.md 描述文件",
            "3. 帮助编写和调试 Python 代码",
            "4. 提供最佳实践建议",
        ]

        if skill_name:
            context_parts.append(f"\n当前正在编辑的 Skill：{skill_name}")
        if current_file:
            context_parts.append(f"当前文件：{current_file}")
        if file_content:
            context_parts.append(f"当前文件内容：\n```\n{file_content}\n```")

        context_parts.append("\n请用友好、专业的方式回答用户的问题。")
        return "\n".join(context_parts)

    def _build_file_decision_prompt(self, skill_name: str, user_msg: str, current_files: Dict[str, str], current_file: Optional[str]) -> str:
        """Ask LLM what files are needed"""
        files_list = "\n".join([f"- {fname}" for fname in current_files.keys()]) if current_files else "（没有现有文件）"

        current_file_note = f"\n\n用户当前正在查看文件：{current_file}" if current_file else ""

        return f"""用户正在编辑技能：{skill_name}

当前技能目录中的文件：
{files_list}{current_file_note}

用户说："{user_msg}"

请分析：完成用户的需求，需要创建或编辑哪些文件？

只返回文件名列表，每行一个，例如：
skill.md
main.py

或者用逗号分隔：
skill.md, main.py

不要解释，只返回文件名！"""

    def _parse_file_list(self, response: str, current_file: Optional[str], user_msg: str) -> List[str]:
        """Parse the file list from LLM response"""
        import re

        files = []

        # Split by lines or commas
        lines = re.split(r'[,\n]', response)
        for line in lines:
            line = line.strip()
            # Skip empty lines and numbers
            if not line or re.match(r'^\d+[\.\)]?\s*$', line):
                continue
            # Clean up
            line = re.sub(r'^\d+[\.\)]?\s*', '', line)
            line = line.strip('*-• ')
            # Check if it looks like a filename
            if '.' in line or line in ['skill.md', 'main.py', 'requirements.txt', 'README.md']:
                if line not in files:
                    files.append(line)

        # If no files found, use defaults
        if not files:
            user_msg_lower = user_msg.lower()
            # If user is editing a specific file and not asking to "完善" or "create" whole skill
            if current_file and not any(k in user_msg_lower for k in ['完善', '完整', '创建', 'create', 'complete']):
                files = [current_file]
            else:
                files = ['skill.md', 'main.py']
                if any(k in user_msg_lower for k in ['依赖', 'requirement', 'library', 'package']):
                    files.append('requirements.txt')

        return files

    def _build_requirements_prompt_simple(self, skill_name: str, user_msg: str, existing_content: str) -> str:
        """Build prompt for requirements.txt"""
        return f"""请为技能"{skill_name}"生成requirements.txt文件。

用户需求：{user_msg}

当前内容：
{existing_content or "(没有)"}

请输出requirements.txt内容，每行一个包，例如：
requests>=2.31.0
screen-brightness-control>=0.2.0

直接输出，不要解释！"""

    def _build_readme_prompt_simple(self, skill_name: str, user_msg: str, existing_content: str) -> str:
        """Build prompt for README.md"""
        return f"""请为技能"{skill_name}"生成README.md文件。

用户需求：{user_msg}

当前内容：
{existing_content or "(没有)"}

请输出README.md内容，包含：
1. 技能简介
2. 功能说明
3. 使用方法

用中文，直接输出，不要解释！"""

    def _build_generic_file_prompt_simple(self, filename: str, skill_name: str, user_msg: str, existing_content: str) -> str:
        """Build prompt for generic files"""
        return f"""请为技能"{skill_name}"生成/编辑文件：{filename}

用户需求：{user_msg}

当前内容：
{existing_content or "(没有)"}

直接输出文件内容，不要解释！"""

    def _get_fallback_chat_response(self, user_message: str) -> str:
        """Fallback chat response when LLM is not available"""
        return "抱歉，LLM服务未配置或不可用。请先配置API密钥。"


# Global instance
_skill_writer: Optional[SkillWriterService] = None


def get_skill_writer_service() -> SkillWriterService:
    """Get or create the global SkillWriterService"""
    global _skill_writer
    if _skill_writer is None:
        _skill_writer = SkillWriterService()
    return _skill_writer
