import argparse
import json
import os
import sys
from typing import Generator, Optional

from dotenv import load_dotenv

from uploader import CFImageUploader, ImageUpload


class ConfigError(Exception):
    pass


parser = argparse.ArgumentParser(
    prog=sys.argv[0],
    description="A cli tool to bulk upload images to the Cloudflare Images service.",
)
parser.add_argument(
    "-i",
    "--images",
    nargs="+",
    required=True,
    help="Images to upload. This can be set as multiple image files and directories.",
)
parser.add_argument(
    "-o",
    "--output",
    default=sys.stdout,
    help="Output the upload results to a json file or stdout as default.",
)
parser.add_argument(
    "--env",
    required=False,
    default=None,
    help="The environment file containing cloudflare auth info. Will read from environment variables if not set.",
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


def is_image(filename: str) -> bool:
    image_extensions = (".png", ".jpg", ".jpeg")
    return any(filename.endswith(ext) for ext in image_extensions)


def walk_images(directory: str, recursive: bool = False) -> Generator[str, None, None]:
    for dirpath, _, filenames in os.walk(directory):
        images = (filename for filename in filenames if is_image(filename))
        for image in images:
            yield os.path.join(dirpath, image)
        if not recursive:
            break


def load_auth(env_file: Optional[str] = None) -> tuple[str, str]:
    if env_file is not None and not load_dotenv(env_file):
        raise ConfigError(f"Unable to load env file {env_file}")
    try:
        account_id = os.environ["CF_ACCOUNT_ID"]
        api_key = os.environ["CF_API_KEY"]
    except KeyError as error:
        raise ConfigError(f"Required environment variable not set {error}")
    else:
        return account_id, api_key


def exit(
    message: Optional[str] = None, code: int = 0, error: Optional[Exception] = None
):
    if isinstance(error, Exception):
        code = 1
        message = str(error)

    if message and code > 0:
        print(message, file=sys.stderr)
    elif message:
        print(message, file=sys.stdout)
    sys.exit(code)


def main():
    args = parser.parse_args()

    if "-" in args.images:
        images = [line.strip() for line in sys.stdin]
    else:
        images = args.images

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

    try:
        account_id, api_key = load_auth(args.env)
    except ConfigError as err:
        exit(error=err)

    uploader = CFImageUploader(account_id, api_key)
    results, errors = uploader(uploads, batch_size=args.batch_size)
    data = {cf_id: upload_info.to_dict() for cf_id, upload_info in results.items()}

    if args.output is sys.stdout:
        json.dump(data, sys.stdout, indent=2)
    else:
        with open(args.output, "w") as fobj:
            json.dump(data, fobj, indent=2)

    if len(errors) == 0:
        exit_code = 0
        exit_msg = f"\n{len(results)} images successfully uploaded" if not args.quiet else None
    else:
        exit_code = 1
        exit_msg = None
        if not args.quiet:
            exit_msg = f"\n{len(results)} images successfully uploaded and {len(errors)} images failed to upload"
            for error in errors:
                print(error, file=sys.stderr)
    exit(message=exit_msg, code=exit_code)


if __name__ == "__main__":
    main()
