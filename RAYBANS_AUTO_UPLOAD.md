# Ray-Bans → API Auto-Upload (iOS Shortcut)

Pipeline: Meta Ray-Bans → Meta AI app (auto-import to Camera Roll) → iOS Automation triggers on new video → Shortcut POSTs the file to your API on Render.

## One-time setup

### 1. Make Meta AI auto-save to Photos
- Meta AI app → Settings → Camera Roll → enable "Save to Camera Roll" (or "Auto Import")
- Optional: in Photos, create an album called `Ray-Bans` and let Meta AI import there, so the trigger only fires for glasses captures, not every photo you take.

### 2. Build the Shortcut (Shortcuts app → `+`)

Name it `Upload Ray-Bans Clip`. Actions, in order:

1. **Get Latest Videos** — Count: 1, sorted by Most Recent (or use the "Shortcut Input" if launched from automation)
2. **Get Contents of URL**
   - URL: `https://<your-render-app>.onrender.com/api/upload` (your inference endpoint)
   - Method: `POST`
   - Request Body: `Form`
   - Add field:
     - Key: `video` (or whatever the API expects)
     - Type: `File`
     - Value: the video from step 1
   - Headers (optional): `Authorization: Bearer <token>`
3. **Show Notification** — "Uploaded ✓" with the response, so you know it worked.

### 3. Wire it to an Automation (Shortcuts app → Automation tab → `+`)

- Trigger: **When [Photo/Video] is added to [Ray-Bans album]** (or just the Camera Roll if you skipped the album)
- Action: **Run Shortcut → Upload Ray-Bans Clip**
- Pass the new item as input
- Set **Run Immediately** (no confirmation tap) — iOS 15+ allows this for album triggers.

## Caveats

- **Meta View / Meta AI sync is manual-ish.** The glasses sync to the phone over Wi-Fi when in range and the app is open. There's no true "instant push." Expect a delay between capture and upload.
- **Background reliability.** iOS automations are best-effort; if Shortcuts is killed or the phone is locked for a long time, triggers can be deferred. For a demo, keep the phone awake.
- **File size.** Ray-Bans clips can be large; the API needs to accept multipart uploads up to ~100MB with a generous timeout. On Render, check the request body size limit on your service plan.
- **Endpoint contract.** Target the `/agent` upload route that creates a new `scene_id` under `artifacts/scenes/<scene_id>/`.
