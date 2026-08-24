import os
import sys
import time
import json
import base64
import subprocess
import re
import math
import shutil
import logging
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
except ImportError:
    cloudscraper = None

import gdrive_helper
import telegram_helper

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TASK_ID = os.environ.get("TASK_ID", "task_stream_001")
TASK_PAYLOAD = os.environ.get("TASK_PAYLOAD", "")
DRIVE_ROOT = os.environ.get("GDRIVE_FOLDER_ID", "1AD83FFKXHHc-0NGK4boRv1jCcbUCRJn7")
DEFAULT_OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "hothihuong113@gmail.com")
MAX_CHUNK_BYTES = 45 * 1024 * 1024  # 45 MB per video part (Strictly <= 50MB for Telegram API)

CHANNEL_ID = os.environ.get("TARGET_CHANNEL_ID", "-1002244827586")
DISCUSS_CHAT_ID = os.environ.get("DISCUSS_CHAT_ID", "-1002087114535")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8',
}

def clean_filename(name):
    if not name:
        return "video"
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def parse_payload():
    """
    Parses base64 JSON payload or environment variables.
    """
    data = {
        "task_id": TASK_ID,
        "title": TASK_ID,
        "code": "",
        "url": "",
        "m3u8_url": "",
        "chat_id": os.environ.get("CHAT_ID", ""),
        "post_id": os.environ.get("POST_ID", ""),
        "folder_id": DRIVE_ROOT,
        "owner_email": DEFAULT_OWNER_EMAIL,
        "episodes": []
    }

    if TASK_PAYLOAD:
        try:
            payload_str = TASK_PAYLOAD.strip()
            missing_padding = len(payload_str) % 4
            if missing_padding:
                payload_str += '=' * (4 - missing_padding)
            try:
                decoded = base64.b64decode(payload_str).decode("utf-8")
                parsed = json.loads(decoded)
            except Exception:
                parsed = json.loads(TASK_PAYLOAD)

            data.update(parsed)
        except Exception as e:
            logger.warning(f"⚠️ Payload parsing fallback: {e}")

    if not data.get("url"):
        data["url"] = data.get("m3u8_url") or data.get("page_url") or data.get("video_url") or data.get("embed_url") or os.environ.get("STREAM_URL", "")
    if not data.get("chat_id"):
        data["chat_id"] = data.get("channel_id") or data.get("comment_chat_id") or os.environ.get("CHAT_ID", "")
    if not data.get("post_id"):
        data["post_id"] = data.get("message_id") or data.get("reply_to_message_id") or data.get("comment_reply_id") or os.environ.get("POST_ID", "")
    if not data.get("folder_id"):
        data["folder_id"] = DRIVE_ROOT

    return data

def is_123av_url(url):
    if not url:
        return False
    u_lower = url.lower()
    return any(d in u_lower for d in ["123av", "missav", "javplayer", "jav"])

def fetch_123av_page(url):
    """
    Fetches HTML from 123AV with automatic mirror domain fallback.
    """
    parsed = urlparse(url)
    path = parsed.path or "/en"
    if not path.startswith("/"):
        path = "/" + path

    code_match = re.search(r'/([a-zA-Z0-9]+-[a-zA-Z0-9]+)', path, re.I)
    canonical_path = f"/en/v/{code_match.group(1).lower()}" if code_match else None

    urls_to_try = []
    if canonical_path:
        for mirror in ['123av.top', '123av.me', '123av.org', '123av.com']:
            urls_to_try.append(f"https://{mirror}{canonical_path}")

    for mirror in ['123av.top', '123av.me', '123av.org', '123av.com']:
        m_url = f"https://{mirror}{path}"
        if m_url not in urls_to_try:
            urls_to_try.append(m_url)

    if url not in urls_to_try:
        urls_to_try.append(url)

    for target_url in urls_to_try:
        if cloudscraper:
            try:
                scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "desktop": True})
                r = scraper.get(target_url, headers=HEADERS, timeout=15)
                if r.status_code == 200 and ("x-data" in r.text or "player(" in r.text or "<html" in r.text.lower()):
                    return r.text, target_url
            except Exception:
                pass

        try:
            r = requests.get(target_url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and ("x-data" in r.text or "player(" in r.text or "<html" in r.text.lower()):
                return r.text, target_url
        except Exception:
            pass

    return None, url

def scrape_123av_details(video_url):
    """
    Scrapes video metadata, title, code, cover image and episode stream URLs from 123AV.
    """
    html, final_url = fetch_123av_page(video_url)
    if not html:
        return {"error": f"Failed to fetch 123AV page at {video_url}"}

    try:
        soup = BeautifulSoup(html, "html.parser")
        t_elem = soup.find("h1") or soup.find("title")
        title = t_elem.get_text(strip=True) if t_elem else "123AV Video"
        title = re.sub(r'\s+', ' ', title).strip()

        meta_dict = {}
        for row in soup.find_all("div", class_=re.compile(r'info-row', re.I)):
            row_text = row.get_text(" ", strip=True)
            for prefix in ['Code', 'Type', 'Release date', 'Cast', 'Maker', 'Series', 'Genres', 'Tags']:
                if row_text.lower().startswith(prefix.lower()):
                    val = row_text[len(prefix):].strip()
                    a_tags = row.find_all('a')
                    if a_tags and prefix in ['Cast', 'Maker', 'Series', 'Genres', 'Tags']:
                        val = ', '.join([a.get_text(strip=True) for a in a_tags])
                    meta_dict[prefix] = val

        code = meta_dict.get("Code", "")
        if not code and "—" in title:
            code = title.split("—")[0].strip()
        elif not code and "-" in title:
            m_c = re.search(r'([A-Z0-9]+-[A-Z0-9]+)', title, re.I)
            if m_c:
                code = m_c.group(1).upper()

        cover_url = ""
        player_div = soup.find("div", class_=re.compile(r'player', re.I))
        if player_div and player_div.has_attr("style"):
            m_cov = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', player_div["style"])
            if m_cov:
                cover_url = m_cov.group(1).replace("/s500/", "/")

        if not cover_url:
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("src") or ""
                if "cover" in src.lower() or "img" in src.lower():
                    cover_url = src.replace("/s500/", "/")
                    break

        episodes = []
        main_player = soup.find("div", attrs={"x-data": re.compile(r'player\(')})
        if main_player:
            xdata = main_player["x-data"]
            m_json = re.search(r'player\(\s*JSON\.parse\(\'([^\']+)\'\)', xdata)
            if m_json:
                raw_json = m_json.group(1)
                try:
                    decoded = bytes(raw_json, "utf-8").decode("unicode_escape")
                    eps_data = json.loads(decoded)
                    for ep in eps_data:
                        raw_ep_url = ep.get("url", "")
                        clean_ep_url = raw_ep_url.replace(r"\/", "/").replace("\\", "")
                        episodes.append({
                            "number": ep.get("number", len(episodes) + 1),
                            "name": ep.get("name", str(len(episodes) + 1)),
                            "url": clean_ep_url
                        })
                except Exception as je:
                    logger.warning(f"Error decoding episodes JSON: {je}")

        if not episodes:
            iframe = soup.find("iframe", src=re.compile(r'javplayer|player|embed', re.I))
            if iframe:
                episodes.append({
                    "number": 1,
                    "name": "1",
                    "url": iframe["src"]
                })

        return {
            "title": title,
            "code": code,
            "url": final_url,
            "cover_url": cover_url,
            "metadata": meta_dict,
            "episodes": episodes,
            "total_episodes": len(episodes)
        }
    except Exception as e:
        logger.error(f"Error scraping 123av details: {e}")
        return {"error": str(e)}

def update_gsheet_row(row_index, title=None, post_id=None, drive_link=None, status="Completed", ep_count=1, movie_code="", gdrive_files_count=None):
    """
    Updates Google Sheet Adult_18Plus tab directly from GitHub Actions runner (13 columns format).
    Prioritizes Service Account (GDRIVE_SA_BASE64) for Google Sheets API.
    """
    if not row_index:
        return False
    sheet_id = os.environ.get("GSHEET_QUEUE_ID", "1qCYT9HV99mTkwyjL4EemqLeIGg_rZpKw0wH0yLl1IEQ")
    sa_b64 = os.environ.get("GDRIVE_SA_BASE64", "")
    try:
        import gspread
        import datetime
        from google.oauth2 import service_account

        creds = None
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        if sa_b64:
            try:
                missing_padding = len(sa_b64) % 4
                if missing_padding:
                    sa_b64 += '=' * (4 - missing_padding)
                sa_info = json.loads(base64.b64decode(sa_b64).decode("utf-8"))
                creds = service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)
            except Exception as e:
                logger.warning(f"Error loading SA for sheets: {e}")

        if not creds:
            logger.warning("⚠️ No Google Sheet credentials available.")
            return False

        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet("Adult_18Plus")

        now_str = datetime.datetime.now().strftime("%d/%m %H:%M:%S")
        updates = []
        if title:
            updates.append({"range": f"D{row_index}", "values": [[str(title)]]})
        if movie_code:
            updates.append({"range": f"F{row_index}", "values": [[str(movie_code)]]})
        if ep_count:
            updates.append({"range": f"G{row_index}", "values": [[str(ep_count)]]})
        if status:
            updates.append({"range": f"H{row_index}", "values": [[str(status)]]})
        if post_id:
            updates.append({"range": f"I{row_index}", "values": [[str(post_id)]]})
        
        files_cnt = gdrive_files_count if gdrive_files_count is not None else (1 if drive_link else 0)
        updates.append({"range": f"J{row_index}", "values": [[str(files_cnt)]]})
        if drive_link:
            updates.append({"range": f"K{row_index}", "values": [[str(drive_link)]]})
        
        audit_res = f"✅ Khớp {files_cnt}/{ep_count} Tập" if files_cnt == ep_count and ep_count > 0 else f"⏳ {status}"
        updates.append({"range": f"L{row_index}", "values": [[str(audit_res)]]})
        updates.append({"range": f"M{row_index}", "values": [[now_str]]})

        ws.batch_update(updates)
        logger.info(f"📊 Updated GSheet row #{row_index} (13 columns): status='{status}', post_id='{post_id}', audit='{audit_res}'")
        return True
    except Exception as e:
        logger.warning(f"⚠️ GSheet update warning: {e}")
        return False

def get_stream_m3u8_url(embed_url):
    """
    Fetches real .m3u8 stream URL from javplayer.cc embed URL.
    Resolves sub-playlist to avoid 404 segments on master playlists.
    """
    if not embed_url:
        return None

    if embed_url.endswith(".m3u8") or ".m3u8?" in embed_url:
        return embed_url

    m_hid = re.search(r'/e/([a-zA-Z0-9_-]+)', embed_url)
    if not m_hid:
        return embed_url

    hash_id = m_hid.group(1)
    stream_api_url = f"https://javplayer.cc/stream?id={hash_id}"
    req_headers = {
        'User-Agent': HEADERS['User-Agent'],
        'Referer': embed_url if embed_url.startswith("http") else f"https://javplayer.cc/e/{hash_id}",
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }

    try:
        r = requests.get(stream_api_url, headers=req_headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            stream_url = data.get("media", {}).get("stream") or data.get("url")
            if stream_url:
                # If master playlist, resolve sub-playlist
                if stream_url.endswith("video.m3u8") or "video.m3u8?" in stream_url:
                    base_dir = stream_url.split("video.m3u8")[0]
                    # Check qc/v.m3u8 or qb/v.m3u8
                    for sub in ["qc/v.m3u8", "qd/v.m3u8", "qb/v.m3u8", "qa/v.m3u8"]:
                        sub_url = f"{base_dir}{sub}"
                        try:
                            chk = requests.get(sub_url, headers=req_headers, timeout=5)
                            if chk.status_code == 200 and "#EXTM3U" in chk.text:
                                return sub_url
                        except Exception:
                            pass
                return stream_url
    except Exception as e:
        logger.error(f"Error fetching stream m3u8 for hash {hash_id}: {e}")

    return None

def download_and_merge_m3u8(stream_url, output_mp4, referer="https://javplayer.cc/"):
    """
    Downloads HLS stream with multi-threaded yt-dlp and FFmpeg native stream copy.
    """
    logger.info(f"📥 Downloading stream to {output_mp4}...")
    
    # 1. Primary: yt-dlp -N 16
    logger.info("🚀 Attempting multi-threaded yt-dlp download (-N 16)...")
    dl_cmd = [
        'yt-dlp',
        '-N', '16',
        '--add-header', f'Referer: {referer}',
        '--add-header', f'User-Agent: {HEADERS["User-Agent"]}',
        '--downloader', 'ffmpeg',
        '--downloader-args', 'ffmpeg:-protocol_whitelist file,http,https,tcp,tls,crypto',
        '-o', output_mp4,
        stream_url
    ]
    try:
        res = subprocess.run(dl_cmd, capture_output=True, text=True)
        if os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 1024 * 100:
            logger.info(f"✅ yt-dlp download success: {format_bytes(os.path.getsize(output_mp4))}")
            return True
        else:
            logger.warning(f"⚠️ yt-dlp error: {res.stderr[-300:] if res.stderr else 'Failed'}")
    except Exception as e:
        logger.warning(f"⚠️ yt-dlp exception: {e}")

    # 2. Secondary Fallback: FFmpeg native stream copy
    logger.info("⚠️ Trying FFmpeg stream copy fallback...")
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-headers', f'Referer: {referer}\r\nUser-Agent: {HEADERS["User-Agent"]}\r\n',
        '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
        '-i', stream_url,
        '-c', 'copy',
        '-bsf:a', 'aac_adtstoasc',
        output_mp4
    ]
    try:
        res = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 1024 * 100:
            logger.info(f"✅ FFmpeg download success: {format_bytes(os.path.getsize(output_mp4))}")
            return True
        else:
            logger.error(f"❌ FFmpeg error: {res.stderr[-400:] if res.stderr else 'Failed'}")
    except Exception as e:
        logger.error(f"❌ FFmpeg execution exception: {e}")

    return False

def get_discussion_thread_id(channel_msg_id, code=""):
    """
    2-Tier Discussion Topic Resolution:
    Tier 1: Check getChat pinned_message
    Tier 2: Probe backwards starting from recent messages with retries for propagation delay.
    """
    if not channel_msg_id:
        return None

    # Step 1: Check getChat pinned_message
    try:
        r_chat = telegram_helper.make_tg_request("getChat", data={"chat_id": DISCUSS_CHAT_ID})
        if r_chat.get("ok"):
            pinned = r_chat.get("result", {}).get("pinned_message")
            if pinned:
                rep_id = pinned.get("message_id")
                fwd_id = pinned.get("forward_from_message_id")
                if not fwd_id and "forward_origin" in pinned:
                    fwd_id = pinned["forward_origin"].get("message_id")
                if fwd_id and str(fwd_id) == str(channel_msg_id):
                    logger.info(f"🎯 [Tier 1] Resolved Discussion Thread Msg #{rep_id} from pinned_message for Channel Post #{channel_msg_id}")
                    return rep_id
    except Exception as e:
        logger.warning(f"Pinned message check warning: {e}")

    # Step 2: Probe backwards with retries for propagation delay
    for attempt in range(1, 6):
        time.sleep(2.5 + attempt * 0.5)
        try:
            ping = telegram_helper.send_message(chat_id=DISCUSS_CHAT_ID, text="🔍 Syncing...")
            if ping.get("ok"):
                latest_id = ping["result"]["message_id"]
                telegram_helper.make_tg_request("deleteMessage", data={"chat_id": DISCUSS_CHAT_ID, "message_id": latest_id})

                # Check backwards up to 14 messages
                for test_id in range(latest_id - 1, max(1, latest_id - 15), -1):
                    chk = telegram_helper.send_message(chat_id=DISCUSS_CHAT_ID, text="✓", reply_to_message_id=test_id)
                    if chk.get("ok"):
                        rep_msg = chk["result"]
                        rep_id = rep_msg["message_id"]
                        telegram_helper.make_tg_request("deleteMessage", data={"chat_id": DISCUSS_CHAT_ID, "message_id": rep_id})

                        reply_to = rep_msg.get("reply_to_message", {})
                        fwd_id = reply_to.get("forward_from_message_id")
                        if not fwd_id and "forward_origin" in reply_to:
                            fwd_id = reply_to["forward_origin"].get("message_id")
                        
                        matched = False
                        if fwd_id and str(fwd_id) == str(channel_msg_id):
                            matched = True
                        elif code:
                            caption = (reply_to.get("caption") or reply_to.get("text") or "").upper()
                            if code.upper() in caption:
                                matched = True

                        if matched:
                            logger.info(f"🎯 [Tier 2] Resolved Discussion Thread Msg #{test_id} in {DISCUSS_CHAT_ID} for Channel Post #{channel_msg_id}")
                            return test_id
                    time.sleep(0.15)
        except Exception as e:
            logger.warning(f"Discussion thread resolution attempt {attempt} error: {e}")

    logger.error(f"❌ Could not resolve Discussion Thread ID for Channel Post #{channel_msg_id}")
    return None

def get_video_meta(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        video_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(res.stdout)
        streams = data.get("streams", [{}])[0]
        fmt = data.get("format", {})
        
        duration = float(streams.get("duration") or fmt.get("duration") or 0)
        width = int(streams.get("width", 1280))
        height = int(streams.get("height", 720))
        return {
            "width": width,
            "height": height,
            "duration": duration
        }
    except Exception as e:
        logger.warning(f"ffprobe warning: {e}")
        return {"width": 1280, "height": 720, "duration": 0}

def generate_video_thumb(video_path, thumb_path, timestamp=2.0):
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        thumb_path
    ]
    subprocess.run(cmd, capture_output=True)
    return os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0

def split_video_lossless(input_mp4, output_dir, max_bytes=MAX_CHUNK_BYTES):
    """
    Splits video into streamable parts <= 45MB using FFmpeg lossless stream copy.
    """
    os.makedirs(output_dir, exist_ok=True)
    file_size = os.path.getsize(input_mp4)
    if file_size <= max_bytes:
        return [input_mp4]

    meta = get_video_meta(input_mp4)
    duration = meta.get("duration", 0)
    if duration <= 0:
        return [input_mp4]

    num_parts = math.ceil(file_size / max_bytes)
    segment_duration = int(duration / num_parts)
    if segment_duration < 1:
        segment_duration = 1

    out_pattern = os.path.join(output_dir, "part_%03d.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_mp4,
        "-c", "copy",
        "-map", "0",
        "-segment_time", str(segment_duration),
        "-f", "segment",
        "-reset_timestamps", "1",
        out_pattern
    ]
    logger.info(f"✂️ Slicing video into ~{segment_duration}s streaming segments ({num_parts} parts)...")
    subprocess.run(cmd, capture_output=True)

    parts = sorted([
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith("part_") and f.endswith(".mp4") and os.path.getsize(os.path.join(output_dir, f)) > 1024
    ])
    if parts:
        return parts
    return [input_mp4]

def process_single_stream(stream_url, work_dir, title, code, ep_num, total_eps, chat_id, post_id, folder_id, owner_email):
    """
    Processes one episode / stream:
    1. Downloads stream to MP4.
    2. Uploads master to Google Drive (5TB OAuth2 with deduplication).
    3. Splits video into <=45MB parts.
    4. Posts parts with thumbnails, width, height, duration to Telegram comments.
    """
    safe_code = clean_filename(code) if code else "Stream"
    safe_title = clean_filename(title)[:60]
    if total_eps > 1:
        master_name = f"{safe_code} - Tập {ep_num} - {safe_title}.mp4"
    else:
        master_name = f"{safe_code} - {safe_title}.mp4"

    master_mp4 = os.path.join(work_dir, master_name)

    # 1. Download
    logger.info(f"🎬 [Stream {ep_num}/{total_eps}] Downloading: {master_name}")
    referer = "https://123av.org/" if "surrit.com" in stream_url else "https://javplayer.cc/"
    if not download_and_merge_m3u8(stream_url, master_mp4, referer=referer):
        logger.error(f"❌ Failed downloading stream for: {master_name}")
        return None

    master_size = os.path.getsize(master_mp4)
    logger.info(f"✅ Downloaded {master_name} ({format_bytes(master_size)})")

    # 2. Upload Master to Google Drive
    drive_link = ""
    logger.info("☁️ Uploading Master MP4 to Google Drive...")
    try:
        drive_link = gdrive_helper.upload_file_to_drive(
            local_path=master_mp4,
            file_name=master_name,
            parent_folder_id=folder_id,
            mime_type="video/mp4",
            owner_email=owner_email
        )
        logger.info(f"✅ GDrive Upload Complete: {drive_link}")
    except Exception as e:
        logger.warning(f"⚠️ GDrive Upload error: {e}")

    # 3. Post parts to Telegram comments
    if chat_id and post_id:
        logger.info(f"✂️ Splitting video for Telegram comments (Chat {chat_id}, Reply Thread #{post_id})...")
        split_dir = os.path.join(work_dir, f"split_ep_{ep_num}")
        parts = split_video_lossless(master_mp4, split_dir, max_bytes=MAX_CHUNK_BYTES)
        total_parts = len(parts)

        for p_idx, part_path in enumerate(parts, 1):
            p_size = os.path.getsize(part_path)
            part_meta = get_video_meta(part_path)
            part_dur = part_meta.get("duration", 0)
            part_w = part_meta.get("width", 1280)
            part_h = part_meta.get("height", 720)

            thumb_file = os.path.join(work_dir, f"thumb_ep{ep_num}_p{p_idx}.jpg")
            has_thumb = generate_video_thumb(part_path, thumb_file, timestamp=min(2.0, part_dur / 2 if part_dur else 1.0))

            ep_header = f"<b>{safe_code} - Tập {ep_num}/{total_eps}</b>" if total_eps > 1 else f"<b>{safe_code or safe_title}</b>"
            caption = f"📹 {ep_header}\n🧩 <b>Phần {p_idx}/{total_parts}</b> (<code>{format_bytes(p_size)}</code>)"
            if p_idx == 1 and drive_link:
                caption += f"\n💾 <a href='{drive_link}'>Google Drive Master (Lossless)</a>"

            logger.info(f"  📤 Sending Part {p_idx}/{total_parts} ({format_bytes(p_size)}) with thumbnail {part_w}x{part_h} ({part_dur:.0f}s)...")
            
            # Robust retry loop per part
            sent_ok = False
            for send_attempt in range(1, 7):
                res = telegram_helper.send_video(
                    chat_id=chat_id,
                    video_path=part_path,
                    caption=caption,
                    thumb_path=thumb_file if has_thumb else None,
                    duration=part_dur,
                    width=part_w,
                    height=part_h,
                    reply_to_message_id=int(post_id)
                )
                if res.get("ok"):
                    sent_msg_id = res.get("result", {}).get("message_id")
                    logger.info(f"    ✅ Telegram Part {p_idx}/{total_parts} sent (Msg ID {sent_msg_id})")
                    sent_ok = True
                    break
                else:
                    logger.warning(f"    ⚠️ Telegram Part {p_idx}/{total_parts} send attempt {send_attempt} failed: {res.get('error')}")
                    time.sleep(3 * send_attempt)

            if not sent_ok:
                logger.error(f"❌ Failed to send Part {p_idx}/{total_parts} after all retries!")

            # Immediate cleanup of part to conserve disk space
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)
                if os.path.exists(thumb_file):
                    os.remove(thumb_file)
            except Exception:
                pass

            time.sleep(2.5)  # Pacing between parts

        shutil.rmtree(split_dir, ignore_errors=True)
    elif chat_id and not post_id:
        logger.error("❌ [GATEKEEPER BARRIER] Discussion thread ID not available. Skipped part upload to protect general chat.")

    try:
        os.remove(master_mp4)
    except Exception:
        pass

    return {
        "filename": master_name,
        "drive_link": drive_link,
        "size": master_size
    }

def main():
    logger.info("==================================================================")
    logger.info(f"🎬 STARTING MEDIA STREAM PIPELINE: {TASK_ID}")
    logger.info("==================================================================")

    data = parse_payload()
    title = data.get("title", TASK_ID)
    code = data.get("code", "")
    target_url = data.get("url", "")
    m3u8_url = data.get("m3u8_url", "")
    chat_id = data.get("chat_id", "")
    post_id = data.get("post_id", "")
    folder_id = data.get("folder_id", DRIVE_ROOT)
    owner_email = data.get("owner_email", DEFAULT_OWNER_EMAIL)
    row_index = data.get("row_index")

    if row_index:
        update_gsheet_row(row_index, title=title, movie_code=code, status="In Progress (Cloud Runner)")

    channel_id = os.environ.get("TARGET_CHANNEL_ID", "-1002244827586")
    discuss_id = os.environ.get("DISCUSS_CHAT_ID", "-1002087114535")

    episodes_raw = data.get("episodes", [])
    episodes_to_process = []
    details = {}

    # 1. Primary: Use explicit episodes from payload if available
    if episodes_raw:
        logger.info(f"📋 Processing {len(episodes_raw)} explicit episodes from payload...")
        for ep in episodes_raw:
            ep_url = ep.get("stream_url") or ep.get("url") or ""
            if ep_url:
                episodes_to_process.append({
                    "name": ep.get("name", str(ep.get("number", 1))),
                    "number": ep.get("number", 1),
                    "stream_url": ep_url
                })
    elif m3u8_url:
        episodes_to_process.append({"name": "1", "number": 1, "stream_url": m3u8_url})
    
    # 2. Secondary Fallback: Scrape 123av if no explicit stream URLs were provided
    if not episodes_to_process:
        if is_123av_url(target_url) and "/e/" not in target_url and not target_url.endswith(".m3u8"):
            logger.info(f"🔍 Scraping 123AV details for: {target_url}")
            details = scrape_123av_details(target_url)
            if not details.get("error"):
                title = details.get("title") or title
                code = details.get("code") or code
                eps = details.get("episodes", [])
                for ep in eps:
                    ep_url = ep.get("url", "")
                    resolved_m3u8 = get_stream_m3u8_url(ep_url) if ("/e/" in ep_url and ".m3u8" not in ep_url) else ep_url
                    if resolved_m3u8:
                        episodes_to_process.append({
                            "name": ep.get("name", "1"),
                            "number": ep.get("number", 1),
                            "stream_url": resolved_m3u8
                        })
            else:
                logger.warning(f"⚠️ Scraping failed: {details.get('error')}")

    if not episodes_to_process:
        logger.error("❌ No playable stream URLs could be extracted. Exiting with error.")
        if row_index:
            update_gsheet_row(row_index, title=title, movie_code=code, status="Error (No Stream URL)")
        sys.exit(1)

    work_dir = os.path.join("./temp_downloads", f"task_{int(time.time())}")
    os.makedirs(work_dir, exist_ok=True)

    channel_post_id = None
    disc_thread_id = None

    if post_id:
        channel_post_id = str(post_id)
        logger.info(f"📢 Using existing Channel Post #{channel_post_id}")
        disc_thread_id = get_discussion_thread_id(channel_post_id, code=code)
    else:
        caption_lines = [f"🎬 <b>{title}</b>"]
        if code:
            caption_lines.append(f"🏷️ <b>Mã phim:</b> <code>{code}</code>")
        meta = data.get("metadata") or details.get("metadata", {})
        if meta.get("Cast"):
            caption_lines.append(f"💃 <b>Diễn viên:</b> {meta.get('Cast')}")
        if meta.get("Maker"):
            caption_lines.append(f"🏢 <b>Hãng:</b> {meta.get('Maker')}")
        if meta.get("Release date"):
            caption_lines.append(f"📅 <b>Phát hành:</b> {meta.get('Release date')}")
        if meta.get("Genres"):
            caption_lines.append(f"🎭 <b>Thể loại:</b> {meta.get('Genres')}")
        caption_lines.append("")
        post_caption = "\n".join(caption_lines)
        cover_url = data.get("cover_url") or details.get("cover_url")

        if cover_url:
            p_res = telegram_helper.send_photo(chat_id=channel_id, photo_path_or_url=cover_url, caption=post_caption)
        else:
            p_res = telegram_helper.send_message(chat_id=channel_id, text=post_caption)

        if p_res.get("ok"):
            channel_post_id = str(p_res.get("result", {}).get("message_id"))
            logger.info(f"📢 Created Channel Post #{channel_post_id} on {channel_id}")
            disc_thread_id = get_discussion_thread_id(channel_post_id, code=code)
            if row_index:
                update_gsheet_row(row_index, title=title, movie_code=code, post_id=channel_post_id, status="In Progress (Downloading)")
        else:
            logger.error(f"❌ Failed creating channel post: {p_res}")

    if not disc_thread_id and channel_post_id:
        logger.warning("⚠️ Discussion thread ID not immediately resolved, retrying one final time...")
        disc_thread_id = get_discussion_thread_id(channel_post_id, code=code)

    target_chat_id = discuss_id
    target_reply_id = str(disc_thread_id) if disc_thread_id else None
    logger.info(f"🔒 Destination: Chat {target_chat_id}, Thread/Reply Msg #{target_reply_id or 'NOT FOUND'}")

    logger.info(f"📦 Total episodes to process: {len(episodes_to_process)}")
    total_eps = len(episodes_to_process)
    results = []

    for ep_idx, ep in enumerate(episodes_to_process, 1):
        stream_url = ep["stream_url"]
        res = process_single_stream(
            stream_url=stream_url,
            work_dir=work_dir,
            title=title,
            code=code,
            ep_num=ep_idx,
            total_eps=total_eps,
            chat_id=target_chat_id,
            post_id=target_reply_id,
            folder_id=folder_id,
            owner_email=owner_email
        )
        if res:
            results.append(res)
        else:
            logger.error(f"❌ Failed processing stream for episode {ep_idx}")
            shutil.rmtree(work_dir, ignore_errors=True)
            if row_index:
                update_gsheet_row(row_index, title=title, movie_code=code, status="Error (Stream Download Failed)")
            sys.exit(1)

    if target_chat_id and target_reply_id and results:
        summary_msg = (
            f"✅ <b>HOÀN TẤT XỬ LÝ MEDIA STREAM: <code>{code or title[:40]}</code></b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        for r in results:
            summary_msg += f"• <b>{r['filename']}:</b> {format_bytes(r['size'])}\n"
            if r['drive_link']:
                summary_msg += f"  💾 <a href='{r['drive_link']}'>Tải bản gốc Lossless Google Drive</a>\n"
        summary_msg += "\n🎉 <i>Quý vị có thể xem video trực tiếp ở trên hoặc tải file gốc từ Google Drive.</i>"

        telegram_helper.send_message(
            chat_id=target_chat_id,
            text=summary_msg,
            parse_mode="HTML",
            reply_to_message_id=int(target_reply_id)
        )

    master_link = results[0]["drive_link"] if results else ""
    if row_index:
        update_gsheet_row(
            row_index=row_index,
            title=title,
            movie_code=code,
            post_id=channel_post_id or post_id,
            drive_link=master_link,
            status="Completed",
            ep_count=total_eps,
            gdrive_files_count=len(results)
        )

    shutil.rmtree(work_dir, ignore_errors=True)
    logger.info("🎉 Media stream processing pipeline completed successfully.")

if __name__ == "__main__":
    main()
