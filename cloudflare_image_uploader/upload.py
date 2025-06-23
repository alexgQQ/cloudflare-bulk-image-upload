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
        async with session.post(url, data=data) as response:
            resp = await response.json()
            success = resp.get("success", False)
            if not success:
                raise CloudflareResponseError(
                    f"{image.filepath} failed to be uploaded", resp
                )
            return resp["result"]["id"]

    async with aiohttp.ClientSession(
        # Skipping ssl verification makes this a little bit faster but risks security
        connector=aiohttp.TCPConnector(ssl=False),
        headers=headers,
        raise_for_status=True,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as session:
        futures = tuple(upload_file(session, upload_url, image) for image in images)
        return await asyncio.gather(*futures, return_exceptions=True)


async def fetch_token(url, headers):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            resp = await response.json()
            success = resp.get("success", False)
            if not success:
                raise CloudflareResponseError("Batch token request failed", resp)
            else:
                try:
                    results = resp["result"]
                    token = results["token"]
                    # Expiry time comes in format "2025-02-10T07:01:55.497877534Z"
                    # and python 3.11+ `fromisoformat` can handle it
                    expires = datetime.fromisoformat(results["expiresAt"])
                except (KeyError, ValueError):
                    raise CloudflareResponseError(
                        "Unable to read token information", resp
                    )
                return token, expires


class CFImageUploader:
    upload_url: str = "https://batch.imagedelivery.net/images/v1"
    user_agent: str = f"CloudflareImageUploader/{__version__}"
    batch_token: str | None = None
    batch_token_expiry: datetime | None = None

    def __init__(
        self,
        account_id: str,
        api_key: str,
        batch_token: Optional[str] = None,
        batch_token_expiry: Optional[datetime] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.account_id = account_id
        self.api_key = api_key

        if user_agent is not None:
            self.user_agent = user_agent

        if batch_token is not None and batch_token_expiry is not None:
            self.batch_token = batch_token
            self.batch_token_expiry = batch_token_expiry
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
        try:
            token, expires = asyncio.run(fetch_token(token_url, headers))
        except (
            aiohttp.ClientConnectionError,
            aiohttp.ClientResponseError,
            json.JSONDecodeError,
            CloudflareResponseError,
        ) as error:
            raise RuntimeError(f"Unable to fetch a batch token - {error}")
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
