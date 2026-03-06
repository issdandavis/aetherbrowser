"""
Browser Bridge — HydraHand + PollyVision + ResearchFunnel Integration
======================================================================

Provides a high-level interface for serve.py to dispatch browser research
and persist results. Falls back gracefully when Playwright isn't installed.

Usage:
    bb = BrowserBridge()
    report = await bb.research("AI safety benchmarks")
    # report.extractions, report.structured, report.funnel_receipt
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aetherbrowser.browser_bridge")

# Whether the heavy deps are available
_PLAYWRIGHT_AVAILABLE = False
_HYDRA_HAND_CLASS = None

try:
    from src.browser.hydra_hand import HydraHand as _HH
    _HYDRA_HAND_CLASS = _HH
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.info("HydraHand not available (playwright not installed). Browser research disabled.")

try:
    from src.browser.research_funnel import ResearchFunnel
except ImportError:
    ResearchFunnel = None  # type: ignore


@dataclass
class BrowserResearchReport:
    """Result of a browser-backed research run."""
    query: str
    extractions: List[Dict[str, Any]] = field(default_factory=list)
    urls_discovered: int = 0
    urls_safe: int = 0
    urls_blocked: int = 0
    structured: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    funnel_receipt: Optional[Dict[str, Any]] = None
    used_browser: bool = False
    error: Optional[str] = None


class BrowserBridge:
    """
    High-level interface for browser research + persistence.

    If Playwright/HydraHand is available, launches a real 6-finger browser
    squad. Otherwise returns an error report indicating the fallback.
    """

    def __init__(self, persist: bool = True):
        self._persist = persist
        self._funnel = None
        if ResearchFunnel is not None and persist:
            try:
                self._funnel = ResearchFunnel()
            except Exception as e:
                logger.warning(f"ResearchFunnel init failed: {e}")

    @staticmethod
    def is_available() -> bool:
        """Check if browser research is available."""
        return _PLAYWRIGHT_AVAILABLE

    async def research(
        self,
        query: str,
        max_urls: int = 5,
        head_id: str = "sidebar",
    ) -> BrowserResearchReport:
        """
        Run a full HydraHand research pipeline.

        Args:
            query: Search query
            max_urls: Max URLs to extract from
            head_id: HydraHand instance ID

        Returns:
            BrowserResearchReport with extractions and optional funnel receipt
        """
        if not _PLAYWRIGHT_AVAILABLE or _HYDRA_HAND_CLASS is None:
            return BrowserResearchReport(
                query=query,
                used_browser=False,
                error="Playwright not installed. Run: pip install playwright && playwright install chromium",
            )

        report = BrowserResearchReport(query=query, used_browser=True)

        try:
            async with _HYDRA_HAND_CLASS(head_id=head_id) as hand:
                raw = await hand.research(query, max_urls=max_urls)

            report.extractions = raw.get("extractions", [])
            report.urls_discovered = len(raw.get("urls_discovered", []))
            report.urls_safe = len(raw.get("urls_safe", []))
            report.urls_blocked = len(raw.get("urls_blocked", []))
            report.structured = raw.get("structured", {})
            report.elapsed_ms = raw.get("elapsed_ms", 0)

            # Persist via ResearchFunnel
            if self._funnel and report.extractions:
                try:
                    receipt = await self._funnel.push(raw)
                    report.funnel_receipt = {
                        "run_id": receipt.run_id,
                        "records_written": receipt.records_written,
                        "local_path": receipt.local_path,
                        "notion_url": receipt.notion_url,
                        "hf_committed": receipt.hf_committed,
                        "errors": receipt.errors,
                    }
                except Exception as e:
                    logger.warning(f"Funnel push failed: {e}")
                    report.funnel_receipt = {"error": str(e)}

        except Exception as e:
            report.error = str(e)
            logger.error(f"HydraHand research failed: {e}")

        return report

    async def persist_extractions(
        self,
        extractions: List[Dict[str, Any]],
        query: str = "manual",
    ) -> Optional[Dict[str, Any]]:
        """Persist arbitrary extractions to the funnel."""
        if not self._funnel:
            return None

        research_dict = {"query": query, "extractions": extractions}
        try:
            receipt = await self._funnel.push(research_dict)
            return {
                "run_id": receipt.run_id,
                "records_written": receipt.records_written,
                "local_path": receipt.local_path,
            }
        except Exception as e:
            logger.warning(f"persist_extractions failed: {e}")
            return {"error": str(e)}
