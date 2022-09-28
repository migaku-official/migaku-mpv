local SelectionMenu = {}
SelectionMenu.__index = SelectionMenu


function SelectionMenu:create(title, entries, size, title_size, color, selection_color, title_color)
    local ret = {}
    setmetatable(ret, SelectionMenu)

    ret.ov = mp.create_osd_overlay('ass-events')
    ret.ov.data = ''
    ret.ov:update()

    title = title or 'Select an entry:'
    
    size = size or 24
    title_size = title_size or size
    color = color or 'ffffff'
    selection_color = selection_color or '00ccff'
    title_color = title_color or color

    ret.is_open = false
    ret.header_formatted = string.format('{\\fs%d\\c&%s&}%s\n{\\fs%d\\c&%s&}—————————————————————————————————\n', title_size, title_color, title, size, color)
    ret.line_format = string.format('{\\fs%d\\c&%s&}', size, color)
    ret.line_sel_format = string.format('{\\fs%d\\c&%s&}', size, selection_color)

    ret:set_entries(entries or {})

    ret.on_confirm = function() end
    ret.on_cancel = function() end

    return ret
end

function SelectionMenu:open()
    if self.is_open then
        return
    end

    self:update()
    self:add_keybinds()

    self.is_open = true
end

function SelectionMenu:close()
    if not(self.is_open) then
        return
    end

    self:remove_keybinds()
    self.ov.data = ''
    self.ov:update()

    self.is_open = false
end

function SelectionMenu:set_entries(entries)
    self.entries = entries
    self.max_idx = #entries
    self.idx = 1
end

function SelectionMenu:update()
    local txt = self.header_formatted

    for key, value in pairs(self.entries) do
        if self.idx == key then
            txt = txt .. self.line_sel_format
        else
            txt = txt .. self.line_format
        end
        txt = txt .. value.txt .. '\n'
    end

    self.ov.data = txt
    self.ov:update()
end

function SelectionMenu:add_keybinds()
    mp.add_forced_key_binding('enter', 'menu-confirm', function() self:on_key_confirm() end)
    mp.add_forced_key_binding('esc',   'menu-exit',    function() self:on_key_exit() end)
    mp.add_forced_key_binding('up',    'menu-up',      function() self:on_key_up() end)
    mp.add_forced_key_binding('down',  'menu-down',    function() self:on_key_down() end)
end

function SelectionMenu:remove_keybinds()
    mp.remove_key_binding('menu-confirm')
    mp.remove_key_binding('menu-exit')
    mp.remove_key_binding('menu-up')
    mp.remove_key_binding('menu-down')
end

function SelectionMenu:on_key_confirm()
    self:close()
    self.on_confirm(self.entries[self.idx])
end

function SelectionMenu:on_key_exit()
    self:close()
    self.on_cancel()
end

function SelectionMenu:on_key_up()
    self.idx = self.idx - 1
    if self.idx < 1 then self.idx = self.max_idx end
    self:update()
end

function SelectionMenu:on_key_down()
    self.idx = self.idx + 1
    if self.idx > self.max_idx then self.idx = 1 end
    self:update()
end


return SelectionMenu
