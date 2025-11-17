# app.py — Multimode survey (clean main sheet + separate meta sheet)
# Root-folder media, 2-second exposure, 4 modes.

import time
import uuid
import random
import base64
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import streamlit as st

# ======================== CONFIG ========================
STUDY_ID = "two_second_multimode_nomf_v3"

IMAGE_DIR = Path(".")
VIDEO_DIR = Path(".")

SHOW_SECONDS = 2.0
MAX_TRIALS = 30
MIN_TEXT_CHARS = 1

DEFAULT_MODE = "img_sliders"
ALL_MODES = ["img_sliders", "img_text", "vid_sliders", "vid_text"]

EMOTIONS = [
    "Angry", "Happy", "Sad", "Scared",
    "Surprised", "Neutral", "Disgusted", "Contempt",
]
RATING_MIN, RATING_MAX, RATING_DEFAULT = 0, 100, 0

# Load sheet URL if configured
try:
    SHEET_URL = st.secrets["google_sheets"]["sheet_url"]
except Exception:
    SHEET_URL = ""

st.set_page_config(page_title="2-Second Media Survey", layout="centered")


# ======================== Media Display Helpers ========================
def render_image_responsive(path: str, max_vw=80, max_vh=70):
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = Path(path).suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"

    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;">
          <img src="data:{mime};base64,{b64}"
               style="max-width:{max_vw}vw;max-height:{max_vh}vh;
                      width:auto;height:auto;border-radius:12px;">
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_video_autoplay(path: Path, max_vw=80, max_vh=70):
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    mime = "video/mp4"

    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;">
          <video autoplay muted playsinline
                 style="max-width:{max_vw}vw;max-height:{max_vh}vh;border-radius:12px;">
            <source src="data:{mime};base64,{b64}" type="{mime}">
          </video>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ======================== SIDEBAR DEBUG ========================
with st.sidebar:
    st.header("Debug Info (not shown to participants)")
    st.write("Sheet URL set:", bool(SHEET_URL))
    try:
        st.write("Service account:", st.secrets["google_service_account"]["client_email"])
    except Exception:
        st.write("Service account: (not loaded)")

    st.write("---")
    for key in ["study_id", "mode", "participant_id", "name", "age",
                "gender", "nationality", "order", "idx", "total_trials"]:
        st.write(f"{key}:", st.session_state.get(key))


# ======================== Utility ========================
def get_mode_from_query():
    try:
        params = st.query_params
        raw = params.get("mode", [DEFAULT_MODE])
        mode = raw[0] if isinstance(raw, list) else raw
    except Exception:
        params = st.experimental_get_query_params()
        mode = params.get("mode", [DEFAULT_MODE])[0]
    return mode if mode in ALL_MODES else DEFAULT_MODE


def generate_participant_id():
    return uuid.uuid4().hex[:8].upper()


def randomize_order(n):
    order = list(range(n))
    random.shuffle(order)
    return order


def ratings_to_dict(sliders):
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


def load_media_files(dirpath, exts):
    if not dirpath.exists():
        return []
    return [
        p for p in sorted(dirpath.iterdir())
        if p.is_file() and p.suffix.lower() in exts
    ]


# ======================== Sheets I/O ========================
def get_sheets():
    """Return (responses_ws, meta_ws) or (None, None) if no Sheets configured."""
    if not SHEET_URL:
        return None, None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        sa_info = st.secrets["google_service_account"]
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(SHEET_URL)

        # --- main sheet: "responses" ---
        try:
            responses_ws = sh.worksheet("responses")
        except gspread.WorksheetNotFound:
            responses_ws = sh.add_worksheet("responses", rows=5000, cols=40)
            responses_ws.append_row([
                "study_id", "participant_id", "consented", "consent_timestamp_iso",
                "name", "age", "gender", "nationality",
                "trial_index", "order_index", "media_file",
                "rating_angry", "rating_happy", "rating_sad", "rating_scared",
                "rating_surprised", "rating_neutral", "rating_disgusted",
                "rating_contempt",
                "result_estimate", "free_text",
                "response_timestamp_iso"
            ])

        # --- meta sheet ---
        try:
            meta_ws = sh.worksheet("meta")
        except gspread.WorksheetNotFound:
            meta_ws = sh.add_worksheet("meta", rows=5000, cols=40)
            meta_ws.append_row([
                "study_id", "participant_id", "mode",
                "total_trials", "order_sequence",
                "n_completed",
                "media_kind", "media_file",
                "trial_index", "order_index",
                "response_timestamp_iso"
            ])

        return responses_ws, meta_ws

    except Exception as e:
        st.error(f"Sheets error: {e}")
        return None, None


def save_main_row(ws, row: Dict[str, Any]):
    if ws is None:
        return
    ws.append_row([
        row["study_id"],
        row["participant_id"],
        row["consented"],
        row["consent_timestamp_iso"],
        row["name"],
        row["age"],
        row["gender"],
        row["nationality"],
        row["trial_index"],
        row["order_index"],
        row["media_file"],
        row["rating_angry"],
        row["rating_happy"],
        row["rating_sad"],
        row["rating_scared"],
        row["rating_surprised"],
        row["rating_neutral"],
        row["rating_disgusted"],
        row["rating_contempt"],
        row["result_estimate"],
        row["free_text"],
        row["response_timestamp_iso"],
    ], value_input_option="RAW")


def save_meta_row(meta_ws, row: Dict[str, Any]):
    if meta_ws is None:
        return
    meta_ws.append_row([
        row["study_id"], row["participant_id"], row["mode"],
        row["total_trials"], row["order_sequence"],
        row["n_completed"],
        row["media_kind"], row["media_file"],
        row["trial_index"], row["order_index"],
        row["response_timestamp_iso"]
    ], value_input_option="RAW")


# ======================== State Init ========================
def init_state(initial_mode):
    ss = st.session_state
    ss.setdefault("phase", "consent")
    ss.setdefault("study_id", STUDY_ID)
    ss.setdefault("mode", initial_mode)

    ss.setdefault("consented", False)
    ss.setdefault("consent_timestamp_iso", "")
    ss.setdefault("participant_id", "")
    ss.setdefault("name", "")
    ss.setdefault("age", 0)
    ss.setdefault("gender", "")
    ss.setdefault("nationality", "")

    ss.setdefault("media_list", [])
    ss.setdefault("order", [])
    ss.setdefault("idx", 0)
    ss.setdefault("total_trials", 0)
    ss.setdefault("order_sequence", "")
    ss.setdefault("show_started_at", None)

    ss.setdefault("current_trial", None)
    ss.setdefault("trial_submitted", False)

    ss.setdefault("responses_ws", None)
    ss.setdefault("meta_ws", None)


def advance(phase):
    st.session_state.phase = phase
    st.rerun()


# ======================== Main Recording ========================
def record_and_next(extra):
    ss = st.session_state
    mode = ss.mode
    total = ss.total_trials
    i = ss.idx
    media_idx = ss.order[i]
    media_path = ss.media_list[media_idx]

    timestamp = datetime.utcnow().isoformat() + "Z"

    # MAIN row
    main_row = {
        "study_id": ss.study_id,
        "participant_id": ss.participant_id,
        "consented": ss.consented,
        "consent_timestamp_iso": ss.consent_timestamp_iso,
        "name": ss.name,
        "age": ss.age,
        "gender": ss.gender,
        "nationality": ss.nationality,

        "trial_index": media_idx + 1,
        "order_index": i + 1,
        "media_file": media_path.name,

        **extra,

        "response_timestamp_iso": timestamp,
    }

    save_main_row(ss.responses_ws, main_row)

    # META row
    meta_row = {
        "study_id": ss.study_id,
        "participant_id": ss.participant_id,
        "mode": ss.mode,
        "total_trials": ss.total_trials,
        "order_sequence": ss.order_sequence,
        "n_completed": i + 1,
        "media_kind": "image" if mode.startswith("img") else "video",
        "media_file": media_path.name,
        "trial_index": media_idx + 1,
        "order_index": i + 1,
        "response_timestamp_iso": timestamp,
    }
    save_meta_row(ss.meta_ws, meta_row)

    # Progress
    ss.idx += 1
    ss.trial_submitted = False
    ss.show_started_at = None

    ss.phase = "done" if ss.idx >= total else "show"
    st.rerun()


# ======================== Run ========================
initial_mode = get_mode_from_query()
init_state(initial_mode)

# Connect Sheets once
if st.session_state.responses_ws is None and SHEET_URL:
    responses_ws, meta_ws = get_sheets()
    st.session_state.responses_ws = responses_ws
    st.session_state.meta_ws = meta_ws


# ===== CONSENT =====
if st.session_state.phase == "consent":
    st.title("Consent to Participate")

    if st.button("🔁 Reset"):
        st.session_state.clear()
        st.rerun()

    default_index = ALL_MODES.index(st.session_state.mode)
    selected_mode = st.selectbox("Select study mode:", ALL_MODES, index=default_index)
    st.session_state.mode = selected_mode

    st.write(f"This study presents { 'images' if selected_mode.startswith('img') else 'videos' } for 2 seconds. You have to guess what emotions are being displayed by the athlete in each of these images or videos, and also provide an estimation of the result of the match. You can select or write multiple emotions. ")

    if not st.session_state.participant_id:
        st.session_state.participant_id = generate_participant_id()

    agree = st.checkbox("I consent to participate")
    pid = st.text_input("Participant ID", value=st.session_state.participant_id)

    if st.button("Continue"):
        if not agree:
            st.error("You must consent to continue.")
        else:
            st.session_state.participant_id = pid.strip()
            st.session_state.consented = True
            st.session_state.consent_timestamp_iso = datetime.utcnow().isoformat() + "Z"
            advance("demographics")


# ===== DEMOGRAPHICS =====
elif st.session_state.phase == "demographics":
    st.title("Participant Information")

    with st.form("demo_form"):
        name = st.text_input("Full name")
        age = st.number_input("Age", min_value=1, step=1)
        gender = st.selectbox("Gender", ["", "Female", "Male", "Non-binary / Other", "Prefer not to say"])
        nationality = st.text_input("Nationality")

        if st.form_submit_button("Start"):
            if not name or not gender or not nationality:
                st.error("Fill all fields.")
            else:
                ss = st.session_state
                ss.name = name.strip()
                ss.age = int(age)
                ss.gender = gender.strip()
                ss.nationality = nationality.strip()

                # Load media
                if ss.mode.startswith("img"):
                    media_files = load_media_files(IMAGE_DIR, {".jpg", ".jpeg", ".png", ".webp"})
                else:
                    media_files = load_media_files(VIDEO_DIR, {".mp4", ".mov", ".m4v"})

                if not media_files:
                    st.error("No media files found.")
                    st.stop()

                full_order = randomize_order(len(media_files))
                n = min(len(media_files), MAX_TRIALS)
                selected = full_order[:n]

                ss.media_list = media_files
                ss.order = selected
                ss.total_trials = n
                ss.order_sequence = ",".join(str(x) for x in selected)
                ss.idx = 0
                ss.show_started_at = None

                advance("show")


# ===== SHOW (2s viewing) =====
elif st.session_state.phase == "show":
    ss = st.session_state
    mode = ss.mode
    i = ss.idx
    total = ss.total_trials

    media_idx = ss.order[i]
    path = ss.media_list[media_idx]

    if ss.show_started_at is None:
        ss.show_started_at = time.time()

    elapsed = time.time() - ss.show_started_at
    remaining = SHOW_SECONDS - elapsed

    st.subheader(f"Stimulus {i+1} of {total}")

    if mode.startswith("img"):
        render_image_responsive(str(path))
    else:
        render_video_autoplay(path)

    if remaining > 0:
        st.caption(f"Next screen in {remaining:.1f}s…")
        time.sleep(0.1)
        st.rerun()
    else:
        advance("rate")


# ===== RATE =====
elif st.session_state.phase == "rate":
    ss = st.session_state
    mode = ss.mode
    i = ss.idx
    total = ss.total_trials

    if ss.current_trial != i:
        ss.current_trial = i
        ss.trial_submitted = False

    st.subheader(f"Response {i+1} of {total}")

    # Slider modes
    if "sliders" in mode:
        with st.form(f"rate_form_{i}"):
            sliders = {emo: st.slider(emo, 0, 100, 0) for emo in EMOTIONS}
            result = st.radio("Did the athlete win or lose?", ["Won", "Lost"], index=None)

            if st.form_submit_button("Submit"):
                if ss.trial_submitted:
                    st.warning("Already submitted.")
                elif result is None:
                    st.error("Select Win/Lost.")
                else:
                    ss.trial_submitted = True
                    extra = {
                        **ratings_to_dict(sliders),
                        "result_estimate": result,
                        "free_text": "",
                    }
                    record_and_next(extra)

    # Text modes
    else:
        with st.form(f"text_form_{i}"):
            result = st.radio("Did the athlete win or lose?", ["Won", "Lost"], index=None)
            text = st.text_area("Describe the emotions you saw. If you are typing text, you can use words of any language you prefer:")

            if st.form_submit_button("Submit"):
                if ss.trial_submitted:
                    st.warning("Already submitted.")
                elif result is None:
                    st.error("Select Win/Loss.")
                elif len(text.strip()) < MIN_TEXT_CHARS:
                    st.error("Enter a text response.")
                else:
                    ss.trial_submitted = True
                    extra = {
                        **{emo.lower(): "" for emo in [
                            "rating_angry","rating_happy","rating_sad","rating_scared",
                            "rating_surprised","rating_neutral","rating_disgusted","rating_contempt"
                        ]},
                        "result_estimate": result,
                        "free_text": text.strip(),
                    }
                    record_and_next(extra)


# ===== DONE =====
elif st.session_state.phase == "done":
    st.success("Done! Thank you.")
    st.write("Your responses have been saved.")
