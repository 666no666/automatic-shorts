import os, re, json, hashlib, asyncio, subprocess, textwrap, random
from pathlib import Path
from datetime import datetime, timezone, timedelta
import feedparser, requests, edge_tts
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
STATE = ROOT / "state" / "used.json"
OUT.mkdir(exist_ok=True)
STATE.parent.mkdir(exist_ok=True)

FEEDS = [
    "https://www.nasa.gov/feed/",
    "https://www.smithsonianmag.com/rss/latest_articles/",
    "https://www.sciencedaily.com/rss/top/science.xml",
]
VOICE = os.getenv("VEYLO_VOICE", "en-US-AndrewNeural")
MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "14"))

def load_used():
    if STATE.exists():
        try: return set(json.loads(STATE.read_text()).get("used", []))
        except Exception: pass
    return set()

def save_used(used):
    STATE.write_text(json.dumps({"used": sorted(used)}, indent=2))

def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()

def get_candidates():
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:25]:
                link = e.get("link", "")
                title = clean(e.get("title", ""))
                summary = clean(e.get("summary", e.get("description", "")))
                if not link or not title or len(summary) < 40: continue
                published = e.get("published_parsed") or e.get("updated_parsed")
                if published:
                    import time
                    dt = datetime.fromtimestamp(time.mktime(published), timezone.utc)
                    if dt < cutoff: continue
                key = hashlib.sha256(link.encode()).hexdigest()
                items.append({"key": key, "title": title, "summary": summary[:1600], "link": link})
        except Exception as ex:
            print("Feed error:", url, str(ex))
    random.shuffle(items)
    return items

def make_script(item):
    title = item["title"].rstrip(".")
    summary = item["summary"]
    # Keep claims tied to the source summary; avoid inventing dates or statistics.
    sentences = re.split(r'(?<=[.!?])\s+', summary)
    body = " ".join(sentences[:4]).strip()
    if len(body) > 650: body = body[:647].rsplit(" ", 1)[0] + "..."
    return (
        f"Here is something worth knowing. {title}. "
        f"{body} "
        "The details matter, because discoveries like this can change how we understand the world. "
        "Read the original report linked in the description."
    )

async def make_audio(script, path):
    """Try Edge TTS first; fall back to offline eSpeak NG if the service rejects the request."""
    communicate = edge_tts.Communicate(script, VOICE, rate="+5%", volume="+0%")
    try:
        await communicate.save(str(path))
        if path.exists() and path.stat().st_size > 1000:
            print("Audio generated with Edge TTS")
            return
        raise RuntimeError("Edge TTS returned an empty audio file")
    except Exception as exc:
        print("Edge TTS failed; switching to offline eSpeak NG:", repr(exc))
        wav_path = path.with_suffix(".wav")
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "155", "-w", str(wav_path), script],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "4", str(path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        wav_path.unlink(missing_ok=True)
        if not path.exists() or path.stat().st_size < 1000:
            raise RuntimeError("Offline eSpeak NG audio generation failed")
        print("Audio generated with offline eSpeak NG")

def commons_image(query, path):
    api = "https://commons.wikimedia.org/w/api.php"
    params = {"action":"query","format":"json","generator":"search","gsrsearch":query,
              "gsrnamespace":6,"gsrlimit":8,"prop":"imageinfo","iiprop":"url",
              "iiurlwidth":1080}
    try:
        data = requests.get(api, params=params, timeout=25, headers={"User-Agent":"VEYLOShorts/1.0"}).json()
        pages = list(data.get("query", {}).get("pages", {}).values())
        random.shuffle(pages)
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url: continue
            r = requests.get(url, timeout=30, headers={"User-Agent":"VEYLOShorts/1.0"})
            if r.ok and r.headers.get("content-type","").startswith("image/"):
                Path(path).write_bytes(r.content)
                return info.get("descriptionurl", url)
    except Exception as e:
        print("Commons lookup failed:", e)
    return None

def make_card(title, path):
    im = Image.new("RGB", (1080,1920), (8,14,30))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 68)
    except:
        font = ImageFont.load_default()
    words, lines, line = title.split(), [], ""
    for w in words:
        test = (line + " " + w).strip()
        if d.textbbox((0,0), test, font=font)[2] > 900:
            lines.append(line); line = w
        else: line = test
    if line: lines.append(line)
    y = 700 - len(lines)*45
    for ln in lines:
        d.text((80,y), ln, font=font, fill=(230,240,255), stroke_width=2, stroke_fill=(0,0,0))
        y += 105
    d.text((80,1650), "BEYOND THE UNKNOWN", fill=(70,210,255))
    im.save(path)

def render(image_path, audio_path, mp4_path, title):
    # Simple single-image motion video with audio; safe fallback if no image found.
    cmd = ["ffmpeg","-y","-loop","1","-i",str(image_path),"-i",str(audio_path),
           "-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.0005,1.08)':d=1:s=1080x1920:fps=30,format=yuv420p",
           "-tune","stillimage","-c:v","libx264","-preset","veryfast","-t","55",
           "-c:a","aac","-b:a","128k","-shortest",str(mp4_path)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def upload_youtube(video, title, description):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    token = os.environ["YOUTUBE_TOKEN_JSON"]
    creds = Credentials.from_authorized_user_info(json.loads(token), ["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube","v3",credentials=creds)
    body = {"snippet":{"title":title[:95],"description":description[:4900] + "\n\n#Shorts #Science #History","categoryId":"27"},
            "status":{"privacyStatus":os.getenv("YOUTUBE_PRIVACY_STATUS","private"),"selfDeclaredMadeForKids":False}}
    req = yt.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(video),mimetype="video/*",resumable=True))
    result = req.execute()
    print("Uploaded video ID:", result.get("id"))

def main():
    used = load_used()
    chosen = next((x for x in get_candidates() if x["key"] not in used), None)
    if not chosen: raise SystemExit("No fresh RSS item found; try again later.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    slug = re.sub(r"[^a-z0-9]+","-",chosen["title"].lower()).strip("-")[:45] or "short"
    base = OUT / f"{stamp}_{slug}"
    script = make_script(chosen)
    (base.with_suffix(".txt")).write_text(script + "\n\nSOURCE: " + chosen["link"], encoding="utf-8")
    audio = base.with_suffix(".mp3")
    asyncio.run(make_audio(script, audio))
    img = base.with_suffix(".jpg")
    credit = commons_image(chosen["title"], img)
    if not credit: make_card(chosen["title"], img)
    mp4 = base.with_suffix(".mp4")
    render(img, audio, mp4, chosen["title"])
    desc = f"Source: {chosen['link']}\nVisual source: {credit or 'Generated text card'}\n\nThis short summarizes the linked source. Check the original report for full context."
    (base.with_suffix(".description.txt")).write_text(desc, encoding="utf-8")
    used.add(chosen["key"]); save_used(used)
    print("Created:", mp4)
    if os.getenv("PUBLISH_TO_YOUTUBE","false").lower() == "true":
        upload_youtube(mp4, chosen["title"] + " #Shorts", desc)
    else:
        print("Publishing disabled. Set PUBLISH_TO_YOUTUBE=true after OAuth setup.")

if __name__ == "__main__":
    main()
