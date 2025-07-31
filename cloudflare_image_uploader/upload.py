import asyncio
import json
import logging
import os
import typing
from datetime import UTC, datetime
from itertools import batched
from typing import List, Optional

import aiofiles
import aiohttp

__version__ = "0.0.1"


# TODO: In general I'd like to make this work with 3.10 and 3.11 but that
# covers some cross compatibility issues. I'm not sure how to package that
# but I could just check version in the code despite that being gross. I'd like
# to look at other options. Below are some code change examples.
# import platform
# major, minor, _ = platform.python_version_tuple()

# TODO: the `batched` function was added in 3.12 and has to be implemented
#   for lower version, this is from the docs on its approximation
# from itertools import islice
# def batched(iterable, n, *, strict=False):
#     if n < 1:
#         raise ValueError('n must be at least one')
#     iterator = iter(iterable)
#     while batch := tuple(islice(iterator, n)):
#         if strict and len(batch) != n:
#             raise ValueError('batched(): incomplete batch')
#         yield batch

# TODO: The UTC const was added in 3.11, so anything below that
#   has to be done manually like below
# from datetime import timezone
# from datetime import datetime, timedelta
# UTC = timezone(timedelta(0))

# TODO: In python 3.10 the `fromisoformat` functions differently and
#   does not work with some of the datetime strings used. Instead it
#   has to be more involved in removing extra microseconds
# str_date = "2025-02-10T07:01:55.497877534Z"
# first, seconds = str_date.split(".")
# str_date = first + "." + seconds[:6] + "Z"
# expires = datetime.strptime(str_date, "%Y-%m-%dT%H:%M:%S.%fZ")


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
    id: Optional[str] = None

    def form_data(self) -> dict:
        """Get a dictionary that can be serialized as body form data.

        Returns:
            A dictionary of the request form data.
        """
        if self.requireSignedURLs and self.id is not None:
            raise RuntimeError("A Cloudflare image upload cannot specify an id and require a signed url")

        data = {
            "requireSignedURLs": "true" if self.requireSignedURLs else "false",
        }
        if self.id is not None:
            data["id"] = str(self.id)
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


async def upload_files(
    upload_url: str, images: list[ImageUpload], headers: Optional[dict] = None
):
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
        # Only allow as many connections as upload requests that we are making
        # I hadn't heard of "Happy Eyeballs" delay, but for this case it may save some time
        # https://docs.aiohttp.org/en/stable/client_reference.html
        connector=aiohttp.TCPConnector(
            ssl=False, limit=len(images), happy_eyeballs_delay=None
        ),
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
            try:
                results = resp["result"]
                token = results["token"]
                expires_at = results["expiresAt"]
                expires = datetime.fromisoformat(expires_at)
            except (KeyError, ValueError) as err:
                raise CloudflareResponseError(
                    "Unable to read token information", resp
                ) from err
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

        if batch_token is not None and batch_token_expiry is not None:
            self.set_batch_token(batch_token, batch_token_expiry)

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
                    self.logger.error("Upload failed for %s", image.filepath)
                else:
                    uploads[result] = image

        return uploads, errors

    def valid_batch_token(self) -> bool:
        """Is the current batch token useable

        Returns:
            If the batch token is valid and not expired.
        """
        return (
            self.batch_token_expiry is not None
            or datetime.now(UTC) < self.batch_token_expiry
        )

    @classmethod
    def set_user_agent(cls, user_agent: str):
        """Sets the user agent header used for CFImageUploader requests

        Args:
            user_agent: The user agent header to use.
        """
        cls.user_agent = user_agent

    @classmethod
    def set_batch_token(cls, batch_token: str, batch_token_expiry: datetime):
        """Sets the batch token to use for CFImageUploader upload requests

        Args:
            batch_token: The batch token to use.
            batch_token_expiry: The datetime that the token expires.
        """
        cls.batch_token = batch_token
        cls.batch_token_expiry = batch_token_expiry

    @classmethod
    def _clear_batch_token(cls):
        """Remove the batch token used for CFImageUploader"""
        cls.batch_token = None
        cls.batch_token_expiry = None

    def _check_batch_token(self):
        """Set a new batch token if one is not set or is expired"""
        if self.batch_token is None or not self.valid_batch_token():
            batch_token, batch_token_expiry = self.fetch_batch_token()
            self.set_batch_token(batch_token, batch_token_expiry)

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
            raise RuntimeError("Unable to fetch a batch token") from error
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
