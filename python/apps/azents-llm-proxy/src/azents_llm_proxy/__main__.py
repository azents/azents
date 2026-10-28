"""Start the packaged independent Proxy, not the Azents server or Worker."""

import os
import sys

import uvicorn
from pydantic import ValidationError

from azents_llm_proxy.config import Settings


def main() -> None:
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    # Import only after disabling third-party dotenv discovery.
    from azents_llm_proxy.application import create_application  # noqa: PLC0415

    try:
        settings = Settings()
        app = create_application(settings)
    except ValidationError, RuntimeError:
        sys.stderr.write("Inference Proxy configuration is invalid.\n")
        raise SystemExit(1) from None
    uvicorn.run(app, host="0.0.0.0", port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
