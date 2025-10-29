import os, re, glob
from itertools import groupby

import streamlit as st
from yt_dlp import YoutubeDL
import webvtt

# --- Simple password gate (uses Streamlit Secrets: APP_PASSWORD) ---
def check_password() -> bool:
    """Return True if the user entered the correct password."""
    if "auth_ok" in st.session_state and st.session_state.auth_ok:
        return True

    pw = st.text_input("Password", type="password", placeholder="Enter app password")
    if st.button("Unlock"):
        required = st.secrets.get("APP_PASSWORD", None)
        if required is None:
            st.error("Server is not configured yet. Admin must set APP_PASSWORD in Secrets.")
            return False
        if pw == required:
            st.session_state.auth_ok = True
            st.experimental_rerun()
        else:
            st.error("Incorrect password.")
    return False

# ---------- CONFIG ----------
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "transcripts")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------- CORE HELPERS ----------
def download_vtt(video_id_or_url: str) -> str:
    """
    Uses yt-dlp to fetch English subtitles (manual or auto) as VTT into current run dir.
    Returns the path to the VTT file.
    """
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,      # manual subs if available
        "writeautomaticsub": True,   # fallback to auto subs
        "subtitleslangs": ["en"],
        "subtitlesformat": "vtt",    # WebVTT
        "outtmpl": "%(id)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_id_or_url, download=True)
        vid = info.get("id")

    # Find the VTT written by yt-dlp
    candidates = sorted(glob.glob(f"{vid}*.vtt"))
    if not candidates:
        raise FileNotFoundError("No .vtt subtitle files were downloaded for this video.")
    # Prefer English variants
    for c in candidates:
        name = os.path.basename(c).lower()
        if ".en" in name:
            return c
    return candidates[0]

def vtt_to_lines(vtt_path: str, include_timestamps: bool) -> list[str]:
    """
    Read VTT and convert to list of transcript lines (optionally with [HH:MM:SS]).
    """
    lines = []
    for cue in webvtt.read(vtt_path):
        text = cue.text.strip().replace("\n", " ")
        if not text:
            continue
        if include_timestamps:
            ts = cue.start.split(".")[0]  # "HH:MM:SS.mmm" -> "HH:MM:SS"
            lines.append(f"[{ts}] {text}")
        else:
            lines.append(text)
    if not lines:
        raise ValueError("Subtitles file was empty after parsing.")
    return lines

def clean_lines(lines: list[str]) -> list[str]:
    """
    Remove exact adjacent duplicates and collapse overlapping halves by keeping the longer line.
    """
    exact = [k for k, _ in groupby([ln.strip() for ln in lines if ln.strip()])]
    final = []
    for ln in exact:
        if not final:
            final.append(ln); continue
        prev = final[-1]
        if ln == prev:
            continue
        if ln in prev:
            continue            # current is shorter fragment of previous
        if prev in ln:
            final[-1] = ln      # current is longer; replace previous
            continue
        final.append(ln)
    return final

def strip_timestamps(line: str) -> str:
    return re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line).strip()

def save_transcript(video_url_or_id: str, base_name: str, include_timestamps: bool) -> tuple[str, str, str]:
    """
    End-to-end:
      - download VTT
      - convert to lines (with or without timestamps)
      - clean duplicates/overlaps
      - save:
          <OUTPUT_DIR>/<base_name>.txt
          <OUTPUT_DIR>/<base_name>_paragraphs.txt
          <OUTPUT_DIR>/<vtt file> (moved here for reference)
    Returns (txt_path, paragraphs_path, vtt_path).
    """
    base_name = os.path.splitext(os.path.basename(base_name))[0] or "transcript"

    vtt_path = download_vtt(video_url_or_id)
    lines = vtt_to_lines(vtt_path, include_timestamps)
    cleaned = clean_lines(lines)

    # Write TXT (line-by-line)
    txt_path = os.path.join(OUTPUT_DIR, f"{base_name}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned))

    # Paragraph version (always without timestamps)
    no_ts = [strip_timestamps(ln) for ln in cleaned if ln.strip()]
    para_path = os.path.join(OUTPUT_DIR, f"{base_name}_paragraphs.txt")
    with open(para_path, "w", encoding="utf-8") as f:
        f.write(" ".join(no_ts))

    # Move VTT into OUTPUT_DIR
    vtt_out = os.path.join(OUTPUT_DIR, os.path.basename(vtt_path))
    try:
        if os.path.abspath(vtt_path) != os.path.abspath(vtt_out):
            import shutil
            shutil.move(vtt_path, vtt_out)
    except Exception:
        vtt_out = os.path.abspath(vtt_path)

    return os.path.abspath(txt_path), os.path.abspath(para_path), os.path.abspath(vtt_out)

# ---------- UI ----------
st.set_page_config(page_title="Snypso Transcript Extractor", page_icon="📝", layout="centered")

# Require login before showing the app
if not check_password():
    st.stop()

st.title("Snypso Transcript Extractor")
st.caption(f"Output folder: {OUTPUT_DIR}")

url = st.text_input("YouTube URL or 11-char Video ID", placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX")
base = st.text_input("Base filename (no extension)", value="transcript")
timestamps = st.checkbox("Include [HH:MM:SS] timestamps", value=False)

if st.button("Download transcript", type="primary"):
    if not url.strip():
        st.error("Please paste a YouTube URL or video ID.")
    else:
        try:
            txt_path, para_path, vtt_path = save_transcript(url.strip(), base.strip(), timestamps)
            st.success("Done!")
            st.write("**Saved files:**")
            st.code(txt_path)
            st.code(para_path)
            st.code(vtt_path)

            # Preview first ~12 lines
            st.write("**Preview (first ~12 lines):**")
            with open(txt_path, "r", encoding="utf-8") as f:
                preview = "".join([next(f, "") for _ in range(12)])
            st.text(preview)

            # Download buttons
            with open(txt_path, "rb") as f:
                st.download_button("Download line-by-line .txt", f.read(), file_name=os.path.basename(txt_path))
            with open(para_path, "rb") as f:
                st.download_button("Download paragraphs .txt", f.read(), file_name=os.path.basename(para_path))

        except Exception as e:
            st.error(f"{type(e).__name__}: {e}")

# ---------- Batch mode ----------
st.header("Batch mode")
st.caption("Paste one URL/ID per line. Outputs will use the video ID as the base filename.")
batch_input = st.text_area("URLs/IDs (one per line)", height=160, placeholder="https://www.youtube.com/watch?v=XXXXXXXXXXX")
batch_ts = st.checkbox("Include timestamps in batch", value=False, key="batch_ts")

if st.button("Run batch"):
    entries = [ln.strip() for ln in batch_input.splitlines() if ln.strip()]
    if not entries:
        st.error("Please paste at least one URL/ID.")
    else:
        results = []
        for item in entries:
            # Heuristic base name = last 11 chars (YouTube ID)
            vid = item[-11:]
            try:
                txt_path, para_path, vtt_path = save_transcript(item, base_name=vid, include_timestamps=batch_ts)
                results.append((item, "OK", txt_path, para_path))
            except Exception as e:
                results.append((item, f"ERROR: {e}", "", ""))
        st.write("**Results:**")
        for row in results:
            st.write(row)



