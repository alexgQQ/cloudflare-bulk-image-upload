import contextlib
import json
import tempfile
import unittest
import unittest.mock as mock
from datetime import UTC, datetime
from uuid import uuid4

import aiohttp

from uploader import CFImageUploader
from uploader.upload import upload_files


class TestCFImageUploader(unittest.TestCase):
    def test_save_batch_token(self):
        test_token = "TEST_TOKEN"
        test_expiry = datetime.now(UTC)
        with tempfile.NamedTemporaryFile() as tmp:
            CFImageUploader.save_batch_token(tmp.name, test_token, test_expiry)
            with open(tmp.name, "r") as fobj:
                data = json.load(fobj)

        token = data["token"]
        expiry = datetime.fromisoformat(data["expiresAt"])
        self.assertEqual(token, test_token)
        self.assertEqual(expiry, test_expiry)

    def test_load_batch_token(self):
        test_token = "TEST_TOKEN"
        test_expiry = datetime.now(UTC)
        test_data = {
            "token": test_token,
            "expiresAt": test_expiry.isoformat(),
        }
        with tempfile.NamedTemporaryFile() as tmp:
            with open(tmp.name, "w") as fobj:
                json.dump(test_data, fobj)
            token, expires = CFImageUploader.load_batch_token(tmp.name)

        self.assertEqual(token, test_token)
        self.assertEqual(expires, test_expiry)

    def _mock_cf_response(
        self, status=200, content="CONTENT", json_data=None, raise_for_status=None
    ):
        mock_resp = mock.Mock()

        mock_resp.raise_for_status = mock.Mock()
        if raise_for_status:
            mock_resp.raise_for_status.side_effect = raise_for_status

        mock_resp.status_code = status
        mock_resp.content = content

        if json_data:
            mock_resp.json = mock.Mock(return_value=json_data)
        return mock_resp

    @mock.patch("requests.get")
    def test_fetch_batch_token(self, mock_get):
        test_token = "TEST_TOKEN"
        test_expiry = "2025-02-28T02:10:00.875924084Z"
        mock_data = {
            "result": {"token": test_token, "expiresAt": test_expiry},
            "success": True,
            "errors": [],
            "messages": [],
        }
        mock_resp = self._mock_cf_response(json_data=mock_data)
        mock_get.return_value = mock_resp
        token, expires = CFImageUploader.fetch_batch_token(
            "TEST_ACCOUNT", "TEST_API_KEY"
        )
        # print(mock_get.call_args)
        self.assertEqual(token, test_token)
        self.assertEqual(expires, datetime.fromisoformat(test_expiry))


class TestAsyncImageFileUpload(unittest.IsolatedAsyncioTestCase):
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

        # The sync mocks are fussy and need some extra wrappers as they
        # are used as context managers, both the session and request
        # however there is a contextlib.asynccontextmanager
        # that does not work while the nullcontext does
        mock_req = mock.AsyncMock(
            spec=aiohttp.ClientResponse, **{"json.return_value": json_data}
        )
        mock_session = mock.AsyncMock(
            spec=aiohttp.ClientSession,
            **{"post.return_value": contextlib.nullcontext(mock_req)},
        )
        with mock.patch(
            target="aiohttp.ClientSession",
            return_value=contextlib.nullcontext(mock_session),
        ):
            with tempfile.NamedTemporaryFile(suffix=".png") as tmp_file:
                data = await upload_files(test_url, [tmp_file.name])
                self.assertEqual(data[0], image_uuid)
