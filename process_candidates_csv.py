#!/usr/bin/env python3
"""Process candidates from CSV file with 24-hour time format"""

import pandas as pd
import requests
import googlemaps
import time
import sys
from pathlib import Path
from datetime import datetime

# Configuration
CSV_INPUT = "candidates_new.csv"
CSV_OUTPUT = "csv_compatibility_results_new.csv"
GMAPS_API_KEY = "AIzaSyAYvOc1EHEMvhXjlWQkc7Wp-8fNkkK8_sA"
ASTRO_API_KEY = "ak-643849987d54535c506cc408bbac992e80dfd53e"

# Female candidate data (Solapur, 8/8/1998, 10:00 AM)
FEMALE_DATA = {
    "f_day": 8,
    "f_month": 8,
    "f_year": 1998,
    "f_hour": 10,
    "f_min": 0,
    "f_lat": 17.6869,
    "f_lon": 75.8320,
    "f_tzone": 5.5,
}

# Initialize Google Maps client
gmaps = googlemaps.Client(key=GMAPS_API_KEY)


def log_message(msg):
    """Log message with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    print(log_entry)
    with open("processing_log.txt", "a") as f:
        f.write(log_entry + "\n")


def get_coordinates_from_birthplace(birthplace):
    """Get coordinates using Google Maps API"""
    try:
        geocode_result = gmaps.geocode(birthplace)
        if geocode_result:
            lat = geocode_result[0]["geometry"]["location"]["lat"]
            lon = geocode_result[0]["geometry"]["location"]["lng"]
            return lat, lon
    except Exception as e:
        log_message(f"  Error geocoding {birthplace}: {e}")
    return None, None


def format_dob_components(dob_string, time_string=None):
    """Parse DOB and time strings. Time can be 24-hour format (HH:MM)"""
    try:
        from datetime import datetime as dt_module

        dob_string = str(dob_string).strip()
        dob_formats = ["%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"]
        parsed_dt = None

        for fmt in dob_formats:
            try:
                parsed_dt = dt_module.strptime(dob_string, fmt)
                break
            except:
                continue

        if parsed_dt is None:
            return None

        hour, minute = 0, 0
        if time_string and str(time_string).strip().lower() != "nan":
            time_str = str(time_string).strip().lower()
            try:
                # Handle 24-hour format (HH:MM)
                time_parts = time_str.split(":")
                if len(time_parts) >= 2:
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                else:
                    # Fallback to dot format if no colon
                    time_parts = time_str.split(".")
                    hour = int(time_parts[0])
                    minute = int(time_parts[1]) * 6 if len(time_parts) > 1 else 0
            except:
                pass

        return {
            "day": parsed_dt.day,
            "month": parsed_dt.month,
            "year": parsed_dt.year,
            "hour": hour,
            "minute": minute,
        }
    except Exception as e:
        log_message(f"  Error parsing DOB: {e}")
        return None


def get_match_score(
    male_name, male_dob, male_birthplace, male_time=None, male_tzone=5.5, max_retries=3
):
    """Get astrological match score with retry logic"""

    # Parse DOB
    dob_components = format_dob_components(male_dob, male_time)
    if not dob_components:
        return {"error": f"Could not parse DOB: {male_dob}"}

    # Get coordinates
    m_lat, m_lon = get_coordinates_from_birthplace(male_birthplace)
    if m_lat is None or m_lon is None:
        return {"error": f"Could not get coordinates for {male_birthplace}"}

    # Prepare API data
    api_data = {
        "m_day": dob_components["day"],
        "m_month": dob_components["month"],
        "m_year": dob_components["year"],
        "m_hour": dob_components["hour"],
        "m_min": dob_components["minute"],
        "m_lat": m_lat,
        "m_lon": m_lon,
        "m_tzone": male_tzone,
        "f_day": FEMALE_DATA["f_day"],
        "f_month": FEMALE_DATA["f_month"],
        "f_year": FEMALE_DATA["f_year"],
        "f_hour": FEMALE_DATA["f_hour"],
        "f_min": FEMALE_DATA["f_min"],
        "f_lat": FEMALE_DATA["f_lat"],
        "f_lon": FEMALE_DATA["f_lon"],
        "f_tzone": FEMALE_DATA["f_tzone"],
    }

    api_url = "https://json.astrologyapi.com/v1/match_making_detailed_report"
    headers = {"x-astrologyapi-key": ASTRO_API_KEY, "Content-Type": "application/json"}

    for attempt in range(max_retries):
        try:
            time.sleep(1)  # Rate limiting
            response = requests.post(
                api_url, headers=headers, json=api_data, timeout=10
            )

            # Check for rate limiting or 405 errors before raise_for_status
            if response.status_code == 429:
                wait_time = 2**attempt
                log_message(f"  Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue

            if response.status_code == 405:
                wait_time = 2**attempt
                log_message(f"  405 error, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            # Raise exception for other HTTP errors
            response.raise_for_status()

            api_response = response.json()

            ashtakoota = api_response.get("ashtakoota", {})
            total_info = ashtakoota.get("total", {})
            manglik = api_response.get("manglik", {})

            result = {
                "name": male_name,
                "dob": male_dob,
                "birthplace": male_birthplace,
                "time_of_birth": male_time,
                "latitude": m_lat,
                "longitude": m_lon,
                "ashtakoota_total_points": total_info.get("total_points", 0),
                "ashtakoota_received_points": total_info.get("received_points", 0),
                "ashtakoota_minimum_required": total_info.get("minimum_required", 0),
                "ashtakoota_percentage": (
                    total_info.get("received_points", 0)
                    / total_info.get("total_points", 1)
                )
                * 100,
                "match_status": ashtakoota.get("conclusion", {}).get("status", False),
                "match_report": ashtakoota.get("conclusion", {}).get("report", ""),
                "manglik_status": manglik.get("status", False),
                "manglik_male_percentage": manglik.get("male_percentage", 0),
                "manglik_female_percentage": manglik.get("female_percentage", 0),
                "rajju_dosha": api_response.get("rajju_dosha", {}).get("status", False),
                "vedha_dosha": api_response.get("vedha_dosha", {}).get("status", False),
                "overall_report": api_response.get("conclusion", {}).get(
                    "match_report", ""
                ),
            }

            # Add individual koot scores
            for koot_name, koot_data in ashtakoota.items():
                if koot_name not in ["total", "conclusion"]:
                    result[f"{koot_name}_received_points"] = koot_data.get(
                        "received_points", 0
                    )
                    result[f"{koot_name}_total_points"] = koot_data.get(
                        "total_points", 0
                    )

            return result

        except requests.exceptions.HTTPError as e:
            return {"error": str(e)}
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                log_message("  Timeout, retrying...")
                continue
            return {"error": "Request timeout"}
        except Exception as e:
            return {"error": str(e)}

    return {"error": "Max retries exceeded"}


def process_csv_candidates():
    """Main processing function with automatic retry loop"""
    log_message("=" * 80)
    log_message("STARTING CSV CANDIDATE PROCESSING WITH AUTO-RETRY")
    log_message("=" * 80)

    # Load CSV
    if not Path(CSV_INPUT).exists():
        log_message(f"✗ CSV file not found: {CSV_INPUT}")
        return

    try:
        candidates_df = pd.read_csv(CSV_INPUT)
        total_candidates = len(candidates_df)
        log_message(f"Total candidates in CSV: {total_candidates}")
    except Exception as e:
        log_message(f"✗ Error reading CSV: {e}")
        return

    max_loops = 5  # Maximum number of loops to try
    loop_count = 0

    while loop_count < max_loops:
        loop_count += 1
        log_message(f"\n{'=' * 80}")
        log_message(f"LOOP {loop_count}/{max_loops}")
        log_message(f"{'=' * 80}")

        # Load existing results to check what's been processed
        processed_candidates = set()
        successfully_processed = 0
        if Path(CSV_OUTPUT).exists():
            try:
                existing_df = pd.read_csv(CSV_OUTPUT)
                processed_candidates = set(existing_df["name"].values)
                successfully_processed = len(processed_candidates)
            except Exception as e:
                log_message(f"Error reading existing results: {e}")

        # Get candidates that still need processing
        remaining_candidates = []
        for idx, row in candidates_df.iterrows():
            name = str(row.get("Name", "")).strip()
            if name and name not in processed_candidates:
                remaining_candidates.append(
                    {
                        "name": name,
                        "dob": row.get("DOB", ""),
                        "birthplace": row.get("place_of_birth", ""),
                        "time": row.get("time_of_birth", None),
                    }
                )

        remaining_count = len(remaining_candidates)

        log_message(f"Status: {successfully_processed}/{total_candidates} processed")
        log_message(f"Remaining: {remaining_count} candidates")

        # If all done, exit loop
        if remaining_count == 0:
            log_message("\n✓✓✓ ALL CANDIDATES SUCCESSFULLY PROCESSED! ✓✓✓")
            break

        # Process remaining candidates
        new_results = []
        failed_count = 0

        for i, candidate in enumerate(remaining_candidates, 1):
            try:
                name = candidate["name"]
                progress = f"  [{loop_count}:{i}/{remaining_count}] {name:<50}"
                print(progress, end=" ", flush=True)

                result = get_match_score(
                    name, candidate["dob"], candidate["birthplace"], candidate["time"]
                )

                if "error" not in result:
                    new_results.append(result)
                    print("✓")
                    log_message(f"    ✓ {name}")
                else:
                    print("✗")
                    failed_count += 1
                    log_message(f"    ✗ {name} - {result['error'][:60]}")

                # Rate limiting pause
                if i % 5 == 0:
                    log_message(
                        f"    [Rate limit: 5 second pause after {i} candidates]"
                    )
                    time.sleep(5)
                else:
                    time.sleep(2)

            except Exception as e:
                print("✗")
                failed_count += 1
                log_message(f"    ✗ Exception for {candidate['name']}: {e}")

        # Save results from this loop
        if new_results:
            new_df = pd.DataFrame(new_results)

            if Path(CSV_OUTPUT).exists():
                existing_df = pd.read_csv(CSV_OUTPUT)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=["name"], keep="last")
            else:
                combined_df = new_df

            combined_df.to_csv(CSV_OUTPUT, index=False)
            log_message(f"\n  ✓ Saved {len(new_results)} new results")
            log_message(f"  Total in results: {len(combined_df)}")

            if failed_count > 0:
                log_message(f"  Failed this loop: {failed_count}")
                log_message("  Will retry in next loop...")
        else:
            log_message(f"\n  ✗ No results this loop (all {failed_count} failed)")

        # Check if we should continue
        if remaining_count > 0 and loop_count < max_loops:
            log_message("\n  Preparing for next loop...")
            log_message("  Waiting 10 seconds before retry...")
            time.sleep(10)
        elif loop_count >= max_loops and remaining_count > 0:
            log_message(
                f"\n  ⚠️  Max loops ({max_loops}) reached but {remaining_count} still pending"
            )
            break

    # Final summary
    if Path(CSV_OUTPUT).exists():
        final_df = pd.read_csv(CSV_OUTPUT)
        log_message(f"\n{'=' * 80}")
        log_message("FINAL SUMMARY")
        log_message(f"{'=' * 80}")
        log_message(f"Total processed: {len(final_df)}/{total_candidates}")
        log_message(f"Success rate: {(len(final_df) / total_candidates) * 100:.1f}%")
        log_message(f"Average match: {final_df['ashtakoota_percentage'].mean():.2f}%")
        log_message(f"Best match: {final_df['ashtakoota_percentage'].max():.2f}%")
        log_message(f"Results saved to: {CSV_OUTPUT}")
    else:
        log_message("\n✗ No results saved!")


if __name__ == "__main__":
    try:
        process_csv_candidates()
    except KeyboardInterrupt:
        log_message("\n✗ Processing interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_message(f"\n✗ Fatal error: {e}")
        sys.exit(1)
