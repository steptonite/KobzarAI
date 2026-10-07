"""Exercise optional menu routing without starting Cocoa, hotkeys or browsers."""
import ast
from pathlib import Path
from types import SimpleNamespace

src=Path(__file__).resolve().parents[1]/'panel/panel.py'
tree=ast.parse(src.read_text())
helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_browser_chat_menu')
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Panel')
handler=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='open_browser_chats')
ns={}
exec(compile(ast.Module(body=[helper,handler],type_ignores=[]),str(src),'exec'),ns)


def test_optional_menu_absent_and_present():
    ns['_addon']=None
    assert ns['_browser_chat_menu']()==[]
    ns['_addon']=SimpleNamespace(tabs=lambda:[{'key':'unrelated'}])
    assert ns['_browser_chat_menu']()==[]
    ns['_addon']=SimpleNamespace(tabs=lambda:[{'key':'browser'}])
    assert ns['_browser_chat_menu']()==['browser_chats']
    def fail():raise RuntimeError('unavailable')
    ns['_addon']=SimpleNamespace(tabs=fail)
    assert ns['_browser_chat_menu']()==[]


def test_action_selects_addon_index_not_assumed_fifth_tab():
    ns['_addon']=SimpleNamespace(tabs=lambda:[{'key':'browser'}])
    events=[]
    settings=SimpleNamespace(_ext_tab_index=lambda key:7 if key=='browser' else None,
                             show=lambda:events.append('show'),select_tab=events.append)
    panel=SimpleNamespace(_settings=settings)
    ns['open_browser_chats'](panel,None)
    assert events==['show',7]
    ns['_addon']=None
    ns['open_browser_chats'](panel,None)
    assert events==['show',7]


def test_new_settings_window_created_once():
    ns['_addon']=SimpleNamespace(tabs=lambda:[{'key':'browser'}])
    events=[]
    settings=SimpleNamespace(_ext_tab_index=lambda k:4, show=lambda:events.append('show'),select_tab=events.append)
    class Factory:
        def alloc(self):return self
        def initWithPanel_(self,p):events.append('created');return settings
    ns['SettingsWindow']=Factory()
    p=SimpleNamespace(_settings=None)
    ns['open_browser_chats'](p,None);ns['open_browser_chats'](p,None)
    assert events==['created','show',4,'show',4]


def test_menu_item_follows_settings_before_separator():
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    assign=next(n for n in ast.walk(init) if isinstance(n,ast.Assign) and
                any(isinstance(t,ast.Attribute) and t.attr=='menu' for t in n.targets))
    elts=assign.value.elts
    i=next(i for i,n in enumerate(elts) if isinstance(n,ast.Constant) and n.value=='settings')
    assert isinstance(elts[i+1],ast.Starred) and elts[i+2].value is None
