import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from openai import OpenAI



# Using a dataclass to keep the configuration explicit and immutable
@dataclass(frozen=True)
class AppConfig:
    
    base: Path
    model: str = "gpt-4.1-mini"

    @property
    def tools_path(self) -> Path:
        # JSON schema for available tools that the model can call.
        return self.base / "tools" / "reaper_tools.json"

    @property
    def cmd_path(self) -> Path:
        # Path to the command JSON file that the Lua bridge watches.
        return self.base / "command.json"

    @property
    def ack_path(self) -> Path:
        # Path to the ack JSON file that the Lua bridge writes back.
        return self.base / "ack.json"

    @property
    def sounds_dir(self) -> Path:
        return Path(__file__).resolve().parent / "sounds"


CONFIG = AppConfig(base=Path(r"<path to files>"))


# System prompt that constrains how the model behaves and which tools it should call
SYSTEM_PROMPT = """You are a REAPER assistant.

You have tools:
- list_samples: browse local samples (kicks/claps/hats/misc)
- set_tempo: change REAPER tempo (BPM)
- add_basic_beat: deterministically add a simple beat using local samples
- insert_track: add a track
- remove_track: delete a track

Rules:
- If the user asks to change tempo/BPM, call set_tempo with the exact BPM they provided.
- If the user asks what sounds/samples exist or to search samples, call list_samples.
- If the user asks to add/make/create a beat/pattern/groove, call add_basic_beat.
- Keep responses concise.
"""

# Audio file extensions that can be used
_AUDIO_EXTS = {".wav", ".mp3", ".aif", ".aiff"}


def read_json(path: Path) -> dict:
    # Tries to read  jsno, returns '{}' for missing files or malformed JSON.
    # The bridge can transiently write partial files, so we treat failures as empty.
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict) -> None:
    # Simple JSON writer used to send commands to the bridge.
    # We do not indent to keep files compact and fast to parse.
    path.write_text(json.dumps(payload), encoding="utf-8")


def extract_bpm(user_text: str) -> Optional[float]:
    # Lowercase for case-insensitive pattern matching.
    t = user_text.lower()
    patterns = [
        r"\b(\d{2,3})\s*bpm\b",
        r"\btempo\s*(?:to\s*)?(\d{2,3})\b",
        r"\bbpm\s*(\d{2,3})\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return float(m.group(1))
    return None


def beats_to_seconds(beats: float, bpm: float) -> float:
    # Convert beat offsets to absolute seconds using the current tempo.
    return (60.0 / bpm) * beats


# Samples are stored in folder-system
# SampleLibrary allows for browsing and retrieval

class SampleLibrary:
    # Responsible for discovering and selecting sample files on disk.
    def __init__(self, sounds_dir: Path):
        self.sounds_dir = sounds_dir

    def list_samples(self, category: str, query: str = "", limit: int = 10) -> list[dict]:
        # Normalize query to make matching consistent and robust.
        q = (query or "").lower().strip()
        # Expand "all" into the four known sample folders.
        cats = ["kicks", "claps", "hats", "misc"] if category == "all" else [category]

        results: list[dict] = []
        for cat in cats:
            folder = self.sounds_dir / cat
            if not folder.exists():
                # Allow missing folders without error so the tool can still function.
                continue

            for p in folder.glob("**/*"):
                if not p.is_file():
                    continue
                # Filter by file extension first to avoid listing non-audio assets.
                if p.suffix.lower() not in _AUDIO_EXTS:
                    continue
                # Simple substring match on filename when a query is provided.
                if q and q not in p.name.lower():
                    continue

                results.append({"category": cat, "name": p.name, "path": str(p.resolve())})
                if len(results) >= limit:
                    return results
        return results

    def pick_first(self, category: str, query: str = "") -> Optional[dict]:
        # Convenience helper to fetch just one matching sample.
        matches = self.list_samples(category, query=query, limit=1)
        return matches[0] if matches else None


class ReaperBridge:
    # Handles the command/ack JSON exchange with the Lua bridge in REAPER.
    def __init__(self, cmd_path: Path, ack_path: Path, timeout_s: float = 3.0, poll_s: float = 0.05):
        self.cmd_path = cmd_path
        self.ack_path = ack_path
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def dispatch(self, cmd_type: str, **kwargs) -> dict:
        # Package the command with a unique id so we can match the ack.
        cmd_id = str(uuid.uuid4())
        payload = {"id": cmd_id, "type": cmd_type, **kwargs}
        print(f"[dispatch] {payload}")
        write_json(self.cmd_path, payload)
        # Block until the ack arrives or we time out.
        ack = self._wait_for_ack(cmd_id)
        print(f"[ack] {ack}")
        return ack

    def _wait_for_ack(self, cmd_id: str) -> dict:
        # Poll the ack file for a matching id within the timeout window.
        t0 = time.time()
        while time.time() - t0 < self.timeout_s:
            ack = read_json(self.ack_path)
            if ack.get("id") == cmd_id:
                # Clear after consuming so the next request does not re-read stale ack data.
                self.ack_path.write_text("{}", encoding="utf-8")
                return ack
            time.sleep(self.poll_s)
        return {"id": cmd_id, "ok": False, "message": "ack timeout"}




class ToolRunner:
    # Maps tool calls from the model into concrete Python handlers.
    def __init__(self, bridge: ReaperBridge, samples: SampleLibrary):
        self.bridge = bridge
        self.samples = samples

        # Registry: tool_name -> handler
        # Each handler signature is (args: dict, user_text: str) -> dict.
        self.handlers: dict[str, Callable[[dict, str], dict]] = {
            "list_samples": self._list_samples,
            "insert_track": self._insert_track,
            "remove_track": self._remove_track,
            "set_tempo": self._set_tempo,
            "add_basic_beat": self._add_basic_beat,
        }

    def run(self, tool_name: str, args: dict, user_text: str) -> dict:
        # Main dispatch entry point used by the LLM turn loop.
        fn = self.handlers.get(tool_name)
        if not fn:
            return {"ok": False, "message": f"Unknown tool: {tool_name}"}
        return fn(args, user_text)

    def _list_samples(self, args: dict, _: str) -> dict:
        # Fetch list of samples, optionally filtering by category/query/limit.
        category = args["category"]
        query = args.get("query", "")
        limit = int(args.get("limit", 10))
        found = self.samples.list_samples(category, query=query, limit=limit)
        return {"ok": True, "count": len(found), "samples": found}

    def _insert_track(self, args: dict, _: str) -> dict:
        # Ask the REAPER bridge to insert a track at the given index
        return self.bridge.dispatch("insert_track", index=int(args["index"]))

    def _remove_track(self, args: dict, _: str) -> dict:
        return self.bridge.dispatch("remove_track", index=int(args["index"]))

    def _set_tempo(self, args: dict, user_text: str) -> dict:
        # Use user bpm if stated
        bpm = extract_bpm(user_text)
        if bpm is None:
            bpm = float(args["bpm"])
        return self.bridge.dispatch("set_tempo", bpm=float(bpm))

    def _add_basic_beat(self, args: dict, user_text: str) -> dict:
        # Don't mutate args in-place
        bpm = extract_bpm(user_text) or float(args["bpm"])
        track = int(args["track"])
        bars = int(args.get("bars", 1))
        kick_query = args.get("kick_query", "")
        hat_query = args.get("hat_query", "")
        clap_query = args.get("clap_query", "")

        return self._add_basic_beat_impl(
            bpm=bpm,
            track=track,
            bars=bars,
            kick_query=kick_query,
            hat_query=hat_query,
            clap_query=clap_query,
        )

    def _add_basic_beat_impl(
        self,
        bpm: float,
        track: int,
        bars: int,
        kick_query: str,
        hat_query: str,
        clap_query: str,
    ) -> dict:
        # Resolve samples
        #Falls back to first smaple if htere isnt a match
        kick = self.samples.pick_first("kicks", kick_query) or self.samples.pick_first("kicks", "")
        hat = self.samples.pick_first("hats", hat_query) or self.samples.pick_first("hats", "")
        clap = self.samples.pick_first("claps", clap_query) or self.samples.pick_first("claps", "")

        if not kick or not hat or not clap:
            return {"ok": False, "message": "Missing samples in one or more categories. Check your sounds folders."}

        # set tempo first
        a = self.bridge.dispatch("set_tempo", bpm=float(bpm))
        if not a.get("ok"):
            return {"ok": False, "message": f"Failed setting tempo: {a.get('message')}"}

        # Builds hit list
        hits: list[tuple[str, str, float]] = []
        for bar in range(bars):
            base = bar * 4.0
            hits.append(("kick", kick["path"], base + 0.0))
            hits.append(("clap", clap["path"], base + 2.0))
            for b in (0.0, 1.0, 2.0, 3.0):
                hits.append(("hat", hat["path"], base + b))

        # Executign hit by moving curser
        for _, path, beat_pos in hits:
            sec = beats_to_seconds(beat_pos, bpm)

            a = self.bridge.dispatch("set_cursor", seconds=float(sec))
            if not a.get("ok"):
                return {"ok": False, "message": f"Failed set_cursor: {a.get('message')}"}

            a = self.bridge.dispatch("insert_sample", path=path, track=int(track))
            if not a.get("ok"):
                return {"ok": False, "message": f"Failed insert_sample: {a.get('message')}"}

        return {
            "ok": True,
            "message": f"Added {bars} bar(s) at {bpm} BPM on track {track}.",
            "used": {"kick": kick["name"], "clap": clap["name"], "hat": hat["name"]},
            "hits": len(hits),
        }


# Loads JSON for tools
def load_tools(tools_path: Path) -> list[dict]:
    with open(tools_path, "r", encoding="utf-8") as f:
        return json.load(f)


# Fallback incase LLM doesnt return text
def render_fallback_message(tool_name: str, tool_out: dict) -> str:
    if tool_name == "set_tempo":
        return "Tempo updated."
    if tool_name == "list_samples":
        return f"Found {tool_out.get('count', 0)} sample(s)."
    if tool_name == "add_basic_beat":
        if tool_out.get("ok"):
            used = tool_out.get("used", {})
            return f"{tool_out.get('message')} (kick={used.get('kick')}, clap={used.get('clap')}, hat={used.get('hat')})"
        return f"Couldn't add beat: {tool_out.get('message')}"
    return ""

# Main LLM turn looop
def run_turn(
    client: OpenAI,
    model: str,
    tools_schema: list[dict],
    tool_runner: ToolRunner,
    history: list[dict],
    user_text: str,
) -> tuple[list[dict], str]:
    # Append the new user message to the conversation history
    history = history + [{"role": "user", "content": user_text}]

    # First call: the model decides whether to call a tool or respond directly
    resp = client.responses.create(
        model=model,
        input=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        tools=tools_schema,
        parallel_tool_calls=False,
        max_tool_calls=1,
    )

    # The Responses API emits structured output objects; find the tool call if any
    tool_call = next((x for x in (resp.output or []) if getattr(x, "type", None) == "function_call"), None)

    if tool_call is None:
        # If no tool call is requested, return the model's text directly
        text = resp.output_text or ""
        return history + [{"role": "assistant", "content": text}], text

    # Parse out tool name and JSON arguments from the tool call object
    tool_name = tool_call.name
    args = json.loads(tool_call.arguments or "{}")
    call_id = getattr(tool_call, "call_id", None) or getattr(tool_call, "id", None)
    print(f"[ai_view] tool_call name={tool_name} args={args} id={call_id}")

    # Run the tool handler locally and capture its output
    tool_out = tool_runner.run(tool_name, args, user_text)

    # Second call: send the tool output back to the model for final text response
    resp2 = client.responses.create(
        model=model,
        previous_response_id=resp.id,
        tools=tools_schema,
        input=[{"type": "function_call_output", "call_id": call_id, "output": json.dumps(tool_out)}],
    )

    text2 = (resp2.output_text or "").strip()
    if not text2:
        # If the model yields no text, synthesize a minimal response
        text2 = render_fallback_message(tool_name, tool_out).strip()

    return history + [{"role": "assistant", "content": text2}], text2


def main() -> None:
    # load variables
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found")

    # Initialize OpenAI client and load tool schema definitions
    client = OpenAI(api_key=api_key)
    tools_schema = load_tools(CONFIG.tools_path)

    # Compose the sample library and bridge used by the tool runner
    samples = SampleLibrary(CONFIG.sounds_dir)
    bridge = ReaperBridge(CONFIG.cmd_path, CONFIG.ack_path)
    tool_runner = ToolRunner(bridge, samples)

    print("LLM REAPER Agent CLI")
    print("Type 'quit' to exit.\n")

    history: list[dict] = []
    while True:
        # Read user command
        user = input("> ").strip()
        if user.lower() in {"quit", "exit"}:
            break

        # Run a single turn and update the conversation history
        history, reply = run_turn(
            client=client,
            model=CONFIG.model,
            tools_schema=tools_schema,
            tool_runner=tool_runner,
            history=history,
            user_text=user,
        )

        if reply.strip():
            print("\n" + reply.strip() + "\n")


if __name__ == "__main__":
    main()
