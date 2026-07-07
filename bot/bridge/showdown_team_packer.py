from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from bot.bridge.showdown_bridge import ShowdownBridgeError


async def pack_team(
    *,
    bot_dir: Path,
    showdown_dir: Path,
    format_id: str,
    team: list[dict[str, Any]],
) -> dict[str, Any]:
    if not team:
        raise ShowdownBridgeError("Cannot pack an empty team.")

    return await _run_team_packer(
        bot_dir=bot_dir,
        showdown_dir=showdown_dir,
        payload={
            "type": "pack-team",
            "formatid": format_id,
            "team": team,
        },
    )


async def import_team(
    *,
    bot_dir: Path,
    showdown_dir: Path,
    format_id: str,
    text: str,
) -> dict[str, Any]:
    if not str(text or "").strip():
        raise ShowdownBridgeError("Missing Showdown team export text.")

    return await _run_team_packer(
        bot_dir=bot_dir,
        showdown_dir=showdown_dir,
        payload={
            "type": "import-team",
            "formatid": format_id,
            "text": text,
        },
    )


async def _run_team_packer(
    *,
    bot_dir: Path,
    showdown_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    script_path = bot_dir / "bridge" / "showdown_team_packer.js"
    encoded_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    env = os.environ.copy()
    env["SHOWDOWN_DIR"] = str(showdown_dir)

    process = await asyncio.create_subprocess_exec(
        "node",
        str(script_path),
        cwd=str(bot_dir),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(encoded_payload)

    stderr_text = (stderr or b"").decode("utf-8", errors="replace").strip()
    stdout_text = (stdout or b"").decode("utf-8", errors="replace").strip()
    if process.returncode != 0 and not stdout_text:
        detail = stderr_text or "Team packer failed."
        raise ShowdownBridgeError(detail)

    try:
        result = json.loads(stdout_text.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        detail = stderr_text or stdout_text or "Team packer returned invalid output."
        raise ShowdownBridgeError(detail) from exc

    if not result.get("ok"):
        detail = str(result.get("error") or stderr_text or "Team packer rejected the team.")
        raise ShowdownBridgeError(detail)
    return result
