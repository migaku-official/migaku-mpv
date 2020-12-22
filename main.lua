local utils = require("mp.utils")


local function file_exists(name)
    local f=io.open(name, "r")
    if f~=nil then
        io.close(f)
        return true
    else
        return false
    end
end
 

local function get_ipc_handle()
    local ipc_handle_path = mp.get_property('input-ipc-server')

    if ipc_handle_path == '' or ipc_handle_path == nil then
        local new_ipc_handle_path = mp.get_script_directory() .. '/mpv-ipc-handle'
        mp.set_property('input-ipc-server', new_ipc_handle_path)
        ipc_handle_path = mp.get_property('input-ipc-server')
    end

    if ipc_handle_path == '' then
        return nil
    end

    return ipc_handle_path
end


local function get_active_subtitle_track_path()
    local sub_track_path
    local tracks_count = mp.get_property_number("track-list/count")

    for i = 1, tracks_count do
        local track_type = mp.get_property(string.format("track-list/%d/type", i))
        local track_selected = mp.get_property(string.format("track-list/%d/selected", i))

        if track_type == "sub" and track_selected == "yes" then
            sub_track_path = mp.get_property(string.format("track-list/%d/external-filename", i))
            if sub_track_path == nil then
                local track_ff_index = mp.get_property(string.format("track-list/%d/ff-index", i))
                local track_codec = mp.get_property(string.format("track-list/%d/codec", i))
                sub_track_path = string.format("%s*%s", track_ff_index, track_codec)
            end
            break
        end
    end

    return sub_track_path
end


local function get_active_audio_tack()
    local tracks_count = mp.get_property_number("track-list/count")

    for i = 1, tracks_count do
        local track_type = mp.get_property(string.format("track-list/%d/type", i))
        local track_selected = mp.get_property(string.format("track-list/%d/selected", i))
        local track_id = mp.get_property(string.format("track-list/%d/id", i))
        local track_ext_path = mp.get_property(string.format("track-list/%d/external-filename", i))

        if track_type == "audio" and track_selected == "yes" and track_id and track_ext_path == nil then
            return track_id
        end
    end

    return "-1"
end


local function on_initialize()
    -- get ipc handle
    ipc_handle = get_ipc_handle()

    if ipc_handle == nil then
        mp.osd_message('ERROR: Getting mpv handle failed.')
        return
    end


    -- launch server
    local dev_script_path = mp.get_script_directory() .. "/migaku_mpv.py"

    if file_exists(dev_script_path) then
        return  --- in dev mode the script is run manually from a terminal
    end

    mp.msg.info('Starting Migaku mpv server')
    local script_command = mp.get_script_directory() .. "/migaku_mpv"
    local cmd_args = { script_command, ipc_handle }
    
    mp.command_native_async(
        { name = 'subprocess', args = cmd_args, playback_only = false, capture_stderr = true },
        function(res, val, err)
            mp.osd_message('The Migaku plugin shut down.\n\n' ..
                           'Note that you can only use the Migaku plugin from one mpv instance at a time.\n\n' ..
                           'If you think this is an error please submit a bug report and attach log.txt from the plugin directory.\n\n' ..
                           'Thank you!',
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
    local sub_start = mp.get_property_number("sub-start")
    if sub_start == nil then
        return
    end

    mp.commandv('script-message', '@migaku', 'sub-start', sub_start)
end


local function on_migaku_open()
    -- get subtitle path
    local sub_path = get_active_subtitle_track_path()
    if sub_path == nil then
        sub_path = ""
    end

    -- get playing file
    local file_name = mp.get_property("path")
    if file_name == nil or file_name == "" then
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



mp.observe_property('sub-text', 'string', on_subtitle)
mp.add_key_binding('b', 'migaku-open', on_migaku_open)

on_initialize()
