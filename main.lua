local utils = require('mp.utils')
local SelectionMenu = require('modules.selectionmenu')


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


local function get_active_subtitle_track_path(only_external)
    only_external = only_external == true

    local sub_track_path
    local tracks_count = mp.get_property_number('track-list/count')

    for i = 1, tracks_count do
        local track_type = mp.get_property(string.format('track-list/%d/type', i))
        local track_selected = mp.get_property(string.format('track-list/%d/selected', i))

        if track_type == 'sub' and track_selected == 'yes' then
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

    for i = 1, tracks_count do
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

    for i = 1, tracks_count do
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
                    track_title = 'Unknown Track'
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


    -- launch server

    local dev_flag_path = mp.get_script_directory() .. '/dev_flag'

    -- Check if dev flag is present. In that case the server is launched manually
    if file_exists(dev_flag_path) then
        mp.msg.info('IPC available: ' .. ipc_handle)
        return
    end

    local cmd_args = {}

    local script_path = mp.get_script_directory() .. '/migaku_mpv.py'

    -- Run as py script if exists
    if file_exists(script_path) then
        mp.msg.info('Starting Migaku mpv server (script)')
        cmd_args = { 'python', script_path }

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
    if value == nil then
        return
    end

    -- fetch and send current subtitle start to script
    local sub_start = mp.get_property_number('sub-start')
    if sub_start == nil then
        return
    end

    mp.commandv('script-message', '@migaku', 'sub-start', sub_start)
end


local function on_migaku_open()
    -- get subtitle path
    local sub_path = get_active_subtitle_track_path()
    if sub_path == nil then
        sub_path = ''
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

    -- get mpv cwd
    local cwd = utils.getcwd()

    -- get mpv pid
    local pid = utils.getpid()

    mp.commandv('script-message', '@migaku', 'open', cwd, pid, file_name, audio_track, sub_path, sub_delay)
end


resync_menu = SelectionMenu:create('Select track to sync current subtitles to:', {}, 26, 32)

local function on_resync_menu_confirm(entry)
    mp.commandv('script-message', '@migaku', 'resync', resync_menu.resync_external_sub, entry.path, entry.ff_id)
end

resync_menu.on_confirm = on_resync_menu_confirm

local function on_migaku_resync()
    local external_sub = get_active_subtitle_track_path(true)

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



mp.observe_property('sub-text', 'string', on_subtitle)
mp.add_key_binding('b', 'migaku-open', on_migaku_open)
mp.add_key_binding('B', 'migaku-resync', on_migaku_resync)

on_initialize()
