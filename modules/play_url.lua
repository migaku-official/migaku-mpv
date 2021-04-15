local utils = require('mp.utils')


local bin_fmt = package.cpath:match("%p[\\|/]?%p(%a+)")
local os_name = nil;

if bin_fmt == 'dll' then
    os_name = 'windows'
elseif bin_fmt == 'so' then
    os_name = 'linux'
elseif bin_fmt == 'dylib' then
    os_name = 'macos'
end

-- Adapterd from https://github.com/rossy/mpv-repl/blob/master/repl.lua
--
-- © 2016, James Ross-Gowan
--
-- Permission to use, copy, modify, and/or distribute this software for any
-- purpose with or without fee is hereby granted, provided that the above
-- copyright notice and this permission notice appear in all copies.
function get_clipboard_text()
  if os_name == 'linux' then
        local res = utils.subprocess({
			args = { 'xclip', '-selection', 'clipboard', '-out' },
			playback_only = false,
		})
		if not res.error then
			return res.stdout
		end
	elseif os_name == 'windows' then
		local res = utils.subprocess({
			args = { 'powershell', '-NoProfile', '-Command', [[& {
				Trap {
					Write-Error -ErrorRecord $_
					Exit 1
				}
				$clip = ""
				if (Get-Command "Get-Clipboard" -errorAction SilentlyContinue) {
					$clip = Get-Clipboard -Raw -Format Text -TextFormatType UnicodeText
				} else {
					Add-Type -AssemblyName PresentationCore
					$clip = [Windows.Clipboard]::GetText()
				}
				$clip = $clip -Replace "`r",""
				$u8clip = [System.Text.Encoding]::UTF8.GetBytes($clip)
				[Console]::OpenStandardOutput().Write($u8clip, 0, $u8clip.Length)
			}]] },
			playback_only = false,
		})
		if not res.error then
			return res.stdout
		end
	elseif os_name == 'macos' then
		local res = utils.subprocess({
			args = { 'pbpaste' },
			playback_only = false,
		})
		if not res.error then
			return res.stdout
		end
	end
	return ''
end


function url_play(mode)
    local clipboard_text = get_clipboard_text()

    if clipboard_text then
        mp.commandv('loadfile', clipboard_text, mode)
        mp.osd_message('Loading ' .. clipboard_text)
    else
        mp.osd_message('No clipboard contents found.')
    end
end

function url_play_replace() url_play('replace') end
function url_play_append() url_play('append-play') end


mp.add_key_binding('y', 'url_play_replace', url_play_replace)
mp.add_key_binding('Y', 'url_play_append', url_play_append)
