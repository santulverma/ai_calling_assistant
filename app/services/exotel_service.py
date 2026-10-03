"""
Exotel Telephony Service for Indian Telecommunications (+91).
Connects outbound calls and handles bi-directional audio streaming
via Exotel's Voicebot / AgentStream WebSocket protocol.
"""

import os
import httpx
import logging
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)


class ExotelService:
    def __init__(self):
        self.account_sid = os.getenv("EXOTEL_ACCOUNT_SID", "")
        self.api_key = os.getenv("EXOTEL_API_KEY", "")
        self.api_token = os.getenv("EXOTEL_API_TOKEN", "")
        self.subdomain = os.getenv("EXOTEL_SUBDOMAIN", "api.exotel.com")
        self.caller_id = os.getenv("EXOTEL_CALLER_ID", "")
        self.app_id = os.getenv("EXOTEL_APP_ID", "")

    async def initiate_outbound_call(
        self,
        to_number: str,
        lead_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Dispatches an outbound call via Exotel REST API.
        When answered, Exotel connects the call to our Voicebot applet / WebSocket stream.
        """
        from dotenv import load_dotenv
        load_dotenv(override=True)

        account_sid = os.getenv("EXOTEL_ACCOUNT_SID") or self.account_sid
        api_key = os.getenv("EXOTEL_API_KEY") or self.api_key
        api_token = os.getenv("EXOTEL_API_TOKEN") or self.api_token
        subdomain = os.getenv("EXOTEL_SUBDOMAIN") or self.subdomain or "api.exotel.com"
        caller_id = os.getenv("EXOTEL_CALLER_ID") or self.caller_id
        app_id = os.getenv("EXOTEL_APP_ID") or self.app_id
        public_base = (os.getenv("PUBLIC_URL") or settings.PUBLIC_URL).rstrip("/")

        if not api_key or not api_token or not account_sid:
            logger.warning("Exotel credentials not configured in .env.")
            return {
                "status": "error",
                "message": "EXOTEL_ACCOUNT_SID, EXOTEL_API_KEY, or EXOTEL_API_TOKEN is not set in .env"
            }

        # Exotel expects standard phone format (e.g., 09876543210 or +919876543210)
        formatted_to = to_number.strip()
        if not formatted_to.startswith("+") and not formatted_to.startswith("0") and len(formatted_to) == 10:
            formatted_to = f"+91{formatted_to}"

        endpoint = f"https://{subdomain}/v1/Accounts/{account_sid}/Calls/connect.json"
        status_callback = f"{public_base}/exotel/events"
        if lead_id:
            status_callback += f"?lead_id={lead_id}"

        # If an Applet ID (Voicebot Flow) is configured in Exotel:
        form_payload = {
            "From": formatted_to,
            "CallerId": caller_id or formatted_to,
            "StatusCallback": status_callback,
            "CallType": "trans"
        }

        if app_id:
            flow_url = f"http://my.exotel.com/{account_sid}/exoml/start_voice/{app_id}"
            form_payload["Url"] = flow_url
        else:
            # Direct Click-to-Call bridging
            form_payload["To"] = caller_id or formatted_to

        auth = httpx.BasicAuth(api_key, api_token)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    endpoint,
                    auth=auth,
                    data=form_payload
                )

                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

                if resp.status_code in [200, 201]:
                    call_obj = data.get("Call", {})
                    call_sid = call_obj.get("Sid") or "active"
                    logger.info(f"Exotel call initiated successfully: SID={call_sid}")
                    return {
                        "status": "success",
                        "call_sid": call_sid,
                        "call_control_id": call_sid,
                        "data": data
                    }
                else:
                    err_msg = data.get("RestException", {}).get("Message") or resp.text
                    logger.error(f"Exotel call failed: HTTP {resp.status_code} - {err_msg}")
                    return {
                        "status": "error",
                        "status_code": resp.status_code,
                        "error": err_msg,
                        "message": err_msg
                    }
        except Exception as e:
            logger.error(f"Exception during Exotel call dispatch: {e}")
            return {"status": "error", "error": str(e), "message": str(e)}

    def get_voicebot_websocket_url(self, lead_id: Optional[int] = None) -> str:
        """
        Returns the publicly reachable WebSocket URL for Exotel Voicebot Applet.
        """
        from dotenv import load_dotenv
        load_dotenv(override=True)
        public_url = (os.getenv("PUBLIC_URL") or settings.PUBLIC_URL).rstrip("/")
        ws_url = public_url.replace("https://", "wss://").replace("http://", "ws://")
        endpoint = f"{ws_url}/ws/exotel"
        if lead_id:
            endpoint += f"?lead_id={lead_id}"
        return endpoint


exotel_service = ExotelService()
