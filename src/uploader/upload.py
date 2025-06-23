import asyncio
import json
import logging
import os
import typing
from datetime import UTC, datetime
# introduced in 3.12 so anything under would need to be manually implemented
from itertools import batched
from typing import List, Optional

import aiofiles
import aiohttp
import requests

__version__ = "0.0.1"


class ImageUpload(typing.NamedTuple):
    filepath: str = ""
    metadata: dict = {}
    requireSignedURLs: bool = False

    def form_data(self):
        data = {
            "requireSignedURLs": "true" if self.requireSignedURLs else "false",
        }
        if self.metadata:
            metadata = json.dumps(self.metadata)
            data["metadata"] = metadata
        return data

    def to_dict(self):
        return self._asdict()


class CloudflareResponseError(Exception):
    def __init__(self, message, response):
        super().__init__(message)
        self.errors = response.get("errors")


async def upload_files(upload_url: str, images: list[ImageUpload], headers: dict = {}):
    async def upload_file(session, url: str, image: ImageUpload):
        data = aiohttp.FormData(image.form_data())
        async with aiofiles.open(image.filepath, "rb") as file:
            file_data = await file.read()
            file_name = os.path.basename(image.filepath)
            data.add_field("file", file_data, filename=file_name)
        async with session.post(url, data=data, raise_for_status=True) as response:
            resp = await response.json()
            success = resp.get("success", False)
            if not success:
                raise CloudflareResponseError(
                    f"{image.filepath} failed to be uploaded", resp
                )
            return resp["result"]["id"]

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False), headers=headers
    ) as session:
        futures = tuple(upload_file(session, upload_url, image) for image in images)
        return await asyncio.gather(*futures, return_exceptions=True)


class CFImageUploader:
    upload_url: str = "https://batch.imagedelivery.net/images/v1"
    batch_token: str | None = None
    batch_token_expiry: datetime | None = None

    def __init__(
        self, account_id: str, api_key: str, batch_token: Optional[str] = None
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.account_id = account_id
        self.api_key = api_key
        self.check_batch_token()

    def __call__(
        self, images: List[ImageUpload], batch_size: int = 100
    ) -> tuple[dict[str, ImageUpload], list[Exception]]:
        self.check_batch_token()
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self.batch_token}",
        }
        uploads = {}
        errors = []
        for batch in batched(images, batch_size):
            results = asyncio.run(upload_files(self.upload_url, batch, headers))
            for result, image in zip(results, images):
                if isinstance(result, Exception):
                    errors.append(result)
                    self.logger.error(f"Upload failed for {image.filepath}")
                else:
                    uploads[result] = image

        return uploads, errors

    @property
    def user_agent(self):
        return f"CloudflareImageUploader/{__version__}"

    @property
    def batch_token_expired(self) -> bool:
        return (
            self.batch_token_expiry is None
            or datetime.now(UTC) >= self.batch_token_expiry
        )

    @classmethod
    def set_batch_token(cls, batch_token: str, batch_token_expiry: datetime):
        cls.batch_token = batch_token
        cls.batch_token_expiry = batch_token_expiry

    def check_batch_token(self):
        if self.batch_token is None or self.batch_token_expired:
            self.batch_token, self.batch_token_expiry = self.fetch_batch_token()

    def fetch_batch_token(self) -> tuple[str, datetime]:
        token_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/images/v1/batch_token"
        headers = {
            "User-Agent": f"{self.user_agent}",
            "Authorization": f"Bearer {self.api_key}",
        }
        response = requests.get(token_url, headers=headers)
        response.raise_for_status()
        resp = response.json()
        success = resp.get("success", False)
        if not success:
            raise CloudflareResponseError("Batch token request failed", resp)
        else:
            results = resp["result"]
            token = results["token"]
            # Expiry time comes in format "2025-02-10T07:01:55.497877534Z"
            # and python 3.11+ `fromisoformat` can handle it
            expires = datetime.fromisoformat(results["expiresAt"])
            return token, expires

    @staticmethod
    def save_batch_token(filepath: str, token: str, expires: datetime):
        with open(filepath, "w") as fobj:
            json.dump(
                {
                    "token": token,
                    "expiresAt": expires.isoformat(),
                },
                fobj,
            )

    @staticmethod
    def load_batch_token(filepath: str) -> tuple[str, datetime]:
        with open(filepath, "r") as fobj:
            data = json.load(fobj)
            return data["token"], datetime.fromisoformat(data["expiresAt"])
