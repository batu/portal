#!/usr/bin/env python3
"""Seed a wool-crush journey demo.

This is data/tooling, NOT Portal logic: every wool-crush-specific constant
(slug, step titles, real artifact ids) lives here in scripts/, never in
gallery/** (the journey primitive is a generic substrate — see card YGFaO9P6 R9).

Two modes:

  remote (default): POST the wool-crush journey to a *running* Portal over HTTP,
    referencing the real production artifact ids that already exist there
    (proxy video post, frame-picker request, style report p_f6d5b8, asset sheet
    p_d7b881, token-promotion request req_ffb283). Base URL + token come from
    --base-url/--token or GALLERY_URL/GALLERY_TOKEN / config.json.

  --local: build a small self-contained demo in the local GALLERY_DATA_DIR
    (a real image post + an open request + a journey referencing them) directly
    via the db layer, so scripts/verify-journey.sh can screenshot a real page
    without any production ids. Used by the verify script.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow running as a bare script (python scripts/seed_journey_demo.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gallery import client, config  # noqa: E402


def build_wool_crush_doc(
    *,
    video_post: str,
    video_file: str,
    frame_picker_request: str,
    style_post: str,
    style_file: str,
    assets_post: str,
    assets_file: str,
    token_promo_request: str,
) -> dict:
    """The ordered wool-crush story, as producer data. Returns {"steps": [...]}."""
    return {
        "steps": [
            {
                "title": "Watch the proxy render",
                "summary": "The first thing you watch — the proxy video, referenced by its "
                "already-uploaded post (no 32MB re-upload).",
                "media": [{"owner_id": video_post, "filename": video_file, "caption": "Proxy render"}],
            },
            {
                "title": "Pick the frames",
                "summary": "Choose the keyframes that define the look.",
                "request_id": frame_picker_request,
            },
            {
                "title": "Review the style",
                "summary": "Palette and rendering direction.",
                "media": [{"owner_id": style_post, "filename": style_file, "caption": "Style report p_f6d5b8"}],
            },
            {
                "title": "Lay out the asset sheet",
                "media": [{"owner_id": assets_post, "filename": assets_file, "caption": "Asset sheet p_d7b881"}],
            },
            {
                "title": "Promote the tokens",
                "summary": "Ship the promoted tokens.",
                "request_id": token_promo_request,
            },
        ]
    }


def _demo_frame_png() -> bytes:
    """A 16:9 placeholder frame so the local visual check shows real media, not a
    stretched 1px pixel. Uses Pillow if present (it is in the dev extra); falls
    back to a tiny valid PNG so the seed never hard-fails on a missing dependency."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000002000100ffff03000006000557bfabd4000000"
            "0049454e44ae426082"
        )
    import io

    img = Image.new("RGB", (1280, 720), (26, 29, 36))
    draw = ImageDraw.Draw(img)
    for i in range(0, 1280, 80):
        draw.line([(i, 0), (i, 720)], fill=(34, 38, 47), width=1)
    draw.rectangle([440, 250, 840, 470], outline=(79, 140, 255), width=6)
    draw.text((470, 340), "REFERENCE FRAME", fill=(220, 226, 235))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _seed_local(slug: str) -> dict:
    """Build a self-contained demo in the local data dir and upsert the journey."""
    from gallery import db  # imported lazily so remote mode never touches the local db

    config.init_config(force=False)
    db.reset_connection()

    png = _demo_frame_png()
    image_post_id = "p_demoimg"
    media_dir = config.media_dir() / image_post_id
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "reference.png").write_bytes(png)
    if db.get_stream(slug) is None:
        db.create_stream(slug, "session", "Wool Crush (demo)")
    if db.get_post(image_post_id) is None:  # fixed post id: keep re-runs idempotent
        db.create_post_for_stream(
            slug, "report", "Reference frame", "codex",
            {"files": [{"media_path": "reference.png", "media_type": "image/png", "size": len(png), "original_name": "reference.png"}]},
            post_id=image_post_id,
        )
    req_id = db.new_request_id()
    db.create_request(req_id, "Pick the frames", None, "pick-one", None,
                      [{"media_path": "reference.png", "media_type": "image", "caption": "frame", "meta": None}])
    doc = {
        "steps": [
            {"title": "See the reference frame",
             "summary": "A picked frame, referenced by its post — not re-uploaded.",
             "media": [{"owner_id": image_post_id, "filename": "reference.png", "caption": "Reference frame"}]},
            {"title": "Pick the frames", "summary": "Live status is pulled from the DB at render time.",
             "request_id": req_id},
        ]
    }
    return db.upsert_journey(slug, "Wool Crush (demo)", doc)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Seed a wool-crush journey demo")
    parser.add_argument("--slug", default="wool-crush")
    parser.add_argument("--title", default="Wool Crush")
    parser.add_argument("--local", action="store_true", help="Build a self-contained local demo (for verify-journey.sh)")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--token", default=None)
    # Real production artifact ids (override to match your Portal).
    parser.add_argument("--video-post", default="p_proxyvid")
    parser.add_argument("--video-file", default="proxy.mp4")
    parser.add_argument("--frame-picker-request", default="req_framepick")
    parser.add_argument("--style-post", default="p_f6d5b8")
    parser.add_argument("--style-file", default="index.html")
    parser.add_argument("--assets-post", default="p_d7b881")
    parser.add_argument("--assets-file", default="index.html")
    parser.add_argument("--token-promo-request", default="req_ffb283")
    args = parser.parse_args(argv)

    if args.local:
        seeded = _seed_local(args.slug)
        print(json.dumps({"slug": seeded["slug"], "mode": "local", "steps": len(seeded["doc"]["steps"])}))
        return

    base_url = (args.base_url or config.client_config()[0]).rstrip("/")
    token = args.token or config.client_config()[1]
    doc = build_wool_crush_doc(
        video_post=args.video_post,
        video_file=args.video_file,
        frame_picker_request=args.frame_picker_request,
        style_post=args.style_post,
        style_file=args.style_file,
        assets_post=args.assets_post,
        assets_file=args.assets_file,
        token_promo_request=args.token_promo_request,
    )
    result = client.upsert_journey(base_url, token, args.slug, args.title, doc)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
