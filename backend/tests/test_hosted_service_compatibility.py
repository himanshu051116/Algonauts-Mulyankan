"""Regression checks for managed Redis and S3-compatible storage."""

from app.config import Settings
from app.services import storage


def test_rediss_url_enables_tls_for_arq_and_decodes_credentials():
    settings = Settings(
        redis_url="rediss://demo%20user:demo%2Fsecret@redis.example.test:6380/2"
    )

    redis_settings = settings.arq_redis_settings

    assert redis_settings.host == "redis.example.test"
    assert redis_settings.port == 6380
    assert redis_settings.database == 2
    assert redis_settings.username == "demo user"
    assert redis_settings.password == "demo/secret"
    assert redis_settings.ssl is True


def test_s3_client_uses_path_style_addressing_for_compatible_hosts(monkeypatch):
    captured = {}

    def fake_client(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(storage.boto3, "client", fake_client)

    storage._get_client("https://project.storage.supabase.co/storage/v1/s3")

    assert captured["args"] == ("s3",)
    assert captured["kwargs"]["config"].signature_version == "s3v4"
    assert captured["kwargs"]["config"].s3 == {"addressing_style": "path"}
