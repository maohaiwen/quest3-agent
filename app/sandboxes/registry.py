"""Sandbox registry — manages sandbox types and creates instances on demand"""
import logging
from typing import Dict, List, Any, Optional, Type

from app.sandboxes.base import BaseSandbox

logger = logging.getLogger(__name__)


class SandboxRegistry:
    """Registry of available sandbox types.

    Usage::

        SandboxRegistry.register("chinese_chess", ChineseChessSandbox)
        sandbox = SandboxRegistry.create("chinese_chess")
    """

    _types: Dict[str, Type[BaseSandbox]] = {}

    @classmethod
    def register(cls, name: str, sandbox_class: Type[BaseSandbox]) -> None:
        """Register a sandbox type.

        Args:
            name: Unique identifier for the sandbox type (e.g. "chinese_chess").
            sandbox_class: A subclass of BaseSandbox.
        """
        if not issubclass(sandbox_class, BaseSandbox):
            raise TypeError(f"{sandbox_class} must be a subclass of BaseSandbox")
        cls._types[name] = sandbox_class
        logger.info(f"Registered sandbox type: {name}")

    @classmethod
    def create(cls, name: str, **kwargs) -> Optional[BaseSandbox]:
        """Create a sandbox instance by type name.

        Args:
            name: The registered sandbox type name.
            **kwargs: Additional arguments passed to the sandbox constructor.

        Returns:
            A BaseSandbox instance, or None if the name is not registered.
        """
        sandbox_class = cls._types.get(name)
        if sandbox_class is None:
            logger.warning(f"Sandbox type '{name}' not found in registry")
            return None
        return sandbox_class(**kwargs)

    @classmethod
    def list_available(cls) -> List[Dict[str, Any]]:
        """Return metadata for all registered sandbox types.

        Each entry includes ``name`` and ``description``.  Subclasses can
        override the ``description`` class attribute to customise this.
        """
        result = []
        for name, sandbox_class in cls._types.items():
            result.append({
                "name": name,
                "description": getattr(sandbox_class, "description", sandbox_class.__doc__ or ""),
            })
        return result
