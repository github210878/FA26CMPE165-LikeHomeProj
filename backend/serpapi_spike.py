import os
import time

import requests
from dotenv import load_dotenv


# Load variables from backend/.env
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_URL = os.getenv("EXTERNAL_API_URL")


def test_hotel_search():
    # Make sure our environment variables loaded
    if not API_KEY:
        print("ERROR: API_KEY was not found in .env")
        return

    if not API_URL:
        print("ERROR: EXTERNAL_API_URL was not found in .env")
        return

    # Parameters for our LikeHome hotel search test
    params = {
        "engine": "google_hotels",
        "q": "San Mateo, CA",
        "check_in_date": "2026-10-10",
        "check_out_date": "2026-10-12",
        "adults": 2,
        "children": 0,
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "api_key": API_KEY
    }


    print("=== LikeHome SerpApi Feasibility Spike ===")
    print(f"Destination: {params['q']}")
    print(f"Check-in: {params['check_in_date']}")
    print(f"Check-out: {params['check_out_date']}")
    print(f"Adults: {params['adults']}")
    print()

    start_time = time.perf_counter()

    try:
        response = requests.get(
            API_URL,
            params=params,
            timeout=30
        )

        latency = time.perf_counter() - start_time

        print(f"HTTP Status: {response.status_code}")
        print(f"Round-trip latency: {latency:.2f} seconds")

        response.raise_for_status()

        data = response.json()

        # SerpApi can return an error inside the JSON
        if "error" in data:
            print(f"SerpApi Error: {data['error']}")
            return

        # SerpApi hotel results
        hotels = data.get("properties", [])

        print(f"Hotels returned: {len(hotels)}")

        metadata = data.get("search_metadata", {})
        if metadata.get("total_time_taken") is not None:
            print(
                "SerpApi processing time:",
                metadata.get("total_time_taken"),
                "seconds"
            )

        print("\n=== First 5 Hotels ===")

        for hotel in hotels[:5]:
            rate = hotel.get("rate_per_night", {})

            print("\n------------------------------")
            print("Name:", hotel.get("name"))
            print("Rating:", hotel.get("overall_rating"))
            print("Reviews:", hotel.get("reviews"))
            print("Price:", rate.get("lowest"))
            print("Property Token:", hotel.get("property_token"))
            print("Amenities:", hotel.get("amenities", [])[:5])

        # Check whether another page exists
        pagination = data.get("serpapi_pagination", {})

        print("\n=== Pagination / Limits ===")
        print(
            "Next page available:",
            bool(pagination.get("next_page_token"))
        )

    except requests.Timeout:
        print("ERROR: SerpApi request timed out.")

    except requests.RequestException:
        print("ERROR: Request failed.")
        print(f"HTTP Status: {response.status_code}")

    except ValueError:
        print("ERROR: SerpApi did not return valid JSON.")


if __name__ == "__main__":
    test_hotel_search()