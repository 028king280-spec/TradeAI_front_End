"""WhatsApp Cloud API transport for explicitly configured template messages.

This module does not subscribe to trade events or start a worker. A successful
API response only means the provider accepted the request, not that it was delivered.
"""
from dataclasses import dataclass
import re
from typing import Sequence

import httpx


@dataclass(frozen=True)
class WhatsAppConfig:
    access_token: str
    phone_number_id: str
    recipient: str
    api_version: str
    template_name: str
    language: str

    def validate(self) -> None:
        if not self.access_token or not self.access_token.strip():
            raise ValueError("WhatsApp access token is required")
        if not re.fullmatch(r"[0-9]+", self.phone_number_id):
            raise ValueError("Invalid WhatsApp phone number ID")
        if not re.fullmatch(r"[1-9][0-9]{7,14}", self.recipient):
            raise ValueError("Recipient must be in international format without +")
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", self.api_version):
            raise ValueError("Invalid Graph API version")
        if not re.fullmatch(r"[a-z0-9_]+", self.template_name):
            raise ValueError("Invalid template name")
        if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", self.language):
            raise ValueError("Invalid template language")


async def send_template(
    config: WhatsAppConfig,
    parameters: Sequence[str],
    *,
    client: httpx.AsyncClient,
) -> str:
    """Send once; callers must reconcile ambiguous failures before retrying."""
    config.validate()
    if not all(isinstance(value, str) and value.strip() for value in parameters):
        raise ValueError("Template parameters must be non-empty strings")
    template = {"name": config.template_name, "language": {"code": config.language}}
    if parameters:
        template["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": value} for value in parameters],
        }]
    response = await client.post(
        f"https://graph.facebook.com/{config.api_version}/{config.phone_number_id}/messages",
        headers={"Authorization": f"Bearer {config.access_token}"},
        json={"messaging_product": "whatsapp", "to": config.recipient,
              "type": "template", "template": template},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict) or not messages[0].get("id"):
        raise ValueError("WhatsApp response did not contain a message ID")
    return str(messages[0]["id"])
