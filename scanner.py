#!/usr/bin/env python3
################################################################################
# Link Scanner                                                                 #
#                                                                              #
# Copyright (C) 2020 J.C. Fields (jcfields@jcfields.dev).                      #
#                                                                              #
# Permission is hereby granted, free of charge, to any person obtaining a copy #
# of this software and associated documentation files (the "Software"), to     #
# deal in the Software without restriction, including without limitation the   #
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or  #
# sell copies of the Software, and to permit persons to whom the Software is   #
# furnished to do so, subject to the following conditions:                     #
#                                                                              #
# The above copyright notice and this permission notice shall be included in   #
# all copies or substantial portions of the Software.                          #
#                                                                              #
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR   #
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,     #
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  #
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER       #
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING      #
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS #
# IN THE SOFTWARE.                                                             #
################################################################################

# from standard library
import json
import os
import re
import time
import urllib
import webbrowser

# threading
from contextlib import closing
from queue import Queue
import threading

# GUI toolkit
import wx
from wx.adv import AboutBox

# HTML parser
from bs4 import BeautifulSoup, SoupStrainer

# HTTP
import requests

################################################################################
# Global variables                                                             #
################################################################################

# about
TITLE = 'Link Scanner'
COPYRIGHT = '© 2020 J.C. Fields <jcfields@jcfields.dev>'
WEB_SITE_URL = 'https://github.com/jcfieldsdev/link-scanner'
VERSION = '1.0.0'

MAIN_FRAME_SIZE = (1000, 600)
SUB_FRAME_SIZE = (600, 400)

# scan settings
HTML_TAGS = ('a', 'img', 'link')
CONTENT_TYPES = ('text/html', 'application/xhtml+xml')
ACCEPT_SCHEMES = ('http', 'https')
IGNORE_SCHEMES = ('mailto', 'javascript') # not reported under "Skipped" filter

# link follow modes
IGNORE = 0
CHECK = 1
FOLLOW = 2

# scanner result event statuses
TIMEOUT = 0
SKIPPED = 1
COMPLETED = 2

# scanner result event server types
ANY = 0
INTERNAL = 1
EXTERNAL = 2

# rule types
INCLUDE = False
EXCLUDE = True

# unique IDs for worker thread
EVT_RESULT_ID = wx.NewIdRef(count=1)
ID_START = wx.NewIdRef(count=1)
ID_STOP = wx.NewIdRef(count=1)

# HTTP status codes
STATUS_CODES = {
	'200': 'OK',
	'201': 'Created',
	'202': 'Accepted',
	'203': 'Non-Authoritative Information',
	'204': 'No Content',
	'205': 'Reset Content',
	'206': 'Partial Content',
	'300': 'Multiple Choices',
	'301': 'Moved Permanently',
	'302': 'Found',
	'303': 'See Other',
	'304': 'Not Modified',
	'305': 'Use Proxy',
	'306': 'Switch Proxy',
	'307': 'Temporary Redirect',
	'308': 'Permanent Redirect',
	'400': 'Bad Request',
	'401': 'Unauthorized',
	'403': 'Forbidden',
	'404': 'Not Found',
	'405': 'Method Not Allowed',
	'406': 'Not Accepted',
	'407': 'Proxy Authentication Required',
	'408': 'Request Timed Out',
	'409': 'Conflict',
	'410': 'Gone',
	'411': 'Length Required',
	'412': 'Precondition Failed',
	'413': 'Payload Too Large',
	'414': 'URI Too Large',
	'415': 'Unsupported Media Type',
	'416': 'Range Not Satisfiable',
	'417': 'Expectation Failed',
	'421': 'Misdirected Request',
	'425': 'Too Early',
	'426': 'Upgrade Required',
	'428': 'Precondition Required',
	'429': 'Too Many Requests',
	'431': 'Request Header Fields Too Large',
	'500': 'Internal Server Error',
	'501': 'Not Implemented',
	'502': 'Bad Gateway',
	'503': 'Service Unavailable',
	'504': 'Gateway Timeout',
	'505': 'HTTP Version Not Supported',
	'506': 'Variant Also Negotiates',
	'510': 'Not Extended',
	'511': 'Network Authentication Required'
}

################################################################################
# MainFrame class                                                              #
################################################################################

class MainFrame(wx.Frame):
	def __init__(self):
		self.config = wx.Config(TITLE)
		self.options = {
			'url':      'https://',
			'redirect': True,
			'query':    True,
			'external': [False, True, False],
			'internal': [False, False, True],
			'depth':    1,
			'threads':  1,
			'delay':    0,
			'timeout':  10,
			'local':    True,
			'remote':   True,
			'status':   [True, False, True, True, True, True]
		}
		self.rules = []

		self.read_config()

		size = self.options.get('size', MAIN_FRAME_SIZE)
		wx.Frame.__init__(self, None, title=TITLE, size=size)

		self.Bind(wx.EVT_CLOSE, self.close)

		self.status = self.CreateStatusBar(2)
		self.panel = MainPanel(self, self.options, self.rules)
		self.create_menu()

	def create_menu(self):
		menu_bar = wx.MenuBar()
		menu_file = wx.Menu()

		self.item_start = menu_file.Append(ID_START, '&Start', 'Start scan')
		self.item_stop = menu_file.Append(ID_STOP, 'S&top', 'Stop scan')
		menu_file.AppendSeparator()
		item_close = menu_file.Append(wx.ID_EXIT, '&Close', 'Close the program')

		menu_help = wx.Menu()
		item_web_site = menu_help.Append(
			wx.ID_ANY, 'Visit &Web Site',
			'Visit the program web site'
		)
		item_about = menu_help.Append(
			wx.ID_ABOUT, '&About {}'.format(TITLE),
			'About this program'
		)

		self.item_stop.Enable(False)

		self.Bind(wx.EVT_MENU, self.panel.enter, self.item_start)
		self.Bind(wx.EVT_MENU, self.panel.stop, self.item_stop)
		self.Bind(wx.EVT_MENU, self.close, item_close)
		self.Bind(wx.EVT_MENU, self.open_web_site, item_web_site)
		self.Bind(wx.EVT_MENU, self.about, item_about)

		menu_bar.Append(menu_file, '&File')
		menu_bar.Append(menu_help, '&Help')
		self.SetMenuBar(menu_bar)

	def read_config(self):
		try:
			options = self.config.Read('options')
			rules = self.config.Read('rules')

			if options != '':
				self.options.update(json.loads(options))

			if rules != '':
				self.rules = json.loads(rules)

		except:
			wx.MessageBox(
				'Could not read configuration file.',
				'Error', wx.OK | wx.ICON_ERROR
			)

	def write_config(self):
		size = self.GetSize().Get() # converts size object to tuple

		if size != MAIN_FRAME_SIZE:
			self.options['size'] = size

		try:
			self.config.Write('options', json.dumps(self.options))
			self.config.Write('rules', json.dumps(self.rules))
		except:
			wx.MessageBox(
				'Could not write configuration file.',
				'Error', wx.OK | wx.ICON_ERROR
			)

	def open_web_site(self, event=None):
		webbrowser.open(WEB_SITE_URL)

	def about(self, event=None):
		dialog = wx.adv.AboutDialogInfo()
		dialog.SetName(TITLE)
		dialog.SetCopyright(COPYRIGHT)
		dialog.SetVersion(VERSION)

		wx.adv.AboutBox(dialog)

	def close(self, event=None):
		self.panel.stop()
		self.write_config()
		self.Destroy()

################################################################################
# MainPanel class                                                              #
################################################################################

class MainPanel(wx.Panel):
	def __init__(self, parent, options, rules):
		wx.Panel.__init__(self, parent)
		self.parent = parent
		self.options = options
		self.rules = rules

		self.paused = False
		self.done = False
		self.scanner = None
		self.results = []
		self.rows = 0
		self.q = ''

		self.list_ctrl = self.create_list_ctrl()
		self.info_sizer = self.create_info_sizer()

		self.sizer = wx.BoxSizer(wx.VERTICAL)
		self.sizer.AddMany((
			(self.create_url_sizer(), 0, wx.ALL | wx.EXPAND, 5),
			(self.create_option_sizer(), 0, wx.ALL | wx.EXPAND, 5),
			(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 5),
			(self.info_sizer, 0, wx.EXPAND | wx.RESERVE_SPACE_EVEN_IF_HIDDEN, 5)
		))
		self.SetSizer(self.sizer)

		self.load_options()
		self.Connect(-1, -1, EVT_RESULT_ID, self.update)

		self.update_status_action()
		self.update_status_items()

	def create_url_sizer(self):
		self.url = wx.TextCtrl(self, ID_START, style=wx.TE_PROCESS_ENTER)
		self.url.Bind(wx.EVT_TEXT, self.save_options)
		self.url.Bind(wx.EVT_TEXT_ENTER, self.enter, id=ID_START)

		self.button_start = wx.Button(self, ID_START, label='&Start')
		self.button_start.Bind(wx.EVT_BUTTON, self.enter, id=ID_START)

		self.button_stop = wx.Button(self, ID_STOP, label='S&top')
		self.button_stop.Disable()
		self.button_stop.Bind(wx.EVT_BUTTON, self.stop, id=ID_STOP)

		sizer = wx.BoxSizer(wx.HORIZONTAL)
		sizer.AddMany((
			(wx.StaticText(self, label='URL:'), 0, wx.CENTER),
			(self.url, 1, wx.ALL, 5),
			(self.button_start, 0, wx.ALL, 5),
			(self.button_stop, 0, wx.TOP | wx.RIGHT | wx.BOTTOM, 5)
		))

		return sizer

	def create_option_sizer(self):
		sizer = wx.BoxSizer(wx.HORIZONTAL)
		sizer.AddMany((
			(self.create_connections_box(), 1, wx.ALL | wx.EXPAND),
			(self.create_links_box(), 1, wx.ALL | wx.EXPAND),
			(self.create_filter_box(), 1, wx.ALL | wx.EXPAND)
		))

		return sizer

	def create_filter_box(self):
		self.search = wx.SearchCtrl(self)
		self.search.Bind(wx.EVT_TEXT, self.filter)

		self.status = (
			wx.CheckBox(self, label='Timeouts'),
			wx.CheckBox(self, label='Skipped'),
			wx.CheckBox(self, label='200 (Success)'),
			wx.CheckBox(self, label='300 (Redirects)'),
			wx.CheckBox(self, label='400 (Client Errors)'),
			wx.CheckBox(self, label='500 (Server Errors)')
		)

		self.local = wx.CheckBox(self, label='Internal')
		self.remote = wx.CheckBox(self, label='External')

		self.local.Bind(wx.EVT_CHECKBOX, self.filter)
		self.remote.Bind(wx.EVT_CHECKBOX, self.filter)

		sizer = wx.FlexGridSizer(cols=2, gap=(5, 5))
		sizer.AddMany((self.local, self.remote))

		for element in self.status:
			sizer.Add(element)
			element.Bind(wx.EVT_CHECKBOX, self.filter)

		box = wx.StaticBoxSizer(wx.StaticBox(self, -1, 'Filter'), wx.VERTICAL)
		box.AddMany(((self.search, 1, wx.BOTTOM | wx.EXPAND, 10), (sizer, 0)))

		return box

	def create_links_box(self):
		self.external = (
			wx.RadioButton(self, label='Ignore', style=wx.RB_GROUP),
			wx.RadioButton(self, label='Check'),
			wx.RadioButton(self, label='Follow')
		)

		external_sizer = wx.BoxSizer(wx.HORIZONTAL)
		external_sizer.AddMany(self.external)

		self.internal = (
			wx.RadioButton(self, label='Ignore', style=wx.RB_GROUP),
			wx.RadioButton(self, label='Check'),
			wx.RadioButton(self, label='Follow')
		)

		internal_sizer = wx.BoxSizer(wx.HORIZONTAL)
		internal_sizer.AddMany(self.internal)

		self.depth = wx.SpinCtrl(self, initial=1, min=1, size=(50, -1))
		self.depth.Bind(wx.EVT_SPINCTRL, self.save_options)

		button_rules = wx.Button(self, label='Edit &Rules')
		button_rules.Bind(wx.EVT_BUTTON, self.open_rules_editor)

		sizer = wx.FlexGridSizer(cols=2, gap=(5, 5))
		sizer.AddMany((
			wx.StaticText(self, label='Internal links:'), internal_sizer,
			wx.StaticText(self, label='External links:'), external_sizer,
			wx.StaticText(self, label='Recursion depth:'), self.depth,
			wx.StaticText(self, label='Matching rules:'), button_rules
		))

		for element in self.external:
			element.Bind(wx.EVT_RADIOBUTTON, self.save_options)

		for element in self.internal:
			element.Bind(wx.EVT_RADIOBUTTON, self.save_options)

		box = wx.StaticBoxSizer(wx.StaticBox(self, -1, 'Links'), wx.VERTICAL)
		box.Add(sizer)

		return box

	def create_connections_box(self):
		size = (50, -1)
		self.threads = wx.SpinCtrl(self, initial=1, min=1, size=size)
		self.delay = wx.SpinCtrl(self, initial=0, min=0, size=size)
		self.timeout = wx.SpinCtrl(self, initial=10, min=1, size=size)

		self.threads.Bind(wx.EVT_SPINCTRL, self.save_options)
		self.delay.Bind(wx.EVT_SPINCTRL, self.save_options)
		self.timeout.Bind(wx.EVT_SPINCTRL, self.save_options)

		sizer = wx.FlexGridSizer(cols=2, gap=(5, 5))
		sizer.AddMany((
			wx.StaticText(self, label='Number of threads:'), self.threads,
			wx.StaticText(self, label='Delay:'), self.delay,
			wx.StaticText(self, label='Timeout:'), self.timeout
		))

		self.redirect = wx.CheckBox(self, label='Follow redirects.')
		self.query = wx.CheckBox(self, label='Follow query strings.')

		self.redirect.Bind(wx.EVT_CHECKBOX, self.save_options)
		self.query.Bind(wx.EVT_CHECKBOX, self.save_options)

		box = wx.StaticBoxSizer(
			wx.StaticBox(self, -1, 'Connections'),
			wx.VERTICAL
		)
		box.AddMany((
			sizer,
			(self.redirect, 0, wx.TOP, 5),
			(self.query, 0, wx.TOP, 5)
		))

		return box

	def create_list_ctrl(self):
		element = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)

		element.InsertColumn(0, 'Status', width=75)
		element.InsertColumn(1, 'Link to', width=445)
		element.InsertColumn(2, 'Appears on', width=445)

		element.Bind(wx.EVT_LIST_ITEM_SELECTED, self.list_selected)
		element.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.list_deselected)

		return element

	def create_info_sizer(self):
		size = (80, -1) # text label size

		self.text_status = wx.StaticText(self, label='')
		self.text_link = wx.TextCtrl(self)
		self.text_source = wx.TextCtrl(self)

		self.text_status.SetFont(self.text_status.GetFont().MakeBold())

		status_sizer = wx.BoxSizer(wx.HORIZONTAL)
		status_sizer.AddMany((
			(wx.StaticText(self, label='Status:', size=size)),
			self.text_status
		))

		self.button_link = wx.Button(self, label='&Open')
		self.button_link.Bind(wx.EVT_BUTTON, self.open_link)
		self.button_link.Disable()

		link_sizer = wx.BoxSizer(wx.HORIZONTAL)
		link_sizer.AddMany((
			(wx.StaticText(self, label='Link to:', size=size), 0, wx.CENTER),
			(self.text_link, 1),
			(self.button_link, 0, wx.LEFT, 5)
		))

		self.button_source = wx.Button(self, label='Op&en')
		self.button_source.Bind(wx.EVT_BUTTON, self.open_source)
		self.button_source.Disable()

		source_sizer = wx.BoxSizer(wx.HORIZONTAL)
		source_sizer.AddMany((
			(wx.StaticText(self, label='Appears on:', size=size), 0, wx.CENTER),
			(self.text_source, 1),
			(self.button_source, 0, wx.LEFT, 5)
		))

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.AddMany((
			(status_sizer, 0, wx.ALL | wx.EXPAND, 5),
			(link_sizer, 0, wx.ALL | wx.EXPAND, 5),
			(source_sizer, 0, wx.ALL | wx.EXPAND, 5)
		))

		return sizer

	def load_options(self):
		self.url.ChangeValue(self.options['url']) # does not fire event
		self.depth.SetValue(self.options['depth'])
		self.threads.SetValue(self.options['threads'])
		self.delay.SetValue(self.options['delay'])
		self.timeout.SetValue(self.options['timeout'])
		self.redirect.SetValue(self.options['redirect'])
		self.query.SetValue(self.options['query'])

		for i, element in enumerate(self.external):
			element.SetValue(self.options['external'][i])

		for i, element in enumerate(self.internal):
			element.SetValue(self.options['internal'][i])

		self.local.SetValue(self.options['local'])
		self.remote.SetValue(self.options['remote'])

		for i, element in enumerate(self.status):
			element.SetValue(self.options['status'][i])

	def save_options(self, event=None):
		self.options['url'] = self.url.GetValue()
		self.options['depth'] = self.depth.GetValue()
		self.options['threads'] = self.threads.GetValue()
		self.options['delay'] = self.delay.GetValue()
		self.options['timeout'] = self.timeout.GetValue()
		self.options['redirect'] = self.redirect.IsChecked()
		self.options['query'] = self.query.IsChecked()
		self.options['local'] = self.local.IsChecked()
		self.options['remote'] = self.remote.IsChecked()

		self.q = self.search.GetValue()

		for i, element in enumerate(self.external):
			self.options['external'][i] = element.GetValue()

		for i, element in enumerate(self.internal):
			self.options['internal'][i] = element.GetValue()

		for i, element in enumerate(self.status):
			self.options['status'][i] = element.GetValue()

	def read_item(self, m, n):
		return self.list_ctrl.GetItem(m, n).GetText()

	def list_selected(self, event=None):
		self.button_link.Enable()
		self.button_source.Enable()
		self.sizer.Show(self.info_sizer)
		self.update_info()

	def list_deselected(self, event=None):
		self.button_link.Disable()
		self.button_source.Disable()
		self.sizer.Hide(self.info_sizer)

	def update_info(self):
		selected = self.list_ctrl.GetNextSelected(-1)

		if selected < 0:
			return

		status = self.read_item(selected, 0)

		if status in STATUS_CODES:
			status = '{} ({})'.format(status, STATUS_CODES[status])

		self.text_status.SetLabel(status)
		self.text_link.SetLabel(self.read_item(selected, 1))
		self.text_source.SetValue(self.read_item(selected, 2))

	def update_status_action(self):
		if self.scanner is not None:
			if self.paused:
				status = 'Paused'
			else:
				status = 'Scanning...'
		else:
			if self.done:
				status = 'Done'
			else:
				status = 'Stopped'

		self.parent.status.SetStatusText(status, 0)

	def update_status_items(self):
		self.parent.status.SetStatusText('{:d} items'.format(self.rows), 1)

	def open_browser(self, link):
		if link != '':
			webbrowser.open(link)

	def open_link(self, event=None):
		self.open_browser(self.text_link.GetValue())

	def open_source(self, event=None):
		webbrowser.open(self.text_source.GetValue())

	def open_rules_editor(self, event=None):
		frame = RulesFrame(self, self.rules)
		frame.Show()
		frame.Center()

	def get_radio_value(self, element, default):
		return next((k for k, v in enumerate(element) if v), default)

	def enter(self, event=None):
		if self.scanner is None:
			self.start()
		else:
			self.pause()

	def start(self, event=None):
		self.done = False
		self.results = []
		self.rows = 0

		self.button_stop.Enable()
		self.button_start.SetLabel('Pau&se')
		self.parent.item_stop.Enable(True)
		self.parent.item_start.SetItemLabel('Pau&se')

		self.list_ctrl.DeleteAllItems()
		self.update_status_items()

		self.scanner = Scanner(self, (
			self.url.GetValue(),
			self.options['depth'],
			self.options['threads'],
			self.options['delay'],
			self.options['timeout'],
			self.options['redirect'],
			self.options['query'],
			self.get_radio_value(self.options['external'], CHECK),
			self.get_radio_value(self.options['internal'], FOLLOW)
		), self.rules)
		self.scanner.start()

		self.update_status_action()

	def pause(self):
		if self.paused:
			self.button_start.SetLabel('Pau&se')
			self.parent.item_start.SetItemLabel('Pau&se')
		else:
			self.button_start.SetLabel('Re&sume')
			self.parent.item_start.SetItemLabel('Re&sume')

		self.paused = not self.paused
		self.scanner.pause()

		self.update_status_action()

	def stop(self, event=None):
		self.button_start.Enable()
		self.button_stop.Disable()
		self.button_start.SetLabel('&Start')
		self.parent.item_start.Enable(True)
		self.parent.item_stop.Enable(False)
		self.parent.item_start.SetItemLabel('&Start')

		if self.paused:
			self.scanner.pause() # resolves unresolved pause event
			self.paused = False

		if self.scanner is not None:
			self.scanner.stop()
			self.scanner = None

		self.update_status_action()

	def filter(self, event=None):
		self.save_options()

		self.list_ctrl.DeleteAllItems()
		self.rows = 0

		for row in self.results:
			self.insert_row(row)

		self.update_status_items()

	def update(self, event):
		if event.status == COMPLETED:
			self.done = True
			self.stop()
		else:
			row = (event.status, event.link, event.source, event.server)
			self.results.append(row)
			self.insert_row(row)

	def insert_row(self, row):
		status, link, source, server = row

		# checks visibility of row
		if status == TIMEOUT:
			n = TIMEOUT
			text = 'Timeout'
		elif status == SKIPPED:
			n = SKIPPED
			text = 'Skipped'
		else:
			n = status // 100
			text = str(status)

		if server == INTERNAL and not self.options['local']:
			return

		if server == EXTERNAL and not self.options['remote']:
			return

		if not self.options['status'][n]:
			return

		if self.q != '' and link.find(self.q) < 0 and source.find(self.q) < 0:
			return

		self.list_ctrl.InsertItem(self.rows, text)
		self.list_ctrl.SetItem(self.rows, 1, link)
		self.list_ctrl.SetItem(self.rows, 2, source)

		# scrolls to bottom
		self.list_ctrl.EnsureVisible(self.list_ctrl.GetItemCount() - 1)

		self.update_status_items()
		self.rows += 1

################################################################################
# RulesFrame class                                                             #
################################################################################

class RulesFrame(wx.Frame):
	def __init__(self, parent, rules):
		wx.Frame.__init__(self, parent, title='Link Rules', size=SUB_FRAME_SIZE)
		self.panel = RulesPanel(self, rules)

	def close(self, event=None):
		self.Destroy()

################################################################################
# RulesPanel class                                                             #
################################################################################

class RulesPanel(wx.Panel):
	def __init__(self, parent, rules):
		wx.Panel.__init__(self, parent)
		self.rules = rules

		self.list_ctrl = self.create_list_ctrl()

		self.sizer = wx.BoxSizer(wx.VERTICAL)
		self.sizer.AddMany((
			(self.list_ctrl, 3, wx.ALL | wx.EXPAND, 5),
			(self.create_edit_sizer(), 0, wx.EXPAND, 5),
			(self.create_button_sizer(parent), 0, wx.EXPAND, 5)
		))
		self.SetSizer(self.sizer)

		self.reload()

	def create_list_ctrl(self):
		element = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)

		element.InsertColumn(0, 'Condition', width=75)
		element.InsertColumn(1, 'Scope', width=75)
		element.InsertColumn(2, 'Rule', width=410)

		element.Bind(wx.EVT_LIST_ITEM_SELECTED, self.list_selected)
		element.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.list_deselected)

		return element

	def create_edit_sizer(self):
		size = (80, -1) # text label size

		self.choices_condition = ('Include', 'Exclude')
		self.choices_scope = ('Any', 'Internal', 'External')

		self.select_condition = wx.Choice(self, choices=self.choices_condition)
		self.select_scope = wx.Choice(self, choices=self.choices_scope)
		self.text_match = wx.TextCtrl(self)

		self.text_match.Bind(wx.EVT_TEXT, self.toggle_add_button)

		condition_sizer = wx.BoxSizer(wx.HORIZONTAL)
		condition_sizer.AddMany((
			(wx.StaticText(self, label='Condition:', size=size)),
			self.select_condition
		))

		scope_sizer = wx.BoxSizer(wx.HORIZONTAL)
		scope_sizer.AddMany((
			(wx.StaticText(self, label='Scope:', size=size)),
			self.select_scope
		))

		match_sizer = wx.BoxSizer(wx.HORIZONTAL)
		match_sizer.AddMany((
			(wx.StaticText(self, label='Match:', size=size), 0),
			(self.text_match, 1)
		))

		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.AddMany((
			(condition_sizer, 0, wx.ALL | wx.EXPAND, 5),
			(scope_sizer, 0, wx.ALL | wx.EXPAND, 5),
			(match_sizer, 0, wx.ALL | wx.EXPAND, 5)
		))

		# selects default choices
		self.select_condition.Select(0)
		self.select_scope.Select(0)

		return sizer

	def create_button_sizer(self, parent):
		button_close = wx.Button(self, label='&Close')
		self.button_add = wx.Button(self, label='&Add')
		self.button_modify = wx.Button(self, label='&Modify')
		self.button_remove = wx.Button(self, label='&Remove')

		button_close.Bind(wx.EVT_BUTTON, parent.close)
		self.button_add.Bind(wx.EVT_BUTTON, self.add)
		self.button_modify.Bind(wx.EVT_BUTTON, self.modify)
		self.button_remove.Bind(wx.EVT_BUTTON, self.remove)

		self.button_add.Disable()
		self.button_modify.Disable()
		self.button_remove.Disable()

		sizer = wx.BoxSizer(wx.HORIZONTAL)
		sizer.AddMany((
			(self.button_add, 0, wx.ALL, 5),
			(self.button_modify, 0, wx.TOP | wx.RIGHT | wx.BOTTOM, 5),
			(self.button_remove, 0, wx.TOP | wx.RIGHT | wx.BOTTOM, 5)
		))
		sizer.AddStretchSpacer()
		sizer.Add(button_close, 0, wx.ALL, 5)

		return sizer

	def toggle_add_button(self, event=None):
		self.button_add.Enable(self.text_match.GetValue() != '')

	def list_selected(self, event=None):
		self.button_modify.Enable()
		self.button_remove.Enable()

		selected = self.list_ctrl.GetNextSelected(-1)
		condition, scope, match = self.rules[selected]

		self.select_condition.SetSelection(condition)
		self.select_scope.SetSelection(scope)
		self.text_match.SetValue(match)

	def list_deselected(self, event=None):
		self.button_modify.Disable()
		self.button_remove.Disable()

		self.select_condition.SetSelection(INCLUDE)
		self.select_scope.SetSelection(INTERNAL)
		self.text_match.SetValue('')

	def add(self, event=None):
		condition = self.select_condition.GetSelection()
		scope = self.select_scope.GetSelection()
		match = self.text_match.GetValue()

		if match != '':
			self.rules.append((condition, scope, match))

			self.reload()
			self.list_ctrl.Select(len(self.rules) - 1)

	def modify(self, event=None):
		condition = self.select_condition.GetSelection()
		scope = self.select_scope.GetSelection()
		match = self.text_match.GetValue()

		selected = self.list_ctrl.GetNextSelected(-1)
		self.rules[selected] = (condition, scope, match)

		self.reload()
		self.list_ctrl.Select(selected)

	def remove(self, event=None):
		selected = self.list_ctrl.GetNextSelected(-1)
		del self.rules[selected]

		self.list_deselected()
		self.reload()

	def reload(self):
		self.list_ctrl.DeleteAllItems()

		for i, rule in enumerate(self.rules):
			condition, scope, match = rule

			self.list_ctrl.InsertItem(i, self.choices_condition[condition])
			self.list_ctrl.SetItem(i, 1, self.choices_scope[scope])
			self.list_ctrl.SetItem(i, 2, match)

################################################################################
# Scanner class                                                                #
################################################################################

class Scanner(threading.Thread):
	def __init__(self, parent, options, rules):
		threading.Thread.__init__(self)
		self.parent = parent

		self.paused = None
		self.stopped = False

		self.url = options[0]
		self.depth = options[1]
		self.threads = options[2]
		self.delay = options[3]
		self.timeout = options[4]
		self.redirect = options[5]
		self.query = options[6]
		self.external = options[7]
		self.internal = options[8]

		self.rules = list(map(lambda r: (r[0], r[1], re.compile(r[2])), rules))
		self.links = set([self.url]) # link cache to avoid repeating links
		self.domain = urllib.parse.urlparse(self.url).netloc

		self.pool = ThreadPool(self.threads)
		self.pool.add(Task(
			link=self.url,
			source='',
			depth=0,
			timeout=self.timeout,
			redirect=self.redirect,
			server=INTERNAL,
			follow=True
		))

	def run(self):
		self.pool.start()

		for task in self.pool.poll_completed_tasks():
			if self.paused is not None: # paused by user
				self.paused.wait()

			if self.stopped: # stopped by user
				return

			if task.server == INTERNAL and task.redirected: # redirected
				parsed = urllib.parse.urlparse(task.link)

				# changes server type if domain has changed
				if parsed.netloc != self.domain:
					task.server = EXTERNAL

			if task.error: # error encountered
				self.error(task)
				continue

			self.tell(task.status, task.link, task.source, task.server)

			# domain has changed, so check follow option again
			# before processing page links
			if task.server == EXTERNAL and self.external != FOLLOW:
				continue

			# adds links found on page to tasks
			for link in self.scan_links(task):
				self.pool.add(link)

			time.sleep(self.delay)

		self.done()

	def scan_links(self, task):
		for link in task.links:
			depth = task.depth

			# ignores URL fragments
			link, fragment = urllib.parse.urldefrag(link)

			# checks if already scanned
			if link in self.links:
				continue

			self.links.add(link)
			parsed = urllib.parse.urlparse(link)

			# checks for query string
			if parsed.query != '':
				link += '?' + parsed.query

				if not self.query:
					self.skip(link, task)
					continue

			# checks if http/s
			if not parsed.scheme in ACCEPT_SCHEMES:
				if not parsed.scheme in IGNORE_SCHEMES:
					self.skip(link, task)

				continue

			if parsed.netloc == self.domain: # internal link
				if self.internal == IGNORE:
					self.skip(link, task)
					continue

				server = INTERNAL
				follow = self.internal == FOLLOW
			else: # external link
				depth += 1

				if self.external == IGNORE or task.depth > self.depth:
					self.skip(link, task)
					continue

				server = EXTERNAL
				follow = self.external == FOLLOW

			# checks link against user-defined rules
			if self.check_rules(link, server):
				self.skip(link, task)
				continue

			yield Task(
				link=link,
				source=task.link,
				depth=depth,
				timeout=self.timeout,
				redirect=self.redirect,
				server=server,
				follow=follow
			)

	def check_rules(self, link, server=INTERNAL):
		for rule in self.rules:
			condition, scope, match = rule

			# checks if rule is for this server type
			if scope != ANY and server != scope:
				continue

			result = re.search(match, link)

			# link must match rule
			if condition == INCLUDE and not result:
				return True
			# link must not match rule
			elif condition == EXCLUDE and result:
				return True

	def pause(self):
		if self.paused is None:
			self.paused = threading.Event()
			self.pool.pause()
		else:
			self.paused.set()
			self.paused = None
			self.pool.resume()

	def stop(self):
		self.stopped = True
		self.pool.pause()

	def tell(self, status, link, source, server, error=None):
		event = ResultEvent(status, link, source, server, error)
		wx.PostEvent(self.parent, event)

	def skip(self, link, task):
		self.tell(SKIPPED, link, task.link, task.server, task.error)

	def error(self, task):
		self.tell(TIMEOUT, task.link, task.source, task.server, task.error)

	def done(self):
		self.tell(COMPLETED, '', '', INTERNAL)

################################################################################
# ResultEvent class                                                            #
################################################################################

class ResultEvent(wx.PyEvent):
	def __init__(self, status, link, source, server, error=None):
		wx.PyEvent.__init__(self)
		self.status = status
		self.link = link
		self.source = source
		self.server = server
		self.error = error

		self.SetEventType(EVT_RESULT_ID)

################################################################################
# Worker class                                                                 #
################################################################################

class Worker(threading.Thread):
	def __init__(self, todo, done):
		super().__init__()
		self.todo = todo
		self.done = done
		self.daemon = True

		self.paused = None

		self.start()

	def run(self):
		while True:
			if self.paused is not None:
				self.paused.wait()

			task = self.todo.get()
			task.run()

			self.done.put(task)
			self.todo.task_done()

	def pause(self):
		self.paused = threading.Event()

	def resume(self):
		self.paused.set()
		self.paused = None

################################################################################
# ThreadPool class                                                             #
################################################################################

class ThreadPool(object):
	def __init__(self, count):
		self.count = count
		self.threads = []

		self.todo = Queue() # pending tasks
		self.done = Queue() # completed tasks

		self.pending = 0

	def add(self, task):
		self.todo.put(task)
		self.pending += 1

	def start(self):
		for n in range(self.count):
			self.threads.append(Worker(self.todo, self.done))

	def pause(self):
		for thread in self.threads:
			thread.pause()

	def resume(self):
		for thread in self.threads:
			thread.resume()

	def wait_for_task(self):
		while True:
			try:
				return self.done.get(block=False)
			except: # gives tasks processor time
				time.sleep(0.1)

	def poll_completed_tasks(self):
		while self.pending > 0:
			yield self.wait_for_task()
			self.pending -= 1

		# completed all tasks
		self.todo.join()

################################################################################
# Task class                                                                   #
################################################################################

class Task():
	def __init__(self, link, source, depth, timeout, redirect, server, follow):
		self.link = link
		self.source = source
		self.depth = depth
		self.timeout = timeout
		self.redirect = redirect
		self.server = server
		self.follow = follow

		self.links = []
		self.status = 0
		self.error = None
		self.redirected = False

	def run(self):
		try:
			original_link = self.link

			# gets head request initially (to avoid downloading every file)
			head_request = requests.head(
				self.link,
				timeout=self.timeout,
				allow_redirects=self.redirect,
				stream=True
			)

			with closing(head_request) as response:
				self.link = response.url # reset in case of redirect
				self.status = response.status_code

				if not self.follow: # not following links
					return

				if self.status >= 400: # error status
					return

				content_type = response.headers.get('Content-Type', '').strip()

				if not content_type.startswith(CONTENT_TYPES):
					return

			# gets full request if content type is HTML
			get_request = requests.get(
				self.link,
				timeout=self.timeout,
				allow_redirects=self.redirect,
				stream=True
			)

			with closing(get_request) as response:
				strainer = SoupStrainer(lambda tag, attr: tag in HTML_TAGS)
				parser = BeautifulSoup(
					response.content,
					'html.parser',
					parse_only=strainer,
					from_encoding=response.encoding
				)

				for tag in parser.find_all('a', href=True):
					link = urllib.parse.urljoin(self.link, tag['href'])
					self.links.append(link)

				for tag in parser.find_all('img', src=True):
					link = urllib.parse.urljoin(self.link, tag['src'])
					self.links.append(link)

				for tag in parser.find_all('link', href=True):
					link = urllib.parse.urljoin(self.link, tag['href'])
					self.links.append(link)

			self.redirected = original_link != self.link
		except Exception as e:
			self.error = e
			return

################################################################################
# Main function                                                                #
################################################################################

def main():
	app = wx.App(False)

	frame = MainFrame()
	frame.Show()
	frame.Center()

	app.MainLoop()

if __name__ == '__main__':
	main()