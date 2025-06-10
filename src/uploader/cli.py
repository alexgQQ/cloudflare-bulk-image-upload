import argparse
import os

import sys

from dotenv import load_dotenv
from uploader import CFImageUploader, ImageUpload


parser = argparse.ArgumentParser(
    prog=sys.argv[0],
    description="A cli tool to bulk upload images to the Cloudflare Images service",
)
parser.add_argument(
    "--images",
    required=True,
    help="",
)
parser.add_argument(
    "--env",
    required=True,
    default=".env",
    help="",
)


def main():
    args = parser.parse_args()
    load_dotenv(args.env)
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_key = os.environ.get("CF_API_KEY")
    uploader = CFImageUploader(account_id, api_key)
    uploads = []
    for file in os.listdir(args.images):
        uploads.append(
            ImageUpload(
                filepath=os.path.join(args.images, file),
            )
        )
    results = uploader(uploads)
    print(results)


if __name__ == "__main__":
    main()
