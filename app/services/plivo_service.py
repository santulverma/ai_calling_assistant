"""
Plivo Telephony Service.
Handles outbound call triggering, Plivo XML generation, and call status events.
"""

import httpx
import logging
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

class PlivoService:
    def __init__(self):
        self.auth_id = settings.PLIVO_AUTH_ID
        self.auth_token = settings.PLIVO_AUTH_TOKEN
        self.from_number = settings.PLIVO_PHONE_NUMBER
        self.base_url = f"https://api.plivo.com/v1/Account/{self.auth_id}"

    async def initiate_outbound_call(
        self,
        to_number: str,
        lead_id: Optional[int] = None,
        custom_greeting: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Triggers an outbound call via Plivo REST API.
        When answered, Plivo will fetch the answer_url which attaches the bidirectional WebSocket.
        """
        if not self.auth_id or not self.auth_token:
            logger.warning("Plivo credentials not configured. Operating in simulation mode.")
            return {
                "status": "simulated",
                "request_uuid": "simulated-call-uuid-12345",
                "message": "Call simulated because Plivo credentials are not set in .env"
            }

        public_base = settings.PUBLIC_URL.rstrip("/")
        answer_url = f"{public_base}/plivo/answer"
        hangup_url = f"{public_base}/plivo/events"

        if lead_id:
            answer_url += f"?lead_id={lead_id}"
            hangup_url += f"?lead_id={lead_id}"

        payload = {
            "from": self.from_number,
            "to": to_number,
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": hangup_url,
            "hangup_method": "POST",
            "ring_timeout": 45,
            "time_limit": 1800,  # 30 minutes max
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/Call/",
                auth=(self.auth_id, self.auth_token),
                json=payload
            )

            if resp.status_code in [200, 201, 202]:
                data = resp.json()
                logger.info(f"Plivo call initiated successfully: {data}")
                return {
                    "status": "success",
                    "request_uuid": data.get("request_uuid"),
                    "data": data
                }
            else:
                logger.error(f"Plivo call initiation failed: {resp.status_code} - {resp.text}")
                return {
                    "status": "error",
                    "status_code": resp.status_code,
                    "error": resp.text
                }

    def generate_bidirectional_stream_xml(self, lead_id: Optional[int] = None) -> str:
        """
        Generates Plivo XML instructing Plivo to connect the caller's audio
        bidirectionally to our FastAPI WebSocket endpoint.
        """
        public_url = settings.PUBLIC_URL.rstrip("/")
        # Convert http(s) to ws(s)
        if public_url.startswith("https://"):
            ws_url = "wss://" + public_url[len("https://"):]
        elif public_url.startswith("http://"):
            ws_url = "ws://" + public_url[len("http://"):]
        elif public_url.startswith("ws://") or public_url.startswith("wss://"):
            ws_url = public_url
        else:
            ws_url = f"wss://{public_url}"

        ws_stream_endpoint = f"{ws_url}/ws/plivo"
        if lead_id:
            ws_stream_endpoint += f"?lead_id={lead_id}"

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" streamTimeout="86400" keepCallAlive="true">
        {ws_stream_endpoint}
    </Stream>
</Response>"""
        return xml.strip()

    async def hangup_call(self, call_uuid: str) -> bool:
        """Hangs up an active call."""
        if not self.auth_id or not self.auth_token:
            return True

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{self.base_url}/Call/{call_uuid}/",
                auth=(self.auth_id, self.auth_token)
            )
            return resp.status_code in [200, 202, 204]

plivo_service = PlivoService()
