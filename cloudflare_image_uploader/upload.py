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
    """An object to represent image upload data to Cloudflare.

    On upload this will get serialized to form data.
    The 'metadata' field can hold anything that is able to be serialized. 
    The API interface for Cloudflare Images is outlined here.
    https://developers.cloudflare.com/api/resources/images/subresources/v1/methods/create/
    
    Attributes:
        filepath: A str that is the path to the image file.
        metadata: A dictionary containing any key valued metadata to associate with the image.
        requireSignedURLs: A boolean for whether the resulting upload is publicly available or not.
    """
    filepath: str = ""
    metadata: dict = {}
    requireSignedURLs: bool = False

    def form_data(self) -> dict:
        """Get a dictionary that can be serialized as body form data.

        Returns:
            A dictionary of the request form data.
        """
        data = {
            "requireSignedURLs": "true" if self.requireSignedURLs else "false",
        }
        if self.metadata:
            metadata = json.dumps(self.metadata)
            data["metadata"] = metadata
        return data

    def to_dict(self) -> dict:
        """Get a dictionary copy of the upload data.

        Returns:
            A dictionary copy of the upload data.
        """
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
    """An object to represent image upload data to Cloudflare.

    This is just a object to hold the interface capabilities

    Attributes:
        upload_url: The url for Cloudflare batch image delivery.
        user_agent: The User-Agent header to use on all requests.
        batch_token: The authorization token for the batch api.
        batch_token_expiry: The expiry time for the batch token.
    """
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
        """Initializes the instance based on spam preference.

        Args:
            account_id: A Cloudflare account id to use.
            api_key: A Cloudflare API key with Image Read/Write permissions.
            batch_token: An optional batch token to use for upload requests.
            batch_token_expiry: The datetime that the related batch token expires.
            user_agent: An optional user agent header to apply to each request.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.account_id = account_id
        self.api_key = api_key

        if user_agent is not None:
            self.user_agent = user_agent

        if batch_token is not None and batch_token_expiry is not None:
            self.batch_token = batch_token
            self.batch_token_expiry = batch_token_expiry
        self._check_batch_token()

    def __call__(
        self, images: List[ImageUpload], batch_size: int = 100
    ) -> tuple[dict[str, ImageUpload], list[Exception]]:
        """Upload ImageUploads to Cloudflare Images in batches.

        Args:
            images: A list of ImageUpload object with filedata and metadata.
            batch_size: The number of images to upload in a single batch.

        Returns:
            A tuple containing the upload results. The first element is a dictionary
            of the Cloudflare image ids to their related ImageUpload. 
            The second element is a list of exceptions generated during uploads.
            This function doesn't raise exceptions but accumulates them so that
            a failed upload doesn't block potentially successful ones.
        """
        self._check_batch_token()
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

    @classmethod
    def valid_batch_token(cls) -> bool:
        """Is the current batch token useable

        Returns:
            If the batch token is valid and not expired.
        """
        return (
            cls.batch_token_expiry is not None
            or datetime.now(UTC) < cls.batch_token_expiry
        )

    # @classmethod
    # def set_batch_token(cls, batch_token: str, batch_token_expiry: datetime):
    #     cls.batch_token = batch_token
    #     cls.batch_token_expiry = batch_token_expiry

    def _check_batch_token(self):
        """Set a new batch token if one is not set or expired"""
        if self.batch_token is None or self.valid_batch_token():
            self.batch_token, self.batch_token_expiry = self.fetch_batch_token()

    def fetch_batch_token(self) -> tuple[str, datetime]:
        """Get a authorized token from Cloudflare to use against their batch API.

        Returns:
            A tuple containing the batch token and the time it expires.

        Raises:
            RuntimeError: An error occurred getting a batch token.
        """
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
