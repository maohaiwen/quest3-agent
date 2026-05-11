"""File system tool service for local file operations"""
import os
from typing import List, Dict, Any
from app.tools.base import BaseToolService, MCPTool


class FileSystemToolService(BaseToolService):
    """File system tool service for local file operations"""

    service_name = "文件系统"
    service_description = "读写本地文件、列出目录内容，用于需要文件操作的Agent任务"
    deps = []

    def __init__(self, base_path: str = "."):
        """Initialize file system tool service

        Args:
            base_path: Base directory for file operations
        """
        self.base_path = base_path

    async def read_file(self, file_path: str) -> str:
        """Read file content

        Args:
            file_path: Path to the file

        Returns:
            File content
        """
        full_path = os.path.join(self.base_path, file_path)

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise ValueError(f"Error reading file: {e}")

    async def write_file(self, file_path: str, content: str) -> str:
        """Write content to file

        Args:
            file_path: Path to the file
            content: Content to write

        Returns:
            Success message
        """
        full_path = os.path.join(self.base_path, file_path)

        # Create directory if needed
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            raise ValueError(f"Error writing file: {e}")

    async def list_directory(self, directory_path: str = ".") -> List[str]:
        """List directory contents

        Args:
            directory_path: Path to the directory

        Returns:
            List of file/directory names
        """
        full_path = os.path.join(self.base_path, directory_path)

        try:
            return os.listdir(full_path)
        except Exception as e:
            raise ValueError(f"Error listing directory: {e}")

    def get_tools(self) -> Dict[str, MCPTool]:
        """Get available file system tools

        Returns:
            Dictionary of tool definitions
        """
        return {
            "read_file": MCPTool(
                name="read_file",
                description="读取文件内容，返回文本字符串",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "文件路径"
                        }
                    },
                    "required": ["file_path"]
                },
                handler=self.read_file
            ),
            "write_file": MCPTool(
                name="write_file",
                description="将内容写入文件，覆盖已有内容",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "文件路径"
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的内容"
                        }
                    },
                    "required": ["file_path", "content"]
                },
                handler=self.write_file
            ),
            "list_directory": MCPTool(
                name="list_directory",
                description="列出目录下的文件和子目录",
                input_schema={
                    "type": "object",
                    "properties": {
                        "directory_path": {
                            "type": "string",
                            "description": "目录路径（默认当前目录）",
                            "default": "."
                        }
                    },
                    "required": []
                },
                handler=self.list_directory
            )
        }
