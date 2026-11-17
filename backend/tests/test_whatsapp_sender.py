import httpx
import pytest

from app.services.whatsapp_sender import WhatsAppConfig, send_template


def config(**changes):
    values = dict(access_token="test-token", phone_number_id="12345", recipient="919876543210",
                  api_version="v22.0", template_name="paper_trade_alert", language="en_US")
    values.update(changes)
    return WhatsAppConfig(**values)


@pytest.mark.asyncio
async def test_sends_approved_template_and_returns_provider_id():
    def handler(request):
        import json
        data = json.loads(request.content)
        assert request.url.host == "graph.facebook.com"
        assert data["to"] == "919876543210"
        assert data["template"]["components"][0]["parameters"][0]["text"] == "PAPER ENTRY"
        return httpx.Response(200, json={"messages": [{"id": "wamid.test"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await send_template(config(), ["PAPER ENTRY"], client=client) == "wamid.test"


@pytest.mark.asyncio
async def test_invalid_config_never_sends():
    def handler(request):
        pytest.fail("unexpected network request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await send_template(config(recipient=""), ["ENTRY"], client=client)


@pytest.mark.asyncio
async def test_provider_error_and_missing_message_id_are_not_success():
    for response in (httpx.Response(503), httpx.Response(200, json={})):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
            with pytest.raises((httpx.HTTPStatusError, ValueError)):
                await send_template(config(), ["EXIT"], client=client)
