# app.py — Multimode survey (no manifest, root media)
# Uses all image/video files in the repo root with ~2s exposure.
# Modes via UI/URL: img_sliders (default), img_text, vid_sliders, vid_text.
# Order is fully random each time a participant starts.
# Includes: trial cap, dropout info, order logging, mode select UI, Sheets logging.

# --- imports ---
import time
import uuid
import random
import base64
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

import streamlit as st

# ======================== CONFIG ========================
# Study ID label (for your data)
STUDY_ID = "two_second_multimode_nomf_v2"

# Currently use repo root as media directory, since your files are not in folders.
# If you later move them into images/ and videos/, change these to Path("images") / Path("videos").
IMAGE_DIR = Path(".")   # or Path("images")
VIDEO_DIR = Path(".")   # or Path("videos")

SHOW_SECONDS = 2.0           # target exposure duration (seconds)
MAX_TRIALS = 30              # cap number of stimuli per participant
MIN_TEXT_CHARS = 1           # minimum chars required in text responses

# Modes: img_sliders (default) | img_text | vid_sliders | vid_text
DEFAULT_MODE = "img_sliders"
ALL_MODES = ["img_sliders", "img_text", "vid_sliders", "vid_text"]

# Emotion sliders for slider modes
EMOTIONS = [
    "Angry", "Happy", "Sad", "Scared",
    "Surprised", "Neutral", "Disgusted", "Contempt",
]
RATING_MIN, RATING_MAX, RATING_DEFAULT = 0, 100, 0

# Optional Google Sheets (safe to leave empty locally)
try:
    SHEET_URL = st.secrets["google_sheets"]["sheet_url"]
except Exception:
    SHEET_URL = ""

st.set_page_config(page_title="2-Second Media Survey (Multimode)", layout="centered")

# --- responsive image helper (no scrolling) ---
def render_image_responsive(path: str, max_vw: int = 80, max_vh: int = 70):
    """
    Show an image centered, scaled to at most max_vw% of viewport width
    and max_vh% of viewport height. Keeps aspect ratio, no scrolling.
    """
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = Path(path).suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;">
          <img src="data:{mime};base64,{b64}"
               style="max-width:{max_vw}vw; max-height:{max_vh}vh;
                      width:auto; height:auto; border-radius:12px;" />
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- autoplay muted video helper ---
def render_video_autoplay(path: Path, max_vw: int = 80, max_vh: int = 70):
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = path.suffix.lower().lstrip(".")
    mime = "video/mp4" if ext in {"mp4", "mov", "m4v"} else f"video/{ext}"
    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;">
          <video autoplay muted playsinline
                 style="max-width:{max_vw}vw; max-height:{max_vh}vh; border-radius:12px;">
            <source src="data:{mime};base64,{b64}" type="{mime}">
            Your browser does not support the video tag.
          </video>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- DEBUG STATUS PANEL (sidebar) ---
with st.sidebar:
    st.header("Data Save Status")
    st.write("Sheet URL set:", bool(SHEET_URL))
    try:
        sa_email = st.secrets["google_service_account"]["client_email"]
        st.write("Service account:", sa_email)
    except Exception:
        st.write("Service account:", "(not loaded)")

    st.subheader("Current participant fields")
    st.write("study_id:", st.session_state.get("study_id"))
    st.write("mode:", st.session_state.get("mode"))
    st.write("participant_id:", st.session_state.get("participant_id"))
    st.write("name:", st.session_state.get("name"))
    st.write("age:", st.session_state.get("age"))
    st.write("gender:", st.session_state.get("gender"))
    st.write("nationality:", st.session_state.get("nationality"))
    st.write("order:", st.session_state.get("order"))
    st.write("total_trials:", st.session_state.get("total_trials"))
    st.write("idx (0-based):", st.session_state.get("idx"))

# -------------------- Utility --------------------
def get_mode_from_query() -> str:
    """Read initial mode from query params, fallback to DEFAULT_MODE."""
    try:
        params = st.query_params  # new Streamlit API
        raw = params.get("mode", [DEFAULT_MODE])
        mode = raw[0] if isinstance(raw, list) else raw
    except Exception:
        params = st.experimental_get_query_params()
        mode = params.get("mode", [DEFAULT_MODE])[0]
    return mode if mode in ALL_MODES else DEFAULT_MODE

def generate_participant_id() -> str:
    return uuid.uuid4().hex[:8].upper()

def randomize_order(n: int) -> List[int]:
    """
    Fully random order each time this is called.
    No dependence on participant_id.
    Returns a permutation of indices [0..n-1].
    """
    order = list(range(n))
    random.shuffle(order)
    return order

def ratings_to_dict(sliders: Dict[str, int]) -> Dict[str, int]:
    return {
        "rating_angry": sliders["Angry"],
        "rating_happy": sliders["Happy"],
        "rating_sad": sliders["Sad"],
        "rating_scared": sliders["Scared"],
        "rating_surprised": sliders["Surprised"],
        "rating_neutral": sliders["Neutral"],
        "rating_disgusted": sliders["Disgusted"],
        "rating_contempt": sliders["Contempt"],
    }

def load_media_files(dirpath: Path, exts) -> List[Path]:
    if not dirpath.exists():
        return []
    files = [
        p for p in sorted(dirpath.iterdir())
        if p.is_file() and p.suffix.lower() in exts
    ]
    return files

# -------------------- Google Sheets I/O (optional) --------------------
def get_worksheet():
    if not SHEET_URL:
        st.warning("Sheets: SHEET_URL is empty; skipping connection.")
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        sa_info = st.secrets["google_service_account"]
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials = Credentials.from_service_account_info(sa_info, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_url(SHEET_URL)
        try:
            ws = sh.worksheet("responses")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title="responses", rows=4000, cols=50)
            ws.append_row([
                "study_id", "mode", "participant_id", "consented", "consent_timestamp_iso",
                "name", "age", "gender", "nationality",
                "trial_index", "order_index", "total_trials", "n_completed", "order_sequence",
                "media_kind", "media_file",
                "rating_angry", "rating_happy", "rating_sad", "rating_scared",
                "rating_surprised", "rating_neutral", "rating_disgusted", "rating_contempt",
                "result_estimate", "free_text",
                "response_timestamp_iso"
            ])
        st.success("✔ Connected to Google Sheet.")
        return ws
    except Exception as e:
        import traceback
        st.error(f"Google Sheets connection error: {type(e).__name__}: {e}")
        st.code(traceback.format_exc())
        st.info("Common fixes: share the Sheet with the service account (Editor), enable Google Sheets + Drive APIs, and check secrets formatting.")
        return None

def append_row_to_sheet(ws, row: Dict[str, Any]):
    if ws is None:
        # Silent: just don't write if no worksheet
        return
    ordered = [
        row.get("study_id",""),
        row.get("mode",""),
        row.get("participant_id",""),
        row.get("consented",False),
        row.get("consent_timestamp_iso",""),
        row.get("name",""),
        row.get("age",""),
        row.get("gender",""),
        row.get("nationality",""),
        row.get("trial_index",""),
        row.get("order_index",""),
        row.get("total_trials",""),
        row.get("n_completed",""),
        row.get("order_sequence",""),
        row.get("media_kind",""),
        row.get("media_file",""),
        row.get("rating_angry",""),
        row.get("rating_happy",""),
        row.get("rating_sad",""),
        row.get("rating_scared",""),
        row.get("rating_surprised",""),
        row.get("rating_neutral",""),
        row.get("rating_disgusted",""),
        row.get("rating_contempt",""),
        row.get("result_estimate",""),
        row.get("free_text",""),
        row.get("response_timestamp_iso",""),
    ]
    try:
        ws.append_row(ordered, value_input_option="RAW")
    except Exception as e:
        st.error(f"Failed to append to Google Sheets: {e}")

# -------------------- App state & flow --------------------
def init_state(initial_mode: str):
    ss = st.session_state
    ss.setdefault("phase", "consent")
    # Basic identifiers
    ss.setdefault("study_id", STUDY_ID)
    # mode is stored once and then locked; initial_mode comes from query param
    ss.setdefault("mode", initial_mode)

    # Participant info
    ss.setdefault("consented", False)
    ss.setdefault("consent_timestamp_iso", "")
    ss.setdefault("participant_id", "")
    ss.setdefault("name", "")
    ss.setdefault("age", 0)
    ss.setdefault("gender", "")
    ss.setdefault("nationality", "")

    # Media selection
    ss.setdefault("media_list", [])      # list[Path]
    ss.setdefault("idx", 0)              # current trial index (0-based within selected trials)
    ss.setdefault("order", [])           # list of indices
    ss.setdefault("total_trials", 0)     # number of trials selected
    ss.setdefault("order_sequence", "")  # string of comma-separated indices
    ss.setdefault("show_started_at", None)

    # Responses
    ss.setdefault("responses", [])

    # Sheets
    ss.setdefault("ws", None)

    # Trial submission guard
    ss.setdefault("current_trial", None)
    ss.setdefault("trial_submitted", False)

def advance(phase: str):
    st.session_state.phase = phase
    st.rerun()

def record_and_next(extra: Dict[str, Any]):
    ss = st.session_state
    mode = ss.mode
    total = ss.total_trials or len(ss.order)
    i = ss.idx
    order_index = i + 1
    media_idx = ss.order[i]
    media_path = ss.media_list[media_idx]

    base_row = {
        "study_id": ss.get("study_id", STUDY_ID),
        "mode": mode,
        "participant_id": ss.participant_id,
        "consented": ss.consented,
        "consent_timestamp_iso": ss.consent_timestamp_iso,
        "name": ss.name,
        "age": ss.age,
        "gender": ss.gender,
        "nationality": ss.nationality,
        "trial_index": media_idx + 1,            # index in full media list (1-based)
        "order_index": order_index,              # 1..total_trials
        "total_trials": total,
        "n_completed": order_index,              # how many trials completed at this row
        "order_sequence": ss.order_sequence,     # same string for all trials
        "media_kind": "image" if mode.startswith("img") else "video",
        "media_file": media_path.name,
        **extra,
        "response_timestamp_iso": datetime.utcnow().isoformat() + "Z",
    }

    ss.responses.append(base_row)
    append_row_to_sheet(ss.ws, base_row)

    ss.idx += 1
    ss.show_started_at = None
    ss.trial_submitted = False
    ss.current_trial = None

    ss.phase = "done" if ss.idx >= total else "show"
    st.rerun()

# -------------------- Run --------------------
initial_mode = get_mode_from_query()
init_state(initial_mode)

# Lock mode in state but let consent screen override it explicitly
mode = st.session_state.mode

# One-time connect to Sheets (if configured)
if st.session_state.ws is None and SHEET_URL:
    st.session_state.ws = get_worksheet()

# ===== CONSENT =====
if st.session_state.phase == "consent":
    st.title("Consent to Participate")

    # Reset button: clears state so you can test with a truly "new participant"
    if st.button("🔁 Reset for new participant"):
        st.session_state.clear()
        st.rerun()

    # Mode selection dropdown
    st.subheader("Study version")
    default_index = ALL_MODES.index(mode) if mode in ALL_MODES else 0
    selected_mode = st.selectbox(
        "Please select the version of the study.",
        ALL_MODES,
        index=default_index,
    )
    st.session_state.mode = selected_mode
    mode = selected_mode  # local convenience

    st.write(f"""
This study shows a series of **{'images' if mode.startswith('img') else 'videos'}** for **{SHOW_SECONDS:.0f} seconds** each.
After each stimulus, you will {'rate emotions (0–100) and estimate whether the athlete won or lost' if 'sliders' in mode else 'describe the emotions you saw and estimate whether the athlete won or lost'}.
Participation is voluntary; you may stop at any time.
    """)

    # Generate a default ID if we don't have one yet
    if not st.session_state.participant_id:
        st.session_state.participant_id = generate_participant_id()

    agreed = st.checkbox("I consent to participate.")
    st.caption("A unique participant ID has been generated. You may override it if needed.")

    participant_id_input = st.text_input(
        "Participant ID",
        value=st.session_state.participant_id,
    )

    if st.button("Continue"):
        if not agreed:
            st.error("You must consent to proceed.")
        else:
            # Store the final ID the participant saw/edited
            final_pid = participant_id_input.strip()
            if final_pid:
                st.session_state.participant_id = final_pid

            st.session_state.consented = True
            st.session_state.consent_timestamp_iso = datetime.utcnow().isoformat() + "Z"
            advance("demographics")

# ===== DEMOGRAPHICS =====
elif st.session_state.phase == "demographics":
    mode = st.session_state.mode
    st.title("Participant Information")

    with st.form("demographics"):
        name_input = st.text_input("Full name", value=st.session_state.get("name", ""))
        age_input = st.number_input("Age", min_value=1, step=1, value=int(st.session_state.get("age", 18)) or 18)
        gender_choices = ["", "Female", "Male", "Non-binary / Other", "Prefer not to say"]
        gender_input = st.selectbox(
            "Gender",
            gender_choices,
            index=0 if not st.session_state.get("gender") else gender_choices.index(st.session_state.get("gender"))
        )
        nationality_input = st.text_input("Nationality", value=st.session_state.get("nationality", ""))

        submitted = st.form_submit_button("Start")
        if submitted:
            st.session_state.name = name_input.strip()
            try:
                st.session_state.age = int(age_input)
            except Exception:
                st.session_state.age = 0
            st.session_state.gender = gender_input.strip()
            st.session_state.nationality = nationality_input.strip()

            if (
                st.session_state.name
                and st.session_state.gender
                and st.session_state.nationality
                and st.session_state.age > 0
            ):
                # Load media from folder depending on mode
                if mode.startswith("img"):
                    media_files = load_media_files(IMAGE_DIR, {".png", ".jpg", ".jpeg", ".webp", ".bmp"})
                else:
                    media_files = load_media_files(VIDEO_DIR, {".mp4", ".mov", ".m4v"})

                if not media_files:
                    st.error(f"No media files found in this folder for mode '{mode}'.")
                    st.stop()

                # Random order of full pool
                full_n = len(media_files)
                full_order = randomize_order(full_n)

                # Cap to MAX_TRIALS
                n_trials = min(full_n, MAX_TRIALS)
                selected_indices = full_order[:n_trials]

                st.session_state.media_list = media_files
                st.session_state.order = selected_indices
                st.session_state.total_trials = n_trials
                st.session_state.order_sequence = ",".join(str(idx) for idx in selected_indices)

                st.session_state.idx = 0
                st.session_state.show_started_at = None
                st.session_state.current_trial = None
                st.session_state.trial_submitted = False

                advance("show")
            else:
                st.error("Please complete all demographic fields before starting.")

# ===== SHOW (stable ~2s exposure) =====
elif st.session_state.phase == "show":
    mode = st.session_state.mode
    media_list = st.session_state.media_list
    total = st.session_state.total_trials or len(st.session_state.order)
    if total == 0:
        st.error("No media selected. Please restart the study.")
        st.stop()

    i = st.session_state.idx
    media_idx = st.session_state.order[i]
    path = media_list[media_idx]

    if st.session_state.show_started_at is None:
        st.session_state.show_started_at = time.time()

    elapsed = time.time() - st.session_state.show_started_at
    remaining = SHOW_SECONDS - elapsed

    st.subheader(f"Stimulus {i+1} of {total}")

    if mode.startswith("img"):
        render_image_responsive(str(path), max_vw=80, max_vh=70)
    else:
        render_video_autoplay(path, max_vw=80, max_vh=70)

    if remaining > 0:
        st.caption(f"Next screen in {max(0.0, remaining):.1f}s…")
        time.sleep(0.1)
        st.rerun()
    else:
        advance("rate")

# ===== RATE — sliders or text depending on mode =====
elif st.session_state.phase == "rate":
    ss = st.session_state
    mode = ss.mode
    media_list = ss.media_list
    total = ss.total_trials or len(ss.order)
    i = ss.idx
    pos_1based = i + 1

    # trial submission guard: set current_trial when entering this phase
    if ss.current_trial != i:
        ss.current_trial = i
        ss.trial_submitted = False

    st.subheader(f"Respond to the last stimulus ({pos_1based} of {total})")

    # Slider modes: emotions sliders + result estimate (Won/Lost)
    if "sliders" in mode:
        st.caption("Move each slider (0–100). Then estimate whether the athlete won or lost the match.")
        with st.form(key=f"ratings_form_{i}"):
            sliders = {}
            for emo in EMOTIONS:
                sliders[emo] = st.slider(emo, RATING_MIN, RATING_MAX, RATING_DEFAULT, key=f"{emo}_{i}")

            result_estimate = st.radio(
                "According to your estimation, did the athlete win or lose the match?",
                ["Won", "Lost"],
                horizontal=True,
                index=None,
                key=f"result_{i}",
            )

            submitted = st.form_submit_button("Submit")
            if submitted:
                if ss.trial_submitted:
                    st.warning("This response has already been recorded.")
                elif result_estimate is None:
                    st.error("Please select Win or Lose before continuing.")
                else:
                    ss.trial_submitted = True
                    extra = {
                        **ratings_to_dict(sliders),
                        "result_estimate": result_estimate,
                        "free_text": "",
                    }
                    st.success("Response saved.")
                    record_and_next(extra)

    # Text modes: open text + result estimate (Won/Lost)
    else:
        st.caption("Describe the emotions you saw and estimate whether the athlete won or lost.")
        with st.form(key=f"text_form_{i}"):
            result_estimate = st.radio(
                "According to your estimation, did the athlete win or lose the match?",
                ["Won", "Lost"],
                horizontal=True,
                index=None,
                key=f"text_result_{i}",
            )

            text = st.text_area(
                "What emotions did the athlete display? "
                "Mention any and all types of emotions that you can think of.",
                height=160,
                key=f"text_{i}",
            )

            submitted = st.form_submit_button("Submit")
            if submitted:
                if ss.trial_submitted:
                    st.warning("This response has already been recorded.")
                elif result_estimate is None:
                    st.error("Please select Win or Lose before continuing.")
                elif len(text.strip()) < MIN_TEXT_CHARS:
                    st.error("Please enter a brief text response before continuing.")
                else:
                    ss.trial_submitted = True
                    extra = {
                        "rating_angry": "", "rating_happy": "", "rating_sad": "", "rating_scared": "",
                        "rating_surprised": "", "rating_neutral": "", "rating_disgusted": "", "rating_contempt": "",
                        "result_estimate": result_estimate,
                        "free_text": text.strip(),
                    }
                    st.success("Response saved.")
                    record_and_next(extra)

# ===== DONE =====
elif st.session_state.phase == "done":
    st.success("All done — thank you for participating!")
    st.write("Your responses have been recorded.")
    st.info("You may now close this window.")
