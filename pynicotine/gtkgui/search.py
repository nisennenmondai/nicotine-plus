# COPYRIGHT (C) 2020 Nicotine+ Team
# COPYRIGHT (C) 2016-2018 Mutnick <mutnick@techie.com>
# COPYRIGHT (C) 2016-2017 Michael Labouebe <gfarmerfr@free.fr>
# COPYRIGHT (C) 2008-2011 Quinox <quinox@users.sf.net>
# COPYRIGHT (C) 2006-2009 Daelstorm <daelstorm@gmail.com>
# COPYRIGHT (C) 2003-2004 Hyriand <hyriand@thegraveyard.org>
#
# GNU GENERAL PUBLIC LICENSE
#    Version 3, 29 June 2007
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import operator
import os
import random
import re
import sre_constants
from gettext import gettext as _

from gi.repository import Gdk
from gi.repository import GObject as gobject
from gi.repository import Gtk as gtk

from pynicotine import slskmessages
from pynicotine.gtkgui.dirchooser import ChooseDir
from pynicotine.gtkgui.dialogs import MetaDialog
from pynicotine.gtkgui.utils import CollapseTreeview
from pynicotine.gtkgui.utils import FillFileGroupingCombobox
from pynicotine.gtkgui.utils import HideColumns
from pynicotine.gtkgui.utils import Humanize
from pynicotine.gtkgui.utils import HumanSize
from pynicotine.gtkgui.utils import HumanSpeed
from pynicotine.gtkgui.utils import IconNotebook
from pynicotine.gtkgui.utils import InitialiseColumns
from pynicotine.gtkgui.utils import PopupMenu
from pynicotine.gtkgui.utils import SelectUserRowIter
from pynicotine.gtkgui.utils import SetTreeviewSelectedRow
from pynicotine.gtkgui.utils import showCountryTooltip
from pynicotine.gtkgui.wishlist import WishList
from pynicotine.logfacility import log
from pynicotine.utils import GetResultBitrateLength


class Searches(IconNotebook):

    def __init__(self, frame):

        self.frame = frame

        self.searchid = int(random.random() * (2 ** 31 - 1))
        self.searches = {}
        self.usersearches = {}
        self.users = {}
        self.maxdisplayedresults = self.frame.np.config.sections['searches']["max_displayed_results"]
        self.maxstoredresults = self.frame.np.config.sections['searches']["max_stored_results"]

        ui = self.frame.np.config.sections["ui"]

        IconNotebook.__init__(
            self,
            self.frame.images,
            angle=ui["labelsearch"],
            tabclosers=ui["tabclosers"],
            show_image=self.frame.np.config.sections["notifications"]["notification_tab_icons"],
            reorderable=ui["tab_reorderable"],
            notebookraw=self.frame.SearchNotebookRaw
        )

        self.popup_enable()

        self.WishList = WishList(frame, self)

        self.UpdateColours()

    def LoadConfig(self):
        """
        Add search history to SearchEntryCombo later and connect Wishlist,
        after widgets have been created.
        """
        items = self.frame.np.config.sections["searches"]["history"]
        templist = []

        for i in items:
            if i not in templist:
                templist.append(i)

        for i in templist:
            self.frame.SearchEntryCombo_List.append([i])

    def OnClearSearchHistory(self):

        self.frame.SearchEntry.set_text("")
        self.frame.np.config.sections["searches"]["history"] = []
        self.frame.np.config.writeConfiguration()
        self.frame.SearchEntryCombo.get_model().clear()
        self.frame.SearchEntryCombo_List.append([""])

    def OnSearch(self):
        self.saveColumns()
        text = self.frame.SearchEntry.get_text().strip()

        if not text:
            return

        users = []
        room = None
        search_mode = self.frame.SearchMethod.get_model().get(self.frame.SearchMethod.get_active_iter(), 0)[0]

        if search_mode == _("Global"):
            mode = 0
        elif search_mode == _("Rooms"):
            mode = 1
            name = self.frame.RoomSearchCombo.get_child().get_text()
            # Space after Joined Rooms is important, so it doesn't conflict
            # with any possible real room
            if name != _("Joined Rooms ") and not name.isspace():
                room = name
        elif search_mode == _("Buddies"):
            mode = 2
        elif search_mode == _("User"):
            mode = 3
            user = self.frame.UserSearchCombo.get_child().get_text().strip()
            if user != "" and not user.isspace():
                users = [user]
            else:
                return
        else:
            mode = 0

        feedback = None

        if mode == 0:
            feedback = self.frame.np.pluginhandler.OutgoingGlobalSearchEvent(text)
            if feedback is not None:
                text = feedback[0]
        elif mode == 1:
            feedback = self.frame.np.pluginhandler.OutgoingRoomSearchEvent(room, text)
            if feedback is not None:
                (room, text) = feedback
        elif mode == 2:
            feedback = self.frame.np.pluginhandler.OutgoingBuddySearchEvent(text)
            if feedback is not None:
                text = feedback[0]
        elif mode == 3:
            feedback = self.frame.np.pluginhandler.OutgoingUserSearchEvent(users)
            if feedback is not None:
                users = feedback[0]
        else:
            log.add_warning(_("Unknown search mode, not using plugin system. Fix me!"))
            feedback = True

        if feedback is not None:
            self.DoSearch(text, mode, users, room)
            self.frame.SearchEntry.set_text("")

    def DoSearch(self, text, mode, users=[], room=None):

        # Get excluded words (starting with "-")
        searchterm_words = text.split()
        searchterm_words_ignore = [p[1:] for p in searchterm_words if p.startswith('-') and len(p) > 1]

        # Remove words starting with "-", results containing these are excluded by us later
        searchterm_without_excluded = re.sub(r'(\s)-\w+', r'\1', text)

        if self.frame.np.config.sections["searches"]["remove_special_chars"]:
            """
            Remove special characters from search term
            SoulseekQt doesn't seem to send search results if special characters are included (July 7, 2020)
            """
            searchterm_without_excluded = re.sub(r'\W+', ' ', searchterm_without_excluded)

        # Remove trailing whitespace
        searchterm_without_excluded = searchterm_without_excluded.strip()

        # Append excluded words
        searchterm_with_excluded = searchterm_without_excluded
        for word in searchterm_words_ignore:
            searchterm_with_excluded += " -" + word

        items = self.frame.np.config.sections["searches"]["history"]

        if searchterm_with_excluded in items:
            items.remove(searchterm_with_excluded)

        items.insert(0, searchterm_with_excluded)

        # Clear old items
        del items[15:]
        self.frame.np.config.writeConfiguration()

        # Repopulate the combo list
        self.frame.SearchEntryCombo.get_model().clear()
        templist = []

        for i in items:
            if i not in templist:
                templist.append(i)

        for i in templist:
            self.frame.SearchEntryCombo_List.append([i])

        if mode == 3 and users != [] and users[0] != '':
            self.usersearches[self.searchid] = users

        search = self.CreateTab(self.searchid, searchterm_with_excluded, mode, showtab=True)
        if search[2] is not None:
            self.set_current_page(self.page_num(search[2].Main))

        if mode == 0:
            self.DoGlobalSearch(self.searchid, searchterm_without_excluded)
        elif mode == 1:
            self.DoRoomsSearch(self.searchid, searchterm_without_excluded, room)
        elif mode == 2:
            self.DoBuddiesSearch(self.searchid, searchterm_without_excluded)
        elif mode == 3 and users != [] and users[0] != '':
            self.DoPeerSearch(self.searchid, searchterm_without_excluded, users)

        self.searchid += 1

    def DoGlobalSearch(self, id, text):
        self.frame.np.queue.put(slskmessages.FileSearch(id, text))

    def DoRoomsSearch(self, id, text, room=None):
        if room is not None:
            self.frame.np.queue.put(slskmessages.RoomSearch(room, id, text))
        else:
            for room in self.frame.chatrooms.roomsctrl.joinedrooms:
                self.frame.np.queue.put(slskmessages.RoomSearch(room, id, text))

    def DoBuddiesSearch(self, id, text):
        for i in self.frame.np.config.sections["server"]["userlist"]:
            user = i[0]
            self.frame.np.queue.put(slskmessages.UserSearch(user, id, text))

    def DoPeerSearch(self, id, text, users):
        for user in users:
            self.frame.np.ProcessRequestToPeer(user, slskmessages.FileSearchRequest(None, id, text))

    def GetUserSearchName(self, id):

        if id in self.usersearches:

            users = self.usersearches[id]

            if len(users) > 1:
                return _("Users")
            elif len(users) == 1:
                return users[0]

        return _("User")

    def CreateTab(self, id, text, mode, remember=False, showtab=True, ignored=False):

        tab = Search(self, text, id, mode, remember, showtab)

        if showtab:
            self.ShowTab(tab, id, text, mode)

        search = [id, text, tab, mode, remember, ignored]
        self.searches[id] = search

        return search

    def ShowTab(self, tab, id, text, mode):
        if mode:
            fulltext = "(" + ("", _("Rooms"), _("Buddies"), self.GetUserSearchName(id))[mode] + ") " + text
            label = fulltext[:15]
        else:
            fulltext = text
            label = fulltext[:20]

        self.append_page(tab.Main, label, tab.OnClose, fulltext=fulltext)

    def ShowResult(self, msg, username, country):

        try:
            search = self.searches[msg.token]
        except KeyError:
            return

        if search[5]:
            # Tab is ignored
            return

        if search[2] is None:
            search = self.CreateTab(search[0], search[1], search[3], search[4], showtab=False)

        counter = len(search[2].all_data) + 1

        # No more things to add because we've reached the max_stored_results limit
        if counter > self.maxstoredresults:
            # Ignore tab
            search[5] = True
            return

        search[2].AddUserResults(msg, username, country)

    def RemoveTab(self, tab):

        if tab.id in self.searches:
            search = self.searches[tab.id]

            if search[5]:
                # Tab is ignored, delete search
                del self.searches[tab.id]
            else:
                search[2] = None

        self.remove_page(tab.Main)
        tab.Main.destroy()

    def UpdateColours(self):

        for id in self.searches.values():
            if id[2] is None:
                continue
            id[2].ChangeColours()

        self.frame.SetTextBG(self.WishList.AddWishEntry)

    def saveColumns(self):

        page_num = self.get_current_page()

        if page_num is not None:

            page = self.get_nth_page(page_num)

            for name, search in self.searches.items():

                if search[2] is None:
                    continue
                if search[2].Main == page:
                    search[2].saveColumns()
                    break

    def TabPopup(self, id):

        popup = PopupMenu(self.frame)
        popup.setup(
            ("#" + _("Copy search term"), self.searches[id][2].OnCopySearchTerm),
            ("", None),
            ("#" + _("Close this tab"), self.searches[id][2].OnClose)
        )

        return popup

    def on_tab_click(self, widget, event, child):

        if event.type == Gdk.EventType.BUTTON_PRESS:

            id = None
            n = self.page_num(child)
            page = self.get_nth_page(n)

            for search, data in self.searches.items():

                if data[2] is None:
                    continue
                if data[2].Main is page:
                    id = search
                    break

            if id is None:
                log.add_warning(_("Search ID was none when clicking tab"))
                return

            if event.button == 2:
                self.searches[id][2].OnClose(widget)
                return True

            if event.button == 3:
                menu = self.TabPopup(id)
                menu.popup(None, None, None, None, event.button, event.time)
                return True

        return False


class Search:

    def __init__(self, Searches, text, id, mode, remember, showtab):

        self.Searches = Searches
        self.frame = Searches.frame

        # Build the window
        builder = gtk.Builder()

        builder.set_translation_domain('nicotine')
        builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "search.ui"))

        self.SearchTab = builder.get_object("SearchTab")

        for i in builder.get_objects():
            try:
                self.__dict__[gtk.Buildable.get_name(i)] = i
            except TypeError:
                pass

        self.SearchTab.remove(self.Main)
        self.SearchTab.destroy()

        builder.connect_signals(self)

        self.text = text
        self.searchterm_words_include = [p for p in text.lower().split() if not p.startswith('-')]
        self.searchterm_words_ignore = [p[1:] for p in text.lower().split() if p.startswith('-') and len(p) > 1]

        self.id = id
        self.mode = mode
        self.remember = remember
        self.showtab = showtab
        self.usersiters = {}
        self.directoryiters = {}
        self.users = set()
        self.all_data = []
        self.filters = None
        self.resultslimit = 2000
        self.numvisibleresults = 0

        self.operators = {
            '<': operator.lt,
            '<=': operator.le,
            '==': operator.eq,
            '!=': operator.ne,
            '>=': operator.ge,
            '>': operator.gt
        }

        FillFileGroupingCombobox(self.ResultGrouping)
        self.ResultGrouping.set_active(self.frame.np.config.sections["searches"]["group_searches"])
        self.ResultGrouping.connect("changed", self.OnGroup)

        self.ExpandButton.set_active(self.frame.np.config.sections["searches"]["expand_searches"])
        self.ExpandButton.connect("toggled", self.OnToggleExpandAll)

        if mode > 0:
            self.RememberCheckButton.set_sensitive(False)

        self.RememberCheckButton.set_active(remember)

        """ Columns """

        self.ResultsList.get_selection().set_mode(gtk.SelectionMode.MULTIPLE)
        self.ResultsList.set_enable_tree_lines(True)
        self.ResultsList.set_headers_clickable(True)
        self.ResultsList.set_rubber_banding(True)

        if self.ResultGrouping.get_active() > 0:
            # Group by folder or user

            self.ResultsList.set_show_expanders(True)
        else:
            self.ResultsList.set_show_expanders(False)

        self.resultsmodel = gtk.TreeStore(
            gobject.TYPE_UINT64,  # (0)  num
            str,                  # (1)  user
            gobject.TYPE_OBJECT,  # (2)  flag
            str,                  # (3)  immediatedl
            str,                  # (4)  h_speed
            str,                  # (5)  h_queue
            str,                  # (6)  directory
            str,                  # (7)  filename
            str,                  # (8)  h_size
            str,                  # (9)  h_bitrate
            str,                  # (10) length
            gobject.TYPE_UINT64,  # (11) bitrate
            str,                  # (12) fullpath
            str,                  # (13) country
            gobject.TYPE_UINT64,  # (14) size
            gobject.TYPE_UINT64,  # (15) speed
            gobject.TYPE_UINT64   # (16) queue
        )

        widths = self.frame.np.config.sections["columns"]["filesearch_widths"]
        cols = InitialiseColumns(
            self.ResultsList,
            [_("ID"), widths[0], "text", self.CellDataFunc],
            [_("User"), widths[1], "text", self.CellDataFunc],
            [_("Country"), widths[2], "pixbuf"],
            [_("Immediate Download"), widths[3], "center", self.CellDataFunc],
            [_("Speed"), widths[4], "number", self.CellDataFunc],
            [_("In queue"), widths[5], "center", self.CellDataFunc],
            [_("Directory"), widths[6], "text", self.CellDataFunc],
            [_("Filename"), widths[7], "text", self.CellDataFunc],
            [_("Size"), widths[8], "number", self.CellDataFunc],
            [_("Bitrate"), widths[9], "number", self.CellDataFunc],
            [_("Length"), widths[10], "number", self.CellDataFunc]
        )

        self.col_num, self.col_user, self.col_country, self.col_immediate, self.col_speed, self.col_queue, self.col_directory, self.col_file, self.col_size, self.col_bitrate, self.col_length = cols

        if self.ResultGrouping.get_active() > 0:
            # Group by folder or user

            self.ResultsList.get_columns()[0].set_visible(False)
            self.ExpandButton.show()

        HideColumns(cols, self.frame.np.config.sections["columns"]["filesearch_columns"])

        self.col_num.set_sort_column_id(0)
        self.col_user.set_sort_column_id(1)
        self.col_country.set_sort_column_id(13)
        self.col_immediate.set_sort_column_id(3)
        self.col_speed.set_sort_column_id(15)
        self.col_queue.set_sort_column_id(16)
        self.col_directory.set_sort_column_id(6)
        self.col_file.set_sort_column_id(7)
        self.col_size.set_sort_column_id(14)
        self.col_bitrate.set_sort_column_id(11)
        self.col_length.set_sort_column_id(10)

        self.col_country.get_widget().hide()

        self.ResultsList.set_model(self.resultsmodel)

        self.ResultsList.connect("button_press_event", self.OnListClicked)

        self.ChangeColours()

        """ Filters """

        self.FilterBitrate_List = gtk.ListStore(gobject.TYPE_STRING)
        self.FilterBitrate.set_model(self.FilterBitrate_List)
        self.FilterBitrate.set_entry_text_column(0)

        self.FilterSize_List = gtk.ListStore(gobject.TYPE_STRING)
        self.FilterSize.set_model(self.FilterSize_List)
        self.FilterSize.set_entry_text_column(0)

        self.FilterCountry_List = gtk.ListStore(gobject.TYPE_STRING)
        self.FilterCountry.set_model(self.FilterCountry_List)
        self.FilterCountry.set_entry_text_column(0)

        self.FilterIn_List = gtk.ListStore(gobject.TYPE_STRING)
        self.FilterIn.set_model(self.FilterIn_List)
        self.FilterIn.set_entry_text_column(0)

        self.FilterOut_List = gtk.ListStore(gobject.TYPE_STRING)
        self.FilterOut.set_model(self.FilterOut_List)
        self.FilterOut.set_entry_text_column(0)

        self.PopulateFilters()

        self.FilterSize.clear()
        sizecell = gtk.CellRendererText()
        sizecell.set_property("xalign", 1)
        self.FilterSize.pack_start(sizecell, True)
        self.FilterSize.add_attribute(sizecell, "text", 0)

        self.FilterBitrate.clear()
        bit_cell = gtk.CellRendererText()
        bit_cell.set_property("xalign", 1)
        self.FilterBitrate.pack_start(bit_cell, True)
        self.FilterBitrate.add_attribute(bit_cell, "text", 0)

        self.FilterIn.connect("changed", self.OnFilterChanged)
        self.FilterOut.connect("changed", self.OnFilterChanged)
        self.FilterSize.connect("changed", self.OnFilterChanged)
        self.FilterBitrate.connect("changed", self.OnFilterChanged)
        self.FilterCountry.connect("changed", self.OnFilterChanged)

        self.FilterIn.get_child().connect("activate", self.OnRefilter)
        self.FilterOut.get_child().connect("activate", self.OnRefilter)
        self.FilterSize.get_child().connect("activate", self.OnRefilter)
        self.FilterBitrate.get_child().connect("activate", self.OnRefilter)
        self.FilterCountry.get_child().connect("activate", self.OnRefilter)

        """ Popup """

        self.popup_menu_users = PopupMenu(self.frame, False)
        self.popup_menu = popup = PopupMenu(self.frame)
        popup.setup(
            ("#" + _("_Download file(s)"), self.OnDownloadFiles),
            ("#" + _("Download file(s) _to..."), self.OnDownloadFilesTo),
            ("#" + _("Download _folder(s)"), self.OnDownloadFolders),
            ("#" + _("Download f_older(s) to..."), self.OnDownloadFoldersTo),
            ("#" + _("View Metadata of file(s)"), self.OnSearchMeta),
            ("", None),
            ("#" + _("Copy _URL"), self.OnCopyURL),
            ("#" + _("Copy folder U_RL"), self.OnCopyDirURL),
            ("", None),
            (1, _("User(s)"), self.popup_menu_users, self.OnPopupMenuUsers)
        )

    def OnTooltip(self, widget, x, y, keyboard_mode, tooltip):
        return showCountryTooltip(widget, x, y, tooltip, 13, stripprefix='')

    def OnFilterChanged(self, widget):

        iter = widget.get_active_iter()

        if iter:
            self.OnRefilter(None)

    def PopulateFilters(self):

        if self.frame.np.config.sections["searches"]["enablefilters"]:

            filter = self.frame.np.config.sections["searches"]["defilter"]

            self.FilterIn.get_child().set_text(filter[0])
            self.FilterOut.get_child().set_text(filter[1])
            self.FilterSize.get_child().set_text(filter[2])
            self.FilterBitrate.get_child().set_text(filter[3])
            self.FilterFreeSlot.set_active(filter[4])

            if(len(filter) > 5):
                self.FilterCountry.get_child().set_text(filter[5])

            self.filtersCheck.set_active(1)

        for i in ['0', '128', '160', '192', '256', '320']:
            self.FilterBitrate.get_model().append([i])

        for i in [">10MiB", "<10MiB", "<5MiB", "<1MiB", ">0"]:
            self.FilterSize.get_model().append([i])

        s_config = self.frame.np.config.sections["searches"]

        for i in s_config["filterin"]:
            self.AddCombo(self.FilterIn, i, True)

        for i in s_config["filterout"]:
            self.AddCombo(self.FilterOut, i, True)

        for i in s_config["filtersize"]:
            self.AddCombo(self.FilterSize, i, True)

        for i in s_config["filterbr"]:
            self.AddCombo(self.FilterBitrate, i, True)

        for i in s_config["filtercc"]:
            self.AddCombo(self.FilterCountry, i, True)

    def AddCombo(self, Combobox, text, list=False):

        text = text.strip()
        if not text:
            return False

        model = Combobox.get_model()
        iter = model.get_iter_first()
        match = False

        while iter is not None:

            value = model.get_value(iter, 0)

            if value.strip() == text:
                match = True

            iter = model.iter_next(iter)

        if not match:
            if list:
                model.append([text])
            else:
                model.prepend([text])

    def AddUserResults(self, msg, user, country):

        if user in self.users:
            return

        self.users.add(user)

        counter = len(self.all_data) + 1

        inqueue = msg.inqueue
        ulspeed = msg.ulspeed
        h_speed = HumanSpeed(ulspeed)

        if msg.freeulslots:
            imdl = "Y"
            inqueue = 0
        else:
            imdl = "N"

        h_queue = Humanize(inqueue)

        append = False
        maxstoredresults = self.Searches.maxstoredresults

        for result in msg.list:

            if counter > maxstoredresults:
                break

            fullpath = result[1]
            fullpath_lower = fullpath.lower()

            if any(word in fullpath_lower for word in self.searchterm_words_ignore):
                """ Filter out results with filtered words (e.g. nicotine -music) """
                log.add_search(_("Filtered out excluded search result " + fullpath + " from user " + user))
                continue

            if not any(word in fullpath_lower for word in self.searchterm_words_include):
                """ Some users may send us wrong results, filter out such ones """
                log.add_search(_("Filtered out inexact or incorrect search result " + fullpath + " from user " + user))
                continue

            fullpath_split = reversed(fullpath.split('\\'))
            name = next(fullpath_split)
            directory = '\\'.join(fullpath_split)

            size = result[2]
            h_size = HumanSize(size)
            h_bitrate, bitrate, h_length = GetResultBitrateLength(size, result[4])

            self.append([counter, user, self.get_flag(user, country), imdl, h_speed, h_queue, directory, name, h_size, h_bitrate, h_length, bitrate, fullpath, country, size, ulspeed, inqueue])
            append = True
            counter += 1

        if append:
            # If this search wasn't initiated by us (e.g. wishlist), and the results aren't spoofed, show tab
            if not self.showtab:
                self.Searches.ShowTab(self, self.id, self.text, self.mode)
                self.showtab = True

            # Update counter
            self.Counter.set_text("Results: %d/%d" % (self.numvisibleresults, len(self.all_data)))

            # Update tab notification
            self.frame.Searches.request_changed(self.Main)
            if self.frame.MainNotebook.get_current_page() != self.frame.MainNotebook.page_num(self.frame.searchvbox):
                self.frame.SearchTabLabel.get_child().set_image(self.frame.images["online"])

    def get_flag(self, user, flag=None):

        if flag is not None:
            flag = "flag_" + flag
            self.frame.flag_users[user] = flag
        else:
            flag = self.frame.GetUserFlag(user)

        return self.frame.GetFlagImage(flag)

    def append(self, row):

        self.all_data.append(row)

        if self.numvisibleresults >= self.Searches.maxdisplayedresults:
            return

        if not self.check_filter(row):
            return

        iter = self.AddRowToModel(row)

        if self.ResultGrouping.get_active() > 0:
            # Group by folder or user

            if self.ExpandButton.get_active():
                path = None

                if iter is not None:
                    path = self.resultsmodel.get_path(iter)

                if path is not None:
                    self.ResultsList.expand_to_path(path)
            else:
                CollapseTreeview(self.ResultsList, self.ResultGrouping.get_active())

    def AddRowToModel(self, row):
        counter, user, flag, immediatedl, h_speed, h_queue, directory, filename, h_size, h_bitrate, length, bitrate, fullpath, country, size, speed, queue = row

        if self.ResultGrouping.get_active() > 0:
            # Group by folder or user

            if user not in self.usersiters:
                self.usersiters[user] = self.resultsmodel.append(
                    None,
                    [0, user, self.get_flag(user, country), immediatedl, h_speed, h_queue, "", "", "", "", "", 0, "", country, 0, speed, queue]
                )

            parent = self.usersiters[user]

            if self.ResultGrouping.get_active() == 1:
                # Group by folder

                if directory not in self.directoryiters:
                    self.directoryiters[directory] = self.resultsmodel.append(
                        self.usersiters[user],
                        [0, user, self.get_flag(user, country), immediatedl, h_speed, h_queue, directory, "", "", "", "", 0, fullpath.rsplit('\\', 1)[0] + '\\', country, 0, speed, queue]
                    )

                row = row[:]
                row[6] = ""  # Directory not visible for file row if "group by folder" is enabled

                parent = self.directoryiters[directory]
        else:
            parent = None

        try:
            iter = self.resultsmodel.append(parent, row)

            self.numvisibleresults += 1
        except Exception as e:
            types = []
            for i in row:
                types.append(type(i))
            log.add_warning(_("Search row error: %(exception)s %(row)s"), {'exception': e, 'row': row})
            iter = None

        return iter

    def checkDigit(self, filter, value, factorize=True):

        op = ">="
        if filter[:1] in (">", "<", "="):
            op, filter = filter[:1] + "=", filter[1:]

        if not filter:
            return True

        factor = 1
        if factorize:
            base = 1024
            if filter[-1:].lower() == 'b':
                filter = filter[:-1]  # stripping off the b, we always assume it means bytes
            if filter[-1:].lower() == 'i':
                base = 1000
                filter = filter[:-1]
            if filter.lower()[-1:] == "g":
                factor = pow(base, 3)
                filter = filter[:-1]
            elif filter.lower()[-1:] == "m":
                factor = pow(base, 2)
                filter = filter[:-1]
            elif filter.lower()[-1:] == "k":
                factor = base
                filter = filter[:-1]

        if not filter:
            return True

        try:
            filter = int(filter) * factor
        except ValueError:
            return True

        operation = self.operators.get(op)
        return operation(value, filter)

    def check_filter(self, row):

        filters = self.filters
        if not self.filtersCheck.get_active():
            return True

        # "Included text"-filter, check full file path (located at index 12 in row)
        if filters[0] and not filters[0].search(row[12].lower()):
            return False

        # "Excluded text"-filter, check full file path (located at index 12 in row)
        if filters[1] and filters[1].search(row[12].lower()):
            return False

        if filters[2] and not self.checkDigit(filters[2], row[14]):
            return False

        if filters[3] and not self.checkDigit(filters[3], row[11], False):
            return False

        if filters[4] and row[3] != "Y":
            return False

        if filters[5]:
            for cc in filters[5]:
                if not cc:
                    continue
                if row[13] is None:
                    return False

                if cc[0] == "-":
                    if row[13].upper() == cc[1:].upper():
                        return False
                elif cc.upper() != row[13].upper():
                    return False

        return True

    def set_filters(self, enable, f_in, f_out, size, bitrate, freeslot, country):

        self.filters = [None, None, None, None, freeslot, None]

        if f_in:
            try:
                f_in = re.compile(f_in.lower())
                self.filters[0] = f_in
            except sre_constants.error:
                self.frame.SetTextBG(self.FilterIn.get_child(), "red", "white")
            else:
                self.frame.SetTextBG(self.FilterIn.get_child())

        if f_out:
            try:
                f_out = re.compile(f_out.lower())
                self.filters[1] = f_out
            except sre_constants.error:
                self.frame.SetTextBG(self.FilterOut.get_child(), "red", "white")
            else:
                self.frame.SetTextBG(self.FilterOut.get_child())

        if size:
            self.filters[2] = size

        if bitrate:
            self.filters[3] = bitrate

        if country:
            self.filters[5] = country.upper().split(" ")

        self.usersiters.clear()
        self.directoryiters.clear()
        self.resultsmodel.clear()
        self.numvisibleresults = 0

        for row in self.all_data:
            if self.numvisibleresults >= self.Searches.maxdisplayedresults:
                break

            if self.check_filter(row):
                self.AddRowToModel(row)

        self.Counter.set_text("Results: %d/%d" % (self.numvisibleresults, len(self.all_data)))

    def OnPopupMenuUsers(self, widget):

        self.select_results()

        self.popup_menu_users.clear()

        if len(self.selected_users) > 0:

            items = []

            for user in self.selected_users:
                popup = PopupMenu(self.frame, False)
                popup.setup(
                    ("#" + _("Send _message"), popup.OnSendMessage),
                    ("#" + _("Show IP a_ddress"), popup.OnShowIPaddress),
                    ("#" + _("Get user i_nfo"), popup.OnGetUserInfo),
                    ("#" + _("Brow_se files"), popup.OnBrowseUser),
                    ("#" + _("Gi_ve privileges"), popup.OnGivePrivileges),
                    ("", None),
                    ("$" + _("_Add user to list"), popup.OnAddToList),
                    ("$" + _("_Ban this user"), popup.OnBanUser),
                    ("$" + _("_Ignore this user"), popup.OnIgnoreUser),
                    ("#" + _("Select User's Results"), self.OnSelectUserResults)
                )
                popup.set_user(user)

                items.append((1, user, popup, self.OnPopupMenuUser, popup))

            self.popup_menu_users.setup(*items)

        return True

    def OnPopupMenuUser(self, widget, popup=None):

        if popup is None:
            return

        menu = popup
        user = menu.user
        items = menu.get_children()

        act = False
        if len(self.selected_users) >= 1:
            act = True

        items[0].set_sensitive(act)
        items[1].set_sensitive(act)
        items[2].set_sensitive(act)
        items[3].set_sensitive(act)

        items[6].set_active(user in [i[0] for i in self.frame.np.config.sections["server"]["userlist"]])
        items[7].set_active(user in self.frame.np.config.sections["server"]["banlist"])
        items[8].set_active(user in self.frame.np.config.sections["server"]["ignorelist"])

        for i in range(4, 9):
            items[i].set_sensitive(act)

        return True

    def OnSelectUserResults(self, widget):

        if len(self.selected_users) == 0:
            return

        selected_user = widget.get_parent().user

        sel = self.ResultsList.get_selection()
        fmodel = self.ResultsList.get_model()
        sel.unselect_all()

        iter = fmodel.get_iter_first()

        SelectUserRowIter(fmodel, sel, 1, selected_user, iter)

        self.select_results()

    def select_results(self):

        self.selected_results = set()
        self.selected_users = set()

        self.ResultsList.get_selection().selected_foreach(self.SelectedResultsCallback)

    def ChangeColours(self):

        self.frame.SetTextBG(self.FilterIn.get_child())
        self.frame.SetTextBG(self.FilterOut.get_child())
        self.frame.SetTextBG(self.FilterSize.get_child())
        self.frame.SetTextBG(self.FilterBitrate.get_child())
        self.frame.SetTextBG(self.FilterCountry.get_child())

        font = self.frame.np.config.sections["ui"]["searchfont"]

        self.frame.ChangeListFont(self.ResultsList, font)

    def saveColumns(self):

        columns = []
        widths = []
        for column in self.ResultsList.get_columns():
            columns.append(column.get_visible())
            widths.append(column.get_width())

        self.frame.np.config.sections["columns"]["filesearch_columns"] = columns
        self.frame.np.config.sections["columns"]["filesearch_widths"] = widths

    def SelectedResultsCallback(self, model, path, iter):

        user = model.get_value(iter, 1)

        if user is None:
            return

        self.selected_users.add(user)

        path = model.get_value(iter, 12)

        if path == "":
            # Result is not a file or directory, don't add it
            return

        bitrate = model.get_value(iter, 9)
        length = model.get_value(iter, 10)
        size = model.get_value(iter, 14)

        self.selected_results.add((user, path, size, bitrate, length))

    def OnListClicked(self, widget, event):

        if event.button == 3:
            return self.OnPopupMenu(widget, event)

        else:
            pathinfo = widget.get_path_at_pos(event.x, event.y)

            if pathinfo is None:
                widget.get_selection().unselect_all()

            elif event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
                self.select_results()
                self.OnDownloadFiles(widget)
                self.ResultsList.get_selection().unselect_all()
                return True

        return False

    def OnPopupMenu(self, widget, event):

        if event.button != 3:
            return False

        SetTreeviewSelectedRow(widget, event)
        self.select_results()

        items = self.popup_menu.get_children()
        users = len(self.selected_users) > 0
        files = len(self.selected_results) > 0

        for i in range(0, 5):
            items[i].set_sensitive(files)

        items[0].set_sensitive(False)
        items[1].set_sensitive(False)
        items[4].set_sensitive(False)
        items[6].set_sensitive(False)
        items[7].set_sensitive(files)
        items[8].set_sensitive(users)

        for result in self.selected_results:
            if not result[1].endswith('\\'):
                # At least one selected result is a file, activate file-related items
                items[0].set_sensitive(True)
                items[1].set_sensitive(True)
                items[4].set_sensitive(True)
                items[6].set_sensitive(True)
                break

        self.popup_menu.popup(None, None, None, None, event.button, event.time)
        widget.stop_emission_by_name("button_press_event")

        return True

    def CellDataFunc(self, column, cellrenderer, model, iter, dummy="dummy"):
        imdl = model.get_value(iter, 3)
        color = imdl == "Y" and "search" or "searchq"

        colour = self.frame.np.config.sections["ui"][color] or None
        cellrenderer.set_property("foreground", colour)

    def MetaBox(self, title="Meta Data", message="", data=None, modal=True):

        win = MetaDialog(self.frame, message, data, modal)
        win.set_title(title)
        win.show()
        gtk.main()

        return win.ret

    def SelectedResultsAllData(self, model, path, iter, data):

        filename = model.get_value(iter, 7)

        # We only want to see the metadata of files, not directories
        if filename != "":
            num = model.get_value(iter, 0)
            user = model.get_value(iter, 1)
            immediate = model.get_value(iter, 3)
            speed = model.get_value(iter, 4)
            queue = model.get_value(iter, 5)
            directory = model.get_value(iter, 6)
            size = model.get_value(iter, 8)
            bitratestr = model.get_value(iter, 9)
            length = model.get_value(iter, 10)
            fn = model.get_value(iter, 12)
            country = model.get_value(iter, 13)

            data[len(data)] = {
                "user": user,
                "fn": fn,
                "position": num,
                "filename": filename,
                "directory": directory,
                "size": size,
                "speed": speed,
                "queue": queue,
                "immediate": immediate,
                "bitrate": bitratestr,
                "length": length,
                "country": country
            }

    def OnSearchMeta(self, widget):

        if not self.frame.np.transfers:
            return

        data = {}
        self.ResultsList.get_selection().selected_foreach(self.SelectedResultsAllData, data)

        if data != {}:
            self.MetaBox(title=_("Search Results"), message=_("<b>Metadata</b> for Search Query: <i>%s</i>") % self.text, data=data, modal=True)

    def OnDownloadFiles(self, widget, prefix=""):

        if not self.frame.np.transfers:
            return

        for file in self.selected_results:
            # Make sure the selected result is not a directory
            if not file[1].endswith('\\'):
                self.frame.np.transfers.getFile(file[0], file[1], prefix, size=file[2], bitrate=file[3], length=file[4], checkduplicate=True)

    def OnDownloadFilesTo(self, widget):

        dir = ChooseDir(self.frame.MainWindow, self.frame.np.config.sections["transfers"]["downloaddir"], multichoice=False)

        if dir is None:
            return

        for dirs in dir:
            self.OnDownloadFiles(widget, dirs)
            break

    def OnDownloadFolders(self, widget):

        requested_folders = {}

        for i in self.selected_results:

            user = i[0]
            folder = i[1].rsplit('\\', 1)[0]

            if user not in requested_folders:
                requested_folders[user] = []

            if folder not in requested_folders[user]:
                """ Ensure we don't send folder content requests for a folder more than once,
                e.g. when several selected resuls belong to the same folder. """

                self.frame.np.ProcessRequestToPeer(user, slskmessages.FolderContentsRequest(None, folder))
                requested_folders[user].append(folder)

    def OnDownloadFoldersTo(self, widget):

        directories = ChooseDir(self.frame.MainWindow, self.frame.np.config.sections["transfers"]["downloaddir"], multichoice=False)

        if directories is None or directories == []:
            return

        destination = directories[0]

        for i in self.selected_results:

            user = i[0]
            folder = i[1].rsplit('\\', 1)[0]

            if user not in self.frame.np.requestedFolders:
                self.frame.np.requestedFolders[user] = {}

            if folder not in self.frame.np.requestedFolders[user]:
                """ Ensure we don't send folder content requests for a folder more than once,
                e.g. when several selected resuls belong to the same folder. """

                self.frame.np.requestedFolders[user][folder] = destination
                self.frame.np.ProcessRequestToPeer(user, slskmessages.FolderContentsRequest(None, folder))

    def OnCopyURL(self, widget):
        user, path = next(iter(self.selected_results))[:2]
        self.frame.SetClipboardURL(user, path)

    def OnCopyDirURL(self, widget):

        user, path = next(iter(self.selected_results))[:2]
        path = "\\".join(path.split("\\")[:-1])

        if path[:-1] != "/":
            path += "/"

        self.frame.SetClipboardURL(user, path)

    def OnGroup(self, widget):

        self.OnRefilter(widget)

        self.ResultsList.set_show_expanders(widget.get_active())

        self.frame.np.config.sections["searches"]["group_searches"] = self.ResultGrouping.get_active()

        if widget.get_active():
            self.ResultsList.get_columns()[0].set_visible(False)
            self.ExpandButton.show()
        else:
            self.ResultsList.get_columns()[0].set_visible(True)
            self.ExpandButton.hide()

    def OnToggleExpandAll(self, widget):

        active = self.ExpandButton.get_active()

        if active:
            self.ResultsList.expand_all()
            self.expand.set_from_icon_name("list-remove-symbolic", gtk.IconSize.BUTTON)
        else:
            CollapseTreeview(self.ResultsList, self.ResultGrouping.get_active())
            self.expand.set_from_icon_name("list-add-symbolic", gtk.IconSize.BUTTON)

        self.frame.np.config.sections["searches"]["expand_searches"] = active

    def OnToggleFilters(self, widget):

        if widget.get_active():
            self.Filters.show()
            self.OnRefilter(None)
        else:
            self.Filters.hide()
            self.ResultsList.set_model(None)
            self.set_filters(0, None, None, None, None, None, "")
            self.ResultsList.set_model(self.resultsmodel)

        if self.ResultGrouping.get_active() > 0:
            # Group by folder or user

            if self.ExpandButton.get_active():
                self.ResultsList.expand_all()
            else:
                CollapseTreeview(self.ResultsList, self.ResultGrouping.get_active())

    def OnIgnore(self, widget):

        self.Searches.searches[self.id][5] = True  # ignored

        self.Searches.WishList.remove_wish(self.text)
        widget.set_sensitive(False)

    def OnClear(self, widget):
        self.all_data = []
        self.usersiters.clear()
        self.directoryiters.clear()
        self.resultsmodel.clear()

    def OnClose(self, widget):

        if not self.frame.np.config.sections["searches"]["reopen_tabs"]:
            if self.text not in self.frame.np.config.sections["server"]["autosearch"]:
                self.OnIgnore(widget)

        self.Searches.RemoveTab(self)

    def OnCopySearchTerm(self, widget):
        self.frame.clip.set_text(self.text, -1)

    def OnToggleRemember(self, widget):

        self.remember = widget.get_active()
        search = self.Searches.searches[self.id]

        if not self.remember:
            self.Searches.WishList.remove_wish(search[1])
        else:
            self.Searches.WishList.add_wish(search[1])

    def PushHistory(self, widget, title):

        text = widget.get_child().get_text()
        if not text.strip():
            return None

        text = text.strip()
        history = self.frame.np.config.sections["searches"][title]

        if text in history:
            history.remove(text)
        elif len(history) >= 5:
            del history[-1]

        history.insert(0, text)
        self.frame.np.config.writeConfiguration()

        self.AddCombo(widget, text)
        widget.get_child().set_text(text)

        return text

    def OnRefilter(self, widget):

        f_in = self.PushHistory(self.FilterIn, "filterin")
        f_out = self.PushHistory(self.FilterOut, "filterout")
        f_size = self.PushHistory(self.FilterSize, "filtersize")
        f_br = self.PushHistory(self.FilterBitrate, "filterbr")
        f_free = self.FilterFreeSlot.get_active()
        f_country = self.PushHistory(self.FilterCountry, "filtercc")

        self.ResultsList.set_model(None)
        self.set_filters(1, f_in, f_out, f_size, f_br, f_free, f_country)
        self.ResultsList.set_model(self.resultsmodel)

        if self.ResultGrouping.get_active() > 0:
            # Group by folder or user

            if self.ExpandButton.get_active():
                self.ResultsList.expand_all()
            else:
                CollapseTreeview(self.ResultsList, self.ResultGrouping.get_active())

    def OnAboutFilters(self, widget):
        self.frame.OnAboutFilters(widget)
