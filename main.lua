local utils = require('mp.utils')
local SelectionMenu = require('modules.selectionmenu')


function trim(s)
    return s:gsub('^%s*(.-)%s*$', '%1')
end

function read_config(path, default)
    local ret = {}

    if default then
        for key, value in pairs(default) do
            ret[key] = value
        end        
    end        

    local file = io.open(path, 'r')

    if file then
        for line in file:lines() do
            line = trim(line)
            if line:find('^#') == nil then
                local i = line:find('=')
                if i ~= nil and i > 0 then
                    local key = trim(line:sub(0, i-1))
                    local value = trim(line:sub(i+1))
                    ret[key] = value
                end
            end
        end

        file:close()
    end

    return ret
end

function save_config(path, data)
    local file = io.open(path, 'w')

    if file then
        for key, value in pairs(data) do
            file:write(key .. '=' .. value)
            file:write('\n')
        end
        
        file:close()
    end
end

local default_config = {
    secondary_sub_area=0.25,
    secondary_sub_lang=''
}

local config = read_config(mp.get_script_directory() .. '/migaku_mpv.cfg', default_config)

local secondary_sub_area = tonumber(config['secondary_sub_area'])

local secondary_sub_langs = {}
for lang in config['secondary_sub_lang']:gmatch('([^,(?! )]+)') do
    table.insert(secondary_sub_langs, lang)
end


SubMode = {
    Default = 1,
    Reading = 2,
    Recall = 3,
    Hidden = 4,
}

local sub_mode = SubMode.Default
local sub_pause_time = nil


local function file_exists(name)
    local f = io.open(name, 'r')
    if f ~= nil then
        io.close(f)
        return true
    else
        return false
    end
end
 

local function get_ipc_handle()
    local ipc_handle_path = mp.get_property('input-ipc-server')

    if ipc_handle_path == '' or ipc_handle_path == nil then
        local new_ipc_handle_path = '/tmp/mpv-ipc-handle-' .. os.time()
        mp.set_property('input-ipc-server', new_ipc_handle_path)
        ipc_handle_path = mp.get_property('input-ipc-server')
    end

    if ipc_handle_path == '' then
        return nil
    end

    return ipc_handle_path
end


local function get_active_subtitle_track_path(secondary, only_external)
    track_selected_val = secondary and '1' or '0'
    only_external = only_external == true

    local sub_track_path
    local tracks_count = mp.get_property_number('track-list/count')

    for i = 0, (tracks_count - 1) do
        local track_type = mp.get_property(string.format('track-list/%d/type', i))
        local track_selected = mp.get_property(string.format('track-list/%d/selected', i))
        local track_selected_main = mp.get_property(string.format('track-list/%d/main-selection', i))

        if track_type == 'sub' and track_selected == 'yes' and track_selected_main == track_selected_val then
            sub_track_path = mp.get_property(string.format('track-list/%d/external-filename', i))
            if sub_track_path == nil and not(only_external) then
                local track_ff_index = mp.get_property(string.format('track-list/%d/ff-index', i))
                local track_codec = mp.get_property(string.format('track-list/%d/codec', i))
                sub_track_path = string.format('%s*%s', track_ff_index, track_codec)
            end
            break
        end
    end

    return sub_track_path
end


local function get_active_audio_tack()
    local tracks_count = mp.get_property_number('track-list/count')

    for i = 0, (tracks_count - 1) do
        local track_type = mp.get_property(string.format('track-list/%d/type', i))
        local track_selected = mp.get_property(string.format('track-list/%d/selected', i))
        local track_id = mp.get_property(string.format('track-list/%d/id', i))
        local track_ext_path = mp.get_property(string.format('track-list/%d/external-filename', i))

        if track_type == 'audio' and track_selected == 'yes' and track_id and track_ext_path == nil then
            return track_id
        end
    end

    return '-1'
end


local function is_sub_codec_supported(codec)
    local supported = { 'subrip', 'ass' }
    for _, v in pairs(supported) do
        if v == codec then return true end
    end
    return false
end


local function get_retime_sync_source_list()

    local tracks_count = mp.get_property_number('track-list/count')

    local ret = {}

    for i = 0, (tracks_count - 1) do
        local track_selected = mp.get_property_native(string.format('track-list/%d/selected', i))
        local track_type = mp.get_property(string.format('track-list/%d/type', i))
        local track_codec = mp.get_property(string.format('track-list/%d/codec', i))

        if track_type == 'audio' or (track_type == 'sub' and not(track_selected) and is_sub_codec_supported(track_codec)) then
            local track_id = mp.get_property(string.format('track-list/%d/id', i))
            local track_title = mp.get_property(string.format('track-list/%d/title', i))
            local track_lang = mp.get_property(string.format('track-list/%d/lang', i))

            local desc

            if track_type == 'audio' then
                desc = 'Audio'
            else
                desc = 'Subtitle'
            end

            if track_title == nil then
                track_title = mp.get_property(string.format('track-list/%d/external-filename', i))
                if track_title == nil then
                    track_title = 'No Title'
                end
            end

            desc = desc .. ' Track ' .. track_id .. ': ' .. track_title

            if track_lang then
                desc = desc .. ' (' .. track_lang .. ')'
            end

            local track_path = mp.get_property(string.format('track-list/%d/external-filename', i))
            local track_ff_id

            if track_path == nil then
                track_path = mp.get_property('path')
                local track_id = mp.get_property_native(string.format('track-list/%d/id', i)) - 1
                local ff_type = 'a'
                if track_type == 'sub' then ff_type = 's' end
                track_ff_id = string.format('%s:%d', ff_type, track_id)
            else
                track_ff_id = 's:0'
            end

            table.insert(ret, { txt = desc, path = track_path, ff_id = track_ff_id })
        end
    end

    return ret
end


local function on_initialize()
    -- get ipc handle
    ipc_handle = get_ipc_handle()

    if ipc_handle == nil then
        mp.osd_message('ERROR: Getting mpv handle failed.')
        return
    end

    local cwd_path = mp.get_script_directory()

    -- launch server

    local dev_flag_path = cwd_path .. '/dev_flag'

    -- Check if dev flag is present. In that case the server is launched manually
    if file_exists(dev_flag_path) then
        mp.msg.info('IPC available: ' .. ipc_handle)
        return
    end

    local cmd_args = {}

    local script_path = cwd_path .. '/migaku_mpv.py'

    local venv_path = cwd_path .. '/.venv/bin'
    -- Run as py script if exists
    if file_exists(script_path) then
        mp.msg.info('Starting Migaku mpv server (script)')

        -- Attempt to run with virtual environment if possible
        if file_exists(venv_path) then
            cmd_args = { venv_path .. '/python3', script_path }
        else
            cmd_args = { 'python3', script_path }
        end
    -- Otherwise try binary
    else
        mp.msg.info('Starting Migaku mpv server (binary)')
        local script_command = mp.get_script_directory() .. '/migaku_mpv'
        cmd_args = { script_command }
    end

    table.insert(cmd_args, ipc_handle)
    
    mp.command_native_async(
        { name = 'subprocess', args = cmd_args, playback_only = false, capture_stderr = true },
        function(res, val, err)
            mp.osd_message('The Migaku plugin shut down.\n\n' ..
                           'If you think this is an error please submit a bug report and attach log.txt from the plugin directory.\n\n' ..
                           'Thank you!\n\n' ..
                           'Also note that you can only use the Migaku plugin from one mpv instance at a time.',
                           15.0)
        end
    )
end


local function on_subtitle(property, value)
    -- ignore subtitle clear callbacks
    if value == nil or value == "" then
        return
    end
    
    -- Pause in reading mode
    if sub_mode == SubMode.Reading then
        mp.set_property_native('pause', true)
    end

    -- Setup time for recall mode
    if sub_mode  == SubMode.Recall then
        sub_pause_time = mp.get_property_number('sub-end') + mp.get_property_number('sub-delay')
    end

    -- Fetch and send current subtitle start to script
    local sub_start = mp.get_property_number('sub-start')
    if sub_start == nil then
        return
    end

    mp.commandv('script-message', '@migaku', 'sub-start', sub_start)
end


local function on_time_pos_change(property, value)
    if value == nil or sub_pause_time == nil then
        return
    end

    if sub_mode ~= SubMode.Recall then
        sub_pause_time = nil
        return
    end

    local sub_show_window_start = sub_pause_time - 0.125
    local pause_window_start = sub_pause_time - 0.075
    local window_end = sub_pause_time
    
    -- Workaround: OSD sometimes isn't properly updated when pausing, so show subs a bit earlier
    if value > sub_show_window_start and value <= window_end then
        mp.set_property_native('sub-visibility', true)
    end

    if value > pause_window_start and value <= window_end then
        mp.set_property_native('pause', true)
        sub_pause_time = nil
    end
end


local function on_pause_change(name, value)
    if sub_mode == SubMode.Recall then
        mp.set_property_native('sub-visibility', value)
    end
end


local function remove_parsed_subtitles(only_inactive)
    local tracks_count = mp.get_property_number('track-list/count')

    for i = (tracks_count - 1), 0, -1 do
        local track_selected = mp.get_property_native(string.format('track-list/%d/selected', i))
        local track_type = mp.get_property(string.format('track-list/%d/type', i))
        if (only_inactive == false or track_selected == false) and track_type == 'sub' then
            local track_path = mp.get_property(string.format('track-list/%d/external-filename', i))
            if track_path ~= nil then
                if string.find(track_path, 'migaku_parsed_') then
                    local track_id = mp.get_property(string.format('track-list/%d/id', i))
                    mp.commandv('sub-remove', track_id)
                end
            end                
        end
    end
end


local function on_script_message(cmd, ...)
    if cmd == 'remove_inactive_parsed_subs' then
        remove_parsed_subtitles(true)

    elseif cmd == 'sub_mode' then
        mode_str = ...
        mode_str = mode_str:lower()

        if mode_str == 'reading' then
            sub_mode = SubMode.Reading
            mp.set_property_native('sub-visibility', true)
        elseif mode_str == 'recall' then
            sub_mode = SubMode.Recall
            mp.set_property_native('sub-visibility', false)
        elseif mode_str == 'hidden' then
            sub_mode = SubMode.Hidden
            mp.set_property_native('sub-visibility', false)
        else
            sub_mode = SubMode.Default
            mp.set_property_native('sub-visibility', true)
        end
    end
end


local function on_migaku_open()
    -- get subtitle path
    local sub_path = get_active_subtitle_track_path(false)
    if sub_path == nil then
        sub_path = ''
    end

    -- get secondary subtitle path
    local secondary_sub_path = get_active_subtitle_track_path(true)
    if secondary_sub_path == nil then
        secondary_sub_path = ''
    end

    -- get playing file
    local file_name = mp.get_property('path')
    if file_name == nil or file_name == '' then
        return
    end

    -- get current audio track (only supports internal audio)
    local audio_track = get_active_audio_tack()

    -- get sub delay
    local sub_delay = mp.get_property('sub-delay')

    -- get media resolution
    local resx = mp.get_property('video-params/w')
    local resy = mp.get_property('video-params/h')

    -- get mpv cwd
    local cwd = utils.getcwd()

    -- get mpv pid
    local pid = utils.getpid()

    mp.commandv('script-message', '@migaku', 'open', cwd, pid, file_name, audio_track, sub_path, secondary_sub_path, sub_delay, resx, resy)
end


resync_menu = SelectionMenu:create('Select track to sync current subtitles to:', {}, 26, 32)

local function on_resync_menu_confirm(entry)
    mp.commandv('script-message', '@migaku', 'resync', resync_menu.resync_external_sub, entry.path, entry.ff_id)
end

resync_menu.on_confirm = on_resync_menu_confirm

local function on_migaku_resync()
    local external_sub = get_active_subtitle_track_path(false, true)

    if external_sub == nil then
        mp.osd_message('Select an external subtitle you want to resync.')
        return
    end

    entries = get_retime_sync_source_list()

    if #entries < 1 then
        mp.osd_message('No tracks audio or subtitle tracks were found for resyncing.')
        return
    end

    resync_menu.resync_external_sub = external_sub
    resync_menu:set_entries(entries)
    resync_menu:open()
end


local function on_mouse_move(name, value)
    local secondary_subs_enabled = value['hover']

    if secondary_subs_enabled then
        local y = value['y']
        local h = mp.get_property_native('osd-dimensions/h')

        local pos = y/h;

        secondary_subs_enabled = pos < secondary_sub_area
    end

    mp.set_property_native('secondary-sub-visibility', secondary_subs_enabled)
end


local function get_auto_secondary_sid()
    local tracks_count = mp.get_property_number('track-list/count')

    for _, lang in pairs(secondary_sub_langs) do
        -- first try external, then internal sub tracks
        for check_internal = 0, 1 do
            for i = 0, (tracks_count - 1) do
                local track_type = mp.get_property(string.format('track-list/%d/type', i))
                if track_type == 'sub' then
                    sub_track_path = mp.get_property(string.format('track-list/%d/external-filename', i))
                    if (sub_track_path == nil) == (check_internal == 1) then
                        local track_id = mp.get_property(string.format('track-list/%d/id', i))
                        local track_lang = mp.get_property(string.format('track-list/%d/lang', i))
                        if track_lang == lang then
                            return track_id
                        end
                    end
                end
            end
        end
    end

    return nil
end


local function on_loaded()
    local secondary_sid = get_auto_secondary_sid()
    if secondary_sid ~= nil then
        mp.set_property('secondary-sid', secondary_sid)
    end
end



mp.observe_property('sub-text', 'string', on_subtitle)
mp.observe_property('time-pos', 'number', on_time_pos_change)
mp.observe_property('pause', 'bool', on_pause_change)
mp.observe_property('mouse-pos', 'native', on_mouse_move)
mp.register_event('file-loaded', on_loaded)
mp.register_script_message('@migakulua', on_script_message)
mp.add_key_binding('b', 'migaku-open', on_migaku_open)
mp.add_key_binding('B', 'migaku-resync', on_migaku_resync)

on_initialize()

-- Init play_url
require('modules.play_url')
