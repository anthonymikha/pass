"""Object storage (REC-1): signed POST forms for uploads, signed GET links for playback. Django never sees file bytes."""
import re
import uuid
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

EXPIRES = 3600  # REC-2: signed forms and links last 1 hour
UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class S3Storage:
    """Two clients on one bucket: the public endpoint signs what phones use (the host is part of a GET signature);
    the internal one makes the server's own calls (head, delete)."""

    def __init__(self):
        def client(endpoint):
            return boto3.client(
                "s3", endpoint_url=endpoint, aws_access_key_id=settings.STORAGE_ACCESS_KEY,
                aws_secret_access_key=settings.STORAGE_SECRET_KEY, region_name=settings.STORAGE_REGION,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        self.bucket = settings.STORAGE_BUCKET
        self.internal, self.public = client(settings.STORAGE_ENDPOINT), client(settings.STORAGE_PUBLIC_ENDPOINT)

    def upload_form(self, key, max_bytes):
        """`{url, fields}` for a multipart POST; the policy refuses a body outside 1..max_bytes bytes (REC-11)."""
        return self.public.generate_presigned_post(
            self.bucket, key, Conditions=[["content-length-range", 1, max_bytes]], ExpiresIn=EXPIRES)

    def url(self, key):
        return self.public.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=EXPIRES)

    def exists(self, key):
        try:
            self.internal.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def delete(self, key):
        self.internal.delete_object(Bucket=self.bucket, Key=key)


class FakeStorage:
    """REC-3: remembers which keys were "uploaded" and what each form allowed. Tests call `put(key)` for the upload."""

    def __init__(self):
        self.keys, self.forms = set(), {}

    def put(self, key):
        self.keys.add(key)

    def upload_form(self, key, max_bytes):
        self.forms[key] = max_bytes
        return {"url": "http://storage.test/pass", "fields": {"key": key, "policy": f"content-length-range 1 {max_bytes}"}}

    def url(self, key):
        return f"http://storage.test/pass/{key}?expires={EXPIRES}"

    def exists(self, key):
        return key in self.keys

    def delete(self, key):
        self.keys.discard(key)


@lru_cache
def get_storage():
    return S3Storage() if settings.STORAGE_ENDPOINT else FakeStorage()


def upload_form(prefix, ext, max_bytes):
    """REC-11, REC-30: a signed form for a new random key `<prefix>/<uuid>.<ext>`."""
    key = f"{prefix}/{uuid.uuid4()}.{ext}"
    return {**get_storage().upload_form(key, max_bytes), "storage_key": key}


def is_key(key, prefix, extensions):
    """REC-12: `key` is `<prefix>/<uuid>.<ext>` with one of `extensions`."""
    return re.fullmatch(rf"{re.escape(prefix)}/{UUID}\.({'|'.join(extensions)})", key) is not None
