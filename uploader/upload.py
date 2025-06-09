import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import List, Optional
import json
import typing

import aiofiles
import aiohttp
import requests


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
                raise CloudflareResponseError(f"{image.filepath} failed to be uploaded", resp)
            return resp["result"]["id"]

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False), headers=headers
    ) as session:
        futures = tuple(
            upload_file(session, upload_url, image) for image in images
        )
        return await asyncio.gather(*futures, return_exceptions=True)


class CFImageUploader:
    upload_url = "https://batch.imagedelivery.net/images/v1"
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_key = os.environ.get("CF_API_KEY")

    # Use a save batched token from this file
    token_file_path = f"{os.getcwd()}/.cftoken"
    batch_token = None
    batch_token_expiry = None

    def __init__(self, batch_token: Optional[str] = None) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.check_batch_token()

    def __call__(self, images: List[ImageUpload]) -> list:
        results = asyncio.run(upload_files(self.upload_url, images, self.headers))
        for result, filepath in zip(results, images):
            if isinstance(result, Exception):
                self.logger.error(f"Upload failed for {filepath}")

        return results

    @property
    def headers(self) -> dict:
        return {
            "User-Agent": "Cloudflare Bulk Image Uploader",
            "Authorization": f"Bearer {self.batch_token}",
        }

    @classmethod
    def check_batch_token(cls):
        if cls.batch_token is None:
            if os.path.exists(cls.token_file_path) and os.path.isfile(
                cls.token_file_path
            ):
                cls.batch_token, cls.batch_token_expiry = cls.load_batch_token(
                    cls.token_file_path
                )
            else:
                cls.batch_token, cls.batch_token_expiry = cls.fetch_batch_token(
                    cls.account_id, cls.api_key
                )

        if datetime.now(UTC) > cls.batch_token_expiry:
            cls.batch_token, cls.batch_token_expiry = cls.fetch_batch_token(
                cls.account_id, cls.api_key
            )

        cls.save_batch_token(
            cls.token_file_path, cls.batch_token, cls.batch_token_expiry
        )

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

    @staticmethod
    def fetch_batch_token(account_id: str, api_key: str) -> tuple[str, datetime]:
        token_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1/batch_token"
        headers = {
            "User-Agent": "Cloudflare Bulk Image Uploader",
            "Authorization": f"Bearer {api_key}",
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
