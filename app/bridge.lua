-- bridge.lua (command.json + ack.json bridge)
-- This script runs inside REAPER and polls command.json for actions.
-- Supports:
--   {"id":"...","type":"set_tempo","bpm":120}
--   {"id":"...","type":"insert_track","index":0}
--   {"id":"...","type":"set_cursor","seconds":0.0}
--   {"id":"...","type":"insert_sample","path":"C:\\...\\kick.wav","track":0}
--   {"id":"...","type":"run_action","action":1007}
--
-- Clears command.json after executing.

-- Base directory for command/ack files.
local BASE = [[C:\Users\colli\dev\Personal\REAPER\bridge_test\]]
local CMD_PATH = BASE .. "command.json"
local ACK_PATH = BASE .. "ack.json"

-- Read full file contents as a string
local function read_all(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  return s
end

-- Write full string to a file; returns true on success.
local function write_all(path, s)
  local f = io.open(path, "w")
  if not f then return false end
  f:write(s)
  f:close()
  return true
end

-- json parsing helpers
local function get_string(str, key)
  local pat = [["]] .. key .. [["%s*:%s*"(.-)"]]
  return str:match(pat)
end

local function get_number(str, key)
  local pat = [["]] .. key .. [["%s*:%s*(%-?%d+%.?%d*)]]
  local v = str:match(pat)
  return v and tonumber(v) or nil
end

-- Escape basic JSON string characters for ack messages
local function escape_json(s)
  s = tostring(s or "")
  s = s:gsub("\\", "\\\\")
  s = s:gsub([["]], [[\"]])
  s = s:gsub("\n", "\\n")
  s = s:gsub("\r", "\\r")
  return s
end

-- Write ack.json with the command id, 'ok' flag, and message
local function write_ack(id, ok, msg)
  if not id then return end
  local ack = string.format([[{"id":"%s","ok":%s,"message":"%s"}]],
    escape_json(id),
    ok and "true" or "false",
    escape_json(msg)
  )
  write_all(ACK_PATH, ack)
end

-- Confirm file existence so the bridge can read/write immediately.
if not read_all(CMD_PATH) then write_all(CMD_PATH, "{}") end
if not read_all(ACK_PATH) then write_all(ACK_PATH, "{}") end

-- Main Loop
-- Runs inside REAPER and listens
local function loop()
  local cmd = read_all(CMD_PATH)

  -- Ignore empty or non-actionable content
  if cmd and cmd ~= "{}" and #cmd > 2 then
    local id  = get_string(cmd, "id")
    local typ = get_string(cmd, "type")

    local ok, msg = true, "ok"

    if typ == "set_tempo" then
      local bpm = get_number(cmd, "bpm")
      if bpm then
        reaper.SetCurrentBPM(0, bpm, true)
        msg = "tempo set to " .. tostring(bpm)
      else
        ok, msg = false, "missing bpm"
      end

    elseif typ == "insert_track" then
      local idx = get_number(cmd, "index") or 0
      reaper.InsertTrackAtIndex(idx, true)
      msg = "inserted track at index " .. tostring(idx)

    elseif typ == "remove_track" then
      local idx = get_number(cmd, "index")
      if idx == nil then
        ok, msg = false, "missing index"
      else
        local track = reaper.GetTrack(0, idx)
        if not track then
          ok, msg = false, "invalid track index: " .. tostring(idx)
        else
          reaper.DeleteTrack(track)
          msg = "removed track at index " .. tostring(idx)
        end
      end

    elseif typ == "set_cursor" then
      local pos = get_number(cmd, "seconds")
      if pos then
        reaper.SetEditCurPos(pos, true, false)
        msg = "cursor set to " .. tostring(pos)
      else
        ok, msg = false, "missing seconds"
      end

    elseif typ == "insert_sample" then
      local path = get_string(cmd, "path")
      local track_idx = get_number(cmd, "track") or 0

      if not path or path == "" then
        ok, msg = false, "missing path"
      else
        local track = reaper.GetTrack(0, track_idx)
        if not track then
          ok, msg = false, "invalid track index: " .. tostring(track_idx)
        else
          -- Select the target track for InsertMedia
          reaper.SetOnlyTrackSelected(track)
          local ins_ok = reaper.InsertMedia(path, 0)
          if ins_ok then
            ok, msg = true, "inserted sample on track " .. tostring(track_idx)
          else
            ok, msg = false, "InsertMedia failed (bad path?): " .. tostring(path)
          end
        end
      end

    elseif typ == "run_action" then
      local action = get_number(cmd, "action")
      if action then
        reaper.Main_OnCommand(action, 0)
        msg = "ran action " .. tostring(action)
      else
        ok, msg = false, "missing action id"
      end

    else
      ok, msg = false, "unknown type: " .. tostring(typ)
    end

    -- Emit ack to notify Python side
    write_ack(id, ok, msg)

    -- Clear command file to avoid reprocessing
    write_all(CMD_PATH, "{}")
    reaper.UpdateArrange()
    reaper.ShowConsoleMsg("[bridge] " .. (ok and "OK" or "ERR") .. " - " .. msg .. "\n")
  end

  -- Schedule the next poll without blocking REAPER
  reaper.defer(loop)
end

-- Initial console output so it's obvious the bridge is running
reaper.ShowConsoleMsg("Bridge running.\n")
reaper.ShowConsoleMsg("Watching: " .. CMD_PATH .. "\n")
loop()
