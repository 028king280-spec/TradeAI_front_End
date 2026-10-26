import pytest
import io
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_knowledge_upload_and_search():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Upload a sample trading knowledge TXT file
        sample_doc = (
            "Breakout trading requires price acceptance beyond the 20-period EMA "
            "and confirmed volume expansion. Institutional buyers accumulate within "
            "the value area before initiating markup phases."
        )
        files = {
            "file": ("institutional_trading_guide.txt", io.BytesIO(sample_doc.encode("utf-8")), "text/plain")
        }
        data = {
            "category": "Technical Analysis",
            "author": "Antigravity Research",
        }
        res_upload = await client.post("/api/knowledge/upload", files=files, data=data)
        assert res_upload.status_code == 200
        upload_json = res_upload.json()
        assert upload_json["success"] is True
        doc_id = upload_json["data"]["documentId"]
        assert doc_id is not None

        # 2. List documents
        res_list = await client.get("/api/knowledge/documents")
        assert res_list.status_code == 200
        docs = res_list.json()["data"]
        assert len(docs) >= 1

        # 3. Semantic search
        search_payload = {
            "query": "breakout volume expansion moving average",
            "topK": 3,
        }
        res_search = await client.post("/api/knowledge/search", json=search_payload)
        assert res_search.status_code == 200
        search_results = res_search.json()["data"]
        assert len(search_results) >= 1
        assert "score" in search_results[0]
        assert search_results[0]["score"] > 0.0


@pytest.mark.asyncio
async def test_ml_train_and_models_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Trigger training job
        req_body = {
            "modelType": "random_forest",
            "target": "next_30m_direction",
            "symbols": ["RELIANCE", "TCS"],
            "lookbackDays": 60,
            "features": ["return_1d", "rsi_14", "ema20_ratio", "vwap_ratio"]
        }
        res_train = await client.post("/api/ml/train", json=req_body)
        assert res_train.status_code == 200
        data = res_train.json()
        assert data["success"] is True
        assert data["data"]["status"] == "RUNNING"
        job_id = data["data"]["jobId"]

        # Check job list
        res_jobs = await client.get("/api/ml/jobs")
        assert res_jobs.status_code == 200
        jobs = res_jobs.json()["data"]
        assert any(j["jobId"] == job_id for j in jobs)

        # List models
        res_models = await client.get("/api/ml/models")
        assert res_models.status_code == 200
        assert isinstance(res_models.json()["data"], list)
