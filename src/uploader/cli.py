import argparse
import os
import json

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
    required=False,
    default=".env",
    help="",
)
parser.add_argument(
    "--batch-size",
    default=100,
    help="",
)


def is_image(filename):
    image_extensions = (".png", ".jpg", ".jpeg")
    return any(filename.endswith(ext) for ext in image_extensions)


def walk_images(directory, recursive=False):
    for dirpath, dirnames, filenames in os.walk(directory):
        images = (filename for filename in filenames if is_image(filename))
        for image in images:
            yield os.path.join(dirpath, image)
        if not recursive:
            break

            # for dir in dirnames:
            #     yield from walk_images(os.path.join(dirpath, dir))


def main():
    args = parser.parse_args()
    load_dotenv(args.env)
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_key = os.environ.get("CF_API_KEY")
    uploader = CFImageUploader(account_id, api_key)
    uploads = []
    filepaths = []
    for filepath in walk_images(args.images):
        filepaths.append(filepath)
        uploads.append(
            ImageUpload(
                filepath=filepath,
            )
        )
    results = uploader(uploads, batch_size=args.batch_size)
    data = {}
    for filepath, image_uuid in zip(filepaths, results):
        data[filepath] = image_uuid
    json.dump(data, sys.stdout, indent=4)

if __name__ == "__main__":
    main()
