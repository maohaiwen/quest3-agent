"""File system tool service for local file operations — sandboxed"""
import os
from pathlib import Path
from typing import List, Dict, Any

from app.config import settings
from app.tools.base import BaseToolService, MCPTool


class FileSystemToolService(BaseToolService):
    """File system tool service — restricted to TOOL_SANDBOX_DIR"""

    service_name = "FileSystem"
    service_description = "Read/write local files, list directory contents (sandboxed)"
    deps = []

    def __init__(self, base_path: str | None = None):
        """Initialize file system tool service.

        Args:
            base_path: Override for sandbox directory. Defaults to TOOL_SANDBOX_DIR setting.
        """
        self.base_path = (Path(base_path) if base_path else Path(settings.TOOL_SANDBOX_DIR)).resolve()
        # Ensure sandbox directory exists
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, file_path: str) -> Path:
        """Resolve a path and ensure it does not escape the sandbox.

        Args:
            file_path: Relative path within the sandbox.

        Returns:
            Absolute path within the sandbox.

        Raises:
            ValueError: If the path would escape the sandbox.
        """
        # Block common escape patterns
        parts = Path(file_path).parts
        if ".." in parts:
            raise ValueError(f"Path traversal not allowed: '{file_path}'")

        # Normalize: strip leading slashes to prevent absolute-path escape
        clean = file_path.lstrip("/\\")

        if not clean:
            return self.base_path

        resolved = (self.base_path / clean).resolve()

        # Verify the resolved path is still under base_path
        try:
            resolved.relative_to(self.base_path)
        except ValueError:
            raise ValueError(
                f"Path '{file_path}' escapes sandbox directory '{self.base_path}'"
            )

        return resolved

    async def read_file(self, file_path: str) -> str:
        """Read file content.

        Args:
            file_path: Path relative to sandbox root.

        Returns:
            File content.
        """
        full_path = self._resolve_safe_path(file_path)

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise ValueError(f"File not found: {file_path}")
        except Exception as e:
            raise ValueError(f"Error reading file: {e}")

    async def write_file(self, file_path: str, content: str) -> str:
        """Write content to file.

        Args:
            file_path: Path relative to sandbox root.
            content: Content to write.

        Returns:
            Success message.
        """
        full_path = self._resolve_safe_path(file_path)

        # Create directory if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            raise ValueError(f"Error writing file: {e}")

    async def list_directory(self, directory_path: str = ".") -> List[str]:
        """List directory contents.

        Args:
            directory_path: Path relative to sandbox root (default: sandbox root).

        Returns:
            List of file/directory names.
        """
        full_path = self._resolve_safe_path(directory_path)

        try:
            return os.listdir(full_path)
        except FileNotFoundError:
            raise ValueError(f"Directory not found: {directory_path}")
        except Exception as e:
            raise ValueError(f"Error listing directory: {e}")

    def get_tools(self) -> Dict[str, MCPTool]:
        """Get available file system tools."""
        return {
            "read_file": MCPTool(
                name="read_file",
                description="Read file content within the sandbox workspace",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "File path relative to sandbox root",
                        }
                    },
                    "required": ["file_path"],
                },
                handler=self.read_file,
            ),
            "write_file": MCPTool(
                name="write_file",
                description="Write content to a file within the sandbox workspace",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "File path relative to sandbox root",
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write",
                        },
                    },
                    "required": ["file_path", "content"],
                },
                handler=self.write_file,
            ),
            "list_directory": MCPTool(
                name="list_directory",
                description="List files and subdirectories within the sandbox workspace",
                input_schema={
                    "type": "object",
                    "properties": {
                        "directory_path": {
                            "type": "string",
                            "description": "Directory path relative to sandbox root (default: root)",
                            "default": ".",
                        }
                    },
                    "required": [],
                },
                handler=self.list_directory,
            ),
        }
