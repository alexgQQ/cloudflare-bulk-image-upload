
# Bulk Image Uploader to Cloudflare Images

This is a tool made to upload a large amount of images to Cloudflare Images quickly. This makes use of their [batch api](https://developers.cloudflare.com/images/upload-images/images-batch/) which has a higher threshold for rate limits.

## Install

This module only requires Python 3.12+. To install:
```bash
git clone https://github.com/alexgQQ/cloudflare-bulk-image-upload
cd cloudflare-bulk-image-upload
pip install .
```
To uninstall:
```bash
pip uninstall cloudflare_image_uploader
```

## Usage

You'll need a valid Cloudflare account id with the Images service enabled and an API key with read and write Image permissions. Make one [if you need to](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) for usage below.

Make sure the application runs and check out the usage text.
```bash
python -m cloudflare_image_uploader --version
python -m cloudflare_image_uploader --help
```

This will upload all the images in `images/to/upload` 
```bash
python -m cloudflare_image_uploader --images images/to/upload \
    --account $CF_ACCOUNT_ID --key $CF_API_KEY
```

Multiple directories and images can be passed as an input where all will be uploaded.
```bash
python -m cloudflare_image_uploader --images one_image.jpeg images/to/upload another_image.png \
    --account $CF_ACCOUNT_ID --key $CF_API_KEY
```

By default the account id and api key will be read from `CF_ACCOUNT_ID` and `CF_API_KEY` environment variables. The cli argument can be ignored if those are set.

This is also made to work with pipelining. Image files can be read by stdin and passed to a file.
```bash
cat images.txt | python -m cloudflare_image_uploader --images - > results.json
```


### Importing

This is also made to be used in code. The top level functionality can be imported and used however you'd like.
```python
import os

from cloudflare_image_uploader import ImageUpload, CFImageUploader

uploads = []
for image in os.listdir("dir/containing/images"):
    uploads.append(ImageUpload(filepath=image))

account_id = os.environ.get("CF_ACCOUNT_ID")
api_key = os.environ.get("CF_API_KEY")
uploader = CFImageUploader(account_id, api_key)
results, errors = uploader(uploads)

if len(errors) > 0:
    print("errors uploading")

for cfid, image in results.items():
    print(f"{image.filepath} - Cloudflare Image ID {cfid}")
``` 

### Development

Make a venv to work in.
```bash
make env
source .venv/bin/activate
pip install -e .[dev]
```
Keep it clean and functional
```bash
make fmt
make test
```

### Docs

The documentation is generated with [MkDocs](https://www.mkdocs.org/) along with plugins listed in the project dependencies. 
```bash
pip install .[doc]
mkdocs build
```
Run the files locally for checking
```bash
mkdocs serve
```
