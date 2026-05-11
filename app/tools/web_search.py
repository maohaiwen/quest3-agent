"""Web search tool service using Volcano Engine API"""
import json
import httpx
import logging
from typing import Dict, Any, List, Optional
from app.tools.base import BaseToolService, MCPTool
from app.config import settings

logger = logging.getLogger(__name__)


class WebSearchToolService(BaseToolService):
    """Web search tool service using Volcano Engine (火山引擎) Web Search API"""

    service_name = "网络搜索"
    service_description = "通过火山引擎搜索互联网信息，支持AI摘要和时间筛选"
    deps = []

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """Initialize web search tool service

        Args:
            api_key: Volcano Engine API key (overrides settings, for backward compat)
            base_url: Web search API endpoint (overrides settings)
        """
        self._api_key_override = api_key
        self._base_url_override = base_url

    async def _resolve_api_key(self) -> str:
        """Resolve API key: DB setting > .env > constructor arg"""
        # 1. Try DB setting first (user may have updated via settings page)
        try:
            from app.services.settings_service import settings_service
            db_value = await settings_service.get_setting("WEB_SEARCH_API_KEY")
            if db_value:
                return db_value
        except Exception:
            pass
        # 2. Constructor override, then .env
        return self._api_key_override or getattr(settings, 'WEB_SEARCH_API_KEY', '')

    async def _resolve_base_url(self) -> str:
        """Resolve base URL: DB setting > constructor override > .env"""
        try:
            from app.services.settings_service import settings_service
            db_value = await settings_service.get_setting("WEB_SEARCH_API_URL")
            if db_value:
                return db_value
        except Exception:
            pass
        return self._base_url_override or getattr(settings, 'WEB_SEARCH_API_URL', 'https://open.feedcoopapi.com/search_api/web_search')

    async def search(
        self,
        query: str,
        search_type: str = "web",
        count: int = 10,
        need_summary: bool = True,
        time_range: Optional[str] = None,
        content_formats: str = "text"
    ) -> Dict[str, Any]:
        """Search the web using Volcano Engine API

        Args:
            query: Search query (1-100 characters)
            search_type: Type of search - "web" (results only), "web_summary" (with LLM summary), or "image"
            count: Number of results to return (max 50, default 10)
            need_summary: Whether to return summary (精准摘要)
            time_range: Time range filter - "OneDay", "OneWeek", "OneMonth", "OneYear", or "YYYY-MM-DD..YYYY-MM-DD"
            content_formats: Content format - "text" or "markdown"

        Returns:
            Search results with titles, URLs, snippets, and optional summary
        """
        # Resolve API key and base URL dynamically (may have been updated in settings)
        api_key = await self._resolve_api_key()
        base_url = await self._resolve_base_url()

        if not api_key:
            return {
                "error": "Web search API key not configured",
                "results": []
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "Query": query,
            "SearchType": search_type,
            "Count": min(count, 50),
            "NeedSummary": need_summary,
            "ContentFormats": content_formats
        }

        if time_range:
            payload["TimeRange"] = time_range

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    base_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                response_text = response.text
                logger.info(f"Web search response status: {response.status_code}, body: {response_text[:500] if response_text else 'empty'}")

            # Handle SSE format - response starts with "data:" prefix and contains JSON
            # SSE format: "data:{\"json\": \"object\"}\n\n" - may have multiple chunks
            data = {}
            text = response_text.strip()
            if text.startswith("data:"):
                # Remove "data:" prefix
                json_text = text[5:].strip()
                # Use JSONDecoder to extract the first complete JSON object
                # This handles multi-line JSON and ignores subsequent chunks
                decoder = json.JSONDecoder()
                try:
                    data, end_idx = decoder.raw_decode(json_text)
                except json.JSONDecodeError:
                    # If first attempt fails, try removing subsequent data: lines
                    # Split by "data:" and try the first non-empty chunk that starts with {
                    for chunk in json_text.split("data:"):
                        chunk = chunk.strip()
                        if chunk.startswith("{"):
                            try:
                                data, _ = decoder.raw_decode(chunk)
                                break
                            except json.JSONDecodeError:
                                continue
            else:
                data = json.loads(text)

            # Check for API errors
            if "ResponseMetadata" in data and "Error" in data["ResponseMetadata"]:
                error = data["ResponseMetadata"]["Error"]
                return {
                    "error": f"API Error {error.get('CodeN', error.get('Code'))}: {error.get('Message', 'Unknown error')}",
                    "results": []
                }

            result = data.get("Result", {})

            if search_type == "image":
                return self._format_image_results(query, result)
            else:
                return self._format_web_results(query, result)

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during web search: {e.response.status_code} - {e.response.text}")
            return {
                "error": f"HTTP error: {e.response.status_code}",
                "results": []
            }
        except Exception as e:
            logger.error(f"Web search error: {e}, response body: {response_text if 'response_text' in dir() else 'N/A'}")
            return {
                "error": str(e),
                "results": []
            }

    def _format_web_results(self, query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format web search results

        Args:
            query: Original query
            result: Raw API result

        Returns:
            Formatted results
        """
        web_results = result.get("WebResults", []) or []
        formatted_results = []

        for item in web_results:
            formatted_results.append({
                "title": item.get("Title", ""),
                "site_name": item.get("SiteName", ""),
                "url": item.get("Url", ""),
                "snippet": item.get("Snippet", ""),
                "summary": item.get("Summary", ""),  # 精准摘要
                "content": item.get("Content", ""),  # Full content if available
                "publish_time": item.get("PublishTime", ""),
                "auth_level": item.get("AuthInfoDes", ""),  # 权威度
                "rank_score": item.get("RankScore", 0)
            })

        return {
            "query": query,
            "provider": "volcengine",
            "result_count": result.get("ResultCount", 0),
            "time_cost_ms": result.get("TimeCost", 0),
            "search_context": result.get("SearchContext", {}),
            "results": formatted_results
        }

    def _format_image_results(self, query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format image search results

        Args:
            query: Original query
            result: Raw API result

        Returns:
            Formatted results
        """
        image_results = result.get("ImageResults", []) or []
        formatted_results = []

        for item in image_results:
            formatted_results.append({
                "title": item.get("Title", ""),
                "site_name": item.get("SiteName", ""),
                "url": item.get("Url", ""),
                "image_url": item.get("Image", {}).get("Url", ""),
                "width": item.get("Image", {}).get("Width", 0),
                "height": item.get("Image", {}).get("Height", 0),
                "shape": item.get("Image", {}).get("Shape", ""),
                "publish_time": item.get("PublishTime", "")
            })

        return {
            "query": query,
            "provider": "volcengine",
            "result_count": result.get("ResultCount", 0),
            "time_cost_ms": result.get("TimeCost", 0),
            "results": formatted_results
        }

    def get_tools(self) -> Dict[str, MCPTool]:
        """Get available web search tools

        Returns:
            Dictionary of tool definitions
        """
        return {
            "web_search": MCPTool(
                name="web_search",
                description="搜索互联网信息，返回标题、链接和摘要，支持AI总结和时间范围筛选",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词（1-100字）"
                        },
                        "search_type": {
                            "type": "string",
                            "enum": ["web", "web_summary"],
                            "description": "搜索类型：'web'普通搜索，'web_summary'带AI总结",
                            "default": "web"
                        },
                        "count": {
                            "type": "integer",
                            "description": "返回结果数量（默认10，最多50）",
                            "default": 10
                        },
                        "need_summary": {
                            "type": "boolean",
                            "description": "是否返回AI精准摘要",
                            "default": True
                        },
                        "time_range": {
                            "type": "string",
                            "description": "时间筛选：'OneDay'/一天内，'OneWeek'/一周内，'OneMonth'/一月内，或'YYYY-MM-DD..YYYY-MM-DD'",
                            "default": None
                        }
                    },
                    "required": ["query"]
                },
                handler=self.search
            )
        }
