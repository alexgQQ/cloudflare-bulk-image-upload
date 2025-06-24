import argparse
import json
import os
import sys
from typing import Iterator

from cloudflare_image_uploader import CFImageUploader, ImageUpload


def valid_file_or_directory(path: str) -> str:
    if not os.path.exists(path) or (
        not os.path.isdir(path) and not os.path.isfile(path)
    ):
        raise argparse.ArgumentTypeError(
            f"the path `{path}` is not a file or directory"
        )
    return path


def is_image(filename: str) -> bool:
    image_extensions = (".png", ".jpg", ".jpeg")
    return any(filename.endswith(ext) for ext in image_extensions)


def walk_images(directory: str, recursive: bool = False) -> Iterator[str]:
    for dirpath, _, filenames in os.walk(directory):
        images = (filename for filename in filenames if is_image(filename))
        for image in images:
            yield os.path.join(dirpath, image)
        if not recursive:
            break


def gather_uploads(image_locations: list[str]) -> Iterator[ImageUpload]:
    for src in image_locations:
        if os.path.isdir(src):
            for filepath in walk_images(src):
                yield ImageUpload(
                    filepath=filepath,
                )
        elif is_image(src):
            yield ImageUpload(
                filepath=src,
            )


parser = argparse.ArgumentParser(
    prog="cloudflare_image_uploader",
    description="A cli tool to bulk upload images to the Cloudflare Images service.",
)
parser.add_argument(
    "-i",
    "--images",
    nargs="+",
    required=True,
    type=valid_file_or_directory,
    help="Images to upload. This can be set as multiple image files and directories.",
)
parser.add_argument(
    "-o",
    "--output",
    default=sys.stdout,
    help="Output the upload results to a json file or stdout as default.",
)
parser.add_argument(
    "--batch-size",
    default=100,
    help="The number of images to upload in a single attempt.",
)
parser.add_argument(
    "-q",
    "--quiet",
    action="store_true",
    help="Suppress standard output from the command.",
)
parser.add_argument(
    "--account",
    default=os.environ.get("CF_ACCOUNT_ID"),
    help="A cloudflare account id",
)
parser.add_argument(
    "--key",
    default=os.environ.get("CF_API_KEY"),
    help="A cloudflare api key",
)


def main():
    args = parser.parse_args()

    if "-" in args.images:
        images = [line.strip() for line in sys.stdin]
    else:
        images = args.images

    if not args.account or not args.key:
        parser.error("the following arguments are required: --account, --key")

    temp_token_file = ".cftoken"
    batch_token = None
    batch_token_expires = None
    if os.path.exists(temp_token_file):
        token_info = CFImageUploader.load_batch_token(temp_token_file)
        if token_info:
            batch_token, batch_token_expires = token_info

    uploader = CFImageUploader(
        args.account,
        args.key,
        batch_token=batch_token,
        batch_token_expiry=batch_token_expires,
    )
    uploads = [upload for upload in gather_uploads(images)]
    results, errors = uploader(uploads, batch_size=args.batch_size)
    data = {cf_id: upload_info.to_dict() for cf_id, upload_info in results.items()}

    # If all uploads fail it could be a bad token so don't save it
    if len(results) != 0:
        CFImageUploader.save_batch_token(
            temp_token_file, uploader.batch_token, uploader.batch_token_expiry
        )

    if args.output is sys.stdout:
        json.dump(data, sys.stdout, indent=2)
    else:
        with open(args.output, "w") as fobj:
            json.dump(data, fobj, indent=2)

    if len(errors) == 0:
        exit_code = 0
        exit_msg = (
            f"\n{len(results)} images successfully uploaded" if not args.quiet else None
        )
    else:
        exit_code = 1
        exit_msg = None
        exit_msg = f"\n{len(results)} images successfully uploaded and {len(errors)} images failed to upload"
        for error in errors:
            print(error, file=sys.stderr)

    if not args.quiet:
        print(exit_msg, file=sys.stdout if exit_code == 0 else sys.stderr)
    sys.exit(exit_code)


main()
