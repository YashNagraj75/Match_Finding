#!/usr/bin/env python3
"""Streamlit app for processing candidate CSV files with astrological matching."""

import streamlit as st
import pandas as pd
import difflib
import io
import time
from datetime import datetime

# Import processing functions from existing script
from process_candidates_csv import (
    get_coordinates_from_birthplace,
    format_dob_components,
    get_match_score,
    FEMALE_DATA,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = {
    "Name": "Name",
    "DOB": "DOB",
    "time_of_birth": "time_of_birth",
    "place_of_birth": "place_of_birth",
}

FUZZY_CUTOFF = 0.6  # similarity threshold for column-name suggestions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fuzzy_match(name: str, choices: list[str]) -> str | None:
    """Return the best fuzzy match for *name* among *choices*, or None."""
    matches = difflib.get_close_matches(name, choices, n=1, cutoff=FUZZY_CUTOFF)
    return matches[0] if matches else None


def validate_columns(uploaded_columns: list[str]) -> tuple[dict, list[str], list[str]]:
    """
    Validate uploaded CSV columns against REQUIRED_COLUMNS.

    Returns
    -------
    mapping : dict
        {required_col: actual_col_in_upload} for every required column that
        was found (exact or fuzzy).
    warnings : list[str]
        Messages about columns matched via fuzzy matching (probable misspelling).
    errors : list[str]
        Messages about columns that are completely missing.
    """
    mapping: dict[str, str] = {}
    warnings: list[str] = []
    errors: list[str] = []

    for req_col in REQUIRED_COLUMNS:
        if req_col in uploaded_columns:
            # Exact match
            mapping[req_col] = req_col
        else:
            # Try fuzzy match (case-insensitive comparison list)
            suggestion = _fuzzy_match(req_col.lower(), [c.lower() for c in uploaded_columns])
            if suggestion:
                # Map back to original-case column name
                original = next(c for c in uploaded_columns if c.lower() == suggestion)
                mapping[req_col] = original
                warnings.append(
                    f"Column **`{original}`** looks like a misspelling of "
                    f"**`{req_col}`** — it will be used as `{req_col}`."
                )
            else:
                errors.append(
                    f"Required column **`{req_col}`** is missing and no similar "
                    f"column name was found in the uploaded file."
                )

    return mapping, warnings, errors


def read_csv_auto_encoding(file) -> pd.DataFrame:
    """Read a CSV trying common encodings so Windows-generated files don't fail."""
    file_bytes = file.read()
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]

    # Use chardet for a better first guess if available
    try:
        import chardet
        detected = chardet.detect(file_bytes).get("encoding", "")
        if detected and detected.lower() not in [e.lower() for e in encodings]:
            encodings.insert(0, detected)
        elif detected:
            encodings = [detected] + [e for e in encodings if e.lower() != detected.lower()]
    except ImportError:
        pass

    last_err: Exception = RuntimeError("No encodings tried")
    for enc in encodings:
        try:
            return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
        except (UnicodeDecodeError, LookupError) as e:
            last_err = e
    raise last_err


def to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    """Convert a DataFrame to XLSX bytes in memory."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    return buf.getvalue()


def reset_app():
    """Clear all session state to start fresh."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
if "merged_df" not in st.session_state:
    st.session_state.merged_df = None
if "filtered_df" not in st.session_state:
    st.session_state.filtered_df = None
if "processed" not in st.session_state:
    st.session_state.processed = False
if "xlsx_bytes" not in st.session_state:
    st.session_state.xlsx_bytes = None
if "xlsx_filename" not in st.session_state:
    st.session_state.xlsx_filename = None

# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Candidate Compatibility Checker",
    page_icon="⭐",
    layout="wide",
)

st.title("⭐ Candidate Compatibility Checker")
st.markdown(
    "Upload a CSV of candidates to compute astrological compatibility scores. "
    "The file must contain the columns **Name**, **DOB**, **time_of_birth**, "
    "and **place_of_birth**. Extra columns are kept as-is."
)

# ---------------------------------------------------------------------------
# Reset button — always visible when results exist
# ---------------------------------------------------------------------------
if st.session_state.processed:
    if st.button("🔄 Reset — Process New Batch", type="secondary"):
        reset_app()
        st.rerun()

uploaded_file = st.file_uploader("Upload candidate CSV", type=["csv"])

if uploaded_file is not None and not st.session_state.processed:
    # ------------------------------------------------------------------
    # 1. Read & validate
    # ------------------------------------------------------------------
    try:
        raw_df = read_csv_auto_encoding(uploaded_file)
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        st.stop()

    col_mapping, col_warnings, col_errors = validate_columns(list(raw_df.columns))

    for w in col_warnings:
        st.warning(w)
    for e in col_errors:
        st.error(e)

    if col_errors:
        st.info("Please fix the column names and re-upload the file.")
        st.stop()

    # Build a normalised working copy with canonical column names
    work_df = raw_df.copy()
    rename_map = {actual: canonical for canonical, actual in col_mapping.items() if actual != canonical}
    if rename_map:
        work_df = work_df.rename(columns=rename_map)

    st.subheader("📄 Uploaded Data Preview")
    st.dataframe(raw_df, use_container_width=True)

    # ------------------------------------------------------------------
    # 2. Process candidates
    # ------------------------------------------------------------------
    if st.button("🚀 Process Candidates", type="primary"):
        total = len(work_df)
        results: list[dict] = []
        progress_bar = st.progress(0, text="Starting…")

        status_container = st.status("Processing candidates…", expanded=True)

        for idx, row in work_df.iterrows():
            name = str(row.get("Name", "")).strip()
            dob = row.get("DOB", "")
            birthplace = row.get("place_of_birth", "")
            birth_time = row.get("time_of_birth", None)

            candidate_num = idx + 1
            progress_bar.progress(
                candidate_num / total,
                text=f"Processing {candidate_num}/{total}: {name}",
            )

            if not name:
                status_container.write(f"⚠️  Row {candidate_num}: Empty name — skipped")
                results.append({"_status": "skipped — empty name"})
                continue

            status_container.write(f"⏳ {candidate_num}/{total} — **{name}**")

            result = get_match_score(name, dob, birthplace, birth_time)

            if "error" in result:
                status_container.write(f"  ❌ {name}: {result['error']}")
                results.append({"_status": f"error — {result['error']}"})
            else:
                status_container.write(
                    f"  ✅ {name}: {result.get('ashtakoota_received_points', '?')}"
                    f"/{result.get('ashtakoota_total_points', '?')} points"
                )
                results.append(result)

        progress_bar.progress(1.0, text="Done!")
        status_container.update(label="✅ Processing complete!", state="complete")

        # ------------------------------------------------------------------
        # 3. Merge results into original data
        # ------------------------------------------------------------------
        results_df = pd.DataFrame(results)

        # Drop columns that duplicate original data to avoid _x/_y suffixes
        drop_cols = [c for c in ["name", "dob", "birthplace", "time_of_birth"] if c in results_df.columns]
        results_df = results_df.drop(columns=drop_cols, errors="ignore")

        # Align indices and concat horizontally
        results_df.index = raw_df.index
        merged_df = pd.concat([raw_df, results_df], axis=1)

        # ------------------------------------------------------------------
        # 4. Filter: bhakut == 7 AND nadi == 8
        # ------------------------------------------------------------------
        filter_cols_present = (
            "bhakut_received_points" in merged_df.columns
            and "nadi_received_points" in merged_df.columns
        )

        if filter_cols_present:
            filtered_df = merged_df[
                (merged_df["bhakut_received_points"] == 7)
                & (merged_df["nadi_received_points"] == 8)
            ].copy()
        else:
            filtered_df = merged_df

        # Prepare XLSX
        download_df = filtered_df if filter_cols_present and not filtered_df.empty else merged_df
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save everything to session state
        st.session_state.merged_df = merged_df
        st.session_state.filtered_df = filtered_df
        st.session_state.filter_cols_present = filter_cols_present
        st.session_state.xlsx_bytes = to_xlsx_bytes(download_df)
        st.session_state.xlsx_filename = f"compatibility_results_filtered_{timestamp}.xlsx"
        st.session_state.processed = True
        st.rerun()

# ---------------------------------------------------------------------------
# Display persisted results (survives reruns, downloads, etc.)
# ---------------------------------------------------------------------------
if st.session_state.processed:
    merged_df = st.session_state.merged_df
    filtered_df = st.session_state.filtered_df
    filter_cols_present = st.session_state.get("filter_cols_present", False)

    st.subheader("📊 All Results")
    st.dataframe(merged_df, use_container_width=True)

    if filter_cols_present:
        st.subheader(
            f"✅ Filtered Results — Bhakut = 7 & Nadi = 8  "
            f"({len(filtered_df)} of {len(merged_df)} candidates)"
        )
        if filtered_df.empty:
            st.info("No candidates matched the filter criteria.")
        else:
            st.dataframe(filtered_df, use_container_width=True)
    else:
        st.warning(
            "Could not apply Bhakut/Nadi filter — result columns "
            "`bhakut_received_points` or `nadi_received_points` are missing."
        )

    st.download_button(
        label="⬇️ Download Filtered Results as XLSX",
        data=st.session_state.xlsx_bytes,
        file_name=st.session_state.xlsx_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
