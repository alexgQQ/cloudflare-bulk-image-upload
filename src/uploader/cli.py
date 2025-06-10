import argparse
import os
import json
import configparser
from typing import Optional, Generator

import sys

from dotenv import load_dotenv
from uploader import CFImageUploader, ImageUpload


class ConfigError(Exception):
    pass


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


def load_ini(ini_file: str) -> tuple[str, str]:
    try:
        config = configparser.ConfigParser(ini_file)
        account_id = config.get("CF_ACCOUNT_ID", None)
        api_key = config.get("CF_API_KEY", None)
    except configparser.Error as err:
        raise ConfigError(f"Unable to read auth values from {config}")
    else:
        return account_id, api_key


def load_env(env_file: Optional[str] = None) -> tuple[str, str]:
    if not load_dotenv(env_file):
        raise ConfigError(f"Unable to load env file for auth {env_file}")
    try:
        account_id = os.environ["CF_ACCOUNT_ID"]
        api_key = os.environ["CF_API_KEY"]
    except KeyError:
        raise ConfigError(f"Unable to load env vars for auth")
    else:
        return account_id, api_key


def load_auth(config: Optional[str] = None) -> tuple[str, str]:
    if config is not None and os.path.exists(config):
        if config.endswith(".ini"):
            account_id, api_key = load_ini(config)
        else:
            account_id, api_key = load_env(config)
    else:
        account_id, api_key = load_env()
    return account_id, api_key


def exit(message: Optional[str] = None, code: int = 0, error: Optional[Exception] = None):
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
        account_id, api_key = load_auth()
    except ConfigError as err:
        exit(error=err)

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
