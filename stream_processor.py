import os
import sys
import json
import base64
import subprocess
import re
import gdrive_helper
import telegram_helper

TASK_ID = os.environ.get("TASK_ID", "task_stream_001")
TASK_PAYLOAD = os.environ.get("TASK_PAYLOAD", "")
DRIVE_ROOT = os.environ.get("GDRIVE_FOLDER_ID", "")

def parse_payload():
    if not TASK_PAYLOAD:
        print(f"ℹ️ No direct payload passed, checking task ID: {TASK_ID}")
        return {"task_id": TASK_ID, "title": TASK_ID, "m3u8_url": "", "chat_id": "", "post_id": ""}
    try:
        decoded = base64.b64decode(TASK_PAYLOAD).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        print(f"⚠️ Payload parsing fallback: {e}")
        return {"task_id": TASK_ID, "title": TASK_ID, "m3u8_url": "", "chat_id": "", "post_id": ""}

def download_and_merge_m3u8(m3u8_url, output_mp4):
    print(f"📥 Downloading stream from M3U8...")
    cmd = [
        "ffmpeg", "-y",
        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n",
        "-i", m3u8_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        output_mp4
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"❌ FFmpeg error: {res.stderr[-500:]}")
        return False
    return os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 0

def split_video_to_parts(input_mp4, output_dir, max_size_mb=48):
    os.makedirs(output_dir, exist_ok=True)
    file_size_mb = os.path.getsize(input_mp4) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        target = os.path.join(output_dir, "part_001.mp4")
        subprocess.run(["cp", input_mp4, target])
        return [target]

    # Get duration
    dur_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_mp4]
    dur_res = subprocess.run(dur_cmd, capture_output=True, text=True)
    duration = float(dur_res.stdout.strip() or "0")
    
    num_parts = int(file_size_mb // (max_size_mb - 2)) + 1
    part_duration = duration / num_parts
    
    parts = []
    for i in range(num_parts):
        start_time = i * part_duration
        out_part = os.path.join(output_dir, f"part_{i+1:03d}.mp4")
        # Check resumability
        if os.path.exists(out_part) and os.path.getsize(out_part) > 1024:
            parts.append(out_part)
            continue
            
        split_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", input_mp4,
            "-t", str(part_duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            out_part
        ]
        subprocess.run(split_cmd, capture_output=True)
        if os.path.exists(out_part):
            parts.append(out_part)
            
    return parts

def main():
    print(f"🎬 Starting Actress Stream Processor for: {TASK_ID}")
    data = parse_payload()
    title = data.get("title", TASK_ID)
    m3u8_url = data.get("m3u8_url", "")
    chat_id = data.get("chat_id", "")
    post_id = data.get("post_id", "")

    if not m3u8_url:
        print("⚠️ No stream URL provided. Exiting gracefully.")
        return

    work_dir = "./temp_downloads"
    os.makedirs(work_dir, exist_ok=True)
    master_mp4 = os.path.join(work_dir, f"{TASK_ID}_full.mp4")

    # 1. Download
    if not download_and_merge_m3u8(m3u8_url, master_mp4):
        print("❌ Download failed.")
        return

    # 2. Upload Master to GDrive
    print("☁️ Uploading Master MP4 to Google Drive...")
    try:
        drive_link = gdrive_helper.upload_file_to_drive(
            master_mp4,
            f"{title}.mp4",
            DRIVE_ROOT,
            mime_type="video/mp4"
        )
        print(f"✅ GDrive Upload Complete: {drive_link}")
    except Exception as e:
        print(f"⚠️ GDrive Upload error: {e}")
        drive_link = ""

    # 3. Split parts & send to TG comments
    if chat_id and post_id:
        print("✂️ Splitting into <= 48MB parts for Telegram Comments...")
        parts_dir = os.path.join(work_dir, "parts")
        parts = split_video_to_parts(master_mp4, parts_dir)
        
        for idx, part in enumerate(parts):
            caption = f"🎬 <b>Part {idx+1}/{len(parts)}</b> | {title}"
            if idx == 0 and drive_link:
                caption += f"\n💾 <a href='{drive_link}'>Full Master Lossless</a>"
            telegram_helper.send_video(
                chat_id=chat_id,
                video_path=part,
                caption=caption,
                reply_to_message_id=int(post_id)
            )
            print(f"  📤 Sent part {idx+1}/{len(parts)} to comments of post {post_id}")

    print("🎉 Stream processing completed successfully.")

if __name__ == "__main__":
    main()
