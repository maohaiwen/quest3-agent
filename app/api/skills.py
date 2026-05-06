"""Skill API endpoints"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Request

from pydantic import BaseModel, Field
from app.models.skill import (
    Skill,
    SkillSummary,
    SkillCreate,
    SkillUpdate,
    AgentSkillLink,
    SkillExecuteRequest,
    SkillScaffoldRequest,
    SkillGenerateRequest,
    SkillCompleteRequest,
    SkillTestRequest,
    SkillSource,
    ChatRequest,
    ChatMessage,
)

# Skill management services
from app.skills.file_manager import get_skill_file_manager
from app.skills.skill_writer import get_skill_writer_service
from app.database.connection import DatabaseConnection
from app.database.skill_repository import SkillRepository
from app.config import settings
from app.skills.registry import get_skill_registry
from app.core.tool_manager import get_tool_manager


class GitHubImportRequest(BaseModel):
    """Request model for GitHub import"""
    repo_url: str = Field(..., description="GitHub repository URL or path")
    ref: str = Field(default="", description="Branch, tag, or commit hash (optional)")
    subdir: str = Field(default="", description="Subdirectory within repo (optional)")
    auto_enable: bool = Field(default=True, description="Auto-enable imported skills")
    force_refresh: bool = Field(default=False, description="Force re-clone even if cached")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Initialization flag
_initialized = False


async def initialize_skills():
    """Initialize skills - called from main app lifespan"""
    global _initialized
    if _initialized:
        return

    db = DatabaseConnection(settings.DATABASE_URL)
    await db.initialize_schema()
    repo = SkillRepository(db)

    # Sync skills from filesystem
    base_dir = Path(__file__).parent.parent.parent
    skill_dirs = [
        str(base_dir / settings.SKILLS_BUILTIN_DIR),
        str(base_dir / settings.SKILLS_USER_DIR),
    ]

    # Ensure user skills directory exists
    (base_dir / settings.SKILLS_USER_DIR).mkdir(exist_ok=True)

    await repo.sync_from_filesystem(skill_dirs)

    # Also initialize the global registry
    from app.skills.registry import get_skill_registry
    registry = get_skill_registry()
    registry.add_skill_dir(str(base_dir / "app" / "skills" / "builtin"))
    registry.add_skill_dir(str(base_dir / "user_skills"))
    registry.initialize()

    _initialized = True
    logger.info("Skill system initialized")


def get_db() -> DatabaseConnection:
    """Get database connection"""
    return DatabaseConnection(settings.DATABASE_URL)


def get_repo(db: DatabaseConnection = Depends(get_db)) -> SkillRepository:
    """Get skill repository"""
    return SkillRepository(db)


@router.get("/", response_model=List[Skill])
async def list_skills(repo: SkillRepository = Depends(get_repo)):
    """List all available skills"""
    return await repo.get_all_skills()


@router.get("/summaries", response_model=Dict[str, SkillSummary])
async def list_skill_summaries():
    """Get skill summaries (token-efficient)"""
    registry = get_skill_registry()
    return registry.get_all_summaries()


@router.get("/available-tools")
async def list_available_tools():
    """List all available tools (local + MCP) for skill tool selection"""
    from app.services.mcp_pool import mcp_client_pool

    # Chinese display names for common local tools
    LOCAL_TOOL_DISPLAY_NAMES = {
        "read_file": "读取文件",
        "write_file": "写入文件",
        "list_directory": "列出目录",
        "web_search": "网页搜索",
        "load_skill": "加载技能",
        "execute_skill": "执行技能",
    }

    tools_list = []
    tool_manager = get_tool_manager()
    for tool_name, tool_def in tool_manager._local_tools.items():
        tools_list.append({
            "name": tool_name,
            "description": tool_def.description,
            "display_name": LOCAL_TOOL_DISPLAY_NAMES.get(tool_name, ""),
            "source": tool_def.source,
            "server_id": "local",
        })
    all_mcp_tools = await mcp_client_pool.get_all_tools()
    for tool_name, tool_info in all_mcp_tools.items():
        desc = tool_info.get("description", "")
        display = desc.split("\n")[0].strip() if desc else ""
        tools_list.append({
            "name": tool_name,
            "description": desc,
            "display_name": display or tool_name,
            "source": tool_info.get("source", "mcp"),
            "server_id": tool_info.get("server_id", ""),
            "server_name": tool_info.get("server_name", ""),
        })
    return {"tools": tools_list}


@router.post("/recommend-tools")
async def recommend_tools(request: dict):
    """AI recommends tools based on skill content"""
    from app.services.mcp_pool import mcp_client_pool
    from app.services.llm_service import llm_service

    skill_name = request.get("skill_name", "")
    skill_content = request.get("skill_content", "")

    # Collect all available tools
    tools_info = []
    tool_manager = get_tool_manager()
    for tool_name, tool_def in tool_manager._local_tools.items():
        tools_info.append({"name": tool_name, "description": tool_def.description})
    all_mcp_tools = await mcp_client_pool.get_all_tools()
    for tool_name, tool_info in all_mcp_tools.items():
        tools_info.append({
            "name": tool_name,
            "description": tool_info.get("description", ""),
        })

    if not tools_info:
        return {"recommended_tools": []}

    # Build prompt
    tools_desc = "\n".join([f"- {t['name']}: {t['description']}" for t in tools_info])
    prompt = f"""根据以下技能描述，从可用工具列表中推荐最相关的工具。只返回推荐的工具名称，用JSON数组格式返回。

技能名称：{skill_name}
技能内容：
{skill_content[:2000]}

可用工具：
{tools_desc}

请返回推荐的工具名称列表，格式：["tool_name_1", "tool_name_2"]
只返回JSON数组，不要其他内容。"""

    try:
        response_text = await llm_service._chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1024,
        )
        # Extract JSON array from response
        match = re.search(r'\[.*?\]', response_text, re.DOTALL)
        if match:
            recommended = json.loads(match.group())
            return {"recommended_tools": recommended}
    except Exception as e:
        logger.error(f"Failed to recommend tools: {e}")

    return {"recommended_tools": []}


@router.get("/{skill_name}", response_model=Skill)
async def get_skill(skill_name: str, repo: SkillRepository = Depends(get_repo)):
    """Get a skill by name"""
    skill = await repo.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.get("/{skill_name}/content")
async def get_skill_content(skill_name: str):
    """Get full skill.md content for injection"""
    registry = get_skill_registry()
    content = registry.get_skill_content(skill_name)
    if not content:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"content": content}


@router.post("/", response_model=Skill)
async def create_skill(skill_create: SkillCreate, repo: SkillRepository = Depends(get_repo)):
    """Create a new skill"""
    existing = await repo.get_skill_by_name(skill_create.name)
    if existing:
        raise HTTPException(status_code=409, detail="Skill with this name already exists")

    try:
        return await repo.create_skill(skill_create)
    except Exception as e:
        logger.error(f"Failed to create skill: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{skill_name}", response_model=Skill)
async def update_skill(skill_name: str, skill_update: SkillUpdate, repo: SkillRepository = Depends(get_repo)):
    """Update a skill"""
    skill = await repo.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        updated = await repo.update_skill(skill.id, skill_update)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update skill")
        return updated
    except Exception as e:
        logger.error(f"Failed to update skill: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str, repo: SkillRepository = Depends(get_repo)):
    """Delete a skill (both from database and filesystem)"""
    from app.skills.file_manager import get_skill_file_manager

    skill = await repo.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Delete from database
    await repo.delete_skill(skill.id)

    # Also delete from filesystem (USER skills only to be safe)
    file_manager = get_skill_file_manager()
    if skill.source == SkillSource.USER:
        # Use dir_path if available, otherwise fall back to skill_name as folder name
        if skill.dir_path:
            file_manager.delete_skill_by_path(skill.dir_path)
        else:
            file_manager.delete_skill(skill_name, SkillSource.USER)

    # Reload registry to update in-memory cache
    try:
        from app.skills.registry import get_skill_registry
        registry = get_skill_registry()
        registry.reload()
    except Exception as e:
        logger.warning(f"Could not reload registry: {e}")

    return {"message": "Skill deleted successfully"}


@router.get("/search/", response_model=List[Skill])
async def search_skills(q: str, repo: SkillRepository = Depends(get_repo)):
    """Search skills by name or description"""
    # Use registry for search (in-memory, faster)
    registry = get_skill_registry()
    if not registry._loaded:
        registry.initialize()
    return registry.search_skills(q)


# Agent-Skill association endpoints


@router.get("/agent/{agent_id}", response_model=List[Skill])
async def get_agent_skills(agent_id: str, repo: SkillRepository = Depends(get_repo)):
    """Get skills linked to an agent"""
    return await repo.get_agent_skills(agent_id)


@router.post("/agent/{agent_id}/link")
async def link_skill_to_agent(agent_id: str, skill_name: str, priority: int = 0, repo: SkillRepository = Depends(get_repo)):
    """Link a skill to an agent"""
    # First get the skill to get its ID
    skill = await repo.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    link = AgentSkillLink(
        agent_id=agent_id,
        skill_id=skill.id,
        enabled=True,
        priority=priority,
    )
    await repo.link_agent_skill(link)

    # Also link in registry too
    registry = get_skill_registry()
    registry.link_agent_skill(link)

    return {"message": "Skill linked to agent successfully"}


@router.post("/agent/{agent_id}/unlink")
async def unlink_skill_from_agent(agent_id: str, skill_name: str, repo: SkillRepository = Depends(get_repo)):
    """Unlink a skill from an agent"""
    skill = await repo.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    await repo.unlink_agent_skill(agent_id, skill.id)

    # Also unlink in registry
    registry = get_skill_registry()
    registry.unlink_agent_skill(agent_id, skill.id)

    return {"message": "Skill unlinked from agent successfully"}


@router.get("/agent/{agent_id}/system-prompt")
async def get_agent_system_prompt_addition(agent_id: str):
    """Get the system prompt addition for an agent's skills"""
    registry = get_skill_registry()
    addition = registry.get_system_prompt_addition(agent_id)
    return {"system_prompt_addition": addition}


# Skill execution endpoints


@router.post("/load")
async def load_skill(skill_name: str):
    """
    Load a skill's full content (tool for agent)

    This is the tool that agents call to load a skill's full instruction
    when they decide to use it (layer 2 loading).
    """
    registry = get_skill_registry()
    content = registry.get_skill_content(skill_name)
    if not content:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {
        "skill_name": skill_name,
        "content": content,
        "message": f"Successfully loaded skill: {skill_name}",
    }


@router.post("/reload")
async def reload_skills():
    """Reload all skills from filesystem"""
    registry = get_skill_registry()
    registry.reload()
    return {"message": "Skills reloaded successfully"}


# GitHub import endpoints


@router.post("/import/github")
async def import_from_github(
    request: GitHubImportRequest,
    repo: SkillRepository = Depends(get_repo),
):
    """
    Import skills from GitHub repository

    Supports formats:
    - github.com/owner/repo
    - github.com/owner/repo#tag
    - github.com/owner/repo/tree/main/path/to/skills
    - https://github.com/owner/repo.git
    """
    registry = get_skill_registry()

    try:
        # Build repo reference
        repo_ref = request.repo_url
        if request.ref:
            if "#" in repo_ref:
                repo_ref = repo_ref.split("#")[0]
            repo_ref += f"#{request.ref}"
        if request.subdir:
            if "#" in repo_ref:
                base, ref = repo_ref.split("#", 1)
                repo_ref = f"{base}/tree/{ref}/{request.subdir}"
            else:
                repo_ref += f"/tree/HEAD/{request.subdir}"

        # Import skills
        skills = await registry.import_from_github(
            repo_ref,
            auto_enable=request.auto_enable,
            force_refresh=request.force_refresh,
        )

        # Also persist to database if repository is available
        for skill in skills:
            # Check if skill already exists in DB
            existing = await repo.get_skill_by_name(skill.name)
            if not existing:
                from app.models.skill import SkillCreate
                skill_create = SkillCreate(
                    name=skill.name,
                    description=skill.description,
                    skill_content=skill.skill_content,
                    source=skill.source,
                )
                await repo.create_skill(skill_create)
            else:
                # Update existing skill
                from app.models.skill import SkillUpdate
                skill_update = SkillUpdate(
                    description=skill.description,
                    skill_content=skill.skill_content,
                    enabled=skill.enabled,
                )
                await repo.update_skill(existing.id, skill_update)

        # Refresh registry to ensure new skills are available
        if not registry._loaded:
            registry.initialize()

        # Also add skills to registry if not already there
        for skill in skills:
            if skill.name not in registry._skills:
                registry.add_skill(skill)

        return {
            "message": f"Successfully imported {len(skills)} skills",
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "version": s.version,
                    "author": s.author,
                }
                for s in skills
            ],
        }

    except Exception as e:
        logger.exception(f"Failed to import from GitHub: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/github/cache")
async def list_cached_repos():
    """List cached GitHub repositories"""
    registry = get_skill_registry()
    importer = registry.get_github_importer()
    cached = importer.get_cached_repos()
    return {"cached_repos": cached}


@router.post("/github/cache/clear")
async def clear_cache(cache_key: str = ""):
    """
    Clear GitHub cache

    Args:
        cache_key: Specific cache key to clear, or empty to clear all
    """
    registry = get_skill_registry()
    importer = registry.get_github_importer()
    importer.clear_cache(cache_key if cache_key else None)
    return {"message": "Cache cleared successfully"}


# ============ New Skill Management Endpoints ============

@router.get("/templates")
async def list_templates():
    """List available skill templates"""
    from app.skills.templates import list_templates
    return {"templates": list_templates()}


@router.post("/scaffold")
async def create_skill_from_template(
    request: SkillScaffoldRequest,
    repo: SkillRepository = Depends(get_repo),
):
    """Create a new skill from a template"""
    from app.skills.file_manager import get_skill_file_manager
    from app.skills.loader import SkillLoader
    from app.skills.registry import get_skill_registry

    file_manager = get_skill_file_manager()

    try:
        skill_dir = file_manager.create_skill_from_template(
            skill_name=request.name,
            template_name=request.template,
            description=request.description,
            author=request.author,
            tags=request.tags,
            tools=request.tools,
        )

        # Reload registry to pick up new skill
        registry = get_skill_registry()
        registry.reload()

        # Check if skill exists now
        new_skill = registry.get_skill(request.name)

        # Sync to database so it appears in the management page
        if new_skill:
            try:
                existing = await repo.get_skill_by_name(new_skill.name)
                if not existing:
                    skill_create = SkillCreate(
                        name=new_skill.name,
                        description=new_skill.description,
                        skill_content=new_skill.skill_content,
                        source=new_skill.source,
                    )
                    await repo.create_skill(skill_create)
                    logger.info(f"Scaffold: synced skill '{new_skill.name}' to database")
            except Exception as db_err:
                logger.warning(f"Scaffold: failed to sync skill to database: {db_err}")

        return {
            "message": f"Skill {request.name} ready",
            "skill_dir": str(skill_dir),
            "skill": new_skill,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============ Skill File Management Endpoints ============

@router.get("/{skill_name}/files")
async def list_skill_files(skill_name: str):
    """List all files in a skill directory"""
    from app.skills.file_manager import get_skill_file_manager
    from app.skills.registry import get_skill_registry

    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)

    file_manager = get_skill_file_manager()

    # 先试USER，再试BUILTIN
    if skill:
        files = file_manager.get_file_list(skill_name, skill.source)
    else:
        files = file_manager.get_file_list(skill_name, SkillSource.USER)
        if not files:
            files = file_manager.get_file_list(skill_name, SkillSource.BUILTIN)

    if not files:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {"skill_name": skill_name, "files": files}


@router.get("/{skill_name}/files/{file_path:path}")
async def read_skill_file(skill_name: str, file_path: str):
    """Read a file from a skill directory"""
    from app.skills.file_manager import get_skill_file_manager
    from app.skills.registry import get_skill_registry

    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)

    file_manager = get_skill_file_manager()

    # 尝试读取
    content = None
    if skill:
        content = file_manager.read_file(skill_name, file_path, skill.source)

    if content is None:
        content = file_manager.read_file(skill_name, file_path, SkillSource.USER)

    if content is None:
        content = file_manager.read_file(skill_name, file_path, SkillSource.BUILTIN)

    if content is None:
        raise HTTPException(status_code=404, detail="File not found")

    return {"skill_name": skill_name, "file_path": file_path, "content": content}


@router.post("/{skill_name}/files/{file_path:path}")
async def write_skill_file(
    skill_name: str,
    file_path: str,
    request: Request,
    repo: SkillRepository = Depends(get_repo),
):
    """Write a file to a skill directory"""
    from app.skills.file_manager import get_skill_file_manager
    from app.skills.registry import get_skill_registry

    content = await request.body()
    content = content.decode("utf-8")

    file_manager = get_skill_file_manager()
    # 用户技能总是写到USER目录
    success = file_manager.write_file(skill_name, file_path, content, SkillSource.USER)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to write file")

    # 重新加载技能
    try:
        registry = get_skill_registry()
        registry.reload()
    except Exception as e:
        logger.warning(f"Failed to reload registry: {e}")

    # Sync skill.md changes to database
    if file_path == "skill.md":
        try:
            registry = get_skill_registry()
            updated_skill = registry.get_skill(skill_name)
            if updated_skill:
                existing = await repo.get_skill_by_name(skill_name)
                if existing:
                    skill_update = SkillUpdate(
                        skill_content=updated_skill.skill_content,
                    )
                    await repo.update_skill(existing.id, skill_update)
                    logger.info(f"Synced skill.md changes to database for '{skill_name}'")
        except Exception as db_err:
            logger.warning(f"Failed to sync skill.md to database: {db_err}")

    return {"message": f"File {file_path} written successfully"}


@router.delete("/{skill_name}/files/{file_path:path}")
async def delete_skill_file(skill_name: str, file_path: str):
    """Delete a file from a skill directory"""
    from app.skills.file_manager import get_skill_file_manager

    file_manager = get_skill_file_manager()
    success = file_manager.delete_file(skill_name, file_path, SkillSource.USER)

    if not success:
        raise HTTPException(status_code=404, detail="File not found")

    return {"message": f"File {file_path} deleted successfully"}


@router.post("/{skill_name}/sync-to-fs")
async def sync_skill_to_filesystem(skill_name: str):
    """Sync a skill from database to filesystem"""
    from app.skills.file_manager import get_skill_file_manager
    from app.skills.registry import get_skill_registry

    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    file_manager = get_skill_file_manager()
    success = file_manager.sync_skill_to_fs(skill)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to sync skill")

    return {"message": f"Skill {skill_name} synced to filesystem successfully"}


# ============ LLM-Assisted Skill Authoring Endpoints ============

@router.post("/llm/generate")
async def generate_skill_with_llm(request: SkillGenerateRequest):
    """Generate a skill using LLM based on description"""
    writer_service = get_skill_writer_service()

    try:
        files = await writer_service.generate_skill_from_description(
            description=request.description,
            template=request.template,
            requirements=request.requirements
        )

        return {
            "message": "Skill generated successfully!",
            "files": files,
            "file_count": len(files)
        }
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/complete")
async def complete_skill_with_llm(request: SkillCompleteRequest):
    """Complete/improve a skill file using LLM"""
    writer_service = get_skill_writer_service()

    try:
        improved_content = await writer_service.complete_file(
            skill_name=request.skill_name,
            file_path=request.file_path,
            current_content=request.current_content,
            instruction=request.instruction
        )

        return {
            "message": "File completed successfully!",
            "skill_name": request.skill_name,
            "file_path": request.file_path,
            "content": improved_content
        }
    except Exception as e:
        logger.error(f"Completion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/generate-main-py")
async def generate_main_py_endpoint(skill_name: str):
    """Generate main.py based on skill.md"""
    writer_service = get_skill_writer_service()
    file_manager = get_skill_file_manager()

    try:
        # 先尝试从USER目录读取，再从BUILTIN目录
        skill_md = file_manager.read_file(skill_name, "skill.md", SkillSource.USER)
        if not skill_md:
            skill_md = file_manager.read_file(skill_name, "skill.md", SkillSource.BUILTIN)

        if not skill_md:
            raise HTTPException(status_code=404, detail="skill.md not found")

        # Generate main.py
        main_py = await writer_service.generate_main_py(skill_md)

        # Save it (总是写到USER目录)
        success = file_manager.write_file(skill_name, "main.py", main_py, SkillSource.USER)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save main.py")

        # Reload registry
        try:
            from app.skills.registry import get_skill_registry
            registry = get_skill_registry()
            registry.reload()
        except Exception as e:
            logger.warning(f"Failed to reload registry: {e}")

        return {
            "message": "main.py generated successfully!",
            "content": main_py
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate main.py: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/test")
async def test_skill_with_llm(request: SkillTestRequest):
    """Test a skill with a sample input"""
    from app.skills.executor import get_skill_executor

    executor = get_skill_executor()

    try:
        # Execute the skill - use directory name lookup
        input_data = request.input if isinstance(request.input, dict) else {"input": request.input}

        # Try to find skill by directory name first
        registry = get_skill_registry()
        skill = registry.get_skill_by_dir_name(request.skill_name)

        if not skill:
            # Fall back to normal name lookup
            skill = registry.get_skill(request.skill_name)

        if not skill:
            return {
                "skill_name": request.skill_name,
                "input": request.input,
                "result": {
                    "success": False,
                    "output": None,
                    "error": f"Skill not found: {request.skill_name}",
                    "execution_time_ms": 0,
                    "state_updates": {},
                    "logs": [f"Skill not found: {request.skill_name}"]
                },
            }

        # Use the found skill's name for execution
        result = await executor.execute(
            skill_name=skill.name,
            input_data=input_data,
            session_id=request.session_id,
        )

        return {
            "skill_name": request.skill_name,
            "input": request.input,
            "result": result,
        }
    except Exception as e:
        logger.error(f"Skill test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AIEditRequest(BaseModel):
    """Request model for AI-powered file editing"""
    skill_name: str
    instruction: str
    current_file: Optional[str] = None
    auto_save: bool = True


@router.post("/llm/edit")
async def ai_edit_files(request: AIEditRequest):
    """Let AI assistant edit files for a skill"""
    writer_service = get_skill_writer_service()
    file_manager = get_skill_file_manager()

    try:
        result = await writer_service.edit_files_with_ai(
            skill_name=request.skill_name,
            instruction=request.instruction,
            current_file=request.current_file,
            auto_save=request.auto_save,
            file_manager=file_manager
        )
        return result
    except Exception as e:
        logger.error(f"AI edit failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/chat")
async def chat_with_ai_assistant(request: ChatRequest):
    """Chat with the AI assistant for skill editing"""
    writer_service = get_skill_writer_service()

    try:
        result = await writer_service.chat(
            messages=request.messages,
            skill_name=request.skill_name,
            current_file=request.current_file,
            file_content=request.file_content,
            skill_type=request.skill_type,
        )

        return result
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        # Return fallback response
        return {
            "content": f"抱歉，我遇到了一个问题：{str(e)}。不过你可以继续告诉我你想要什么！",
            "files_edited": [],
            "success": False
        }
