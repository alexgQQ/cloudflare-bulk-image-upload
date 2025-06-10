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
    "-i",
    "--images",
    nargs="+",
    required=True,
    help="",
)
parser.add_argument(
    "-o",
    "--output",
    default="-",
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
    for dirpath, _, filenames in os.walk(directory):
        images = (filename for filename in filenames if is_image(filename))
        for image in images:
            yield os.path.join(dirpath, image)
        if not recursive:
            break

            # for dir in dirnames:
            #     yield from walk_images(os.path.join(dirpath, dir))


def main():
    args = parser.parse_args()

    if "-" in args.images:
        images = [line.strip() for line in sys.stdin]
    else:
        images = args.images

    load_dotenv(args.env)
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_key = os.environ.get("CF_API_KEY")

    uploads = []
    filepaths = []
    for src in images:
        if not os.path.exists(src):
            continue
        elif os.path.isdir(src):
            for filepath in walk_images(src):
                filepaths.append(filepath)
                uploads.append(
                    ImageUpload(
                        filepath=filepath,
                    )
                )
        elif is_image(src):
            filepaths.append(src)
            uploads.append(
                ImageUpload(
                    filepath=src,
                )
            )

    uploader = CFImageUploader(account_id, api_key)
    results = uploader(uploads, batch_size=args.batch_size)
    data = {}
    for filepath, image_uuid in zip(filepaths, results):
        data[filepath] = image_uuid

    if args.output == "-":
        json.dump(data, sys.stdout, indent=2)
    else:
        with open(args.output, "w") as fobj:
            json.dump(data, fobj, indent=2)


if __name__ == "__main__":
    main()
