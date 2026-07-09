"""Source verification for the Kochi Urban Mobility Transit Optimizer.

Performs a single authenticated request against each external data source to
confirm it is reachable and returning the expected data, before any ingestion
pipelines are built (Phase 0, deliverable D0.2).

Verifies:
    - TomTom Routing API (traffic / travel times) — requires an API key.
    - Open-Meteo API (weather / rainfall) — no key required.

Run:
    python ingestion/verify_sources.py
"""

import logging
import os
import sys

import requests
from dotenv import load_dotenv

# Configure logging once, at module load. All functions use this logger
# rather than print(), so output has timestamps, levels, and is redirectable.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Kochi city-centre coordinates, used for the weather verification call.
KOCHI_LAT = 9.9312
KOCHI_LON = 76.2673

# Network calls should never hang forever; fail fast if a source is unreachable.
REQUEST_TIMEOUT_SECONDS = 10

def load_api_key() -> str:
    """Load the TomTom API key from the .env file.

    Reads environment variables from a local .env file (never committed) and
    returns the TomTom API key. Fails fast with a clear message if the key is
    absent, rather than letting a missing key surface as a confusing error
    later in the request functions.

    Returns:
        The TomTom API key as a string.

    Raises:
        SystemExit: If TOMTOM_API_KEY is not set in the environment.
    """
    load_dotenv()  # reads .env from the project root into os.environ
    api_key = os.getenv("TOMTOM_API_KEY")

    if not api_key:
        logger.error("TOMTOM_API_KEY not found. Check that .env exists and contains it.")
        sys.exit(1)

    logger.info("TomTom API key loaded successfully.")
    return api_key

def verify_tomtom(api_key: str) -> bool:
    """Verify the TomTom Routing API is reachable and returning travel times.

    Makes a single authenticated calculateRoute request for a fixed Kochi
    route (Kaloor -> Vyttila) and confirms a travel time is returned.

    Args:
        api_key: A valid TomTom API key.

    Returns:
        True if the API responded 200 and a travel time was parsed,
        False on any HTTP error, network failure, or unexpected response shape.
    """
    # Fixed test route (lat,lon:lat,lon). Hard-coded for verification only;
    # real OD pairs will come from config in Phase 1.
    route = "9.9970,76.2990:9.9670,76.3210"
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{route}/json"
    params = {"key": api_key}

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        # Network-level failure: DNS, timeout, connection refused, etc.
        logger.error("TomTom request failed (network error): %s", exc)
        return False

    if response.status_code != 200:
        logger.error("TomTom returned HTTP %s (expected 200).", response.status_code)
        return False

    try:
        summary = response.json()["routes"][0]["summary"]
        travel_seconds = summary["travelTimeInSeconds"]
    except (KeyError, IndexError, ValueError) as exc:
        # Response wasn't the shape we expect (structure changed, empty body, etc.)
        logger.error("TomTom response missing expected fields: %s", exc)
        return False

    logger.info(
        "TomTom OK — Kaloor->Vyttila travel time: %s min (%s sec).",
        round(travel_seconds / 60, 1),
        travel_seconds,
    )
    return True

if __name__ == "__main__":
    key = load_api_key()
    verify_tomtom(key)