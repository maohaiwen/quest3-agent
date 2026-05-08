"""Settings management API endpoints"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import logging

from app.services.settings_service import settings_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings(group: Optional[str] = None):
    """Get all settings, with secret values masked.

    Query params:
        group: Optional filter by group name (llm / memory / search)
    """
    try:
        result = await settings_service.get_all_settings(group=group)
        return {"settings": result}
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("")
async def update_settings(request: Dict[str, Any]):
    """Batch update settings.

    Request body:
        updates: Dict of key -> new_value
        user_role: User role (only admin can modify)
    """
    try:
        updates = request.get("updates", {})
        user_role = request.get("user_role", "user")

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        result = await settings_service.update_settings(updates, user_role)

        if not result.get("success"):
            raise HTTPException(status_code=403, detail=result.get("error", "Update failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/init-status")
async def get_init_status():
    """Check if the application has been initialized.

    Returns initialized: false if critical settings (API key) are not configured,
    useful for first-time setup guidance.
    """
    try:
        initialized = await settings_service.is_initialized()
        return {"initialized": initialized}
    except Exception as e:
        logger.error(f"Error checking init status: {e}")
        # If we can't check, assume not initialized
        return {"initialized": False}


@router.get("/llm-presets")
async def get_llm_presets():
    """Get LLM provider presets for auto-filling settings in the UI.

    Returns the default base_url and model for each provider,
    so the frontend can auto-fill when the user switches provider.
    """
    from app.config import settings as cfg
    return {"presets": cfg.PROVIDER_PRESETS}


@router.post("/test-llm")
async def test_llm_connection():
    """Test LLM connection with current settings.

    Sends a simple request to verify the API key and model are working.
    """
    try:
        if not llm_service.is_configured():
            return {"success": False, "error": "LLM service not configured. Please set LLM_API_KEY and LLM_BASE_URL."}

        # Try a simple completion
        try:
            response = await llm_service._chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=10
            )
            return {
                "success": True,
                "message": "LLM connection successful",
                "response_preview": response[:50] if response else ""
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"LLM connection failed: {str(e)}"
            }
    except Exception as e:
        logger.error(f"Error testing LLM connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))
