"""
core/gemini_uploader.py
-----------------------
Handles uploading video files to the Gemini Files API.
Stores the returned file ID/URI in the project database for reuse.

FIX: Unicode/non-ASCII filenames (e.g. fullwidth pipe, CJK characters)
     cause an ASCII codec error in the Gemini SDK HTTP headers.
     We create a sanitized ASCII copy for upload only, then delete it.
"""

import os
import re
import shutil
import time
from pathlib import Path

from google import genai
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from db import database as db

console = Console()


def get_gemini_client() -> genai.Client:
    """Create and return a configured Gemini client."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not found. Set it in your .env file or as an environment variable."
        )
    return genai.Client(api_key=api_key)


def _safe_ascii_path(video_path: Path):
    """
    Ensure the file has an ASCII-safe name for the Gemini SDK.

    The SDK transmits the filename in HTTP headers which must be ASCII.
    Non-ASCII chars (fullwidth pipe, CJK, emoji, smart quotes, etc.)
    cause:  'ascii' codec can't encode character ...

    Returns (upload_path, temp_copy_or_None).
    Caller MUST delete temp_copy after upload completes.
    """
    suffix = video_path.suffix.lower()

    # Drop every non-ASCII byte
    ascii_stem = video_path.stem.encode("ascii", errors="ignore").decode("ascii")
    # Replace unsafe chars with underscore, collapse runs
    ascii_stem = re.sub(r"[^\w\s.\-()]", "_", ascii_stem)
    ascii_stem = re.sub(r"_+", "_", ascii_stem).strip("_. ")
    if not ascii_stem:
        ascii_stem = "video"
    ascii_stem = ascii_stem[:80]          # cap length

    safe_name = ascii_stem + suffix

    if safe_name == video_path.name:
        return video_path, None           # already safe

    temp_copy = video_path.parent / safe_name
    if not temp_copy.exists():
        shutil.copy2(video_path, temp_copy)
    console.print(f"[dim]Non-ASCII filename detected. Uploading as: {safe_name}[/dim]")
    return temp_copy, temp_copy


def upload_video_to_gemini(project_id: str, video_path: str) -> dict:
    """
    Upload a local video file to the Gemini Files API.
    Returns updated project dict with gemini_file_id and gemini_file_uri set.
    """
    video_path = Path(video_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    supported = {".mp4", ".mpeg", ".mov", ".avi", ".flv", ".mpg", ".webm", ".wmv", ".3gpp"}
    if video_path.suffix.lower() not in supported:
        raise ValueError(f"Unsupported format: {video_path.suffix}")

    size_mb = video_path.stat().st_size / (1024 * 1024)
    console.print(f"[cyan]File:[/cyan] {video_path.name} ({size_mb:.1f} MB)")

    upload_path, temp_copy = _safe_ascii_path(video_path)
    client = get_gemini_client()
    uploaded_file = None

    try:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
            task = p.add_task("Uploading to Gemini Files API...", total=None)

            uploaded_file = client.files.upload(file=str(upload_path))

            p.update(task, description="Waiting for Gemini to process video...")
            max_wait, elapsed, interval = 300, 0, 5

            while elapsed < max_wait:
                info = client.files.get(name=uploaded_file.name)
                state = str(info.state).upper()
                if "ACTIVE" in state:
                    p.update(task, description="Video processing complete!")
                    break
                elif "FAILED" in state:
                    raise RuntimeError(f"Gemini file processing failed: {info}")
                time.sleep(interval)
                elapsed += interval
                p.update(task, description=f"Processing... ({elapsed}s elapsed)")
            else:
                raise TimeoutError("Gemini file processing timed out after 5 minutes.")

    finally:
        if temp_copy and temp_copy.exists():
            try:
                temp_copy.unlink()
            except Exception:
                pass

    updated = db.update_project(project_id, {
        "gemini_file_id": uploaded_file.name,
        "gemini_file_uri": uploaded_file.uri if hasattr(uploaded_file, "uri") else None,
        "video_path": str(video_path),
        "stage": "uploaded",
    })

    console.print(f"[green]Uploaded! File ID:[/green] [bold]{uploaded_file.name}[/bold]")
    return updated


def get_or_reuse_gemini_file(project_id: str, video_path: str = None):
    """Return (file_name, file_uri), reusing existing upload if still ACTIVE."""
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    if project.get("gemini_file_id"):
        try:
            client = get_gemini_client()
            info = client.files.get(name=project["gemini_file_id"])
            if "ACTIVE" in str(info.state).upper():
                console.print(f"[dim]Reusing Gemini file: {project['gemini_file_id']}[/dim]")
                return project["gemini_file_id"], project.get("gemini_file_uri")
        except Exception:
            console.print("[yellow]Previous Gemini file unavailable. Re-uploading...[/yellow]")

    if not video_path:
        video_path = project.get("video_path")
    if not video_path:
        raise ValueError("No video path provided and no previous upload found.")

    updated = upload_video_to_gemini(project_id, video_path)
    return updated["gemini_file_id"], updated.get("gemini_file_uri")


def delete_gemini_file(file_name: str):
    """Delete a file from Gemini Files API."""
    try:
        client = get_gemini_client()
        client.files.delete(name=file_name)
        console.print(f"[dim]Deleted Gemini file: {file_name}[/dim]")
    except Exception as e:
        console.print(f"[yellow]Could not delete {file_name}: {e}[/yellow]")


def list_gemini_files():
    """List all files in Gemini Files API."""
    client = get_gemini_client()
    console.print("[bold]Files in Gemini Files API:[/bold]")
    count = 0
    for f in client.files.list():
        display = f.display_name if hasattr(f, "display_name") else "N/A"
        console.print(f"  [cyan]{f.name}[/cyan] - {display}")
        count += 1
    if count == 0:
        console.print("  [dim](no files)[/dim]")
