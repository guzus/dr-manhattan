from __future__ import annotations

from typing import Dict, List

import requests


class PolymarketBridge:
    """Bridge API mixin: cross-chain asset transfers (read-only)."""

    BRIDGE_URL = "https://bridge.polymarket.com"

    def fetch_supported_assets(self) -> List[Dict]:
        """
        Fetch supported bridge assets.

        Returns:
            List of supported asset dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BRIDGE_URL}/supported-assets", timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("supportedAssets", [])
            return []

        return _fetch()
