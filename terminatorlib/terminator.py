#!/usr/bin/python
#    Terminator - multiple gnome terminals in one window
#    Copyright (C) 2006-2008  cmsj@tenshu.net
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 2 only.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

"""Terminator by Chris Jones <cmsj@tenshu.net>"""
import time, re, sys, os, platform

import pygtk
pygtk.require ("2.0")
import gobject, gtk, pango

from terminatorlib.version import APP_NAME, APP_VERSION

from terminatorlib import config
from config import dbg, err, debug

from terminatorlib.keybindings import TerminatorKeybindings
from terminatorlib.terminatorterm import TerminatorTerm
from terminatorlib.prefs_profile import ProfileEditor

try:
  import deskbar.core.keybinder as bindkey
except:
  dbg (_("Unable to find python bindings for deskbar, "\
           "hide_window is not available."))
  pass

class TerminatorNotebookTabLabel(gtk.HBox):
  _terminator = None
  _notebook = None
  _label = None
  _icon = None
  _button = None
    
  def __init__(self, title, notebook, terminator):
    gtk.HBox.__init__(self, False)
    self._notebook = notebook
    self._terminator = terminator
    
    self._label = gtk.Label(title)
    self.update_angle()
    self.pack_start(self._label, True, True)

    self._icon = gtk.Image()
    self._icon.set_from_stock(gtk.STOCK_CLOSE, gtk.ICON_SIZE_MENU)
    
    self.update_closebut()

    self.show_all()

  def update_closebut(self):
    if self._terminator.conf.close_button_on_tab:
      if not self._button:
        self._button = gtk.Button()
      self._button.set_relief(gtk.RELIEF_NONE)
      self._button.set_focus_on_click(False)
      self._button.set_relief(gtk.RELIEF_NONE)
      self._button.add(self._icon)
      self._button.connect('clicked', self.on_close)
      self._button.set_name("terminator-tab-close-button")
      self.connect("style-set", self.on_style_set)
      if hasattr(self._button, "set_tooltip_text"): 
        self._button.set_tooltip_text(_("Close Tab"))
        self.pack_start(self._button, False, False)
        self.show_all()
    else:
      if self._button:
        self._button.remove(self._icon)
        self.remove(self._button)
        del(self._button)
        self._button = None

  def update_angle(self):
      tab_pos = self._notebook.get_tab_pos()
      if tab_pos == gtk.POS_LEFT:
        self._label.set_angle(90)
      elif tab_pos == gtk.POS_RIGHT:
        self._label.set_angle(270)
      else:
        self._label.set_angle(0)

  def on_style_set(self, widget, prevstyle):
    x, y = gtk.icon_size_lookup_for_settings( self._button.get_settings(), gtk.ICON_SIZE_MENU)
    self._button.set_size_request(x + 2,y + 2)

  def on_close(self, widget):
    nbpages = self._notebook.get_n_pages()
    for i in xrange(0,nbpages):
      if self._notebook.get_tab_label(self._notebook.get_nth_page(i)) == self:
        #dbg("[Close from tab] Found tab at position [%d]" % i)
        if not isinstance (self._notebook.get_nth_page(i), TerminatorTerm):
          if self._terminator.confirm_close_multiple (self._terminator.window, _("tab")):
            return False
        term = self._terminator._notebook_first_term(self._notebook.get_nth_page(i))
        while term:
          if term == self._notebook.get_nth_page(i):
            self._terminator.closeterm(term)
            break
          self._terminator.closeterm(term)
          term = self._terminator._notebook_first_term(self._notebook.get_nth_page(i))
        break

  def set_title(self, title):
    self._label.set_text(title)

  def get_title(self):
    return self._label.get_text()
  
  def height_request(self):
    return self.size_request()[1]

  def width_request(self):
    return self.size_request()[0]

class Terminator:
  options = None
  groupings = []

  def __init__ (self, profile = None, command = None, fullscreen = False,
                maximise = False, borderless = False, no_gconf = False,
                geometry = None, hidden = False):
    self.profile = profile
    self.command = command

    self._zoomed = False
    self._maximised = False
    self._fullscreen = False
    self._geometry = geometry
    self.debugaddress = None
    self.start_cwd = os.getcwd()
    self._hidden = False
    self.term_list = []
    self.gnome_client = None
    stores = []

    store = config.TerminatorConfValuestoreRC ()
    store.set_reconfigure_callback (self.reconfigure_vtes)
    stores.append (store)
    
    self._tab_reorderable = True
    if not hasattr(gtk.Notebook, "set_tab_reorderable") or not hasattr(gtk.Notebook, "get_tab_reorderable"):
      self._tab_reorderable = False

    if not no_gconf:
      try:
        import gconf
        if self.profile:
          self.profile = gconf.escape_key (self.profile, -1)
        store = config.TerminatorConfValuestoreGConf (self.profile)
        store.set_reconfigure_callback (self.reconfigure_vtes)
        dbg ('Terminator__init__: comparing %s and %s'%(self.profile, store.profile.split ('/').pop ()))
        if self.profile == store.profile.split ('/').pop ():
          # If we have been given a profile, and we loaded it, we should be higher priority than RC
          dbg ('Terminator__init__: placing GConf before RC')
          stores.insert (0, store)
        else:
          stores.append (store)
      except Exception, e:
        # This should probably be ImportError; what else might it throw?
        dbg("GConf setup threw exception %s" % str(e))

    self.conf = config.TerminatorConfig (stores)

    # Sort out cwd detection code, if available
    self.pid_get_cwd = lambda pid: None
    if platform.system() == 'FreeBSD':
      try:
        from terminatorlib import freebsd
        self.pid_get_cwd = freebsd.get_process_cwd
        dbg ('Using FreeBSD self.pid_get_cwd')
      except (OSError, NotImplementedError, ImportError):
        dbg ('FreeBSD version too old for self.pid_get_cwd')
    elif platform.system() == 'Linux':
      dbg ('Using Linux self.pid_get_cwd')
      self.pid_get_cwd = lambda pid: os.path.realpath ('/proc/%s/cwd' % pid)
    else:
      dbg ('Unable to set a self.pid_get_cwd, unknown system: %s' % platform.system)

    # import a library for viewing URLs
    try:
      dbg ('Trying to import gnome for X session and backup URL handling support')
      global gnome
      import gnome, gnome.ui
      self.gnome_program = gnome.init(APP_NAME, APP_VERSION)
      self.url_show = gnome.url_show
      
      # X session saving support
      self.gnome_client = gnome.ui.master_client()
      self.gnome_client.connect_to_session_manager()
      self.gnome_client.connect('save-yourself', self.save_yourself)
      self.gnome_client.connect('die', self.die)
    except ImportError:
      # webbrowser.open() is not really useful, but will do as a fallback
      dbg ('gnome not available, no X session support, backup URL handling via webbrowser module')
      import webbrowser
      self.url_show = webbrowser.open

    self.icon_theme = gtk.IconTheme ()

    self.keybindings = TerminatorKeybindings()
    if self.conf.f11_modifier:
      config.Defaults['keybindings']['full_screen'] = '<Ctrl><Shift>F11'
      print "Warning: Config setting f11_modifier is deprecated and will be removed in version 1.0"
      print "Please add the following to the end of your terminator config:"
      print "[keybindings]"
      print "full_screen = <Ctrl><Shift>F11"
    self.keybindings.configure(self.conf.keybindings)

    self.set_handle_size (self.conf.handle_size)

    self.window = gtk.Window ()
    self.window.set_title (APP_NAME.capitalize())

    if self._geometry is not None:
      dbg("Geometry=%s" % self._geometry)
      if not self.window.parse_geometry(self._geometry):
        err(_("Invalid geometry string %r") % self._geometry)

    try:
      self.window.set_icon (self.icon_theme.load_icon (APP_NAME, 48, 0))
    except:
      self.icon = self.window.render_icon (gtk.STOCK_DIALOG_INFO, gtk.ICON_SIZE_BUTTON)
      self.window.set_icon (self.icon)

    self.window.connect ("key-press-event", self.on_key_press)
    self.window.connect ("delete_event", self.on_delete_event)
    self.window.connect ("destroy", self.on_destroy_event)
    self.window.connect ("window-state-event", self.on_window_state_changed)

    self.window.set_property ('allow-shrink', True)

    if fullscreen or self.conf.fullscreen:
      self.fullscreen_toggle ()

    if maximise or self.conf.maximise:
      self.maximize ()

    if borderless or self.conf.borderless:
      self.window.set_decorated (False)

    # Set RGBA colormap if possible so VTE can use real alpha
    # channels for transparency.
    if self.conf.enable_real_transparency:
      dbg ('H9TRANS: Enabling real transparency')
      self.enable_rgba(True)

    # Start out with just one terminal
    # FIXME: This should be really be decided from some kind of profile
    term = (TerminatorTerm (self, self.profile, self.command))
    self.term_list = [term]

    self.window.add (term)
    term._titlebox.hide()
    self.window.show ()
    term.spawn_child ()
    self.save_yourself ()

    if hidden or self.conf.hidden:
      self.hide()

    try:
      bindkey.tomboy_keybinder_bind(self.conf.keybindings['hide_window'],self.cbkeyCloak,term)
    except:
      dbg (_("Unable to bind hide_window key"))
      pass

  def set_handle_size (self, size):
    if size in xrange (0,6):
      gtk.rc_parse_string("""
        style "terminator-paned-style" {
            GtkPaned::handle_size = %s 
        }
        
        class "GtkPaned" style "terminator-paned-style"
        """ % self.conf.handle_size)
        
      gtk.rc_parse_string("""
      style "terminator-tab-close-button-style" {
            GtkWidget::focus-padding = 0
            GtkWidget::focus-line-width = 0
            xthickness = 0
            ythickness = 0
         }
         widget "*.terminator-tab-close-button" style "terminator-tab-close-button-style"
         """)

  def enable_rgba (self, rgba = False):
    screen = self.window.get_screen()
    if rgba:
      colormap = screen.get_rgba_colormap()
    else:
      colormap = screen.get_rgb_colormap()
    if colormap:
      self.window.set_colormap(colormap)

  def die(self, *args):
    gtk.main_quit ()

  def save_yourself (self, *args):
    """ Save as much of our state as possible for the X session manager """
    dbg("Saving session for xsm")
    args = [sys.argv[0],
        ("--geometry=%dx%d" % self.window.get_size()) + ("+%d+%d" % self.window.get_position())]

    # OptionParser should really help us out here
    drop_next_arg = False
    geompatt = re.compile(r'^--geometry(=.+)?')
    for arg in sys.argv[1:]:
      mo = geompatt.match(arg)
      if mo:
        if not mo.group(1):
          drop_next_arg = True
      elif not drop_next_arg and arg not in ('--maximise', '-m', '--fullscreen', '-f'):
        args.append(arg)
        drop_next_arg = False

    if self._maximised:
      args.append('--maximise')

    if self._fullscreen:
      args.append('--fullscreen')

    if self.gnome_client:
      # We can't set an interpreter because Gnome unconditionally spams it with
      # --sm-foo-bar arguments before our own argument list. *mutter*
      # So, hopefully your #! line is correct.  If not, we could write out
      # a shell script with the interpreter name etc.
      c = self.gnome_client
      c.set_program(sys.argv[0])
      dbg("Session restart command: %s with args %r in %s" % (sys.argv[0], args, self.start_cwd))

      c.set_restart_style(gnome.ui.RESTART_IF_RUNNING)
      c.set_current_directory(self.start_cwd)
      try:
        c.set_restart_command(args)
        c.set_clone_command(args)
      except (TypeError,AttributeError):
        # Apparantly needed for some Fedora systems
        # see http://trac.nicfit.net/mesk/ticket/137
        dbg("Gnome bindings have weird set_clone/restart_command")
        c.set_restart_command(len(args), args)
        c.set_clone_command(len(args), args)
      return True

  def show(self):
    """Show the terminator window"""
    # restore window position
    self.window.move(self.pos[0],self.pos[1])
    #self.window.present()
    self.window.show_now()
    self._hidden = False   

  def hide(self):
    """Hide the terminator window"""
    # save window position
    self.pos = self.window.get_position()
    self.window.hide()
    self._hidden = True

  def cbkeyCloak(self, data):
    """Callback event for show/hide keypress"""
    if self._hidden:
      self.show()
    else:
      self.hide()

  def maximize (self):
    """ Maximize the Terminator window."""
    self.window.maximize ()

  def unmaximize (self):
    """ Unmaximize the Terminator window."""
    self.window.unmaximize ()

  def fullscreen_toggle (self):
    """ Toggle the fullscreen state of the window. If it is in
        fullscreen state, it will be unfullscreened. If it is not, it
        will be set to fullscreen state.
    """
    if self._fullscreen:
      self.window.unfullscreen ()
    else:
      self.window.fullscreen ()

  def fullscreen_absolute (self, fullscreen):
    """ Explicitly set the fullscreen state of the window.
    """
    if self._fullscreen != fullscreen:
      self.fullscreen_toggle ()

  def on_window_state_changed (self, window, event):
    self._fullscreen = bool (event.new_window_state & gtk.gdk.WINDOW_STATE_FULLSCREEN)
    self._maximised = bool (event.new_window_state & gtk.gdk.WINDOW_STATE_MAXIMIZED)
    dbg("window state changed: fullscreen: %s, maximised: %s" % (self._fullscreen, self._maximised))
    return (False)

  def on_delete_event (self, window, event, data=None):
    if len (self.term_list) == 1:
      return False
    return self.confirm_close_multiple (window, _("window"))

  def confirm_close_multiple (self, window, type):
    # show dialog
    dialog = gtk.Dialog (_("Close?"), window, gtk.DIALOG_MODAL)
    dialog.set_has_separator (False)
    dialog.set_resizable (False)

    cancel = dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT)
    close_all = dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_ACCEPT)
    label = close_all.get_children()[0].get_children()[0].get_children()[1].set_label(_("Close _Terminals"))

    primairy = gtk.Label (_('<big><b>Close multiple terminals?</b></big>'))
    primairy.set_use_markup (True)
    primairy.set_alignment (0, 0.5)
    secundairy = gtk.Label (_("This %s has several terminals open.  Closing the %s will also close all terminals within it.") % (type, type))
    secundairy.set_line_wrap(True)
    primairy.set_alignment (0, 0.5)

    labels = gtk.VBox ()
    labels.pack_start (primairy, False, False, 6)
    labels.pack_start (secundairy, False, False, 6)

    image = gtk.image_new_from_stock(gtk.STOCK_DIALOG_WARNING, gtk.ICON_SIZE_DIALOG)
    image.set_alignment (0.5, 0)

    box = gtk.HBox()
    box.pack_start (image, False, False, 6)
    box.pack_start (labels, False, False, 6)
    dialog.vbox.pack_start (box, False, False, 12)

    dialog.show_all ()
    result = dialog.run ()
    dialog.destroy ()
    return not (result == gtk.RESPONSE_ACCEPT)

  def on_destroy_event (self, widget, data=None):
    self.die()

  # keybindings for the whole terminal window (affects the main
  # windows containing the splited terminals)
  def on_key_press (self, window, event):
    """ Callback for the window to determine what to do with special
        keys. Currently handled key-combo's:
          * F11:              toggle fullscreen state of the window.
          * CTRL - SHIFT - Q: close all terminals
    """
    mapping = self.keybindings.lookup(event)

    if mapping:
      dbg("on_key_press: lookup found %r" % mapping)
      if mapping == 'full_screen':
        self.fullscreen_toggle ()
      elif mapping == 'close_window':
        if not self.on_delete_event (window, gtk.gdk.Event (gtk.gdk.DELETE)):
          self.on_destroy_event (window, gtk.gdk.Event (gtk.gdk.DESTROY))
      else:
        return (False)
      return (True)

  def set_window_title(self, title):
    """
    Modifies Terminator window title
    """
    self.window.set_title(title)
    
  def add(self, widget, terminal, pos = "bottom"):
    """
    Add a term to another at position pos
    """
    vertical = pos in ("top", "bottom")
    pane = (vertical) and gtk.VPaned () or gtk.HPaned ()
    
    # get the parent of the provided terminal
    parent = widget.get_parent ()
    dbg ('SEGBUG: add() Got parent')
    if isinstance (parent, gtk.Window):
      dbg ('SEGBUG: parent is a gtk.Window')
      # We have just one term
      parent.remove(widget)
      dbg ('SEGBUG: removed widget from window')
      if pos in ("top", "left"):
        dbg ('SEGBUG: pos is in top/left')
        pane.pack1 (terminal, True, True)
        dbg ('SEGBUG: packed terminal')
        pane.pack2 (widget, True, True)
        dbg ('SEGBUG: packed widget')
      else:
        dbg ('SEGBUG: pos is not in top/left')
        pane.pack1 (widget, True, True)
        dbg ('SEGBUG: packed widget')
        pane.pack2 (terminal, True, True)
        dbg ('SEGBUG: packed terminal')
      parent.add (pane)
      dbg ('SEGBUG: added pane to parent')

      position = (vertical) and parent.allocation.height \
                             or parent.allocation.width

    if (isinstance (parent, gtk.Notebook) or isinstance (parent, gtk.Window)) and widget.conf.titlebars:
      #not the only term in the notebook/window anymore, need to reshow the title
      dbg ('SEGBUG: Showing _titlebox')
      widget._titlebox.update()
      terminal._titlebox.update()
      
    if isinstance (parent, gtk.Notebook):
      dbg ('SEGBUG: Parent is a notebook')
      page = -1
      
      for i in xrange(0, parent.get_n_pages()):
        if parent.get_nth_page(i) == widget:
          page = i
          break
      widget.reparent (pane)
      if pos in ("top", "left"):
        pane.remove(widget)
        pane.pack1 (terminal, True, True)
        pane.pack2 (widget, True, True)
      else:
        pane.pack1 (widget, True, True)
        pane.pack2 (terminal, True, True)
      #parent.remove_page(page)
      pane.show()
      parent.insert_page(pane, None, page)
      notebooktablabel = TerminatorNotebookTabLabel(widget.get_window_title(), parent, self)
      parent.set_tab_label(pane,notebooktablabel)
      parent.set_tab_label_packing(pane, True, True, gtk.PACK_START)
      if self._tab_reorderable:
        parent.set_tab_reorderable(pane, True)
      parent.set_current_page(page)

      position = (vertical) and parent.allocation.height \
                             or parent.allocation.width

    if isinstance (parent, gtk.Paned):
      dbg ('SEGBUG: parent is a Paned')
      # We are inside a split term
      position = (vertical) and widget.allocation.height \
                             or widget.allocation.width

      dbg ('SEGBUG: Preparing to reparent sibling')
      if (widget == parent.get_child1 ()):
        widget.reparent (pane)
        parent.pack1 (pane, True, True)
      else:
        widget.reparent (pane)
        parent.pack2 (pane, True, True)

      if pos in ("top", "left"):
        dbg ('SEGBUG: pos is in top/left. Removing and re-ordering')
        pane.remove(widget)
        pane.pack1 (terminal, True, True)
        pane.pack2 (widget, True, True)
      else:
        dbg ('SEGBUG: pos is not in top/left. Packing')
        pane.pack1 (widget, True, True)
        pane.pack2 (terminal, True, True)

      dbg ('SEGBUG: packing widget and terminal')
      pane.pack1 (widget, True, True)
      pane.pack2 (terminal, True, True)
      dbg ('SEGBUG: packed widget and terminal')

    # show all, set position of the divider
    dbg ('SEGBUG: Showing pane')
    pane.show ()
    dbg ('SEGBUG: Showed pane')
    pane.set_position (position / 2)
    dbg ('SEGBUG: Set position')
    terminal.show ()

    # insert the term reference into the list
    index = self.term_list.index (widget)
    if pos in ('bottom', 'right'):
      index = index + 1
    self.term_list.insert (index, terminal)
    # make the new terminal grab the focus
    terminal._vte.grab_focus ()

    return (terminal)

  def on_page_reordered(self, notebook, child, page_num):
    #page has been reordered, we need to get the
    # first term and last term
    dbg ("Reordered: %d"%page_num)
    nbpages = notebook.get_n_pages()
    if nbpages == 1:
      dbg("[ERROR] only one page in on_page_reordered")
      
    first = self._notebook_first_term(notebook.get_nth_page(page_num))
    last = self._notebook_last_term(notebook.get_nth_page(page_num))
    firstidx = self.term_list.index(first)
    lastidx = self.term_list.index(last)
    termslice = self.term_list[firstidx:lastidx+1]
    #remove them from the list
    for term in termslice:
      self.term_list.remove(term)
      
    if page_num == 0:
      #first page, we insert before the first term of next page
      nexttab = notebook.get_nth_page(1)
      sibling = self._notebook_first_term(nexttab)
      siblingindex = self.term_list.index(sibling)
      for term in  termslice:
        self.term_list.insert(siblingindex, term)
        siblingindex += 1
    else:
      #other pages, we insert after the last term of previous page
      previoustab = notebook.get_nth_page(page_num - 1)
      sibling = self._notebook_last_term(previoustab)
      siblingindex = self.term_list.index(sibling)
      for term in  termslice:
        siblingindex += 1
        self.term_list.insert(siblingindex, term)
      
  #for page reorder, we need to get the first term of a notebook
  def notebook_first_term(self, notebook):
    return self._notebook_first_term(notebook.get_nth_page(0))
  
  def _notebook_first_term(self, child):
    if isinstance(child, TerminatorTerm):
      return child
    elif isinstance(child, gtk.Paned):
      return self._notebook_first_term(child.get_child1())
    elif isinstance(child, gtk.Notebook):
      return self._notebook_first_term(child.get_nth_page(0))
    
    dbg("[ERROR] unsupported class %s in _notebook_first_term" % child.__class__.__name__)
    return None
  
  #for page reorder, we need to get the last term of a notebook
  def notebook_last_term(self, notebook):
    return self._notebook_last_term(notebook.get_nth_page(notebook.get_n_pages()-1))
  
  def _notebook_last_term(self, child):
    if isinstance(child, TerminatorTerm):
      return child
    elif isinstance(child, gtk.Paned):
      return self._notebook_last_term(child.get_child2())
    elif isinstance(child, gtk.Notebook):
      return self._notebook_last_term(child.get_nth_page(child.get_n_pages()-1))
    
    dbg("[ERROR] unsupported class %s in _notebook_last_term" % child.__class__.__name__)
    return None
  
  def newtab(self,widget, toplevel = False, command = None):
    if self._zoomed:
      # We don't want to add a new tab while we are zoomed in on a terminal
      dbg ("newtab function called, but Terminator was in zoomed terminal mode.")
      return

    terminal = TerminatorTerm (self, self.profile, command, widget.get_cwd())
    #only one term, we don't show the title
    terminal._titlebox.hide()
    if self.conf.extreme_tabs and not toplevel:
      parent = widget.get_parent ()
      child = widget
    else:
      child = self.window.get_children()[0]
      parent = child.get_parent()
      
    if isinstance(parent, gtk.Paned) or (isinstance(parent, gtk.Window) 
       and
       ((self.conf.extreme_tabs and not toplevel) or not isinstance(child, gtk.Notebook))):
      #no notebook yet.
      notebook = gtk.Notebook()
      if self._tab_reorderable:
        notebook.connect('page-reordered',self.on_page_reordered)
        notebook.set_tab_reorderable(widget, True)
      notebook.set_property('homogeneous', True)
      # Config validates this.
      pos = getattr(gtk, "POS_%s" % self.conf.tab_position.upper())
      notebook.set_tab_pos(pos)
      notebook.set_show_tabs (not self.conf.hide_tabbar)
      
      if isinstance(parent, gtk.Paned):
        if parent.get_child1() == child:
          child.reparent(notebook)
          parent.pack1(notebook)
        else:
          child.reparent(notebook)
          parent.pack2(notebook)
      elif isinstance(parent, gtk.Window):
         child.reparent(notebook)
         parent.add(notebook)
      if self._tab_reorderable:
        notebook.set_tab_reorderable(child,True)
      notebooklabel = ""
      if isinstance(child, TerminatorTerm):
        child._titlebox.hide()
      if widget.get_window_title() is not None:
        notebooklabel = widget.get_window_title()
      notebooktablabel = TerminatorNotebookTabLabel(notebooklabel, notebook, self)
      notebook.set_tab_label(child, notebooktablabel)
      notebook.set_tab_label_packing(child, True, True, gtk.PACK_START)

      wal = self.window.allocation
      if not (self._maximised or self._fullscreen):
        self.window.resize(wal.width,
            min(wal.height + notebooktablabel.height_request(), gtk.gdk.screen_height()))

      notebook.show()
    elif isinstance(parent, gtk.Notebook):
      notebook = parent
    elif isinstance(parent, gtk.Window) and isinstance(child, gtk.Notebook):
      notebook = child
    else:
      return (False)
    
    ## NOTE
    ## Here we need to append to the notebook before we can 
    ## spawn the terminal (WINDOW_ID needs to be set)
    
    notebook.append_page(terminal,None)
    terminal.show ()
    terminal.spawn_child ()
    notebooklabel = terminal.get_window_title()
    notebooktablabel = TerminatorNotebookTabLabel(notebooklabel, notebook, self)
    notebook.set_tab_label(terminal, notebooktablabel)
    notebook.set_tab_label_packing(terminal, True, True, gtk.PACK_START)
    if self._tab_reorderable:
      notebook.set_tab_reorderable(terminal,True)
    ## Now, we set focus on the new term
    notebook.set_current_page(-1)
    terminal._vte.grab_focus ()
    
    #adding a new tab, thus we need to get the 
    # last term of the previous tab and add
    # the new term just after
    sibling = self._notebook_last_term(notebook.get_nth_page(notebook.page_num(terminal)-1))
    index = self.term_list.index(sibling)
    self.term_list.insert (index + 1, terminal)
    return (True)
  
  def splitaxis (self, widget, vertical=True, command=None):
    """ Split the provided widget on the horizontal or vertical axis. """
    if self._zoomed:
      # We don't want to split the terminal while we are in zoomed mode
      dbg ("splitaxis function called, but Terminator was in zoomed mode.")
      return

    # create a new terminal and parent pane.
    dbg ('SEGBUG: Creating TerminatorTerm')
    terminal = TerminatorTerm (self, self.profile, command, widget.get_cwd())
    dbg ('SEGBUG: Created TerminatorTerm')
    pos = vertical and "right" or "bottom"
    dbg ('SEGBUG: Position is: %s'%pos)
    self.add(widget, terminal, pos)
    dbg ('SEGBUG: added TerminatorTerm to container')
    terminal.show ()
    dbg ('SEGBUG: showed TerminatorTerm')
    terminal.spawn_child ()
    dbg ('SEGBUG: spawned child')
    return
  
  def remove(self, widget, keep = False):
    """Remove a TerminatorTerm from the Terminator view and terms list
       Returns True on success, False on failure"""
    parent = widget.get_parent ()
    sibling = None
    focus_on_close = 'prev'
    if isinstance (parent, gtk.Window):
      # We are the only term
      if not self.on_delete_event (parent, gtk.gdk.Event (gtk.gdk.DELETE)):
        self.on_destroy_event (parent, gtk.gdk.Event (gtk.gdk.DESTROY))
      return True

    if isinstance (parent, gtk.Paned):
      index = self.term_list.index (widget)
      grandparent = parent.get_parent ()

      # Discover sibling while all objects exist
      if widget == parent.get_child1 ():
        sibling = parent.get_child2 ()
        focus_on_close = 'next'
      if widget == parent.get_child2 ():
        sibling = parent.get_child1 ()

      if not sibling:
        # something is wrong, give up
        err ("Error: %s is not a child of %s"%(widget, parent))
        return False

      parent.remove(widget)
      if isinstance(grandparent, gtk.Notebook):
        page = -1
        for i in xrange(0, grandparent.get_n_pages()):
          if grandparent.get_nth_page(i) == parent:
            page = i
            break
        parent.remove(sibling)
        grandparent.remove_page(page)
        grandparent.insert_page(sibling, None,page)
        grandparent.set_tab_label(sibling, TerminatorNotebookTabLabel("",grandparent, self))
        grandparent.set_tab_label_packing(sibling, True, True, gtk.PACK_START)
        if self._tab_reorderable:
          grandparent.set_tab_reorderable(sibling, True)
        grandparent.set_current_page(page)
      else:
        grandparent.remove (parent)
        sibling.reparent (grandparent)
        if not self._zoomed:
          grandparent.resize_children()
      if isinstance(sibling, TerminatorTerm) and isinstance(sibling.get_parent(), gtk.Notebook):
        sibling._titlebox.hide()

      self.term_list.remove (widget)
      if not keep:
        widget._vte.get_parent().remove(widget._vte)
        widget._vte = None

    elif isinstance (parent, gtk.Notebook):
      parent.remove(widget)
      nbpages = parent.get_n_pages()
      index = self.term_list.index (widget)

      self.term_list.remove (widget)
      if not keep:
        widget._vte.get_parent().remove(widget._vte)
        widget._vte = None
      if nbpages == 1:
        if self.window.allocation.height != gtk.gdk.screen_height():
          self.window.resize(self.window.allocation.width, min(self.window.allocation.height - parent.get_tab_label(parent.get_nth_page(0)).height_request(), gtk.gdk.screen_height()))
        sibling = parent.get_nth_page(0)
        parent.remove(sibling)
        gdparent = parent.get_parent()
        if isinstance(gdparent, gtk.Window):
          gdparent.remove(parent)
          gdparent.add(sibling)
        elif isinstance(gdparent, gtk.Paned):
          if gdparent.get_child1() == parent:
            gdparent.remove(parent)
            gdparent.pack1(sibling)
          else:
            gdparent.remove(parent)
            gdparent.pack2(sibling)
        if isinstance(sibling, TerminatorTerm) and sibling.conf.titlebars and sibling.conf.extreme_tabs:
          sibling._titlebox.show()
    if self.conf.focus_on_close == 'prev' or ( self.conf.focus_on_close == 'auto' and focus_on_close == 'prev'):
      if index == 0: index = 1
      self.term_list[index - 1]._vte.grab_focus ()
      self._set_current_notebook_page_recursive(self.term_list[index - 1])
    elif self.conf.focus_on_close == 'next' or ( self.conf.focus_on_close == 'auto' and focus_on_close == 'next'):
      if index == len(self.term_list): index = index - 1
      self.term_list[index]._vte.grab_focus ()
      self._set_current_notebook_page_recursive(self.term_list[index])
      
    if len(self.term_list) == 1:
      self.term_list[0]._titlebox.hide()

    return True
    
  def closeterm (self, widget):
    if self._zoomed:
      # We are zoomed, pop back out to normal layout before closing
      dbg ("closeterm function called while in zoomed mode. Restoring previous layout before closing.")
      self.toggle_zoom(widget, not self._maximised)

    if self.remove(widget):
      self.group_hoover()
      return True
    return False

  def go_to (self, term, selector):
    current = self.term_list.index (term)
    target = selector (term)
    if not target is None:
        term = self.term_list[target]
        ##we need to set the current page of each notebook
        self._set_current_notebook_page_recursive(term)
        term._vte.grab_focus ()

  def _select_direction (self, term, matcher):
    current = self.term_list.index (term)
    current_geo = term.get_geometry ()
    best_index = None
    best_geo = None

    for i in range(0,len(self.term_list)):
        if i == current:
            continue
        possible = self.term_list[i]
        possible_geo = possible.get_geometry ()

        #import pprint
        #print "I am %d" % (current)
        #pprint.pprint(current_geo)
        #print "I saw %d" % (i)
        #pprint.pprint(possible_geo)

        if matcher (current_geo, possible_geo, best_geo):
            best_index = i
            best_geo = possible_geo
    #if best_index is None:
    #    print "nothing best"
    #else:
    #    print "sending %d" % (best_index)
    return best_index

  def _match_up (self, current_geo, possible_geo, best_geo):
    '''We want to find terminals that are fully above the top
       border, but closest in the y direction, breaking ties via
       the closest cursor x position.'''
    #print "matching up..."
    # top edge of the current terminal
    edge = current_geo['origin_y']
    # botoom edge of the possible target
    new_edge = possible_geo['origin_y']+possible_geo['span_y']

    # Width of the horizontal bar that splits terminals
    horizontalBar = self.term_list[0].get_parent().style_get_property('handle-size') + self.term_list[0]._titlebox.get_allocation().height
    # Vertical distance between two terminals
    distance = current_geo['offset_y'] - (possible_geo['offset_y'] + possible_geo['span_y'])
    if new_edge < edge:
        #print "new_edge < edge"
        if best_geo is None:
            #print "first thing left"
            return True
        best_edge = best_geo['origin_y']+best_geo['span_y']
        if new_edge > best_edge and distance == horizontalBar:
            #print "closer y"
            return True
        if new_edge == best_edge:
            #print "same y"

            cursor      = current_geo['origin_x']  + current_geo['cursor_x']
            new_cursor  = possible_geo['origin_x'] + possible_geo['cursor_x']
            best_cursor = best_geo['origin_x']     + best_geo['cursor_x']

            if abs(new_cursor - cursor) < abs(best_cursor - cursor):
                #print "closer x"
                return True
	else:
		if distance == horizontalBar:
			return True
    #print "fail"
    return False

  def _match_down (self, current_geo, possible_geo, best_geo):
    '''We want to find terminals that are fully below the bottom
       border, but closest in the y direction, breaking ties via
       the closest cursor x position.'''
    #print "matching down..."
    # bottom edge of the current terminal
    edge = current_geo['origin_y']+current_geo['span_y']
    # top edge of the possible target
    new_edge = possible_geo['origin_y']
    #print "edge: %d new_edge: %d" % (edge, new_edge)

    # Width of the horizontal bar that splits terminals
    horizontalBar = self.term_list[0].get_parent().style_get_property('handle-size') + self.term_list[0]._titlebox.get_allocation().height
    # Vertical distance between two terminals
    distance = possible_geo['offset_y'] - (current_geo['offset_y'] + current_geo['span_y'])
    if new_edge > edge:
        #print "new_edge > edge"
        if best_geo is None:
            #print "first thing right"
            return True
        best_edge = best_geo['origin_y']
        #print "best_edge: %d" % (best_edge)
        if new_edge < best_edge and distance == horizontalBar:
            #print "closer y"
            return True
        if new_edge == best_edge:
            #print "same y"

            cursor      = current_geo['origin_x']  + current_geo['cursor_x']
            new_cursor  = possible_geo['origin_x'] + possible_geo['cursor_x']
            best_cursor = best_geo['origin_x']     + best_geo['cursor_x']

            if abs(new_cursor - cursor) < abs(best_cursor - cursor):
                #print "closer x"
                return True
	else:
		if distance == horizontalBar:
			return True
    #print "fail"
    return False

  def _match_left (self, current_geo, possible_geo, best_geo):
    '''We want to find terminals that are fully to the left of
       the left-side border, but closest in the x direction, breaking
       ties via the closest cursor y position.'''
    #print "matching left..."
    # left-side edge of the current terminal
    edge = current_geo['origin_x']
    # right-side edge of the possible target
    new_edge = possible_geo['origin_x']+possible_geo['span_x']

    # Width of the horizontal bar that splits terminals
    horizontalBar = self.term_list[0].get_parent().style_get_property('handle-size') + self.term_list[0]._titlebox.get_allocation().height
    # Width of the vertical bar that splits terminals
    if self.term_list[0].is_scrollbar_present():
	    verticalBar = self.term_list[0].get_parent().style_get_property('handle-size') + self.term_list[0].get_parent().style_get_property('scroll-arrow-vlength')
    else:
	    verticalBar = self.term_list[0].get_parent().style_get_property('handle-size')
    # Horizontal distance between two terminals
    distance = current_geo['offset_x'] - (possible_geo['offset_x'] + possible_geo['span_x'])
    if new_edge < edge:
        #print "new_edge(%d) < edge(%d)" % (new_edge, edge)
        if best_geo is None:
            #print "first thing left"
            return True
        best_edge = best_geo['origin_x']+best_geo['span_x']
        if new_edge > best_edge and distance == verticalBar:
            #print "closer x (new_edge(%d) > best_edge(%d))" % (new_edge, best_edge)
            return True
        if new_edge == best_edge:
            #print "same x"

            cursor      = current_geo['origin_y']  + current_geo['cursor_y']
            new_cursor  = possible_geo['origin_y'] + possible_geo['cursor_y']
            best_cursor = best_geo['origin_y']     + best_geo['cursor_y']

            if abs(new_cursor - cursor) < abs(best_cursor - cursor) and distance <> horizontalBar:
                #print "closer y"
                return True
    #print "fail"
    return False

  def _match_right (self, current_geo, possible_geo, best_geo):
    '''We want to find terminals that are fully to the right of
       the right-side border, but closest in the x direction, breaking
       ties via the closest cursor y position.'''
    #print "matching right..."
    # right-side edge of the current terminal
    edge = current_geo['origin_x']+current_geo['span_x']
    # left-side edge of the possible target
    new_edge = possible_geo['origin_x']
    #print "edge: %d new_edge: %d" % (edge, new_edge)

    # Width of the horizontal bar that splits terminals
    horizontalBar = self.term_list[0].get_parent().style_get_property('handle-size') + self.term_list[0]._titlebox.get_allocation().height
    # Width of the vertical bar that splits terminals
    if self.term_list[0].is_scrollbar_present():
	    verticalBar = self.term_list[0].get_parent().style_get_property('handle-size') + self.term_list[0].get_parent().style_get_property('scroll-arrow-vlength')
    else:
	    verticalBar = self.term_list[0].get_parent().style_get_property('handle-size')
    # Horizontal distance between two terminals
    distance = possible_geo['offset_x'] - (current_geo['offset_x'] + current_geo['span_x'])
    if new_edge > edge:
        #print "new_edge > edge"
        if best_geo is None:
            #print "first thing right"
            return True
        best_edge = best_geo['origin_x']
        #print "best_edge: %d" % (best_edge)
        if new_edge < best_edge and distance == verticalBar:
            #print "closer x"
            return True
        if new_edge == best_edge:
            #print "same x"

            cursor      = current_geo['origin_y']  + current_geo['cursor_y']
            new_cursor  = possible_geo['origin_y'] + possible_geo['cursor_y']
            best_cursor = best_geo['origin_y']     + best_geo['cursor_y']

            if abs(new_cursor - cursor) < abs(best_cursor - cursor) and distance <> horizontalBar:
                #print "closer y"
                return True
    #print "fail"
    return False

  def _select_up (self, term):
    return self._select_direction (term, self._match_up)

  def _select_down (self, term):
    return self._select_direction (term, self._match_down)

  def _select_left (self, term):
    return self._select_direction (term, self._match_left)

  def _select_right (self, term):
    return self._select_direction (term, self._match_right)

  def go_next (self, term):
    self.go_to (term, self._select_next)

  def go_prev (self, term):
    self.go_to (term, self._select_prev)

  def go_up (self, term):
    self.go_to (term, self._select_up)

  def go_down (self, term):
    self.go_to (term, self._select_down)

  def go_left (self, term):
    self.go_to (term, self._select_left)

  def go_right (self, term):
    self.go_to (term, self._select_right)

  def _select_next (self, term):
    current = self.term_list.index (term)
    next = None
    if self.conf.cycle_term_tab:
      notebookpage = self.get_first_notebook_page(term)
      if notebookpage:
        last = self._notebook_last_term(notebookpage[1])
        first = self._notebook_first_term(notebookpage[1])
        if term == last:
          next = self.term_list.index(first)

    if next is None:
      if current == len (self.term_list) - 1:
        next = 0
      else:
        next = current + 1
    return next

  def _select_prev (self, term):
    current = self.term_list.index (term)
    previous = None
    if self.conf.cycle_term_tab:
      notebookpage = self.get_first_notebook_page(term)
      if notebookpage:
        last = self._notebook_last_term(notebookpage[1])
        first = self._notebook_first_term(notebookpage[1])
        if term == first:
          previous = self.term_list.index(last)

    if previous is None:
      if current == 0:
        previous = len (self.term_list) - 1
      else:
        previous = current - 1
    return previous

  def _set_current_notebook_page_recursive(self, widget):
    page = self.get_first_notebook_page(widget)
    while page:
      child = None
      page_num = page[0].page_num(page[1])
      page[0].set_current_page(page_num)
      page = self.get_first_notebook_page(page[0])

  def resizeterm (self, widget, keyname):
    vertical = False
    if keyname in ('Up', 'Down'):
      vertical = True
    elif keyname in ('Left', 'Right'):
      vertical = False
    else:
      return
    parent = self.get_first_parent_paned(widget,vertical)
    if parent == None:
      return
    
    #We have a corresponding parent pane
    #
    #allocation = parent.get_allocation()

    if keyname in ('Up', 'Down'):
      maxi = parent.get_child1().get_allocation().height + parent.get_child2().get_allocation().height - 1

    else:
      maxi = parent.get_child1().get_allocation().width + parent.get_child2().get_allocation().width - 1
    move = 10
    if keyname in ('Up', 'Left'):
      move = -10

    move = max(2, parent.get_position() + move)
    move = min(maxi, move)

    parent.set_position(move)

  def previous_tab(self, term):
    notebook = self.get_first_parent_notebook(term)
    if notebook:
      cur = notebook.get_current_page()
      pages = notebook.get_n_pages()
      if cur == 0:
        notebook.set_current_page(pages - 1)
      else:
        notebook.prev_page()
      # This seems to be required in some versions of (py)gtk.
      # Without it, the selection changes, but the displayed page doesn't change
      # Seen in gtk-2.12.11 and pygtk-2.12.1 at least.
      notebook.set_current_page(notebook.get_current_page())

  def next_tab(self, term):
    notebook = self.get_first_parent_notebook(term)
    if notebook:
      cur = notebook.get_current_page()
      pages = notebook.get_n_pages()
      if cur == pages - 1:
        notebook.set_current_page(0)
      else:
        notebook.next_page()
      notebook.set_current_page(notebook.get_current_page())

  def switch_to_tab(self, term, index):
    notebook = self.get_first_parent_notebook(term)
    if notebook:
      notebook.set_current_page(index)
      notebook.set_current_page(notebook.get_current_page())

  def move_tab(self, term, direction):
    dbg("moving to direction %s" % direction)
    (notebook, page) = self.get_first_notebook_page(term)
    page_num = notebook.page_num(page)
    nbpages = notebook.get_n_pages()
    #dbg ("%s %s %s %s" % (page_num, nbpages,notebook, page))
    if page_num == 0 and direction == 'left':
      new_page_num = nbpages  
    elif page_num == nbpages - 1 and direction == 'right':
      new_page_num = 0
    elif direction == 'left':
      new_page_num = page_num - 1
    elif direction == 'right':
      new_page_num = page_num + 1
    else:
      dbg("[ERROR] unhandled combination in move_tab: direction = %s page_num = %d" % (direction, page_num))
      return False
    notebook.reorder_child(page, new_page_num)
    return True
    
  def get_first_parent_notebook(self, widget):
    if isinstance (widget, gtk.Window):
      return None
    parent = widget.get_parent()
    if isinstance (parent, gtk.Notebook):
        return parent
    return self.get_first_parent_notebook(parent)
  
  def get_first_parent_paned (self, widget, vertical = None):
    """This method returns the first parent pane of a widget.
    if vertical is True returns the first VPaned
    if vertical is False return the first Hpaned
    if is None return the First Paned"""
    if isinstance (widget, gtk.Window):
      return None
    parent = widget.get_parent()
    if isinstance (parent, gtk.Paned) and vertical is None:
        return parent
    if isinstance (parent, gtk.VPaned) and vertical:
      return parent
    elif isinstance (parent, gtk.HPaned) and not vertical:
      return parent
    return self.get_first_parent_paned(parent, vertical)

  def get_first_notebook_page(self, widget):
    if isinstance (widget, gtk.Window) or widget is None:
      return None
    parent = widget.get_parent()
    if isinstance (parent, gtk.Notebook):
      page = -1
      for i in xrange(0, parent.get_n_pages()):
        if parent.get_nth_page(i) == widget:
          return (parent, widget)
    return self.get_first_notebook_page(parent)

  def reconfigure_vtes (self):
    for term in self.term_list:
      term.reconfigure_vte ()

  def toggle_zoom(self, widget, fontscale = False):
    if not self._zoomed:
      widget._titlebars = widget._titlebox.get_property ('visible')
      dbg ('toggle_zoom: not zoomed. remembered titlebar setting of %s'%widget._titlebars)
      if widget._titlebars:
        widget._titlebox.hide()
      self.zoom_term (widget, fontscale)
    else:
      dbg ('toggle_zoom: zoomed. restoring titlebar setting of %s'%widget._titlebars)
      self.unzoom_term (widget, True)
      if widget._titlebars and \
          len(self.term_list) > 1 \
          and \
          (isinstance(widget, TerminatorTerm) and isinstance(widget.get_parent(),gtk.Paned))\
          :
        widget._titlebox.show()

    widget._vte.grab_focus()
    widget._titlebox.update()

  def zoom_term (self, widget, fontscale = False):
    """Maximize to full window an instance of TerminatorTerm."""
    self.old_font = widget._vte.get_font ()
    self.old_columns = widget._vte.get_column_count ()
    self.old_rows = widget._vte.get_row_count ()
    self.old_parent = widget.get_parent()

    if isinstance(self.old_parent, gtk.Window):
      return
    if isinstance(self.old_parent, gtk.Notebook):
      self.old_page = self.old_parent.get_current_page()

    self.window_child = self.window.get_children()[0]
    self.window.remove(self.window_child)
    self.old_parent.remove(widget)
    self.window.add(widget)
    self._zoomed = True

    if fontscale:
      self.cnid = widget.connect ("size-allocate", self.zoom_scale_font)
      dbg ('zoom_term: registered font zoom handler to %s with cnid: %s'%(widget, self.cnid))
    else:
      self._maximised = True

    widget._vte.grab_focus ()

  def zoom_scale_font (self, widget, allocation):
    new_columns = widget._vte.get_column_count ()
    new_rows = widget._vte.get_row_count ()
    new_font = widget._vte.get_font ()

    dbg ('zoom_scale_font: Disconnecting %s from %s'%(self.cnid, widget))
    widget.disconnect (self.cnid)

    dbg ('zoom_scale_font: I just went from %dx%d to %dx%d. Raa!'%(self.old_columns, self.old_rows, new_columns, new_rows))

    if new_rows != self.old_rows:
      titleheight = widget._titlebox.get_allocation().height
      vtecharheight =  widget._vte.get_char_height()
      rowdiff = new_rows - self.old_rows + 2
      dbg ('zoom_scale_font: titlebox height is %d, char_height is %d'%(titleheight, vtecharheight))
      dbg ('zoom_scale_font: lhs: %d, rhs: %f'%((titleheight / vtecharheight), rowdiff))
      care_height = (rowdiff <= vtecharheight / rowdiff)
      dbg ('zoom_scale_font: caring about height difference: %s'%care_height)
    else:
      care_height = False
    
    if (new_rows <= self.old_rows) or care_height or (new_columns <= self.old_columns):
      dbg ('zoom_scale_font: Which means I didnt scale on one axis (col: %s, row: %s). Bailing'%((new_columns <= self.old_columns), (new_rows <= self.old_rows)))
      return

    old_area = self.old_columns * self.old_rows
    new_area = new_columns * new_rows
    area_factor = new_area / old_area

    dbg ('zoom_scale_font: My area changed from %d characters to %d characters, a factor of %f.'%(old_area, new_area, area_factor))

    new_font.set_size (self.old_font.get_size() * (area_factor / 2))
    dbg ('zoom_scale_font: Scaled font from %f to %f'%(self.old_font.get_size () / pango.SCALE, new_font.get_size () / pango.SCALE))
    widget._vte.set_font (new_font)

  def unzoom_term (self, widget, fontscale = False):
    """Proof of concept: Go back to previous application                                 
    widget structure.                        
    """
    if self._zoomed:
      if fontscale:
        widget._vte.set_font (self.old_font)
      self._zoomed = False
      self._maximised = False

      self.window.remove(widget)
      self.window.add(self.window_child)
      if isinstance(self.old_parent, gtk.Notebook):
        self.old_parent.insert_page(widget, None, self.old_page)
        self.old_parent.set_tab_label(widget, TerminatorNotebookTabLabel("", self.old_parent, self))
        self.old_parent.set_tab_label_packing(widget, True, True, gtk.PACK_START)
        if self._tab_reorderable:
          self.old_parent.set_tab_reorderable(widget, True)
        self.old_parent.set_current_page(self.old_page)

      else:
        self.old_parent.add(widget)

      widget._vte.grab_focus ()

  def edit_profile (self, widget):
    if not self.options:
      self.options = ProfileEditor(self)
      self.options.go()
 
  def group_emit (self, terminatorterm, group, type, event):
    for term in self.term_list:
      if term != terminatorterm and term._group == group:
        term._vte.emit (type, event)

  def group_hoover (self):
    destroy = []
    for group in self.groupings:
      save = False
      for term in self.term_list:
        if term._group == group:
          save = True

      if not save:
        destroy.append (group)

    for group in destroy:
      self.groupings.remove (group)
