# app.py — Multimode survey (no manifest, root media)
# Uses all image/video files in the repo root with 2s exposure.
# Modes via URL: img_sliders (default), img_text, vid_sliders, vid_text.
# Order is fully random each time a participant starts.

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
# Currently use repo root as media directory, since your files are not in folders.
# If you later move them into images/ and videos/, change these to Path("images") / Path("videos").
IMAGE_DIR = Path(".")   # or Path("images")
VIDEO_DIR = Path(".")   # or Path("videos")

SHOW_SECONDS = 2.0

# Modes: img_sliders (default) | img_text | vid_sliders | vid_text
DEFAULT_MODE = "img_sliders"

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
    st.write("mode:", st.session_state.get("mode"))
    st.write("participant_id:", st.session_state.get("participant_id"))
    st.write("name:", st.session_state.get("name"))
    st.write("age:", st.session_state.get("age"))
    st.write("gender:", st.session_state.get("gender"))
    st.write("nationality:", st.session_state.get("nationality"))
    st.write("order:", st.session_state.get("order"))  # helpful to see permutations while testing

# -------------------- Utility --------------------
def get_mode() -> str:
    try:
        params = st.query_params  # new Streamlit API
        raw = params.get("mode", [DEFAULT_MODE])
        mode = raw[0] if isinstance(raw, list) else raw
    except Exception:
        params = st.experimental_get_query_params()
        mode = params.get("mode", [DEFAULT_MODE])[0]
    valid = {"img_sliders", "img_text", "vid_sliders", "vid_text"}
    return mode if mode in valid else DEFAULT_MODE

def generate_participant_id() -> str:
    return uuid.uuid4().hex[:8].upper()

def randomize_order(n: int) -> List[int]:
    """
    Fully random order each time this is called.
    No dependence on participant_id.
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
            ws = sh.add_worksheet(title="responses", rows=4000, cols=40)
            ws.append_row([
                "study_id", "mode", "participant_id", "consented", "consent_timestamp_iso",
                "name", "age", "gender", "nationality",
                "trial_index", "order_index",
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
        st.warning("Sheets: no worksheet; not writing.")
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
        st.toast("Saved to Google Sheet ✅", icon="✅")
    except Exception as e:
        st.error(f"Failed to append to Google Sheets: {e}")

# -------------------- App state & flow --------------------
def init_state(mode: str):
    ss = st.session_state
    ss.setdefault("phase", "consent")
    ss.setdefault("study_id", "two_second_multimode_nomf")
    ss.setdefault("mode", mode)

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
    ss.setdefault("idx", 0)
    ss.setdefault("order", [])
    ss.setdefault("show_started_at", None)

    # Responses
    ss.setdefault("responses", [])

    # Sheets
    ss.setdefault("ws", None)

def advance(phase: str):
    st.session_state.phase = phase
    st.rerun()

def record_and_next(extra: Dict[str, Any]):
    ss = st.session_state
    total = len(ss.media_list)
    i = ss.idx
    order_index = i + 1
    media_idx = ss.order[i]
    media_path = ss.media_list[media_idx]

    base_row = {
        "study_id": ss.study_id,
        "mode": ss.mode,
        "participant_id": ss.participant_id,
        "consented": ss.consented,
        "consent_timestamp_iso": ss.consent_timestamp_iso,
        "name": ss.name,
        "age": ss.age,
        "gender": ss.gender,
        "nationality": ss.nationality,
        "trial_index": media_idx + 1,
        "order_index": order_index,
        "media_kind": "image" if ss.mode.startswith("img") else "video",
        "media_file": media_path.name,
        **extra,
        "response_timestamp_iso": datetime.utcnow().isoformat() + "Z",
    }

    ss.responses.append(base_row)
    append_row_to_sheet(ss.ws, base_row)

    ss.idx += 1
    ss.show_started_at = None
    ss.phase = "done" if ss.idx >= total else "show"
    st.rerun()

# -------------------- Run --------------------
mode = get_mode()
init_state(mode)

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

    st.write(f"""
This study shows a series of **{'images' if mode.startswith('img') else 'videos'}** for **{SHOW_SECONDS:.0f} seconds** each.
After each stimulus, you will {'rate emotions (0–100) and estimate whether the athlete won or lost' if 'sliders' in mode else 'describe the emotions you saw and estimate whether the athlete won or lost'}.
Participation is voluntary; you may stop at any time.
    """)

    if not st.session_state.participant_id:
        st.session_state.participant_id = generate_participant_id()
    agreed = st.checkbox("I consent to participate.")
    st.caption("A unique participant ID has been generated. You may override it if needed.")
    st.text_input("Participant ID", key="participant_id")

    st.caption("Mode: " + mode + "  •  Change with ?mode=img_sliders | img_text | vid_sliders | vid_text")

    if st.button("Continue"):
        if not agreed:
            st.error("You must consent to proceed.")
        else:
            st.session_state.consented = True
            st.session_state.consent_timestamp_iso = datetime.utcnow().isoformat() + "Z"
            advance("demographics")

# ===== DEMOGRAPHICS =====
elif st.session_state.phase == "demographics":
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

                st.session_state.media_list = media_files
                n_media = len(media_files)

                # Fully random order each time demographics is submitted
                st.session_state.order = randomize_order(n_media)

                st.session_state.idx = 0
                st.session_state.show_started_at = None
                advance("show")
            else:
                st.error("Please complete all demographic fields before starting.")

# ===== SHOW (stable 2s exposure) =====
elif st.session_state.phase == "show":
    media_list = st.session_state.media_list
    total_media = len(media_list)
    if total_media == 0:
        st.error("No media selected. Please restart the study.")
        st.stop()

    i = st.session_state.idx
    media_idx = st.session_state.order[i]
    path = media_list[media_idx]

    if st.session_state.show_started_at is None:
        st.session_state.show_started_at = time.time()

    elapsed = time.time() - st.session_state.show_started_at
    remaining = SHOW_SECONDS - elapsed

    st.subheader(f"Stimulus {i+1} of {total_media}")

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
    media_list = st.session_state.media_list
    total_media = len(media_list)
    i = st.session_state.idx
    pos_1based = i + 1

    st.subheader(f"Respond to the last stimulus ({pos_1based} of {total_media})")

    # Slider modes: emotions sliders + result estimate (Won/Lost)
    if "sliders" in st.session_state.mode:
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
                if result_estimate is None:
                    st.error("Please select Win or Lose before continuing.")
                else:
                    extra = {
                        **ratings_to_dict(sliders),
                        "result_estimate": result_estimate,
                        "free_text": "",
                    }
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
                if result_estimate is None:
                    st.error("Please select Win or Lose before continuing.")
                else:
                    extra = {
                        "rating_angry": "", "rating_happy": "", "rating_sad": "", "rating_scared": "",
                        "rating_surprised": "", "rating_neutral": "", "rating_disgusted": "", "rating_contempt": "",
                        "result_estimate": result_estimate,
                        "free_text": text.strip(),
                    }
                    record_and_next(extra)

# ===== DONE =====
elif st.session_state.phase == "done":
    st.success("All done — thank you for participating!")
    st.write("Your responses have been recorded.")
    st.info("You may now close this window.")
