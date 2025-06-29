import contextlib
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import aiohttp

from cloudflare_image_uploader.upload import (CFImageUploader, ImageUpload,
                                              fetch_token, upload_files)


class TestFullUpload(unittest.TestCase):
    """
    This is a end to end test of the main module entrypoint and needs to be manually ran.
    It uploads a few images then checks the cloudflare api to match their ids to the related files.
    Uploaded images are deleted.
    Setup a .env with valid account id and api key
    ```
    CF_ACCOUNT_ID=<acount_id>
    CF_API_KEY=<api_key>
    ```
    then `source` it
    make sure a few images are in `testimages` directory
    then comment the skip and run
    ```
    python -m unittest tests.test_upload.TestFullUpload
    ```
    """

    @unittest.skip("This is a full end to end test and should be ran manually")
    def test_upload_testimages(self):
        test_image_dir = "testimages"
        upload_cmd = (
            f"python -m cloudflare_image_uploader --images {test_image_dir} -q".split(
                " "
            )
        )
        upload_results = subprocess.run(
            upload_cmd, capture_output=True, text=True, check=True
        )
        uploads = json.loads(upload_results.stdout)
        upload_ids = list(uploads.keys())
        success = len(uploads)
        self.assertGreater(success, 0)
        self.assertEqual(success, len(os.listdir(test_image_dir)))

        account_id = os.environ.get("CF_ACCOUNT_ID")
        api_key = os.environ.get("CF_API_KEY")

        headers = {"Authorization": f"Bearer {api_key}"}
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1"
        req = urllib.request.Request(url, None, headers)
        with urllib.request.urlopen(req) as response:
            response = json.loads(response.read())

        images = response["result"]["images"]
        for image in images:
            image_id = image.get("id")
            if (image_upload := uploads.get(image_id, None)) is None:
                continue
            expected_filename = os.path.basename(image_upload["filepath"])
            self.assertEqual(image["filename"], expected_filename)

        headers = {"Authorization": f"Bearer {api_key}"}
        for upload_id in upload_ids:
            url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1/{upload_id}"
            req = urllib.request.Request(url, headers=headers, method="DELETE")
            with urllib.request.urlopen(req) as response:
                pass


class TestCFImageUploader(unittest.TestCase):

    def setUp(self) -> None:
        self.account_id = "123"
        self.api_key = "KEY123"
        self.test_token = "TEST_TOKEN"
        self.test_expiry = datetime.now(UTC)
        self.test_user_agent = "FOOBAR/123"

    def tearDown(self):
        CFImageUploader._clear_batch_token()

    def test_save_batch_token(self):
        with tempfile.NamedTemporaryFile() as tmp:
            CFImageUploader.save_batch_token(
                tmp.name, self.test_token, self.test_expiry
            )
            with open(tmp.name, "r") as fobj:
                data = json.load(fobj)

        token = data["token"]
        expiry = datetime.fromisoformat(data["expiresAt"])
        self.assertEqual(token, self.test_token)
        self.assertEqual(expiry, self.test_expiry)

    def test_load_batch_token(self):
        test_data = {
            "token": self.test_token,
            "expiresAt": self.test_expiry.isoformat(),
        }
        with tempfile.NamedTemporaryFile() as tmp:
            with open(tmp.name, "w") as fobj:
                json.dump(test_data, fobj)
            token, expires = CFImageUploader.load_batch_token(tmp.name)

        self.assertEqual(token, self.test_token)
        self.assertEqual(expires, self.test_expiry)

    def test_init(self):
        uploader = CFImageUploader(self.account_id, self.api_key)
        self.assertEqual(uploader.account_id, self.account_id)
        self.assertEqual(uploader.api_key, self.api_key)

        uploader = CFImageUploader(
            self.account_id, self.api_key, batch_token=self.test_token
        )
        self.assertIsNone(uploader.batch_token)
        self.assertIsNone(uploader.batch_token_expiry)

        uploader = CFImageUploader(
            self.account_id,
            self.api_key,
            batch_token=self.test_token,
            batch_token_expiry=self.test_expiry,
        )
        self.assertEqual(uploader.batch_token, self.test_token)
        self.assertEqual(uploader.batch_token_expiry, self.test_expiry)

    def test_set_user_agent(self):
        CFImageUploader.set_user_agent(self.test_user_agent)
        self.assertEqual(CFImageUploader.user_agent, self.test_user_agent)

    def test_set_user_agent(self):
        CFImageUploader.set_batch_token(self.test_token, self.test_expiry)
        self.assertEqual(CFImageUploader.batch_token, self.test_token)
        self.assertEqual(CFImageUploader.batch_token_expiry, self.test_expiry)

    def test_call(self):
        test_expiry = datetime.now(UTC) + timedelta(days=1)
        test_uploads = [ImageUpload(filepath="foobar") for _ in range(20)]
        uploader = CFImageUploader(
            self.account_id,
            self.api_key,
            batch_token=self.test_token,
            batch_token_expiry=test_expiry,
        )
        with mock.patch(
            target="cloudflare_image_uploader.upload.upload_files", spec=upload_files
        ) as upload_mock:
            upload_mock.return_value = [a for a in range(len(test_uploads))]
            uploader(test_uploads, batch_size=5)
            self.assertTrue(upload_mock.called)
            self.assertEqual(upload_mock.call_count, 4)

    def test_fetch_batch_token(self):
        expected_token_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/images/v1/batch_token"
        expected_auth_header = f"Bearer {self.api_key}"
        uploader = CFImageUploader(self.account_id, self.api_key)

        with mock.patch(
            target="cloudflare_image_uploader.upload.fetch_token", spec=fetch_token
        ) as fetch_mock:
            fetch_mock.return_value = (self.test_token, self.test_expiry)
            token, expires = uploader.fetch_batch_token()
            self.assertTrue(fetch_mock.called)
            self.assertEqual(fetch_mock.call_args[0][0], expected_token_url)
            self.assertEqual(
                fetch_mock.call_args[0][1]["Authorization"], expected_auth_header
            )
            self.assertEqual(self.test_token, token)
            self.assertEqual(self.test_expiry, expires)


class TestAsyncHTTPFunctions(unittest.IsolatedAsyncioTestCase):
    """
    An example response for a successful upload
    {
        "result": {
            "id": "image_uuid",
            "filename": "test_image.png",
            "uploaded": "2025-02-28T16:18:41.141Z",
            "requireSignedURLs": false,
            "variants": [
            "https://imagedelivery.net/_account_hash/image_uuid/public"
            ]
        },
        "success": true,
        "errors": [],
        "messages": []
    }
    """

    def mock_resp(self, method, json_data=None):
        # The sync mocks are fussy and need some extra wrappers as they
        # are used as context managers, both the session and request
        # however there is a contextlib.asynccontextmanager
        # that does not work while the nullcontext does
        mock_req = mock.AsyncMock(
            spec=aiohttp.ClientResponse, **{"json.return_value": json_data}
        )
        mock_session = mock.AsyncMock(
            spec=aiohttp.ClientSession,
            **{f"{method.lower()}.return_value": contextlib.nullcontext(mock_req)},
        )
        patcher = mock.patch(
            target="aiohttp.ClientSession",
            return_value=contextlib.nullcontext(mock_session),
        )
        return patcher

    async def test_upload_files(self):
        # The received image id is the important bit as that gets saved to the db
        # so lets test for that specifically but I want to preserve a response expected
        # from cloudflare
        image_uuid = str(uuid4())
        test_url = "https://batch.imagedelivery.net/images/v1"
        success_response_str = f"""{{
                "result": {{
                    "id": "{image_uuid}",
                    "filename": "test_image.png",
                    "uploaded": "2025-02-28T16:18:41.141Z",
                    "requireSignedURLs": false,
                    "variants": [
                    "https://imagedelivery.net/_ACCOUNTHASH_123/{image_uuid}/public"
                    ]
                }},
                "success": true,
                "errors": [],
                "messages": []
            }}"""
        json_data = json.loads(success_response_str)

        with self.mock_resp("POST", json_data=json_data):
            with tempfile.NamedTemporaryFile(suffix=".png") as tmp_file:
                data = await upload_files(
                    test_url, [ImageUpload(filepath=tmp_file.name)]
                )
                self.assertEqual(data[0], image_uuid)

    async def test_fetch_token(self):
        test_token = "TEST_TOKEN"
        test_expiry = "2025-02-28T02:10:00.875924084Z"
        mock_data = {
            "result": {"token": test_token, "expiresAt": test_expiry},
            "success": True,
            "errors": [],
            "messages": [],
        }
        with self.mock_resp("GET", json_data=mock_data):
            test_url = f"https://api.cloudflare.com/client/v4/accounts/123/images/v1/batch_token"
            headers = {}
            token, expires = await fetch_token(test_url, headers)
            self.assertEqual(token, test_token)
            self.assertEqual(expires, datetime.fromisoformat(test_expiry))


class TestImageUpload(unittest.TestCase):
    def test_form_data(self):
        result = ImageUpload(requireSignedURLs=True)
        form_data = result.form_data().get("requireSignedURLs")
        self.assertEqual(form_data, "true")
        result = ImageUpload(requireSignedURLs=False)
        form_data = result.form_data().get("requireSignedURLs")
        self.assertEqual(form_data, "false")
        test_metadata = {"name": "foobar", "id": 123}
        result = ImageUpload(metadata=test_metadata)
        form_data = result.form_data().get("metadata")
        self.assertEqual(form_data, json.dumps(test_metadata))
