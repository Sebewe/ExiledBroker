"""Write the API's OpenAPI schema, from which the frontend's types are generated:

    python -m exiledbroker.api.schema > web/openapi.json   (or `npm run gen:api` in web/)

tests/test_api.py fails if the committed web/openapi.json is out of date."""

import json

from exiledbroker.api.app import create_app


def schema() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    print(schema(), end="")
