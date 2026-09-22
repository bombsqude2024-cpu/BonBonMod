# ba_meta require api 9

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, Generic, cast

import re, string
import logging
import os
import math, weakref, threading, time
import babase
import bauiv1 as bui
import bascenev1 as bs
from bauiv1lib.popup import PopupMenuWindow, PopupWindow
from bauiv1lib.confirm import ConfirmWindow
from bauiv1lib.colorpicker import ColorPickerExact
from bauiv1lib.mainmenu import MainMenuWindow
from typing import List, Tuple, Sequence, Optional, Dict, Any, Union, TYPE_CHECKING, cast
import bauiv1lib.party

def client_to_account(client_id):
    rost = bs.get_game_roster()
    for i in rost:
        if i['client_id'] == client_id:
            return i['account_id']
    return ''

def client_to_display_string(client_id):
    rost = bs.get_game_roster()
    for i in rost:
        if i['client_id'] == client_id:
            return i['display_string']
    return ''

def client_to_player(client_id):
    rost = bs.get_game_roster()
    for i in rost:
        if i['client_id'] == client_id:
            if len(i['players']) >= 1:
                return i['players'][0]['name_full']
            return i['display_string']
    return ''

config = babase.app.config
if 'Chat Muted' not in config:
    config['Chat Muted'] = False
if 'Party Chat Muted' not in config:
    config['Party Chat Muted'] = False

quick_msg_file = babase.env()['python_directory_user'] + '/QuickMessages.txt'

_ip = '127.0.0.1'
_port = 43210
_ping = '-'

_light_yellow_ = (1.0, 0.93, 0.75)

def get_msg_type(msg):
    if msg.startswith(bui.charstr(bui.SpecialChar.PARTY_ICON) + ' :'):
        return 'server message'
    elif msg.startswith(bui.charstr(bui.SpecialChar.DICE_BUTTON1) + bui.charstr(bui.SpecialChar.PARTY_ICON) + ' :'):
        return 'private info'
    elif msg.startswith(bui.charstr(bui.SpecialChar.DICE_BUTTON2)):
        return 'private message'
    elif msg.startswith(bui.charstr(bui.SpecialChar.DICE_BUTTON3)):
        return 'private chat message'
    elif msg.startswith(bui.charstr(bui.SpecialChar.PARTY_ICON) + '['):
        return 'transit message'
    elif client_to_player(-1) != '' and msg.startswith(client_to_player(-1)):
        return 'server message'
    msg_bgn = msg.find(': ') + 2
    if msg[msg_bgn:].startswith('          | '):
        return 'replied message'
    elif msg[msg_bgn:].startswith('/'):
        return 'player command'
    return 'normal message'

def set_correct_msg_color(msg_type):
    if msg_type == 'server message':
        return (1.0, 0.9, 0.7)
    elif msg_type == 'private info':
        return (1.0, 0.2, 0.7)
    elif msg_type == 'private message':
        return (0.6, 0.4, 0.3)
    elif msg_type == 'private chat message':
        return (0.8, 1.0, 0.5)
    elif msg_type == 'transit message':
        return (1.0, 0.7, 0.85)
    elif msg_type == 'replied message':
        return (0.3, 0.7, 1.0)
    #elif msg_type == 'player command':
        #return (0.9, 1.0, 1.0)
        #return (0.5, 0.0, 0.2)
    else:
        return (0.85, 0.85, 0.85)

def split_msg(msg):
    lines = []
    if len(msg) > 48:
        index = msg[:40].rfind(' ')
        if index >= 24:
            lines.append(msg[:index])
            msg = msg[index + 1:]
    if len(msg) > 48:
        index = msg[:40].rfind(' ')
        if index >= 24:
            lines.append(msg[:index])
            msg = msg[index + 1:]
    lines.append(msg)
    return lines

class PartyWindow(bui.Window):
    """Party list/chat window."""

    def __del__(self) -> None:
        None

    def __init__(self, origin: Sequence[float] = (0, 0)):
        self.ping_server()
        None
        self._r = 'partyWindow'
        self._popup_type: Optional[str] = None
        self._popup_party_member_client_id: Optional[int] = None
        self._popup_party_member_is_host: Optional[bool] = None
        self._width = 500 * 1.1
        uiscale = bui.app.ui_v1.uiscale
        self._height = (365 if uiscale is bui.UIScale.SMALL else
                        480 if uiscale is bui.UIScale.MEDIUM else 600)
        self.bg_color = (0.08, 0.07, 0.1)
        self.ping_timer = bui.AppTimer(5, babase.WeakCall(self.ping_server), repeat=True)

        bui.Window.__init__(self, root_widget=bui.containerwidget(
            size=(self._width, self._height),
            transition='in_scale',
            color=self.bg_color,
            parent=bui.get_special_widget('overlay_stack'),
            on_outside_click_call=self.close_with_sound,
            scale_origin_stack_offset=origin,
            scale=(2.0 if uiscale is bui.UIScale.SMALL else
                   1.35 if uiscale is bui.UIScale.MEDIUM else 1.0),
            stack_offset=(0, -10) if uiscale is bui.UIScale.SMALL else (
                240, 0) if uiscale is bui.UIScale.MEDIUM else (330, 20)))

        self._cancel_button = bui.buttonwidget(parent=self._root_widget,
                                              scale=0.7,
                                              position=(30, self._height - 47),
                                              size=(50, 50),
                                              label='',
                                              on_activate_call=self.close,
                                              autoselect=True,
                                              color=self.bg_color,
                                              icon=bui.gettexture('crossOut'),
                                              iconscale=1.2)
        bui.containerwidget(edit=self._root_widget,
                           cancel_button=self._cancel_button)

        self._menu_button = bui.buttonwidget(
            parent=self._root_widget,
            scale=0.7,
            position=(self._width - 60, self._height - 47),
            size=(50, 50),
            label='...',
            textcolor=_light_yellow_,
            autoselect=True,
            button_type='square',
            on_activate_call=babase.WeakCall(self._on_menu_button_press),
            color=self.bg_color,
            iconscale=1.2)

        info = bs.get_connection_to_host_info()
        if info.get('name', '') != '':
            title = bui.Lstr(value=info['name'])
        else:
            title = bui.Lstr(resource=self._r + '.titleText')

        self._title_text = bui.textwidget(parent=self._root_widget,
                                         scale=0.9,
                                         color=_light_yellow_,
                                         text=title,
                                         size=(0, 0),
                                         position=(self._width * 0.5,
                                                   self._height - 29),
             maxwidth=self._width * 0.7,
                                         h_align='center',
                                         v_align='center')

        self._ping_button = None
        if info.get('name', '') != '':
            self._ping_button = bui.buttonwidget(
                parent=self._root_widget,
                scale=0.7 * 0.7,
                position=(self._width - 538 - 50, self._height - 57),
                size=(75 * 0.7, 75 * 0.7),
                autoselect=True,
                button_type='square',
                label='',
                textcolor=_light_yellow_,
                #on_activate_call=babase.WeakCall(self._on_menu_button_press),
                color=self.bg_color,
                iconscale=1.2)

            self._ping_text = bui.textwidget(parent=self._root_widget,
                                        scale=1.3 * 0.7,
                                        color=self._get_ping_color(),
                                        text=f'{_ping}',
                                        size=(30 * 0.7, 30 * 0.7),
                                        position=(self._width - 538 - 50, self._height - 57),
                                        maxwidth=self._width * 0.7,
                                        selectable=True,
                                        autoselect=True,
                                        click_activate=True,
                                        on_activate_call=self._send_ping,
                                        h_align='center',
                                        v_align='center')
            self._ip_port_button = bui.buttonwidget(parent=self._root_widget,
                                  size=(30 * 0.7, 30 * 0.7),
                                  scale=0.7,
                                  label='IP',
                                  textcolor=_light_yellow_,
                                  button_type='square',
                                  autoselect=True,
                                  color=self.bg_color,
                                  position=(self._width - 530 - 50, self._height - 100),
                                  on_activate_call=self._ip_port_msg)
        else:
            self._ping_text = None
        
        self._empty_str = bui.textwidget(parent=self._root_widget,
                                        scale=0.75,
                                        size=(0, 0),
                                        position=(self._width * 0.5,
                                                  self._height - 65),
                                        maxwidth=self._width * 0.85,
                                        h_align='center',
                                        v_align='center')

        self._scroll_width = self._width - 50
        self._scrollwidget = bui.scrollwidget(parent=self._root_widget,
                                             size=(self._scroll_width,
                                                   self._height - 200 - 20),
                                             position=(30, 80 + 20),
                                             color=(0.4, 0.6, 0.3))
        self._columnwidget = bui.columnwidget(parent=self._scrollwidget,
                                             border=2,
                                             margin=0)
        bui.widget(edit=self._menu_button, down_widget=self._columnwidget)

        self._muted_text = bui.textwidget(
            parent=self._root_widget,
            position=(self._width * 0.5, self._height * 0.5),
            size=(0, 0),
            h_align='center',
            v_align='center',
            text=bui.Lstr(resource='chatMutedText'))
        self._chat_texts: List[bui.Widget] = []

        # add all existing messages if chat is not muted
        if not babase.app.config['Party Chat Muted']:
            msgs = bs.get_chat_messages()
            for msg in msgs:
                self._add_msg(msg)

        self._text_field = txt = bui.textwidget(
            parent=self._root_widget,
            editable=True,
            size=(550, 40),
            position=(74, 39),
            text='',
            maxwidth=494,
            shadow=0.3,
            flatness=1.0,
            description=bui.Lstr(resource=self._r + '.chatMessageText'),
            autoselect=True,
            v_align='center',
            corner_scale=0.7)

        bui.widget(edit=self._scrollwidget,
                  autoselect=True,
                  left_widget=self._cancel_button,
                  up_widget=self._cancel_button,
                  down_widget=self._text_field)
        bui.widget(edit=self._columnwidget,
                  autoselect=True,
                  up_widget=self._cancel_button,
                  down_widget=self._text_field)
        bui.containerwidget(edit=self._root_widget, selected_child=txt)
        self._send_button = btn = bui.buttonwidget(parent=self._root_widget,
                              size=(50, 35),
                              label=bui.Lstr(resource=self._r + '.sendText'),
                              textcolor=_light_yellow_,
                              button_type='square',
                              autoselect=True,
                              color=self.bg_color,
                              position=(self._width - 70, 35),
                              on_activate_call=self._send_chat_message)
        bui.textwidget(edit=txt, on_return_press_call=btn.activate)
        self._previous_button = bui.buttonwidget(parent=self._root_widget,
                              size=(18, 18),
                              label=bui.charstr(bui.SpecialChar.UP_ARROW),
                              textcolor=_light_yellow_,
                              button_type='square',
                              autoselect=True,
                              position=(38, 57),
                              color=self.bg_color,
                              on_activate_call=self._previous_message)
        self._next_button = bui.buttonwidget(parent=self._root_widget,
                              size=(18, 18),
                              label=bui.charstr(bui.SpecialChar.DOWN_ARROW),
                              textcolor=_light_yellow_,
                              button_type='square',
                              autoselect=True,
                              color=self.bg_color,
                              position=(38, 28),
                              on_activate_call=self._next_message)
        self._reply_button = bui.buttonwidget(parent=self._root_widget,
                              size=(20, 12),
                              scale=1.1,
                              label='reply',
                              textcolor=_light_yellow_,
                              button_type='square',
                              autoselect=True,
                              color=self.bg_color,
                              position=(-0.1 * self._width + 20, 80),
                              on_activate_call=self._reply_to_message)
        self._copy_button = bui.buttonwidget(parent=self._root_widget,
                              size=(20, 15),
                              label='copy',
                              textcolor=_light_yellow_,
                              button_type='square',
                              autoselect=True,
                              color=self.bg_color,
                              position=(-0.1 * self._width + 10, 52),
                              on_activate_call=self._copy_to_clipboard)
        self._reverse_button = bui.buttonwidget(parent=self._root_widget,
                              size=(25, 7),
                              scale=1.5,
                              label='reverse',
                              textcolor=_light_yellow_,
                              button_type='square',
                              autoselect=True,
                              color=self.bg_color,
                              position=(-0.1 * self._width + 10, 30),
                              on_activate_call=self._reverse_message)

        self._replied_message = bui.textwidget(
            parent=self._root_widget,
            size=(550, 40),
            position=(59, 59),
            text='',
            color=(0.45, 0.7, 0.85),
            scale=0.7,
            maxwidth=494,
            shadow=0.3,
            flatness=1.0,
            description=bui.Lstr(resource=self._r + '.chatMessageText'),
            autoselect=True,
            v_align='center',
            h_align='left',
            corner_scale=0.7)
        self._replied_message_cancel_button = None

        self._name_widgets: List[bui.Widget] = []
        self._roster: Optional[List[Dict[str, Any]]] = None
        self._update_timer = bui.AppTimer(1.0,
                                      babase.WeakCall(self._update),
                                      repeat=True)
        self._update()

    def on_chat_message(self, msg: str) -> None:
        """Called when a new chat message comes through."""
        if not babase.app.config['Party Chat Muted']:
            self._add_msg(msg)

    def _add_msg(self, msg: str) -> None:
        clr = set_correct_msg_color(get_msg_type(msg))
        txt = bui.textwidget(parent=self._columnwidget,
                            text=msg,
                            color=clr,
                            h_align='left',
                            v_align='center',
                            size=(0, 13),
                            scale=0.55,
                            maxwidth=self._scroll_width * 0.94,
                            shadow=0.3,
                            flatness=1.0)
        self._chat_texts.append(txt)
        if len(self._chat_texts) > 40:
            first = self._chat_texts.pop(0)
            first.delete()
            if hasattr(self, 'msg_index'):
                self.msg_index -= 1
                if self.msg_index == -1:
                    self._next_message()
                    
        bui.containerwidget(edit=self._columnwidget, visible_child=txt)

    def _on_menu_button_press(self) -> None:
        is_muted = babase.app.config['Party Chat Muted']
        uiscale = bui.app.ui_v1.uiscale
        
        choices = ['muteChat', 'addQuickReply', 'removeQuickReply']
        choices_display = ['mute chat', 'add as quick reply', 'remove a quick reply']            
        PopupMenuWindow(
            position=self._menu_button.get_screen_space_center(),
            color=self.bg_color,
            scale=(2.3 if uiscale is bui.UIScale.SMALL else
                   1.65 if uiscale is bui.UIScale.MEDIUM else 1.23),
            choices=choices,
            choices_display= self._create_baLstr_list(choices_display),
            current_choice='muteOption',
            delegate=self)
        self._popup_type = 'menu'

    def _on_party_member_press(self, client_id: int, is_host: bool,
                               widget: bui.Widget) -> None:
        # if we're the host, pop up 'kick' options for all non-host members
        if bs.get_foreground_host_session() is not None:
            kick_str = bui.Lstr(resource='kickText')
        else:
            kick_str = bui.Lstr(resource='kickVoteText')
        uiscale = bui.app.ui_v1.uiscale
        account_name = client_to_display_string(client_id)
        player_name = client_to_player(client_id)
        choices = ['account_name', 'client_id']
        choices_display = [bui.Lstr(value=account_name), bui.Lstr(value=str(client_id))]
        if not is_host:
            choices += ['kick']
            choices_display += [kick_str]
        if player_name != account_name:
            choices = ['player_name'] + choices
            choices_display = [bui.Lstr(value=player_name)] + choices_display
        PopupMenuWindow(
            position=widget.get_screen_space_center(),
            color=self.bg_color,
            scale=(2.3 if uiscale is bui.UIScale.SMALL else
                   1.65 if uiscale is bui.UIScale.MEDIUM else 1.23),
            choices=choices,
            choices_display=choices_display,
            current_choice='mention',
            delegate=self)
        self._popup_type = 'partyMemberPress'
        self._popup_party_member_client_id = client_id
        self._popup_party_member_is_host = is_host

    def _update(self) -> None:
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-statements
        # pylint: disable=too-many-nested-blocks

        # update muted state
        if babase.app.config['Party Chat Muted']:
            bui.textwidget(edit=self._muted_text, color=(1, 1, 1, 0.3))
            # clear any chat texts we're showing
            if self._chat_texts:
                while self._chat_texts:
                    first = self._chat_texts.pop()
                    first.delete()
        else:
            bui.textwidget(edit=self._muted_text, color=(1, 1, 1, 0.0))

        if self._ping_text:
            bui.textwidget(edit=self._ping_text,
                          text=f'{_ping}',
                          color=self._get_ping_color())

        # update roster section
        roster = bs.get_game_roster()
        if roster != self._roster:
            self._roster = roster

            # clear out old
            for widget in self._name_widgets:
                widget.delete()
            self._name_widgets = []
            if not self._roster:
                top_section_height = 60
                bui.textwidget(edit=self._empty_str,
                              text=bui.Lstr(resource=self._r + '.emptyText'))
                bui.scrollwidget(edit=self._scrollwidget,
                                size=(self._width - 50,
                                      self._height - top_section_height - 110 - 20),
                                position=(30, 80 + 20))
            else:
                columns = 1 if len(
                    self._roster) == 1 else 2 if len(self._roster) == 2 else 3
                rows = int(math.ceil(float(len(self._roster)) / columns))
                c_width = (self._width * 0.9) / max(3, columns)
                c_width_total = c_width * columns
                c_height = 24
                c_height_total = c_height * rows
                for y in range(rows):
                    for x in range(columns):
                        index = y * columns + x
                        if index < len(self._roster):
                            t_scale = 0.65
                            pos = (self._width * 0.53 - c_width_total * 0.5 +
                                   c_width * x - 23,
                                   self._height - 65 - c_height * y - 15)

                            # if there are players present for this client, use
                            # their names as a display string instead of the
                            # client spec-string
                            try:
                                if self._roster[index]['players']:
                                    # if there's just one, use the full name;
                                    # otherwise combine short names
                                    if len(self._roster[index]
                                           ['players']) == 1:
                                        p_str = self._roster[index]['players'][
                                            0]['name_full']
                                    else:
                                        p_str = ('/'.join([
                                            entry['name'] for entry in
                                            self._roster[index]['players']
                                        ]))
                                        if len(p_str) > 25:
                                            p_str = p_str[:25] + '...'
                                else:
                                    p_str = self._roster[index][
                                        'display_string']
                            except Exception:
                                logging.exception(
                                    'Error calcing client name str.')
                                p_str = '???'

                            widget = bui.textwidget(parent=self._root_widget,
                                                   position=(pos[0], pos[1]),
                                                   scale=t_scale,
                                                   size=(c_width * 0.85, 30),
                                                   maxwidth=c_width * 0.85,
                                                   color=(1.0, 1.0, 1.0) if index == 0 else
                                                   (0.75, 0.8, 0.85),
                                                   selectable=True,
                                                   autoselect=True,
                                                   click_activate=True,
                                                   text=bui.Lstr(value=p_str),
                                                   h_align='left',
                                                   v_align='center')
                            self._name_widgets.append(widget)

                            # in newer versions client_id will be present and
                            # we can use that to determine who the host is.
                            # in older versions we assume the first client is
                            # host
                            if self._roster[index]['client_id'] is not None:
                                is_host = self._roster[index][
                                    'client_id'] == -1
                            else:
                                is_host = (index == 0)

                            # FIXME: Should pass client_id to these sort of
                            #  calls; not spec-string (perhaps should wait till
                            #  client_id is more readily available though).
                            bui.textwidget(edit=widget,
                                          on_activate_call=babase.Call(
                                              self._on_party_member_press,
                                              self._roster[index]['client_id'],
                                              is_host, widget))
                            pos = (self._width * 0.53 - c_width_total * 0.5 +
                                   c_width * x,
                                   self._height - 65 - c_height * y)

                            # Make the assumption that the first roster
                            # entry is the server.
                            # FIXME: Shouldn't do this.
                            if is_host:
                                pass
                bui.textwidget(edit=self._empty_str, text='')
                bui.scrollwidget(edit=self._scrollwidget,
                                size=(self._width - 50,
                                      max(100, self._height - 139 -
                                          c_height_total)),
                                position=(30, 80))

    def popup_menu_selected_choice(self, popup_window: PopupMenuWindow,
                                   choice: str) -> None:
        """Called when a choice is selected in the popup."""
        if self._popup_type == 'partyMemberPress':
            if choice == 'kick':
                account_name = client_to_display_string(self._popup_party_member_client_id)
                ConfirmWindow(text=f'Are you sure to kick {account_name}?',
                                action = self._vote_kick_player,
                                cancel_button=True,
                                cancel_is_selected=True,
                                color=self.bg_color,
                                text_scale=1.0,
                                origin_widget=self.get_root_widget())
            elif choice == 'account_name':
                account_name = client_to_display_string(self._popup_party_member_client_id)
                cur_msg = bui.textwidget(query=self._text_field)
                if cur_msg.endswith(' '):
                    self._edit_text_msg_box(account_name)
                else:
                    self._edit_text_msg_box(' ' + account_name)
            elif choice == 'player_name':
                player_name = client_to_player(self._popup_party_member_client_id)
                cur_msg = bui.textwidget(query=self._text_field)
                if cur_msg.endswith(' '):
                    self._edit_text_msg_box(player_name)
                else:
                    self._edit_text_msg_box(' ' + player_name)
            elif choice == 'client_id':
                cur_msg = bui.textwidget(query=self._text_field)
                if cur_msg.endswith(' '):
                    self._edit_text_msg_box(str(self._popup_party_member_client_id))
                else:
                    self._edit_text_msg_box(' ' + str(self._popup_party_member_client_id))

        elif self._popup_type == 'menu':
            if choice == 'muteChat':
                current_choice = self._get_current_mute_type()
                PopupMenuWindow(
                    position = (self._width - 60, self._height - 47),
                    color=self.bg_color,
                    scale=self._get_popup_window_scale(),
                    choices=['muteAll', 'unmuteAll'],
                    choices_display=self._create_baLstr_list(['mute all', 'unmute all']),
                    current_choice=current_choice,
                    delegate=self
             )
                self._popup_type = 'muteType'
            elif choice == 'addQuickReply':
                try:
                    newReply = bui.textwidget(query=self._text_field)
                    oldReplies = self._get_quick_responds()
                    oldReplies.append(newReply)
                    self._write_quick_responds(oldReplies)
                    bui.screenmessage(f'"{newReply}" is added.', (0,1,0))
                    bui.getsound('dingSmallHigh').play()
                except:
                    logging.exception()
            elif choice == 'removeQuickReply':
                quick_reply = self._get_quick_responds()
                PopupMenuWindow(position=self._send_button.get_screen_space_center(),
                                color=self.bg_color,
                                scale=self._get_popup_window_scale(),
                                choices=quick_reply,
                                choices_display=self._create_baLstr_list(quick_reply),
                                current_choice=quick_reply[0],
                                delegate=self)
                self._popup_type = 'removeQuickReplySelect'
            elif choice == 'credits':
                ConfirmWindow(text=u'\ue043Ultra Pro Maxx ++ Party Window',
                                action = self.join_discord,
                                width=420,
                                height=230,
                                color=self.bg_color,
                                text_scale=1.0,
                                ok_text="Join Discord",
                                origin_widget=self.get_root_widget())
                    
        elif self._popup_type == 'muteType':
            self._change_mute_type(choice)

        elif self._popup_type == 'quickMessage':
            self._edit_text_msg_box(choice)

        elif self._popup_type == 'removeQuickReplySelect':
            data = self._get_quick_responds()
            data.remove(choice)
            self._write_quick_responds(data)
            bui.screenmessage(f'"{choice}" is removed.', (1,0,0))
            bui.getsound('shieldDown').play()

        else:
            print(f'unhandled popup type: {self._popup_type}')
        del popup_window  # unused

    def _vote_kick_player(self):
        if self._popup_party_member_is_host:
            bui.getsound('error').play()
            bui.screenmessage(
                bui.Lstr(resource='internal.cantKickHostError'),
                color=(1, 0, 0))
        else:
            assert self._popup_party_member_client_id is not None

            # Ban for 5 minutes.
            result = bs.disconnect_client(
                self._popup_party_member_client_id, ban_time=60 * 60)
            if not result:
                bui.getsound('error').play()
                bui.screenmessage(
                    bui.Lstr(resource='getTicketsWindow.unavailableText'),
                    color=(1, 0, 0))

    def _copy_to_clipboard(self):
        msg = bui.textwidget(query=self._text_field)
        if msg == '':
            bui.getsound('error').play()
        else:
            bui.clipboard_set_text(msg)
            bui.screenmessage('text copied to clipboard', (0,1,0))
            bui.getsound('dingSmallHigh').play()
            self._edit_text_msg_box(msg, 'replace')

    def _reverse_message(self):
        msg = bui.textwidget(query=self._text_field)
        msg2 = ''
        for i in range(len(msg)):
        	msg2 = msg[i:i+1] + msg2
        msg = msg2
        if msg == '':
            pass
        else:
            bui.getsound('dingSmallHigh').play()
            self._edit_text_msg_box(msg, 'replace')

    def _reply_to_message(self):
        msgs = bs.get_chat_messages()
        if hasattr(self, 'msg_index'):
            msg = msgs[self.msg_index]
        else:
            msg = bui.textwidget(query=self._text_field)
        if msg.startswith(bui.charstr(bui.SpecialChar.RIGHT_ARROW)):
            msg = msg[1:]
        if msg != '':
            bui.textwidget(edit=self._replied_message,
                          text=msg)
            self._replied_message_cancel_button = bui.buttonwidget(parent=self._root_widget,
                              size=(10, 10),
                              label='x',
                              scale=0.4,
                              textcolor=(0.8, 0.0, 0.0),
                              button_type='square',
                              autoselect=True,
                              position=(107, 77),
                              color=self.bg_color,
                              on_activate_call=self._cancel_replied_message)
            bui.textwidget(edit=self._text_field, text='')

    def _cancel_replied_message(self):
        if self._replied_message_cancel_button != None:
            self._replied_message_cancel_button.delete()
            self._replied_message_cancel_button = None
            bui.textwidget(edit=self._replied_message,
                          text='')

    def _get_current_mute_type(self):
        cfg = babase.app.config
        if cfg['Chat Muted'] == True:
            if cfg['Party Chat Muted'] == True:
                return 'muteAll'
            else:
                return 'muteInGameOnly'
        else:
            if cfg['Party Chat Muted'] == True:
                return 'mutePartyWindowOnly'
            else:
                return 'unmuteAll'

    def _change_mute_type(self, choice):
        cfg = babase.app.config
        if choice == 'muteInGameOnly':
            cfg['Chat Muted'] = True
            cfg['Party Chat Muted'] = False
        elif choice == 'mutePartyWindowOnly':
            cfg['Chat Muted'] = False
            cfg['Party Chat Muted'] = True
        elif choice == 'muteAll':
            cfg['Chat Muted'] = True
            cfg['Party Chat Muted'] = True
        else:
            cfg['Chat Muted'] = False
            cfg['Party Chat Muted'] = False
        cfg.apply_and_commit()
        self._update()

    def popup_menu_closing(self, popup_window: PopupWindow) -> None:
        """Called when the popup is closing."""

    def _send_chat_message(self) -> None:
        msg = bui.textwidget(query=self._text_field)
        replied_msg = cast(str, bui.textwidget(query=self._replied_message))
        if msg == '/save':
          info = bs.get_connection_to_host_info()
          config = babase.app.config
          if info.get('name', '') != '':
            title = info['name']
            if not isinstance(config.get('Saved Servers'), dict):
                config['Saved Servers'] = {}
            config['Saved Servers'][f'{_ip}@{_port}'] = {
                'addr': _ip,
                'port': _port,
                'name': title
            }
            config.commit()
            bui.screenmessage("Server Added To Manual", color=(0,1,0), transient=True)
            bui.getsound('gunCocking').play()
            bui.textwidget(edit=self._text_field,text="")
            return
        elif msg != '' or replied_msg != '':
            if replied_msg != '':
                if len(replied_msg) > 48:
                    replied_msg = replied_msg[:46] + '...'
                bs.chatmessage('          | ' + replied_msg) 
            #bs.chatmessage(cast(str, msg))
            msg_parts = split_msg(cast(str, msg))
            for part in msg_parts:
                bs.chatmessage(part)
            self._cancel_replied_message()
        else:
            quick_reply = self._get_quick_responds()
            if len(quick_reply) == 0:
                #bs.chatmessage(cast(str, msg))
                msg_parts = split_msg(cast(str, msg))
                for part in msg_parts:
                    bs.chatmessage(part)
            else:
                PopupMenuWindow(position=self._send_button.get_screen_space_center(),
                                scale=self._get_popup_window_scale(),
                                color=self.bg_color,
                                choices=quick_reply,
                                choices_display=self._create_baLstr_list(quick_reply),
                                current_choice=quick_reply[0],
                                delegate=self)
                self._popup_type = 'quickMessage'
        bui.textwidget(edit=self._text_field, text='')

    def _write_quick_responds(self, data):
        try:
            with open(quick_msg_file, 'w') as f:
                f.write('\n'.join(data))
        except:
            logging.exception()
            bui.screenmessage('Error!', (1,0,0))
            bui.getsound('error').play()

    def _get_quick_responds(self):
        if os.path.exists(quick_msg_file):
            with open(quick_msg_file, 'r') as f:
                return f.read().split('\n')
        else:
            default_replies = ['What the hell?', 'Dude that\'s amazing!']
            self._write_quick_responds(default_replies)
            return default_replies

    def _remove_sender_from_message(self, msg=''):
        msg_start = msg.find(": ") + 2
        return msg[msg_start:]

    def _previous_message(self):
        msgs = bs.get_chat_messages()
        if len(msgs) != 0:
            index0 = self.msg_index if hasattr(self, 'msg_index') else 0
            for index in [index0 - 1, index0, (index0 + 1) % len(msgs)]:
                bui.textwidget(edit=self._chat_texts[index],
                      text=msgs[index])
            if not hasattr(self, 'msg_index'):
                self.msg_index = len(msgs) - 1 
            else:
                if self.msg_index > 0:
                    self.msg_index -= 1
                else:
                    del self.msg_index
        if hasattr(self, 'msg_index'):
            msg = self._remove_sender_from_message(msgs[self.msg_index])
            bui.textwidget(edit=self._chat_texts[self.msg_index],
                          text=bui.charstr(bui.SpecialChar.RIGHT_ARROW) + '  ' + msgs[self.msg_index])
            bui.containerwidget(edit=self._columnwidget, visible_child=self._chat_texts[self.msg_index])
        else:
            msg = ''
        self._edit_text_msg_box(msg, 'replace')

    def _next_message(self):
        msgs = bs.get_chat_messages()
        if len(msgs) != 0:
            index0 = self.msg_index if hasattr(self, 'msg_index') else 0
            for index in [index0 - 1, index0, (index0 + 1) % len(msgs)]:
                bui.textwidget(edit=self._chat_texts[index],
                      text=msgs[index])
            if not hasattr(self, 'msg_index'):
                self.msg_index = 0
            else:
                if self.msg_index < len(msgs)-1:
                    self.msg_index += 1
                else:
                    del self.msg_index
        if hasattr(self, 'msg_index'):
            msg = self._remove_sender_from_message(msgs[self.msg_index])
            bui.textwidget(edit=self._chat_texts[self.msg_index],
                          text=bui.charstr(bui.SpecialChar.RIGHT_ARROW) + '  ' + msgs[self.msg_index])
            bui.containerwidget(edit=self._columnwidget, visible_child=self._chat_texts[self.msg_index])
        else:
            msg = ''
        self._edit_text_msg_box(msg, 'replace')
        
    def _ip_port_msg(self):
        try:
            msg = f'IP : {_ip}     PORT : {_port}'
        except:
            msg = ''
        self._edit_text_msg_box(msg, 'replace')
    
    def ping_server(self):
        info = bs.get_connection_to_host_info()
        if info.get('name', '') != '':
            self.pingThread = PingThread(_ip, _port)
            self.pingThread.start()

    def _get_ping_color(self):
        try:
            if _ping < 100:
                return (0.1, 1.0, 0.3)
            elif _ping < 500:
                return (1.0, 1.0, 0.3)
            else:
                return (1.0, 0.0, 0.3)
        except:
            return (0.1,0.1,0.1)

    def _send_ping(self):
        if isinstance(_ping, int):
            bs.chatmessage(f'my ping: {_ping}ms')

    def close(self) -> None:
        """Close the window."""
        bui.containerwidget(edit=self._root_widget, transition='out_scale')

    def close_with_sound(self) -> None:
        """Close the window and make a lovely sound."""
        bui.getsound('swish').play()
        self.close()

    def _get_popup_window_scale(self) -> float:
        uiscale = bui.app.ui_v1.uiscale
        return(2.4 if uiscale is bui.UIScale.SMALL else
                1.5 if uiscale is bui.UIScale.MEDIUM else 1.0)

    def _create_baLstr_list(self, list1):
        return (bui.Lstr(value=i) for i in list1)

    def _edit_text_msg_box(self, text, action='add'):
        if isinstance(text, str):
            if action == 'add':
                bui.textwidget(edit=self._text_field, text=bui.textwidget(query=self._text_field)+text)
            elif action =='replace':
                bui.textwidget(edit=self._text_field, text=text)
           
    def join_discord(self):
        bui.open_url("https://discord.gg/AnqRvKQkmV") 
        
def __popup_menu_window_init__(self,
                 position: Tuple[float, float],
                 choices: Sequence[str],
                 current_choice: str,
                 delegate: Any = None,
                 width: float = 230.0,
                 maxwidth: float = None,
                 scale: float = 1.0,
                 color: Tuple[float, float, float] = (0.35, 0.55, 0.15),
                 choices_disabled: Sequence[str] = None,
                 choices_display: Sequence[bui.Lstr] = None):
        # FIXME: Clean up a bit.
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-statements
        if choices_disabled is None:
            choices_disabled = []
        if choices_display is None:
            choices_display = []

        # FIXME: For the moment we base our width on these strings so
        #  we need to flatten them.
        choices_display_fin: List[str] = []
        for choice_display in choices_display:
            choices_display_fin.append(choice_display.evaluate())

        if maxwidth is None:
            maxwidth = width * 1.5

        self._transitioning_out = False
        self._choices = list(choices)
        self._choices_display = list(choices_display_fin)
        self._current_choice = current_choice
        self._color = color
        self._choices_disabled = list(choices_disabled)
        self._done_building = False
        if not choices:
            raise TypeError('Must pass at least one choice')
        self._width = width
        self._scale = scale
        if len(choices) > 8:
            self._height = 280
            self._use_scroll = True
        else:
            self._height = 20 + len(choices) * 33
            self._use_scroll = False
        self._delegate = None  # don't want this stuff called just yet..

        # extend width to fit our longest string (or our max-width)
        for index, choice in enumerate(choices):
            if len(choices_display_fin) == len(choices):
                choice_display_name = choices_display_fin[index]
            else:
                choice_display_name = choice
            if self._use_scroll:
                self._width = max(
                    self._width,
                    min(
                        maxwidth,
                        babase.get_string_width(choice_display_name,
                                             suppress_warning=True)) + 75)
            else:
                self._width = max(
                    self._width,
                    min(
                        maxwidth,
                        babase.get_string_width(choice_display_name,
                                             suppress_warning=True)) + 60)

        # init parent class - this will rescale and reposition things as
        # needed and create our root widget
        PopupWindow.__init__(self,
                             position,
                             size=(self._width, self._height),
                             bg_color = self._color,
                             scale=self._scale)

        if self._use_scroll:
            self._scrollwidget = bui.scrollwidget(parent=self.root_widget,
                                                 position=(20, 20),
                                                 highlight=False,
                                                 color=(0.35, 0.55, 0.15),
                                                 size=(self._width - 40,
                                                       self._height - 40))
            self._columnwidget = bui.columnwidget(parent=self._scrollwidget,
                                                 border=2,
                                                 margin=0)
        else:
            self._offset_widget = bui.containerwidget(parent=self.root_widget,
                                                     position=(30, 15),
                                                     size=(self._width - 40,
                                                           self._height),
                                                     background=False)
            self._columnwidget = bui.columnwidget(parent=self._offset_widget,
                                                 border=2,
                                                 margin=0)
        for index, choice in enumerate(choices):
            if len(choices_display_fin) == len(choices):
                choice_display_name = choices_display_fin[index]
            else:
                choice_display_name = choice
            inactive = (choice in self._choices_disabled)
            wdg = bui.textwidget(parent=self._columnwidget,
                                size=(self._width - 40, 28),
                                on_select_call=babase.Call(self._select, index),
                                click_activate=True,
                                color=(0.5, 0.5, 0.5, 0.5) if inactive else
                                ((0.5, 1, 0.5,
                                  1) if choice == self._current_choice else
                                 (0.8, 0.8, 0.8, 1.0)),
                                padding=0,
                                maxwidth=maxwidth,
                                text=choice_display_name,
                                on_activate_call=self._activate,
                                v_align='center',
                                selectable=(not inactive))
            if choice == self._current_choice:
                bui.containerwidget(edit=self._columnwidget,
                                   selected_child=wdg,
                                   visible_child=wdg)

        # ok from now on our delegate can be called
        self._delegate = weakref.ref(delegate)
        self._done_building = True

original_connect_to_party = bs.connect_to_party

def modify_connect_to_party(address, port, print_progress=False):
    global _ip, _port
    _ip = address
    _port = port
    babase.app.config['chat'] = []
    babase.app.config['server_start_time'] = None
    original_connect_to_party(_ip, _port)
bs.connect_to_party = modify_connect_to_party

class PingThread(threading.Thread):
    """Thread for sending out game pings."""

    def __init__(self, address: str, port: int):
        super().__init__()
        self._address = address
        self._port = port

    def run(self) -> None:
        sock: Optional[socket.socket] = None
        try:
            import socket
            from babase import get_ip_address_type
            socket_type = get_ip_address_type(self._address)
            sock = socket.socket(socket_type, socket.SOCK_DGRAM)
            sock.connect((self._address, self._port))

            starttime = time.time()

            # Send a few pings and wait a second for
            # a response.
            sock.settimeout(1)
            for _i in range(3):
                sock.send(b'\x0b')
                result: Optional[bytes]
                try:
                    # 11: BA_PACKET_SIMPLE_PING
                    result = sock.recv(10)
                except Exception:
                    result = None
                if result == b'\x0c':
                    # 12: BA_PACKET_SIMPLE_PONG
                    accessible = True
                    break
                time.sleep(1)
            global _ping
            _ping = int((time.time() - starttime) * 1000.0)
        except Exception:
            logging.exception('Error on gather ping', once=True)
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                logging.exception('Error on gather ping cleanup', once=True)

class ServerStartTimeThread(threading.Thread):
    """Thread for sending out game pings."""

    def __init__(self, address: str, port: int):
        super().__init__()
        self._address = address
        self._port = port + 1357

    def run(self) -> None:
        sock: Optional[socket.socket] = None
        try:
            import socket
            from babase import get_ip_address_type
            socket_type = get_ip_address_type(self._address)
            sock = socket.socket(socket_type, socket.SOCK_DGRAM)
            sock.connect((self._address, self._port))

            # Send a few pings and wait a second for
            # a response.
            sock.settimeout(1)
            sock.send(b'getserverstarttime')
            result: Optional[bytes]
            try:
                result = sock.recv(10)
            except Exception:
                result = None
            if len(result) != 0:
                try:
                    babase.app.config['serverstarttime'] = int(result.decode("utf-8"))
                except:
                    pass
        except Exception:
            pass
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass


# ba_meta export plugin
class InitalRun(babase.Plugin):
    def __init__(self):
        if babase.env().get("build_number",0) >= 20918:
            # bs.connect_to_party is wrapped above
            bauiv1lib.party.PartyWindow = PartyWindow
            PopupMenuWindow.__init__ = __popup_menu_window_init__
            #MainMenuWindow._get_store_char_tex = _get_store_char_tex
        else:print("плагин совместим только с версией игры 1.7.13 или выше")

