import pytest


@pytest.mark.asyncio
async def test_signed_upload_url_and_delete_use_thread_safe_boto_calls(monkeypatch):
    from app.services import storage as storage_service

    class FakeClient:
        def __init__(self, name="internal"):
            self.name = name
            self.calls = []

        def head_bucket(self, Bucket):
            self.calls.append(("head_bucket", Bucket))

        def create_bucket(self, Bucket):
            self.calls.append(("create_bucket", Bucket))

        def generate_presigned_url(self, operation, **kwargs):
            self.calls.append(("presign", operation, kwargs))
            return f"https://{self.name}.example.test/{operation}"

        def head_object(self, Bucket, Key):
            self.calls.append(("head_object", Bucket, Key))
            return {"ContentLength": 12, "ContentType": "application/pdf"}

        def delete_object(self, Bucket, Key):
            self.calls.append(("delete_object", Bucket, Key))

    client = FakeClient()
    presign_client = FakeClient("public")
    monkeypatch.setattr(storage_service, "_get_client", lambda endpoint_url=None: client)
    monkeypatch.setattr(storage_service, "_get_presign_client", lambda: presign_client)

    upload_url = await storage_service.get_signed_upload_url("proposals/key.pdf", 12, "application/pdf")
    download_url = await storage_service.get_signed_download_url("proposals/key.pdf")
    head = await storage_service.head_object("proposals/key.pdf")
    await storage_service.delete_object("proposals/key.pdf")

    assert upload_url == "https://public.example.test/put_object"
    assert download_url == "https://public.example.test/get_object"
    assert head["ContentLength"] == 12
    assert any(call[0] == "head_bucket" for call in client.calls)
    assert [
        call[1] for call in presign_client.calls if call[0] == "presign"
    ] == ["put_object", "get_object"]
    assert not any(call[0] == "presign" for call in client.calls)
    assert ("delete_object", storage_service.settings.storage_bucket, "proposals/key.pdf") in client.calls
