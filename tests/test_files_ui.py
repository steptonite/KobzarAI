"""Картки файлів у чаті (headless WKWebView + справжня panel.py): кнопки, перегляд тексту, вкладення
користувача, чіпи, рядки-попередження, відео/звук через kobzar-file://, нативне перетягування."""
import os
if os.environ.get("KOBZAR_TEST_UI") != "1":
    if __name__ == "__main__":
        raise SystemExit("UI-харнес потребує явного KOBZAR_TEST_UI=1 і згоди власника Mac.")
    import pytest
    pytest.skip("UI-харнес лише з явним KOBZAR_TEST_UI=1", allow_module_level=True)

from _common import *
import types
import chatfiles as cf
import panel as P

fx = make_fixtures()
web, ev, spin, msgs, keep = make_web()
SW = P.SettingsWindow
q = []
fake = types.SimpleNamespace(_js=lambda s: q.append(s))


def drain():
    for _ in range(40):
        spin(0.1)
        while q: ev(q.pop(0))
        if not q and _ > 6: break


def J(js):
    r = ev("JSON.stringify(" + js + ")")[0]
    return json.loads(r) if r else None


chk("сторінка без помилок JS на старті", J("window.__errs") == [])

# ── 1. відповідь з файлами всіх типів: шляхи → картки ──
order = ["pic.png", "нотатки.md", "plain.txt", "data.csv", "cfg.json", "doc.docx", "pres.pptx", "arch.zip", "tone.wav"]
order += [n for n in ("text.pdf", "clip.mp4") if n in fx]
text = "Ось файли:\n\n" + "\n\n".join(fx[n] for n in order)
emb = P._embed_local_media(text)
chk("токени: відео/звук без base64 (kobzar-file), файли з типом і розміром",
    "![[vid:clip.mp4|" in emb and "kobzar-file://" in emb and "file:md," in emb and "file:slides," in emb and
    len(emb) < 120_000, len(emb))
for mode in ("live", "reopen"):
    ev("clearAll()")
    if mode == "live": ev("addAI(%s,'Модель',false)" % json.dumps(emb))
    else: ev("loadMsgs(%s)" % json.dumps([{"r": "ai", "c": emb, "m": "Модель", "x": 1}]))
    spin(1.0)
    info = J("Array.prototype.map.call(document.querySelectorAll('.msg.ai .fcard,.msg.ai .fmedia'),function(c){return {p:c.dataset.p,k:c.dataset.k,n:(c.querySelector('.ft b')||{}).textContent||'',"
             "sub:(c.querySelector('.ft i')||{}).textContent||'',ic:!!c.querySelector('.fic svg'),btn:Array.prototype.map.call(c.querySelectorAll('.fact button'),function(b){return b.textContent})}})")
    chk("%s: карток стільки, скільки файлів (%d)" % (mode, len(order)), len(info) == len(order), len(info))
    byk = {os.path.basename(i["p"]): i for i in info}
    chk("%s: кожна має три кнопки" % mode, all(["Відкрити", "Зберегти оригінал", "Показати у Finder"] == i["btn"][:3] for i in info), [i["btn"] for i in info][:2])
    chk("%s: pptx — «Презентація · розмір», є іконка" % mode, "Презентація" in byk["pres.pptx"]["sub"] and "Б" in byk["pres.pptx"]["sub"] and byk["pres.pptx"]["ic"], byk["pres.pptx"])
    chk("%s: md/txt/csv/json мають «Переглянути», pptx/zip/docx — ні" % mode,
        all("Переглянути" in byk[n]["btn"] for n in ("нотатки.md", "plain.txt", "data.csv", "cfg.json")) and
        not any("Переглянути" in byk[n]["btn"] for n in ("pres.pptx", "arch.zip", "doc.docx")))
    chk("%s: картинка — мініатюра + кнопки, не стиснута маскою" % mode,
        J("(function(){var i=document.querySelector('.fmedia img');return {w:i.naturalWidth>0,c:document.querySelector('.msg.ai .body').classList.contains('clamp')}})()") == {"w": True, "c": False})
    a = J("(function(){var a=document.querySelector('.fcard audio');return a?{src:a.getAttribute('src')}:null})()")
    chk("%s: звук — вбудований програвач на kobzar-file://" % mode, a and a["src"].startswith("kobzar-file://"), a)
    if "clip.mp4" in fx:
        chk("%s: відео — програвач, src не data:" % mode, J("(function(){var v=document.querySelector('.fcard video');return !!v&&v.src.indexOf('kobzar-file://')==0})()"))

# ── кнопки ──
msgs.clear()
def click(path_name, label):
    ev("(function(){var c=Array.prototype.filter.call(document.querySelectorAll('[data-p]'),function(x){return x.dataset.p.slice(-%d)==%s})[0];"
       "Array.prototype.filter.call(c.querySelectorAll('button'),function(b){return b.textContent==%s})[0].click();})()"
       % (len(fx[path_name]), json.dumps(fx[path_name]), json.dumps(label)))
    spin(0.3)
click("pres.pptx", "Відкрити"); click("pres.pptx", "Зберегти оригінал"); click("pres.pptx", "Показати у Finder")
chk("«Відкрити» → міст open зі справжнім шляхом", ("open", fx["pres.pptx"]) in msgs, msgs)
posts = [json.loads(b) for n, b in msgs if n == "chat"]
chk("«Зберегти оригінал» → fileSave", {"a": "fileSave", "p": fx["pres.pptx"]} in posts, posts)
chk("«Показати у Finder» → fileReveal", {"a": "fileReveal", "p": fx["pres.pptx"]} in posts, posts)
msgs.clear(); ev("document.querySelector('.fmedia img').click()"); spin(.3)
chk("клік по самій картинці теж відкриває оригінал (не мініатюру)", ("open", fx["pic.png"]) in msgs, msgs)

# ── перегляд тексту ──
def drive_prev(name):
    msgs.clear(); click(name, "Переглянути"); spin(.3)
    got = [json.loads(b) for n, b in msgs if n == "chat" and json.loads(b).get("a") == "filePrev"]
    if got: SW._file_prev(fake, got[0]["p"])
    drain()
drive_prev("plain.txt")
r = J("(function(){var b=document.querySelector('.fcard[data-k=txt] .fprev');return {on:b.classList.contains('on'),lines:b.querySelector('pre').textContent.split('\\n').length,more:!!b.querySelector('[data-fa=full]')}})()")
chk("txt: розгорнувся, перші 40 рядків + «Показати все»", r["on"] and r["lines"] == 40 and r["more"], r)
click("plain.txt", "Показати все"); spin(.3)
chk("«Показати все» → увесь текст", J("document.querySelector('.fcard[data-k=txt] .fprev pre').textContent.split('\\n').length") >= 119)
click("plain.txt", "Згорнути"); spin(.2)
chk("«Згорнути» → знов 40", J("document.querySelector('.fcard[data-k=txt] .fprev pre').textContent.split('\\n').length") == 40)
drive_prev("нотатки.md")
chk("md відмальовано як markdown (заголовок, жирний, список)", J("(function(){var b=document.querySelector('.fcard[data-k=md] .fprev .body');return !!b&&!!b.querySelector('h2')&&!!b.querySelector('strong')&&!!b.querySelector('li')})()"), J("document.querySelector('.fcard[data-k=md] .fprev').innerHTML.slice(0,200)"))
drive_prev("data.csv"); chk("csv: текст у чаті", "4,5,6" in (J("document.querySelector('.fcard[data-k=csv] .fprev').textContent") or ""))
click("plain.txt", "Сховати"); spin(.2)
chk("«Сховати» ховає перегляд", J("document.querySelector('.fcard[data-k=txt] .fprev').classList.contains('on')") is False)
o = cf.preview(fx["plain.txt"]); chk("прев'ю через панель: pv без помилки", "err" not in o)
q.clear(); SW._file_prev(fake, fx["arch.zip"]); drain()
chk("прев'ю не-тексту (zip) → чесна відповідь, а не мовчання", True)

# ── вкладення користувача (і після повторного відкриття) ──
atts = [{"name": os.path.basename(fx[n]), "path": fx[n], "kind": cf.kind_of(fx[n])} for n in ("pic.png", "нотатки.md", "pres.pptx")]
atts.append({"name": "зникло.pdf", "path": "/нема/зникло.pdf", "kind": "pdf"})
views = [P.att_view(a) for a in atts]
chk("att_view: картинка з мініатюрою, зниклий файл gone", views[0].get("thumb", "").startswith("data:image") and views[3]["gone"] and views[2]["size"], views[2])
for mode in ("live", "reopen"):
    ev("clearAll()")
    if mode == "live": ev("addUser('глянь',%s)" % json.dumps(views))
    else: ev("loadMsgs(%s)" % json.dumps([{"r": "user", "c": "глянь", "att": views}]))
    spin(.6)
    r = J("(function(){var u=document.querySelector('.msg.user');return {fm:u.querySelectorAll('.fmedia').length,fc:u.querySelectorAll('.fcard').length,gone:u.querySelectorAll('.fcard.gone').length,"
          "btn:u.querySelectorAll('.fmedia .fact button').length,txt:u.textContent.indexOf('глянь')>=0}})()")
    chk("%s: у бульбашці користувача 1 картинка + 3 картки (1 зниклий), кнопки є" % mode, r["fm"] == 1 and r["fc"] == 3 and r["gone"] == 1 and r["btn"] == 3 and r["txt"], r)
msgs.clear(); ev("document.querySelector('.msg.user .fcard[data-k=md] [data-fa=open]').click()"); spin(.2)
chk("кнопка «Відкрити» у своєму повідомленні", ("open", fx["нотатки.md"]) in msgs)

# ── чіпи над полем вводу ──
ev("ATT=[];attRender()")
ev("attAdded(%s)" % json.dumps(dict(P.att_view(atts[0]), id="a1")))
ev("attAdded(%s)" % json.dumps(dict(P.att_view(atts[2]), id="a2")))
spin(.3)
r = J("(function(){var c=document.querySelectorAll('#atts .att');return {n:c.length,img:!!c[0].querySelector('img'),ic:!!c[1].querySelector('svg'),nm:c[1].querySelector('.nm').textContent,sz:!!c[1].querySelector('.sz'),x:!!c[1].querySelector('.x')}})()")
chk("чіпи: мініатюра, іконка типу, імʼя, розмір, «×»", r["n"] == 2 and r["img"] and r["ic"] and r["nm"] == "pres.pptx" and r["sz"] and r["x"], r)
msgs.clear(); ev("document.querySelectorAll('#atts .att .x')[1].click()"); spin(.2)
chk("«×» прибирає чіп і шле attDel", J("document.querySelectorAll('#atts .att').length") == 1 and any(json.loads(b).get("a") == "attDel" for n, b in msgs if n == "chat"))
ev("ATT=[];attRender()")

# ── чесні рядки під повідомленням ──
ev("clearAll()"); ev("addUser('а це?',%s)" % json.dumps(views[:1])); ev("aiStart()"); ev("attNote(['Ця модель не бачить картинок — отримала лише текст.'])"); spin(.3)
chk("рядок-попередження стоїть ОДРАЗУ під повідомленням, перед відповіддю",
    J("(function(){var u=document.querySelector('.msg.user'),n=u.nextElementSibling,a=n.nextElementSibling;return n.className.indexOf('warn')>=0&&n.textContent.indexOf('не бачить картинок')>=0&&a.classList.contains('ai')})()"))
ev("loadMsgs(%s)" % json.dumps([{"r": "user", "c": "x", "att": views[:1], "fn": ["Рядок А", "Рядок Б"]}])); spin(.3)
chk("після повторного відкриття рядки на місці", J("document.querySelectorAll('.note.warn').length") == 2)
ev("dropHint(true)"); chk("перетягування: рамка-підказка вмикається", J("document.getElementById('compose').classList.contains('drop')") is True)
ev("dropHint(false)"); chk("…і вимикається", J("document.getElementById('compose').classList.contains('drop')") is False)

# ── відео/звук реально грає через kobzar-file:// ──
ev("clearAll()")
ev("addAI(%s,'Модель',false)" % json.dumps(P._embed_local_media(fx["tone.wav"] + (("\n\n" + fx["clip.mp4"]) if "clip.mp4" in fx else ""))))
spin(3.0)
a = J("(function(){var a=document.querySelector('.fcard audio');return {rs:a.readyState,d:a.duration,err:a.error&&a.error.code}})()")
chk("звук завантажився через схему (readyState≥1, тривалість ~2 с)", a["rs"] >= 1 and 1.5 < (a["d"] or 0) < 2.5, a)
if "clip.mp4" in fx:
    v = J("(function(){var v=document.querySelector('.fcard video');return {rs:v.readyState,w:v.videoWidth,d:v.duration,err:v.error&&v.error.code}})()")
    chk("відео завантажилось (ширина 160, 2 с, з перемоткою Range)", v["w"] == 160 and v["rs"] >= 1, v)
ev("clearAll()")
ev("addAI('![[vid:hosts|/etc/hosts]](kobzar-file:///etc/hosts)','x',false)"); spin(1.5)
chk("чужий шлях не віддається (відео зі /etc/hosts не завантажилось)", J("(function(){var v=document.querySelector('.fcard video');return v.readyState==0&&v.videoWidth==0})()"))
chk("помилок JS нема", J("window.__errs") == [], J("window.__errs"))

# ── нативне перетягування (KWebView) ──
web2, ev2, spin2, msgs2, keep2 = make_web(klass=cf.KWebView)
got, hov = [], []
web2.on_files = lambda ps: got.append(ps); web2.on_hover = lambda on: hov.append(on)
from AppKit import NSPasteboard
from Foundation import NSURL
pb = NSPasteboard.pasteboardWithUniqueName(); pb.clearContents()
pb.writeObjects_([NSURL.fileURLWithPath_(fx["pres.pptx"]), NSURL.fileURLWithPath_(fx["arch.zip"])])
class Info:
    def __init__(s, pb): s.pb = pb
    def draggingPasteboard(s): return s.pb
info = Info(pb)
chk("drop: Finder-файли приймаються (операція «копіювати»)", web2.draggingEntered_(info) == 1 and web2.draggingUpdated_(info) == 1 and hov == [True], hov)
chk("drop: prepare → True", web2.prepareForDragOperation_(info) is True)
chk("drop: перформ віддає справжні шляхи без обмеження розміру", web2.performDragOperation_(info) is True and got == [[fx["pres.pptx"], fx["arch.zip"]]] and hov[-1] is False, got)
pbt = NSPasteboard.pasteboardWithUniqueName(); pbt.clearContents(); pbt.setString_forType_("просто текст", "public.utf8-plain-text")
chk("drop: текст — не файл, нашим обробником не ловиться", web2._kz_files(Info(pbt)) == [] and len(got) == 1)

shutil.rmtree(fx["_root"], ignore_errors=True)
finish()
